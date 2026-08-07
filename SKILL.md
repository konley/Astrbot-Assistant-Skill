---
name: astrbot-assistant
description: >-
  AstrBot host ops and plugin engineering assistant (local + remote). Deploy/configure
  AstrBot, NapCat (aiocqhttp) reverse-WS debugging (incl. 405 /ws), diagnose/trace/logs
  on the robot host or via SSH, safe cmd_config edits, OpenAPI/plugin lifecycle
  (direct HTTP local or --via-ssh remote), plugin scaffold + compliance check + personal
  git-identity gate, plugin sync. Trigger when: AstrBot no-reply/errors/load-fail/405,
  NapCat deploy, host ops, plugin create/fix/reload. Optional: systemd status, tunnel
  print/open (remote only), framework source version align, persona/provider fields,
  plugin API cheatsheet + Agent/tools guidance.
cn_name: AstrBot 助手
cn_description: >-
  AstrBot 主机运维与插件工程助手（本地 + 远程）。部署/配置、NapCat 对接与 405 排查、
  本机或 SSH diagnose/trace、安全改配置、OpenAPI/插件生命周期、插件脚手架与合规检查、
  个人 git 身份门禁、插件同步。触发：不回复/报错/加载失败/405、插件开发、主机运维。
  可选：systemd 巡检、隧道命令（远程）、框架源码版本对齐、人格/Provider 配置字段辅助、
  插件 API 速查与 Agent/Tools 指引。
---

# AstrBot 助手

协助 **主机运维 / 排障 / 插件工程** 闭环（支持本地直连与 SSH 远程）。详细 SOP 在 `references/`，可执行能力在 `scripts/`。

**设计哲学**：`SKILL.md` 只放导航 + 硬约束；禁止为一次性任务重写 paramiko/临时脚本。  
**双模式**：`login.config [runtime].mode = auto|local|remote`（可用 `ASTRBOT_RUNTIME_MODE` 覆盖）。

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

## 主机操作执行契约（最高优先级）

完整手册：`references/remote-ops-playbook.md`（含 local/remote 双模式）。

1. 先 `python scripts/ssh-exec.py whoami`；确认 `runtime.mode` / `resolved=local|remote`。失败则停（看 Searched 路径），禁止猜 host。
2. 开局：`ssh-exec.py diagnose`（全面 `--full`）。
3. 不回复：`ssh-exec.py trace --since "30 min ago"`（禁止连开 5 次 log）。
4. 多命令：`ssh-exec.py batch`；禁止临时 paramiko / 临时脚本。
5. 日志：`--profile errors|llm|ws|plugin|wake` 或 `--grep "pat"`（不要 `--grep -i`）。
6. 改 JSON：`scripts/config-tool.py`；长文件：`write --file` / `upload` / `sync-plugin`。
7. WebUI/插件生命周期：
   - **local**：`scripts/astrbot-api.py plugins list|reload ...`（直连 dashboard）
   - **remote**：`scripts/astrbot-api.py --via-ssh plugins list|reload ...`
8. 调用用 **scripts 绝对路径**；cwd 不稳时设 `$env:ASTRBOT_LOGIN_CONFIG` / `$env:ASTRBOT_SKILL_ROOT` / `$env:ASTRBOT_RUNTIME_MODE`。
9. 预置子命令不够时才 `exec "单行"`；交互 `astrbot init` 才用 `invoke_shell_send`。
10. systemd：`ssh-exec.py service status|logs|enable`；`restart/start/stop` 必须用户确认 + `--yes`。
11. 隧道：仅 **remote** 有意义 → `ssh-exec.py tunnel print|open`（不在 argv 嵌入密码）；local 下 whoami/tunnel 会提示已在主机本地。
12. **mode 选择**：skill 在机器人主机 → `local`；在开发机远程排障 → `remote`；不确定 → `auto`。

## 插件开发执行契约（做/改插件时最高优先级）

完整手册：`references/plugin-dev-playbook.md`。

1. 身份：`login.config` 扁平 `[git]`（**只认个人**）。
2. 新建门禁：author → 仓库策略 → logo 三态。
3. 骨架：`plugin-scaffold.py --from-login-config`。
4. 交付前：`plugin-check.py` 无 FAIL；按需 `--bump`。
5. commit/push 前：`git-identity.py check-push`；否则 `fix` 锁 local。
6. 部署：`sync-plugin` + API reload（local 直连 / remote 加 `--via-ssh`）。
7. 禁止：公司 global 账号静默 push；禁止在未版本管理的生产目录里直接改完不提交。
8. 写 API / tool / cron / subagent：先读 `references/api-cheatsheet.md`；Agent 专题再读 `references/agent-tools.md`。
9. 骨架可选生命周期：`plugin-scaffold.py --with-lifecycle`（默认仍最小可用，但默认也带 logger）。
10. **可观测日志（新建/改插件必做）**：`from astrbot.api import logger`；关键路径打 `info/error/exception`；消息带稳定前缀 `[plugin_name]`；禁止用 `print` 当运行信号。交付前处理 `plugin-check` 的 `logger.missing`/`logger.print`（旧插件可暂 WARN）。查日志：`ssh-exec.py log astrbot --profile plugin` 或 `--grep plugin_name`。

## 插件 API / Agent 文档路由（按需，不替代运维契约）

主机排障 **仍走** 上文「主机操作执行契约」。以下仅在做/改插件代码时加载：

| 需求 | 读 |
|------|----|
| 指令/消息/Context/schema 速查 | `references/api-cheatsheet.md` |
| FunctionTool / tool_loop / cron / persona / subagent / Agent hooks | `references/agent-tools.md` |
| Page / WebUI | `references/plugin-page-patterns.md` |
| 机制深读 | `references/source-*.md`（先 `framework check`） |

**两层 hook 不要混**：`@filter.*` 是插件事件层；`BaseAgentRunHooks` 是 Agent 运行层（见 `agent-tools.md` §0）。


## 框架源码缓存与版本对齐（防不兼容代码）

本地 `./AstrBot/`（及 `cache/AstrBot/<ver>/`、`framework-cache.meta.json`）**不是**生产代码，且常与远端运行版本不一致 → 会写出不兼容插件。

**权威流程**见 `references/source-version-align.md`。强制摘要：

1. 依赖框架 API / 查源码前：`python scripts/ssh-exec.py framework check`。
2. `status=mismatch|local_missing`：先 `framework sync --yes`（征得用户同意）对齐 tag/version，再 read/grep。
3. 对齐失败或 runtime 版本未知：以**运行时行为**（日志 / OpenAPI / host site-packages）为准，不要把本地缓存当权威。
4. **禁止修改**本地 `./AstrBot/` 缓存；改插件只改插件项目目录。
5. `references/source-*.md` 是精华小抄，行号可能漂移；以符号/字符串检索 + 对齐后的缓存为准。

## Debug 决策树

**Top 3**：
- 不回复 → `trace` + `debug-handbook.md` §2
- 插件加载失败 → handbook §1 + `log --profile plugin`
- NapCat 405 → handbook §3 + `config-tool.py get platform.0` + `--profile ws`（地址必须带 `/ws`）

其余：`references/debug-handbook.md` §9 决策表。

## 工具入口（scripts/）

**首选统一入口 `astrobot.py`**（薄转发，兼容旧脚本，新人从 QUICKSTART 开始）：

| 统一入口 | 用途 |
|----------|------|
| `astrobot.py ops whoami\|log\|trace\|diagnose\|service\|framework\|sync-plugin…` | 全部主机运维（转发 ssh-exec.py） |
| `astrobot.py api plugins\|chat\|config\|im…` | OpenAPI：插件生命周期 / Chat / IM / 配置（local 直连，remote 加 `--via-ssh`） |
| `astrobot.py config get\|set\|patch\|backup` | 安全改 cmd_config / data/config（转发 config-tool.py） |
| `astrobot.py plugin new\|check` | 脚手架 / 合规（plugin-scaffold.py / plugin-check.py） |
| `astrobot.py git …` | 个人身份门禁（git-identity.py） |
| `astrobot.py doctor` | 只读环境体检 + **config_drift 配置漂移检测** |
| `astrobot.py heal --yes` | **自愈**：服务启动失败且命中 urllib3/requests 依赖损坏 → `uv tool upgrade --reinstall` + 重启 + 验证 |
| `astrobot.py version` | 框架版本 pin 缓存 vs host runtime（= `framework check`） |

**底层脚本（仍可用，被统一入口转发）**：

| 命令 | 用途 |
|------|------|
| `ssh-exec.py service …` | systemd 巡检/enable/logs/restart/heal（restart/heal 需 --yes） |
| `ssh-exec.py tunnel print\|open` | remote：本地端口转发；local：提示不需要 |
| `ssh-exec.py config discover [--write]` | 探测主机布局并建议/回填 login.config [paths]/port |
| `ssh-exec.py framework check\|sync` | 版本 pin 缓存 vs host runtime（禁 latest fallback） |
| `doctor.py` | 只读检查 Python、依赖、runtime、路径、框架缓存和配置漂移 |
| `market-check.py` | 插件元数据、市场 JSON、16MB 发布包检查 |
| `backup-tool.py` | 用户确认后创建本地 AstrBot 数据归档 |

## 路径基线（可配置）

默认生产：`/opt/astrbot`（可用 `login.config [paths]` 覆盖）。  
插件安装：当前默认 `data/plugins/{name}/`；历史实例可能是 `data/addons/plugins/`。`sync-plugin` / `diagnose` 会探测远端真实目录并自动回退；以 `config discover` 与 login.config `[paths].plugins_dir` 为准。
权威表：`references/config-reference.md`。

## login.config

推荐 INI。先定 **`[runtime].mode`**，再填对应段落。

- `ASTRBOT_RUNTIME_MODE=local|remote|auto`
- `ASTRBOT_SSH_PASSWORD` / `ASTRBOT_SSH_IDENTITY` / `ASTRBOT_SSH_ALLOW_AGENT=1`
- `ASTRBOT_LOGIN_CONFIG` / `ASTRBOT_SKILL_ROOT` / `ASTRBOT_API_KEY` / `ASTRBOT_DASH_PORT`

```ini
[runtime]
# auto | local | remote
mode = remote

[ssh]
# mode=remote 时需要
host = 1.2.3.4
port = 22
user = root
# password = ...
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

机器人主机上的最小 local 示例：

```ini
[runtime]
mode = local

[git]
user = yourname
email = you@example.com
github = https://github.com/yourname

[dashboard]
port = 6185
api_key = abk_...

[paths]
astrbot_root = /opt/astrbot
```

缺失时 `init-config` 生成模板。搜索顺序：`--login-config` → env → cwd 向上 → skill 根/父目录。  
**不要把 login.config 提交到 git**。配置文件均应 **UTF-8 无 BOM**。

## 参考文档（按需加载）

| 文件 | 何时读 |
|------|--------|
| `remote-ops-playbook.md` | 任何主机运维问题（local/remote） |
| `plugin-dev-playbook.md` | 做/改插件 |
| `api-cheatsheet.md` | 插件 API / 消息 / Context 速查 |
| `agent-tools.md` | Tool / tool_loop / cron / subagent / Agent hooks |
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
| `QUICKSTART.md` | 维护人最短上手路径（whoami→日志/更新/插件三件事+硬规矩） |
| `modern-runtime.md` | uv/Docker/Compose/当前路径与升级（含更新后 urllib3 自愈） |
| `skills-sandbox-mcp.md` | Runtime Skills、Sandbox、MCP、主动 Agent |
| `backup-recovery.md` | 实例备份与恢复 |

## 硬约束（唯一权威清单）

1. 主机操作只走 `scripts/` CLI；禁止临时 paramiko/sed 改 JSON。  
2. 禁止随意重启：重载 ≫ 重装 ≫ 重启；重启须用户确认 + `service … --yes`。  
3. NapCat 反向 WS 地址必须带 `/ws`。  
4. 插件路径默认 `data/plugins/`（历史实例可回退 `data/addons/plugins/`，以 host 探测/`config discover` 为准）；插件配置在 `data/config/`，持久化数据在 `data/plugin_data/`；网络用异步 aiohttp/httpx。
5. git 只认 login.config 个人身份；交付 `plugin-check` 无 FAIL。  
6. 带 Page：先读 `plugin-page-patterns.md`（iframe 沙箱限制）。  
7. 改插件优先在 git 项目目录；再 `sync-plugin` 到运行目录（local 也不要只改生产目录不提交）。  
8. 依赖框架 API 前必须 `framework check`；版本不一致先对齐；`api-cheatsheet`/`agent-tools` 是速查，不是 runtime 权威。  
9. `_conf_schema.json` type 以 `source-config-schema.md` 为准；当前支持 `string/text/int/float/bool/list/object/dict/template_list/file`，使用 `options`，不使用 `choices` 或 `type: select`。
10. 生成代码提交前 ruff 格式化。
11. 插件运行信号必须走 `astrbot.api.logger`（带 `[plugin_name]` 前缀），禁止 `print` 充当运维日志；脚手架默认已带，改插件时也要补齐。
12. 先 `whoami` 确认 `resolved=local|remote`；local 不需要 SSH/paramiko；remote 才要求 `[ssh]`。
13. `--via-ssh` 与 local 模式冲突时必须停止，不得静默改为本地目标。
14. 插件 install/update/uninstall/on/off 与服务状态改变必须显式 `--yes`。
15. **skill 仓库只放 skill 自身文件**：禁止把插件源码/第三方项目（含 clone、开发副本、`astrbot_plugin_*` 目录）放进 skill 根目录或子目录；插件源码在独立 git 项目，运行目录在 `data/plugins/`。误入即清理（skill 内出现 `astrbot_plugin_*` 未跟踪目录视为违规）。

> references 内不再重复展开上述清单，只引用「硬约束 #N」。

## 适配器键（support_platforms）

aiocqhttp · qq_official · qq_official_webhook · telegram · wecom · wecom_ai_bot · lark · dingtalk · discord · slack · kook · vocechat · weixin_official_account · weixin_oc · satori · misskey · line · matrix · mattermost

## Skill 维护

若通过 Junction 挂到 `~/.codex/skills/astrbot-assistant`，git 操作请在真实路径 `Astrbot-Assistant-Skill/` 进行。
