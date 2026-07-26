# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import (  # noqa: E402
    Credentials,
    PathLayout,
    detect_local_install,
    exec_command,
    parse_login_config,
    read_file,
    resolve_runtime_mode,
    upload_dir,
    write_file,
)


def test_detect_local_install_tmp(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "opt" / "astrbot"
    data = root / "data"
    data.mkdir(parents=True)
    cfg = data / "cmd_config.json"
    cfg.write_text("{}", encoding="utf-8")
    layout = PathLayout(astrbot_root=str(root).replace("\\", "/"))
    # On Windows PathLayout still builds POSIX-like strings; pass absolute paths explicitly
    layout = PathLayout(
        astrbot_root=str(root),
        data_dir=str(data),
        cmd_config=str(cfg),
    )
    info = detect_local_install(layout)
    assert info["detected"] is True
    assert info["markers"]


def test_resolve_auto_prefers_local_when_markers(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "cmd_config.json"
    cfg.write_text("{}", encoding="utf-8")
    layout = PathLayout(astrbot_root=str(tmp_path), cmd_config=str(cfg), data_dir=str(tmp_path))
    req, resolved = resolve_runtime_mode(
        "auto",
        paths=layout,
        host="",
        user="",
        password="",
        identity_file="",
        allow_agent=False,
        env_mode="",
    )
    assert req == "auto"
    assert resolved == "local"


def test_local_file_ops_and_exec(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "login.config"
    target = tmp_path / "data" / "cmd_config.json"
    target.parent.mkdir(parents=True)
    cfg.write_text(
        "[runtime]\nmode=local\n"
        f"[paths]\nastrbot_root={tmp_path.as_posix()}\n"
        f"cmd_config={target.as_posix()}\n",
        encoding="utf-8",
    )
    c = parse_login_config(cfg)
    assert c.is_local()
    write_file(c, str(target), '{"ok": true}\n')
    body = read_file(c, str(target))
    assert "ok" in body
    # local exec
    if os.name == "nt":
        r = exec_command(c, "echo hello-local")
    else:
        r = exec_command(c, "echo hello-local")
    assert r.ok
    assert "hello-local" in (r.stdout or "")


def test_local_upload_dir_copy(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "plugin"
    src.mkdir()
    (src / "main.py").write_text("print(1)\n", encoding="utf-8")
    dst = tmp_path / "addons" / "plugins" / "demo"
    cfg = tmp_path / "login.config"
    cfg.write_text(
        "[runtime]\nmode=local\n"
        f"[paths]\nastrbot_root={tmp_path.as_posix()}\n",
        encoding="utf-8",
    )
    c = parse_login_config(cfg)
    result = upload_dir(c, str(src), str(dst))
    assert result.uploaded >= 1
    assert (dst / "main.py").is_file()


if __name__ == "__main__":
    base = Path(tempfile.mkdtemp())
    test_detect_local_install_tmp(base / "det")
    test_resolve_auto_prefers_local_when_markers(base / "auto")
    test_local_file_ops_and_exec(base / "ops")
    test_local_upload_dir_copy(base / "up")
    print("test_runtime_mode: PASS")
