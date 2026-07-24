#!/usr/bin/env python3
"""
AstrBot Skill - SSH/SFTP/Log CLI (thin wrapper over _common.py).

CLI surface for remote ops. Connection/login.config/SFTP live in _common.py.

Usage (prefer absolute path to this script from skill root):
    python ssh-exec.py diagnose [--full]
    python ssh-exec.py trace [--since "30 min ago"]
    python ssh-exec.py batch "cmd1" "cmd2" ...
    python ssh-exec.py batch --file cmds.txt
    python ssh-exec.py log astrbot --since "1 hour ago" [--grep PAT | --profile errors]
    python ssh-exec.py sync-plugin <local_dir> [--name plugin_name]
    python ssh-exec.py upload-dir <local_dir> <remote_dir>
    python ssh-exec.py write <remote> --file local.txt
    python ssh-exec.py exec "command"
    python ssh-exec.py tail astrbot|napcat
    python ssh-exec.py upload|download|cat|ls|whoami

Credentials: --login-config | $ASTRBOT_LOGIN_CONFIG | login.config walk-up.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Credentials,
    ExecResult,
    SshConfigError,
    SshExecError,
    connect,
    download_file,
    exec_batch,
    exec_command,
    load_credentials,
    preferred_login_config_path,
    read_file,
    skill_root,
    upload_dir,
    upload_file,
    write_file,
    write_login_config_template,
)


def _configure_stdio() -> None:
    """Avoid UnicodeEncodeError on Windows GBK consoles (remote logs may contain emoji)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PLUGIN_ROOT = "/opt/astrbot/data/addons/plugins"
DEFAULT_CMD_CONFIG = "/opt/astrbot/data/cmd_config.json"

LOG_PROFILES: dict[str, str] = {
    "errors": r"error|exception|fail|traceback",
    "llm": r"provider|llm|completion|session lock|api key|401|403|timeout",
    "ws": r"websocket|aiocqhttp|405|disconnect|reverse",
    "plugin": r"plugin|reload|yaml|import|ModuleNotFound|SyntaxError|BOM|metadata",
    "wake": r"DIRECTED TO YOU|is_wake|wake_prefix|empty_mention",
}

TRACE_STEPS: list[tuple[str, str, str]] = [
    # (id, label, grep pattern)
    ("1_wake", "DIRECTED TO YOU (wake)", r"DIRECTED TO YOU"),
    ("2_ready", "ready to request llm", r"ready to request llm"),
    ("3_lock", "session lock", r"session lock|acquired session lock"),
    ("4_completion", "completion", r"completion"),
    ("5_send", "Prepare to send", r"Prepare to send"),
]


def _print_result(r: ExecResult) -> int:
    if r.stdout:
        sys.stdout.write(r.stdout)
        if not r.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if r.stderr:
        sys.stderr.write(r.stderr)
        if not r.stderr.endswith("\n"):
            sys.stderr.write("\n")
    return r.rc


def _shell_quote(s: str) -> str:
    return shlex.quote(s)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_exec(creds: Credentials, command: str, timeout: int) -> int:
    r = exec_command(creds, command, timeout=timeout)
    return _print_result(r)


def cmd_tail(creds: Credentials, service: str, lines: int) -> int:
    if service == "astrbot":
        command = f"journalctl -u astrbot -n {int(lines)} --no-pager"
    elif service == "napcat":
        command = (
            f"tail -n {int(lines)} ~/Napcat/log/$(ls -t ~/Napcat/log/ 2>/dev/null | head -1) "
            f"2>/dev/null || tail -n {int(lines)} ~/Napcat/log/*.log 2>/dev/null "
            f"|| echo '(no napcat log found)'"
        )
    else:
        sys.stderr.write(f"unknown service: {service}. Use astrbot or napcat.\n")
        return 2
    return cmd_exec(creds, command, timeout=60)


def cmd_log(
    creds: Credentials,
    service: str,
    since: str | None,
    until: str | None,
    grep: str | None,
    profile: str | None,
    lines: int | None,
) -> int:
    pattern = grep
    if profile:
        if profile not in LOG_PROFILES:
            sys.stderr.write(
                f"unknown profile: {profile}. "
                f"Choose from: {', '.join(LOG_PROFILES)}\n"
            )
            return 2
        pattern = LOG_PROFILES[profile]

    if service == "astrbot":
        parts = ["journalctl -u astrbot --no-pager"]
        if since:
            parts.append(f"--since {_shell_quote(since)}")
        if until:
            parts.append(f"--until {_shell_quote(until)}")
        cmd = " ".join(parts)
        if pattern:
            # Use grep -aEi for binary-safe case-insensitive extended regex
            cmd = f"{cmd} | grep -aEi {_shell_quote(pattern)} || true"
        if lines:
            cmd = f"{cmd} | tail -n {int(lines)}"
        return cmd_exec(creds, cmd, timeout=300)

    if service == "napcat":
        # Best-effort: newest log file
        base = (
            "f=~/Napcat/log/$(ls -t ~/Napcat/log/ 2>/dev/null | head -1); "
            "if [ -z \"$f\" ] || [ ! -f $f ]; then echo '(no napcat log)'; exit 0; fi; "
        )
        if pattern:
            cmd = base + f"grep -aEi {_shell_quote(pattern)} \"$f\" || true"
        else:
            n = int(lines or 200)
            cmd = base + f"tail -n {n} \"$f\""
        return cmd_exec(creds, cmd, timeout=120)

    sys.stderr.write(f"unknown service: {service}\n")
    return 2


def cmd_upload(creds: Credentials, local: str, remote: str) -> int:
    try:
        upload_file(creds, local, remote)
    except FileNotFoundError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    sys.stdout.write(f"uploaded {local} -> {creds} {remote}\n")
    return 0


def cmd_download(creds: Credentials, remote: str, local: str) -> int:
    try:
        download_file(creds, remote, local)
    except SshExecError as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write(f"downloaded {creds} {remote} -> {local}\n")
    return 0


def cmd_cat(creds: Credentials, remote: str) -> int:
    try:
        content = read_file(creds, remote)
    except SshExecError as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write(content)
    if not content.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def cmd_write(
    creds: Credentials,
    remote: str,
    content: str | None,
    file_path: str | None,
    use_stdin: bool,
) -> int:
    if use_stdin:
        data = sys.stdin.read()
    elif file_path:
        data = Path(file_path).read_text(encoding="utf-8")
    elif content is not None:
        data = content
    else:
        sys.stderr.write("write requires content, --file, or --stdin\n")
        return 2
    write_file(creds, remote, data)
    sys.stdout.write(f"wrote {len(data.encode('utf-8'))} bytes -> {creds} {remote}\n")
    return 0


def cmd_ls(creds: Credentials, remote: str, long: bool) -> int:
    flag = "-la" if long else "-la"
    # always useful listing
    return cmd_exec(creds, f"ls {flag} {_shell_quote(remote)}", timeout=60)


def cmd_whoami(creds: Credentials) -> int:
    sys.stdout.write(f"skill_root={skill_root()}\n")
    sys.stdout.write(f"credentials={creds}\n")
    sys.stdout.write(f"source={creds.source}\n")
    sys.stdout.write(f"github_url={getattr(creds, 'github_url', '')}\n")
    sys.stdout.write(f"git_user={getattr(creds, 'git_user', '')}\n")
    sys.stdout.write(f"git_email={getattr(creds, 'git_email', '')}\n")
    sys.stdout.write(f"cwd={Path.cwd()}\n")
    client = connect(creds)
    try:
        r = exec_command(creds, "whoami; hostname; pwd; date -Is", client=client)
        _print_result(r)
        return r.rc
    finally:
        client.close()


def cmd_batch(
    creds: Credentials,
    commands: list[str],
    file_path: str | None,
    use_stdin: bool,
    timeout: int,
    stop_on_error: bool,
    as_json: bool,
) -> int:
    cmds: list[str] = []
    if use_stdin:
        cmds.extend(sys.stdin.read().splitlines())
    if file_path:
        cmds.extend(Path(file_path).read_text(encoding="utf-8").splitlines())
    cmds.extend(commands)
    cmds = [c.strip() for c in cmds if c.strip() and not c.strip().startswith("#")]
    if not cmds:
        sys.stderr.write("batch: no commands provided\n")
        return 2

    steps = exec_batch(
        creds, cmds, timeout=timeout, stop_on_error=stop_on_error
    )
    if as_json:
        payload = [
            {
                "index": s.index,
                "command": s.command,
                "rc": s.result.rc,
                "stdout": s.result.stdout,
                "stderr": s.result.stderr,
            }
            for s in steps
        ]
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        for s in steps:
            sys.stdout.write(f"=== [{s.index}/{len(steps)}] rc={s.result.rc} ===\n")
            sys.stdout.write(f"$ {s.command}\n")
            if s.result.stdout:
                sys.stdout.write(s.result.stdout)
                if not s.result.stdout.endswith("\n"):
                    sys.stdout.write("\n")
            if s.result.stderr:
                sys.stderr.write(s.result.stderr)
                if not s.result.stderr.endswith("\n"):
                    sys.stderr.write("\n")
            sys.stdout.write("\n")
    return 0 if all(s.result.ok for s in steps) else 1


def cmd_trace(
    creds: Credentials,
    since: str,
    until: str | None,
    lines_per_step: int,
    as_json: bool,
) -> int:
    """One-shot message-flow pipeline check (single SSH connection)."""
    client = connect(creds)
    try:
        report = []
        for step_id, label, pattern in TRACE_STEPS:
            parts = [
                "journalctl -u astrbot --no-pager",
                f"--since {_shell_quote(since)}",
            ]
            if until:
                parts.append(f"--until {_shell_quote(until)}")
            cmd = (
                " ".join(parts)
                + f" | grep -aEi {_shell_quote(pattern)} "
                + f"| tail -n {int(lines_per_step)} || true"
            )
            r = exec_command(creds, cmd, timeout=120, client=client)
            hits = [ln for ln in r.stdout.splitlines() if ln.strip()]
            report.append(
                {
                    "id": step_id,
                    "label": label,
                    "pattern": pattern,
                    "hit_count": len(hits),
                    "lines": hits,
                }
            )

        # Summary: first missing step after previous hits
        stuck_at = None
        saw_any = False
        for item in report:
            if item["hit_count"] > 0:
                saw_any = True
            elif saw_any and stuck_at is None:
                stuck_at = item["id"]
        if not saw_any:
            stuck_at = "1_wake (no wake logs at all)"

        if as_json:
            sys.stdout.write(
                json.dumps(
                    {
                        "since": since,
                        "until": until,
                        "stuck_at": stuck_at,
                        "steps": report,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        else:
            sys.stdout.write(f"=== message flow trace (since {since}) ===\n")
            for item in report:
                mark = "OK" if item["hit_count"] else "MISS"
                sys.stdout.write(
                    f"[{mark}] {item['label']}: {item['hit_count']} hit(s)\n"
                )
                for ln in item["lines"][-3:]:
                    sys.stdout.write(f"    {ln}\n")
            sys.stdout.write("\n")
            if stuck_at:
                sys.stdout.write(
                    f">>> stuck_at / first gap: {stuck_at}\n"
                    ">>> see references/debug-handbook.md §2 and "
                    "references/remote-ops-playbook.md\n"
                )
            else:
                sys.stdout.write(
                    ">>> all 5 stages have hits in the window "
                    "(if still no reply, check NapCat send path / platform)\n"
                )
        return 0
    finally:
        client.close()


def cmd_diagnose(creds: Credentials, full: bool, as_json: bool) -> int:
    client = connect(creds)
    try:
        steps: list[tuple[str, str]] = [
            (
                "service:astrbot",
                "systemctl status astrbot --no-pager 2>&1 | head -20",
            ),
            (
                "ports",
                "ss -tlnp 2>/dev/null | grep -E '6185|6199|62124|62125' "
                "|| echo '(no target ports listening)'",
            ),
            (
                "errors:5m",
                "journalctl -u astrbot --since '5 min ago' --no-pager 2>/dev/null "
                "| grep -aEi 'error|exception|fail|traceback' | tail -40 "
                "|| echo '(no recent errors)'",
            ),
        ]
        if full:
            steps = [
                (
                    "service:astrbot",
                    "systemctl status astrbot --no-pager 2>&1 | head -20",
                ),
                (
                    "service:napcat",
                    "systemctl status napcat --no-pager 2>&1 | head -15 "
                    "|| napcat status 2>&1 | head -15 "
                    "|| echo '(napcat status unavailable)'",
                ),
                (
                    "ports",
                    "ss -tlnp 2>/dev/null | grep -E '6185|6199|62124|62125' "
                    "|| echo '(no target ports listening)'",
                ),
                (
                    "errors:5m",
                    "journalctl -u astrbot --since '5 min ago' --no-pager 2>/dev/null "
                    "| grep -aEi 'error|exception|fail|traceback' | tail -40 "
                    "|| echo '(no recent errors)'",
                ),
                (
                    "plugins:dirs",
                    f"ls -la {DEFAULT_PLUGIN_ROOT} 2>/dev/null | head -40 "
                    f"|| echo '(plugin root missing)'",
                ),
                (
                    "config:snapshot",
                    f"python3 - <<'PY'\n"
                    f"import json\n"
                    f"p={DEFAULT_CMD_CONFIG!r}\n"
                    f"try:\n"
                    f"  d=json.load(open(p,encoding='utf-8'))\n"
                    f"except Exception as e:\n"
                    f"  print('config read error:', e); raise SystemExit(0)\n"
                    f"dash=d.get('dashboard') or {{}}\n"
                    f"print('dashboard.port=', dash.get('port'))\n"
                    f"print('dashboard.host=', dash.get('host') or dash.get('ip'))\n"
                    f"plats=d.get('platform') or []\n"
                    f"print('platform.count=', len(plats))\n"
                    f"for i,p0 in enumerate(plats[:5]):\n"
                    f"  print(f'platform[{{i}}].id=', p0.get('id'), "
                    f"'type=', p0.get('type'), 'enable=', p0.get('enable'), "
                    f"'ws_port=', p0.get('ws_reverse_port'))\n"
                    f"provs=d.get('provider') or []\n"
                    f"print('provider.count=', len(provs))\n"
                    f"for i,p0 in enumerate(provs[:5]):\n"
                    f"  print(f'provider[{{i}}].id=', p0.get('id'), 'type=', p0.get('type'))\n"
                    f"PY",
                ),
            ]

        payload = []
        worst_rc = 0
        for label, command in steps:
            r = exec_command(creds, command, client=client, timeout=90)
            payload.append(
                {
                    "step": label,
                    "rc": r.rc,
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                }
            )
            if r.rc != 0:
                worst_rc = r.rc
            if not as_json:
                sys.stdout.write(f"=== {label} ===\n")
                if r.stdout:
                    sys.stdout.write(r.stdout)
                    if not r.stdout.endswith("\n"):
                        sys.stdout.write("\n")
                if r.stderr:
                    sys.stderr.write(r.stderr)
                sys.stdout.write("\n")

        if as_json:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0
    finally:
        client.close()


def cmd_upload_dir(creds: Credentials, local_dir: str, remote_dir: str) -> int:
    try:
        result = upload_dir(creds, local_dir, remote_dir)
    except FileNotFoundError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    sys.stdout.write(
        f"upload-dir {local_dir} -> {creds} {remote_dir}\n"
        f"  uploaded={result.uploaded} skipped={result.skipped} "
        f"bytes={result.bytes_sent}\n"
    )
    if result.files:
        preview = result.files[:20]
        for f in preview:
            sys.stdout.write(f"  + {f}\n")
        if len(result.files) > 20:
            sys.stdout.write(f"  ... and {len(result.files) - 20} more\n")
    return 0


def cmd_sync_plugin(
    creds: Credentials,
    local_dir: str,
    name: str | None,
    remote_root: str,
) -> int:
    local = Path(local_dir).resolve()
    if not local.is_dir():
        sys.stderr.write(f"local plugin dir not found: {local}\n")
        return 2
    plugin_name = name or local.name
    # sanitize
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", plugin_name):
        sys.stderr.write(f"invalid plugin name: {plugin_name!r}\n")
        return 2
    remote = f"{remote_root.rstrip('/')}/{plugin_name}"
    sys.stdout.write(f"sync-plugin {local} -> {remote}\n")
    return cmd_upload_dir(creds, str(local), remote)



def cmd_init_config(path: str | None, fmt: str, force: bool) -> int:
    """Create a fill-in login.config template (INI or JSON)."""
    target = Path(path).expanduser() if path else preferred_login_config_path(fmt=fmt)
    try:
        written = write_login_config_template(target, fmt=fmt, force=force)
    except SshConfigError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    sys.stdout.write(f"Wrote login.config template ({fmt}): {written}\n")
    sys.stdout.write("Fill [ssh] host/user/password (and optional [git]), then run: whoami\n")
    return 0


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def _add_cred_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--login-config", help="path to login.config")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--user")
    p.add_argument("--pass", dest="password")


def main() -> int:
    p = argparse.ArgumentParser(
        description="SSH/SFTP/Log CLI for AstrBot skill (wraps _common.py).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Profiles for log --profile: " + ", ".join(LOG_PROFILES) + "\n"
            f"Skill root: {skill_root()}"
        ),
    )
    _add_cred_args(p)
    sub = p.add_subparsers(dest="action", required=True)

    s_exec = sub.add_parser("exec", help="run a shell command")
    s_exec.add_argument("command")
    s_exec.add_argument("--timeout", type=int, default=120)

    s_tail = sub.add_parser("tail", help="tail service log")
    s_tail.add_argument("service", choices=["astrbot", "napcat"])
    s_tail.add_argument("--lines", type=int, default=200)

    s_log = sub.add_parser("log", help="journalctl / napcat log query")
    s_log.add_argument("service", choices=["astrbot", "napcat"])
    s_log.add_argument("--since")
    s_log.add_argument("--until")
    s_log.add_argument("--grep", help="extended regex (remote grep -Ei)")
    s_log.add_argument(
        "--profile",
        choices=sorted(LOG_PROFILES.keys()),
        help="predefined grep profile",
    )
    s_log.add_argument("--lines", type=int, help="max lines after filter")

    s_up = sub.add_parser("upload", help="SFTP upload a local file")
    s_up.add_argument("local")
    s_up.add_argument("remote")

    s_dn = sub.add_parser("download", help="SFTP download a remote file")
    s_dn.add_argument("remote")
    s_dn.add_argument("local")

    s_cat = sub.add_parser("cat", help="read a remote file to stdout")
    s_cat.add_argument("remote")

    s_write = sub.add_parser(
        "write", help="write content to remote file (no BOM)"
    )
    s_write.add_argument("remote")
    s_write.add_argument("content", nargs="?", help="inline content (prefer --file)")
    s_write.add_argument("--file", dest="file_path", help="read content from local file")
    s_write.add_argument("--stdin", action="store_true", help="read content from stdin")

    s_ls = sub.add_parser("ls", help="list a remote path")
    s_ls.add_argument("remote")
    s_ls.add_argument("-l", "--long", action="store_true")

    sub.add_parser("whoami", help="print skill root, creds source, remote identity")

    s_batch = sub.add_parser("batch", help="run multiple commands on one SSH connection")
    s_batch.add_argument("commands", nargs="*", help="commands as separate args")
    s_batch.add_argument("--file", dest="file_path", help="file with one command per line")
    s_batch.add_argument("--stdin", action="store_true")
    s_batch.add_argument("--timeout", type=int, default=120)
    s_batch.add_argument("--stop-on-error", action="store_true")
    s_batch.add_argument("--json", action="store_true", dest="as_json")

    s_trace = sub.add_parser(
        "trace", help="message-flow 5-step log trace (single connection)"
    )
    s_trace.add_argument("--since", default="30 min ago")
    s_trace.add_argument("--until")
    s_trace.add_argument("--lines", type=int, default=5, help="lines per step")
    s_trace.add_argument("--json", action="store_true", dest="as_json")

    s_diag = sub.add_parser(
        "diagnose", help="one-shot debug: status + ports + errors"
    )
    s_diag.add_argument(
        "--full",
        action="store_true",
        help="include napcat, plugin dirs, config snapshot",
    )
    s_diag.add_argument("--json", action="store_true", dest="as_json")

    s_ud = sub.add_parser("upload-dir", help="recursive SFTP upload directory")
    s_ud.add_argument("local_dir")
    s_ud.add_argument("remote_dir")

    s_sp = sub.add_parser(
        "sync-plugin",
        help=f"upload local plugin dir to {DEFAULT_PLUGIN_ROOT}/<name>",
    )
    s_sp.add_argument("local_dir")
    s_sp.add_argument("--name", help="remote plugin folder name (default: local dir name)")
    s_sp.add_argument(
        "--remote-root",
        default=DEFAULT_PLUGIN_ROOT,
        help=f"default {DEFAULT_PLUGIN_ROOT}",
    )

    s_init = sub.add_parser(
        "init-config",
        help="create login.config template (INI recommended; JSON supported)",
    )
    s_init.add_argument(
        "--path",
        help="target path (default: preferred project login.config)",
    )
    s_init.add_argument(
        "--format",
        dest="fmt",
        choices=["ini", "json"],
        default="ini",
        help="template format (default: ini)",
    )
    s_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing file",
    )

    args = p.parse_args()

    if args.action == "init-config":
        return cmd_init_config(args.path, args.fmt, args.force)

    try:
        creds = load_credentials(
            explicit_path=args.login_config,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
        )
    except SshConfigError as e:
        sys.stderr.write(f"credentials error: {e}\n")
        return 2

    try:
        if args.action == "exec":
            return cmd_exec(creds, args.command, args.timeout)
        if args.action == "tail":
            return cmd_tail(creds, args.service, args.lines)
        if args.action == "log":
            return cmd_log(
                creds,
                args.service,
                args.since,
                args.until,
                args.grep,
                args.profile,
                args.lines,
            )
        if args.action == "upload":
            return cmd_upload(creds, args.local, args.remote)
        if args.action == "download":
            return cmd_download(creds, args.remote, args.local)
        if args.action == "cat":
            return cmd_cat(creds, args.remote)
        if args.action == "write":
            return cmd_write(
                creds, args.remote, args.content, args.file_path, args.stdin
            )
        if args.action == "ls":
            return cmd_ls(creds, args.remote, args.long)
        if args.action == "whoami":
            return cmd_whoami(creds)
        if args.action == "batch":
            return cmd_batch(
                creds,
                args.commands,
                args.file_path,
                args.stdin,
                args.timeout,
                args.stop_on_error,
                args.as_json,
            )
        if args.action == "trace":
            return cmd_trace(
                creds, args.since, args.until, args.lines, args.as_json
            )
        if args.action == "diagnose":
            return cmd_diagnose(creds, args.full, args.as_json)
        if args.action == "upload-dir":
            return cmd_upload_dir(creds, args.local_dir, args.remote_dir)
        if args.action == "sync-plugin":
            return cmd_sync_plugin(
                creds, args.local_dir, args.name, args.remote_root
            )
    except SshExecError as e:
        sys.stderr.write(f"SSH error: {e}\n")
        return 1
    except FileNotFoundError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    return 0


if __name__ == "__main__":
    _configure_stdio()
    sys.exit(main())
