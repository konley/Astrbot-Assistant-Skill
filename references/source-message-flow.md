# AstrBot 消息流源码精华

按需加载此文件：当需要理解一条消息从接收到回复经过哪些阶段、对应哪些源码、打哪些日志时使用。
配合 `references/debug-handbook.md` §2（机器人不回复）一起看。

## 顶层流程

```
[适配器] 收事件 → [Stage: woke check] → [Stage: 指令分发] → [Stage: LLM 请求]
   → [Stage: result handler] → [Stage: 发送] → [适配器] send
```

每个 Stage 是 `astrbot/core/pipeline/` 下一个目录，含 `stage.py`。Pipeline 由
`StageScheduler` 串行驱动。所有阶段共享一个 `AstrMessageEvent` 上下文。

## 1. 消息入站（适配器 → Event）

| 文件 | 角色 |
|------|------|
| `astrbot/core/platform/astr_message_event.py` | `AstrMessageEvent` 基类，封装 message, session, sender, result |
| `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py` | aiocqhttp 适配器，把 NapCat 上行的 OneBot 消息段转为 `AstrMessageEvent` |
| `astrbot/core/platform/sources/<other>/...` | 其他适配器（qq_official / telegram / ...） |

关键转换：NapCat 发来的 `At` 段 → `MessageResult.At` 对象。**如果这步丢了 At**，
后续 `waking_check` 永远不会触发 `DIRECTED AT YOU` 日志。

日志关键字（入站成功）：`on_event_received` / 适配器对应的 receive 日志。

## 2. 唤醒检查（waking_check stage）

源码：`astrbot/core/pipeline/waking_check/stage.py`

关键判定逻辑（行号约 121-139）：

```python
def _check_wake(self, event: AstrMessageEvent) -> bool:
    msg = event.message
    # 1) 优先 At 判定（独立于 wake_prefix）
    for c in msg.message:
        if isinstance(c, At) and c.qq == event.bot_self_id:
            return True   # → 打印 "DIRECTED AT YOU"
    # 2) wake_prefix 前缀唤醒
    if self.wake_prefix and plain_text.startswith(self.wake_prefix):
        return True
    # 3) 纯 @无文字 → empty_mention_waiting（默认 60 秒窗口等下一句）
    if is_pure_at and self.empty_mention_waiting:
        event.set_waiting()
        return True
    return False
```

### 三个独立机制

| 机制 | 触发 | 配置项 | 备注 |
|------|------|--------|------|
| `@at` 唤醒 | 消息段含 `At`，且 `qq == bot_self_id` | 无（始终启用） | 独立于 `wake_prefix`，最常见的入口 |
| `wake_prefix` 唤醒 | 纯文本以 `wake_prefix` 开头 | `wake_prefix`（默认 `""`） | 用于 `/cmd` 这种指令唤醒 |
| `empty_mention_waiting` | 纯 @无文字 | `empty_mention_waiting`（默认 true） | 60 秒窗口等用户接着发文字 |

### 调试

```bash
# 看唤醒是否通过
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "DIRECTED AT YOU"
# 看唤醒配置
python assets/config-tool.py get wake_prefix
python assets/config-tool.py get empty_mention_waiting
```

## 3. 指令分发（command / regex / hook）

源码：`astrbot/core/pipeline/decorator_handle/stage.py`

`@filter.command("xxx")` / `@filter.regex(...)` / `@filter.on_llm_request()` 等装饰器
在插件加载时注册到 `star_registry`。本 Stage 按 event 中的文本匹配触发对应装饰器。

| 装饰器 | 触发时机 |
|--------|---------|
| `@filter.command("xxx")` event message_obj 以 `xxx` 开头（受 `wake_prefix` 影响） |
| `@filter.regex(pattern)` | message 文本匹配正则 |
| `@filter.on_decorating_result()` | LLM 结果回包后（可改写回复） |
| `@filter.on_llm_request()` | LLM 请求前（可改 prompt） |
| `@filter.on_message_received()` | 消息刚入站（最早的钩子） |

### 指令冲突
两个插件注册同名 `@filter.command("weather")` 会导致只触发先注册的那个。修复：改其中一个的指令名 → reload。

## 4. LLM 请求（含会话锁）

源码：
- `astrbot/core/pipeline/llm_request/stage.py` —— 请求编排
- `astrbot/core/utils/session_lock.py` —— 会话锁
- `astrbot/core/provider/*.py` —— Provider 实现

### 会话锁机制（高频 debug 点）

```python
# session_lock.py 简化版
class SessionLock:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}  # 按 unified_msg_origin 分组

    async def acquire(self, unified_msg_origin: str) -> asyncio.Lock:
        lock = self._locks.setdefault(unified_msg_origin, asyncio.Lock())
        await lock.acquire()
        return lock
```

- 同一群（同一 `unified_msg_origin`）同一时间只能有一个 LLM 请求持锁
- 前一个请求没释放，后续请求阻塞在 `acquired session lock` 那行前

### 日志时序
| 顺序 | 日志 | 含义 |
|------|------|------|
| 1 | `ready to request llm provider` | LLM 请求准备就绪 |
| 2 | `acquired session lock for llm request` | 拿到锁（这步缺失 = 死锁） |
| 3 | `completion` | 上游 API 返回 |
| 4 | `Prepare to send` | 回复准备发送 |

```bash
# 查时序是否完整
python assets/ssh-exec.py log astrbot --since "30 min ago" --grep "ready to request\|acquired session lock\|completion\|Prepare to send"
```

### MiniMax 推理泄漏特殊性
`minimax_token_plan` 继承 `ProviderAnthropic`（非 OpenAI 源），缺 `<thought>` 标签剥离，
推理内容会泄漏进 `completion_text`。根因与修复详见 `references/debug-handbook.md` §4。

## 5. 回复发送（result handlers → adapter send）

源码：`astrbot/core/pipeline/result_handle/stage.py` + 适配器的 `send` 方法。

- LLM 结果会先过 `@filter.on_decorating_result` 钩子（插件可改写）
- 然后过 `_strip_markdown` 类后处理（如果插件加了）
- 最后交回适配器 `send`，转换为 OneBot 段发回 NapCat

如果 `completion` 后没 `Prepare to send`：插件 on_decorating_result 把消息吞了，
或 `platform_settings.ignore_bot_self_message` 误开。

## 配合 ssh-exec 的端到端追踪命令

```bash
# 查一条具体消息从收到到发送的全过程
python assets/ssh-exec.py log astrbot --since "10 min ago" --grep "unified_msg_origin=<群ID>"
# 上面命令会把该群所有 stage 日志串起来，便于看卡在哪步
```

## 关键源码定位小抄

| 想查什么 | 文件 |
|---------|------|
| 唤醒规则 | `astrbot/core/pipeline/waking_check/stage.py` |
| 指令分发 | `astrbot/core/pipeline/decorator_handle/stage.py` |
| LLM 请求编排 | `astrbot/core/pipeline/llm_request/stage.py` |
| 会话锁实现 | `astrbot/core/utils/session_lock.py` |
| 回复处理 | `astrbot/core/pipeline/result_handle/stage.py` |
| aiocqhttp 适配器 | `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py` |
| 插件注册装饰器 | `astrbot/api/star/__init__.py`（`@register`、`@filter`） |

要读取具体源码（在不确定某个判定时）：
```bash
python assets/ssh-exec.py exec "grep -n 'isinstance.*At' /opt/astrbot/.venv/lib/python*/site-packages/astrbot/core/pipeline/waking_check/stage.py 2>/dev/null || find / -path '*/astrbot/core/pipeline/waking_check/stage.py' 2>/dev/null | head -1 | xargs grep -n 'isinstance.*At'"
```
