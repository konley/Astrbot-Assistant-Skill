# AstrBot + NapCat 部署指南

## 系统要求

- Python 3.12+
- curl
- Ubuntu/Debian/CentOS 均可

## 一、安装 AstrBot（uv 方式）

### 1. 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | bash
source ~/.local/bin/env
uv --version
```

### 2. 安装 AstrBot

```bash
uv tool install astrbot
```

uv 会自动下载 Python 3.12（如果系统没有）。

### 3. 初始化

```bash
mkdir -p /opt/astrbot
cd /opt/astrbot
astrbot init
```

> `astrbot init` 是交互式的，会提示 `Install AstrBot to this directory? [Y/n]`，需输入 `Y`。
> 生成 `data/cmd_config.json` 和 `data/t2i_templates/`。

### 4. 配置端口

```bash
cd /opt/astrbot
astrbot conf set dashboard.port {端口}
astrbot conf get dashboard.port
```

默认端口 6185。改为自定义端口后需重启生效。

### 5. 创建 systemd 服务

```ini
# /etc/systemd/system/astrbot.service
[Unit]
Description=AstrBot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/astrbot
Environment=PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/root/.local/bin/astrbot run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable astrbot
systemctl start astrbot
systemctl status astrbot
```

### 6. 验证

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:{端口}
```

### 7. 升级

```bash
source /root/.local/bin/env
uv tool upgrade astrbot
```

> uv 方式不支持 WebUI 升级。

## 二、安装 NapCat

### 1. 下载安装脚本

```bash
curl -o /tmp/napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
```

### 2. 运行安装

```bash
bash /tmp/napcat.sh --cli y --force
```

安装到 `~/Napcat/`，QQ 在 `~/Napcat/opt/QQ/`。
管理命令 `napcat` 安装到 `/usr/local/bin/napcat`。

### 3. 配置 WebUI 端口

配置文件路径：

```
~/Napcat/opt/QQ/resources/app/app_launcher/napcat/config/webui.json
```

```json
{
  "host": "::",
  "port": 62125,
  "token": "",
  "loginRate": 10,
  "autoLoginAccount": "",
  "disableWebUI": false,
  "accessControlMode": "none",
  "ipWhitelist": [],
  "ipBlacklist": [],
  "enableXForwardedFor": false,
  "enable2FA": false,
  "totpSecret": ""
}
```

> 默认端口 6099。用 SFTP 写入文件以避免 BOM 问题。

### 4. 启动并扫码登录

```bash
napcat start {QQ号}
napcat log {QQ号}
```

查看日志中的二维码或二维码 URL，用手机 QQ 扫码。

### 5. 设置开机自启

```bash
napcat startup {QQ号}
```

## 三、对接 AstrBot ↔ NapCat

### AstrBot 端配置 aiocqhttp 适配器

在 WebUI → 平台适配器 → 添加 aiocqhttp，或编辑 `data/cmd_config.json`：

```json
{
  "id": "aiocqhttp-default",
  "type": "aiocqhttp",
  "enable": true,
  "ws_reverse_host": "0.0.0.0",
  "ws_reverse_port": 6199,
  "ws_reverse_token": ""
}
```

### NapCat 端配置反向 WebSocket

在 NapCat WebUI → 网络配置 → 添加反向 WebSocket：

```
ws://127.0.0.1:6199/ws
```

> **关键**：地址必须以 `/ws` 结尾，否则返回 HTTP 405。

### 验证连通

双方重启后，AstrBot 日志应显示 WebSocket 连接成功，NapCat 日志不再出现 405 错误。
