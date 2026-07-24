# 配置文件参考

## AstrBot

### 安装路径

> 本表为路径基线的**全局权威**，其它 reference 与此冲突以此为准。

| 项目 | 路径（uv 部署，生产） |
|------|------|
| 工作目录 | `/opt/astrbot/` |
| 数据目录 | `/opt/astrbot/data/` |
| 主配置文件 | `/opt/astrbot/data/cmd_config.json` |
| 插件安装目录 | `/opt/astrbot/data/addons/plugins/{plugin_name}/` |
| 插件配置目录 | `/opt/astrbot/data/plugin_configs/` |
| 插件数据 | `/opt/astrbot/data/plugin_data/{plugin_name}/` |
| uv 安装位置 | `/root/.local/share/uv/tools/astrbot/` |
| uv Python 解释器 | `/root/.local/share/uv/tools/astrbot/bin/python` |
| astrbot 命令 | `/root/.local/bin/astrbot` |
| systemd 服务 | `/etc/systemd/system/astrbot.service` |

> ⚠️ 历史版本曾用 `data/plugins/`，当前版本统一为 `data/addons/plugins/`。本地开发场景（clone AstrBot repo）的相对路径基线为 `<repo>/AstrBot/data/addons/plugins/`。

### cmd_config.json 关键字段

```json
{
  "dashboard": {
    "port": 62124
  },
  "platform": [
    {
      "id": "aiocqhttp-default",
      "type": "aiocqhttp",
      "enable": true,
      "ws_reverse_host": "0.0.0.0",
      "ws_reverse_port": 6199,
      "ws_reverse_token": ""
    }
  ],
  "provider": [
    {
      "id": "minimax-token-plan",
      "type": "minimax_token_plan"
    }
  ],
  "persona": {}
}
```

### 常用 CLI 命令

| 命令 | 用途 |
|------|------|
| `astrbot init` | 初始化（交互式） |
| `astrbot run` | 启动 |
| `astrbot conf set {key} {value}` | 设置配置项 |
| `astrbot conf get {key}` | 读取配置项 |

### systemd 运维

```bash
systemctl start astrbot      # 启动
systemctl stop astrbot       # 停止
systemctl restart astrbot    # 重启
systemctl status astrbot     # 状态
systemctl enable astrbot     # 开机自启
journalctl -u astrbot -f     # 实时日志
```

---

## NapCat

### 安装路径

| 项目 | 路径 |
|------|------|
| 安装根目录 | `~/Napcat/` |
| QQ 程序 | `~/Napcat/opt/QQ/` |
| NapCat 核心 | `~/Napcat/opt/QQ/resources/app/app_launcher/napcat/` |
| 配置目录 | `~/Napcat/opt/QQ/resources/app/app_launcher/napcat/config/` |
| WebUI 配置 | `config/webui.json` |
| 日志目录 | `~/Napcat/log/` |
| 管理命令 | `/usr/local/bin/napcat` |
| 运行目录 | `~/Napcat/run/` |

### webui.json 结构

```json
{
  "host": "::",           // 监听地址，:: 表示所有
  "port": 62125,          // WebUI 端口
  "token": "",            // 访问令牌，空则不需要
  "loginRate": 10,        // 登录频率限制
  "autoLoginAccount": "", // 自动登录的 QQ 号
  "disableWebUI": false,  // 是否禁用 WebUI
  "accessControlMode": "none",
  "ipWhitelist": [],
  "ipBlacklist": [],
  "enableXForwardedFor": false,
  "enable2FA": false,
  "totpSecret": ""
}
```

### 常用 napcat 命令

| 命令 | 用途 |
|------|------|
| `napcat start {QQ号}` | 启动 |
| `napcat stop` | 停止 |
| `napcat restart {QQ号}` | 重启 |
| `napcat log {QQ号}` | 查看日志 |
| `napcat startup {QQ号}` | 设置开机自启 |

### 反向 WebSocket 配置

NapCat WebUI → 网络配置 → 添加反向 WebSocket：

```
ws://127.0.0.1:{astrbot_ws_port}/ws
```

> 必须带 `/ws` 路径后缀。

---

## SSH 远程操作（Windows 本地）

> 完整流程见 `references/remote-ops-playbook.md`。下列为路径/凭据权威摘要。

### login.config 凭据文件

项目或 skill 附近可存在 `login.config` / `login.config.json`。远程操作时**优先读取**，不询问用户凭据。

#### 1) INI（推荐，可写注释）

```ini
# DO NOT commit. UTF-8 no BOM.
# [git] = 个人身份唯一来源，避免本机 global 公司账号误 push
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

| 段/键 | 必填 | 用途 |
|---|---|---|
| `[ssh].host` | 是 | SSH 主机 |
| `[ssh].port` | 否（默认 22） | SSH 端口 |
| `[ssh].user` | 是 | SSH 用户名 |
| `[ssh].password` | 是 | SSH 密码 |
| `[git].user` | 插件推荐 | metadata `author` + git `user.name`（个人） |
| `[git].email` | 插件推荐 | git `user.email`（个人） |
| `[git].github` | 插件推荐 | `metadata.repo` 根 |
| `[dashboard].port` | 否 | 远程 WebUI 端口（`astrbot-api --via-ssh`；常非 6185） |
| `[dashboard].api_key` | 否 | Dashboard API Key（`X-API-Key`；WebUI 创建） |
| 旧版 `[git.personal]` / multi-profile | 兼容 | 仍可解析，**新配置请用扁平 [git]** |

插件身份工具：`python assets/git-identity.py show|status|fix|check-push`  
插件合规：`python assets/plugin-check.py <dir>`  
详见 `references/plugin-dev-playbook.md`。

#### 2) JSON（可选）

文件名 `login.config.json`，或 `login.config` 内容以 `{` 开头：

```json
{
  "ssh": { "host": "1.2.3.4", "port": 22, "user": "root", "password": "secret" },
  "git": {
    "user": "yourname",
    "email": "you@example.com",
    "github": "https://github.com/yourname"
  },
  "dashboard": { "port": 6185, "api_key": "" }
}
```

#### 3) 旧行位序格式（兼容，不推荐新写）

```
IP:端口
SSH用户名
密码
https://github.com/用户名
git_user:name
git_email:you@example.com
```

#### 自动生成模板

- 缺失时：`load_credentials()` 会在首选项目路径生成带注释的 INI 模板，并提示填写
- 手动：`python assets/ssh-exec.py init-config [--format ini|json] [--path PATH] [--force]`

解析实现：`assets/_common.py` 的 `parse_login_config`（**唯一实现**，自动识别格式）。

搜索顺序：`--login-config` → `$ASTRBOT_LOGIN_CONFIG` → cwd 向上 → skill 根向上（同时找 `login.config` 与 `login.config.json`）。

```python
import sys; sys.path.insert(0, "assets")
from _common import load_credentials
creds = load_credentials()  # or parse_login_config(Path("login.config"))
```

### 远程操作首选 CLI

```bash
python assets/ssh-exec.py whoami
python assets/ssh-exec.py diagnose --full
python assets/ssh-exec.py trace --since "30 min ago"
python assets/ssh-exec.py batch "cmd1" "cmd2"
python assets/ssh-exec.py log astrbot --since "30 min ago" --profile errors
python assets/ssh-exec.py sync-plugin ./my_plugin --name my_plugin
python assets/config-tool.py get dashboard.port
python assets/astrbot-api.py --via-ssh plugins reload --name my_plugin
```

### paramiko 片段（仅 invoke_shell 交互式场景）

仅 `astrbot init` 等必须交互应答时，才允许最小片段，且必须复用 `_common`：

```python
import sys; sys.path.insert(0, "assets")
from _common import load_credentials, invoke_shell_send
creds = load_credentials()
print(invoke_shell_send(creds, ["cd /opt/astrbot", "astrbot init", "Y"]))
```

### 注意事项

- 过滤在远端完成；PowerShell 下给 `exec`/`batch` 的命令用引号包住
- 长内容用 `write --file` / `upload` / `sync-plugin`，避免 argv 与 BOM
- 禁止为一次性任务新建 paramiko 运维脚本
