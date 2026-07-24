# AstrBot Assistant Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-Skill-blue)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://www.python.org/)

面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的全流程助手 Skill：部署、远程运维、排障、插件开发与合规检查，一套 CLI + 手册打通。

> **给谁用**
>
> - **人**：安装 Skill、写 `login.config`、用 `assets/` 工具排查与同步
> - **AI Agent**（Codex / OpenCode 等）：读 [`SKILL.md`](./SKILL.md) 的硬约束与导航，按 `references/` 执行 SOP

仓库：[konley/Astrbot-Assistant-Skill](https://github.com/konley/Astrbot-Assistant-Skill)

---

## 能做什么

| 场景 | 你能得到什么 |
|------|-------------|
| **从零部署** | AstrBot（uv）+ NapCat 对接、systemd 保活、路径与配置基线 |
| **远程运维** | 一键诊断、日志/消息流追踪、配置读写、插件同步，全部走封装 CLI |
| **日常排障** | 不回复、加载失败、405、LLM、会话锁等 8 类场景手册 |
| **插件开发** | 自然语言 → 合规脚手架；metadata 检查、升版、个人 git 身份门禁 |
| **OpenAPI** | 经 SSH 隧道调用 WebUI/OpenAPI（dashboard 仅监听 127.0.0.1 时也能用） |

设计原则（与 `SKILL.md` 一致）：

1. **导航与硬约束在 `SKILL.md`**，细节 SOP 在 `references/`，按需打开，不堆在一个文件里。
2. **高频操作一律走 `assets/` CLI**，禁止为一次性任务临时写 paramiko / 拼 SSH 脚本。
3. **插件业务代码只在本地改**，用 `sync-plugin` 同步到远端；SSH 负责日志、配置、验证。

---

## 快速开始

### 1. 安装为 Skill

把本仓库放到 Agent 的 skills 目录（名称建议 `astrbot-assistant`）：

| 环境 | 示例路径 |
|------|----------|
| Codex | `~/.codex/skills/astrbot-assistant`（可用 Junction / 符号链接指到本仓库） |
| OpenCode | `.opencode/skills/astrbot-assistant/` |

**不要**在 Junction / 链接路径上做 `git add/commit/push`；提交请在真实仓库目录操作。

本机依赖：**Python 3.10+**（推荐 3.12），能跑 `assets/*.py` 即可。远程侧部署要求见 [`references/deploy-guide.md`](./references/deploy-guide.md)。

### 2. 配置 `login.config`

远程操作与插件作者信息都读这个文件。标准格式为 **INI**（也兼容 JSON / 旧格式）：

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

# 可选：Dashboard / OpenAPI（astrbot-api.py 使用）
# [dashboard]
# port = 6185
# api_key = your-token
```

生成模板：

```powershell
python assets/ssh-exec.py init-config
# 可选：python assets/ssh-exec.py init-config --format json
```

搜索顺序：`--login-config` → 环境变量 `ASTRBOT_LOGIN_CONFIG` → 从当前目录向上查找 → skill 根 / 父目录。  
字段与路径权威说明：[`references/config-reference.md`](./references/config-reference.md)。

### 3. 验证连通并诊断

在 PowerShell 中（把 `$SKILL` 换成你的仓库路径）：

```powershell
$SKILL = "C:\path\to\Astrbot-Assistant-Skill"
$A = Join-Path $SKILL "assets"
# 可选：固定凭据
# $env:ASTRBOT_LOGIN_CONFIG = "C:\path\to\login.config"

python "$A\ssh-exec.py" whoami
python "$A\ssh-exec.py" diagnose --full
```

- `whoami` 失败会打印已搜索的配置路径，**不要猜 host**。
- 机器人不回复时优先：`python "$A\ssh-exec.py" trace --since "30 min ago"`。

---

## 常用工作流

### 远程排障

```powershell
python "$A\ssh-exec.py" diagnose --full
python "$A\ssh-exec.py" trace --since "30 min ago"
python "$A\ssh-exec.py" log astrbot --profile errors
python "$A\ssh-exec.py" log astrbot --profile plugin --since "1 hour ago"
```

| 症状 | 优先动作 |
|------|----------|
| 不回复 / @ 没用 | `trace` + [`debug-handbook.md`](./references/debug-handbook.md) §2 |
| 插件加载失败 | `log astrbot --profile plugin` + handbook §1 |
| NapCat 405 / 掉线 | `config-tool.py get platform.0` + `--profile ws` + handbook §3 |

多条远端命令用 `batch`（单连接）；改 `cmd_config.json` 用 `config-tool.py`，不要手写 sed / 拼 JSON。

完整契约：[`references/remote-ops-playbook.md`](./references/remote-ops-playbook.md)。

### 插件：新建 → 检查 → 同步 → 重载

```powershell
# 1. 脚手架（author / github 来自 login.config）
python "$A\plugin-scaffold.py" --from-login-config --repo auto

# 2. 合规检查（交付前必须无 FAIL）
python "$A\plugin-check.py" <plugin_dir>

# 3. 提交前锁定个人 git 身份（禁止静默用公司 global 账号）
python "$A\git-identity.py" check-push --repo <plugin_dir>
# 不一致时：
python "$A\git-identity.py" fix --repo <plugin_dir>

# 4. 本地改完同步 + 远端重载（不要在 SSH 里改业务代码）
python "$A\ssh-exec.py" sync-plugin <plugin_dir>
python "$A\astrbot-api.py" --via-ssh plugins reload
```

完整 SOP：[`references/plugin-dev-playbook.md`](./references/plugin-dev-playbook.md)。  
写带 Web Page 的插件前必读：[`references/plugin-page-patterns.md`](./references/plugin-page-patterns.md)。

### 查框架源码（debug 深入机制）

源码缓存目录为 skill 根下的 `AstrBot/`（`.gitignore` 已忽略，不污染业务仓库）：

```powershell
# 不存在时浅克隆一次
git clone --depth 1 https://github.com/AstrBotDevs/AstrBot "$SKILL\AstrBot"
```

本地缓存**只读参考**，禁止当真实线上代码改。消息流 / 插件机制 / 配置 schema 的精华见 `references/source-*.md`。

---

## 目录结构

```
Astrbot-Assistant-Skill/
├── SKILL.md                          # Agent 入口：导航 + 硬约束（必读）
├── README.md                         # 本文件：给人看的安装与用法
├── LICENSE
├── assets/                           # 可执行 CLI / 模板（优先绝对路径调用）
│   ├── _common.py                    # 公共库（login.config / SSH / 路径）
│   ├── ssh-exec.py                   # 远程：诊断 / 日志 / 同步 / 传输
│   ├── config-tool.py                # cmd_config.json 安全读写
│   ├── astrbot-api.py                # WebUI / OpenAPI（支持 --via-ssh）
│   ├── plugin-scaffold.py            # 插件脚手架
│   ├── plugin-check.py               # 合规检查与升版
│   ├── git-identity.py               # 个人 git 身份锁定
│   ├── logo-process.py               # Logo 处理
│   ├── tunnel-generator.html         # SSH 隧道可视化
│   ├── *.template                    # metadata / 依赖 / 测试模板
│   └── dev-commands.txt              # 开发常用命令备忘
├── references/                       # 按需加载的 SOP / 手册
│   ├── remote-ops-playbook.md        # 远程作战手册（最高优先级）
│   ├── plugin-dev-playbook.md        # 插件开发主路径
│   ├── debug-handbook.md             # 8 类场景 debug
│   ├── deploy-guide.md               # AstrBot + NapCat 部署
│   ├── config-reference.md           # 路径与 login.config 权威表
│   ├── plugin-lifecycle.md           # 重载 / 重装 / 重启优先级
│   ├── plugin-new-checklist.md       # 新插件官方清单
│   ├── plugin-page-patterns.md       # Plugin Page 沙箱与桥接模式
│   ├── compliance-checklist.md       # 合规 + 需求解析 + 测试
│   ├── openapi-integration.md        # OpenAPI 鉴权与调用
│   ├── troubleshooting.md            # 边缘案例
│   ├── source-message-flow.md        # 消息流源码精华
│   ├── source-plugin-internals.md    # 插件加载 / 重载机制
│   └── source-config-schema.md       # 配置 schema 权威详解
└── AstrBot/                          # 可选：框架源码浅克隆缓存（gitignore）
```

---

## 工具速查

| 命令 | 用途 |
|------|------|
| `ssh-exec.py whoami` | 校验 login.config 与 SSH |
| `ssh-exec.py diagnose [--full]` | 服务 / 端口 / 近期错误一键看 |
| `ssh-exec.py trace [--since ...]` | 消息流 5 步追踪（不回复首选） |
| `ssh-exec.py log … --profile errors\|llm\|ws\|plugin\|wake` | 结构化日志过滤 |
| `ssh-exec.py sync-plugin <dir>` | 本地插件 → 远端安装目录 |
| `ssh-exec.py batch "c1" "c2"` | 单连接批量远端命令 |
| `config-tool.py get\|set …` | 改 `cmd_config.json` |
| `astrbot-api.py --via-ssh …` | 插件 list / reload / install 等 |
| `plugin-scaffold.py --from-login-config` | 生成合规插件骨架 |
| `plugin-check.py <dir> [--bump …]` | 交付前检查 / 升版 |
| `git-identity.py check-push\|fix` | push 前个人身份门禁 |

更多子命令：`python assets/<tool>.py -h`。

---

## 硬约束摘要（人与 Agent 都适用）

1. **远程只走封装 CLI**：`ssh-exec.py` / `config-tool.py` / `astrbot-api.py --via-ssh`。
2. **禁止随意重启机器人**：重载 ≫ 重新安装 ≫ 重启；重启须用户确认。
3. **NapCat 反向 WebSocket 地址必须带 `/ws`**，否则 405。
4. **插件路径**是 `data/addons/plugins/{name}/`（不是历史路径 `data/plugins/`）。
5. **git 只认 `login.config` 的个人身份**；交付前 `plugin-check` 无 FAIL，push 前 `git-identity check-push`。
6. 详细约束与决策树见 **[`SKILL.md`](./SKILL.md)**，不要只靠本 README 推断 Agent 行为。

---

## 文档地图

| 你想… | 打开 |
|------|------|
| 远程排障 / 同步 / Windows 调用约定 | [`remote-ops-playbook.md`](./references/remote-ops-playbook.md) |
| 做 / 改插件全流程 | [`plugin-dev-playbook.md`](./references/plugin-dev-playbook.md) |
| 8 类 debug 场景 | [`debug-handbook.md`](./references/debug-handbook.md) |
| 从零部署 AstrBot + NapCat | [`deploy-guide.md`](./references/deploy-guide.md) |
| 路径、配置、login.config 权威表 | [`config-reference.md`](./references/config-reference.md) |
| Plugin Page（iframe / 上传 / bridge） | [`plugin-page-patterns.md`](./references/plugin-page-patterns.md) |
| OpenAPI 鉴权与 `--via-ssh` | [`openapi-integration.md`](./references/openapi-integration.md) |

---

## 相关链接

- [AstrBot 官方文档](https://docs.astrbot.app/)
- [插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [OpenAPI（Scalar）](https://docs.astrbot.app/scalar.html)
- [AstrBot GitHub](https://github.com/AstrBotDevs/AstrBot)

---

## License

[MIT](./LICENSE)
