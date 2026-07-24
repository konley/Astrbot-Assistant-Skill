# OpenAPI / WebUI 集成

权威命令以 `python assets/astrbot-api.py --help` 为准。

## 鉴权

- Header：`X-API-Key: <key>`
- CLI：`--api-key` 或环境变量 `$ASTRBOT_API_KEY`
- 无 key 且 dashboard 未开鉴权时可不传（少见）

## 传输模式

| 模式 | 何时用 | 示例 |
|------|--------|------|
| 直连 HTTP | 本机 AstrBot 或已有公网/隧道 | `astrbot-api.py --base-url http://127.0.0.1:6185 plugins list` |
| **SSH 侧 curl** | 生产 dashboard 只绑 `127.0.0.1`（默认推荐远程） | `astrbot-api.py --via-ssh --dash-port 6185 plugins list` |

`--via-ssh` 使用 `login.config` 与 `_common.remote_http_request`，在远端对 `http://127.0.0.1:<dash-port>` 发请求，**无需**本地手动建隧道。

端口以 `config-tool.py get dashboard.port` 为准（常见 6185 / 62124）。

```bash
export ASTRBOT_API_KEY=...   # 或 PowerShell: $env:ASTRBOT_API_KEY="..."
python assets/astrbot-api.py --via-ssh --dash-port 6185 plugins list
python assets/astrbot-api.py --via-ssh plugins reload --name my_plugin
python assets/astrbot-api.py --via-ssh plugins reload --all
python assets/astrbot-api.py --via-ssh bots
python assets/astrbot-api.py --via-ssh config get
python assets/astrbot-api.py --via-ssh chat --session test --text "hello"
python assets/astrbot-api.py --via-ssh raw --method GET --path /api/plugin/get
```

## 端点族

- WebUI 内部：`/api/plugin/*`（reload / install / on / off / ...）
- OpenAPI v1：`/api/v1/*`（chat / bots / configs / ...）

版本差异时用 `raw` 探测。401/403 见 `debug-handbook.md` §7。

## 与插件同步闭环

```bash
python assets/ssh-exec.py sync-plugin ./my_plugin --name my_plugin
python assets/astrbot-api.py --via-ssh plugins reload --name my_plugin
python assets/ssh-exec.py log astrbot --since "2 min ago" --profile plugin
```
