# 配置文件参考

## login.config runtime 模式

| 字段 | 说明 |
|------|------|
| `[runtime].mode` | `auto` / `local` / `remote` |
| `ASTRBOT_RUNTIME_MODE` | 环境变量覆盖文件中的 mode |

- **local**：skill 与 AstrBot 同机，直接文件系统 + journalctl + `http://127.0.0.1:<dashboard.port>`
- **remote**：经 SSH/SFTP；API 使用 `astrbot-api.py --via-ssh`
- **auto**：本机存在 `[paths]`/`/opt/astrbot` 等标记 → local；否则 SSH 凭据齐全 → remote

`[paths]` 在两种模式下语义相同，只是目标主机不同（本机路径 vs 远端路径）。


## AstrBot

### 安装路径

> 本表为路径基线的**全局权威**，其它 reference 与此冲突以此为准。

| 项目 | 路径（uv 部署，生产） |
|------|------|
| 工作目录 | `/opt/astrbot/` |
| 数据目录 | `/opt/astrbot/data/` |
| 主配置文件 | `/opt/astrbot/data/cmd_config.json` |
| 插件安装目录 | `/opt/astrbot/data/plugins/{plugin_name}/` |
| 插件配置目录 | `/opt/astrbot/data/config/{plugin_name}_config.json` |
| 插件数据 | `/opt/astrbot/data/plugin_data/{plugin_name}/` |
| uv 安装位置 | `/root/.local/share/uv/tools/astrbot/` |
| uv Python 解释器 | `/root/.local/share/uv/tools/astrbot/bin/python` |
| astrbot 命令 | `/root/.local/bin/astrbot` |
| systemd 服务 | `/etc/systemd/system/astrbot.service` |

> 当前官方默认 `data/plugins/`；历史实例可能使用 `data/addons/plugins/`。
> `sync-plugin` / `diagnose` 解析顺序：`--remote-root` → `login.config [paths].plugins_dir` → 远端存在的 modern/legacy 候选。
> 建议先 `ssh-exec.py config discover --write` 把真实路径写回 login.config。本地开发相对路径基线为 `<repo>/AstrBot/data/plugins/`。

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
# AstrBot skill 凭据（login.config）— 勿提交 git；UTF-8 无 BOM
# [ssh] 远程运维  [git] 个人身份  [dashboard] 可选 API
[ssh]
host = 1.2.3.4
port = 22
user = root
password = secret

[git]
# 个人身份唯一来源；不要填公司账号
user = yourname
email = you@example.com
github = https://github.com/yourname

[dashboard]
# 可选：astrbot-api 用；port 常非默认 6185
port = 6185
api_key =
```

| 段/键 | 必填 | 用途 |
|---|---|---|
| `[ssh].host` | 是 | SSH 主机 |
| `[ssh].port` | 否（默认 22） | SSH 端口 |
| `[ssh].user` | 是 | SSH 用户名 |
| `[ssh].password` | 条件必填 | SSH 密码；与 identity_file/allow_agent 至少一种 |
| `[ssh].identity_file` | 条件必填 | 私钥路径；也可用 `ASTRBOT_SSH_IDENTITY` |
| `[ssh].allow_agent` | 否 | 是否使用 ssh-agent；或 `ASTRBOT_SSH_ALLOW_AGENT=1` |
| `[git].user` | 插件推荐 | metadata `author` + git `user.name`（个人） |
| `[git].email` | 插件推荐 | git `user.email`（个人） |
| `[git].github` | 插件推荐 | `metadata.repo` 根 |
| `[dashboard].port` | 否 | 远程 WebUI 端口（`astrbot-api --via-ssh`；常非 6185） |
| `[dashboard].api_key` | 否 | Dashboard API Key（Bearer/X-API-Key；WebUI 创建） |
| 旧版 `[git.personal]` / multi-profile | 兼容 | 仍可解析，**新配置请用扁平 [git]** |

自动发现远端布局：`python scripts/ssh-exec.py config discover [--write]`

插件身份工具：`python scripts/git-identity.py show|status|fix|check-push`  
插件合规：`python scripts/plugin-check.py <dir>`  
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
- 手动：`python scripts/ssh-exec.py init-config [--format ini|json] [--path PATH] [--force]`

解析实现：`scripts/_common.py` 的 `parse_login_config`（**唯一实现**，自动识别格式）。

搜索顺序：`--login-config` → `$ASTRBOT_LOGIN_CONFIG` → cwd 向上 → skill 根向上（同时找 `login.config` 与 `login.config.json`）。

```python
import sys; sys.path.insert(0, "assets")
from _common import load_credentials
creds = load_credentials()  # or parse_login_config(Path("login.config"))
```

### 远程操作首选 CLI

```bash
python scripts/ssh-exec.py whoami
python scripts/ssh-exec.py diagnose --full
python scripts/ssh-exec.py trace --since "30 min ago"
python scripts/ssh-exec.py batch "cmd1" "cmd2"
python scripts/ssh-exec.py log astrbot --since "30 min ago" --profile errors
python scripts/ssh-exec.py sync-plugin ./my_plugin --name my_plugin
python scripts/config-tool.py get dashboard.port
python scripts/astrbot-api.py --via-ssh plugins reload --name my_plugin
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


## [paths] 远端布局（可选）

用于非 `/opt/astrbot` 安装或自定义 systemd 单元名。未写则使用默认。

| 键 | 默认 | 说明 |
|----|------|------|
| `astrbot_root` | `/opt/astrbot` | 安装根 |
| `data_dir` | `{root}/data` | 数据目录 |
| `plugins_dir` | `{data}/plugins`（历史实例可能为 `{data}/addons/plugins`） | 插件安装目录；以 `config discover` 为准 |
| `plugin_configs_dir` | `{data}/config` | 插件配置 |
| `skills_dir` | `{data}/skills` | Runtime Skills |
| `workspaces_dir` | `{data}/workspaces` | 会话 workspace |
| `knowledge_base_dir` | `{data}/knowledge_base` | 知识库 |
| `backups_dir` | `{data}/backups` | 备份 |
| `plugin_data_dir` | `{data}/plugin_data` | 插件持久化 |
| `cmd_config` | `{data}/cmd_config.json` | 主配置 |
| `astrbot_unit` | `astrbot` | systemd 单元名 |
| `python_bin` | optional remote python for version probe (uv tool interpreter) |
| `napcat_unit` | _(空)_ | 可选 |

`config-tool` / `sync-plugin` / `service` / `diagnose` 会读取该段。

## 编码与 BOM

`login.config` 与远端 `cmd_config.json` 均应使用 **UTF-8 无 BOM**。
Windows 记事本有时会写入 BOM（字节 `EF BB BF`），会导致 `json.load` 报错。
skill 读取时会 strip BOM；写回使用无 BOM。可用 `config discover` 检测远端 BOM。
