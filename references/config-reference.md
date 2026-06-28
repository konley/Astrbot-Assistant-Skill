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

### login.config 凭据文件

项目根目录下可能存在 `login.config` 文件，存储 SSH 连接凭据。当用户请求远程操作时，**优先读取此文件**，不询问用户凭据。

**统一格式（推荐）**：
```
IP:端口
用户名
密码
https://github.com/用户名
```

第 4 行（可选）为 GitHub 仓库根地址，用于自动填充插件 `metadata.yaml` 的 `repo` 字段。

解析逻辑兼容历史前缀格式（`ssh:` / `name:` / `psw:`），实现见 `assets/_common.py` 的 `parse_login_config`（**唯一实现**，禁止在其它地方重复）。需要时直接 import：

```python
import sys; sys.path.insert(0, "assets")
from _common import parse_login_config
creds = parse_login_config("login.config")
```

### 远程操作首选：ssh-exec.py CLI

`assets/ssh-exec.py` 是本 skill 远程操作的**唯一入口**，覆盖 95% 场景。详见 SKILL.md 的"工具链"段。常用命令：

```bash
python assets/ssh-exec.py exec "systemctl status astrbot --no-pager"
python assets/ssh-exec.py tail astrbot --lines 200
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "session lock"
python assets/ssh-exec.py upload local.py /remote/path/main.py
python assets/ssh-exec.py cat /opt/astrbot/data/cmd_config.json
```

### paramiko 片段（仅 invoke_shell 交互式场景）

仅当遇到 `astrbot init` 这类必须交互应答的情况，才允许写最小 paramiko 片段。必须复用 `_common.py` 的连接逻辑，**不得重写**：

```python
import sys; sys.path.insert(0, "assets")
from _common import parse_login_config, connect  # 复用，不重写

creds = parse_login_config("login.config")
c = connect(creds)
try:
    ch = c.invoke_shell()
    ch.send("cd /opt/astrbot && astrbot init\n")
    # 自动应答 Y/n 提示
    import time; time.sleep(2)
    ch.send("Y\n")
    # 读取输出 ...
finally:
    c.close()
```

### 注意事项

- 用 `;` 分隔命令，不用 `&&`（PowerShell 语法）
- 含特殊字符的命令包装成 `ssh-exec.py exec "..."`；复杂内容用 `upload` 上传脚本到服务器再执行
- 文件上传用 `ssh-exec.py upload`（SFTP），避免 heredoc 和 BOM 问题
- 交互式命令才用 `invoke_shell()` + 自动应答
