# AstrBot 插件生命周期管理：重载、重新安装 vs 重启

## 核心原则

**优先级：重载 >> 重新安装 >>> 重启机器人**

- 能重载解决就不要重启
- 能重新安装解决就不要重启
- **重启机器人必须征得用户确认**

## WebUI 插件管理 API 端点

所有 API 通过 AstrBot Dashboard（默认 `http://localhost:6185`）调用，路径前缀 `/api/`，鉴权头由 Dashboard 的 API Key 机制处理。

### 插件操作端点

| 路由 Key | 方法 | URL 路径 | 说明 |
|----------|------|----------|------|
| `plugin/reload` | POST | `/api/plugin/reload` | 重载指定插件（或全部） |
| `plugin/install` | POST | `/api/plugin/install` | 从仓库 URL 安装插件 |
| `plugin/uninstall` | POST | `/api/plugin/uninstall` | 卸载插件 |
| `plugin/update` | POST | `/api/plugin/update` | 更新单个插件 |
| `plugin/off` | POST | `/api/plugin/off` | 禁用插件 |
| `plugin/on` | POST | `/api/plugin/on` | 启用插件 |
| `plugin/reload-failed` | POST | `/api/plugin/reload-failed` | 重载加载失败的插件 |
| `plugin/uninstall-failed` | POST | `/api/plugin/uninstall-failed` | 卸载加载失败的插件 |

### 重载端点详情

**POST `/api/plugin/reload`**

请求体 JSON：
```json
{
  "name": "插件名称"  // 可选，省略则重载全部插件
}
```

实现逻辑（`star_manager.py:842`）：
1. 获取 `_pm_lock` 异步锁
2. 终止插件（`_terminate_plugin`）
3. 解绑插件（`_unbind_plugin`）— 从 `star_registry`、`star_map` 等移除
4. 重新加载（`load()`）— 重新读取文件、重新解析 metadata、重新执行插件代码

这确保**所有文件修改**都会被完整重新读取并执行。

### 安装端点详情

**POST `/api/plugin/install`**

请求体 JSON：
```json
{
  "repo_url": "https://github.com/user/astrbot_plugin_xxx",
  "proxy": "",            // 可选
  "ignore_version_check": false,  // 可选
  "download_url": ""      // 可选，直接下载地址
}
```

流程（`star_manager.py:1386`）：
1. 解析 GitHub URL → 获取仓库名
2. 下载插件到 `plugin_store_path`
3. 安装依赖（`_ensure_plugin_requirements`）
4. 调用 `load()` 加载插件

### 卸载端点详情

**POST `/api/plugin/uninstall`**

请求体 JSON：
```json
{
  "plugin_name": "插件名称",
  "delete_config": false,  // 是否删除插件配置文件
  "delete_data": false     // 是否删除插件数据
}
```

## 常见操作场景与 SOP

### 场景 1：修改已安装插件的源代码

**正确流程**：
1. SSH 到服务器，找到插件目录（通常 `{data_dir}/addons/plugins/{plugin_name}/`）
2. 修改源文件
3. 通过 OpenAPI 或 WebUI 触发重载：`POST /api/plugin/reload` `{"name": "插件名"}`
4. ✗ 不要重启机器人

### 场景 2：本地开发插件 → 部署到服务器

**正确流程**：
1. 在本地完成代码修改
2. 提交到 GitHub（`git add` → `git commit` → `git push`）
3. 通过 WebUI 的"插件市场"→ 重新安装，或调用 `POST /api/plugin/install` 重新安装
4. ✗ 不要重启机器人

### 场景 3：本地开发，未推送 GitHub，需要同步到服务器

**正确流程**：
1. SSH/SFTP 将本地修改的文件同步到服务器插件目录
2. 触发重载：`POST /api/plugin/reload` `{"name": "插件名"}`
3. ✗ 不要重启机器人

### 场景 4：修改插件配置

**正确流程**：
1. 在 WebUI 插件配置页面修改配置 → 保存时自动触发重载
2. 或直接编辑配置文件后调用 `POST /api/plugin/reload`
3. ✗ 不要重启机器人

## 何时需要重启机器人

以下情况**可能**需要重启（必须征得用户确认）：
- AstrBot 核心版本升级（`uv tool upgrade astrbot`）
- 修改 `cmd_config.json` 中影响核心生命周期的配置（如平台适配器、LLM Provider）
- 系统级别故障（进程僵死、内存泄漏等）

## 插件文件目录定位 SOP

1. AstrBot 数据目录：通常 `~/.local/share/astrbot/` 或 `~/.config/astrbot/`
2. 插件安装目录：`{data_dir}/addons/plugins/`
3. 插件配置目录：`{data_dir}/plugin_configs/`
4. 查找命令：
   ```bash
   # 查找数据目录
   cat /etc/systemd/system/astrbot*.service 2>/dev/null | grep ExecStart
   # 查找插件目录
   find / -path "*/addons/plugins" -type d 2>/dev/null | head -5
   # 搜索特定插件目录
   find /root -path "*/addons/plugins/插件名" -type d 2>/dev/null
   ```