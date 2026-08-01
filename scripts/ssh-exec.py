#!/usr/bin/env python3
"""
AstrBot Skill - Host ops CLI (local + SSH remote; thin wrapper over _common.py).

CLI surface for diagnose/trace/log/service/sync. Transport chosen by
login.config [runtime].mode (auto|local|remote). Connection/login.config
live in _common.py.

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
from config_discover import (  # noqa: E402
    apply_writes,
    build_report,
    format_report_text,
    probe_remote,
)
from framework_cache import (  # noqa: E402
    build_check_payload,
    ensure_version_cache,
    exit_code_for_status,
    local_framework_info,
    normalize_version,
    parse_remote_probe_output,
    remote_version_probe_commands,
    versions_equal,
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

DEFAULT_PLUGIN_ROOT = "/opt/astrbot/data/plugins"  # current AstrBot default
DEFAULT_PLUGIN_ROOT_LEGACY = "/opt/astrbot/data/addons/plugins"  # historical installs
DEFAULT_CMD_CONFIG = "/opt/astrbot/data/cmd_config.json"


def _paths(creds: Credentials):
    return getattr(creds, "paths", None)


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        p = (raw or "").strip().rstrip("/")
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def plugin_root_candidates(
    creds: Credentials | None = None,
    override: str | None = None,
) -> list[str]:
    """Ordered plugin-dir candidates: override → login.config → modern → legacy."""
    cands: list[str] = []
    if override:
        cands.append(override)

    p = _paths(creds) if creds is not None else None
    if p and getattr(p, "plugins_dir", None):
        cands.append(str(p.plugins_dir))

    root = "/opt/astrbot"
    data = "/opt/astrbot/data"
    if p is not None:
        root = (getattr(p, "astrbot_root", None) or root).rstrip("/") or root
        data = (getattr(p, "data_dir", None) or f"{root}/data").rstrip("/") or f"{root}/data"

    cands.append(f"{data}/plugins")
    cands.append(f"{data}/addons/plugins")
    # absolute stock fallbacks (in case data_dir was customized oddly)
    cands.append(DEFAULT_PLUGIN_ROOT)
    cands.append(DEFAULT_PLUGIN_ROOT_LEGACY)
    return _dedupe_paths(cands)


def _remote_existing_dirs(
    creds: Credentials,
    paths: list[str],
    *,
    client=None,
) -> list[str]:
    """Return subset of paths that exist as directories on the remote host."""
    if not paths:
        return []
    # One SSH round-trip: print existing dirs, one per line.
    quoted = " ".join(_shell_quote(p) for p in paths)
    cmd = (
        "for d in "
        + quoted
        + '; do if [ -d "$d" ]; then printf "%s\n" "$d"; fi; done'
    )
    r = exec_command(creds, cmd, client=client, timeout=30)
    found: list[str] = []
    for line in (r.stdout or "").splitlines():
        s = line.strip().rstrip("/")
        if s:
            found.append(s)
    # preserve candidate order
    order = {p: i for i, p in enumerate(paths)}
    found_set = set(found)
    return [p for p in paths if p in found_set]


def resolve_plugin_root(
    creds: Credentials,
    override: str | None = None,
    *,
    client=None,
    verify_remote: bool = True,
    log: bool = True,
) -> str:
    """Resolve remote plugins directory.

    Preference:
      1) explicit --remote-root / override
      2) login.config [paths].plugins_dir if it exists remotely
      3) first existing among modern/legacy candidates
      4) configured/modern default (upload may create it)
    """
    cands = plugin_root_candidates(creds, override)
    if not verify_remote:
        return cands[0]

    existing = _remote_existing_dirs(creds, cands, client=client)
    if override:
        ov = override.rstrip("/")
        if ov in existing:
            return ov
        if existing:
            chosen = existing[0]
            if log:
                sys.stderr.write(
                    f"warn: --remote-root {ov} missing; falling back to {chosen}\n"
                )
            return chosen
        if log:
            sys.stderr.write(
                f"warn: --remote-root {ov} missing and no candidate exists; using it anyway\n"
            )
        return ov

    configured = None
    p = _paths(creds)
    if p and getattr(p, "plugins_dir", None):
        configured = str(p.plugins_dir).rstrip("/")

    if configured and configured in existing:
        return configured

    if existing:
        chosen = existing[0]
        if configured and configured != chosen and log:
            sys.stderr.write(
                f"warn: configured plugins_dir {configured} missing; "
                f"using existing {chosen}\n"
            )
        elif log and chosen != DEFAULT_PLUGIN_ROOT:
            sys.stderr.write(f"info: using plugin root {chosen}\n")
        return chosen

    # nothing exists yet — prefer configured, else modern default
    fallback = configured or cands[0]
    if log:
        sys.stderr.write(
            f"warn: no remote plugin dir found among candidates; "
            f"will use {fallback} (may be created on upload)\n"
        )
    return fallback


def _plugin_root(creds: Credentials, override: str | None = None) -> str:
    """Backward-compatible helper (no remote probe). Prefer resolve_plugin_root."""
    return plugin_root_candidates(creds, override)[0]


def _cmd_config(creds: Credentials) -> str:
    p = _paths(creds)
    if p and getattr(p, "cmd_config", None):
        return str(p.cmd_config)
    return DEFAULT_CMD_CONFIG


def _astrbot_unit(creds: Credentials) -> str:
    p = _paths(creds)
    if p and getattr(p, "astrbot_unit", None):
        return (p.astrbot_unit or "astrbot").strip() or "astrbot"
    return "astrbot"


def _astrbot_root(creds: Credentials) -> str:
    p = _paths(creds)
    if p and getattr(p, "astrbot_root", None):
        return str(p.astrbot_root).rstrip("/")
    return "/opt/astrbot"


def _resolve_unit(creds: Credentials, service: str) -> str:
    service = (service or "").strip()
    if service in ("", "astrbot"):
        return _astrbot_unit(creds)
    return service

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
    if service in ("astrbot", _astrbot_unit(creds)):
        unit = _astrbot_unit(creds)
        command = f"journalctl -u {_shell_quote(unit)} -n {int(lines)} --no-pager"
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

    if service in ("astrbot", _astrbot_unit(creds)):
        unit = _astrbot_unit(creds)
        parts = [f"journalctl -u {_shell_quote(unit)} --no-pager"]
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
    sys.stdout.write(
        f"runtime.mode={getattr(creds, 'runtime_mode', 'auto')} "
        f"resolved={getattr(creds, 'resolved_mode', 'remote')}\n"
    )
    sys.stdout.write(f"credentials={creds}\n")
    sys.stdout.write(f"source={creds.source}\n")
    methods = []
    try:
        methods = creds.auth_methods()
    except Exception:
        methods = []
    if creds.is_local():
        sys.stdout.write("auth_methods=local-fs/subprocess\n")
    else:
        sys.stdout.write(f"auth_methods={','.join(methods) or 'unknown'}\n")
    identity = getattr(creds, "identity_file", "") or ""
    sys.stdout.write(f"identity_file={identity or '(none)'}\n")
    sys.stdout.write(f"github_url={getattr(creds, 'github_url', '')}\n")
    sys.stdout.write(f"git_user={getattr(creds, 'git_user', '')}\n")
    sys.stdout.write(f"git_email={getattr(creds, 'git_email', '')}\n")
    paths = _paths(creds)
    if paths:
        sys.stdout.write(f"paths={json.dumps(paths.as_dict(), ensure_ascii=False)}\n")
    sys.stdout.write(f"cwd={Path.cwd()}\n")
    # Local framework cache summary (use framework check for remote probe)
    try:
        finfo = local_framework_info(skill_root())
        sys.stdout.write(
            f"framework.local.version={finfo.get('version')} "
            f"path={finfo.get('cache_path')} exists={finfo.get('exists')}\n"
        )
        meta = finfo.get("meta") if isinstance(finfo.get("meta"), dict) else None
        if meta:
            sys.stdout.write(
                f"framework.meta.remote_version={meta.get('remote_version')} "
                f"synced_at={meta.get('synced_at')}\n"
            )
    except Exception as e:
        sys.stdout.write(f"framework.local.error={type(e).__name__}: {e}\n")
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
    """One-shot message-flow pipeline check (single host session)."""
    client = connect(creds)
    try:
        report = []
        for step_id, label, pattern in TRACE_STEPS:
            unit = _astrbot_unit(creds)
            parts = [
                f"journalctl -u {_shell_quote(unit)} --no-pager",
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
    unit = _astrbot_unit(creds)
    cmd_config = _cmd_config(creds)
    client = connect(creds)
    plugin_root = resolve_plugin_root(
        creds, None, client=client, verify_remote=True, log=False
    )
    try:
        steps: list[tuple[str, str]] = [
            (
                f"service:{unit}",
                f"systemctl status {_shell_quote(unit)} --no-pager 2>&1 | head -20",
            ),
            (
                "ports",
                "ss -tlnp 2>/dev/null | grep -E '6185|6199|62124|62125' "
                "|| echo '(no target ports listening)'",
            ),
            (
                "errors:5m",
                f"journalctl -u {_shell_quote(unit)} --since '5 min ago' --no-pager 2>/dev/null "
                "| grep -aEi 'error|exception|fail|traceback' | tail -40 "
                "|| echo '(no recent errors)'",
            ),
            (
                "framework:version",
                "astrbot version 2>/dev/null || astrbot --version 2>/dev/null "
                "|| python3 -c \"import astrbot; print(getattr(astrbot,'__version__','?'))\" 2>/dev/null "
                "|| echo '(remote version unknown)'",
            ),
        ]
        if full:
            steps = [
                (
                    f"service:{unit}",
                    f"systemctl status {_shell_quote(unit)} --no-pager 2>&1 | head -20",
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
                    f"journalctl -u {_shell_quote(unit)} --since '5 min ago' --no-pager 2>/dev/null "
                    "| grep -aEi 'error|exception|fail|traceback' | tail -40 "
                    "|| echo '(no recent errors)'",
                ),
                (
                    "framework:version",
                    "astrbot version 2>/dev/null || astrbot --version 2>/dev/null "
                    "|| python3 -c \"import astrbot; print(getattr(astrbot,'__version__','?'))\" 2>/dev/null "
                    "|| echo '(remote version unknown)'",
                ),
                (
                    "plugins:dirs",
                    f"ls -la {_shell_quote(plugin_root)} 2>/dev/null | head -40 "
                    f"|| echo '(plugin root missing)'",
                ),
                (
                    "config:snapshot",
                    f"python3 - <<'PY'\n"
                    f"import json\n"
                    f"p={cmd_config!r}\n"
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
            if not as_json:
                sys.stdout.write(f"=== {label} ===\n")
                if r.stdout:
                    sys.stdout.write(r.stdout)
                    if not r.stdout.endswith("\n"):
                        sys.stdout.write("\n")
                if r.stderr:
                    sys.stderr.write(r.stderr)
                sys.stdout.write("\n")

        # Local vs remote framework skew summary
        remote_ver = None
        remote_raw = None
        for item in payload:
            if item.get("step") == "framework:version":
                remote_raw = (item.get("stdout") or "").strip()
                remote_ver = parse_remote_probe_output(remote_raw)
                break
        if not remote_ver:
            probed = _remote_framework_version(creds, client=client)
            remote_ver = probed.get("version")
            remote_raw = probed.get("raw")
            if not as_json and remote_ver:
                sys.stdout.write("=== framework:version(probes) ===\n")
                sys.stdout.write(f"{remote_raw} (probe={probed.get('probe')})\n\n")
        local = local_framework_info(skill_root())
        skew = build_check_payload(
            local=local,
            remote_version=remote_ver,
            remote_raw=remote_raw,
            remote_probe="diagnose",
        )
        payload.append(
            {
                "step": "framework:skew",
                "rc": exit_code_for_status(skew["status"]),
                "stdout": json.dumps(skew, ensure_ascii=False),
                "stderr": "",
            }
        )
        if not as_json:
            sys.stdout.write("=== framework:skew ===\n")
            sys.stdout.write(
                f"status={skew['status']} remote={skew['remote'].get('version')} "
                f"local={skew['local'].get('version')}\n"
            )
            for a in skew.get("advice") or []:
                sys.stdout.write(f"advice: {a}\n")
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
    remote_root: str | None,
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
    client = connect(creds)
    try:
        root = resolve_plugin_root(
            creds,
            remote_root,
            client=client,
            verify_remote=True,
            log=True,
        )
        remote = f"{root.rstrip('/')}/{plugin_name}"
        sys.stdout.write(f"sync-plugin {local} -> {remote}\n")
        # reuse same connection for upload_dir via underlying helpers? upload_dir opens own.
        return cmd_upload_dir(creds, str(local), remote)
    finally:
        client.close()





def cmd_service(
    creds: Credentials,
    action: str,
    unit: str | None,
    lines: int,
    since: str | None,
    yes: bool,
) -> int:
    """systemd helpers: status|logs|enable|disable|restart|start|stop|heal."""
    target = _resolve_unit(creds, unit or "astrbot")
    action = (action or "").strip().lower()
    if action == "heal":
        return cmd_service_heal(creds, target, yes)
    if action in ("status", "st"):
        cmd = f"systemctl status {_shell_quote(target)} --no-pager -l 2>&1 | head -40"
    elif action in ("logs", "log"):
        parts = [f"journalctl -u {_shell_quote(target)} --no-pager"]
        if since:
            parts.append(f"--since {_shell_quote(since)}")
        parts.append(f"-n {int(lines)}")
        cmd = " ".join(parts)
    elif action == "enable":
        cmd = (
            f"systemctl enable {_shell_quote(target)} && "
            f"systemctl is-enabled {_shell_quote(target)}"
        )
    elif action == "disable":
        if not yes:
            sys.stderr.write(
                "service disable requires --yes (destructive). Aborting.\n"
            )
            return 2
        cmd = f"systemctl disable {_shell_quote(target)}"
    elif action in ("restart", "start", "stop", "reload"):
        if action in ("restart", "reload") and not yes:
            sys.stderr.write(
                f"service {action} requires --yes and user confirmation policy.\n"
                "Prefer: plugins reload via astrbot-api, or re-run with --yes after confirm.\n"
            )
            return 2
        if action in ("start", "stop") and not yes:
            sys.stderr.write(f"service {action} requires --yes.\n")
            return 2
        cmd = (
            f"systemctl {action} {_shell_quote(target)} && "
            f"systemctl is-active {_shell_quote(target)} || "
            f"systemctl status {_shell_quote(target)} --no-pager | head -20"
        )
    else:
        sys.stderr.write(
            f"unknown service action: {action}. "
            "Use status|logs|enable|disable|restart|start|stop|reload|heal\n"
        )
        return 2
    return cmd_exec(creds, cmd, timeout=120)


def _find_uv_path(creds: Credentials) -> str:
    """Locate uv on the host: python_bin's uv sibling, then common candidates."""
    p = _paths(creds)
    python_bin = ""
    if p and getattr(p, "python_bin", None):
        python_bin = str(p.python_bin).strip()
    candidates: list[str] = []
    if python_bin:
        candidates.append(str(Path(python_bin).resolve().parents[2] / "bin" / "uv"))
        candidates.append(str(Path(python_bin).resolve().parents[3] / ".local" / "bin" / "uv"))
    candidates += ["~/.local/bin/uv", "/root/.local/bin/uv", "uv"]
    r = exec_command(
        creds,
        "for c in " + " ".join(_shell_quote(c) for c in candidates) + "; do "
        "command -v \"$c\" >/dev/null 2>&1 && { echo \"$c\"; break; }; done",
        timeout=30,
    )
    uv = (r.stdout or "").strip().splitlines()
    return uv[0] if uv else "uv"


def cmd_service_heal(creds: Credentials, target: str, yes: bool) -> int:
    """Self-heal a broken AstrBot service.

    Detects the classic uv-tool upgrade failure (urllib3/requests package
    files missing after `uv tool upgrade`), re-installs astrbot, restarts the
    unit, and verifies the running process is clean.
    """
    if not yes:
        sys.stderr.write("service heal requires --yes (may reinstall astrbot and restart).\n")
        return 2
    status = exec_command(
        creds, f"systemctl is-active {_shell_quote(target)}", timeout=30
    )
    active = (status.stdout or "").strip()
    if active == "active":
        sys.stdout.write(f"service {target}: already active, nothing to heal.\n")
        return 0

    sys.stdout.write(f"service {target}: not active ({active!r}). Checking for dependency break...\n")
    probe = exec_command(
        creds,
        "journalctl -u {0} --no-pager -n 300 2>/dev/null | "
        "grep -m1 -E \"No module named 'urllib3'|requests library is not installed|ModuleNotFoundError\" || true".format(
            _shell_quote(target)
        ),
        timeout=30,
    )
    if "urllib3" not in (probe.stdout or "") and "requests library is not installed" not in (probe.stdout or ""):
        sys.stderr.write(
            f"service {target}: failed but no urllib3/requests signature found. "
            "Manual diagnosis needed (see `service status`/`log`). Not auto-healing.\n"
        )
        return 3

    sys.stdout.write("urllib3/requests dependency break detected. Reinstalling astrbot (uv tool upgrade --reinstall)...\n")
    uv = _find_uv_path(creds)
    sys.stdout.write(f"uv binary: {uv}\n")
    rr = exec_command(creds, f"{_shell_quote(uv)} tool upgrade --reinstall astrbot 2>&1 | tail -8", timeout=600)
    if not rr.ok:
        sys.stderr.write(f"reinstall failed:\n{rr.stdout}{rr.stderr}\n")
        return 1
    sys.stdout.write(rr.stdout)

    sys.stdout.write("Restarting service...\n")
    rs = exec_command(
        creds,
        f"systemctl restart {_shell_quote(target)} && "
        f"systemctl is-active {_shell_quote(target)}",
        timeout=120,
    )
    sys.stdout.write(rs.stdout)
    if (rs.stdout or "").strip() != "active":
        sys.stderr.write(f"restart did not reach active:\n{rs.stdout}{rs.stderr}\n")
        return 1
    sys.stdout.write(f"service {target}: active after heal.\n")
    return 0


def cmd_tunnel(
    creds: Credentials,
    action: str,
    forwards: list[str],
    ssh_bin: str,
    background: bool,
) -> int:
    """Generate (print) or open local SSH port-forward tunnels.

    forwards: LOCAL:REMOTE_PORT or NAME=LOCAL:REMOTE_PORT
    Default if empty: dashboard + napcat webui.
    """
    if creds.is_local():
        dash = getattr(creds, "dashboard_port", None) or 6185
        sys.stdout.write(
            "# tunnel not needed in local mode (already on the robot host)\n"
            f"# dashboard: http://127.0.0.1:{int(dash)}\n"
            "# napcat webui: check login.config / napcat config (often :6099)\n"
        )
        return 0
    action = (action or "print").strip().lower()
    items: list[tuple[str, int, int]] = []
    if not forwards:
        dash = getattr(creds, "dashboard_port", None) or 6185
        forwards = [f"dashboard={int(dash)}:{int(dash)}", "napcat-webui=16099:6099"]
    for raw in forwards:
        name = ""
        spec = raw
        if "=" in raw:
            name, spec = raw.split("=", 1)
        if ":" not in spec:
            sys.stderr.write(f"bad forward spec (want LOCAL:REMOTE): {raw}\n")
            return 2
        local_s, remote_s = spec.split(":", 1)
        try:
            local_p = int(local_s)
            remote_p = int(remote_s)
        except ValueError:
            sys.stderr.write(f"bad forward ports: {raw}\n")
            return 2
        items.append((name or f"port{local_p}", local_p, remote_p))

    fwd_args = " ".join(f"-L {lp}:127.0.0.1:{rp}" for _, lp, rp in items)
    identity = (getattr(creds, "identity_file", "") or "").strip()
    cmd_parts = [ssh_bin or "ssh", "-N"]
    if background:
        cmd_parts.append("-f")
    cmd_parts.append(fwd_args)
    cmd_parts.extend(["-p", str(creds.port), f"{creds.username}@{creds.host}"])
    if identity:
        cmd_parts.extend(["-i", identity])
    cmd = " ".join(cmd_parts)

    if action == "print":
        sys.stdout.write(cmd + "\n")
        sys.stdout.write("# forwards:\n")
        for name, lp, rp in items:
            sys.stdout.write(f"#   {name}: http://127.0.0.1:{lp} -> 127.0.0.1:{rp}\n")
        if (creds.password or "").strip():
            sys.stdout.write(
                "# note: password auth not embedded (avoid leaking secrets). "
                "Use key/agent, or assets/tunnel-generator.html for plink -pw.\n"
            )
        return 0

    if action == "open":
        # Build argv list (no shell) to avoid injection / password leakage patterns
        argv: list[str] = [ssh_bin or "ssh", "-N"]
        if background:
            argv.append("-f")
        for _, lp, rp in items:
            argv.extend(["-L", f"{lp}:127.0.0.1:{rp}"])
        argv.extend(["-p", str(creds.port), f"{creds.username}@{creds.host}"])
        if identity:
            argv.extend(["-i", identity])
        sys.stdout.write("opening tunnel: " + " ".join(argv) + "\n")
        try:
            import subprocess

            proc = subprocess.Popen(argv)
            sys.stdout.write(f"tunnel pid={proc.pid}\n")
            if not background:
                return int(proc.wait() or 0)
            return 0
        except Exception as e:
            sys.stderr.write(f"tunnel open failed: {type(e).__name__}: {e}\n")
            return 1

    sys.stderr.write("tunnel action must be print|open\n")
    return 2


def _remote_framework_version(creds: Credentials, client=None) -> dict:
    """Probe remote runtime version using uv/service python first."""
    paths = _paths(creds)
    root = paths.astrbot_root if paths else "/opt/astrbot"
    unit = paths.astrbot_unit if paths else "astrbot"
    python_bin = ""
    if paths is not None:
        python_bin = str(getattr(paths, "python_bin", "") or "")
    probes = remote_version_probe_commands(
        astrbot_root=root, python_bin=python_bin, unit=unit
    )
    own = client is None
    if own:
        client = connect(creds)
    try:
        for label, cmd in probes:
            r = exec_command(creds, cmd, client=client, timeout=60)
            out = (r.stdout or "").strip()
            if not out:
                continue
            ver = parse_remote_probe_output(out)
            if ver:
                return {
                    "raw": out.splitlines()[0][:200],
                    "version": ver,
                    "probe": label,
                }
        return {"raw": "", "version": None, "probe": None}
    finally:
        if own:
            client.close()


def cmd_framework(
    creds: Credentials | None,
    action: str,
    as_json: bool,
    yes: bool,
    tag: str | None,
    offline: bool = False,
) -> int:
    """Compare remote AstrBot version with local skill source cache; optional sync."""
    action = (action or "check").strip().lower()
    local = local_framework_info(skill_root())

    remote: dict = {"raw": "", "version": None, "probe": None}
    if not offline and creds is None:
        sys.stderr.write("framework: credentials required unless --offline check\n")
        return 2
    if offline:
        meta = local.get("meta") if isinstance(local.get("meta"), dict) else None
        if meta and meta.get("remote_version"):
            remote = {
                "raw": f"meta:{meta.get('remote_version')}",
                "version": normalize_version(str(meta.get("remote_version"))),
                "probe": "meta.offline",
            }
    else:
        assert creds is not None
        remote = _remote_framework_version(creds)

    payload = build_check_payload(
        local=local,
        remote_version=remote.get("version"),
        remote_raw=remote.get("raw"),
        remote_probe=remote.get("probe"),
    )
    payload["remote"]["raw"] = remote.get("raw")
    payload["remote"]["probe"] = remote.get("probe")
    if offline:
        payload["offline"] = True

    if action == "check":
        if as_json:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            status = payload["status"]
            sys.stdout.write(f"status={status}\n")
            sys.stdout.write(f"remote.version={payload['remote'].get('version')}\n")
            sys.stdout.write(f"remote.raw={remote.get('raw')!r}\n")
            sys.stdout.write(f"remote.probe={remote.get('probe')}\n")
            sys.stdout.write(f"local.version={payload['local'].get('version')}\n")
            sys.stdout.write(f"local.path={payload['local'].get('cache_path')}\n")
            sys.stdout.write(
                f"local.git={payload['local'].get('git_describe') or payload['local'].get('git_head')}\n"
            )
            sys.stdout.write(f"meta_fresh={payload.get('meta_fresh')}\n")
            for a in payload.get("advice") or []:
                sys.stdout.write(f"advice: {a}\n")
        return exit_code_for_status(payload["status"])

    if action == "sync":
        if not yes:
            sys.stderr.write(
                "framework sync will clone/fetch/checkout a version-pinned local AstrBot cache. "
                "Re-run with --yes after user agrees.\n"
            )
            return 2
        target_ver = normalize_version(tag) or normalize_version(remote.get("version"))
        if not target_ver:
            sys.stderr.write(
                "cannot sync: remote version unknown and no --tag given "
                "(refusing untagged latest fallback)\n"
            )
            return 2

        def _log(msg: str) -> None:
            sys.stdout.write(msg + "\n")

        result = ensure_version_cache(skill_root(), target_ver, log=_log)
        sys.stdout.write(result.message + "\n")
        if result.meta:
            sys.stdout.write(f"meta={json.dumps(result.meta, ensure_ascii=False)}\n")
        if remote.get("version") and result.version and not versions_equal(
            result.version, remote.get("version")
        ):
            sys.stdout.write(
                f"warning: local={result.version} still != remote={remote.get('version')}\n"
            )
            return 3
        return 0 if result.ok else int(result.rc or 1)

    sys.stderr.write("framework action must be check|sync\n")
    return 2



def cmd_config_discover(
    creds: Credentials,
    *,
    write: bool,
    force: bool,
    as_json: bool,
    path: str | None,
) -> int:
    """Probe remote layout and suggest (optionally write) login.config fills."""
    try:
        remote = probe_remote(creds)
    except Exception as e:
        sys.stderr.write(f"config discover probe failed: {type(e).__name__}: {e}\n")
        return 1
    report = build_report(creds, remote, force=force)
    target = None
    if write:
        if path:
            target = Path(path).expanduser()
        else:
            src = getattr(creds, "source", "") or ""
            target = Path(src) if src and Path(src).is_file() else preferred_login_config_path()
        report.login_config = str(target)
        report = apply_writes(target, report, force=force)
        if report.writes:
            sys.stdout.write(f"updated {target}\n")
        else:
            sys.stdout.write(f"no writes applied to {target}\n")
    if as_json:
        sys.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(format_report_text(report))
    # non-zero if mismatches need manual attention and not forced
    if any(a.action == "manual" for a in report.advice) and not force:
        return 3
    return 0


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
        description="Host ops CLI for AstrBot skill (local + SSH; wraps _common.py).",
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

    sub.add_parser("whoami", help="print skill root, runtime mode, creds, host identity")

    s_batch = sub.add_parser("batch", help="run multiple commands on one host session")
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
        help="sync local plugin dir to host plugins root (login.config / current data/plugins / legacy addons/plugins)",
    )
    s_sp.add_argument("local_dir")
    s_sp.add_argument("--name", help="remote plugin folder name (default: local dir name)")
    s_sp.add_argument(
        "--remote-root",
        default=None,
        help="override plugin root (default: resolve login.config / modern / legacy by remote existence)",
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

    s_svc = sub.add_parser(
        "service",
        help="systemd unit helpers (status|logs|enable|disable|restart|...)",
    )
    s_svc.add_argument(
        "svc_action",
        choices=["status", "logs", "enable", "disable", "restart", "start", "stop", "reload", "heal"],
    )
    s_svc.add_argument(
        "--unit",
        default="astrbot",
        help="systemd unit (default: astrbot or login.config [paths].astrbot_unit)",
    )
    s_svc.add_argument("--lines", type=int, default=100, help="for logs")
    s_svc.add_argument("--since", default=None, help='for logs, e.g. "30 min ago"')
    s_svc.add_argument(
        "--yes",
        action="store_true",
        help="required for restart/reload/start/stop/disable (user must confirm)",
    )

    s_tun = sub.add_parser(
        "tunnel",
        help="print or open SSH local port forwards (no password on argv)",
    )
    s_tun.add_argument("tunnel_action", choices=["print", "open"], default="print", nargs="?")
    s_tun.add_argument(
        "--forward",
        action="append",
        default=[],
        help="NAME=LOCAL:REMOTE or LOCAL:REMOTE (repeatable)",
    )
    s_tun.add_argument("--ssh-bin", default="ssh", help="ssh executable (default ssh)")
    s_tun.add_argument(
        "-f",
        "--background",
        action="store_true",
        help="for open: pass ssh -f",
    )

    s_fw = sub.add_parser(
        "framework",
        help="compare/sync local AstrBot source cache with remote runtime version",
    )
    s_fw.add_argument("fw_action", choices=["check", "sync"], default="check", nargs="?")
    s_fw.add_argument("--json", action="store_true", dest="as_json")
    s_fw.add_argument(
        "--yes",
        action="store_true",
        help="required for sync (clone/fetch/checkout version-pinned local cache)",
    )
    s_fw.add_argument(
        "--tag",
        default=None,
        help="explicit tag/version for sync (default: remote detected version)",
    )
    s_fw.add_argument(
        "--offline",
        action="store_true",
        help="check against framework-cache.meta.json only (no SSH remote probe)",
    )


    s_cfg = sub.add_parser(
        "config",
        help="discover remote layout and suggest/write login.config [paths]/[dashboard]",
    )
    s_cfg.add_argument(
        "cfg_action",
        choices=["discover"],
        help="discover: probe remote and compare with login.config",
    )
    s_cfg.add_argument(
        "--write",
        action="store_true",
        help="write fill/update values into login.config (backup .bak-discover once)",
    )
    s_cfg.add_argument(
        "--force",
        action="store_true",
        help="overwrite mismatched discovered fields (not only empty ones)",
    )
    s_cfg.add_argument(
        "--path",
        help="login.config path for --write (default: credentials source)",
    )
    s_cfg.add_argument("--json", action="store_true", dest="as_json")

    args = p.parse_args()

    if args.action == "init-config":
        return cmd_init_config(args.path, args.fmt, args.force)

    # Offline framework check can work without SSH credentials.
    if (
        args.action == "framework"
        and (getattr(args, "fw_action", None) or "check") == "check"
        and bool(getattr(args, "offline", False))
    ):
        return cmd_framework(
            None,  # type: ignore[arg-type]
            "check",
            getattr(args, "as_json", False),
            False,
            getattr(args, "tag", None),
            offline=True,
        )

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
        if args.action == "service":
            return cmd_service(
                creds,
                args.svc_action,
                args.unit,
                args.lines,
                args.since,
                args.yes,
            )
        if args.action == "tunnel":
            return cmd_tunnel(
                creds,
                args.tunnel_action or "print",
                args.forward,
                args.ssh_bin,
                args.background,
            )
        if args.action == "config":
            return cmd_config_discover(
                creds,
                write=bool(getattr(args, "write", False)),
                force=bool(getattr(args, "force", False)),
                as_json=bool(getattr(args, "as_json", False)),
                path=getattr(args, "path", None),
            )
        if args.action == "framework":
            return cmd_framework(
                creds,
                args.fw_action or "check",
                getattr(args, "as_json", False),
                args.yes,
                args.tag,
                offline=bool(getattr(args, "offline", False)),
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
