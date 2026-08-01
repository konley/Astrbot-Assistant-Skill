from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_api_headers_and_chat_body():
    api = _load("astrbot-api")
    transport = object.__new__(api.Transport)
    transport.api_key = "abk_test"
    transport.timeout = 2
    transport.base_url = "http://127.0.0.1:1"
    transport.via_ssh = False
    captured = {}

    class Response:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data)
        return Response()

    with patch.object(api.urllib.request, "urlopen", fake_urlopen):
        api.cmd_chat(transport, "alice", "s1", "hello", False)

    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["x-api-key"] == "abk_test"
    assert headers["authorization"] == "Bearer abk_test"
    assert captured["body"] == {
        "username": "alice",
        "session_id": "s1",
        "message": "hello",
        "enable_streaming": False,
    }


def test_plugin_checker_current_adapters_and_assets(tmp_path: Path):
    checker = _load("plugin-check")
    plugin = tmp_path / "astrbot_plugin_demo"
    (plugin / ".astrbot-plugin" / "i18n").mkdir(parents=True)
    (plugin / "skills" / "helper").mkdir(parents=True)
    (plugin / "pages" / "settings").mkdir(parents=True)
    (plugin / "metadata.yaml").write_text(
        "name: astrbot_plugin_demo\n"
        "desc: demo\nversion: 0.1.0\nauthor: me\n"
        "repo: https://github.com/me/astrbot_plugin_demo\n"
        "support_platforms:\n  - mattermost\n  - wecom_ai_bot\n"
        "tags:\n  - demo\n",
        encoding="utf-8",
    )
    (plugin / "main.py").write_text(
        "from astrbot.api import logger\n"
        "from astrbot.api.star import Context, Star, register\n"
        '@register("astrbot_plugin_demo", "me", "demo", version="0.1.0")\n'
        "class Main(Star):\n"
        "    def __init__(self, context: Context):\n"
        "        super().__init__(context)\n"
        "        logger.info('[astrbot_plugin_demo] loaded')\n",
        encoding="utf-8",
    )
    (plugin / ".astrbot-plugin" / "i18n" / "zh-CN.json").write_text("{}", encoding="utf-8")
    (plugin / "skills" / "helper" / "SKILL.md").write_text("# Helper\n", encoding="utf-8")
    (plugin / "pages" / "settings" / "index.html").write_text("<h1>Settings</h1>", encoding="utf-8")

    report = checker.check_plugin(plugin, login_config=None)
    codes = {issue.code for issue in report.issues}
    assert report.ok
    assert "platforms" not in codes
    assert "i18n.parse" not in codes


if __name__ == "__main__":
    test_api_headers_and_chat_body()
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as td:
        test_plugin_checker_current_adapters_and_assets(Path(td))
    print("test_current_contracts: PASS")
