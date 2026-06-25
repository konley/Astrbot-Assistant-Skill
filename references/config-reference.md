# 配置文件参考

## AstrBot

### 安装路径

| 项目 | 路径 |
|------|------|
| 工作目录 | `/opt/astrbot/`（或自定义） |
| 数据目录 | `/opt/astrbot/data/` |
| 主配置文件 | `/opt/astrbot/data/cmd_config.json` |
| 插件目录 | `/opt/astrbot/data/plugins/` |
| 插件数据 | `/opt/astrbot/data/plugin_data/` |
| uv 安装位置 | `/root/.local/share/uv/tools/astrbot/` |
| astrbot 命令 | `/root/.local/bin/astrbot` |
| systemd 服务 | `/etc/systemd/system/astrbot.service` |

### cmd_config.json 关键字段

```json
{
  "dashboard": {
    "port": 6185
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
  "port": 6099,          // WebUI 端口
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

### paramiko 脚本模板

```python
import paramiko

HOST = "你的服务器IP"
PORT = 22
USER = "用户名"
PASS = "密码"

# 执行单条命令
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
stdin, stdout, stderr = client.exec_command("命令", timeout=60)
print(stdout.read().decode())
client.close()

# SFTP 上传文件
sftp = client.open_sftp()
with sftp.open("/远程/路径", "w") as f:
    f.write(content)
sftp.close()

# 交互式 shell（用于 astrbot init 等）
channel = client.invoke_shell()
channel.send("命令\n")
# 自动应答
channel.send("Y\n")
```

### 注意事项

- 用 `;` 分隔命令，不用 `&&`（PowerShell 语法）
- 含特殊字符的命令用 Python 脚本包装
- 文件上传用 SFTP，避免 heredoc 和 BOM 问题
- 交互式命令用 `invoke_shell()` + 自动应答
