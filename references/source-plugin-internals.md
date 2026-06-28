# AstrBot 插件内部源码精华

按需加载此文件：当需要理解插件加载/重载/卸载/注册的内部机制时使用。配合
`references/plugin-lifecycle.md`（操作 SOP）和 `references/debug-handbook.md` §1（加载失败）一起看。

## 1. 插件注册：`@register` 装饰器

源码：`astrbot/api/star/__init__.py`

```python
def register(name, author, desc, *, version="1.0.0", repo=None):
    def deco(cls):
        cls.metadata = {
            "name": name, "author": author, "desc": desc,
            "version": version, "repo": repo,
        }
        StarRegistry.register(cls)   # 注册到全局 star_registry
        return cls
    return deco
```

要点：
- `@register` 装饰类时只是把类放进 `star_registry`，**不实例化**
- 实际实例化由 `StarManager.load()` 在加载插件时完成
- 类必须继承 `Star`，否则不会作为插件加载

## 2. `@filter.*` 装饰器（指令/钩子注册）

源码：`astrbot/api/event/filter/__init__.py`

| 装饰器 | 注册到 | 触发时机 |
|--------|--------|---------|
| `@filter.command("xxx")` | `command_handlers` | message_obj 以 `xxx` 开头 |
| `@filter.regex(pattern)` | `regex_handlers` | 文本匹配正则 |
| `@filter.on_llm_request()` | `llm_request_hooks` | LLM 请求前 |
| `@filter.on_decorating_result()` | `decorating_result_hooks` | LLM 结果回包后 |
| `@filter.on_message_received()` | `message_received_hooks` | 最早入站钩子 |

**调试要点**：两个插件注册同名 `@filter.command("weather")` 会冲突，只触发先注册的那个。
找不到触发原因时检查所有已加载插件的 `command` 列表。

## 3. StarManager 加载流程

源码：`astrbot/core/star/star_manager.py`

### `load()` —— 加载单个插件

```
load(plugin_path):
    1. 读 metadata.yaml → 验证字段（name/desc/version/author 必填）
    2. 检查 astrbot_version 约束（PEP 440）
    3. _ensure_plugin_requirements() — pip install -r requirements.txt
    4. importlib 加载 main.py
    5. 找到 @register 装饰的类，实例化（传入 config dict）
    6. star_map[plugin_name] = instance
    7. 调用 instance.on_load()（如果定义了）
```

### `_ensure_plugin_requirements()` —— 依赖安装

- 用 uv 部署时 Python 解释器路径：`/root/.local/share/uv/tools/astrbot/bin/python`
- 命令：`<python> -m pip install -r requirements.txt`
- 失败原因常见：缺 `requirements.txt` 文件 / 依赖名拼错 / 网络不通

### 加载失败时的报错映射

| 报错 | 源码位置 / 原因 |
|------|---------------|
| `yaml.parser.ParserError` | `metadata.yaml` 语法错（如 `help` 字段以 `[` 开头） |
| `Unexpected UTF-8 BOM` | metadata.yaml / _conf_schema.json / main.py 有 BOM 头 |
| `ModuleNotFoundError: No module named 'xxx'` | `_ensure_plugin_requirements` 失败 / requirements.txt 缺依赖 |
| `class X is not a subclass of Star` | main.py 的类没继承 `Star` |
| `metadata.yaml not found` | 插件目录结构错（必须在根目录有 metadata.yaml） |

## 4. 重载流程：`reload()`

源码：`astrbot/core/star/star_manager.py`（约 line 842 引用 `_pm_lock`）

```
reload(name):
    async with _pm_lock:               # 全局插件管理锁
        instance = star_map[name]
        _terminate_plugin(instance)    # 调 terminate() + 释放资源
        _unbind_plugin(instance)       # 从 star_registry、command_handlers 等移除
        load(plugin_path)              # 重新走 load 流程
```

**重要**：
- 重载会**完整**重新读 metadata.yaml、main.py、_conf_schema.json
- 修改任何插件文件后用 reload 即可生效，**无需重启机器人**
- 重载期间该插件短暂不可用，但其他插件和机器人主进程不受影响

### API 端点
```bash
POST /api/plugin/reload  {"name": "<plugin>"}    # 重载指定
POST /api/plugin/reload  {}                      # 重载全部
POST /api/plugin/reload-failed                   # 重载上次失败的
```
（详见 `references/plugin-lifecycle.md`）

## 5. 安装/卸载流程

### `install()`

源码：`star_manager.py`（约 line 1386）

```
install(repo_url, proxy=""):
    1. 解析 GitHub URL → 仓库名
    2. git clone 到 plugin_store_path（{data_dir}/addons/plugins/<repo_name>/）
    3. _ensure_plugin_requirements()
    4. load()
```

### `uninstall()`

```
uninstall(plugin_name, delete_config=False, delete_data=False):
    1. _terminate_plugin(instance)
    2. _unbind_plugin(instance)
    3. 删除插件目录（可选 delete_config / delete_data）
```

**注意**：删除插件目录不会自动清理 `plugin_data/<name>/`（除非 `delete_data=true`），
持久化数据默认保留。

## 6. 插件配置：`_conf_schema.json`

源码：`astrbot/core/config/plugin_config.py`（schema 解析） + WebUI 渲染。

- 路径：插件根目录 `_conf_schema.json`
- 结构：`{"config_items": [{"key":"x","type":"string","default":"...","description":"..."}]}`
- 加载时 schema 转为默认值 dict，传给插件 `__init__(config: dict)`
- 用户在 WebUI 修改配置 → 写入 `data/plugin_configs/<plugin_name>.json`
- 下次重载时读 `data/plugin_configs/<plugin_name>.json` 覆盖默认值

详细 type 支持（`int` / `float` / `bool` / `string` / `text` / `list` / `file` /
`object` / `template_list`）和 `options` 数组下拉菜单语法，见
`references/source-config-schema.md`。

## 7. 插件目录结构

路径基线见 `references/config-reference.md`。单个插件目录内部结构：

```
<plugin_install_dir>/<plugin_name>/
  main.py
  metadata.yaml
  requirements.txt
  _conf_schema.json            # 可选
  logo.png                     # 可选
  tests/                       # 可选

<plugin_config_dir>/<plugin_name>.json    # 用户配置（运行时生成）
<plugin_data_dir>/<plugin_name>/          # 持久化数据目录
```

## 8. 热修改工作流（源码视角）

```
本地改 main.py
   ↓ git push（可选）
   ↓ SFTP 同步到 /opt/astrbot/data/addons/plugins/<name>/main.py
   ↓ POST /api/plugin/reload {"name": "<name>"}
   ↓ _pm_lock 锁住
   ↓ _terminate_plugin → _unbind_plugin → load()
   ↓ 新实例就绪，新代码生效
```

**没有重启机器人**。这就是为什么 SKILL.md 反复强调：能用 reload 就不要 restart。

## 9. 关键源码定位小抄

| 想查什么 | 文件 |
|---------|------|
| `@register` 装饰器实现 | `astrbot/api/star/__init__.py` |
| `@filter.*` 装饰器 | `astrbot/api/event/filter/__init__.py` |
| 插件加载/重载/卸载核心逻辑 | `astrbot/core/star/star_manager.py` |
| 依赖安装 | `star_manager.py::_ensure_plugin_requirements` |
| 插件配置 schema 解析 | `astrbot/core/config/plugin_config.py` |
| Star 基类 | `astrbot/api/star/star.py`（或同目录） |

要 SSH 查具体源码：
```bash
python assets/ssh-exec.py exec "find / -path '*/astrbot/core/star/star_manager.py' 2>/dev/null | head -1 | xargs grep -n 'def reload'"
python assets/ssh-exec.py exec "find / -path '*/astrbot/api/star/__init__.py' 2>/dev/null | head -1 | xargs cat"
```
