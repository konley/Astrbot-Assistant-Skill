# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_ssh_exec():
    """Load scripts/ssh-exec.py as a module (filename has a hyphen)."""
    import importlib.util

    path = ROOT / "scripts" / "ssh-exec.py"
    spec = importlib.util.spec_from_file_location("ssh_exec_mod", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["ssh_exec_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _creds(plugins_dir: str | None = None, data_dir: str | None = None, root: str = "/opt/astrbot"):
    paths = SimpleNamespace(
        astrbot_root=root,
        data_dir=data_dir or f"{root}/data",
        plugins_dir=plugins_dir or f"{(data_dir or f'{root}/data')}/plugins",
    )
    return SimpleNamespace(paths=paths)


def test_candidates_order_default():
    mod = _load_ssh_exec()
    c = mod.plugin_root_candidates(_creds())
    assert c[0] == "/opt/astrbot/data/plugins"
    assert "/opt/astrbot/data/plugins" in c
    assert c.index("/opt/astrbot/data/plugins") < c.index("/opt/astrbot/data/addons/plugins")


def test_candidates_override_first():
    mod = _load_ssh_exec()
    c = mod.plugin_root_candidates(_creds(), override="/custom/plugins")
    assert c[0] == "/custom/plugins"


def test_candidates_login_config_before_defaults():
    mod = _load_ssh_exec()
    c = mod.plugin_root_candidates(
        _creds(plugins_dir="/opt/astrbot/data/plugins")
    )
    assert c[0] == "/opt/astrbot/data/plugins"
    assert "/opt/astrbot/data/addons/plugins" in c


def test_candidates_custom_data_dir():
    mod = _load_ssh_exec()
    c = mod.plugin_root_candidates(
        _creds(plugins_dir="/srv/bot/data/plugins", data_dir="/srv/bot/data", root="/srv/bot")
    )
    assert c[0] == "/srv/bot/data/plugins"
    assert "/srv/bot/data/addons/plugins" in c
    assert "/srv/bot/data/plugins" in c


def test_candidates_dedupe():
    mod = _load_ssh_exec()
    c = mod.plugin_root_candidates(
        _creds(plugins_dir="/opt/astrbot/data/addons/plugins")
    )
    assert c.count("/opt/astrbot/data/addons/plugins") == 1


def test_resolve_no_probe_returns_first():
    mod = _load_ssh_exec()
    root = mod.resolve_plugin_root(
        _creds(plugins_dir="/opt/astrbot/data/plugins"),
        None,
        verify_remote=False,
        log=False,
    )
    assert root == "/opt/astrbot/data/plugins"


def test_resolve_falls_back_to_existing_legacy():
    mod = _load_ssh_exec()
    creds = _creds(plugins_dir="/opt/astrbot/data/addons/plugins")

    def fake_existing(_creds, paths, client=None):
        return [p for p in paths if p == "/opt/astrbot/data/plugins"]

    with patch.object(mod, "_remote_existing_dirs", side_effect=fake_existing):
        root = mod.resolve_plugin_root(creds, None, verify_remote=True, log=False)
    assert root == "/opt/astrbot/data/plugins"


def test_resolve_prefers_configured_when_exists():
    mod = _load_ssh_exec()
    creds = _creds(plugins_dir="/opt/astrbot/data/plugins")

    def fake_existing(_creds, paths, client=None):
        return list(paths)

    with patch.object(mod, "_remote_existing_dirs", side_effect=fake_existing):
        root = mod.resolve_plugin_root(creds, None, verify_remote=True, log=False)
    assert root == "/opt/astrbot/data/plugins"


def test_resolve_override_missing_falls_back():
    mod = _load_ssh_exec()
    creds = _creds()

    def fake_existing(_creds, paths, client=None):
        return [p for p in paths if p.endswith("/data/plugins")]

    with patch.object(mod, "_remote_existing_dirs", side_effect=fake_existing):
        root = mod.resolve_plugin_root(
            creds, "/does/not/exist", verify_remote=True, log=False
        )
    assert root == "/opt/astrbot/data/plugins"


def test_resolve_nothing_exists_uses_configured():
    mod = _load_ssh_exec()
    creds = _creds(plugins_dir="/opt/astrbot/data/addons/plugins")

    def fake_existing(_creds, paths, client=None):
        return []

    with patch.object(mod, "_remote_existing_dirs", side_effect=fake_existing):
        root = mod.resolve_plugin_root(creds, None, verify_remote=True, log=False)
    assert root == "/opt/astrbot/data/addons/plugins"


def main():
    test_candidates_order_default()
    test_candidates_override_first()
    test_candidates_login_config_before_defaults()
    test_candidates_custom_data_dir()
    test_candidates_dedupe()
    test_resolve_no_probe_returns_first()
    test_resolve_falls_back_to_existing_legacy()
    test_resolve_prefers_configured_when_exists()
    test_resolve_override_missing_falls_back()
    test_resolve_nothing_exists_uses_configured()
    print("test_plugin_root_resolve: PASS")


if __name__ == "__main__":
    main()
