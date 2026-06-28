#!/usr/bin/env python3
"""
AstrBot Skill - Remote cmd_config.json read/modify/write CLI.

Editing cmd_config.json correctly is a recurring task (port / platform /
provider / persona / toggles). Doing it with sed is forbidden (breaks JSON
quoting — see references/debug-handbook.md §5). This CLI enforces the safe
parse → modify → dump → SFTP-write pipeline with one command.

Pipeline (always):
    1. SFTP-read remote /opt/astrbot/data/cmd_config.json
    2. json.loads → dict
    3. apply get / set / patch / unset
    4. (only on set/patch/unset) json.dumps(indent=2, ensure_ascii=False)
       → SFTP-write back, NO BOM, atomic via SFTP open('w')

Keys are dotted paths: "dashboard.port", "platform.0.ws_reverse_port",
"provider.0.id". Array indices accepted as integers in the path: "platform.0".

Credentials resolved via _common.load_credentials (login.config aware).

Usage:
    python config-tool.py show
    python config-tool.py get dashboard.port
    python config-tool.py get platform.0.ws_reverse_port
    python config-tool.py set dashboard.port 62124
    python config-tool.py set platform.0.enable true
    python config-tool.py set provider.0.api_key sk-xxx
    python config-tool.py patch '{"dashboard.port":62124,"platform.0.enable":false}'
    python config-tool.py unset persona.some_temp_key
    python config-tool.py backup                    # download copy to local ./cmd_config.bak.json
    python config-tool.py --plugin myplug get city_default      # operate on plugin_configs/myplug.json
    python config-tool.py --plugin myplug set proactive_emoji_probability 0.2

Type coercion rules for `set`:
    - "true"/"false"  → bool
    - "null"          → None
    - integer-looking → int
    - float-looking   → float
    - else            → string

To force a string that looks like a number, use patch with JSON value:
    patch '{"dashboard.port":"62124"}'  # stays a string
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Credentials,
    SshConfigError,
    SshExecError,
    download_file,
    load_credentials,
    read_file,
    write_file,
)

# Mirrors the global baseline in SKILL.md; can be overridden via --path.
DEFAULT_REMOTE_PATH = "/opt/astrbot/data/cmd_config.json"


# ---------------------------------------------------------------------------
# Path navigation
# ---------------------------------------------------------------------------

def _split_path(path: str) -> list:
    """Split dotted path into segments. Integers become int (list index)."""
    segs = []
    for raw in path.split("."):
        if raw == "":
            continue
        # array index?
        if raw.lstrip("-").isdigit():
            segs.append(int(raw))
        else:
            segs.append(raw)
    return segs


def get_by_path(obj, path: str):
    segs = _split_path(path)
    cur = obj
    for s in segs:
        if isinstance(s, int):
            if not isinstance(cur, list) or s >= len(cur) or s < -len(cur):
                raise KeyError(f"list index out of range: {s} in path {path}")
            cur = cur[s]
        else:
            if not isinstance(cur, dict) or s not in cur:
                raise KeyError(f"key not found: {s} in path {path}")
            cur = cur[s]
    return cur


def set_by_path(obj, path: str, value) -> None:
    segs = _split_path(path)
    if not segs:
        raise ValueError("empty path")
    cur = obj
    for s in segs[:-1]:
        last = segs[-1] if not isinstance(segs[-1], int) else segs[-1]
        if isinstance(s, int):
            cur = cur[s]
        else:
            if s not in cur:
                cur[s] = {}
            cur = cur[s]
    final = segs[-1]
    if isinstance(final, int):
        cur[final] = value
    else:
        cur[final] = value


def unset_by_path(obj, path: str) -> None:
    segs = _split_path(path)
    if not segs:
        raise ValueError("empty path")
    cur = obj
    for s in segs[:-1]:
        cur = cur[s] if isinstance(s, int) else cur[s]
    final = segs[-1]
    if isinstance(final, int):
        del cur[final]
    else:
        cur.pop(final, None)


# ---------------------------------------------------------------------------
# Value coercion for `set`
# ---------------------------------------------------------------------------

def coerce(raw: str):
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null" or low == "none":
        return None
    # int
    try:
        return int(raw)
    except ValueError:
        pass
    # float
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _load_remote(creds: Credentials, remote_path: str) -> dict:
    text = read_file(creds, remote_path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Save a local copy for inspection
        sys.stderr.write(
            f"remote cmd_config.json is not valid JSON: {e}\n"
            f"first 200 bytes: {text[:200]!r}\n"
        )
        raise SshExecError("remote cmd_config.json parse failed") from e


def _save_remote(creds: Credentials, remote_path: str, obj: dict) -> None:
    out = json.dumps(obj, indent=2, ensure_ascii=False)
    if not out.endswith("\n"):
        out += "\n"
    write_file(creds, remote_path, out)


def cmd_show(creds: Credentials, remote_path: str, key: str | None) -> int:
    obj = _load_remote(creds, remote_path)
    target = get_by_path(obj, key) if key else obj
    sys.stdout.write(json.dumps(target, ensure_ascii=False, indent=2) + "\n")
    return 0


def cmd_get(creds: Credentials, remote_path: str, key: str) -> int:
    try:
        obj = _load_remote(creds, remote_path)
        val = get_by_path(obj, key)
    except KeyError as e:
        sys.stderr.write(f"key not found: {e}\n")
        return 1
    sys.stdout.write(json.dumps(val, ensure_ascii=False, indent=2) + "\n")
    return 0


def cmd_set(creds: Credentials, remote_path: str, key: str, raw: str) -> int:
    obj = _load_remote(creds, remote_path)
    value = coerce(raw)
    set_by_path(obj, key, value)
    _save_remote(creds, remote_path, obj)
    sys.stdout.write(f"set {key} = {json.dumps(value, ensure_ascii=False)}\n")
    sys.stderr.write("[note] reload AstrBot or relevant plugin for the change to take effect\n")
    return 0


def cmd_patch(creds: Credentials, remote_path: str, json_arg: str) -> int:
    try:
        updates = json.loads(json_arg)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"invalid JSON: {e}\n")
        return 2
    if not isinstance(updates, dict):
        sys.stderr.write("--json must be a JSON object\n")
        return 2
    obj = _load_remote(creds, remote_path)
    for k, v in updates.items():
        set_by_path(obj, k, v)
    _save_remote(creds, remote_path, obj)
    sys.stdout.write(f"patched {len(updates)} keys: {', '.join(updates)}\n")
    sys.stderr.write("[note] reload AstrBot or relevant plugin for the change to take effect\n")
    return 0


def cmd_unset(creds: Credentials, remote_path: str, key: str) -> int:
    obj = _load_remote(creds, remote_path)
    try:
        unset_by_path(obj, key)
    except KeyError as e:
        sys.stderr.write(f"key not found: {e}\n")
        return 1
    _save_remote(creds, remote_path, obj)
    sys.stdout.write(f"unset {key}\n")
    return 0


def cmd_backup(creds: Credentials, remote_path: str, local: str) -> int:
    download_file(creds, remote_path, local)
    sys.stdout.write(f"backed up {creds}@{remote_path} -> {local}\n")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Read/modify remote AstrBot cmd_config.json safely "
                    "(parse→modify→dump, never sed).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--login-config")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--user")
    p.add_argument("--pass", dest="password")
    p.add_argument("--path", default=DEFAULT_REMOTE_PATH,
                   help=f"remote cmd_config.json path (default: {DEFAULT_REMOTE_PATH})")
    p.add_argument("--plugin",
                   help="shortcut: operate on plugin_configs/<name>.json (overrides --path)")
    sub = p.add_subparsers(dest="action", required=True)

    s_show = sub.add_parser("show", help="print whole config (or sub-key with --key)")
    s_show.add_argument("--key")

    s_get = sub.add_parser("get", help="get a dotted-path key")
    s_get.add_argument("key")

    s_set = sub.add_parser("set", help="set a dotted-path key (auto type-coerce)")
    s_set.add_argument("key")
    s_set.add_argument("value")

    s_patch = sub.add_parser("patch", help="batch-set from a JSON object")
    s_patch.add_argument("json", help='JSON object like \'{"a.b":1,"c":true}\'')

    s_unset = sub.add_parser("unset", help="delete a key")
    s_unset.add_argument("key")

    s_bak = sub.add_parser("backup", help="SFTP-download a backup copy")
    s_bak.add_argument("--local", default="cmd_config.bak.json")

    args = p.parse_args()

    # --plugin overrides --path to the plugin_configs location
    if args.plugin:
        args.path = f"/opt/astrbot/data/plugin_configs/{args.plugin}.json"

    try:
        creds = load_credentials(
            explicit_path=args.login_config,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            quiet=True,
        )
    except SshConfigError as e:
        sys.stderr.write(f"credentials error: {e}\n")
        return 2

    try:
        if args.action == "show":
            return cmd_show(creds, args.path, args.key)
        if args.action == "get":
            return cmd_get(creds, args.path, args.key)
        if args.action == "set":
            return cmd_set(creds, args.path, args.key, args.value)
        if args.action == "patch":
            return cmd_patch(creds, args.path, args.json)
        if args.action == "unset":
            return cmd_unset(creds, args.path, args.key)
        if args.action == "backup":
            return cmd_backup(creds, args.path, args.local)
    except SshExecError as e:
        sys.stderr.write(f"SSH error: {e}\n")
        return 1
    except KeyError as e:
        sys.stderr.write(f"key error: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
