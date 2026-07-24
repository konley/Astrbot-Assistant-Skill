# -*- coding: utf-8 -*-
"""Discover remote AstrBot layout and suggest login.config fills.

Remote runtime facts (systemd / process / ports / cmd_config) are preferred
over local guesses. Secrets are never printed in full; api_key is not taken
from dashboard password hashes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from _common import (  # type: ignore
    Credentials,
    PathLayout,
    connect,
    exec_command,
    preferred_login_config_path,
)

REMOTE_PROBE_PY = r'''
import json, os, re, glob
from pathlib import Path

def sh(cmd):
    import subprocess
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return ""

out = {
  "astrbot_unit": "astrbot",
  "astrbot_root": None,
  "python_bin": None,
  "exec_start": None,
  "data_dir": None,
  "plugins_dir": None,
  "plugin_configs_dir": None,
  "plugin_data_dir": None,
  "cmd_config": None,
  "cmd_config_has_bom": None,
  "dashboard_port": None,
  "dashboard_host": None,
  "dashboard_enable": None,
  "listen_ports": [],
  "napcat_unit": None,
  "framework_version": None,
  "notes": [],
}

# systemd unit
unit = "astrbot"
cat = sh("systemctl cat astrbot --no-pager 2>/dev/null")
if not cat.strip():
    # try fuzzy
    units = sh("systemctl list-unit-files --type=service --no-pager 2>/dev/null")
    for line in units.splitlines():
        name = line.split()[0] if line.strip() else ""
        if "astrbot" in name.lower():
            unit = name.replace(".service","")
            cat = sh(f"systemctl cat {unit} --no-pager 2>/dev/null")
            break
out["astrbot_unit"] = unit
m = re.search(r"(?m)^WorkingDirectory=(.+)$", cat)
if m:
    out["astrbot_root"] = m.group(1).strip()
m = re.search(r"(?m)^ExecStart=(.+)$", cat)
if m:
    out["exec_start"] = m.group(1).strip()

root = out["astrbot_root"] or "/opt/astrbot"
if not out["astrbot_root"] and Path("/opt/astrbot").is_dir():
    out["astrbot_root"] = "/opt/astrbot"
    root = "/opt/astrbot"
    out["notes"].append("astrbot_root defaulted to /opt/astrbot (dir exists)")

# python from main pid of unit
pid = sh(f"systemctl show -p MainPID --value {unit} 2>/dev/null").strip()
if pid and pid.isdigit() and int(pid) > 0:
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8","replace").strip()
    except Exception:
        cmd = ""
    if cmd:
        # first token often python path
        tok = cmd.split()[0]
        if "python" in tok:
            out["python_bin"] = tok
        # uv tools path pattern
        m = re.search(r"(\S+/uv/tools/astrbot/bin/python\d*)", cmd)
        if m:
            out["python_bin"] = m.group(1)

if not out["python_bin"]:
    cand = "/root/.local/share/uv/tools/astrbot/bin/python3"
    if Path(cand).exists():
        out["python_bin"] = cand
        out["notes"].append("python_bin from default uv tool path")

# layout paths
data = str(Path(root) / "data")
out["data_dir"] = data if Path(data).is_dir() else data
plugins = str(Path(data) / "addons" / "plugins")
legacy_plugins = str(Path(data) / "plugins")
if Path(plugins).is_dir():
    out["plugins_dir"] = plugins
elif Path(legacy_plugins).is_dir():
    out["plugins_dir"] = legacy_plugins
    out["notes"].append("plugins_dir looks like legacy data/plugins")
else:
    out["plugins_dir"] = plugins
out["plugin_configs_dir"] = str(Path(data) / "plugin_configs")
out["plugin_data_dir"] = str(Path(data) / "plugin_data")
cmd_config = str(Path(data) / "cmd_config.json")
out["cmd_config"] = cmd_config

# BOM + dashboard from cmd_config
p = Path(cmd_config)
if p.is_file():
    raw = p.read_bytes()
    out["cmd_config_has_bom"] = raw.startswith(b"\xef\xbb\xbf")
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
        dash = obj.get("dashboard") if isinstance(obj, dict) else None
        if isinstance(dash, dict):
            port = dash.get("port")
            if port is not None:
                try:
                    out["dashboard_port"] = int(port)
                except Exception:
                    out["dashboard_port"] = port
            out["dashboard_host"] = dash.get("host")
            out["dashboard_enable"] = dash.get("enable")
    except Exception as e:
        out["notes"].append(f"cmd_config parse failed: {type(e).__name__}")
else:
    out["cmd_config_has_bom"] = None
    out["notes"].append("cmd_config.json missing")

# listen ports (python / node related sample)
ss = sh("ss -tlnp 2>/dev/null | head -80")
ports = []
for line in ss.splitlines():
    m = re.search(r":(\d+)\s", line)
    if not m:
        continue
    port = int(m.group(1))
    if port in (6185, 6199, 6099, 62124, 62125) or "python" in line or "astrbot" in line:
        ports.append({"port": port, "line": line.strip()[:180]})
out["listen_ports"] = ports[:20]
if out["dashboard_port"] is None:
    # heuristic: python listening on non-ssh port
    for item in ports:
        if "python" in item.get("line",""):
            out["dashboard_port"] = item["port"]
            out["notes"].append(f"dashboard_port guessed from listen {item['port']}")
            break

# napcat unit
nu = sh("systemctl list-unit-files --type=service --no-pager 2>/dev/null | awk '{print $1}' | grep -i napcat | head -1")
if nu.strip():
    out["napcat_unit"] = nu.strip().replace(".service","")

# version
ver = None
py = out.get("python_bin")
if py:
    ver_out = sh(f"{py} -c \"import astrbot; print(getattr(astrbot,'__version__',''))\" 2>/dev/null")
    ver = (ver_out or "").strip().splitlines()[:1]
    ver = ver[0] if ver else None
if not ver:
    ver = (sh("astrbot version 2>/dev/null || astrbot --version 2>/dev/null") or "").strip().splitlines()[:1]
    ver = ver[0] if ver else None
out["framework_version"] = ver

print(json.dumps(out, ensure_ascii=False))
'''


def strip_bom_text(text: str) -> str:
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def upsert_ini_key(text: str, section: str, key: str, value: str) -> str:
    """Insert or update key under [section], preserving comments when possible.

    - Strips UTF-8 BOM from input
    - Creates section at EOF if missing
    - Updates first matching key line inside section (case-insensitive key)
    - Does not reorder unrelated keys
    """
    text = strip_bom_text(text)
    if text and not text.endswith("\n"):
        text += "\n"
    lines = text.splitlines(keepends=True)
    sec_re = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")
    key_re = re.compile(r"^(\s*)([^#;=\s][^=]*?)(\s*)=(\s*)(.*?)(\s*)$")

    section_l = section.strip().lower()
    key_l = key.strip().lower()
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        m = sec_re.match(line.rstrip("\r\n"))
        if not m:
            continue
        name = m.group(1).strip().lower()
        if start is None and name == section_l:
            start = i
            continue
        if start is not None and i > start:
            end = i
            break

    new_line = f"{key} = {value}\n"
    if start is None:
        # append section
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"[{section}]\n")
        lines.append(new_line)
        return "".join(lines)

    # search key in section body
    for i in range(start + 1, end):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith(("#", ";")):
            continue
        m = key_re.match(raw.rstrip("\r\n"))
        if not m:
            continue
        if m.group(2).strip().lower() == key_l:
            # preserve spacing style lightly
            lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}={m.group(4)}{value}\n"
            return "".join(lines)

    # insert before next section (end)
    insert_at = end
    # if previous line is blank and end is EOF-ish, still fine
    lines.insert(insert_at, new_line)
    return "".join(lines)


def write_text_no_bom(path: Path, text: str) -> None:
    path = Path(path)
    data = strip_bom_text(text)
    if data and not data.endswith("\n"):
        data += "\n"
    path.write_text(data, encoding="utf-8", newline="\n")


@dataclass
class FieldAdvice:
    section: str
    key: str
    current: Any
    discovered: Any
    action: str  # keep|fill|update|skip|manual
    reason: str = ""


@dataclass
class DiscoverReport:
    remote: dict[str, Any] = field(default_factory=dict)
    advice: list[FieldAdvice] = field(default_factory=list)
    login_config: str | None = None
    writes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "login_config": self.login_config,
            "remote": self.remote,
            "advice": [
                {
                    "section": a.section,
                    "key": a.key,
                    "current": a.current,
                    "discovered": a.discovered,
                    "action": a.action,
                    "reason": a.reason,
                }
                for a in self.advice
            ],
            "writes": self.writes,
            "warnings": self.warnings,
        }


def _cur_paths(creds: Credentials) -> dict[str, str]:
    p = getattr(creds, "paths", None) or PathLayout()
    return p.as_dict() if hasattr(p, "as_dict") else {}


# Stock defaults from PathLayout / dashboard — treated as "unset" for discover writes
# so a real remote layout can fill login.config without requiring --force.
_STOCK_DEFAULTS: dict[tuple[str, str], set[str]] = {
    ("paths", "astrbot_root"): {"/opt/astrbot"},
    ("paths", "astrbot_unit"): {"astrbot"},
    ("paths", "data_dir"): {"/opt/astrbot/data"},
    ("paths", "plugins_dir"): {
        "/opt/astrbot/data/addons/plugins",
        "/opt/astrbot/data/plugins",
    },
    ("paths", "plugin_configs_dir"): {"/opt/astrbot/data/plugin_configs"},
    ("paths", "plugin_data_dir"): {"/opt/astrbot/data/plugin_data"},
    ("paths", "cmd_config"): {"/opt/astrbot/data/cmd_config.json"},
    ("dashboard", "port"): {"6185"},
}


def _is_stock_default(section: str, key: str, value: str) -> bool:
    return value in _STOCK_DEFAULTS.get((section, key), set())


def _decide(
    section: str,
    key: str,
    current: Any,
    discovered: Any,
    *,
    force: bool,
) -> FieldAdvice:
    cur_s = "" if current is None else str(current).strip()
    dis_s = "" if discovered is None else str(discovered).strip()
    if not dis_s:
        return FieldAdvice(section, key, current, discovered, "skip", "nothing discovered")
    if not cur_s:
        return FieldAdvice(section, key, current, discovered, "fill", "empty local value")
    if cur_s == dis_s:
        return FieldAdvice(section, key, current, discovered, "keep", "already matches")
    # Unset-looking stock defaults may be replaced by a concrete remote value.
    if _is_stock_default(section, key, cur_s) and not _is_stock_default(section, key, dis_s):
        return FieldAdvice(
            section,
            key,
            current,
            discovered,
            "fill",
            "local value is stock default; remote layout differs",
        )
    if _is_stock_default(section, key, cur_s) and _is_stock_default(section, key, dis_s):
        # e.g. plugins modern default vs legacy default — still prefer remote discovery
        return FieldAdvice(
            section,
            key,
            current,
            discovered,
            "fill",
            "prefer remote-discovered path over local stock default",
        )
    if force:
        return FieldAdvice(section, key, current, discovered, "update", "force overwrite mismatch")
    return FieldAdvice(
        section,
        key,
        current,
        discovered,
        "manual",
        "mismatch; re-run with --force to overwrite, or edit manually",
    )


def probe_remote(creds: Credentials, *, client=None) -> dict[str, Any]:
    own = client is None
    if own:
        client = connect(creds)
    try:
        # feed probe via python -c is too large; use stdin python
        # Write temp on remote via shell heredoc is forbidden for JSON safety;
        # instead run python - <<'PY' through invoke? exec_command uses exec_command not shell invoke.
        # Use base64-less approach: python -c with compressed one-liner file via SFTP write.
        from _common import write_file  # local import

        remote_path = "/tmp/astrbot_skill_config_discover.py"
        write_file(creds, remote_path, REMOTE_PROBE_PY, client=client)
        r = exec_command(
            creds,
            f"python3 {remote_path}; rc=$?; rm -f {remote_path}; exit $rc",
            client=client,
            timeout=90,
        )
        text = (r.stdout or "").strip()
        if not text:
            raise RuntimeError(f"empty probe output rc={r.rc} stderr={r.stderr!r}")
        # last JSON line
        line = text.splitlines()[-1]
        data = json.loads(line)
        if not isinstance(data, dict):
            raise RuntimeError("probe returned non-object")
        return data
    finally:
        if own:
            client.close()


def build_report(
    creds: Credentials,
    remote: dict[str, Any],
    *,
    force: bool = False,
) -> DiscoverReport:
    report = DiscoverReport(remote=remote, login_config=getattr(creds, "source", None))
    paths = _cur_paths(creds)

    pairs = [
        ("paths", "astrbot_root", paths.get("astrbot_root"), remote.get("astrbot_root")),
        ("paths", "astrbot_unit", paths.get("astrbot_unit"), remote.get("astrbot_unit")),
        ("paths", "python_bin", paths.get("python_bin"), remote.get("python_bin")),
        ("paths", "data_dir", paths.get("data_dir"), remote.get("data_dir")),
        ("paths", "plugins_dir", paths.get("plugins_dir"), remote.get("plugins_dir")),
        (
            "paths",
            "plugin_configs_dir",
            paths.get("plugin_configs_dir"),
            remote.get("plugin_configs_dir"),
        ),
        (
            "paths",
            "plugin_data_dir",
            paths.get("plugin_data_dir"),
            remote.get("plugin_data_dir"),
        ),
        ("paths", "cmd_config", paths.get("cmd_config"), remote.get("cmd_config")),
        ("paths", "napcat_unit", paths.get("napcat_unit"), remote.get("napcat_unit")),
        (
            "dashboard",
            "port",
            getattr(creds, "dashboard_port", None),
            remote.get("dashboard_port"),
        ),
    ]
    for section, key, cur, dis in pairs:
        # skip writing default-equivalent noise for derived paths unless force/fill empty custom
        adv = _decide(section, key, cur, dis, force=force)
        # python_bin empty is important even if optional
        report.advice.append(adv)

    if remote.get("cmd_config_has_bom"):
        report.warnings.append(
            "remote cmd_config.json has UTF-8 BOM; JSON tools must use utf-8-sig. "
            "Prefer rewriting via scripts/config-tool.py (writes UTF-8 no BOM)."
        )
    for n in remote.get("notes") or []:
        report.warnings.append(str(n))

    # api_key cannot be discovered from dashboard password hash
    if not (getattr(creds, "dashboard_api_key", "") or "").strip():
        report.warnings.append(
            "dashboard.api_key is empty; create in WebUI → 设置 → API Keys "
            "(not auto-discoverable from cmd_config password fields)."
        )
    return report


def apply_writes(
    login_path: Path,
    report: DiscoverReport,
    *,
    force: bool = False,
) -> DiscoverReport:
    path = Path(login_path)
    if not path.is_file():
        report.warnings.append(f"login.config not found for write: {path}")
        return report
    text = path.read_text(encoding="utf-8-sig")
    original = text
    for adv in report.advice:
        if adv.action not in ("fill", "update"):
            continue
        if adv.discovered is None or str(adv.discovered).strip() == "":
            continue
        if adv.action == "update" and not force:
            continue
        text = upsert_ini_key(text, adv.section, adv.key, str(adv.discovered))
        report.writes.append(f"[{adv.section}] {adv.key} = {adv.discovered}")
    if text != original:
        # backup
        bak = path.with_suffix(path.suffix + ".bak-discover")
        if not bak.exists():
            write_text_no_bom(bak, original)
        write_text_no_bom(path, text)
    return report


def format_report_text(report: DiscoverReport) -> str:
    lines: list[str] = []
    lines.append(f"login_config={report.login_config or '(unknown)'}")
    remote = report.remote or {}
    lines.append(f"remote.framework_version={remote.get('framework_version')}")
    lines.append(f"remote.cmd_config_has_bom={remote.get('cmd_config_has_bom')}")
    lines.append(f"remote.exec_start={remote.get('exec_start')}")
    lines.append("")
    lines.append("advice:")
    for a in report.advice:
        lines.append(
            f"  [{a.section}] {a.key}: action={a.action} "
            f"current={a.current!r} discovered={a.discovered!r} ({a.reason})"
        )
    if report.writes:
        lines.append("")
        lines.append("writes:")
        for w in report.writes:
            lines.append(f"  {w}")
    if report.warnings:
        lines.append("")
        lines.append("warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    # suggested snippet for fill/update/manual
    fill_lines = ["", "suggested login.config snippet:"]
    by_sec: dict[str, list[str]] = {}
    for a in report.advice:
        if a.action in ("fill", "update", "manual") and a.discovered not in (None, ""):
            by_sec.setdefault(a.section, []).append(f"{a.key} = {a.discovered}")
    if not by_sec:
        fill_lines.append("  (no changes suggested)")
    else:
        for sec, ks in by_sec.items():
            fill_lines.append(f"[{sec}]")
            fill_lines.extend(ks)
            fill_lines.append("")
    lines.extend(fill_lines)
    return "\n".join(lines).rstrip() + "\n"
