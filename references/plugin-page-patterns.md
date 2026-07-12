# AstrBot Plugin Page 开发模式（必读）

> 写带 WebUI Page 的 AstrBot 插件前必须读完本文。所有模式来自对
> `meme_manager` 和 `smart_imagechat_hub` 两个成熟插件的逆向分析。

## 0. 关键约束速记

| 约束 | 说明 |
|------|------|
| 沙箱 iframe | page 运行在 sandboxed iframe，无 `allow-modals` 权限 |
| `window.confirm()` | **不可用**，必须用自定义 DOM 确认框 |
| `<img src>` 直连 | **不可直接请求 /api/plug/...**，不带 auth cookie 会被拦截 |
| bridge SDK | 所有后端通信必须通过 `window.AstrBotPluginPage` |
| FastAPI 底层 | AstrBot 用 FastAPI/Starlette，插件兼容层模拟 Quart |
| 路由注册 | 用 `context.register_web_api()`，handler 是 bound method |

## 1. 架构模式：Mixin 类 + bound method

**不要**用独立模块函数 + `_bind` 闭包包装。**必须**用 Mixin 类，与 `Star` 一起继承：

```python
# core/api.py
class WebApiMixin:
    manager: MemeManager  # 由主类提供

    def _register_webui_api(self, route: str, handler, methods: list[str], desc: str):
        """与 meme_manager 完全一致的包装模式"""
        route_path = f"/{PLUGIN_NAME}/{route.strip('/')}"

        async def logged_handler(*args, **kwargs):
            # logging, error handling...
            response = await handler(*args, **kwargs)
            return response

        logged_handler.__name__ = f"webui_{handler.__name__}"
        self.context.register_web_api(route_path, logged_handler, methods, desc)

    def _register_web_apis(self) -> None:
        """在 __init__ 中调用，不是 initialize"""
        self._register_webui_api("groups", self._api_groups, ["GET", "POST"], "...")
        self._register_webui_api("groups/<name>/delete", self._api_delete_group, ["POST"], "...")
        # ...

    async def _api_groups(self):
        # handler 作为 bound method，self.manager 直接可用
        ...
```

```python
# main.py
from .core.api import WebApiMixin

class RandomMemePlugin(Star, WebApiMixin):
    def __init__(self, context, config):
        super().__init__(context)
        self.manager = MemeManager(...)
        self._register_web_apis()  # 在 __init__ 注册，不是 initialize
```

关键点：
- handler 是 `self._api_xxx` bound method，框架调用时 `self` 自动绑定
- `logged_handler(*args, **kwargs)` 同时接受 positional 和 keyword 参数
- 在 `__init__` 注册路由（与 meme_manager / smart_imagechat_hub 一致）

## 2. Bridge SDK 正确用法

bridge SDK 通过 `window.AstrBotPluginPage` 暴露，通信基于 postMessage。

### 2.1 GET 请求

```js
// ✅ 正确：第二个参数是 query 字典对象
const data = await bridge.apiGet("stats");
const data = await bridge.apiGet("images/data", { name: group, filename: file });

// ❌ 错误：手动拼 query string
const data = await bridge.apiGet(`images/data?name=${encodeURIComponent(group)}`);
```

`apiGet(endpoint, params)` 中 `params` 由 dashboard 自动转为 HTTP query string。

### 2.2 POST 请求

```js
// ✅ 正确
const data = await bridge.apiPost("groups", { name, aliases, require_wake });
const data = await bridge.apiPost("groups/mygroup/delete");
```

### 2.3 文件上传

**不要用 `bridge.upload()`！** 它通过 postMessage 传 ArrayBuffer → dashboard 重建请求，
可能触发 `ERR_ACCESS_DENIED`。改用 base64 + apiPost：

```js
// ✅ 正确：base64 编码 + apiPost
function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error || new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

async function handleUploadFiles(files) {
  for (const file of files) {
    const base64 = await readFileAsBase64(file);
    await bridge.apiPost("groups/mygroup/images", {
      filename: file.name,
      mime_type: file.type || "image/png",
      content_base64: base64,
    });
  }
}
```

后端需要同时支持 base64 JSON 和 multipart 两种格式。

### 2.4 响应格式

bridge SDK **不自动解包** `{status:"ok", data:{...}}`。如果后端用包裹格式，前端必须解包：

```js
function unwrap(payload) {
  if (payload && typeof payload === "object" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

// 使用
const result = unwrap(await bridge.apiGet("groups"));
state.groups = result.groups || [];
```

或者后端直接返回 plain JSON（像 meme_manager 那样），不使用包裹。

## 3. 预览图（关键）

### 3.1 不能直接 `<img src="/api/plug/...">`

沙箱 iframe 中 `<img>` 标签直接请求不带 auth cookie，会被 401/403。

### 3.2 正确方式：bridge API + base64 data URL

**后端**（使用 query 参数，不是路径参数）：

```python
# 路由注册（无路径参数）
self._register_webui_api("images/data", self._api_image_data, ["GET"], "...")

# handler 从 query 参数读取
async def _api_image_data(self):
    name = request.args.get("name") or ""
    filename = request.args.get("filename") or ""
    # ...读取文件...
    payload = await asyncio.to_thread(target.read_bytes)
    encoded = base64.b64encode(payload).decode("ascii")
    return jsonify({
        "data_url": f"data:{mime_type};base64,{encoded}",
    })
```

**前端**（使用 apiGet 的 params 参数）：

```js
async function loadImageData(group, filename) {
  const result = await bridge.apiGet("images/data", {
    name: group,
    filename: filename,
  });
  return result.data_url;  // "data:image/png;base64,..."
}

// 使用
loadImageData(group, filename).then((dataUrl) => {
  img.src = dataUrl;
});
```

### 3.3 为什么用 query 参数而非路径参数

- 路径参数中的中文文件名会产生编码问题
- `<path:filename>` 是贪婪匹配，会吞噬后续路径段
- query 参数由 bridge SDK 的 `params` 字典自动处理编码

## 4. 自定义确认对话框

沙箱 iframe 禁用了 `window.confirm()`，必须用 DOM 自定义：

```html
<!-- index.html -->
<div class="dialog-backdrop" id="confirm-dialog" hidden>
  <div class="dialog" role="alertdialog" aria-modal="true">
    <h2 id="confirm-title">确认操作</h2>
    <p id="confirm-message"></p>
    <div class="dialog-actions">
      <button type="button" class="btn" id="btn-confirm-cancel">取消</button>
      <button type="button" class="btn danger" id="btn-confirm-ok">确认</button>
    </div>
  </div>
</div>
```

```js
function showConfirm(title, message) {
  return new Promise((resolve) => {
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    $("#confirm-dialog").hidden = false;
    function cleanup(result) {
      $("#confirm-dialog").hidden = true;
      resolve(result);
    }
    $("#btn-confirm-ok").onclick = () => cleanup(true);
    $("#btn-confirm-cancel").onclick = () => cleanup(false);
  });
}

// 使用
async function onDeleteGroup(g) {
  if (!await showConfirm("删除组别", `确定删除 "${g.name}"？`)) return;
  // ...执行删除...
}
```

## 5. 路由注意事项

### 5.1 不要同路径注册多个 handler

```python
# ❌ 错误：同一路径注册两次
("/groups", list_groups, ["GET"])
("/groups", create_group, ["POST"])

# ✅ 正确：合并为单 handler，内部按 method 分发
("/groups", handle_groups, ["GET", "POST"])
```

### 5.2 `<path:...>` 贪婪路由必须在精确路由之后

```python
# ✅ 正确顺序：精确路由在前
self._register_webui_api("groups/<name>/images/data/<filename>", ...)
self._register_webui_api("groups/<name>/images/<path:filename>", ...)

# ❌ 错误：贪婪路由在前会吞噬精确路由
self._register_webui_api("groups/<name>/images/<path:filename>", ...)
self._register_webui_api("groups/<name>/images/data/<filename>", ...)
```

### 5.3 不要用 `<path:filename>` 作为 data 预览路由

预览图参数应该走 query string（见 §3），不要放路径里。

## 6. 完整前端模式总结

```js
const bridge = window.AstrBotPluginPage;

// 初始化
await bridge.ready();

// 读取数据 — params 是对象
const result = unwrap(await bridge.apiGet("groups"));
const result = await bridge.apiGet("images/data", { name, filename });

// 修改数据 — body 是对象
await bridge.apiPost("groups/mygroup/delete");
await bridge.apiPost("groups/mygroup/update", { aliases, enabled });

// 上传 — base64 + apiPost
const base64 = await readFileAsBase64(file);
await bridge.apiPost("groups/mygroup/images", { content_base64: base64, ... });

// 确认 — 自定义 DOM
if (!await showConfirm("标题", "消息")) return;
```

## 7. 开发前检查清单

- [ ] 已读 meme_manager 的 `mixins/web_api.py` + `pages/a_manage/script.js`
- [ ] 已读 smart_imagechat_hub 的 `backend/web_api.py` + frontend
- [ ] 架构：Mixin 类 + `_register_webui_api` + `logged_handler` 模式
- [ ] 所有 `confirm()` 替换为自定义 DOM 对话框
- [ ] 预览图走 bridge API 拉取 base64，不直接 `<img src>`
- [ ] 上传用 `bridge.apiPost` + base64，不用 `bridge.upload()`
- [ ] 响应格式前后端一致（要么都不包裹，要么前端 unwrap）
- [ ] 路由不重复注册同路径，贪婪路由在精确路由之后
- [ ] 前端 `apiGet` 第二个参数传对象而非拼 query string
