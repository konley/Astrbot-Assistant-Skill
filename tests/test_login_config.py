# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import (  # noqa: E402
    PathLayout,
    SshConfigError,
    parse_login_config,
    write_login_config_template,
)


def test_path_layout_defaults():
    p = PathLayout()
    assert p.astrbot_root == "/opt/astrbot"
    assert p.plugins_dir.endswith("/addons/plugins")
    assert p.cmd_config.endswith("cmd_config.json")


def test_path_layout_custom_root():
    p = PathLayout(astrbot_root="/srv/bot")
    assert p.data_dir == "/srv/bot/data"
    assert p.plugins_dir == "/srv/bot/data/addons/plugins"


def test_parse_password_ini(tmp_path: Path):
    cfg = tmp_path / "login.config"
    cfg.write_text(
        "[ssh]\nhost=1.1.1.1\nuser=root\npassword=secret-pass\n"
        "[git]\nuser=yourname\nemail=a@b.c\ngithub=https://github.com/yourname\n",
        encoding="utf-8",
    )
    c = parse_login_config(cfg)
    assert c.host == "1.1.1.1"
    assert c.auth_methods() == ["password"]
    assert c.password == "secret-pass"


def test_parse_identity_ini(tmp_path: Path):
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    cfg = tmp_path / "login.config"
    cfg.write_text(
        f"[ssh]\nhost=2.2.2.2\nuser=ubuntu\nidentity_file={key.as_posix()}\n"
        "[paths]\nastrbot_root=/opt/x\nastrbot_unit=astrbot-x\npython_bin=/opt/x/bin/python\n",
        encoding="utf-8",
    )
    c = parse_login_config(cfg)
    assert c.auth_methods() == ["identity_file"]
    assert c.paths.astrbot_unit == "astrbot-x"
    assert c.paths.astrbot_root == "/opt/x"
    assert c.paths.python_bin == "/opt/x/bin/python"


def test_parse_json_key_and_paths(tmp_path: Path):
    key = tmp_path / "k"
    key.write_text("x", encoding="utf-8")
    cfg = tmp_path / "login.config.json"
    cfg.write_text(
        (
            '{"ssh":{"host":"3.3.3.3","user":"u","identity_file":"%s","allow_agent":true},'
            '"paths":{"astrbot_root":"/data/astrbot"}}'
        )
        % key.as_posix().replace("\\", "/"),
        encoding="utf-8",
    )
    c = parse_login_config(cfg)
    assert "identity_file" in c.auth_methods()
    assert "agent" in c.auth_methods()
    assert c.paths.data_dir == "/data/astrbot/data"


def test_incomplete_raises(tmp_path: Path):
    cfg = tmp_path / "login.config"
    cfg.write_text("[ssh]\nhost=1.1.1.1\nuser=root\npassword=your_password_here\n", encoding="utf-8")
    try:
        parse_login_config(cfg)
        assert False, "expected SshConfigError"
    except SshConfigError:
        pass


def test_template_write(tmp_path: Path):
    target = tmp_path / "login.config"
    out = write_login_config_template(path=target, fmt="ini", force=True)
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert "[ssh]" in body and "[paths]" in body and "identity_file" in body


if __name__ == "__main__":
    # minimal runner without pytest dependency
    tmp = Path(tempfile.mkdtemp())
    test_path_layout_defaults()
    test_path_layout_custom_root()
    test_parse_password_ini(tmp)
    test_parse_identity_ini(tmp)
    test_parse_json_key_and_paths(tmp)
    test_incomplete_raises(tmp)
    test_template_write(tmp)
    print("test_login_config: PASS")
