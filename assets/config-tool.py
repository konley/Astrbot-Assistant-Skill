#!/usr/bin/env python3
"""Compatibility shim: tools moved to ../scripts/. Prefer scripts/<name>.py."""
from __future__ import annotations
import runpy
import sys
from pathlib import Path

_target = Path(__file__).resolve().parent.parent / "scripts" / Path(__file__).name
if not _target.is_file():
    sys.stderr.write(f"shim error: missing {_target}\n")
    sys.exit(2)
sys.stderr.write(
    f"[deprecated] {Path(__file__).name} moved to scripts/{Path(__file__).name}; "
    "update callers to scripts/.\n"
)
sys.argv[0] = str(_target)
runpy.run_path(str(_target), run_name="__main__")
