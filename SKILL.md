---
name: astrbot-assistant
description: >-
  AstrBot 全流程助手。部署、配置、管理 AstrBot，NapCat QQ 适配器对接，
  插件开发脚手架生成与合规检查，插件修复，systemd 保活，日志 debug，
  会话锁排查，LLM/Provider 配置，AI 人格生成，SSH 隧道管理，OpenAPI 集成。
  触发：AstrBot 报错/不回复/加载失败/405、插件开发、NapCat 部署、远程运维时使用。
cn_name: AstrBot 助手
cn_description: >-
  AstrBot 全流程助手。部署、安装、配置、管理 AstrBot，NapCat 对接，插件开发脚手架与合规检查，
  插件修复，systemd 保活，日志 debug，会话锁排查，LLM 配置，AI 人格生成，SSH 隧道，OpenAPI 集成。
---

# AstrBot 助手

协助部署、配置、管理 AstrBot 聊天机器人框架，debug 运行时问题，并从自然语言需求生成合规插件。

**设计哲学**：本文件只承载导航和硬约束，详细 SOP 在 `references/` 下按需加载。高频操作已封装为 `assets/` 下的 CLI 工具，禁止从头造轮子。

## 源码查询（debug / 深入机制时）

查 AstrBot 框架源码时按此顺序，**不要 webfetch**。源码缓存**统一放在本 skill 所在目录下的 `./AstrBot/`**（相对路径，相对于 SKILL.md；跟着 skill 走，不污染用户工作区，跨 IDE 通用）：

1. 先定位本 skill 目录（SKILL.md 所在目录），检查其下 `AstrBot/` 是否存在且非空。
2. 不存在则浅克隆到该目录：`git clone --depth 1 https://github.com/AstrBotDevs/AstrBot <skill_dir>/AstrBot`。
3. 已存在直接复用，**不要重复 clone**。
4. 用 `read`/`grep` 直接查文件与行号；`references/source-*.md` 的"关键源码定位小抄"可直接作为 read 参数。
5. 怀疑过时 → `git -C <skill_dir>/AstrBot pull --ff-only`（征得用户同意）。
6. 仅当 clone 失败 → webfetch `raw.githubusercontent.com` 单文件兜底。

> ⚠️ **本地源码仅供查询参考，不是真实项目**。真实 AstrBot 服务运行在远程服务器（见路径基线）。**禁止修改本地缓存的源码文件**——它只是参考副本。要改插件代码，改本地插件项目目录，用 `ssh-exec.py upload` 同步到服务器。

## Debug 决策树（最高频场景，先看这里）

**Top 3（命中直接跳）**：
- 机器人不回复 / 没反应 / @没用 → `references/debug-handbook.md` §2 + `ssh-exec.py log astrbot --grep "session lock|completion"`
- 插件加载失败 / 装不上 / YAML / import → §1 + `ssh-exec.py log astrbot --grep "error"`
- NapCat 405 / 连不上 / 掉线 → §3 + `config-tool.py get platform.0`

**其余场景 → 平铺映射**（症状 → 文件章节）：

| 症状 | 跳到 |
|---|---|
| LLM 调用失败 / 401 / 403 / 推理泄漏 | `debug-handbook.md` §4 |
| 配置改完起不来 / JSON 错 / BOM | §5 |
| /指令不响应 / @判定 | §6 |
| API 鉴权失败 | §7 |
| 卡 / 慢 / 内存爆 | §8 |
| 一键三步开局 | `ssh-exec.py diagnose` |

所有 debug 默认先跑 `ssh-exec.py diagnose`（一次连接完成：服务状态 + 端口 + 近期 error 日志），缩小范围后再按上表深入。完整手册 `references/debug-handbook.md`；边缘案例 `references/troubleshooting.md`。

## 工具链（assets/，禁止从头造轮子）

| 工具 | 用途 | 常用入口 |
|---|---|---|
| `_common.py` | SSH 基座：login.config 解析 + connect + exec + SFTP | `from _common import load_credentials, connect, exec_command` |
| `ssh-exec.py` | SSH/SFTP/查日志 CLI | `exec` / `tail` / `log` / `diagnose` / `upload` / `cat` / `write` |
| `astrbot-api.py` | WebUI/OpenAPI HTTP CLI（不需 SSH） | `plugins list/reload/install` / `config get` / `bots` |
| `config-tool.py` | cmd_config.json 读写（parse→modify→dump） | `show`/`get`/`set`/`patch`/`backup`；`--plugin <name>` 操作插件配置 |
| `plugin-scaffold.py` | 插件骨架生成 | `--name ... --desc ... --author ...` |
| `logo-process.py` | Logo 转 256×256 PNG | `logo-process.py <图片路径>` |

**硬规则**（违反即浪费 token）：

1. SSH/SFTP/查日志必须用 `ssh-exec.py`；需要复用连接逻辑时 import `_common.py`，**禁止从头写 paramiko 脚本**。
2. 改 JSON 必须用 `config-tool.py`（parse→modify→dump，**绝不 sed**）。
3. 生成新插件必须用 `plugin-scaffold.py`，再用 Edit 填业务逻辑。
4. 调 WebUI API 必须用 `astrbot-api.py`，不要从头写 curl。
5. 例外：`astrbot init` 交互式 Y/n 可写最小 paramiko 片段，但必须 import `_common.py` 的 `parse_login_config` / `connect`。

详细用法见各工具 `--help` 与 `references/debug-handbook.md` §0。dashboard 仅监听 127.0.0.1 时，`astrbot-api.py` 需先建 SSH 隧道，或直接用 `ssh-exec.py exec "curl ..."`。

## 路径基线

权威表见 `references/config-reference.md`。速记：生产 `/opt/astrbot/data/`，插件安装 `data/addons/plugins/{name}/`（**非** `data/plugins/`），插件配置 `data/plugin_configs/{name}.json`，持久化数据 `data/plugin_data/{name}/`。

## login.config 凭据

格式与解析见 `references/config-reference.md` 与 `assets/_common.py` 的 `parse_login_config`（唯一实现）。检测到 `login.config` 直接读，**不询问用户凭据**，只需确认"要帮你远程操作吗？"；第 4 行 GitHub 链接用于自动填充插件 `metadata.yaml` 的 `repo` 字段。

## 参考文档（按需加载）

| 文件 | 覆盖 |
|---|---|
| `references/debug-handbook.md` | **debug 手册**（8 类场景 + 快速决策表 + 三步法 + 命令小抄） |
| `references/source-message-flow.md` | 消息流源码精华（收事件→唤醒→指令→LLM→回复） |
| `references/source-plugin-internals.md` | 插件加载/重载/注册内部机制 |
| `references/source-config-schema.md` | cmd_config.json 与 _conf_schema.json 字段**权威**详解 |
| `references/deploy-guide.md` | AstrBot + NapCat 完整部署 |
| `references/troubleshooting.md` | debug-handbook 未覆盖的边缘案例 |
| `references/config-reference.md` | 配置文件路径/字段/login.config **权威**表 |
| `references/plugin-lifecycle.md` | 插件生命周期 SOP：重载/重装/重启优先级 |
| `references/plugin-new-checklist.md` | 新插件官方检查清单：环境、metadata、适配器键、调试 |
| `references/openapi-integration.md` | OpenAPI 端点、鉴权、测试策略（权威端点以 `astrbot-api.py --help` 为准） |
| `references/compliance-checklist.md` | 合规检查 + 需求解析工作流 + 测试要求 |

## 关键硬约束

- **禁止随意重启机器人**：重载 >> 重新安装 >>> 重启。重启必须征得用户确认。详见 `references/plugin-lifecycle.md`。
- 改核心配置（platform/provider/dashboard）后需 restart 才生效，且需用户确认；改插件配置只需 reload。
- NapCat 反向 WebSocket 地址必须带 `/ws`，否则 405。
- `_conf_schema.json` 支持 type：int/float/bool/string/text/list/file/object/template_list；下拉菜单用 `type:"string"+options`，不支持 `choices`/`type:"select"`。详见 `source-config-schema.md` §2。
- 插件持久化数据写 `data/plugin_data/{name}/`，不写源目录；网络请求用异步 aiohttp/httpx，不用 requests。
- 生成代码提交前用 ruff 格式化。
- **修改插件直接本地读/写，绝不走 SSH**：本地有插件源码的就用 `read`/`edit`，不需要 shell、ssh-exec、远程 cat 等。SSH 只用于查远程日志和改远端配置。

## 支持的适配器键（metadata.yaml support_platforms）

aiocqhttp · qq_official · telegram · wecom · lark · dingtalk · discord · slack · kook · vocechat · weixin_official_account · satori · misskey · line

## Skill 文件维护

当需要 git push 时，先检查 `.opencode/skills/{skill-name}/SKILL.md` 是否为符号链接。如果是，用 `cmd /c dir` 查看链接目标（JUNCTION 或 SYMLINK），然后到真实路径下执行 `git add/commit/push`，不要在符号链接位置操作。
