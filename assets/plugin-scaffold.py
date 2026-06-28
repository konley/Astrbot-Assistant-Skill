#!/usr/bin/env python3
"""
AstrBot Skill - Plugin scaffold generator.

Generates a complete, ready-to-develop AstrBot plugin skeleton from a small
set of arguments, eliminating the boilerplate the model would otherwise write
by hand each time (metadata.yaml, main.py, _conf_schema.json, tests).

Produced tree (under <out_dir>/<plugin_name>/):
    <plugin_name>/
      main.py                 # async AstrBot plugin entry (StarRegister)
      metadata.yaml           # required + optional fields filled
      requirements.txt        # empty or from --reqs
      _conf_schema.json       # empty schema (or basic if --config flags given)
      tests/
        test_smoke.py         # import smoke test
      README.md               # minimal usage + dev workflow

References (don't re-derive):
    - references/config-reference.md "路径基线" for plugin install path
    - references/plugin-new-checklist.md for required fields
    - references/compliance-checklist.md for delivery rules

Usage:
    # bare minimum
    python plugin-scaffold.py --name astrbot_plugin_xxx --desc "..." --author me

    # with GitHub repo + deps + adapter constraint + basic config schema
    python plugin-scaffold.py \\
        --name astrbot_plugin_weather \\
        --desc "Query weather by city" \\
        --author konley \\
        --repo https://github.com/konley/astrbot_plugin_weather \\
        --astrbot-version ">=4.17.0" \\
        --platforms aiocqhttp telegram \\
        --reqs httpx pyyaml \\
        --config 'city_default:string:默认城市:北京' 'UseEmoji:bool:回复带emoji:true'

    # then: cd astrbot_plugin_weather && ruff format . && pytest -q

All generated files are UTF-8 **without** BOM (required by AstrBot loader).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

METADATA_TEMPLATE = """\
name: {name}
desc: {desc}
version: 0.1.0
author: {author}
{repo_line}{display_line}{platforms_line}{version_line}
"""

MAIN_TEMPLATE = '''\
"""AstrBot plugin: {name}.

{desc}
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Star, register
from astrbot.core.platform.astr_message_message import MessageResult

logger = logging.getLogger(__name__)


@register("{name}", "{author}", "{desc}", version="0.1.0"{repo_kw})
class {class_name}(Star):
    def __init__(self, config: dict | None = None):
        super().__init__()
        self.config = config or {{}}

    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        """Reply with a greeting. Trigger: /hello"""
        await event.plain_result(f"Hello from {name}!")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, request: ProviderRequest):
        """Hook called before each LLM request. Remove if not needed."""
        request.system_prompt += "\\n[plugin {name} active]"

    async def terminate(self):
        """Called when plugin is reloaded/unloaded. Clean up resources."""
        pass
'''

REQUIREMENTS_TEMPLATE = """\
# Third-party dependencies for {name}.
# One per line, with version constraint recommended: package>=1.0.0
{reqs}
"""

SCHEMA_TEMPLATE = """\
{{
  "config_items": [
{items}  ]
}}
"""

SCHEMA_ITEM_TEMPLATE = '''\
    {{
      "key": "{key}",
      "description": "{desc}",
      "type": "{type}",
      "default": {default}
    }}{comma}\
'''

SMOKE_TEST_TEMPLATE = '''\
"""Smoke test: verify the plugin module can be imported.

This test does NOT require a running AstrBot instance; it monkeypatches
astrbot.api.* to stub objects so the import succeeds offline.
"""
import importlib
import sys
import types
import pytest


def _stub_astrbot_modules():
    """Install minimal stubs so plugin import works without astrbot installed."""
    if "astrbot" in sys.modules:
        return  # assume real astrbot present
    # astrbot.api.event
    api_event = types.ModuleType("astrbot.api.event")
    def _passthrough_decorator(*args, **kwargs):
        def deco(func):
            return func
        return deco
    api_event.filter = types.SimpleNamespace(
        command=_passthrough_decorator,
        regex=_passthrough_decorator,
        on_llm_request=_passthrough_decorator,
        on_decorating_result=_passthrough_decorator,
        permission_type=_passthrough_decorator,
        platform_adapter_type=_passthrough_decorator,
    )
    api_event.AstrMessageEvent = object
    # astrbot.api.provider
    api_provider = types.ModuleType("astrbot.api.provider")
    api_provider.ProviderRequest = type("ProviderRequest", (), {{"system_prompt": ""}})
    # astrbot.api.star
    api_star = types.ModuleType("astrbot.api.star")
    api_star.Star = type("Star", (), {{"__init__": lambda self, *a, **k: None}})
    def _register(*args, **kwargs):
        def deco(cls):
            return cls
        return deco
    api_star.register = _register
    # astrbot.core.platform.astr_message_message
    core_plat = types.ModuleType("astrbot.core.platform.astr_message_message")
    core_plat.MessageResult = type("MessageResult", (), {{}})
    # Package hierarchy
    for name, mod in [
        ("astrbot", types.ModuleType("astrbot")),
        ("astrbot.api", types.ModuleType("astrbot.api")),
        ("astrbot.core", types.ModuleType("astrbot.core")),
        ("astrbot.core.platform", types.ModuleType("astrbot.core.platform")),
        ("astrbot.api.event", api_event),
        ("astrbot.api.provider", api_provider),
        ("astrbot.api.star", api_star),
        ("astrbot.core.platform.astr_message_message", core_plat),
    ]:
        sys.modules.setdefault(name, mod)


def test_import():
    _stub_astrbot_modules()
    mod = importlib.import_module("main")
    assert hasattr(mod, "{class_name}")


def test_class_registered():
    _stub_astrbot_modules()
    mod = importlib.import_module("main")
    cls = getattr(mod, "{class_name}")
    assert callable(cls)
'''

README_TEMPLATE = """\
# {name}

{desc}

## Install

In AstrBot WebUI → Plugin market → install from `{repo_or_local}`.

## Commands

- `/hello` — greet (built-in demo)

## Config

See `_conf_schema.json`. Edit via WebUI plugin config page.

## Dev

```bash
# local
ruff format .
pytest -q
```

Reload after code changes (WebUI → Plugin management → reload).
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _camel(snake: str) -> str:
    """astrbot_plugin_weather -> PluginWeather"""
    parts = [p for p in snake.split("_") if p]
    # drop leading "astrbot" / "plugin"
    while parts and parts[0].lower() in ("astrbot", "plugin"):
        parts.pop(0)
    if not parts:
        parts = ["Plugin"]
    return "".join(p.capitalize() for p in parts)


def _parse_config_spec(spec: str) -> tuple[str, str, str, str, Any]:
    """Parse '<key>:<type>:<desc>:<default>' (default optional)."""
    parts = spec.split(":", 3)
    if len(parts) < 3:
        raise ValueError(
            f"bad --config spec {spec!r}, expected key:type:desc[:default]"
        )
    key = parts[0].strip()
    typ = parts[1].strip().lower()
    desc = parts[2].strip()
    default_raw = parts[3].strip() if len(parts) > 3 else ""
    default = _coerce_default(default_raw, typ)
    return key, typ, desc, default_raw, default


def _coerce_default(raw: str, typ: str) -> Any:
    if raw == "":
        if typ == "bool":
            return False
        if typ in ("int", "float"):
            return 0
        if typ == "list":
            return []
        return ""
    if typ == "bool":
        return raw.lower() in ("true", "1", "yes")
    if typ == "int":
        try:
            return int(raw)
        except ValueError:
            return 0
    if typ == "float":
        try:
            return float(raw)
        except ValueError:
            return 0.0
    if typ == "list":
        return [s.strip() for s in raw.split(",")]
    return raw


def _json_default(default: Any) -> str:
    return json.dumps(default, ensure_ascii=False)


# ---------------------------------------------------------------------------
# generator
# ---------------------------------------------------------------------------

def generate(
    out_dir: Path,
    name: str,
    desc: str,
    author: str,
    repo: str | None,
    display_name: str | None,
    platforms: list[str],
    astrbot_version: str | None,
    reqs: list[str],
    config_specs: list[str],
) -> Path:
    plugin_dir = out_dir / name
    if plugin_dir.exists():
        sys.stderr.write(f"plugin dir already exists: {plugin_dir}\n")
        sys.exit(2)
    (plugin_dir / "tests").mkdir(parents=True, exist_ok=True)

    # metadata.yaml
    repo_line = f"repo: {repo}\n" if repo else ""
    display_line = f"display_name: {display_name or name}\n"
    platforms_line = (
        f"support_platforms:\n" + "".join(f"  - {p}\n" for p in platforms) + "\n"
        if platforms else ""
    )
    version_line = f'astrbot_version: "{astrbot_version}"\n' if astrbot_version else ""
    metadata = METADATA_TEMPLATE.format(
        name=name, desc=desc, author=author,
        repo_line=repo_line, display_line=display_line,
        platforms_line=platforms_line, version_line=version_line,
    ).rstrip() + "\n"
    _write_no_bom(plugin_dir / "metadata.yaml", metadata)

    # main.py
    main_code = MAIN_TEMPLATE.format(
        name=name, desc=desc, author=author,
        class_name=_camel(name),
        repo_kw=f', repo="{repo}"' if repo else "",
    )
    _write_no_bom(plugin_dir / "main.py", main_code)

    # requirements.txt
    req_text = REQUIREMENTS_TEMPLATE.format(
        name=name,
        reqs="\n".join(reqs) if reqs else "# (no third-party dependencies yet)",
    )
    _write_no_bom(plugin_dir / "requirements.txt", req_text)

    # _conf_schema.json
    items_text = ""
    if config_specs:
        parsed = [_parse_config_spec(s) for s in config_specs]
        for i, (key, typ, ddesc, _raw, default) in enumerate(parsed):
            comma = "," if i < len(parsed) - 1 else ""
            items_text += SCHEMA_ITEM_TEMPLATE.format(
                key=key, type=typ, desc=ddesc, default=_json_default(default), comma=comma,
            ) + "\n"
    schema = SCHEMA_TEMPLATE.format(items=items_text)
    _write_no_bom(plugin_dir / "_conf_schema.json", schema)

    # tests/test_smoke.py
    smoke = SMOKE_TEST_TEMPLATE.format(class_name=_camel(name))
    _write_no_bom(plugin_dir / "tests" / "test_smoke.py", smoke)

    # README.md
    readme = README_TEMPLATE.format(
        name=name, desc=desc,
        repo_or_local=repo or f"local dir {name}",
    )
    _write_no_bom(plugin_dir / "README.md", readme)

    return plugin_dir


def _write_no_bom(path: Path, content: str) -> None:
    """Write text as UTF-8 WITHOUT BOM. Critical for AstrBot loader."""
    # Python's default open(..., encoding="utf-8") does NOT add BOM.
    # Only utf-8-sig adds BOM. We use utf-8.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate an AstrBot plugin skeleton.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--name", required=True,
                   help='plugin name, e.g. astrbot_plugin_weather (lowercase, no spaces)')
    p.add_argument("--desc", required=True, help='short description')
    p.add_argument("--author", required=True)
    p.add_argument("--repo", help='GitHub repo URL (auto-derived from login.config GitHub link if absent)')
    p.add_argument("--display-name", help='display name shown in WebUI (default: --name)')
    p.add_argument("--platforms", nargs="*",
                   default=["aiocqhttp"],
                   help='support_platforms list (default: aiocqhttp)')
    p.add_argument("--astrbot-version",
                   help='PEP 440 constraint, e.g. ">=4.17.0". No v prefix.')
    p.add_argument("--reqs", nargs="*", default=[],
                   help='third-party deps for requirements.txt')
    p.add_argument("--config", nargs="*", default=[],
                   help='config schema items, each: key:type:desc[:default]')
    p.add_argument("--out", default=".",
                   help='output parent dir (default: cwd); plugin created under <out>/<name>/')
    args = p.parse_args()

    # Validate name
    if not args.name or " " in args.name or not args.name.replace("_", "").replace("-", "").isalnum():
        sys.stderr.write(
            f"invalid plugin name {args.name!r}: use lowercase, no spaces, "
            "underscore/hyphen allowed\n"
        )
        return 2

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    plugin_dir = generate(
        out_dir=out_dir,
        name=args.name,
        desc=args.desc,
        author=args.author,
        repo=args.repo,
        display_name=args.display_name,
        platforms=args.platforms,
        astrbot_version=args.astrbot_version,
        reqs=args.reqs,
        config_specs=args.config,
    )

    sys.stdout.write(f"generated plugin at: {plugin_dir}\n")
    sys.stdout.write("next steps:\n")
    sys.stdout.write(f"  cd {plugin_dir.name}\n")
    sys.stdout.write("  ruff format .\n")
    sys.stdout.write("  pytest -q\n")
    sys.stdout.write("  # then sync to server: python ../ssh-exec.py upload main.py "
                     f"/opt/astrbot/data/addons/plugins/{args.name}/main.py\n")
    sys.stdout.write("  # then reload: python ../astrbot-api.py plugins reload --name "
                     f"{args.name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
