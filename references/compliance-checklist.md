# Compliance Checklist For AstrBot Plugin Generation

## Metadata Compliance
- `metadata.yaml` exists.
- Required keys: `name`, `desc`, `version`, `author`.
- Optional keys are valid and documented (`display_name`, `support_platforms`, `astrbot_version`).
- `astrbot_version` follows PEP 440 and has no `v` prefix.

## Adapter Compliance
- `support_platforms` only contains supported keys:
  - aiocqhttp
  - qq_official
  - telegram
  - wecom
  - lark
  - dingtalk
  - discord
  - slack
  - kook
  - vocechat
  - weixin_official_account
  - satori
  - misskey
  - line

## Code Compliance
- No persistent data written in plugin source directory.
- Persistent data paths use AstrBot `data` directory.
- Network calls avoid `requests`; prefer async `aiohttp` or `httpx`.
- Error handling prevents single-failure crash.

## Encoding & Syntax Pre-flight (MANDATORY before delivery)
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

## Test Compliance
- At least one smoke test exists.
- Behavior tests exist for non-trivial logic.
- Tests are runnable with `pytest`.

## Delivery Compliance
- Include debug and reload instructions.
- Include assumptions for ambiguous requirements.
- Keep generated code minimal and runnable.
