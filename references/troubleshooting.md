# 常见问题排障（边缘案例）

> 通用 debug 场景见 `references/debug-handbook.md`（8 类场景 + 快速决策表 + 三步法）。
> 本文件仅收录 debug-handbook 未覆盖的边缘案例与运维细节。

## 1. astrbot init 交互式提示卡住

**现象**：通过 SSH 非交互执行 `astrbot init` 时命令挂起无响应。

**原因**：`astrbot init` 有交互式确认提示 `[Y/n]`。

**解决**：不要手写 paramiko。复用 skill 封装：

```powershell
$S = $env:ASTRBOT_SKILL_ROOT
python -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path(r'$S')/'scripts')); from _common import load_credentials, invoke_shell_send; print(invoke_shell_send(load_credentials(), ['cd /opt/astrbot && astrbot init', 'Y']))"
```

仍失败再 `ssh-exec.py exec` / `diagnose` 查 unit 与日志；**禁止**新建临时 paramiko 脚本。

## 2. PowerShell 传递含特殊字符的远程命令失败

**现象**：SSH 执行含 `$`、`"`、`{` 等字符的命令报错。

**原因**：PowerShell 对嵌套引号和特殊字符的处理与 bash 不同。

**解决**：
- 简单命令用分号 `;` 分隔（不要用 `&&`，PowerShell 5.1 不支持）
- 复杂内容（JSON、多行文件）用 SFTP 上传（`ssh-exec.py upload`）而非 heredoc
- 含双引号的 grep 模式改用 Python 脚本执行

## 3. AI 输出夹带 Markdown 格式

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

## 4. SSH 密码登录在 Windows 上无法自动化

**现象**：系统 `ssh.exe` 需要交互式输入密码，无法通过脚本自动传递。

**解决**：使用 Python `paramiko` 库实现 SSH 操作（本 skill 的 `_common.py` 已封装）：
- `exec_command` 用于执行单条命令
- `invoke_shell` 用于交互式场景（如 `astrbot init`）
- `open_sftp` 用于文件上传

## 5. 端口被占用

**现象**：服务启动失败，日志显示端口已被占用。

**解决**：
```bash
# 查找占用进程
python scripts/ssh-exec.py exec "ss -tlnp | grep {端口}"
# 或
python scripts/ssh-exec.py exec "lsof -i:{端口}"
# 停止占用进程
python scripts/ssh-exec.py exec "kill {PID}"
```

## 6. metadata.yaml 的 astrbot_version 格式错误

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

## 7. sentence-transformers 嵌入模型加载失败

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

## 8. 新增 provider 后模型不可用：key 必须是数组，写字符串报 401 / 'str' object has no attribute 'copy'

**现象**：手动在 `cmd_config.json` 的 `provider_sources` 新增 OpenAI 兼容中转站后，模型报错：
- 日志/API 报 `openai.AuthenticationError: Error code: 401 - invalid_api_key`（实际 key 完全正确）
- 或 `AttributeError: 'str' object has no attribute 'copy'`

**原因**：`provider.py get_keys()` 原样返回 `provider_sources[].key` 字段；该字段**必须是数组** `["sk-xxx"]`（多 key 轮询）。写成字符串后：
- `self.api_keys[0]` 取到 key 的**第一个字符** → 401；
- 后续 `self.api_keys.copy()` 对 str 调用 → `'str' object has no attribute 'copy'`。

**解决**：

```json
// 错误
"key": "sk-abc..."
// 正确（与 st/ah 等既有供应商一致）
"key": ["sk-abc..."]
```

**验证**：改后重启 AstrBot，用 `astrbot-api.py chat --username x --message "ping"` 实测；新增 provider 结构对齐既有条目（`provider`/`type`/`provider_type`/`key` 数组/`api_base`/`timeout`/`proxy`/`custom_headers`/`id`/`enable`）。

**提醒**：新增 openai_chat_completion 供应商时，先 curl 验证 `GET {api_base}/v1/models` 与 `POST /chat/completions` 可用再写配置。

## 9. 插件源码误入 skill 仓库（禁止）

**现象**：skill 仓库根目录出现未跟踪的 `astrbot_plugin_*` 目录（插件 git 开发副本 / clone）。

**原因**：开发插件时把插件项目 clone 或放在了 skill 目录下，未在提交前清理。

**解决**：
1. 确认该插件在运行目录 `data/plugins/<name>` 已有副本（`diff -rq` 比对，排除 `__pycache__` 等缓存）。
2. 删除 skill 内的副本（`rm -r`，勿用 `rm -rf` 全路径）。
3. 插件源码应放独立 git 项目；同步运行目录用 `sync-plugin`。

**硬约束**：见 SKILL.md 硬约束 #15 —— skill 仓库只放 skill 自身文件。
