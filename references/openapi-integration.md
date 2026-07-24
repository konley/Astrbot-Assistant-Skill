# OpenAPI / WebUI 集成

权威命令以 `python assets/astrbot-api.py --help` 为准。

## 这个 key 是干什么的？

Skill 用 Dashboard **API Key**（请求头 `X-API-Key`）调用 AstrBot 的 HTTP API，主要场景：

| 用途 | 命令示例 |
|------|----------|
| 列插件 / 重载 / 安装 / 启停 | `astrbot-api.py --via-ssh plugins list/reload/install/on/off` |
| 读配置 / bots / chat | `config get` / `bots` / `chat` |
| 任意探活 | `raw --method GET --path /api/v1/plugins` |

**不需要** key 的场景：`ssh-exec`、`sync-plugin`、`config-tool`、`git-identity`、纯文件同步。

> 源码事实：API Key 存在 **数据库**（WebUI「API Keys」创建，明文通常 `abk_...`）。
> **不是** `cmd_config.json` 里的 `dashboard.api_key` 静态字段（旧文档说法已废弃）。
> 旧路径 `/api/plugin/*` 走 JWT 中间件，**只认 Bearer/Cookie**；本 CLI 优先 `/api/v1/*`（认 X-API-Key）。

## 鉴权与端口（login.config）

可以（也推荐）在 `login.config` 约定面板端口与 key——你的实例经常不是默认 `6185`：

```ini
[dashboard]
# 远程 AstrBot WebUI 端口（--via-ssh 时对 127.0.0.1 使用）
port = 62124
api_key = abk_你的key
```

解析优先级：

| 项 | 高 → 低 |
|----|---------|
| API Key | `--api-key` → `$ASTRBOT_API_KEY` → `login.config [dashboard].api_key` |
| Dashboard 端口（`--via-ssh`） | `--dash-port` → `$ASTRBOT_DASH_PORT` → `[dashboard].port` → `6185` |

缺 key 时 CLI 会 stderr 警告；HTTP 401/403 时打印「从哪取 key / 怎么写 login.config / 无 API 时用 sync-plugin」。

## 传输模式

| 模式 | 何时用 | 示例 |
|------|--------|------|
| 直连 HTTP | 本机 AstrBot 或已有公网/隧道 | `astrbot-api.py --base-url http://127.0.0.1:62124 plugins list` |
| **SSH 侧 curl** | 生产 dashboard 只绑 `127.0.0.1`（远程推荐） | `astrbot-api.py --via-ssh plugins list` |

`--via-ssh` 使用 `login.config` 的 **[ssh]** 连服务器，在远端对 `http://127.0.0.1:<dash-port>` 发请求。
端口以 `config-tool.py get dashboard.port` 或 `[dashboard].port` 为准。

```bash
# 推荐：key/port 写在 login.config 后
python assets/astrbot-api.py --via-ssh plugins list
python assets/astrbot-api.py --via-ssh plugins reload --name my_plugin
python assets/astrbot-api.py --via-ssh bots
python assets/astrbot-api.py --via-ssh config get
python assets/astrbot-api.py --via-ssh chat --session test --text "hello"
python assets/astrbot-api.py --via-ssh raw --method GET --path /api/v1/plugins
```

## 端点族

- OpenAPI v1：`/api/v1/*`（**API Key**，CLI 优先）
- WebUI 旧版：`/api/plugin/*`（**JWT**，浏览器登录态；CLI 仅作回退）

版本差异用 `raw` 探活。401/403 见 `debug-handbook.md`。

## 与插件同步闭环

```bash
python assets/ssh-exec.py sync-plugin ./my_plugin --name my_plugin
python assets/astrbot-api.py --via-ssh plugins reload --name my_plugin
python assets/ssh-exec.py log astrbot --since "2 min ago" --profile plugin
```
