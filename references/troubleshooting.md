# 常见问题排障

## 1. metadata.yaml 解析失败

**现象**：安装插件报错 `yaml.parser.ParserError: while parsing a block mapping`

**原因**：`help` 字段值以 `[` 开头，YAML 将其解释为列表开始符。

**解决**：给 `help` 字段值加双引号：

```yaml
# 错误
help: [占卜] 随机选取...

# 正确
help: "[占卜] 随机选取..."
```

## 2. WebSocket 连接返回 405

**现象**：NapCat 日志报 `[WebSocket Client] 反向WebSocket (ws://localhost:6199) 连接错误 Error: Unexpected server response: 405`

**原因**：NapCat 连接地址缺少 `/ws` 路径。

**解决**：将 NapCat 反向 WebSocket 地址从 `ws://localhost:6199` 改为 `ws://localhost:6199/ws`。

## 3. webui.json BOM 导致解析失败

**现象**：NapCat 启动时 WebUI 端口仍为默认 6099，忽略自定义配置。

**原因**：通过 Windows SFTP 上传的文件带有 UTF-8 BOM 头（`EF BB BF`），JSON 解析失败。

**解决**：
- 用 `printf` 命令写入文件（无 BOM）
- 或用 Python paramiko SFTP 写入时确保 `json.dumps` 不加 BOM
- 验证：`xxd webui.json | head -1`，首字节应为 `7b`（`{`）而非 `ef`

## 3.1 插件文件 BOM / Python 字符串语法导致加载失败

**现象一**：WebUI 安装插件报 `json.decoder.JSONDecodeError: Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)`，多见于 `_conf_schema.json`。

**现象二**：插件 `main.py` 报 `SyntaxError: invalid syntax. Perhaps you forgot a comma?`，多见于提示词字符串里夹带未转义的 ASCII 双引号（如 `"省流"`）。

**原因**：
- 在 Windows 上用编辑器/脚本写文件时引入了 UTF-8 BOM 头（`EF BB BF`），AstrBot 的 `json.loads` 零容忍。
- Python 字符串用 `"..."` 包裹，内部又出现 `"`，导致字符串提前结束。

**解决**：
1. **去 BOM**（PowerShell）：
   ```powershell
   $p="_conf_schema.json"
   $c=[IO.File]::ReadAllText($p).TrimStart([char]0xFEFF)
   [IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($false)))
   ```
2. **修字符串**：含 ASCII 双引号的行改用单引号包裹，例如
   `'请进行"省流"总结'` 而非 `"请进行"省流"总结"`。
3. **交付前批量自检**（见 `references/compliance-checklist.md` 的 Encoding & Syntax Pre-flight）：
   逐个对 `.json`/`.py`/`.yaml` 验证 BOM + `json.load` + `py_compile`，不要只编译改动过的单文件。

## 4. astrbot init 交互式提示卡住

**现象**：通过 SSH 非交互执行 `astrbot init` 时命令挂起无响应。

**原因**：`astrbot init` 有交互式确认提示 `[Y/n]`。

**解决**：使用 paramiko `invoke_shell()` + 自动检测并发送 `Y`。

## 5. PowerShell 传递含特殊字符的远程命令失败

**现象**：SSH 执行含 `$`、`"`、`{` 等字符的命令报错。

**原因**：PowerShell 对嵌套引号和特殊字符的处理与 bash 不同。

**解决**：
- 简单命令用分号 `;` 分隔（不要用 `&&`）
- 复杂内容（JSON、多行文件）用 SFTP 上传而非 heredoc
- 含双引号的 grep 模式改用 Python 脚本执行

## 6. AI 输出夹带 Markdown 格式

**现象**：插件调用 LLM 返回的结果包含 `**加粗**`、`#标题`、`*斜体*` 等 markdown 符号。

**解决**：
1. 在 prompt 中明确要求"不要使用任何 Markdown 格式"
2. 添加后处理函数清理 markdown 符号：

```python
def _strip_markdown(self, text: str) -> str:
    import re
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.+?)_{1,3}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
```

## 7. SSH 密码登录在 Windows 上无法自动化

**现象**：系统 `ssh.exe` 需要交互式输入密码，无法通过脚本自动传递。

**解决**：使用 Python `paramiko` 库实现 SSH 操作：
- `exec_command` 用于执行单条命令
- `invoke_shell` 用于交互式场景（如 `astrbot init`）
- `open_sftp` 用于文件上传

## 8. 端口被占用

**现象**：服务启动失败，日志显示端口已被占用。

**解决**：
```bash
# 查找占用进程
ss -tlnp | grep {端口}
# 或
lsof -i:{端口}

# 停止占用进程
kill {PID}
```

## 9. 插件依赖缺失导致安装失败

**现象**：WebUI 安装插件时报 `ModuleNotFoundError`，插件无法加载。

**原因**：插件缺少 `requirements.txt`，或依赖版本约束不正确。

**解决**：
- 在插件根目录创建 `requirements.txt`，列出所有第三方依赖
- 每行一个依赖，建议带版本约束（如 `httpx>=0.27.0`）
- 在 WebUI 插件管理中重新安装/重载

## 10. 插件持久化数据写入源目录

**现象**：插件升级后数据丢失，或插件目录被 git 管理时出现意外文件。

**原因**：插件将数据文件写在了自身源码目录而非 AstrBot data 目录。

**解决**：
- 使用 AstrBot 提供的 data 目录路径写入持久化数据
- 路径参考：`/opt/astrbot/data/plugin_data/{plugin_name}/`
- 不要在插件源码目录中创建 `data/`、`cache/` 等子目录

## 11. 插件中同步 HTTP 请求阻塞事件循环

**现象**：插件调用外部 API 时整个机器人卡顿无响应。

**原因**：使用了 `requests` 库的同步请求，阻塞了 asyncio 事件循环。

**解决**：
- 将 `requests` 替换为 `aiohttp` 或 `httpx` 的异步客户端
- 示例：
```python
# 错误 - 阻塞
import requests
resp = requests.get(url)

# 正确 - 异步
import aiohttp
async with aiohttp.ClientSession() as session:
    async with session.get(url) as resp:
        data = await resp.json()
```

## 12. OpenAPI 调用返回 401/403

**现象**：插件调用 AstrBot HTTP API 时返回 401 Unauthorized 或 403 Forbidden。

**原因**：缺少 `X-API-Key` 请求头，或 API Key 无效。

**解决**：
- 在请求头中添加 `X-API-Key: {your_api_key}`
- API Key 从配置或环境变量读取，不要硬编码
- 对 401/403 返回用户友好的错误提示
- 参考 `references/openapi-integration.md` 获取端点列表

## 13. metadata.yaml 的 astrbot_version 格式错误

**现象**：插件加载时版本校验失败。

**原因**：版本约束格式不符合 PEP 440，或带了 `v` 前缀。

**解决**：
```yaml
# 错误
astrbot_version: v4.17.0
astrbot_version: 4.17

# 正确
astrbot_version: ">=4.17.0"
astrbot_version: ">=4.16,<5"
astrbot_version: "~=4.17"
```

## 14. sentence-transformers 嵌入模型加载失败

**现象**：日志报 `嵌入模型加载失败，L2 记忆库将不可用：sentence-transformers 未安装`

**原因**：服务器未安装 `sentence-transformers` 包，或安装时默认拉取了完整 GPU 版 torch 导致磁盘/时间浪费。

**解决**：

uv 部署方式下，AstrBot 的 Python 路径为 `/root/.local/share/uv/tools/astrbot/bin/python`。

### 无 GPU 服务器（推荐 CPU-only）

先装 CPU 版 torch（避免下载 2GB+ CUDA 包），再装 sentence-transformers：

```bash
PY=/root/.local/share/uv/tools/astrbot/bin/python
$PY -m pip install torch --index-url https://download.pytorch.org/whl/cpu
$PY -m pip install sentence-transformers --no-deps
$PY -m pip install transformers huggingface-hub scikit-learn scipy nltk tokenizers
```

### 有 GPU 服务器

直接装即可：

```bash
PY=/root/.local/share/uv/tools/astrbot/bin/python
$PY -m pip install sentence-transformers
```

### 验证

```bash
$PY -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

### 重启

```bash
systemctl restart astrbot
```
