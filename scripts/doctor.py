#!/usr/bin/env python3
"""Read-only AstrBot skill environment and runtime doctor."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import SshConfigError, load_credentials  # noqa: E402


def _probe_drift(creds) -> list[dict]:
    """Detect login.config path/setup values that no longer match the host.

    Returns a list of {key, current, discovered, action}. Empty when aligned.
    """
    try:
        from config_discover import build_report, probe_remote  # type: ignore[import-not-found]
    except Exception as exc:
        return [
            {
                "key": "_error",
                "current": "",
                "discovered": "",
                "action": f"config_discover import failed: {exc}",
            }
        ]
    try:
        remote = probe_remote(creds)
        report = build_report(creds, remote)
    except Exception as exc:
        return [
            {
                "key": "_error",
                "current": "",
                "discovered": "",
                "action": f"probe failed: {exc}",
            }
        ]
    drift = []
    for field in report.advice:
        if field.action in ("fill", "update"):
            drift.append(
                {
                    "key": f"{field.section}.{field.key}",
                    "current": field.current,
                    "discovered": field.discovered,
                    "action": field.action,
                }
            )
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only AstrBot skill doctor")
    parser.add_argument("--login-config")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "skill_root": str(ROOT),
        "executables": {
            name: bool(shutil.which(name)) for name in ("uv", "docker", "systemctl")
        },
        "cache_meta": str(ROOT / "framework-cache.meta.json"),
    }
    meta_path = ROOT / "framework-cache.meta.json"
    if meta_path.is_file():
        try:
            checks["framework_cache"] = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            checks["framework_cache_error"] = f"{type(exc).__name__}: {exc}"
    try:
        creds = load_credentials(
            explicit_path=args.login_config,
            quiet=True,
            auto_template=False,
        )
        checks["runtime"] = {
            "requested": creds.runtime_mode,
            "resolved": creds.resolved_mode,
            "target": str(creds),
            "paths": creds.paths.as_dict(),
        }
    except SshConfigError as exc:
        checks["runtime_error"] = str(exc)
    else:
        checks["config_drift"] = _probe_drift(creds)

    if args.as_json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for key, value in checks.items():
            print(f"{key}={json.dumps(value, ensure_ascii=False)}")
    return 0 if "runtime_error" not in checks else 2


if __name__ == "__main__":
    raise SystemExit(main())
