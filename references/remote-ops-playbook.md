# Remote Ops Playbook（Windows 本机 → SSH 远端）

**唯一远程作战手册。** 排障/同步/API 先读本文，再按需打开 `debug-handbook.md`。

## 0. 硬契约（违反即浪费 token）

1. **禁止**为一次性任务新建 paramiko / 临时 `.py` 脚本。
2. 远程操作只用：`ssh-exec.py` / `config-tool.py` / `astrbot-api.py --via-ssh`。
3. 需要多命令 → `ssh-exec.py batch` 或 `diagnose` / `trace`（单连接）。
4. 改 JSON → `config-tool.py`（禁止 sed / 手工拼 JSON 字符串写回）。
5. 长文件内容 → `write --file` / `upload` / `upload-dir` / `sync-plugin`（禁止 `write` 内联大段 argv）。
6. 本地有插件源码 → 本地 `read`/`edit`，再用 `sync-plugin` 同步；不要远程 cat 改业务代码。
7. 调用时优先用 **skill 内 assets 的绝对路径**，避免 cwd 漂移。

### 推荐调用模板（PowerShell）

```powershell
$SKILL = "C:\测试开发\AstrBot\Astrbot-Assistant-Skill"   # 或 Junction 目标
$A = Join-Path $SKILL "assets"
# 可选：固定凭据文件
# $env:ASTRBOT_LOGIN_CONFIG = "C:\测试开发\AstrBot\login.config"

python "$A\ssh-exec.py" whoami
python "$A\ssh-exec.py" diagnose --full
python "$A\ssh-exec.py" trace --since "30 min ago"
python "$A\config-tool.py" get platform.0
python "$A\astrbot-api.py" --via-ssh --dash-port 6185 plugins list
```

> 首次使用：`python assets/ssh-exec.py init-config` 生成带注释 INI 模板（也支持 `--format json`）。
> `login.config` 搜索顺序：`--login-config` → `$ASTRBOT_LOGIN_CONFIG` → cwd 向上 → skill 根向上。  
> 失败时 stderr 会打印 **Searched:** 列表，不要猜 host。

---

## 1. 标准开局（任何远程问题）

```powershell
python "$A\ssh-exec.py" whoami
python "$A\ssh-exec.py" diagnose --full
```

读输出后分支：

| 现象 | 下一步 |
|------|--------|
| astrbot inactive / failed | `log astrbot --since "15 min ago" --profile errors` |
| 端口不在听 | 查 config + systemd；**restart 需用户确认** |
| 有 error 日志 | 按关键字进 `debug-handbook.md` 对应节 |
| 服务正常但不回复 | `trace --since "30 min ago"` |
| 插件相关 | `ls /opt/astrbot/data/addons/plugins` + API reload |

---

## 2. 机器人不回复（最高频）

```powershell
python "$A\ssh-exec.py" trace --since "30 min ago"
# 需要 JSON 给后续步骤解析时：
python "$A\ssh-exec.py" trace --since "1 hour ago" --json
```

`trace` 一次连接查消息流 5 步：

1. `DIRECTED TO YOU`（唤醒）
2. `ready to request llm`
3. `session lock`
4. `completion`
5. `Prepare to send`

解读：

- 全 MISS → 消息没进 AstrBot（NapCat / 平台 / 唤醒）
- 卡在某步 → 见 `debug-handbook.md` §2 对应小节
- 全 OK 仍无回复 → 查 NapCat 发送与平台配置

补充：

```powershell
python "$A\ssh-exec.py" log astrbot --since "30 min ago" --profile llm
python "$A\ssh-exec.py" log astrbot --since "30 min ago" --profile wake
python "$A\ssh-exec.py" tail napcat --lines 200
```

---

## 3. 日志查询（正确参数）

```powershell
# 预置 profile（推荐）
python "$A\ssh-exec.py" log astrbot --since "10 min ago" --profile errors
python "$A\ssh-exec.py" log astrbot --since "1 hour ago" --profile plugin --lines 80

# 自定义扩展正则：整段作为 --grep 的一个参数（不要单独写 -i）
python "$A\ssh-exec.py" log astrbot --since "30 min ago" --grep "session lock|completion"
```

**错误示例（禁止）：**

```text
--grep -i "error|fail"     # -i 会被 argparse 当成选项 → 失败
... | findstr ...          # 不要本地二次管道；过滤放远端
```

Profiles：`errors` / `llm` / `ws` / `plugin` / `wake`。

---

## 4. 多命令 / 批处理（替代临时脚本）

```powershell
python "$A\ssh-exec.py" batch `
  "systemctl is-active astrbot" `
  "ss -tlnp | grep -E '6185|6199|62124' || true" `
  "ls -la /opt/astrbot/data/addons/plugins | head"

# 或从文件
python "$A\ssh-exec.py" batch --file cmds.txt
python "$A\ssh-exec.py" batch --stdin --json   # 管道输入
```

仅当预置子命令不够时，才用 `exec` **单行** shell。

---

## 5. 配置读写

```powershell
python "$A\config-tool.py" show --key platform
python "$A\config-tool.py" get platform.0.ws_reverse_port
python "$A\config-tool.py" set platform.0.enable true
python "$A\config-tool.py" --plugin myplug get some_key
python "$A\config-tool.py" backup
```

- 改 **插件配置** → reload 插件即可  
- 改 **platform/provider/dashboard** → 需 **用户确认后** restart  

---

## 6. 插件同步与热重载闭环

```powershell
# 本地改完源码后
python "$A\ssh-exec.py" sync-plugin "C:\path\to\my_plugin" --name my_plugin
# 等价 upload-dir 到 /opt/astrbot/data/addons/plugins/my_plugin

# dashboard 只监听 127.0.0.1 时用 --via-ssh
python "$A\astrbot-api.py" --via-ssh --dash-port 6185 plugins reload --name my_plugin
python "$A\ssh-exec.py" log astrbot --since "2 min ago" --profile plugin
```

`sync-plugin` 默认排除：`.git` / `__pycache__` / `*.pyc` / venv 等。

若 API key 需要：

```powershell
$env:ASTRBOT_API_KEY = "<key>"
python "$A\astrbot-api.py" --via-ssh plugins list
```

端口以 `config-tool.py get dashboard.port` 为准；可用 `--dash-port`。

---

## 7. 写远端文件（无 BOM）

```powershell
# 推荐：本地文件上传内容
python "$A\ssh-exec.py" write /tmp/x.json --file .\local.json
python "$A\ssh-exec.py" upload .\main.py /opt/astrbot/data/addons/plugins/p/main.py

# 短字符串才用位置参数
python "$A\ssh-exec.py" write /tmp/flag.txt "ok"
```

---

## 8. 决策简表

| 用户说 | 命令 |
|--------|------|
| 帮我看看机器人怎么了 | `diagnose --full` → 必要时 `trace` |
| 不回复 / @没反应 | `trace` + `--profile llm/wake` |
| 插件装不上 / 加载失败 | `--profile plugin` + `ls` 插件目录 |
| NapCat 405 | `config-tool get platform.0` + `--profile ws` |
| 改个配置 | `config-tool` |
| 同步插件并生效 | `sync-plugin` + `astrbot-api --via-ssh plugins reload` |
| 要跑好几条检查 | `batch` |

---

## 9. 仍不够用时的唯一逃生口

1. 先确认没有对应子命令（`ssh-exec.py -h` / `astrbot-api.py -h`）。
2. 用 `batch` 或 `exec` 跑**一条**远端 shell（过滤在远端完成）。
3. 交互式 `astrbot init` 才允许最小 `invoke_shell_send`（import `_common`，禁止重写连接）。
4. **不要**落盘写新的运维脚本到工作区除非用户明确要求固化工具。