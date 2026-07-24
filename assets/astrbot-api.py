#!/usr/bin/env python3
"""
AstrBot Skill - AstrBot WebUI / OpenAPI HTTP CLI.

Wraps AstrBot Dashboard HTTP endpoints so the model can drive plugin lifecycle,
read config, and chat via one-liners instead of curl + manual JSON shaping.

Two endpoint families:
  - /api/plugin/*        WebUI internal (reload/install/uninstall/on/off/...)
  - /api/v1/*            OpenAPI v1    (chat/bots/configs/files/...)

Auth: dashboard API key passed via --api-key or $ASTRBOT_API_KEY.

Transport modes:
  1) Direct HTTP to --base-url (default http://localhost:6185)
  2) --via-ssh: run curl on the remote host against 127.0.0.1:<port>
     (for dashboard bound to loopback only). Uses login.config / _common.

Usage:
    python astrbot-api.py plugins list
    python astrbot-api.py --via-ssh plugins reload --name my_plugin
    python astrbot-api.py --via-ssh --dash-port 62124 plugins list
    python astrbot-api.py plugins install --repo https://github.com/user/plug
    python astrbot-api.py config get
    python astrbot-api.py bots
    python astrbot-api.py chat --session s1 --text "hello"
    python astrbot-api.py raw --method POST --path /api/plugin/reload --json '{"name":"x"}'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "http://localhost:6185"
ENV_API_KEY = "ASTRBOT_API_KEY"
TIMEOUT = 30
DEFAULT_DASH_PORT = 6185

# Optional SSH backend (lazy import so pure-HTTP use needs no paramiko path issues)
_SSH = None


def _ssh():
    global _SSH
    if _SSH is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _common as common  # noqa: WPS433

        _SSH = common
    return _SSH


class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class Transport:
    """Abstracts direct HTTP vs SSH-side curl."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout: int,
        via_ssh: bool,
        dash_port: int,
        login_config: str | None,
        host: str | None,
        port: int | None,
        user: str | None,
        password: str | None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.via_ssh = via_ssh
        self.dash_port = dash_port
        self._creds = None
        self._client = None
        if via_ssh:
            common = _ssh()
            self._creds = common.load_credentials(
                explicit_path=login_config,
                host=host,
                port=port,
                user=user,
                password=password,
            )
            # Prefer loopback on remote
            self.base_url = f"http://127.0.0.1:{dash_port}"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
    ) -> tuple[int, str]:
        if not path.startswith("/"):
            path = "/" + path
        url = self.base_url + path
        if self.via_ssh:
            return self._request_via_ssh(method, url, body)
        return self._request_direct(method, url, body)

    def _request_direct(
        self, method: str, url: str, body: dict | None
    ) -> tuple[int, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise ApiError(e.code, body_text) from None

    def _request_via_ssh(
        self, method: str, url: str, body: dict | None
    ) -> tuple[int, str]:
        common = _ssh()
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        body_str = None
        if body is not None:
            body_str = json.dumps(body, ensure_ascii=False)
            headers["Content-Type"] = "application/json; charset=utf-8"

        if self._client is None:
            self._client = common.connect(self._creds)

        r = common.remote_http_request(
            self._creds,
            method,
            url,
            headers=headers,
            body=body_str,
            timeout=self.timeout,
            client=self._client,
        )
        text = r.stdout or ""
        # Parse trailing status marker from curl -w
        status = 0
        m = re.search(r"\n__HTTP_STATUS__:(\d+)\s*$", text)
        if m:
            status = int(m.group(1))
            text = text[: m.start()]
        elif r.rc != 0:
            raise ApiError(
                0,
                f"remote curl failed rc={r.rc}\nstdout={text}\nstderr={r.stderr}",
            )
        if status >= 400:
            raise ApiError(status, text)
        if status == 0 and not text and r.rc != 0:
            raise ApiError(0, r.stderr or "empty response")
        # If marker missing but curl succeeded, treat as 200
        if status == 0:
            status = 200
        return status, text


def _print_json(text: str) -> None:
    try:
        obj = json.loads(text) if text else None
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    except json.JSONDecodeError:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")


def cmd_plugins_list(t: Transport) -> int:
    last_err = None
    for path in ("/api/plugin/get", "/api/plugins"):
        try:
            status, text = t.request("GET", path)
            _print_json(text)
            return 0 if status < 400 else 1
        except ApiError as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return 1


def cmd_plugins_reload(t: Transport, name: str | None, all_: bool) -> int:
    if all_:
        status, text = t.request("POST", "/api/plugin/reload", body={})
    else:
        if not name:
            sys.stderr.write("reload requires --name or --all\n")
            return 2
        status, text = t.request("POST", "/api/plugin/reload", body={"name": name})
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_install(t: Transport, repo: str, proxy: str) -> int:
    body = {"repo_url": repo}
    if proxy:
        body["proxy"] = proxy
    status, text = t.request("POST", "/api/plugin/install", body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_uninstall(t: Transport, name: str) -> int:
    status, text = t.request("POST", "/api/plugin/uninstall", body={"plugin_name": name})
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_update(t: Transport, name: str) -> int:
    status, text = t.request("POST", "/api/plugin/update", body={"name": name})
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_on_off(t: Transport, name: str, on: bool) -> int:
    path = "/api/plugin/on" if on else "/api/plugin/off"
    status, text = t.request("POST", path, body={"name": name})
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_reload_failed(t: Transport) -> int:
    status, text = t.request("POST", "/api/plugin/reload-failed", body={})
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_config_get(t: Transport) -> int:
    status, text = t.request("GET", "/api/v1/configs")
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_bots(t: Transport) -> int:
    status, text = t.request("GET", "/api/v1/im/bots")
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_chat(t: Transport, session: str, text: str) -> int:
    status, body = t.request(
        "POST",
        "/api/v1/chat",
        body={"session_id": session, "text": text},
    )
    _print_json(body)
    return 0 if status < 400 else 1


def cmd_raw(t: Transport, method: str, path: str, json_arg: str | None) -> int:
    body = None
    if json_arg:
        try:
            body = json.loads(json_arg)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"invalid --json: {e}\n")
            return 2
    status, text = t.request(method.upper(), path, body=body)
    _print_json(text)
    return 0 if status < 400 else 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="AstrBot WebUI/OpenAPI HTTP CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("ASTRBOT_BASE_URL", DEFAULT_BASE_URL),
        help=f"dashboard base URL (default: {DEFAULT_BASE_URL} or $ASTRBOT_BASE_URL)",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get(ENV_API_KEY),
        help=f"API key for X-API-Key (or ${ENV_API_KEY})",
    )
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    p.add_argument(
        "--via-ssh",
        action="store_true",
        help="call dashboard via remote curl (127.0.0.1 on server)",
    )
    p.add_argument(
        "--dash-port",
        type=int,
        default=int(os.environ.get("ASTRBOT_DASH_PORT", DEFAULT_DASH_PORT)),
        help=f"remote dashboard port when --via-ssh (default {DEFAULT_DASH_PORT})",
    )
    # SSH credential flags (used only with --via-ssh)
    p.add_argument("--login-config")
    p.add_argument("--host")
    p.add_argument("--port", type=int, help="SSH port")
    p.add_argument("--user")
    p.add_argument("--pass", dest="password")

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

    sub.add_parser("bots", help="GET /api/v1/im/bots")

    s_chat = sub.add_parser("chat", help="POST /api/v1/chat")
    s_chat.add_argument("--session", required=True)
    s_chat.add_argument("--text", required=True)

    s_raw = sub.add_parser("raw", help="arbitrary HTTP call")
    s_raw.add_argument("--method", required=True)
    s_raw.add_argument("--path", required=True)
    s_raw.add_argument("--json", help="JSON body string")

    args = p.parse_args()

    import socket

    socket.setdefaulttimeout(args.timeout)

    t = Transport(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
        via_ssh=args.via_ssh,
        dash_port=args.dash_port,
        login_config=args.login_config,
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
    )
    try:
        if args.action == "plugins":
            pa = args.plug_action
            if pa == "list":
                return cmd_plugins_list(t)
            if pa == "reload":
                return cmd_plugins_reload(t, args.name, args.all_)
            if pa == "install":
                return cmd_plugins_install(t, args.repo, args.proxy)
            if pa == "uninstall":
                return cmd_plugins_uninstall(t, args.name)
            if pa == "update":
                return cmd_plugins_update(t, args.name)
            if pa == "on":
                return cmd_plugins_on_off(t, args.name, on=True)
            if pa == "off":
                return cmd_plugins_on_off(t, args.name, on=False)
            if pa == "reload-failed":
                return cmd_plugins_reload_failed(t)
        if args.action == "config":
            if args.cfg_action == "get":
                return cmd_config_get(t)
        if args.action == "bots":
            return cmd_bots(t)
        if args.action == "chat":
            return cmd_chat(t, args.session, args.text)
        if args.action == "raw":
            return cmd_raw(t, args.method, args.path, args.json)
    except ApiError as e:
        sys.stderr.write(f"{e}\n")
        return max(e.status // 100, 1) if e.status else 1
    except urllib.error.URLError as e:
        sys.stderr.write(f"network error: {e}\n")
        return 1
    except Exception as e:
        # surface SSH config errors cleanly
        sys.stderr.write(f"error: {e}\n")
        return 1
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
