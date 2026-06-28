# AstrBot 插件合规检查与开发工作流

涵盖从自然语言需求解析到交付合规的完整流程。生成新插件时配合 `assets/plugin-scaffold.py`
与 `references/plugin-new-checklist.md` 一起看。

## 1. 需求解析工作流（from natural language）

当用户只给出自由文本需求时，先解析再实现：

1. **需求解析** — 提取并重述：
   - Goal：插件要解决什么
   - Triggers：命令 / 事件 / 定时
   - Inputs：用户文本、配置、上下文
   - Outputs：回复 / 动作 / 副作用
   - Constraints：适配器、版本、性能、安全
   - 缺失项用安全默认值，并显式标注假设。
2. **实现规划** — 转为具体产物：
   - 要创建/修改的文件
   - 核心函数/类
   - 错误处理策略
   - 持久化数据位置（AstrBot `data` 目录）
3. **构建顺序**：
   1. `metadata.yaml`（若有 login.config GitHub 链接，`repo` = `{github_url}/{plugin_folder_name}`；向用户确认后使用）
   2. `requirements.txt`
   3. 插件代码（用 `plugin-scaffold.py` 生成骨架，再 Edit 填业务逻辑）
   4. 测试
   5. Logo 处理（可选：`assets/logo-process.py`）
   6. 本列表合规自检

## 2. Metadata Compliance

- `metadata.yaml` exists.
- Required keys: `name`, `desc`, `version`, `author`.
- Recommended key: `repo`（repository URL；若 login.config 含 GitHub 链接，必须为 `{github_url}/{plugin_folder_name}`）。
- Optional keys valid: `display_name`, `support_platforms`, `astrbot_version`, `repo`.
- `astrbot_version` follows PEP 440 and has no `v` prefix.

## 3. Adapter Compliance

`support_platforms` only contains supported keys:

aiocqhttp · qq_official · telegram · wecom · lark · dingtalk · discord · slack · kook · vocechat · weixin_official_account · satori · misskey · line

## 4. Code Compliance

- No persistent data written in plugin source directory.
- Persistent data paths use AstrBot `data` directory (`data/plugin_data/{name}/`).
- Network calls avoid `requests`; prefer async `aiohttp` or `httpx`.
- Error handling prevents single-failure crash.

## 5. Encoding & Syntax Pre-flight (MANDATORY before delivery)

> 在 Windows 上用 write_to_file 生成的文件可能带 UTF-8 BOM 头（`EF BB BF`），
> AstrBot 用 `json.loads` / `__import__` 加载时会直接报错。交付前必须对 **所有**
> `.json` / `.py` / `.yaml` 文件做一次批量自检，不能只校验本次改动的单个文件。

- **No BOM**: every `.json`/`.py`/`.yaml` file must start with a non-BOM byte
  (`{` = `0x7b`, not `0xEF`). `json.loads` raises `Unexpected UTF-8 BOM`.
- **JSON parses**: every `.json` (esp. `_conf_schema.json`) passes `json.load`.
- **Python compiles**: every `.py` passes `py_compile` (catches unescaped `"` inside
  Python string literals — wrap such strings in single quotes `'...'`).
- One-shot check (PowerShell + venv python):
  ```powershell
  Get-ChildItem -File -Recurse -Include *.json,*.py,*.yaml | ForEach-Object {
    $b=[IO.File]::ReadAllBytes($_.FullName)
    if($b.Length-ge3-and$b[0]-eq0xEF-and$b[1]-eq0xBB-and$b[2]-eq0xBF){"BOM! $($_.Name)"}
  }
  python -c "import json,glob; [json.load(open(f,encoding='utf-8')) for f in glob.glob('**/*.json',recursive=True)]; print('JSON OK')"
  python -c "import py_compile,glob; [py_compile.compile(f,doraise=True) for f in glob.glob('**/*.py',recursive=True)]; print('PY OK')"
  ```
- Fix BOM: rewrite with `New-Object System.Text.UTF8Encoding($false)` after `TrimStart([char]0xFEFF)`.

## 6. Test Compliance

### Test Layers
1. **Smoke test**: plugin module import succeeds; core class/function exists.
2. **Behavior test**: key function returns expected output; handles invalid input gracefully.
3. **Optional integration test**: run under AstrBot runtime when environment available.

### Layout
- `tests/test_plugin_smoke.py`
- `tests/test_plugin_behavior.py`
- 模板见 `assets/test_plugin_smoke.py.template` / `assets/test_plugin_behavior.py.template`

### Run
```bash
pytest -q
```

- 至少一个 smoke test；非平凡逻辑必须有 behavior test；测试可被 `pytest` 运行。
- Keep tests deterministic and offline.
- For async code, use `pytest.mark.asyncio` when required.

## 7. Delivery Compliance

- Include debug and reload instructions.
- Include assumptions for ambiguous requirements.
- Keep generated code minimal and runnable.

### Completion Contract

Before finish, verify:
- behavior matches requirement summary
- assumptions are listed
- `repo` field in metadata.yaml is correctly populated (if GitHub link available)
- user can run/debug/reload with clear steps
- remind user about optional logo on first git commit (non-mandatory)
