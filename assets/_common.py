"""Compatibility shim: import from scripts._common via path insert."""
from __future__ import annotations
import sys
from pathlib import Path

_scripts = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))
from _common import *  # noqa: F401,F403
from _common import __doc__ as _doc  # re-export
