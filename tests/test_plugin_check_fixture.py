# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load_plugin_check():
    path = SCRIPTS / "plugin-check.py"
    name = "plugin_check_mod"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _minimal_plugin(tmp: Path, name: str = "astrbot_plugin_demo") -> Path:
    d = tmp / name
    d.mkdir(parents=True)
    (d / "metadata.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                "desc: demo plugin for tests",
                "version: 0.1.0",
                "author: yourname",
                "repo: https://github.com/yourname/astrbot_plugin_demo",
                "support_platforms:",
                "  - aiocqhttp",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (d / "main.py").write_text(
        "from astrbot.api.star import Context, Star, register\n\n"
        f'@register("{name}", "yourname", "demo", "0.1.0")\n'
        "class Main(Star):\n"
        "    def __init__(self, context: Context):\n"
        "        super().__init__(context)\n",
        encoding="utf-8",
    )
    (d / "tests").mkdir()
    (d / "tests" / "test_smoke.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return d


def test_plugin_check_pass_minimal():
    mod = _load_plugin_check()
    with tempfile.TemporaryDirectory() as td:
        plugin = _minimal_plugin(Path(td))
        rep = mod.check_plugin(plugin, login_config=None)
        fails = [i for i in rep.issues if i.level == "FAIL"]
        assert not fails, fails


def test_plugin_check_fail_missing_metadata():
    mod = _load_plugin_check()
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "broken"
        d.mkdir()
        (d / "main.py").write_text("print('x')\n", encoding="utf-8")
        rep = mod.check_plugin(d, login_config=None)
        assert not rep.ok
        assert any(i.level == "FAIL" and "metadata" in i.code for i in rep.issues)


def test_plugin_check_warns_recommended_metadata():
    mod = _load_plugin_check()
    with tempfile.TemporaryDirectory() as td:
        plugin = _minimal_plugin(Path(td))
        rep = mod.check_plugin(plugin, login_config=None)
        codes = {i.code for i in rep.issues if i.level == "WARN"}
        assert "metadata.display_name" in codes
        assert "metadata.astrbot_version" in codes
        # still PASS (no FAIL)
        assert rep.ok


def test_plugin_check_no_fail_when_recommended_present():
    mod = _load_plugin_check()
    with tempfile.TemporaryDirectory() as td:
        plugin = _minimal_plugin(Path(td))
        meta = (plugin / "metadata.yaml").read_text(encoding="utf-8")
        meta = meta.replace(
            "version: 0.1.0\n",
            'version: 0.1.0\ndisplay_name: Demo\nastrbot_version: ">=4.16,<5"\n',
        )
        (plugin / "metadata.yaml").write_text(meta, encoding="utf-8")
        rep = mod.check_plugin(plugin, login_config=None)
        codes = {i.code for i in rep.issues if i.level == "WARN"}
        assert "metadata.display_name" not in codes
        assert "metadata.astrbot_version" not in codes
        assert rep.ok


if __name__ == "__main__":
    test_plugin_check_pass_minimal()
    test_plugin_check_fail_missing_metadata()
    test_plugin_check_warns_recommended_metadata()
    test_plugin_check_no_fail_when_recommended_present()
    print("test_plugin_check_fixture: PASS")
