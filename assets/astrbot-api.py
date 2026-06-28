#!/usr/bin/env python3
"""
AstrBot Skill - AstrBot WebUI / OpenAPI HTTP CLI.

Wraps AstrBot Dashboard HTTP endpoints so the model can drive plugin lifecycle,
read config, and chat via one-liners instead of curl + manual JSON shaping.

Two endpoint families:
  - /api/plugin/*        WebUI internal (reload/install/uninstall/on/off/...)
  - /api/v1/*            OpenAPI v1    (chat/bots/configs/files/...)

Auth: dashboard API key passed via --api-key or $ASTRBOT_API_KEY. The same key
works for both families (dashboard enforces it via the `X-API-Key` header on
/api/v1/*, and via session/api-key on /api/plugin/*). When --api-key is absent
the requests are sent without auth (works only if dashboard disabled auth).

The CLI does NOT do SSH. To operate a remote dashboard either:
  - set --base-url to the public address, or
  - establish an SSH tunnel first (see assets/tunnel-generator.html and
    ssh-exec.py) then point --base-url at the local forwarded port.

Usage:
    python astrbot-api.py plugins list
    python astrbot-api.py plugins reload --name my_plugin
    python astrbot-api.py plugins reload --all
    python astrbot-api.py plugins install --repo https://github.com/user/plug
    python astrbot-api.py plugins uninstall --name my_plugin
    python astrbot-api.py plugins on  --name my_plugin
    python astrbot-api.py plugins off --name my_plugin
    python astrbot-api.py plugins update --name my_plugin
    python astrbot-api.py plugins reload-failed
    python astrbot-api.py config get                       # GET /api/v1/configs
    python astrbot-api.py bots                             # GET /api/v1/im/bots
    python astrbot-api.py chat --session s1 --text "hello"
    python astrbot-api.py raw --method POST --path /api/plugin/reload --json '{"name":"x"}'

Output: JSON pretty-printed to stdout. Errors go to stderr with HTTP status.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:6185"
ENV_API_KEY = "ASTRBOT_API_KEY"
TIMEOUT = 30


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _request(
    method: str,
    url: str,
    *,
    api_key: str | None,
    body: dict | None = None,
    timeout: int = TIMEOUT,
) -> tuple[int, str]:
    """Send an HTTP request. Returns (status, response_text).

    Uses urllib (stdlib) so no extra deps. Raises ApiError on HTTP >= 400.
    Network errors raise urllib.error.URLError.
    """
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
        # IMPORTANT: no BOM. urllib encodes our str as UTF-8 without BOM.
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise ApiError(e.code, body_text) from None


def _print_json(text: str) -> None:
    """Pretty-print JSON if parseable, otherwise print raw."""
    try:
        obj = json.loads(text) if text else None
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    except json.JSONDecodeError:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_plugins_list(base: str, key: str | None) -> int:
    # WebUI exposes plugin list via /api/plugin/get (returns installed plugins).
    # Some versions use /api/plugins. Try both, prefer a successful JSON response.
    for path in ("/api/plugin/get", "/api/plugins"):
        try:
            status, text = _request("GET", base + path, api_key=key)
            _print_json(text)
            return 0
        except ApiError as e:
            if e.status == 404:
                continue
            sys.stderr.write(f"{e}\n")
            return e.status
    sys.stderr.write("plugin list endpoint not found (tried /api/plugin/get, /api/plugins)\n")
    return 1


def cmd_plugins_reload(base: str, key: str | None, name: str | None, all_: bool) -> int:
    body: dict = {}
    if all_:
        # omit name to reload all (per plugin-lifecycle.md)
        pass
    elif name:
        body["name"] = name
    else:
        sys.stderr.write("specify --name X or --all\n")
        return 2
    status, text = _request("POST", base + "/api/plugin/reload", api_key=key, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_install(base: str, key: str | None, repo: str, proxy: str = "") -> int:
    body = {"repo_url": repo}
    if proxy:
        body["proxy"] = proxy
    status, text = _request("POST", base + "/api/plugin/install", api_key=key, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_uninstall(base: str, key: str | None, name: str) -> int:
    body = {"plugin_name": name}
    status, text = _request("POST", base + "/api/plugin/uninstall", api_key=key, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_update(base: str, key: str | None, name: str) -> int:
    body = {"name": name}
    status, text = _request("POST", base + "/api/plugin/update", api_key=key, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_on_off(base: str, key: str | None, name: str, on: bool) -> int:
    path = "/api/plugin/on" if on else "/api/plugin/off"
    body = {"name": name}
    status, text = _request("POST", base + path, api_key=key, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_reload_failed(base: str, key: str | None) -> int:
    status, text = _request("POST", base + "/api/plugin/reload-failed", api_key=key, body={})
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_config_get(base: str, key: str | None) -> int:
    status, text = _request("GET", base + "/api/v1/configs", api_key=key)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_bots(base: str, key: str | None) -> int:
    status, text = _request("GET", base + "/api/v1/im/bots", api_key=key)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_chat(base: str, key: str | None, session: str, text: str) -> int:
    body = {"session_id": session, "text": text}
    status, resp_text = _request("POST", base + "/api/v1/chat", api_key=key, body=body)
    _print_json(resp_text)
    return 0 if status < 400 else 1


def cmd_raw(
    base: str, key: str | None, method: str, path: str, json_arg: str | None
) -> int:
    body = None
    if json_arg:
        try:
            body = json.loads(json_arg)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"invalid --json: {e}\n")
            return 2
    if not path.startswith("/"):
        path = "/" + path
    status, text = _request(method.upper(), base + path, api_key=key, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="AstrBot WebUI/OpenAPI HTTP CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--base-url", default=os.environ.get("ASTRBOT_BASE_URL", DEFAULT_BASE_URL),
                   help=f"AstrBot dashboard base URL (default: {DEFAULT_BASE_URL}, "
                        f"or $ASTRBOT_BASE_URL)")
    p.add_argument("--api-key", default=os.environ.get(ENV_API_KEY),
                   help=f"API key for X-API-Key header (or ${ENV_API_KEY})")
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    sub = p.add_subparsers(dest="action", required=True)

    s_plug = sub.add_parser("plugins", help="plugin lifecycle operations")
    plug_sub = s_plug.add_subparsers(dest="plug_action", required=True)

    plug_sub.add_parser("list", help="list installed plugins")

    s_reload = plug_sub.add_parser("reload", help="reload plugin(s)")
    s_reload.add_argument("--name")
    s_reload.add_argument("--all", action="store_true", dest="all_")

    s_install = plug_sub.add_parser("install", help="install from repo URL")
    s_install.add_argument("--repo", required=True)
    s_install.add_argument("--proxy", default="")

    s_uninstall = plug_sub.add_parser("uninstall", help="uninstall by name")
    s_uninstall.add_argument("--name", required=True)

    s_update = plug_sub.add_parser("update", help="update a plugin")
    s_update.add_argument("--name", required=True)

    s_on = plug_sub.add_parser("on", help="enable a plugin")
    s_on.add_argument("--name", required=True)

    s_off = plug_sub.add_parser("off", help="disable a plugin")
    s_off.add_argument("--name", required=True)

    plug_sub.add_parser("reload-failed", help="reload failed plugins")

    s_cfg = sub.add_parser("config", help="config operations")
    cfg_sub = s_cfg.add_subparsers(dest="cfg_action", required=True)
    cfg_sub.add_parser("get", help="GET /api/v1/configs")

    sub.add_parser("bots", help="GET /api/v1/im/bots (list bot accounts)")

    s_chat = sub.add_parser("chat", help="POST /api/v1/chat")
    s_chat.add_argument("--session", required=True)
    s_chat.add_argument("--text", required=True)

    s_raw = sub.add_parser("raw", help="arbitrary HTTP call")
    s_raw.add_argument("--method", required=True, help="GET/POST/...")
    s_raw.add_argument("--path", required=True, help="path beginning with /api/")
    s_raw.add_argument("--json", help="JSON body (string)")

    args = p.parse_args()
    base = args.base_url.rstrip("/")
    key = args.api_key

    # Set global timeout via env (urllib honors defaultsocket timeout)
    import socket
    socket.setdefaulttimeout(args.timeout)

    try:
        if args.action == "plugins":
            pa = args.plug_action
            if pa == "list":
                return cmd_plugins_list(base, key)
            if pa == "reload":
                return cmd_plugins_reload(base, key, args.name, args.all_)
            if pa == "install":
                return cmd_plugins_install(base, key, args.repo, args.proxy)
            if pa == "uninstall":
                return cmd_plugins_uninstall(base, key, args.name)
            if pa == "update":
                return cmd_plugins_update(base, key, args.name)
            if pa == "on":
                return cmd_plugins_on_off(base, key, args.name, on=True)
            if pa == "off":
                return cmd_plugins_on_off(base, key, args.name, on=False)
            if pa == "reload-failed":
                return cmd_plugins_reload_failed(base, key)
        if args.action == "config":
            if args.cfg_action == "get":
                return cmd_config_get(base, key)
        if args.action == "bots":
            return cmd_bots(base, key)
        if args.action == "chat":
            return cmd_chat(base, key, args.session, args.text)
        if args.action == "raw":
            return cmd_raw(base, key, args.method, args.path, args.json)
    except ApiError as e:
        sys.stderr.write(f"{e}\n")
        return max(e.status // 100, 1)
    except urllib.error.URLError as e:
        sys.stderr.write(f"network error: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
