# AstrBot Debug Handbook

按需加载此文件，覆盖 AstrBot / NapCat / 插件运行时最常见的 debug 场景。
每节四段式：**症状 → 日志关键字定位 → 根因 → 修复**。所有"查日志"命令默认走
`assets/ssh-exec.py`，所有"改配置"命令走 `assets/config-tool.py`，"调 API"
走 `assets/astrbot-api.py`，**禁止**用 sed 改 JSON、用从头写的 paramiko 脚本查日志。

## 0. 一键命令小抄

```bash
# AstrBot 最近 200 行日志
python assets/ssh-exec.py tail astrbot --lines 200
# 时间窗 + 关键词过滤（最常用）
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "session lock"
python assets/ssh-exec.py log astrbot --since "1 hour ago" --grep "completion"
# NapCat 日志
python assets/ssh-exec.py tail napcat --lines 200
# 服务状态 / 端口
python assets/ssh-exec.py exec "systemctl status astrbot --no-pager"
python assets/ssh-exec.py exec "ss -tlnp | grep -E '6185|6199'"
# 读远程 cmd_config.json
python assets/ssh-exec.py cat /opt/astrbot/data/cmd_config.json
# WebUI 操作
python assets/astrbot-api.py plugins list
python assets/astrbot-api.py plugins reload --name <plugin>
```

下方各节默认引用上述工具。

---

## 1. 插件加载失败（YAML / import / syntax）

### 症状
- WebUI 安装/重载报错，插件状态显示「加载失败」
- 日志关键词：`yaml.parser.ParserError` / `SyntaxError` / `ModuleNotFoundError` /
  `Unexpected UTF-8 BOM` / `JSONDecodeError`

### 定位
```bash
python assets/ssh-exec.py log astrbot --since "10 min ago" --grep -i "error\|exception\|fail"
python assets/ssh-exec.py tail astrbot --lines 500 | findstr /i "yaml syntax bom import"
# 看插件目录
python assets/ssh-exec.py exec "ls -la /opt/astrbot/data/addons/plugins/<plugin_name>/"
# 查 metadata.yaml 是否有 BOM
python assets/ssh-exec.py exec "xxd /opt/astrbot/data/addons/plugins/<plugin_name>/metadata.yaml | head -1"
```
首字节应为 `7b`(`{`) 或字母，**不**应是 `ef bb bf`(UTF-8 BOM)。

### 根因与修复

| 报错 | 原因 | 修复 |
|------|------|------|
| `yaml.parser.ParserError: while parsing a block mapping` | `help` 字段值以 `[` 开头被识别为列表 | 给 `help` 值加双引号：`help: "[占卜] 随机..."` |
| `Unexpected UTF-8 BOM (decode using utf-8-sig)` | Windows SFTP/编辑器写入带 BOM | 用 `ssh-exec.py write` 或 `config-tool.py` 重写（无 BOM）；本地用 `New-Object System.Text.UTF8Encoding($false)` 重存 |
| `SyntaxError: invalid syntax. Perhaps you forgot a comma?` | Python 字符串字面值里夹未转义 `"` | 内层字符串改用单引号 `'请进行"省流"总结'` |
| `ModuleNotFoundError: No module named 'xxx'` | 插件缺 `requirements.txt` 或依赖未装 | 在插件根目录补 `requirements.txt`（每行 `pkg>=ver`），WebUI 重新安装 |
| `module 'main' has no attribute '__all__'` / 找不到类 | `@register` 装饰器漏写或类不继承 `Star` | 检查 main.py 有 `@register("name","author","desc",version="...")` + `class X(Star)` |

### 修复后验证
```bash
python assets/astrbot-api.py plugins reload --name <plugin_name>
python assets/ssh-exec.py log astrbot --since "1 min ago" --grep -i "error\|reload"
```

> 完整 BOM/JSON 校验流程见 `references/troubleshooting.md` #3 / #3.1 / #15
> 和 `references/compliance-checklist.md` 的 Encoding & Syntax Pre-flight。

---

## 2. 机器人不回复（LLM 链路）

### 症状
- 用户 @机器人 / 发消息，无响应
- 私聊正常但群聊不回，或某些群正常某些群不回

### 定位（消息流五个关键 log）
AstrBot 处理一条消息会依次打这五条日志（见 `references/source-message-flow.md`）：

1. `DIRECTED AT YOU` — @检测通过、`is_wake` 唤醒成功
2. `ready to request llm provider` — LLM 请求准备就绪
3. `acquired session lock for llm request` — 获取会话锁成功
4. `completion` — API 返回结果
5. `Prepare to send` — 最终发出回复

```bash
# 找出卡在哪一步
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "DIRECTED AT YOU"
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "ready to request"
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "session lock"
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "completion\|Prepare to send"
```

### 根因分类

#### 2.1 没有 `DIRECTED AT YOU` —— 唤醒没过
- @唤醒走 `isinstance(message, At)` 判定（`pipeline/waking_check/stage.py:121-139`），
  独立于 `wake_prefix`
- `wake_prefix` 只管不带 @ 的前缀唤醒（如 `/command`）
- `empty_mention_waiting`（默认 60s）只影响"纯 @ 无文字"，不影响带文字的 @at
- **修复**：检查 NapCat 是否正确把 `@机器人` 解析为 `At` 消息段；检查
  `wake_prefix` 是否被设置成了奇怪的值导致截断

#### 2.2 有 `ready to request` 但没 `acquired session lock` —— 会话锁死锁（最常见）
- 锁机制：`astrbot/core/utils/session_lock.py` 内的 `asyncio.Lock`，按
  `unified_msg_origin`（每群）隔离。同一群同一时间只能有一个 LLM 请求持有锁
- 前一个请求卡死（LLM 超时 / 工具调用死循环 / Agent runner 没退出）→ 后续全部阻塞
- **修复**：
  ```bash
  # 立即恢复（需征得用户同意，是系统级故障恢复）
  python assets/ssh-exec.py exec "systemctl restart astrbot"
  ```

#### 2.3 插件并行 LLM 请求抢锁
某些插件（如 `astrbot_plugin_smart_imagechat_hub` 的 proactive_emoji）会主动触发并行 LLM
请求，与主请求抢同一群的会话锁。并行请求卡住 → 主请求永远拿不到锁。
- **修复**（用 `config-tool.py --plugin`，不要手写 `python3 -c` 改 JSON）：
  ```bash
  # 先用 ls 找插件配置文件名
  python assets/ssh-exec.py exec "ls /opt/astrbot/data/plugin_configs/"
  # 降概率 + 切串行模式
  python assets/config-tool.py --plugin <plugin_name> set proactive_emoji_probability 0.2
  python assets/config-tool.py --plugin <plugin_name> set retrieval_mode on_decorating_result
  python assets/astrbot-api.py plugins reload --name <plugin_name>
  ```

#### 2.4 有 `completion` 但没 `Prepare to send` —— 回复被吞
- 可能某插件在 `on_decorating_result` 钩子里把消息包过滤掉
- 可能 `platform_settings.ignore_bot_self_message` 误关
- 用 `config-tool.py get platform_settings.ignore_bot_self_message` 看值

#### 2.5 分群差异
A 群正常 / B 群不回 → 对比两群日志：
```bash
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "unified_msg_origin=<群A>"
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "unified_msg_origin=<群B>"
```
重点看 B 群是否有未退出的 agent runner / 长耗时 tool call / 特殊插件触发（`#生成图片` 等）。

---

## 3. 适配器连接问题（aiocqhttp / NapCat / WebSocket）

### 症状
- NapCat 日志报 `405` / `连接错误`
- AstrBot 日志报 `WebSocket` 相关错误
- 机器人掉线 / 群消息不进来

### 定位
```bash
python assets/ssh-exec.py tail napcat --lines 300
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep -i "websocket\|aiocqhttp\|405\|disconnect"
# 看端口
python assets/ssh-exec.py exec "ss -tlnp | grep -E '6185|6199|62125'"
# 看 AstrBot 的 aiocqhttp 配置
python assets/config-tool.py get platform.0
python assets/config-tool.py get platform.0.ws_reverse_port
```

### 根因与修复

| 症状 | 原因 | 修复 |
|------|------|------|
| NapCat 报 `Unexpected server response: 405` | 反向 WebSocket 地址缺 `/ws` 路径 | NapCat WebUI → 网络配置 → 反向 WebSocket 地址改为 `ws://127.0.0.1:{ws_reverse_port}/ws` |
| NapCat 报连接拒绝 | AstrBot 没起 / ws_reverse_port 不对 / 防火墙 | `systemctl status astrbot`；`config-tool.py get platform.0.ws_reverse_port` |
| webui.json 端口不生效（仍是 6099） | 文件有 UTF-8 BOM | `xxd ~/Napcat/.../webui.json \| head -1` 看首字节；用 `ssh-exec.py write` 重写无 BOM |
| AstrBot 报 aiocqhttp 平台 disabled | `platform.0.enable=false` | `python assets/config-tool.py set platform.0.enable true` 然后 restart astrbot（影响核心生命周期，需用户确认） |
| 双方都启动但连不上 | NapCat 在另一台机器 / 端口绑定 127.0.0.1 | `platform.0.ws_reverse_host` 改 `0.0.0.0`；NapCat 反向地址写实际 IP |

### 验证连通
重置后双方重启：
```bash
python assets/ssh-exec.py exec "systemctl restart astrbot"
python assets/ssh-exec.py exec "napcat restart <QQ号>"
# 30 秒后看日志
python assets/ssh-exec.py log astrbot --since "30 sec ago" --grep -i "websocket\|connected"
```

---

## 4. LLM 调用失败（Provider）

### 症状
- 日志报 `API key invalid` / `401` / `403` / `timeout` / `rate limit`
- 用户问什么机器人都不回（且 2.3 节没命中）
- 推理模型回复内容混入 `<thought>...</thought>` 之类（MiniMax 推理泄漏）

### 定位
```bash
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep -i "provider\|llm\|api key\|401\|403\|timeout"
# 看 provider 配置
python assets/config-tool.py get provider.0
python assets/config-tool.py get provider.0.api_key
python assets/config-tool.py get provider.0.type
```

### 根因与修复

| 症状 | 原因 | 修复 |
|------|------|------|
| `401 Unauthorized` / `403 Forbidden` | API Key 错 / 过期 / 额度耗尽 | 更换 Key：`config-tool.py set provider.0.api_key sk-xxx`；restart astrbot（核心配置变更，需用户确认） |
| `Request timed out` | 上游 API 慢 / 网络断 | 检查 `provider.0.request_timeout`；服务器能否 `curl api.example.com` |
| `Rate limit exceeded` | 并发过高 / 配额耗尽 | 降低 `provider.0.concurrent_limiter`；更换 Provider |
| MiniMax M3 推理内容混入正文 | `minimax_token_plan` 适配器继承 `ProviderAnthropic`，`reasoning:true` 但 `anth_thinking_config={"type":"","budget":0}` 时模型推理直接进 `completion_text` | `config-tool.py set provider.0.anth_thinking_config '{"type":"enabled","budget":2048}'`（需 patch 模式传对象）；restart astrbot |
| LLM 返回 markdown 干扰下游 | prompt 未约束 / 插件未过滤 | prompt 加"不要使用任何 Markdown"；插件加 `_strip_markdown` 后处理函数（见 `references/troubleshooting.md` #3） |

---

## 5. 配置文件错误（cmd_config / webui / BOM）

### 症状
- AstrBot 启动失败，`systemctl` 显示 `auto-restart` 循环
- 日志报 `JSONDecodeError` / `Expecting property name enclosed in double quotes`
- 改了配置后服务起不来

### 定位
```bash
python assets/ssh-exec.py exec "systemctl status astrbot --no-pager"
python assets/ssh-exec.py log astrbot --since "10 min ago" --grep -i "json\|parse\|config"
# 验证 JSON
python assets/ssh-exec.py exec "python3 -c \"import json; json.load(open('/opt/astrbot/data/cmd_config.json'))\" || echo PARSE_FAIL"
# 查 BOM
python assets/ssh-exec.py exec "xxd /opt/astrbot/data/cmd_config.json | head -1"
```

### 根因与修复

| 症状 | 原因 | 修复 |
|------|------|------|
| `JSONDecodeError: Expecting property name enclosed in double quotes` | 用 sed 改过 JSON，破坏了引号/逗号 | **绝不**用 sed 改 JSON。回滚备份：`config-tool.py backup --local cmd_config.bak.json` 拉本地修，再 upload 回去 |
| `Unexpected UTF-8 BOM` | Windows SFTP/编辑器写入带 BOM | 用 `config-tool.py` 操作（自动无 BOM）；或 `ssh-exec.py write` 覆写 |
| 改完端口不生效 | 改了 `dashboard.port` 但没重启 | restart astrbot（核心配置，需用户确认） |
| 启动循环 | 多个配置项连锁错 | 备份后清空可疑段，逐段恢复 |

### 安全修改 JSON 的唯一姿势
```bash
# 1. 先备份
python assets/config-tool.py backup --local cmd_config.bak.json
# 2. 用 config-tool 改（parse→modify→dump，绝不 sed）
python assets/config-tool.py set dashboard.port 62124
python assets/config-tool.py patch '{"platform.0.enable":true,"platform.0.ws_reverse_port":6199}'
# 3. 重启生效（核心配置变更，需用户确认）
python assets/ssh-exec.py exec "systemctl restart astrbot"
```

> 案例：`references/troubleshooting.md` #15 详细记录了 sed 改 JSON 导致的崩溃循环。

---

## 6. 命令路由错误（@ / 唤醒前缀 / 指令冲突）

### 症状
- 发 `/hello` 机器人没反应
- @机器人也不响应（但其他群正常）
- 多个插件的相同指令名冲突

### 定位
```bash
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "wake\|prefix\|command\|is_wake"
# 看唤醒配置
python assets/config-tool.py get wake_prefix
python assets/config-tool.py get wake_prefix_blacklist
python assets/config-tool.py get empty_mention_waiting
```

### 根因与修复

| 症状 | 原因 | 修复 |
|------|------|------|
| 纯 @不响应但带字 @响应 | `empty_mention_waiting` 被关 / 关键字拦截 | `config-tool.py set empty_mention_waiting true` |
| `/cmd` 不响应 | `wake_prefix` 没设或被设错 | `config-tool.py set wake_prefix "/"` |
| 两个插件都有 `/weather` 指令 | 指令名冲突 | 改其中一个的指令名（改源码后 `astrbot-api.py plugins reload --name X`） |
| @无响应 + 日志无 `DIRECTED AT YOU` | NapCat 没解析出 At 段 / 机器人 QQ 号配错 | 检查 `platform.0.id` 与 NapCat 实际登录 QQ 一致；NapCat 日志看 raw message 段 |

### @唤醒机制速记
- `@at` 唤醒独立于 `wake_prefix`，走 `isinstance(message, At)` 判定
- 实现位置：`astrbot/core/pipeline/waking_check/stage.py:121-139`
- `wake_prefix` 仅影响不带 @ 的前缀唤醒
- `empty_mention_waiting` 仅控制"纯 @ 无文字"的 60 秒等待
- 详见 `references/source-message-flow.md` § 唤醒检查

---

## 7. 权限 / 鉴权（OpenAPI / WebUI）

### 症状
- 调 `/api/v1/*` 返回 401 / 403
- 插件调 AstrBot HTTP API 失败
- WebUI 操作被拒

### 定位
```bash
# 看 WebUI 是否要求 API Key
python assets/ssh-exec.py exec "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6185/api/v1/im/bots"
# 带 Key 试
python assets/ssh-exec.py exec "curl -s -w '%{http_code}' http://127.0.0.1:6185/api/v1/im/bots -H 'X-API-Key: YOUR_KEY'"
# 看 dashboard 配置
python assets/config-tool.py get dashboard
```

### 根因与修复

| 症状 | 原因 | 修复 |
|------|------|------|
| `401 Unauthorized` | 缺 `X-API-Key` 头 | 请求加 `-H "X-API-Key: <key>"`；用 `astrbot-api.py --api-key <key> ...` |
| `403 Forbidden` | Key 错 / 无权限 | WebUI → 设置 → 重新生成 API Key；`config-tool.py set dashboard.api_key <new>` |
| 工具脚本一直 401 | Key 没设到环境变量 | `setx ASTRBOT_API_KEY "<key>"`（Windows）或写到 shell rc |

### 用本 skill 的工具调 API
```bash
# 列出机器人账号
python assets/astrbot-api.py --api-key <key> bots
# 重载插件
python assets/astrbot-api.py --api-key <key> plugins reload --name <plugin>
# 测试 chat
python assets/astrbot-api.py --api-key <key> chat --session test --text "hello"
```

---

## 8. 性能 / 阻塞 / 内存

### 症状
- 机器人响应越来越慢
- CPU 占用高
- 群消息积压
- 进程内存上涨不释放

### 定位
```bash
python assets/ssh-exec.py exec "top -bn1 | grep -E 'astrbot|python' | head -5"
python assets/ssh-exec.py exec "ps auxf | grep astrbot | grep -v grep"
python assets/ssh-exec.py exec "free -h"
# 长时间观察
python assets/ssh-exec.py exec "vmstat 5 5"
# AstrBot 是否在积压
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep -i "queue\|backlog\|slow"
```

### 根因与修复

| 症状 | 原因 | 修复 |
|------|------|------|
| 整体卡顿 | 插件用同步 `requests` 阻塞事件循环 | 改 `aiohttp` / `httpx` 异步；reload 插件 |
| 内存涨 | 插件存了 conversation 历史 / 缓存无界 | 给缓存加 LRU/上限；定期清理；用 `data/` 目录持久化而非内存 |
| 单群卡死 | 见 §2.2 会话锁死锁 | `systemctl restart astrbot`（用户确认） |
| LLM 慢 | 上游 API 慢 / 模型太大 | 检查 `provider.0.request_timeout`；尝试更快的模型 |
| 启动慢 | 插件 `__init__` 做了重活（IO/大文件读） | 移到 lazy init；用 `asyncio.create_task` 异步预热 |

### 同步请求示例（错误 vs 正确）
```python
# 错 - 阻塞事件循环
import requests
resp = requests.get(url)

# 对 - 异步
import aiohttp
async with aiohttp.ClientSession() as s:
    async with s.get(url) as resp:
        data = await resp.json()
```

---

## 9. 快速决策表（症状 → 跳到哪节）

| 用户原话 | 跳到 |
|---------|------|
| "插件装不上 / 加载失败" | §1 |
| "@机器人不回话 / 没反应" | §2 |
| "NapCat 报 405 / 连不上" | §3 |
| "LLM 调不动 / API 错" | §4 |
| "改完配置起不来 / JSON 报错" | §5 |
| "/指令不响应" | §6 |
| "调 API 401 / 403" | §7 |
| "卡 / 慢 / 内存爆" | §8 |

---

## 10. 排查通用三步法

任何 AstrBot debug 默认按此三步开局，缩小范围后再去具体章节：

1. **看服务是否在跑**
   ```bash
   python assets/ssh-exec.py exec "systemctl status astrbot --no-pager"
   python assets/ssh-exec.py exec "systemctl status napcat --no-pager 2>/dev/null || napcat status"
   ```
2. **看端口是否在听**
   ```bash
   python assets/ssh-exec.py exec "ss -tlnp | grep -E '6185|6199|62125'"
   ```
3. **看最近 5 分钟日志有无 error/exception/fail**
   ```bash
   python assets/ssh-exec.py log astrbot --since "5 min ago" --grep -i "error\|exception\|fail\|traceback"
   ```

这三步走完，80% 的问题就能定位到具体章节约 80% 范围；剩下 20% 再深挖单
条日志关键字（用 `--grep` 二次过滤）或读源码精华（`references/source-*.md`）。
