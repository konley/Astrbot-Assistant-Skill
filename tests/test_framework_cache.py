# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from framework_cache import (  # noqa: E402
    alignment_status,
    build_check_payload,
    exit_code_for_status,
    meta_is_fresh,
    normalize_version,
    parse_remote_probe_output,
    remote_version_probe_commands,
    versions_equal,
    write_meta,
    read_meta,
    local_framework_info,
)


def test_normalize_version():
    assert normalize_version("4.26.7") == "4.26.7"
    assert normalize_version("v4.26.7") == "4.26.7"
    assert normalize_version("AstrBot 4.26.7") == "4.26.7"
    assert normalize_version("version: v4.26.7+abc") == "4.26.7"
    assert normalize_version("") is None
    assert normalize_version(None) is None
    assert normalize_version("nope") is None


def test_versions_equal_and_status():
    assert versions_equal("v4.26.7", "4.26.7")
    assert not versions_equal("4.25.0", "4.26.7")
    assert alignment_status("4.26.7", "v4.26.7") == "match"
    assert alignment_status("4.25.0", "4.26.7") == "mismatch"
    assert alignment_status(None, "4.26.7") == "local_missing"
    assert alignment_status("4.26.7", None) == "remote_unknown"
    assert alignment_status(None, None) == "unknown"
    assert exit_code_for_status("match") == 0
    assert exit_code_for_status("mismatch") == 3
    assert exit_code_for_status("unknown") == 2


def test_parse_remote_probe_output():
    assert parse_remote_probe_output("4.26.7") == "4.26.7"
    assert parse_remote_probe_output("astrbot 4.26.7\n") == "4.26.7"
    assert parse_remote_probe_output("unknown") is None


def test_probe_order_prefers_uv_and_custom():
    cmds = remote_version_probe_commands(
        astrbot_root="/opt/astrbot",
        python_bin="/custom/python",
        unit="astrbot",
    )
    labels = [c[0] for c in cmds]
    assert labels[0] == "paths.python_bin"
    assert "uv.tool.python" in labels
    assert labels.index("uv.tool.python") < labels.index("python3.import")


def test_build_check_payload_mismatch_advice():
    local = {
        "version": "4.25.0",
        "cache_path": "/tmp/AstrBot",
        "exists": True,
        "git_head": "abc",
        "git_describe": "abc",
        "meta": None,
        "versioned_caches": [],
    }
    payload = build_check_payload(local=local, remote_version="v4.26.7", remote_raw="4.26.7")
    assert payload["status"] == "mismatch"
    assert payload["remote"]["version"] == "4.26.7"
    assert any("sync" in a for a in payload["advice"])


def test_meta_roundtrip_and_fresh():
    base = Path(tempfile.mkdtemp())
    write_meta(
        base,
        {
            "remote_version": "4.26.7",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    meta = read_meta(base)
    assert meta and meta["remote_version"] == "4.26.7"
    assert meta_is_fresh(meta, ttl_seconds=3600)
    old = {
        "synced_at": (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    }
    assert not meta_is_fresh(old, ttl_seconds=3600)


def test_local_framework_info_smoke():
    info = local_framework_info(ROOT)
    assert "cache_path" in info
    assert "exists" in info


if __name__ == "__main__":
    test_normalize_version()
    test_versions_equal_and_status()
    test_parse_remote_probe_output()
    test_probe_order_prefers_uv_and_custom()
    test_build_check_payload_mismatch_advice()
    test_meta_roundtrip_and_fresh()
    test_local_framework_info_smoke()
    print("test_framework_cache: PASS")
