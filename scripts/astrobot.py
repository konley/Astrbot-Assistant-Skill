#!/usr/bin/env python3
"""AstrBot skill unified entrypoint.

Collapses the skill's many scripts into a few stable groups so that
maintainers only need to remember ONE command:

    astrobot.py ops ...      host ops (ssh-exec.py)
    astrobot.py api ...      OpenAPI/plugin lifecycle (astrbot-api.py)
    astrobot.py config ...   safe cmd_config edits (config-tool.py)
    astrobot.py plugin ...   plugin scaffold/check (plugin-scaffold.py / plugin-check.py)
    astrobot.py git ...      personal git identity gate (git-identity.py)
    astrobot.py doctor       read-only environment + config-drift doctor
    astrobot.py heal         self-heal broken astrbot service (ssh-exec.py service heal)
    astrobot.py version      framework alignment (ssh-exec.py framework check)

Existing scripts remain as-is and fully supported (backwards compatible).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
_PY = sys.executable or "python3"


def _run(script: str, args: list[str]) -> int:
    return subprocess.call([_PY, str(SCRIPTS / script), *args])


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="astrobot.py",
        description=__doc__.strip().splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="group", required=True)

    ops = sub.add_parser("ops", help="host ops: log/service/trace/diagnose/whoami/framework... (ssh-exec)")
    ops.add_argument("args", nargs=argparse.REMAINDER)

    api = sub.add_parser("api", help="OpenAPI: plugins list/reload/install, chat, config... (astrbot-api)")
    api.add_argument("args", nargs=argparse.REMAINDER)

    cfg = sub.add_parser("config", help="safe cmd_config edits: get/set/patch/backup (config-tool)")
    cfg.add_argument("args", nargs=argparse.REMAINDER)

    plug = sub.add_parser("plugin", help="plugin dev: new (scaffold) / check (compliance)")
    plug.add_argument("args", nargs=argparse.REMAINDER)

    git = sub.add_parser("git", help="personal git identity gate (git-identity)")
    git.add_argument("args", nargs=argparse.REMAINDER)

    doc = sub.add_parser("doctor", help="read-only environment + config-drift doctor (doctor.py)")
    doc.add_argument("--json", action="store_true", dest="as_json", help="emit JSON output")

    heal = sub.add_parser("heal", help="self-heal broken astrbot service (ssh-exec service heal)")
    heal.add_argument("--unit", default="astrbot", help="systemd unit (default: astrbot)")
    heal.add_argument("--yes", action="store_true", help="required; may reinstall astrbot and restart")

    sub.add_parser("version", help="framework version alignment (ssh-exec framework check)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    group = args.group

    if group == "doctor":
        return _run("doctor.py", ["--json"] if args.as_json else [])
    if group == "heal":
        cmd = ["service", "heal", "--unit", args.unit]
        if args.yes:
            cmd.append("--yes")
        return _run("ssh-exec.py", cmd)
    if group == "version":
        return _run("ssh-exec.py", ["framework", "check"])

    mapping = {
        "ops": "ssh-exec.py",
        "api": "astrbot-api.py",
        "config": "config-tool.py",
        "git": "git-identity.py",
    }
    if group in mapping:
        return _run(mapping[group], args.args)

    if group == "plugin":
        rest = list(args.args)
        if not rest:
            sys.stderr.write(
                "usage: astrobot.py plugin <new|check> [args...]\n"
                "  new    scaffold a plugin (plugin-scaffold.py)\n"
                "  check  run compliance checks (plugin-check.py)\n"
            )
            return 2
        action = rest.pop(0)
        if action in ("new", "scaffold"):
            return _run("plugin-scaffold.py", rest)
        if action == "check":
            return _run("plugin-check.py", rest)
        sys.stderr.write(f"unknown plugin action: {action}\n")
        return 2

    sys.stderr.write(f"unknown group: {group}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
