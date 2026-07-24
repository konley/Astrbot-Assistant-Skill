# AstrBot Agent / Tools 速查

> **权威声明**：写依赖框架 API 的代码前，先 `python scripts/ssh-exec.py framework check`。
> 本文覆盖 **LLM Tool / tool_loop_agent / cron / persona / subagent / Agent hooks**。
> 签名以对齐后的 `./AstrBot/` 为准；本文不是自动同步的官方镜像。

配合：`api-cheatsheet.md`（通用 API）· `source-plugin-internals.md`（加载机制）。

## 0. 两层 hook（先分清）

| 层 | 用途 | 典型 API |
|----|------|----------|
| **插件事件层** | 消息指令、入站/出站、LLM 请求包装 | `@filter.command` / `@filter.llm_tool` / `@filter.on_llm_request` |
| **Agent 运行层** | tool-loop 执行过程回调 | `BaseAgentRunHooks`：`on_agent_begin/on_tool_start/on_tool_end/on_agent_done` |

- 写“用户发指令触发” → 插件事件层  
- 写“LLM 调 tool 前后插桩” → Agent 运行层（传给 `tool_loop_agent(..., agent_hooks=...)`）  
- **禁止**把 `BaseAgentRunHooks` 当成 `@filter` 装饰器使用

## 1. 注册 LLM Tool

### 1.1 推荐：FunctionTool dataclass（v4.5.7+）

源码：`astrbot/core/agent/tool.py` · 注册：`Context.add_llm_tools`

```python
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import FunctionTool
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext

@dataclass
class WeatherTool(FunctionTool[AstrAgentContext]):
    name: str = "weather"
    description: str = "查询城市天气"
    parameters: dict = Field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名"},
        },
        "required": ["city"],
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        city = kwargs.get("city", "")
        return f"{city}: sunny"

@register("astrbot_plugin_weather", "you", "weather tool", version="0.1.0")
class WeatherPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.context.add_llm_tools(WeatherTool())
```

规则：
- `parameters` 必须是 **JSON Schema object**
- `call` / handler 必须是 **async**
- 返回尽量 `str`（或 MCP CallToolResult）
- 密钥/模型 ID 走 `_conf_schema.json`，不要写死

### 1.2 兼容：`@filter.llm_tool`

```python
@filter.llm_tool(name="weather")
async def weather(self, event, city: str) -> str:
    """查询天气。
    Args:
        city(string): 城市名
    """
    return f"{city}: sunny"
```

- docstring 会被解析成 tool 描述/参数说明  
- **不要**再叠 `@filter.permission_type`（对 llm_tool 无效）

### 1.3 启停 / 注销

```python
mgr = self.context.get_llm_tool_manager()
self.context.activate_llm_tool("weather")
self.context.deactivate_llm_tool("weather")
self.context.unregister_llm_tool("weather")
```

## 2. 直接调 LLM / Tool Loop

```python
umo = event.unified_msg_origin
prov_id = await self.context.get_current_chat_provider_id(umo)

# 单次生成（不自动执行 tools）
resp = await self.context.llm_generate(
    chat_provider_id=prov_id,
    prompt="summarize this",
    system_prompt="be brief",
)

# 自动 tool 循环（可带 agent_hooks）
from astrbot.core.agent.tool import ToolSet
from astrbot.core.agent.hooks import BaseAgentRunHooks

class MyHooks(BaseAgentRunHooks):
    async def on_tool_start(self, run_context, tool, tool_args):
        ...

resp = await self.context.tool_loop_agent(
    event=event,
    chat_provider_id=prov_id,
    prompt=event.message_str,
    tools=ToolSet(tools=[WeatherTool()]),
    system_prompt="use tools when needed",
    max_steps=30,
    tool_call_timeout=120,
    agent_hooks=MyHooks(),
)
```

注意：
- `tool_loop_agent` 需要 `event`
- `max_steps` / `tool_call_timeout` 防止死循环
- provider 缺失会抛 `ProviderNotFoundError` / 同类异常——业务里要处理或转用户提示

## 3. Cron（定时）

入口：`self.context.cron_manager`（由 core lifecycle 注入）。

典型能力（以对齐后源码为准，符号名可能随版本微调）：
- 注册周期性 Python handler（basic job）
- 注册 AI 唤醒任务（active / agent job）
- 持久化 / 一次性 / 取消

实践约束：
- cron 表达式与时区以框架实现为准，先在测试实例验证
- handler 必须 async，避免阻塞 event loop
- payload 里的 session/UMO 要可解析
- 插件 `terminate` 时取消本插件创建的非持久任务，避免泄漏

查符号：

```text
./AstrBot/astrbot/** 中检索 CronJobManager / cron_manager / add_basic_job / add_active_job
```

## 4. Persona / 会话上下文

- 当前会话 provider：`await self.context.get_current_chat_provider_id(umo)`
- 会话历史 / 分支：`self.context.conversation_manager`（async 方法）
- 人格相关：通过 conversation / persona 管理器读写，**不要**直接改 `cmd_config.json` 里的 persona 大对象（生产改配置走 `config-tool.py`）

调试：
- UMO 用 `event.unified_msg_origin`
- 关注 `platform_settings.unique_session` 对 session 粒度的影响

## 5. Subagent / Handoff

框架侧有 subagent orchestrator 与 agent-as-tool（handoff）能力：
- 源码入口：`astrbot/core/agent/handoff.py`、`subagent_orchestrator`
- 常见模式：把子智能体包成 `FunctionTool`，在 `tool_loop_agent` 的 `ToolSet` 里暴露

约束：
- 明确 `max_steps` / 并发上限，防止递归 tool 爆炸
- 子 agent 的 tools 集合应小于父 agent（最小权限）
- 先在非生产实例验证，再 sync-plugin

## 6. Sandbox / Skills（运行时）

AstrBot 运行时 Skills / sandbox 与 **本 Codex skill** 不是同一概念：
- 运行时 Skills：用户在 WebUI 上传的 skill 包，由 `skill_manager` 管理
- 本仓库 skill：给 Agent/Codex 用的运维+工程助手

插件里若依赖运行时 Skills/MCP：
- 在 README 写清安装/启用步骤
- 配置项进 `_conf_schema.json`
- 不要在插件内再实现一套 MCP server（除非需求明确要求）

## 7. 调试清单

1. `framework check` 版本是否对齐  
2. tool 是否 `active=True`、名称是否冲突  
3. `@filter.llm_tool` docstring / parameters 是否可解析  
4. `tool_loop_agent` 是否传了正确 `event` 与 `chat_provider_id`  
5. 日志：`ssh-exec.py log astrbot --profile llm` / `--profile plugin`  
6. 重载：`astrbot-api.py --via-ssh plugins reload --name <name>`（不要动不动重启）

## 8. 相关路由

| 需求 | 读 |
|------|----|
| 通用 API / 消息 / schema | `api-cheatsheet.md` |
| 插件加载/重载机制 | `source-plugin-internals.md` / `plugin-lifecycle.md` |
| 远程不回复 / LLM 失败 | `debug-handbook.md` |
| 新建插件流程 | `plugin-dev-playbook.md` |
