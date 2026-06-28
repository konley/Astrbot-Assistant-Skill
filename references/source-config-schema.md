# AstrBot 配置 Schema 详解

按需加载此文件：当涉及 `cmd_config.json` 字段、`_conf_schema.json` 类型、 provider
/ platform 配置项时使用。配合 `assets/config-tool.py`（远程读写 cmd_config.json）和
`assets/plugin-scaffold.py`（生成 _conf_schema.json）一起看。

## 1. `cmd_config.json` 顶层结构

路径（生产）：`/opt/astrbot/data/cmd_config.json`
本地开发：`<repo>/AstrBot/data/cmd_config.json`

```jsonc
{
  "dashboard": { ... },           // 仪表盘配置
  "platform": [ ... ],            // 平台适配器数组（aiocqhttp / qq_official / telegram ...）
  "provider": [ ... ],            // LLM Provider 数组
  "platform_settings": { ... },   // 全局消息处理开关
  "wake_prefix": "",              // 唤醒前缀
  "wake_prefix_blacklist": [],
  "empty_mention_waiting": true,  // 纯 @无文字 60s 等待
  "persona": { ... },             // 人格 prompt
  "provider_settings": { ... },   // 全局 LLM 设置
  "plugin": [ ... ]               // 插件层全局配置
}
```

### `dashboard` 字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `port` | int | 6185 | WebUI 端口 |
| `api_key` | string | "" | OpenAPI / WebUI API 的 X-API-Key 鉴权 |
| `username` | string | "" | WebUI 登录用户名 |
| `password` | string | "" | WebUI 登录密码 |

### `platform` 数组字段（按 `type` 区分）

#### `type: "aiocqhttp"`（对接 NapCat，反向 WS）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `id` | string | "aiocqhttp-default" | 适配器实例 ID |
| `type` | string | "aiocqhttp" | 适配器类型 |
| `enable` | bool | true | 是否启用 |
| `ws_reverse_host` | string | "0.0.0.0" | 反向 WS 监听地址 |
| `ws_reverse_port` | int | 6199 | 反向 WS 监听端口 |
| `ws_reverse_token` | string | "" | 反向 WS 鉴权 token（NapCat 端要一致） |

> NapCat 端反向 WebSocket 地址必须含 `/ws` 路径：`ws://127.0.0.1:6199/ws`，否则 405。

#### `type: "qq_official"`（QQ 官方 API）

含 `bot_app_id` / `bot_secret` / `sandbox` 等字段。

#### 其他类型

`telegram` / `wecom` / `lark` / `dingtalk` / `discord` / `slack` / `kook` / `vocechat` /
`weixin_official_account` / `satori` / `misskey` / `line` 各自有专属字段，详见官方文档：
https://docs.astrbot.app

### `provider` 数组字段（按 `type` 区分）

| 通用字段 | 说明 |
|---------|------|
| `id` | Provider 实例 ID |
| `type` | `openai_chat_completion` / `anthropic` / `minimax_token_plan` / ... |
| `api_key` | 上游 API Key |
| `api_base` | 自定义 API 基址 |
| `model_config` | 模型名（如 `gpt-4o` / `abab6.5s-chat`） |
| `request_timeout` | 请求超时（秒） |
| `concurrent_limiter` | 并发上限 |

#### `type: "minimax_token_plan"` 特殊字段（推理泄漏相关）

| 字段 | 类型 | 说明 |
|------|------|------|
| `reasoning` | bool | 启用推理模式 |
| `anth_thinking_config` | object | 推理预算 `{"type":"enabled","budget":2048}`；为 `{"type":"","budget":0}` 时会泄漏推理内容到正文 |
| `display_reasoning_text` | bool | 是否在 UI 显示推理（对泄漏无效） |

> 详见 `references/debug-handbook.md` §4。

### `platform_settings` 常用字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `ignore_bot_self_message` | bool | true | 忽略机器人自己发的消息（防回环） |
| `reply_with_mention` | bool | false | 回复时 @发送者 |
| `enable_id_revert` | bool | true | ID 还原（平台 ID → 显示名） |
| `websocket_buffer_size` | int | 16 | WS 缓冲大小 |

### 唤醒相关全局字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `wake_prefix` | string | "" | 前缀唤醒（如 `/`） |
| `wake_prefix_blacklist` | list | [] | 不参与前缀唤醒的指令 |
| `empty_mention_waiting` | bool | true | 纯 @无文字 60s 等待 |

> @唤醒独立于这些字段，走 `isinstance(message, At)` 判定。详见
> `references/source-message-flow.md` §2。

## 2. `_conf_schema.json` 插件配置 Schema

路径：插件根目录 `_conf_schema.json`。可选，用于让 WebUI 渲染配置面板。

### 结构

```json
{
  "config_items": [
    {
      "key": "city_default",
      "description": "默认城市",
      "type": "string",
      "default": "北京",
      "hint": "查询天气时的默认城市",
      "options": ["北京", "上海", "广州"]
    }
  ]
}
```

### 支持的 `type`

| type | 用途 | default 例子 |
|------|------|------------|
| `int` | 整数 | `0` |
| `float` | 浮点 | `0.5` |
| `bool` | 布尔 | `false` |
| `string` | 字符串（单行） | `"北京"` |
| `text` | 多行文本 | `"long..."` |
| `list` | 列表 | `["a", "b"]` |
| `file` | 文件路径（WebUI 上传） | `""` |
| `object` | 嵌套对象 | `{}` |
| `template_list` | 模板列表（高级） | `[]` |

### `options` 数组（下拉菜单）

`type: "string"` 配合 `options: ["a", "b", "c"]` 在 WebUI 渲染为下拉菜单：

```json
{
  "key": "tone",
  "description": "辞气",
  "type": "string",
  "default": "自动",
  "options": ["自动", "温言", "辩经"],
  "hint": "选择辞气风格"
}
```

> ⚠️ **不支持** `choices` 字段，**不支持** `type: "select"`。这是 AstrBot 的硬约束，常踩坑。

### 其他字段

| 字段 | 说明 |
|------|------|
| `key` | 配置键（snake_case），插件 `__init__(config)` 里 `config[key]` 读取 |
| `description` | WebUI 显示的说明 |
| `default` | 默认值（用户没改时用这个） |
| `hint` | WebUI 输入框下的提示语（可选） |
| `options` | 仅 `type: "string"` 时支持下拉菜单 |
| `obvious` | bool，是否在 WebUI 突出显示（可选） |

### 运行时读取流程

1. 插件加载时，schema 的 `default` 组成初始 config dict
2. 若 `data/plugin_configs/<plugin>.json` 存在，覆盖默认值
3. 用户在 WebUI 修改配置 → 写入 `data/plugin_configs/<plugin>.json`
4. 重载插件时读 `<plugin>.json` 覆盖默认值，传给 `__init__`

```python
class MyPlugin(Star):
    def __init__(self, config: dict | None = None):
        super().__init__()
        self.config = config or {}
        self.city = self.config.get("city_default", "北京")
```

> 修改配置后**重载插件**即可生效，无需重启机器人。

## 3. 用 config-tool.py 改 cmd_config.json（速查）

```bash
# 完整 dump
python assets/config-tool.py show
# 读字段
python assets/config-tool.py get dashboard.port
python assets/config-tool.py get platform.0.ws_reverse_port
python assets/config-tool.py get provider.0.api_key
# 改字段（自动类型推断）
python assets/config-tool.py set dashboard.port 62124
python assets/config-tool.py set platform.0.enable true
# 批量改
python assets/config-tool.py patch '{"dashboard.port":62124,"platform.0.enable":true}'
# 删字段
python assets/config-tool.py unset persona.temp_key
# 备份
python assets/config-tool.py backup --local cmd_config.bak.json
```

要点：
- **绝不**用 sed 改 JSON（会破坏引号/逗号，见 `references/troubleshooting.md` #15）
- 改完核心配置（platform / provider / dashboard）后**必须 restart astrbot**，且
  **必须征得用户确认**（影响核心生命周期）
- 改 `wake_prefix` / `empty_mention_waiting` 等运行时项也要 restart 才生效
- 插件配置（`plugin_configs/*.json`）改完只需要 reload，不要 restart

## 4. 常见配置陷阱

| 陷阱 | 原因 | 解决 |
|------|------|------|
| 改了端口不生效 | 改 `dashboard.port` 后没 restart | restart astrbot（需用户确认） |
| NapCat 连 405 | 反向 WS 地址缺 `/ws` | NapCat 端改为 `ws://IP:PORT/ws` |
| webui.json 端口不生效（仍是 6099） | 文件有 BOM | 用 `ssh-exec.py write` 重写无 BOM |
| `support_platforms` 不识别 | 用了 `choices` 或 `type:"select"` | 改用 `type:"string"` + `options` 数组 |
| 插件配置改了不生效 | 改了 plugin_configs 但没 reload | `astrbot-api.py plugins reload --name X` |
| MiniMax 推理混入正文 | `anth_thinking_config` 未启用 | `config-tool.py set provider.0.anth_thinking_config '{"type":"enabled","budget":2048}'` |

## 5. 完整 provider 示例（MiniMax + 推理修复后）

```jsonc
{
  "id": "minimax-token-plan",
  "type": "minimax_token_plan",
  "api_key": "eyJ...xxx",
  "model_config": "abab6.5s-chat",
  "request_timeout": 120,
  "reasoning": true,
  "anth_thinking_config": {
    "type": "enabled",
    "budget": 2048
  },
  "display_reasoning_text": false
}
```

## 6. 完整 platform 示例（aiocqhttp 对接 NapCat）

```jsonc
{
  "id": "aiocqhttp-default",
  "type": "aiocqhttp",
  "enable": true,
  "ws_reverse_host": "0.0.0.0",
  "ws_reverse_port": 6199,
  "ws_reverse_token": ""
}
```

NapCat 端反向 WS 地址：`ws://127.0.0.1:6199/ws`（**必须带 `/ws`**）
