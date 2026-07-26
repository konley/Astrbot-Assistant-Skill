#!/usr/bin/env python3
"""
AstrBot Skill - AstrBot WebUI / OpenAPI HTTP CLI.

Wraps AstrBot Dashboard HTTP endpoints so the model can drive plugin lifecycle,
read config, and chat via one-liners instead of curl + manual JSON shaping.

Endpoint family (prefer OpenAPI v1 — works with X-API-Key):
  - /api/v1/*            OpenAPI v1 (plugins / chat / bots / configs / ...)
  - /api/plugin/*        WebUI legacy (JWT cookie/Bearer only; API key ignored by middleware)

Auth resolution for X-API-Key (first non-empty wins):
  1) --api-key
  2) $ASTRBOT_API_KEY
  3) login.config [dashboard].api_key

Dashboard port resolution for --via-ssh (first set wins):
  1) --dash-port
  2) $ASTRBOT_DASH_PORT
  3) login.config [dashboard].port
  4) default 6185

Transport modes:
  1) Direct HTTP to --base-url (default http://localhost:6185)
     Preferred when login.config [runtime].mode=local (skill on robot host).
  2) --via-ssh: remote curl against 127.0.0.1:<dash-port> via login.config / _common
     Preferred when runtime.mode=remote (skill on a laptop).
  3) Auto: if --via-ssh not set and resolved mode is remote, still default to
     direct HTTP (backward compatible). Pass --via-ssh for remote loopback.

Usage:
    python astrbot-api.py plugins list
    python astrbot-api.py --via-ssh plugins reload --name my_plugin
    python astrbot-api.py --via-ssh plugins list   # uses [dashboard] port/key if set
    python astrbot-api.py plugins install --repo https://github.com/user/plug
    python astrbot-api.py config get
    python astrbot-api.py bots
    python astrbot-api.py chat --session s1 --text "hello"
    python astrbot-api.py raw --method GET --path /api/v1/plugins
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
ENV_DASH_PORT = "ASTRBOT_DASH_PORT"
TIMEOUT = 30
DEFAULT_DASH_PORT = 6185

_SSH = None


def _ssh():
    global _SSH
    if _SSH is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _common as common  # noqa: WPS433

        _SSH = common
    return _SSH


class ApiError(Exception):
    def __init__(self, status: int, body: str, *, hint: str = ""):
        msg = f"HTTP {status}: {body}"
        if hint:
            msg = f"{msg}\n{hint}"
        super().__init__(msg)
        self.status = status
        self.body = body
        self.hint = hint


def _mask_key(key: str | None) -> str:
    k = (key or "").strip()
    if not k:
        return "(empty)"
    if len(k) <= 8:
        return k[:2] + "***"
    return f"{k[:6]}...{k[-4:]} (len={len(k)})"


def auth_help_text(*, has_key: bool, login_config: str | None = None) -> str:
    """Clear guidance when API key is missing or rejected."""
    cfg = login_config or "login.config (project/skill nearby)"
    lines = [
        "---- astrbot-api auth help ----",
        "This CLI calls AstrBot Dashboard HTTP APIs with header X-API-Key.",
        "Used for: plugins list/reload/install, bots, chat, config get, etc.",
        "NOT needed for: ssh-exec / sync-plugin / config-tool / git-identity.",
        "",
        "How to get a key:",
        "  1) Open WebUI → 设置 / Settings → API Keys → 创建",
        "  2) Copy the raw key once (usually starts with abk_...)",
        "  3) Scope at least: plugin (and chat/config/im if you need those)",
        "",
        "How to set it (priority high → low):",
        "  --api-key <key>",
        f"  env ${ENV_API_KEY}",
        f"  {cfg}  →  [dashboard] api_key = ...",
        "",
        "Dashboard port (when --via-ssh; your instance may not be 6185):",
        "  --dash-port <port>  |  env $ASTRBOT_DASH_PORT  |  [dashboard] port = ...",
        "  Discover: python scripts/config-tool.py get dashboard.port",
        "",
        "No-API fallback for plugin files:",
        "  python scripts/ssh-exec.py sync-plugin ./my_plugin --name my_plugin",
        "  (then reload via WebUI or after API key is set)",
    ]
    if has_key:
        lines.insert(
            1,
            "A key WAS sent but server returned 401/403 — key wrong, revoked, "
            "or missing required scope (need 'plugin' for plugin APIs).",
        )
    else:
        lines.insert(1, "No API key found in --api-key / env / login.config [dashboard].")
    lines.append("--------------------------------")
    return "\n".join(lines)


def load_dashboard_settings(
    login_config: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    need_ssh: bool = False,
):
    """Return (Credentials|None, api_key, dash_port|None, source_path).

    When need_ssh=True, load full credentials (raises on missing SSH).
    When need_ssh=False, still try to read optional dashboard fields from config.
    """
    common = _ssh()
    if need_ssh:
        creds = common.load_credentials(
            explicit_path=login_config,
            host=host,
            port=port,
            user=user,
            password=password,
            quiet=True,
        )
        return (
            creds,
            (creds.dashboard_api_key or "").strip(),
            creds.dashboard_port,
            creds.source,
        )

    # Optional: read login.config only for dashboard key/port
    try:
        cfg = common.find_login_config(login_config)
        if cfg is None:
            return None, "", None, ""
        creds = common.parse_login_config(cfg)
        return (
            creds,
            (creds.dashboard_api_key or "").strip(),
            creds.dashboard_port,
            str(cfg),
        )
    except Exception:
        return None, "", None, ""


def resolve_api_key(
    cli_key: str | None,
    cfg_key: str = "",
) -> str:
    for candidate in (cli_key, os.environ.get(ENV_API_KEY), cfg_key):
        v = (candidate or "").strip()
        if v:
            return v
    return ""


def resolve_dash_port(
    cli_port: int | None,
    cfg_port: int | None,
) -> int:
    if cli_port is not None:
        return int(cli_port)
    env = (os.environ.get(ENV_DASH_PORT) or "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    if cfg_port is not None:
        return int(cfg_port)
    return DEFAULT_DASH_PORT


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
        config_source: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip() or None
        self.timeout = timeout
        self.via_ssh = via_ssh
        self.dash_port = dash_port
        self.login_config = login_config
        self.config_source = config_source
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
                quiet=True,
            )
            self.config_source = self.config_source or self._creds.source
            # Prefer loopback on remote
            self.base_url = f"http://127.0.0.1:{dash_port}"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _auth_hint(self, status: int) -> str:
        if status in (401, 403):
            return auth_help_text(
                has_key=bool(self.api_key),
                login_config=self.config_source or self.login_config,
            )
        return ""

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
            raise ApiError(
                e.code, body_text, hint=self._auth_hint(e.code)
            ) from None

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
            raise ApiError(status, text, hint=self._auth_hint(status))
        if status == 0 and not text and r.rc != 0:
            raise ApiError(0, r.stderr or "empty response")
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


def _try_paths(
    t: Transport,
    attempts: list[tuple[str, str, dict | None]],
) -> tuple[int, str]:
    """Try (method, path, body) list; return first non-404 success or last error."""
    last_err: ApiError | None = None
    for method, path, body in attempts:
        try:
            status, text = t.request(method, path, body=body)
            return status, text
        except ApiError as e:
            last_err = e
            # try next only on not-found / method issues
            if e.status in (404, 405):
                continue
            # 401/403: don't silently keep hammering legacy JWT-only paths
            # unless this was a known-legacy fallback after v1 404
            if e.status in (401, 403) and path.startswith("/api/v1/"):
                # still allow one legacy attempt only if no key? no — raise with hint
                raise
            if e.status in (401, 403):
                raise
            continue
    if last_err:
        raise last_err
    raise ApiError(0, "no endpoint attempts configured")


def cmd_plugins_list(t: Transport) -> int:
    # Prefer OpenAPI v1 (API key). Legacy /api/plugin/* requires JWT middleware.
    status, text = _try_paths(
        t,
        [
            ("GET", "/api/v1/plugins", None),
            ("GET", "/api/plugin/get", None),
        ],
    )
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_reload(t: Transport, name: str | None, all_: bool) -> int:
    if all_:
        # v1 has no bulk reload; legacy empty body reloads all
        status, text = _try_paths(
            t,
            [
                ("POST", "/api/plugin/reload", {}),
            ],
        )
    else:
        if not name:
            sys.stderr.write("reload requires --name or --all\n")
            return 2
        status, text = _try_paths(
            t,
            [
                ("POST", f"/api/v1/plugins/{name}/reload", {}),
                ("POST", "/api/v1/plugins/reload", {"plugin_id": name, "name": name}),
                ("POST", "/api/plugin/reload", {"name": name}),
            ],
        )
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_install(t: Transport, repo: str, proxy: str) -> int:
    body_v1 = {"repository": repo, "url": repo}
    if proxy:
        body_v1["proxy"] = proxy
    body_legacy = {"repo_url": repo, "url": repo}
    if proxy:
        body_legacy["proxy"] = proxy
    status, text = _try_paths(
        t,
        [
            ("POST", "/api/v1/plugins/install/github", body_v1),
            ("POST", "/api/v1/plugins/install/url", body_v1),
            ("POST", "/api/plugin/install", body_legacy),
        ],
    )
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_uninstall(t: Transport, name: str) -> int:
    status, text = _try_paths(
        t,
        [
            ("DELETE", f"/api/v1/plugins/{name}", None),
            ("DELETE", f"/api/v1/plugins/by-id?plugin_id={name}", {"plugin_id": name}),
            ("POST", "/api/plugin/uninstall", {"plugin_name": name, "name": name}),
        ],
    )
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_update(t: Transport, name: str) -> int:
    status, text = _try_paths(
        t,
        [
            ("POST", f"/api/v1/plugins/{name}/update", {}),
            ("POST", "/api/v1/plugins/update", {"plugin_id": name, "name": name}),
            ("POST", "/api/plugin/update", {"name": name}),
        ],
    )
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_on_off(t: Transport, name: str, on: bool) -> int:
    status, text = _try_paths(
        t,
        [
            (
                "PATCH",
                "/api/v1/plugins/enabled",
                {"plugin_id": name, "name": name, "enabled": on},
            ),
            (
                "PATCH",
                f"/api/v1/plugins/{name}/enabled",
                {"enabled": on},
            ),
            (
                "POST",
                "/api/plugin/on" if on else "/api/plugin/off",
                {"name": name},
            ),
        ],
    )
    _print_json(text)
    return 0 if status < 400 else 1


def cmd_plugins_reload_failed(t: Transport) -> int:
    status, text = _try_paths(
        t,
        [
            ("POST", "/api/plugin/reload-failed", {}),
        ],
    )
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
        epilog=(
            "Auth: --api-key > $ASTRBOT_API_KEY > login.config [dashboard].api_key\n"
            "Port: --dash-port > $ASTRBOT_DASH_PORT > login.config [dashboard].port > 6185\n"
            "Get key: WebUI → Settings → API Keys (not cmd_config dashboard.api_key)."
        ),
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("ASTRBOT_BASE_URL", DEFAULT_BASE_URL),
        help=f"dashboard base URL (default: {DEFAULT_BASE_URL} or $ASTRBOT_BASE_URL)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help=f"API key for X-API-Key (or ${ENV_API_KEY} / login.config [dashboard].api_key)",
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
        default=None,
        help=(
            f"remote dashboard port when --via-ssh "
            f"(default: ${ENV_DASH_PORT} / login.config [dashboard].port / {DEFAULT_DASH_PORT})"
        ),
    )
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

    # Load optional/required login.config for dashboard settings + runtime mode
    cfg_key = ""
    cfg_port = None
    config_source = ""
    # Prefer full credential load so runtime.mode is available; fall back soft.
    _creds, cfg_key, cfg_port, config_source = load_dashboard_settings(
        args.login_config,
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        need_ssh=False,
    )
    resolved_mode = "remote"
    if _creds is not None:
        resolved_mode = getattr(_creds, "resolved_mode", None) or "remote"
        # If full parse was soft-failed earlier without mode, try proper load when via-ssh
    via_ssh = bool(args.via_ssh)
    if via_ssh and resolved_mode == "local":
        sys.stderr.write(
            "[astrbot-api] note: runtime.mode=local — ignoring --via-ssh, "
            "using direct HTTP to loopback dashboard\n"
        )
        via_ssh = False
    if via_ssh:
        # Ensure SSH-ready credentials (raises clearly if incomplete)
        _creds, cfg_key, cfg_port, config_source = load_dashboard_settings(
            args.login_config,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            need_ssh=True,
        )
        resolved_mode = getattr(_creds, "resolved_mode", "remote") or "remote"

    api_key = resolve_api_key(args.api_key, cfg_key)
    dash_port = resolve_dash_port(args.dash_port, cfg_port)

    # Base URL: if user left default and config has port, and not via-ssh, adjust local default
    base_url = args.base_url
    if (
        not via_ssh
        and base_url.rstrip("/") in (DEFAULT_BASE_URL, "http://127.0.0.1:6185")
        and cfg_port is not None
        and args.dash_port is None
        and not os.environ.get(ENV_DASH_PORT)
    ):
        base_url = f"http://127.0.0.1:{cfg_port}"

    if not api_key:
        # Soft preflight warning — still attempt request (auth may be off)
        sys.stderr.write(
            "[astrbot-api] warning: no API key "
            f"(--api-key / ${ENV_API_KEY} / login.config [dashboard].api_key)\n"
            "If the next call returns 401, fill [dashboard] api_key. "
            f"See help below after failure.\n"
            f"[astrbot-api] mode={resolved_mode} dash-port={dash_port} via_ssh={via_ssh} "
            f"key={_mask_key(api_key)} config={config_source or '(none)'}\n"
        )
    else:
        sys.stderr.write(
            f"[astrbot-api] mode={resolved_mode} dash-port={dash_port} via_ssh={via_ssh} "
            f"key={_mask_key(api_key)} config={config_source or '(flags/env)'}\n"
        )

    t = Transport(
        base_url=base_url,
        api_key=api_key or None,
        timeout=args.timeout,
        via_ssh=via_ssh,
        dash_port=dash_port,
        login_config=args.login_config,
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        config_source=config_source,
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
