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
    # recommended: author/repo from login.config
    python plugin-scaffold.py --name astrbot_plugin_xxx --desc "..." --from-login-config
    # bare minimum manual author
    python plugin-scaffold.py --name astrbot_plugin_xxx --desc "..." --author me
    # optional lifecycle template (initialize/terminate + aiohttp)
    python plugin-scaffold.py --name astrbot_plugin_xxx --desc "..." --author me --with-lifecycle
    # default skeleton always includes astrbot.api logger + [{name}] prefixes

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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SshConfigError, load_credentials  # noqa: E402

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

METADATA_TEMPLATE = """\
name: {name}
display_name: {display_name}
short_desc: {short_desc}
desc: {desc}
version: 0.1.0
author: {author}
{repo_line}{platforms_line}{version_line}{social_line}{tags_line}
"""

MAIN_TEMPLATE = '''\
"""AstrBot plugin: {name}.

{desc}

Logging contract:
  - Always use `from astrbot.api import logger` (never print for ops signals).
  - Prefix messages with [{name}] so remote greps stay stable.
  - Log lifecycle + command entry; use logger.exception on unexpected failures.
"""
from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@register("{name}", "{author}", "{desc}", version="0.1.0"{repo_kw})
class {class_name}(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {{}}

    async def initialize(self) -> None:
        """Called after the plugin is activated."""
        logger.info("[{name}] initialize")

    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        """Reply with a greeting. Trigger: /hello"""
        logger.info(
            "[{name}] command=hello sender=%s",
            event.get_sender_name(),
        )
        yield event.plain_result(f"Hello from {name}!")

    async def terminate(self):
        """Called when plugin is reloaded/unloaded. Clean up resources."""
        logger.info("[{name}] terminate")
'''

# Optional richer lifecycle template (--with-lifecycle). Default is minimal but still logs.
MAIN_LIFECYCLE_TEMPLATE = '''\
"""AstrBot plugin: {name}.

{desc}

Includes initialize/terminate resource management. Remove unused parts freely.

Logging contract:
  - Use astrbot.api logger with [{name}] prefixes (no bare print for ops signals).
  - Log initialize/terminate, command entry, and unexpected failures.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register


@register("{name}", "{author}", "{desc}", version="0.1.0"{repo_kw})
class {class_name}(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {{}}
        self._session: Optional[aiohttp.ClientSession] = None
        self._bg_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Called after the plugin is activated."""
        logger.info("[{name}] initialize")
        self._session = aiohttp.ClientSession()
        self._bg_task = asyncio.create_task(self._heartbeat())

    async def terminate(self) -> None:
        """Called on unload/reload. Must release resources."""
        logger.info("[{name}] terminate - cleaning up")
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[{name}] bg task cancel error: {{e}}")
        if self._session and not self._session.closed:
            await self._session.close()
        await self._save_state()

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(1800)
                logger.debug("[{name}] heartbeat")
        except asyncio.CancelledError:
            raise

    async def _save_state(self) -> None:
        data_dir = StarTools.get_data_dir()
        logger.info(f"[{name}] plugin data dir: {{data_dir}}")

    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        """Reply with a greeting. Trigger: /hello"""
        logger.info(
            "[{name}] command=hello sender=%s",
            event.get_sender_name(),
        )
        yield event.plain_result(f"Hello from {name}!")
'''

REQUIREMENTS_TEMPLATE = """\
# Third-party dependencies for {name}.
# One per line, with version constraint recommended: package>=1.0.0
{reqs}
"""

SCHEMA_TEMPLATE = """\
{{
{items}}}\
"""

SCHEMA_ITEM_TEMPLATE = '''\
  "{key}": {{
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
    api_mod = types.ModuleType("astrbot.api")
    api_mod.logger = types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        exception=lambda *a, **k: None,
        critical=lambda *a, **k: None,
    )
    for name, mod in [
        ("astrbot", types.ModuleType("astrbot")),
        ("astrbot.api", api_mod),
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

## Logs

Ops-visible logs use `from astrbot.api import logger` with a stable `[{name}]` prefix.
Query after reload:

```bash
python scripts/ssh-exec.py log astrbot --since "10 min ago" --profile plugin
python scripts/ssh-exec.py log astrbot --since "10 min ago" --grep "{name}"
```

Do not use bare `print()` for runtime signals.

## Dev

```bash
# local
ruff format .
pytest -q
```

Reload after code changes (WebUI -> Plugin management -> reload).
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
    with_lifecycle: bool = False,
    short_desc: str = "",
    social_link: str = "",
    tags: list[str] | None = None,
    schema_file: Path | None = None,
    with_i18n: bool = False,
    with_pages: bool = False,
) -> Path:
    plugin_dir = out_dir / name
    if plugin_dir.exists():
        sys.stderr.write(f"plugin dir already exists: {plugin_dir}\n")
        sys.exit(2)
    (plugin_dir / "tests").mkdir(parents=True, exist_ok=True)

    # metadata.yaml
    repo_line = f"repo: {repo}\n" if repo else ""
    platforms_line = (
        f"support_platforms:\n" + "".join(f"  - {p}\n" for p in platforms) + "\n"
        if platforms else ""
    )
    version_line = f'astrbot_version: "{astrbot_version}"\n' if astrbot_version else ""
    social_line = f"social_link: {social_link}\n" if social_link else ""
    tags_line = "tags:\n" + "".join(f"  - {tag}\n" for tag in (tags or [])) if tags else ""
    metadata = METADATA_TEMPLATE.format(
        name=name, desc=desc, author=author,
        display_name=display_name or name,
        short_desc=short_desc or desc,
        repo_line=repo_line, platforms_line=platforms_line, version_line=version_line,
        social_line=social_line, tags_line=tags_line,
    ).rstrip() + "\n"
    _write_no_bom(plugin_dir / "metadata.yaml", metadata)

    # main.py
    main_tpl = MAIN_LIFECYCLE_TEMPLATE if with_lifecycle else MAIN_TEMPLATE
    main_code = main_tpl.format(
        name=name, desc=desc, author=author,
        class_name=_camel(name),
        repo_kw=f', repo="{repo}"' if repo else "",
    )
    _write_no_bom(plugin_dir / "main.py", main_code)

    # requirements.txt
    final_reqs = list(reqs)
    if with_lifecycle and "aiohttp" not in final_reqs:
        final_reqs.append("aiohttp")
    req_text = REQUIREMENTS_TEMPLATE.format(
        name=name,
        reqs="\n".join(final_reqs) if final_reqs else "# (no third-party dependencies yet)",
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
    if schema_file:
        schema = schema_file.read_text(encoding="utf-8-sig")
        json.loads(schema)
    else:
        schema = SCHEMA_TEMPLATE.format(items=items_text)
    _write_no_bom(plugin_dir / "_conf_schema.json", schema)

    if with_i18n:
        i18n = plugin_dir / ".astrbot-plugin" / "i18n"
        i18n.mkdir(parents=True, exist_ok=True)
        _write_no_bom(i18n / "zh-CN.json", '{"metadata": {}, "config": {}, "pages": {}}\n')
        _write_no_bom(i18n / "en-US.json", '{"metadata": {}, "config": {}, "pages": {}}\n')
    if with_pages:
        page = plugin_dir / "pages" / "settings"
        page.mkdir(parents=True, exist_ok=True)
        _write_no_bom(page / "index.html", "<!doctype html>\n<html><body><h1>Plugin Page</h1></body></html>\n")

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
        epilog=(
            "Identity: use --from-login-config to fill author/repo from login.config.\n"
            "Repo modes: --repo auto|none|<url>  (auto = {github}/{name}).\n"
            "After generate: plugin-check.py <dir>; ask user about logo & repo create/fork."
        ),
    )
    p.add_argument("--name", required=True,
                   help='plugin name, e.g. astrbot_plugin_weather (lowercase, no spaces)')
    p.add_argument("--desc", required=True, help='short description')
    p.add_argument("--author", help='defaults from login.config git profile when --from-login-config')
    p.add_argument(
        "--repo",
        help='GitHub repo URL, or "auto" ({github}/{name}), or "none" (omit repo field)',
    )
    p.add_argument("--display-name", help='display name shown in WebUI (default: --name)')
    p.add_argument("--short-desc", default="", help="compact marketplace description")
    p.add_argument("--social-link", default="", help="author or project HTTPS URL")
    p.add_argument("--tags", nargs="*", default=[], help="marketplace tags")
    p.add_argument("--platforms", nargs="*",
                   default=["aiocqhttp"],
                   help='support_platforms list (default: aiocqhttp)')
    p.add_argument("--astrbot-version",
                   help='PEP 440 constraint, e.g. ">=4.17.0". No v prefix.')
    p.add_argument("--reqs", nargs="*", default=[],
                   help='third-party deps for requirements.txt')
    p.add_argument("--config", nargs="*", default=[],
                   help='config schema items, each: key:type:desc[:default]')
    p.add_argument("--schema-file", type=Path, help="copy a complete _conf_schema.json")
    p.add_argument("--with-i18n", action="store_true")
    p.add_argument("--with-pages", action="store_true")
    p.add_argument(
        "--with-lifecycle",
        action="store_true",
        help="use initialize/terminate lifecycle template (aiohttp session + bg task). Default stays minimal.",
    )
    p.add_argument("--out", default=".",
                   help='output parent dir (default: cwd); plugin created under <out>/<name>/')
    p.add_argument(
        "--from-login-config",
        action="store_true",
        help="fill author / repo root from login.config git profile",
    )
    p.add_argument("--login-config", help="path to login.config")
    p.add_argument(
        "--profile",
        help="git profile name (optional; usually omit); default from login.config",
    )
    args = p.parse_args()

    # Validate name
    if not args.name or " " in args.name or not args.name.replace("_", "").replace("-", "").isalnum():
        sys.stderr.write(
            f"invalid plugin name {args.name!r}: use lowercase, no spaces, "
            "underscore/hyphen allowed\n"
        )
        return 2

    author = args.author
    repo = args.repo
    profile_name = args.profile
    github_root = ""

    if args.from_login_config or (not author) or (repo in (None, "auto")):
        try:
            creds = load_credentials(
                explicit_path=args.login_config, quiet=True, auto_template=False
            )
            prof = creds.profile(args.profile)
            profile_name = prof.name
            github_root = (prof.github or "").rstrip("/")
            if not author:
                author = prof.user
            if repo in (None, "auto") and github_root:
                repo = f"{github_root}/{args.name}"
            sys.stderr.write(
                f"[scaffold] profile={profile_name} author={author!r} "
                f"github={github_root!r} repo={repo!r}\n"
            )
        except SshConfigError as e:
            if args.from_login_config or not author:
                sys.stderr.write(f"login.config required for author/repo: {e}\n")
                return 2

    if repo == "none":
        repo = None
    if not author:
        sys.stderr.write(
            "--author is required (or use --from-login-config with [git] profile user)\n"
        )
        return 2

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    plugin_dir = generate(
        out_dir=out_dir,
        name=args.name,
        desc=args.desc,
        author=author,
        repo=repo,
        display_name=args.display_name,
        platforms=args.platforms,
        astrbot_version=args.astrbot_version,
        reqs=args.reqs,
        config_specs=args.config,
        with_lifecycle=args.with_lifecycle,
        short_desc=args.short_desc,
        social_link=args.social_link,
        tags=args.tags,
        schema_file=args.schema_file,
        with_i18n=args.with_i18n,
        with_pages=args.with_pages,
    )

    sys.stdout.write(f"generated plugin at: {plugin_dir}\n")
    sys.stdout.write("gates (do NOT skip):\n")
    sys.stdout.write("  1) Confirm author from login.config [git].user with user if needed\n")
    sys.stdout.write("  2) Ask logo: provide image | skip | later (logo-process.py)\n")
    sys.stdout.write(
        "  3) Ask repo: existing URL | create new | fork template | none\n"
    )
    if github_root:
        sys.stdout.write(f"     suggested create: {github_root}/{args.name}\n")
    if args.with_lifecycle:
        sys.stdout.write("  note: generated with --with-lifecycle (initialize/terminate)\n")
    sys.stdout.write(f"  4) python scripts/plugin-check.py {plugin_dir}\n")
    sys.stdout.write(
        f"  5) keep logger.info/error with [{args.name}] prefix; "
        "avoid print() for runtime signals\n"
    )
    sys.stdout.write("next steps:\n")
    sys.stdout.write(f"  cd {plugin_dir}\n")
    sys.stdout.write("  ruff format .\n")
    sys.stdout.write("  pytest -q\n")
    sys.stdout.write(
        f"  python scripts/ssh-exec.py sync-plugin {plugin_dir} --name {args.name}\n"
    )
    sys.stdout.write(
        f"  python scripts/astrbot-api.py --via-ssh plugins reload --name {args.name}\n"
    )
    sys.stdout.write(
        "  before git push: python scripts/git-identity.py check-push --repo <plugin_dir>\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
