---
name: astrbot-assistant
description: >-
  AstrBot remote ops and plugin engineering assistant. Deploy/configure AstrBot,
  NapCat (aiocqhttp) reverse-WS debugging (incl. 405 /ws), SSH diagnose/trace/logs,
  safe cmd_config edits, OpenAPI/plugin lifecycle via --via-ssh, plugin scaffold +
  compliance check + personal git-identity gate, local→remote plugin sync.
  Trigger when: AstrBot no-reply/errors/load-fail/405, NapCat deploy, remote ops,
  plugin create/fix/reload. Optional helpers: systemd service status, SSH tunnel
  print/open, framework source version align, persona/provider config fields.
cn_name: AstrBot 助手
cn_description: >-
  AstrBot 远程运维与插件工程助手。部署/配置、NapCat 对接与 405 排查、SSH diagnose/trace、
  安全改配置、OpenAPI/插件生命周期、插件脚手架与合规检查、个人 git 身份门禁、插件同步。
  触发：不回复/报错/加载失败/405、插件开发、远程运维。可选：systemd 巡检、隧道命令、
  框架源码版本对齐、人格/Provider 配置字段辅助。
---

# AstrBot 助手

协助 **远程运维 / 排障 / 插件工程** 闭环。详细 SOP 在 `references/`，可执行能力在 `scripts/`。

**设计哲学**：`SKILL.md` 只放导航 + 硬约束；禁止为一次性任务重写 paramiko/临时脚本。

**目录约定**：
- `scripts/` — CLI 工具（首选）
- `assets/` — 模板 / 静态资源；`assets/*.py` 仅为兼容 shim（会告警）
- `references/` — 按需加载 SOP
- `./AstrBot/` — 框架源码缓存（gitignore，**只读参考**，须与远端版本对齐）

## When NOT to use

- 与 AstrBot / NapCat / 其插件无关的通用编程问题
- 只需阅读官方文档、不涉及本机/远端实例
- 无 `login.config` 且用户明确只要本地纯代码讨论（可只读 references，不要硬 SSH）
- 非本 skill 管理的其它机器人框架

## 远程操作执行契约（最高优先级）

完整手册：`references/remote-ops-playbook.md`。

1. 先 `python scripts/ssh-exec.py whoami`；失败则停（看 Searched 路径），禁止猜 host。
2. 开局：`ssh-exec.py diagnose`（全面 `--full`）。
3. 不回复：`ssh-exec.py trace --since "30 min ago"`（禁止连开 5 次 log）。
4. 多命令：`ssh-exec.py batch`；禁止临时 paramiko 脚本。
5. 日志：`--profile errors|llm|ws|plugin|wake` 或 `--grep "pat"`（不要 `--grep -i`）。
6. 改 JSON：`scripts/config-tool.py`；长文件：`write --file` / `upload` / `sync-plugin`。
7. WebUI/插件生命周期：`scripts/astrbot-api.py --via-ssh`。
8. 调用用 **scripts 绝对路径**；cwd 不稳时设 `$env:ASTRBOT_LOGIN_CONFIG` / `$env:ASTRBOT_SKILL_ROOT`。
9. 预置子命令不够时才 `exec "单行"`；交互 `astrbot init` 才用 `invoke_shell_send`。
10. systemd：`ssh-exec.py service status|logs|enable`；`restart/start/stop` 必须用户确认 + `--yes`。
11. 隧道：`ssh-exec.py tunnel print|open`（不在 argv 嵌入密码）；HTML 生成器仅备用。

## 插件开发执行契约（做/改插件时最高优先级）

完整手册：`references/plugin-dev-playbook.md`。

1. 身份：`login.config` 扁平 `[git]`（**只认个人**）。
2. 新建门禁：author → 仓库策略 → logo 三态。
3. 骨架：`plugin-scaffold.py --from-login-config`。
4. 交付前：`plugin-check.py` 无 FAIL；按需 `--bump`。
5. commit/push 前：`git-identity.py check-push`；否则 `fix` 锁 local。
6. 部署：`sync-plugin` + `astrbot-api.py --via-ssh plugins reload`。
7. 禁止：公司 global 账号静默 push；禁止 SSH 里改业务源码。

## 框架源码缓存与版本对齐（防不兼容代码）

本地 `./AstrBot/`（及 `cache/AstrBot/<ver>/`、`framework-cache.meta.json`）**不是**生产代码，且常与远端运行版本不一致 → 会写出不兼容插件。

**权威流程**见 `references/source-version-align.md`。强制摘要：

1. 依赖框架 API / 查源码前：`python scripts/ssh-exec.py framework check`。
2. `status=mismatch|local_missing`：先 `framework sync --yes`（征得用户同意）对齐 tag/version，再 read/grep。
3. 对齐失败或远端版本未知：以**远端运行时行为**（日志 / OpenAPI / 远端 site-packages）为准，不要把本地缓存当权威。
4. **禁止修改**本地 `./AstrBot/` 缓存；改插件只改插件项目目录。
5. `references/source-*.md` 是精华小抄，行号可能漂移；以符号/字符串检索 + 对齐后的缓存为准。

## Debug 决策树

**Top 3**：
- 不回复 → `trace` + `debug-handbook.md` §2
- 插件加载失败 → handbook §1 + `log --profile plugin`
- NapCat 405 → handbook §3 + `config-tool.py get platform.0` + `--profile ws`（地址必须带 `/ws`）

其余：`references/debug-handbook.md` §9 决策表。

## 工具入口（scripts/）

| 命令 | 用途 |
|------|------|
| `ssh-exec.py whoami` | 校验凭据/路径/鉴权方式 |
| `ssh-exec.py diagnose [--full]` | 开局体检（含远端版本探测） |
| `ssh-exec.py trace` | 消息流 5 步 |
| `ssh-exec.py service …` | systemd 巡检/enable/logs（restart 需 --yes） |
| `ssh-exec.py tunnel print\|open` | 本地端口转发命令/拉起 |
| `ssh-exec.py framework check\|sync` | 版本 pin 缓存 vs 远端 runtime（禁 latest fallback） |
| `ssh-exec.py config discover [--write]` | 探测远端布局并建议/回填 login.config [paths]/port |
| `ssh-exec.py sync-plugin` | 插件同步到 `[paths].plugins_dir` |
| `config-tool.py` | 安全改 cmd_config / plugin_configs |
| `astrbot-api.py --via-ssh` | 插件 list/reload/install 等 |
| `plugin-scaffold.py` / `plugin-check.py` | 脚手架 / 合规 |
| `git-identity.py` | 个人身份门禁 |

## 路径基线（可配置）

默认生产：`/opt/astrbot`（可用 `login.config [paths]` 覆盖）。  
插件安装：`data/addons/plugins/{name}/`（**非**历史 `data/plugins/`）。  
权威表：`references/config-reference.md`。

## login.config

推荐 INI。`[ssh]` 支持 **password 和/或 identity_file / allow_agent**；敏感字段可用环境变量：

- `ASTRBOT_SSH_PASSWORD` / `ASTRBOT_SSH_IDENTITY` / `ASTRBOT_SSH_ALLOW_AGENT=1`
- `ASTRBOT_LOGIN_CONFIG` / `ASTRBOT_SKILL_ROOT` / `ASTRBOT_API_KEY` / `ASTRBOT_DASH_PORT`

```ini
[ssh]
host = 1.2.3.4
port = 22
user = root
# password = ...                 # 或改用下方私钥
# identity_file = ~/.ssh/id_ed25519
# allow_agent = false

[git]
user = yourname
email = you@example.com
github = https://github.com/yourname

[dashboard]
port = 6185
api_key =

[paths]
# astrbot_root = /opt/astrbot
# astrbot_unit = astrbot
```

缺失时 `init-config` 生成模板。搜索顺序：`--login-config` → env → cwd 向上 → skill 根/父目录。  
**不要把 login.config 提交到 git**。本地/远端配置文件均应 **UTF-8 无 BOM**。

## 参考文档（按需加载）

| 文件 | 何时读 |
|------|--------|
| `remote-ops-playbook.md` | 任何远程问题 |
| `plugin-dev-playbook.md` | 做/改插件 |
| `debug-handbook.md` | 8 类故障 |
| `source-version-align.md` | 查框架源码 / 写依赖 API 的代码前 |
| `source-message-flow.md` / `source-plugin-internals.md` / `source-config-schema.md` | 机制精读（先对齐版本） |
| `plugin-page-patterns.md` | 带 Page 的插件（必读） |
| `plugin-lifecycle.md` | 重载/重装/重启优先级 |
| `config-reference.md` | 路径与 login.config 权威表 |
| `deploy-guide.md` | 从零安装 |
| `openapi-integration.md` | API 鉴权 |
| `compliance-checklist.md` | 交付合规 |
| `troubleshooting.md` | 边缘案例 |

## 硬约束（唯一权威清单）

1. 远程只走 `scripts/` CLI；禁止临时 paramiko/sed 改 JSON。  
2. 禁止随意重启：重载 ≫ 重装 ≫ 重启；重启须用户确认 + `service … --yes`。  
3. NapCat 反向 WS 地址必须带 `/ws`。  
4. 插件路径 `data/addons/plugins/`；持久化 `data/plugin_data/`；网络用异步 aiohttp/httpx。  
5. git 只认 login.config 个人身份；交付 `plugin-check` 无 FAIL。  
6. 带 Page：先读 `plugin-page-patterns.md`（iframe 沙箱限制）。  
7. 改插件只在本地项目目录；同步用 `sync-plugin`。  
8. 依赖框架 API 前必须 `framework check`；版本不一致先对齐。  
9. `_conf_schema.json` type 以 `source-config-schema.md` 为准（无 `choices`/`select`）。  
10. 生成代码提交前 ruff 格式化。

> references 内不再重复展开上述清单，只引用「硬约束 #N」。

## 适配器键（support_platforms）

aiocqhttp · qq_official · telegram · wecom · lark · dingtalk · discord · slack · kook · vocechat · weixin_official_account · satori · misskey · line

## Skill 维护

若通过 Junction 挂到 `~/.codex/skills/astrbot-assistant`，git 操作请在真实路径 `Astrbot-Assistant-Skill/` 进行。
