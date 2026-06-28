#!/usr/bin/env python3
"""
AstrBot Skill - SSH/SFTP/Log CLI (thin wrapper over _common.py).

Provides a CLI surface for the SSH primitives in _common.py. All connection,
login.config parsing, and SFTP logic live in _common.py — this file only
parses argv and prints results.

Reuse rule: other tools MUST import _common directly, not this CLI. This CLI
exists for shell one-liners (see SKILL.md "SSH/服务器操作硬约束").

Usage:
    python ssh-exec.py exec "command [args]"
    python ssh-exec.py exec "cmd" --timeout 300
    python ssh-exec.py tail astrbot [--lines N]            # default N=200
    python ssh-exec.py tail napcat [--lines N]
    python ssh-exec.py log astrbot --since "1 hour ago" [--until "now"] [--grep PATTERN]
    python ssh-exec.py upload <local> <remote>
    python ssh-exec.py download <remote> <local>
    python ssh-exec.py cat <remote>
    python ssh-exec.py write <remote> <content>            # write string to remote (no BOM)
    python ssh-exec.py diagnose                            # one-shot 3-step debug (single connection)

Credentials resolution (in order):
    1. --host/--user/--pass flags
    2. --login-config PATH
    3. $ASTRBOT_LOGIN_CONFIG env var
    4. ./login.config (walks up parent dirs)

Exit code: 0 on success, non-zero on error.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make _common importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Credentials,
    ExecResult,
    SshConfigError,
    SshExecError,
    connect,
    download_file,
    exec_command,
    load_credentials,
    read_file,
    upload_file,
    write_file,
)


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


def cmd_exec(creds: Credentials, command: str, timeout: int) -> int:
    r = exec_command(creds, command, timeout=timeout)
    return _print_result(r)


def cmd_tail(creds: Credentials, service: str, lines: int) -> int:
    if service == "astrbot":
        command = f"journalctl -u astrbot -n {lines} --no-pager"
    elif service == "napcat":
        # Pick newest log file under ~/Napcat/log/
        command = (
            f"tail -n {lines} ~/Napcat/log/$(ls -t ~/Napcat/log/ 2>/dev/null | head -1) "
            f"2>/dev/null || tail -n {lines} ~/Napcat/log/*.log 2>/dev/null"
        )
    else:
        sys.stderr.write(f"unknown service: {service}. Use astrbot or napcat.\n")
        return 2
    return cmd_exec(creds, command, timeout=60)


def cmd_log(
    creds: Credentials,
    since: str | None,
    until: str | None,
    grep: str | None,
) -> int:
    parts = ["journalctl -u astrbot --no-pager"]
    if since:
        parts.append(f"--since '{since}'")
    if until:
        parts.append(f"--until '{until}'")
    if grep:
        parts.append(f"| grep -i '{grep}'")
    return cmd_exec(creds, " ".join(parts), timeout=300)


def cmd_upload(creds: Credentials, local: str, remote: str) -> int:
    try:
        upload_file(creds, local, remote)
    except FileNotFoundError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    sys.stdout.write(f"uploaded {local} -> {creds}@{remote}\n")
    return 0


def cmd_download(creds: Credentials, remote: str, local: str) -> int:
    try:
        download_file(creds, remote, local)
    except SshExecError as e:
        sys.stderr.write(f"{e}\n")
        return 1
    sys.stdout.write(f"downloaded {creds}@{remote} -> {local}\n")
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


def cmd_write(creds: Credentials, remote: str, content: str) -> int:
    write_file(creds, remote, content)
    sys.stdout.write(f"wrote {len(content)} bytes -> {creds}@{remote}\n")
    return 0


def cmd_diagnose(creds: Credentials) -> int:
    """One-shot 3-step debug opening over a single SSH connection.

    Runs (in order): service status -> listening ports -> recent error logs.
    Mirrors debug-handbook.md §10 in one round-trip.
    """
    client = connect(creds)
    try:
        steps = [
            ("=== [1/3] service status ===",
             "systemctl status astrbot --no-pager 2>&1 | head -15"),
            ("=== [2/3] listening ports (6185/6199/62125) ===",
             "ss -tlnp 2>/dev/null | grep -E '6185|6199|62125' || echo '(no target ports listening)'"),
            ("=== [3/3] recent errors (last 5 min) ===",
             "journalctl -u astrbot --since '5 min ago' --no-pager 2>/dev/null "
             "| grep -iE 'error|exception|fail|traceback' | tail -30 "
             "|| echo '(no recent errors)'"),
        ]
        for label, command in steps:
            sys.stdout.write(label + "\n")
            r = exec_command(creds, command, client=client, timeout=60)
            if r.stdout:
                sys.stdout.write(r.stdout)
                if not r.stdout.endswith("\n"):
                    sys.stdout.write("\n")
            if r.stderr:
                sys.stderr.write(r.stderr)
            sys.stdout.write("\n")
        return 0
    finally:
        client.close()


def main() -> int:
    p = argparse.ArgumentParser(
        description="SSH/SFTP/Log CLI for AstrBot skill (wraps _common.py).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--login-config", help="path to login.config")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--user")
    p.add_argument("--pass", dest="password")
    sub = p.add_subparsers(dest="action", required=True)

    s_exec = sub.add_parser("exec", help="run a shell command")
    s_exec.add_argument("command")
    s_exec.add_argument("--timeout", type=int, default=120)

    s_tail = sub.add_parser("tail", help="tail service log")
    s_tail.add_argument("service", choices=["astrbot", "napcat"])
    s_tail.add_argument("--lines", type=int, default=200)

    s_log = sub.add_parser("log", help="journalctl query (astrbot only)")
    s_log.add_argument("service", choices=["astrbot"])
    s_log.add_argument("--since")
    s_log.add_argument("--until")
    s_log.add_argument("--grep")

    s_up = sub.add_parser("upload", help="SFTP upload a local file")
    s_up.add_argument("local")
    s_up.add_argument("remote")

    s_dn = sub.add_parser("download", help="SFTP download a remote file")
    s_dn.add_argument("remote")
    s_dn.add_argument("local")

    s_cat = sub.add_parser("cat", help="read a remote file to stdout")
    s_cat.add_argument("remote")

    s_write = sub.add_parser("write", help="write string content to a remote file (no BOM)")
    s_write.add_argument("remote")
    s_write.add_argument("content")

    sub.add_parser("diagnose", help="one-shot 3-step debug: status + ports + recent errors (single connection)")

    args = p.parse_args()

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
            return cmd_log(creds, args.since, args.until, args.grep)
        if args.action == "upload":
            return cmd_upload(creds, args.local, args.remote)
        if args.action == "download":
            return cmd_download(creds, args.remote, args.local)
        if args.action == "cat":
            return cmd_cat(creds, args.remote)
        if args.action == "write":
            return cmd_write(creds, args.remote, args.content)
        if args.action == "diagnose":
            return cmd_diagnose(creds)
    except SshExecError as e:
        sys.stderr.write(f"SSH error: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
