# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from config_discover import (  # noqa: E402
    strip_bom_text,
    upsert_ini_key,
    write_text_no_bom,
    _decide,
)


def test_strip_bom():
    assert strip_bom_text("\ufeffabc") == "abc"
    assert strip_bom_text("abc") == "abc"


def test_upsert_creates_section_and_key(tmp_path: Path | None = None):
    text = "[ssh]\nhost = 1.2.3.4\n"
    out = upsert_ini_key(text, "paths", "python_bin", "/opt/py")
    assert "[paths]" in out
    assert "python_bin = /opt/py" in out
    assert "host = 1.2.3.4" in out


def test_upsert_updates_existing():
    text = "[paths]\npython_bin = /old\nastrbot_unit = astrbot\n"
    out = upsert_ini_key(text, "paths", "python_bin", "/new")
    assert "python_bin = /new" in out
    assert "/old" not in out
    assert "astrbot_unit = astrbot" in out


def test_upsert_preserves_comments():
    text = "# head\n[paths]\n# keep me\nastrbot_root = /opt/astrbot\n"
    out = upsert_ini_key(text, "paths", "python_bin", "/x")
    assert "# head" in out
    assert "# keep me" in out
    assert "python_bin = /x" in out


def test_write_text_no_bom(tmp_path=None):
    from pathlib import Path as P
    import tempfile, os
    fd, name = tempfile.mkstemp(suffix=".ini")
    os.close(fd)
    p = P(name)
    try:
        write_text_no_bom(p, "\ufeff[ssh]\nhost=a\n")
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert raw.decode("utf-8").startswith("[ssh]")
    finally:
        p.unlink(missing_ok=True)


def test_decide_actions():
    assert _decide("paths", "python_bin", "", "/py", force=False).action == "fill"
    assert _decide("paths", "python_bin", "/py", "/py", force=False).action == "keep"
    assert _decide("paths", "python_bin", "/a", "/b", force=False).action == "manual"
    assert _decide("paths", "python_bin", "/a", "/b", force=True).action == "update"


def main():
    test_strip_bom()
    test_upsert_creates_section_and_key()
    test_upsert_updates_existing()
    test_upsert_preserves_comments()
    test_write_text_no_bom()
    test_decide_actions()
    print("test_config_discover: PASS")


if __name__ == "__main__":
    main()
