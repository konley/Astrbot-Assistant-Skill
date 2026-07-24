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

## 远程操作执行契约（最高优先级）

完整作战手册：`references/remote-ops-playbook.md`（**远程问题先读**）。

1. 解析 skill 根与 `login.config`：先 `python assets/ssh-exec.py whoami`；失败则停（会打印 Searched 路径），禁止猜 host。
2. 开局：`ssh-exec.py diagnose`（全面用 `--full`）。
3. 不回复：`ssh-exec.py trace --since "30 min ago"`（禁止连开 5 次 log）。
4. 多条远端命令：`ssh-exec.py batch`（单连接）；禁止为一次性任务新建 paramiko/临时 `.py`。
5. 日志过滤用 `--profile errors|llm|ws|plugin|wake` 或 `--grep "pat"`（**不要**写 `--grep -i ...`）。
6. 改 JSON：`config-tool.py`；长文件：`write --file` / `upload` / `sync-plugin`。
7. WebUI/插件生命周期：优先 `astrbot-api.py --via-ssh`（dashboard 仅 127.0.0.1 时必用）。
8. 调用优先 **assets 绝对路径**；cwd 不可靠时设 `$env:ASTRBOT_LOGIN_CONFIG`。
9. 仅当预置子命令无法覆盖时，才允许 `ssh-exec.py exec "单行命令"`；交互式 `astrbot init` 才可用 `_common.invoke_shell_send`。


## 插件开发执行契约（主路径：做/改插件时最高优先级）

完整手册：`references/plugin-dev-playbook.md`（**做插件/改插件先读**）。

1. 身份源：`login.config` 的扁平 `[git] user/email/github`（**个人身份唯一**；不要填公司账号）。
2. 新建门禁（写业务前）：author 取自 login.config → 问仓库策略（已有/新建/fork/none）→ 问 logo 三态（有图/暂无/后补）。
3. 骨架：`plugin-scaffold.py --from-login-config [--repo auto|none|URL]`。
4. 交付/收尾前：`plugin-check.py <dir>` 必须无 FAIL；按改动 `--bump patch|minor|major`（或用户明确不升版）。
5. **任何 git commit/push 前**：`git-identity.py check-push --repo <dir>`；不一致则 `fix --repo <dir>` 把 **local** 锁到 login.config（禁止问“用公司还是个人”，本 skill 只认个人）。
6. 部署：本地迭代用 `sync-plugin` + `astrbot-api.py --via-ssh plugins reload`；发布再 push。
7. 禁止：静默用 global 公司账号推个人插件；禁止 SSH 里改业务源码。

## 源码查询（debug / 深入机制时）

查 AstrBot 框架源码时按此顺序，**不要 webfetch**。源码缓存**统一放在本 skill 所在目录下的 `./AstrBot/`**（相对路径，相对于 SKILL.md；跟着 skill 走，不污染用户工作区，跨 IDE 通用）：

1. 先定位本 skill 目录（SKILL.md 所在目录），检查其下 `AstrBot/` 是否存在且非空。
2. 不存在则浅克隆到该目录：`git clone --depth 1 https://github.com/AstrBotDevs/AstrBot <skill_dir>/AstrBot`。
3. 已存在直接复用，**不要重复 clone**。
4. 用 `read`/`grep` 直接查文件与行号；`references/source-*.md` 的"关键源码定位小抄"可直接作为 read 参数。
5. 怀疑过时 → `git -C <skill_dir>/AstrBot pull --ff-only`（征得用户同意）。
6. 仅当 clone 失败 → webfetch `raw.githubusercontent.com` 单文件兜底。

> ⚠️ **本地源码仅供查询参考，不是真实项目**。真实 AstrBot 服务运行在远程服务器（见路径基线）。**禁止修改本地缓存的源码文件**——它只是参考副本。要改插件代码，改本地插件项目目录，用 `ssh-exec.py sync-plugin` 同步到服务器。

## Debug 决策树（最高频场景，先看这里）

**Top 3（命中直接跳）**：
- 机器人不回复 / 没反应 / @没用 → `ssh-exec.py trace` + `references/debug-handbook.md` §2
- 插件加载失败 / 装不上 / YAML / import → §1 + `log astrbot --profile plugin`
- NapCat 405 / 连不上 / 掉线 → §3 + `config-tool.py get platform.0` + `--profile ws`

**其余场景 → 平铺映射**（症状 → 文件章节）：

| 症状 | 跳到 |
|---|---|
| LLM 调用失败 / 401 / 403 / 推理泄漏 | `debug-handbook.md` §4 |
| 配置改完起不来 / JSON 错 / BOM | §5 |
| /指令不响应 / @判定 | §6 |
| API 鉴权失败 | §7 |
| 卡 / 慢 / 内存爆 | §8 |
| 一键开局 | `ssh-exec.py diagnose --full` |
| 远程怎么查/怎么同步 | `references/remote-ops-playbook.md` |
| 做插件 / 改插件 / push 账号 | `references/plugin-dev-playbook.md` |

所有 debug 默认先跑 `ssh-exec.py diagnose`（可选 `--full`：服务+NapCat+端口+error+插件目录+配置摘要），缩小范围后再按上表深入。完整手册 `references/debug-handbook.md`；边缘案例 `references/troubleshooting.md`。

## 工具链（assets/，禁止从头造轮子）

| 工具 | 用途 | 常用入口 |
|---|---|---|
| `_common.py` | SSH 基座：login.config / connect / exec / batch / SFTP / upload_dir / remote curl | `from _common import load_credentials, connect, exec_command` |
| `ssh-exec.py` | SSH/SFTP/日志/诊断 CLI | `whoami` / `diagnose` / `trace` / `batch` / `log` / `sync-plugin` / `upload-dir` / `write --file` |
| `astrbot-api.py` | WebUI/OpenAPI HTTP CLI；远程用 `--via-ssh` | `plugins list/reload` / `config get` / `bots` |
| `config-tool.py` | 远端 cmd_config.json 安全读写 | `show`/`get`/`set`/`patch`/`backup`；`--plugin <name>` |
| `plugin-scaffold.py` | 插件骨架生成 | `--from-login-config --name ... --desc ...` |
| `plugin-check.py` | 插件合规检查 + version 建议/写入 | `plugin-check.py <dir> [--bump patch]` |
| `git-identity.py` | 锁定 login.config 个人身份 / push 前门禁 | `show` / `status` / `fix` / `check-push` |
| `logo-process.py` | Logo 转 256×256 PNG | `logo-process.py <图片路径>` |

**硬规则**（违反即浪费 token）：

1. SSH/SFTP/查日志必须用 `ssh-exec.py`；需要复用连接逻辑时 import `_common.py`，**禁止从头写 paramiko 脚本**。
2. 改 JSON 必须用 `config-tool.py`（parse→modify→dump，**绝不 sed**）。
3. 生成新插件必须用 `plugin-scaffold.py --from-login-config`，再用 Edit 填业务逻辑；收尾 `plugin-check.py`。
4. 调 WebUI API 必须用 `astrbot-api.py`（远程加 `--via-ssh`），不要从头写 curl/隧道脚本。
5. 例外：`astrbot init` 交互式 Y/n 可写最小片段，但必须 import `_common.py` 的 `parse_login_config` / `connect` / `invoke_shell_send`。

### ssh-exec 速查

```text
whoami                          # skill 根 + 凭据来源 + 远端身份
diagnose [--full] [--json]      # 开局三步；--full 含 napcat/插件/配置摘要
trace [--since ...] [--json]    # 消息流 5 步，单连接
batch "c1" "c2" | --file | --stdin [--json]
log astrbot|napcat --since ... [--grep PAT | --profile errors|llm|ws|plugin|wake]
tail astrbot|napcat [--lines N]
sync-plugin <local_dir> [--name NAME]
upload-dir <local> <remote>
write <remote> --file local | --stdin | "short"
upload|download|cat|ls|exec
```

## 路径基线

权威表见 `references/config-reference.md`。速记：生产 `/opt/astrbot/data/`，插件安装 `data/addons/plugins/{name}/`（**非** `data/plugins/`），插件配置 `data/plugin_configs/{name}.json`，持久化数据 `data/plugin_data/{name}/`。

## login.config 凭据

**标准格式：INI**（推荐，可写注释；含可选 `[dashboard] port/api_key` 供 `astrbot-api`）。也支持 JSON（`login.config.json` 或 `{...}`），旧行位序格式仍兼容。解析唯一实现：`assets/_common.py` 的 `parse_login_config`。

```ini
[ssh]
host = 1.2.3.4
port = 22
user = root
password = secret

[git]
user = yourname
email = you@example.com
github = https://github.com/yourname
```

- 检测到可用配置则直接读，**不询问用户凭据**，只需确认「要帮你远程操作吗？」
- **缺失时自动生成**带注释的 `login.config` 模板，提示用户填写后重试
- 手动生成：`python assets/ssh-exec.py init-config`（`--format json` / `--force`）
- `[git]`：`user`/`email` 用于 commit/push；`github` 用于插件 `metadata.yaml` 的 `repo` 根

搜索顺序：`--login-config` → `$ASTRBOT_LOGIN_CONFIG` → cwd 向上 → skill 根/父目录。可用 `$ASTRBOT_SKILL_ROOT` 固定 skill 根。权威表见 `references/config-reference.md`。

## 参考文档（按需加载）

| 文件 | 覆盖 |
|---|---|
| `references/remote-ops-playbook.md` | **远程作战手册**（契约、trace/batch/sync、Windows 调用） |
| `references/plugin-dev-playbook.md` | **插件开发作战手册**（身份/logo/仓库/收尾/push 门禁） |
| `references/debug-handbook.md` | **debug 手册**（8 类场景 + 快速决策表） |
| `references/source-message-flow.md` | 消息流源码精华（收事件→唤醒→指令→LLM→回复） |
| `references/source-plugin-internals.md` | 插件加载/重载/注册内部机制 |
| `references/source-config-schema.md` | cmd_config.json 与 _conf_schema.json 字段**权威**详解 |
| `references/deploy-guide.md` | AstrBot + NapCat 完整部署 |
| `references/troubleshooting.md` | debug-handbook 未覆盖的边缘案例 |
| `references/config-reference.md` | 配置文件路径/字段/login.config **权威**表 |
| `references/plugin-lifecycle.md` | 插件生命周期 SOP：重载/重装/重启优先级 |
| `references/plugin-new-checklist.md` | 新插件官方检查清单：环境、metadata、适配器键、调试 |
| `references/openapi-integration.md` | OpenAPI 端点、鉴权、`--via-ssh` |
| `references/compliance-checklist.md` | 合规检查 + 需求解析工作流 + 测试要求 |
| `references/plugin-page-patterns.md` | **插件 Page 开发模式**（必读）：沙箱、bridge、上传、路由 |

## 关键硬约束
- 做/改插件走 `plugin-dev-playbook.md`；交付前 `plugin-check.py` 无 FAIL；push 前 `git-identity.py check-push`（不匹配则 `fix` 锁定 local）。

- **禁止随意重启机器人**：重载 >> 重新安装 >>> 重启。重启必须征得用户确认。详见 `references/plugin-lifecycle.md`。
- 改核心配置（platform/provider/dashboard）后需 restart 才生效，且需用户确认；改插件配置只需 reload。
- NapCat 反向 WebSocket 地址必须带 `/ws`，否则 405。
- `_conf_schema.json` 支持 type：int/float/bool/string/text/list/file/object/template_list；下拉菜单用 `type:"string"+options`，不支持 `choices`/`type:"select"`。详见 `source-config-schema.md` §2。
- 插件持久化数据写 `data/plugin_data/{name}/`，不写源目录；网络请求用异步 aiohttp/httpx，不用 requests。
- 生成代码提交前用 ruff 格式化。
- **写带 Page 的插件前必须读 `references/plugin-page-patterns.md`**：Plugin Page 运行在 sandboxed iframe，`confirm()`/`alert()` 不可用，`<img src>` 不带 auth，上传须用 base64+apiPost，详见该文档。
- **修改插件直接本地读/写，绝不走 SSH 编辑业务代码**：本地有源码用 `read`/`edit`；同步用 `sync-plugin`；SSH 用于日志、配置与验证。

## 支持的适配器键（metadata.yaml support_platforms）

aiocqhttp · qq_official · telegram · wecom · lark · dingtalk · discord · slack · kook · vocechat · weixin_official_account · satori · misskey · line

## Skill 文件维护

本 skill 可能通过 Junction/符号链接挂到 Codex skills 目录（如 `~/.codex/skills/astrbot-assistant`）。`git add/commit/push` 时到**真实路径**操作（`Astrbot-Assistant-Skill/`），不要在链接位置误操作。