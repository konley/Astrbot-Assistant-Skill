# AstrBot 插件 API 速查

> **权威声明**：写依赖框架 API 的代码前，先 `python scripts/ssh-exec.py framework check`。
> 本文是**可调用符号速查**，不是生产权威；行号/签名可能漂移。
> 以对齐后的 `./AstrBot/` 与远端 runtime 为准。细节见 `source-version-align.md`。
>
> 风格：代码优先、无废话。机制深读见 `source-plugin-internals.md` / `source-message-flow.md`。

## 1. 插件骨架

```python
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

@register("astrbot_plugin_demo", "author", "desc", version="0.1.0", repo="https://github.com/you/demo")
class Demo(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

    async def initialize(self) -> None:
        """插件激活后调用（可选）"""

    async def terminate(self) -> None:
        """卸载/重载前调用（可选，清理资源）"""

    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        yield event.plain_result("hi")
```

要点：
- 类必须继承 `Star`；`__init__(self, context, config=None)` + `super().__init__(context)`
- 被动回复：`yield event.plain_result(...)` / `yield event.chain_result([...])`
- 主动发送：`await event.send(...)` 或 `await self.context.send_message(umo, chain)`
- 生命周期方法名是 **`initialize` / `terminate`**（不是 `activate`）

## 1.5 日志（可观测性，必做）

```python
from astrbot.api import logger

logger.info("[astrbot_plugin_demo] initialize")
logger.info("[astrbot_plugin_demo] command=hello sender=%s", event.get_sender_name())
try:
    ...
except Exception:
    logger.exception("[astrbot_plugin_demo] command=hello failed")
    raise
```

约定：
- 只用 `astrbot.api.logger`，不要 `print` 当运行信号
- 前缀固定为 `[plugin_name]`，方便 `ssh-exec.py log ... --grep plugin_name`
- 至少：生命周期 + 关键 handler 入口 + 异常
- `plugin-check` 对缺失 logger / 裸 print 给 WARN


## 2. 常用 filter

| 装饰器 | 用途 |
|--------|------|
| `@filter.command("name")` | 指令（可用 alias/priority） |
| `@filter.command_group("g")` + `@g.command("sub")` | 指令组 |
| `@filter.regex(r"...")` | 正则 |
| `@filter.event_message_type(...)` | 私聊/群/全部 |
| `@filter.platform_adapter_type(...)` | 限制平台 |
| `@filter.permission_type(...)` | 权限（勿与 llm_tool 混用） |
| `@filter.llm_tool(name="x")` | 注册 LLM 工具（docstring 会被解析） |
| `@filter.on_llm_request()` | LLM 请求前 |
| `@filter.on_llm_response()` | LLM 响应后 |
| `@filter.on_decorating_result()` | 结果装扮前 |
| `@filter.after_message_sent()` | 消息发出后 |
| `@filter.on_message_received()` | 最早入站 |

特殊 hook（`on_llm_*` / `on_decorating_result` / `after_message_sent`）里用 `await event.send(...)`，不要 `yield`。

## 3. 消息

```python
event.message_str                 # 纯文本
event.message_obj.message         # 消息链组件列表
event.message_obj.raw_message     # 平台原始载荷
event.unified_msg_origin          # UMO / 会话原点
event.get_sender_name()
event.get_messages()
```

组件：

```python
import astrbot.api.message_components as Comp
Comp.Plain("text")
Comp.At(qq=123)
Comp.Image.fromURL(url) / Comp.Image.fromFileSystem(path)
Comp.Record.fromFileSystem(path)
Comp.Video.fromURL(url) / Comp.Video.fromFileSystem(path)
Comp.Reply(id=msg_id)
```

结果：

```python
yield event.plain_result("text")
yield event.image_result("https://.../a.png")   # http→URL，否则本地路径
yield event.chain_result([Comp.Plain("a"), Comp.At(qq=1)])
```

## 4. Context 常用 API

```python
self.context.get_config(umo=None)
self.context.get_using_provider(umo=None)
await self.context.get_current_chat_provider_id(umo)   # v4.5.7+
await self.context.send_message(umo, chain)
self.context.get_platform(platform_type)
self.context.get_llm_tool_manager()
self.context.add_llm_tools(*tools)                    # FunctionTool 实例
self.context.register_web_api(path, handler, methods, desc)
self.context.conversation_manager
self.context.cron_manager
```

LLM 调用（v4.5.7+）：

```python
prov_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt="hi")
# 需要自动跑 tool 循环：
resp = await self.context.tool_loop_agent(
    event=event,
    chat_provider_id=prov_id,
    prompt="...",
    tools=tool_set,          # ToolSet | None
    system_prompt="...",
    max_steps=30,
    tool_call_timeout=120,
)
```

> `llm_generate` **不会**自动执行 tool call；要 tool 循环用 `tool_loop_agent`。

## 5. 存储 / 渲染 / 数据目录

```python
# 插件隔离 KV（Star / PluginKVStoreMixin）
await self.get_kv_data(key, default)
await self.put_kv_data(key, value)
await self.delete_kv_data(key)

# HTML / 文转图
await self.html_render(tmpl, data, return_url=True, options=None)
await self.text_to_image(text, return_url=True)

# 持久目录：data/plugin_data/{plugin_name}/
from astrbot.api.star import StarTools
data_dir = StarTools.get_data_dir()          # 或 get_data_dir("plugin_name")
```

## 6. `_conf_schema.json`

扁平 dict，**不要**外层 `config_items` 数组：

```json
{
  "city": {
    "description": "默认城市",
    "type": "string",
    "default": "北京",
    "hint": "可选说明",
    "options": ["北京", "上海"]
  }
}
```

支持 type：`int|float|bool|string|text|list|file|object|template_list`  
**不支持** `choices` / `type: "select"`。完整约束见 `source-config-schema.md`。

## 7. metadata.yaml 最小字段

必填：`name` / `desc` / `version` / `author`  
推荐：`repo` / `display_name` / `astrbot_version` / `support_platforms`

```yaml
name: astrbot_plugin_demo
display_name: Demo
desc: 一句话
version: 0.1.0
author: you
repo: https://github.com/you/astrbot_plugin_demo
astrbot_version: ">=4.16,<5"
support_platforms:
  - aiocqhttp
```

## 8. 分层：插件钩子 vs Agent 钩子

| 层 | 入口 | 文档 |
|----|------|------|
| 插件事件钩子 | `@filter.on_*` / `@filter.command` | 本文 §2 + `source-plugin-internals.md` |
| Agent 运行钩子 | `BaseAgentRunHooks` | `agent-tools.md` |

**不要混用两套 hook 模型。**

## 9. 相关文档路由

| 需求 | 读 |
|------|----|
| Tool / cron / subagent / persona | `agent-tools.md` |
| 新建/改插件流程 | `plugin-dev-playbook.md` |
| Page / WebUI | `plugin-page-patterns.md` |
| 加载失败排障 | `debug-handbook.md` §1 + `plugin-lifecycle.md` |
| 配置字段权威 | `source-config-schema.md` / `config-reference.md` |
