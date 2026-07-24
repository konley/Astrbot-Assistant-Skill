"""
AstrBot Skill - SSH common library.

Shared foundation for all remote-operation tools in this skill. Provides:
  - login.config discovery + parsing (single source of truth)
  - skill root resolution
  - connection management
  - exec / batch exec / read_file / write_file / upload / download / upload_dir
  - ExecResult dataclass for structured command output

Design rules:
  - Never print to stdout from library code; return structured results.
    CLI wrappers decide what to print.
  - Raise specific exceptions (SshConfigError, SshExecError) so callers can
    catch granularly.
  - All file writes go through SFTP (no heredoc, no BOM issues).

Imported by: ssh-exec.py, config-tool.py, plugin-scaffold.py, astrbot-api.py
(for --via-ssh).

Usage:
    import sys; sys.path.insert(0, str(Path(__file__).parent))
    from _common import load_credentials, connect, exec_command, read_file, write_file
"""
from __future__ import annotations

import configparser
import json
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import paramiko
except ImportError as e:
    raise ImportError(
        "paramiko not installed. Run: pip install paramiko"
    ) from e


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SshConfigError(Exception):
    """login.config missing / malformed."""


class SshExecError(Exception):
    """Remote command failed (non-zero exit or SSH error)."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GitProfile:
    """One git/GitHub identity (personal, company, ...)."""
    name: str
    user: str = ""
    email: str = ""
    github: str = ""

    def identity(self) -> tuple[str, str]:
        return (self.user or "", self.email or "")

    def repo_url(self, plugin_name: str) -> str:
        root = (self.github or "").rstrip("/")
        if not root or not plugin_name:
            return ""
        return f"{root}/{plugin_name}"


@dataclass
class Credentials:
    host: str
    port: int
    username: str
    password: str
    source: str = ""  # path or "flags"
    github_url: str = ""  # active profile github (compat)
    git_user: str = ""    # active profile user (compat)
    git_email: str = ""   # active profile email (compat)
    git_default: str = "personal"
    git_profiles: dict = field(default_factory=dict)  # name -> GitProfile
    # Optional Dashboard / OpenAPI settings (astrbot-api.py)
    dashboard_port: int | None = None
    dashboard_api_key: str = ""

    def __str__(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"

    def profile(self, name: str | None = None) -> "GitProfile":
        """Return named profile or default; empty profile if missing."""
        key = (name or self.git_default or "personal").strip() or "personal"
        profiles: dict = self.git_profiles or {}
        if key in profiles:
            return profiles[key]
        # fallback aliases
        for alt in ("personal", "default", "company"):
            if alt in profiles:
                return profiles[alt]
        if profiles:
            return next(iter(profiles.values()))
        return GitProfile(
            name=key,
            user=self.git_user or "",
            email=self.git_email or "",
            github=self.github_url or "",
        )

    def git_identity(self, profile: str | None = None) -> tuple[str, str]:
        """Return (user.name, user.email) for git commit/push config."""
        p = self.profile(profile)
        return p.identity()

    def with_active_profile(self, name: str | None = None) -> "Credentials":
        """Return a copy-like view with compat fields set from profile."""
        p = self.profile(name)
        self.git_default = p.name
        self.git_user = p.user
        self.git_email = p.email
        self.github_url = p.github
        return self



@dataclass
class ExecResult:
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


@dataclass
class BatchStepResult:
    index: int
    command: str
    result: ExecResult


@dataclass
class UploadDirResult:
    uploaded: int = 0
    skipped: int = 0
    bytes_sent: int = 0
    files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Paths / skill root
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDE_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".vscode",
}
DEFAULT_EXCLUDE_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
}


def skill_root() -> Path:
    """Return the skill directory that contains assets/ and SKILL.md.

    Resolution order:
      1. $ASTRBOT_SKILL_ROOT if it points to a dir with SKILL.md
      2. parent of this file (assets/..)
    """
    env = os.environ.get(ENV_SKILL_ROOT)
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "SKILL.md").is_file():
            return p
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# login.config discovery + parsing  (single source of truth)
# ---------------------------------------------------------------------------
#
# Supported formats (auto-detected):
#   1) INI  (recommended)  — sections [ssh] / [git], comments allowed
#   2) JSON                — {"ssh":{...},"git":{...}}  or login.config.json
#   3) Legacy line-based   — positional host:port / user / password lines
#
# Auto-template: when missing, load_credentials() writes a fill-in template
# to the preferred project path and raises SshConfigError with that path.
# ---------------------------------------------------------------------------

LOGIN_CONFIG_FILENAME = "login.config"
LOGIN_CONFIG_JSON_FILENAME = "login.config.json"
LOGIN_CONFIG_FILENAMES = (LOGIN_CONFIG_FILENAME, LOGIN_CONFIG_JSON_FILENAME)
ENV_VAR = "ASTRBOT_LOGIN_CONFIG"
ENV_SKILL_ROOT = "ASTRBOT_SKILL_ROOT"

# Placeholders that mean "user has not filled yet"
_PLACEHOLDER_VALUES = {
    "",
    "your_password_here",
    "your_ssh_password",
    "your_dashboard_api_key_here",
    "change_me",
    "changeme",
    "<password>",
    "<your_password>",
    "<api_key>",
    "xxx",
    "TODO",
    "todo",
}

LOGIN_CONFIG_INI_TEMPLATE = """\
# =============================================================================
# AstrBot skill credentials  (login.config)
# Encoding: UTF-8 without BOM
# DO NOT commit this file to git.
#
# [ssh]       required for remote ops
# [git]       personal identity ONLY — plugin author / commit / push 唯一来源
#             目的：避免被本机 global 公司 git 账号误 push
# [dashboard] optional — astrbot-api.py WebUI/OpenAPI（端口常非默认）
#             API key 在 WebUI「设置 → API Keys」创建，不是 cmd_config 字段
#
# Verify SSH:  python assets/ssh-exec.py whoami
# Verify git:  python assets/git-identity.py show
# Pre-push:    python assets/git-identity.py check-push --repo <plugin_dir>
# API smoke:   python assets/astrbot-api.py --via-ssh plugins list
# =============================================================================

[ssh]
# Required
host = 127.0.0.1
port = 22
user = root
password = your_password_here

[git]
# 个人身份（唯一默认）。不要填公司账号。
user = yourname
email = you@example.com
# GitHub 账号/组织根 URL（用于 metadata.yaml repo 字段）
github = https://github.com/yourname

[dashboard]
# Optional. Used by astrbot-api.py (X-API-Key + remote port)
# Get key: WebUI → 设置 → API Keys → 创建（前缀通常 abk_...）
# Priority: --api-key / --dash-port > env > this file
# 你的实例若不在 6185，请改 port（例如 62124）
port = 6185
api_key =
"""

LOGIN_CONFIG_JSON_TEMPLATE = """\
{
  "ssh": {
    "host": "127.0.0.1",
    "port": 22,
    "user": "root",
    "password": "your_password_here"
  },
  "git": {
    "user": "yourname",
    "email": "you@example.com",
    "github": "https://github.com/yourname"
  },
  "dashboard": {
    "port": 6185,
    "api_key": ""
  }
}
"""


def _candidate_login_dirs() -> list[Path]:
    """Dirs to search for login.config (deduped, order preserved)."""
    seen: set[str] = set()
    out: list[Path] = []

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            rp = p.expanduser().resolve()
        except OSError:
            return
        key = str(rp).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(rp)

    cwd = Path.cwd()
    add(cwd)
    for parent in cwd.parents:
        add(parent)

    # skill root and its parents (junction-friendly)
    try:
        sr = skill_root()
        add(sr)
        add(sr.parent)
        for parent in sr.parents:
            add(parent)
    except OSError:
        pass

    # assets dir parent walk (when cwd is elsewhere)
    try:
        ad = assets_dir()
        add(ad.parent)
        add(ad.parent.parent)
    except OSError:
        pass

    return out


def preferred_login_config_path(*, fmt: str = "ini") -> Path:
    """Best path for a new login.config template (project root preferred).

    Preference:
      1. cwd if it looks like a project (has .git / SKILL.md / AstrBot)
      2. skill parent (workspace that contains the skill folder)
      3. cwd
    """
    name = LOGIN_CONFIG_JSON_FILENAME if fmt == "json" else LOGIN_CONFIG_FILENAME
    cwd = Path.cwd()
    markers = (".git", "SKILL.md", "AstrBot", "Astrbot-Assistant-Skill")

    def score(d: Path) -> int:
        s = 0
        try:
            for m in markers:
                if (d / m).exists():
                    s += 2 if m in (".git", "Astrbot-Assistant-Skill") else 1
        except OSError:
            return -1
        return s

    candidates: list[Path] = [cwd]
    try:
        candidates.append(skill_root().parent)
        candidates.append(skill_root())
    except OSError:
        pass

    best = max(candidates, key=score)
    return best / name


def write_login_config_template(
    path: Path | None = None,
    *,
    fmt: str = "ini",
    force: bool = False,
) -> Path:
    """Write a fill-in template. Raises SshConfigError if exists and not force."""
    fmt = (fmt or "ini").lower().strip()
    if fmt not in ("ini", "json"):
        raise SshConfigError(f"unsupported login.config format: {fmt!r} (use ini|json)")
    target = path or preferred_login_config_path(fmt=fmt)
    target = Path(target).expanduser()
    if target.exists() and not force:
        raise SshConfigError(
            f"login.config already exists: {target}\n"
            "Use force=True / --force to overwrite, or edit the existing file."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    body = LOGIN_CONFIG_JSON_TEMPLATE if fmt == "json" else LOGIN_CONFIG_INI_TEMPLATE
    # Always write UTF-8 without BOM
    target.write_text(body, encoding="utf-8", newline="\n")
    return target.resolve()


def find_login_config(
    explicit: str | None = None,
    *,
    searched: list[str] | None = None,
) -> Path | None:
    """Locate login.config / login.config.json.

    Order:
      1. explicit arg
      2. $ASTRBOT_LOGIN_CONFIG
      3. cwd + parents
      4. skill root + parents / assets
    If `searched` list is provided, append every candidate path checked.
    """
    def note(p: Path) -> None:
        if searched is not None:
            searched.append(str(p))

    if explicit:
        p = Path(explicit).expanduser().resolve()
        note(p)
        return p if p.is_file() else None

    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser().resolve()
        note(p)
        return p if p.is_file() else None

    for d in _candidate_login_dirs():
        for name in LOGIN_CONFIG_FILENAMES:
            cand = d / name
            note(cand)
            if cand.is_file():
                return cand
    return None


def _strip_bom(text: str) -> str:
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _is_placeholder(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    low = v.lower()
    if low in {x.lower() for x in _PLACEHOLDER_VALUES if x}:
        return True
    if v.startswith("<") and v.endswith(">"):
        return True
    return False


def _kv_line(line: str) -> tuple[str, str] | None:
    for sep in ("=", ":", "："):
        if sep in line:
            k, v = line.split(sep, 1)
            k, v = k.strip().lower(), v.strip().strip('"').strip("'")
            if k and v:
                return k, v
    return None


def _creds_from_fields(
    *,
    host: str,
    port: int | None,
    user: str,
    password: str,
    github: str = "",
    git_user: str = "",
    git_email: str = "",
    source: str = "",
    git_default: str = "personal",
    git_profiles: dict | None = None,
    dashboard_port: int | None = None,
    dashboard_api_key: str = "",
) -> Credentials:
    host = (host or "").strip()
    user = (user or "").strip()
    password = (password or "").strip()
    if not host or not user or not password or _is_placeholder(password):
        raise SshConfigError(
            f"login.config incomplete at {source or '(unknown)'}."
            "\n"
            "Required [ssh] fields: host, user, password (non-placeholder)."
            "\n"
            "Edit the file, then re-run. Example:"
            "\n"
            "  [ssh]\n  host = 1.2.3.4\n  port = 22\n  user = root\n  password = ...\n"
            "Or: python assets/ssh-exec.py init-config --force"
        )
    profiles: dict[str, GitProfile] = {}
    for k, v in (git_profiles or {}).items():
        if isinstance(v, GitProfile):
            profiles[k] = v
        elif isinstance(v, dict):
            profiles[k] = GitProfile(
                name=k,
                user=str(v.get("user") or v.get("name") or ""),
                email=str(v.get("email") or ""),
                github=str(v.get("github") or v.get("url") or "").rstrip("/"),
            )
    # Ensure default profile has values from flat fields
    dname = (git_default or "personal").strip() or "personal"
    if dname not in profiles and (git_user or git_email or github):
        profiles[dname] = GitProfile(
            name=dname,
            user=(git_user or "").strip(),
            email=(git_email or "").strip(),
            github=(github or "").rstrip("/"),
        )
    elif dname in profiles:
        p = profiles[dname]
        if not p.user and git_user:
            p.user = git_user.strip()
        if not p.email and git_email:
            p.email = git_email.strip()
        if not p.github and github:
            p.github = github.rstrip("/")
    # Compat active fields from default profile
    active = profiles.get(dname) or (
        next(iter(profiles.values())) if profiles else GitProfile(name=dname)
    )
    dash_key = (dashboard_api_key or "").strip()
    if _is_placeholder(dash_key):
        dash_key = ""
    dash_port = dashboard_port
    if dash_port is not None:
        try:
            dash_port = int(dash_port)
        except (TypeError, ValueError) as e:
            raise SshConfigError(
                f"invalid dashboard.port in {source or '(unknown)'}: {dashboard_port!r}"
            ) from e
    return Credentials(
        host=host,
        port=int(port or 22),
        username=user,
        password=password,
        source=source,
        github_url=active.github or (github or "").rstrip("/"),
        git_user=active.user or (git_user or "").strip(),
        git_email=active.email or (git_email or "").strip(),
        git_default=dname,
        git_profiles=profiles,
        dashboard_port=dash_port,
        dashboard_api_key=dash_key,
    )


def _parse_login_ini(text: str, path: Path) -> Credentials:
    cp = configparser.ConfigParser()
    try:
        cp.read_string(text)
    except configparser.Error as e:
        raise SshConfigError(f"login.config INI parse error at {path}: {e}") from e

    ssh_sec = None
    git_sec = None
    dash_sec = None
    profile_secs: dict[str, str] = {}  # profile_name -> section name
    for name in cp.sections():
        low = name.lower()
        if low in ("ssh", "server", "remote", "connection"):
            ssh_sec = name
        elif low == "git":
            git_sec = name
        elif low.startswith("git."):
            profile_secs[low.split(".", 1)[1]] = name
        elif low in ("github", "vcs"):
            git_sec = git_sec or name
        elif low in ("dashboard", "webui", "openapi", "api"):
            dash_sec = name

    if ssh_sec is None:
        raise SshConfigError(
            f"login.config INI missing [ssh] section: {path}"
        )

    def g(sec: str | None, *keys: str, default: str = "") -> str:
        if not sec:
            return default
        for k in keys:
            if cp.has_option(sec, k):
                return cp.get(sec, k).strip()
        return default

    host = g(ssh_sec, "host", "ip", "hostname", "server")
    port_s = g(ssh_sec, "port", default="22")
    user = g(ssh_sec, "user", "username", "name", "ssh_user")
    password = g(ssh_sec, "password", "pass", "psw", "pwd")
    try:
        port = int(port_s) if port_s else 22
    except ValueError as e:
        raise SshConfigError(f"invalid ssh.port in {path}: {port_s!r}") from e

    git_default = g(git_sec, "default", "profile", "active", default="personal") or "personal"
    # flat fields on [git]
    flat_user = g(git_sec, "user", "name", "git_user")
    flat_email = g(git_sec, "email", "git_email", "mail")
    flat_github = g(git_sec, "github", "repo", "url", "github_url")

    profiles: dict[str, GitProfile] = {}
    for pname, sec in profile_secs.items():
        profiles[pname] = GitProfile(
            name=pname,
            user=g(sec, "user", "name", "git_user"),
            email=g(sec, "email", "git_email", "mail"),
            github=g(sec, "github", "repo", "url", "github_url").rstrip("/"),
        )

    # If no [git.xxx], treat flat [git] as default profile
    if not profiles and (flat_user or flat_email or flat_github):
        profiles[git_default] = GitProfile(
            name=git_default,
            user=flat_user,
            email=flat_email,
            github=flat_github.rstrip("/"),
        )
    else:
        # seed default profile from flat if empty
        if git_default not in profiles and (flat_user or flat_email or flat_github):
            profiles[git_default] = GitProfile(
                name=git_default,
                user=flat_user,
                email=flat_email,
                github=flat_github.rstrip("/"),
            )
        elif git_default in profiles:
            p = profiles[git_default]
            if not p.user and flat_user:
                p.user = flat_user
            if not p.email and flat_email:
                p.email = flat_email
            if not p.github and flat_github:
                p.github = flat_github.rstrip("/")

    active = profiles.get(git_default) or (
        next(iter(profiles.values())) if profiles else GitProfile(name=git_default)
    )

    dash_port_s = g(dash_sec, "port", "dash_port", "dashboard_port", default="")
    dash_key = g(
        dash_sec,
        "api_key",
        "apikey",
        "key",
        "token",
        "dashboard_api_key",
        default="",
    )
    dash_port: int | None = None
    if dash_port_s:
        try:
            dash_port = int(dash_port_s)
        except ValueError as e:
            raise SshConfigError(
                f"invalid dashboard.port in {path}: {dash_port_s!r}"
            ) from e

    return _creds_from_fields(
        host=host,
        port=port,
        user=user,
        password=password,
        github=active.github or flat_github,
        git_user=active.user or flat_user,
        git_email=active.email or flat_email,
        source=str(path),
        git_default=git_default,
        git_profiles=profiles,
        dashboard_port=dash_port,
        dashboard_api_key=dash_key,
    )



def _parse_login_json(text: str, path: Path) -> Credentials:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SshConfigError(f"login.config JSON parse error at {path}: {e}") from e
    if not isinstance(data, dict):
        raise SshConfigError(f"login.config JSON root must be object: {path}")

    ssh = data.get("ssh") or data.get("server") or data
    git = data.get("git") or data.get("github") or {}
    if not isinstance(ssh, dict):
        raise SshConfigError(f"login.config JSON.ssh must be object: {path}")
    if not isinstance(git, dict):
        git = {}

    host = str(ssh.get("host") or ssh.get("ip") or ssh.get("hostname") or "")
    port = ssh.get("port", 22)
    user = str(ssh.get("user") or ssh.get("username") or ssh.get("name") or "")
    password = str(ssh.get("password") or ssh.get("pass") or ssh.get("psw") or "")
    try:
        port_i = int(port)
    except (TypeError, ValueError) as e:
        raise SshConfigError(f"invalid ssh.port in {path}: {port!r}") from e

    git_default = str(git.get("default") or git.get("profile") or "personal")
    profiles: dict[str, GitProfile] = {}
    raw_profiles = git.get("profiles") or {}
    if isinstance(raw_profiles, dict):
        for k, v in raw_profiles.items():
            if not isinstance(v, dict):
                continue
            profiles[str(k)] = GitProfile(
                name=str(k),
                user=str(v.get("user") or v.get("name") or ""),
                email=str(v.get("email") or ""),
                github=str(v.get("github") or v.get("url") or "").rstrip("/"),
            )
    # flat git fields
    flat_user = str(git.get("user") or git.get("name") or git.get("git_user") or "")
    flat_email = str(git.get("email") or git.get("git_email") or git.get("mail") or "")
    flat_github = str(
        git.get("github") or git.get("url") or git.get("repo") or data.get("github") or ""
    ).rstrip("/")
    if not profiles and (flat_user or flat_email or flat_github):
        profiles[git_default] = GitProfile(
            name=git_default, user=flat_user, email=flat_email, github=flat_github
        )

    active = profiles.get(git_default) or (
        next(iter(profiles.values())) if profiles else GitProfile(name=git_default)
    )

    dash = data.get("dashboard") or data.get("webui") or data.get("openapi") or {}
    if not isinstance(dash, dict):
        dash = {}
    dash_port_raw = dash.get("port", dash.get("dash_port"))
    dash_port: int | None = None
    if dash_port_raw not in (None, ""):
        try:
            dash_port = int(dash_port_raw)
        except (TypeError, ValueError) as e:
            raise SshConfigError(
                f"invalid dashboard.port in {path}: {dash_port_raw!r}"
            ) from e
    dash_key = str(
        dash.get("api_key")
        or dash.get("apikey")
        or dash.get("key")
        or dash.get("token")
        or data.get("api_key")
        or ""
    )

    return _creds_from_fields(
        host=host,
        port=port_i,
        user=user,
        password=password,
        github=active.github or flat_github,
        git_user=active.user or flat_user,
        git_email=active.email or flat_email,
        source=str(path),
        git_default=git_default,
        git_profiles=profiles,
        dashboard_port=dash_port,
        dashboard_api_key=dash_key,
    )



def _parse_login_legacy(text: str, path: Path) -> Credentials:
    """Legacy positional / mixed key:value lines (backward compatible)."""
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if len(lines) < 3:
        raise SshConfigError(
            f"login.config needs >=3 non-empty lines (legacy), got {len(lines)}: {path}"
        )

    host = ""
    port: int | None = None
    user = ""
    psw = ""
    github = ""
    git_user = ""
    git_email = ""

    l0 = lines[0]
    pair = _kv_line(l0)
    hostport = l0
    if pair and pair[0] in ("ssh", "host", "远程", "服务器", "主机"):
        hostport = pair[1]
    mhost = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{2,5}))?", hostport)
    if mhost:
        host = mhost.group(1)
        port = int(mhost.group(2)) if mhost.group(2) else 22
    else:
        if pair and pair[0] in ("ssh", "host"):
            parts = pair[1].rsplit(":", 1)
        else:
            parts = hostport.rsplit(":", 1)
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 22

    l1 = lines[1]
    pair = _kv_line(l1)
    if pair and pair[0] in ("name", "user", "username", "ssh_user", "sshuser"):
        user = pair[1]
    else:
        user = l1

    l2 = lines[2]
    pair = _kv_line(l2)
    if pair and pair[0] in ("psw", "pass", "password", "pwd"):
        psw = pair[1]
    else:
        psw = l2

    for ln in lines[3:]:
        if re.match(r"^https?://", ln, re.I):
            github = ln.rstrip("/")
            continue
        pair = _kv_line(ln)
        if not pair:
            continue
        k, v = pair
        if k in ("github", "repo", "gh"):
            github = v.rstrip("/")
        elif k in ("git_user", "git.user", "github_user", "gituser"):
            git_user = v
        elif k in ("git_email", "git.email", "email", "gitemail"):
            git_email = v
        elif k in ("port",) and v.isdigit():
            port = int(v)

    return _creds_from_fields(
        host=host,
        port=port or 22,
        user=user,
        password=psw,
        github=github,
        git_user=git_user,
        git_email=git_email,
        source=str(path),
    )


def detect_login_format(text: str, path: Path | None = None) -> str:
    """Return 'json' | 'ini' | 'legacy'."""
    t = _strip_bom(text).lstrip()
    if path is not None and path.suffix.lower() == ".json":
        return "json"
    if t.startswith("{"):
        return "json"
    if re.search(r"^\s*\[[^\]]+\]\s*$", t, re.M):
        return "ini"
    return "legacy"


def parse_login_config(path: Path) -> Credentials:
    """Parse login.config into Credentials (SSH + optional git identity).

    Formats (auto-detected):
      - INI (recommended)::

            [ssh]
            host = 1.2.3.4
            port = 22
            user = root
            password = secret

            [git]
            user = name
            email = you@example.com
            github = https://github.com/you

            [dashboard]
            port = 6185
            api_key = abk_...

      - JSON::

            {"ssh":{"host":"...","port":22,"user":"...","password":"..."},
             "git":{"user":"...","email":"...","github":"..."},
             "dashboard":{"port":6185,"api_key":"abk_..."}}

      - Legacy line-based (still supported).
    """
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    text = _strip_bom(raw)
    fmt = detect_login_format(text, path)
    if fmt == "json":
        return _parse_login_json(text, path)
    if fmt == "ini":
        return _parse_login_ini(text, path)
    return _parse_login_legacy(text, path)


def load_credentials(
    *,
    explicit_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    quiet: bool = False,
    auto_template: bool = True,
    template_format: str = "ini",
) -> Credentials:
    """Resolve credentials: prefer explicit fields, else read login.config.

    If config is missing and auto_template=True, write a fill-in template to the
    preferred project path and raise SshConfigError pointing at that file.
    """
    if host and user and password:
        return Credentials(
            host=host,
            port=port or 22,
            username=user,
            password=password,
            source="flags",
        )

    searched: list[str] = []
    cfg = find_login_config(explicit_path, searched=searched)
    if cfg is None:
        created: Path | None = None
        err_create = ""
        if auto_template and not explicit_path:
            try:
                created = write_login_config_template(fmt=template_format, force=False)
            except SshConfigError:
                created = None
            except OSError as e:
                created = None
                err_create = str(e)

        preview = "\n  ".join(searched[:12]) if searched else "(none)"
        more = f"\n  ... and {len(searched) - 12} more" if len(searched) > 12 else ""
        if created is not None:
            raise SshConfigError(
                "login.config not found — created a template for you to fill in:\n"
                f"  {created}\n"
                "Edit [ssh] host/user/password (and optional [git]), then re-run.\n"
                "JSON users: python assets/ssh-exec.py init-config --format json\n"
                f"Also searched:\n  {preview}{more}"
            )
        raise SshConfigError(
            "login.config not found.\n"
            "Provide --host/--user/--pass, or --login-config PATH, or set "
            f"${ENV_VAR}, or place login.config in project/skill root.\n"
            "Generate a template: python assets/ssh-exec.py init-config\n"
            f"Searched:\n  {preview}{more}"
            + (f"\n(template write failed: {err_create})" if err_create else "")
        )
    creds = parse_login_config(cfg)
    if not quiet:
        import sys
        sys.stderr.write(f"[_common] using {creds} (from {cfg})\n")
    return creds


# ---------------------------------------------------------------------------
# Connection + exec primitives
# ---------------------------------------------------------------------------

def connect(creds: Credentials, timeout: int = 15) -> paramiko.SSHClient:
    """Open a new SSH client. Caller is responsible for closing."""
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(
            creds.host,
            port=creds.port,
            username=creds.username,
            password=creds.password,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:
        raise SshExecError(
            f"SSH connect failed to {creds}: {type(e).__name__}: {e}"
        ) from e
    return c


def exec_command(
    creds: Credentials,
    command: str,
    *,
    timeout: int = 120,
    client: paramiko.SSHClient | None = None,
) -> ExecResult:
    """Run a shell command remotely. Returns ExecResult.

    If `client` is None, opens a fresh connection and closes it after.
    If `client` provided, reuses it (caller closes).
    """
    own_client = client is None
    if own_client:
        client = connect(creds)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return ExecResult(rc=rc, stdout=out, stderr=err)
    except Exception as e:
        if isinstance(e, SshExecError):
            raise
        raise SshExecError(
            f"exec failed on {creds}: {type(e).__name__}: {e}\ncommand: {command}"
        ) from e
    finally:
        if own_client:
            client.close()


def exec_batch(
    creds: Credentials,
    commands: list[str],
    *,
    timeout: int = 120,
    stop_on_error: bool = False,
    client: paramiko.SSHClient | None = None,
) -> list[BatchStepResult]:
    """Run multiple commands on a single SSH connection."""
    own_client = client is None
    if own_client:
        client = connect(creds)
    results: list[BatchStepResult] = []
    try:
        for i, cmd in enumerate(commands):
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue
            r = exec_command(creds, cmd, timeout=timeout, client=client)
            results.append(BatchStepResult(index=len(results) + 1, command=cmd, result=r))
            if stop_on_error and not r.ok:
                break
        return results
    finally:
        if own_client:
            client.close()


def read_file(
    creds: Credentials,
    remote_path: str,
    *,
    client: paramiko.SSHClient | None = None,
) -> str:
    """Read a remote file via SFTP. Raises SshExecError on missing/failed."""
    own_client = client is None
    if own_client:
        client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open(remote_path, "r") as f:
                content = f.read().decode("utf-8", errors="replace")
            return content
        except FileNotFoundError as e:
            raise SshExecError(f"remote file not found: {remote_path}") from e
        finally:
            sftp.close()
    finally:
        if own_client:
            client.close()


def write_file(
    creds: Credentials,
    remote_path: str,
    content: str,
    *,
    client: paramiko.SSHClient | None = None,
) -> None:
    """Write string content to a remote path via SFTP (no BOM, no heredoc)."""
    own_client = client is None
    if own_client:
        client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = str(Path(remote_path).as_posix()).rsplit("/", 1)[0]
            if remote_dir and remote_dir != remote_path:
                _ensure_remote_dir(sftp, remote_dir)
            # Encode as UTF-8 without BOM; write as binary for paramiko safety
            data = content.encode("utf-8")
            with sftp.open(remote_path, "wb") as f:
                f.write(data)
        finally:
            sftp.close()
    finally:
        if own_client:
            client.close()


def upload_file(
    creds: Credentials,
    local_path: str,
    remote_path: str,
    *,
    client: paramiko.SSHClient | None = None,
) -> None:
    """SFTP upload a local file. Creates remote parent dirs."""
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"local not found: {local_path}")
    own_client = client is None
    if own_client:
        client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            remote_posix = remote_path.replace("\\", "/")
            remote_dir = remote_posix.rsplit("/", 1)[0] if "/" in remote_posix else ""
            if remote_dir:
                _ensure_remote_dir(sftp, remote_dir)
            sftp.put(local_path, remote_posix)
        finally:
            sftp.close()
    finally:
        if own_client:
            client.close()


def download_file(
    creds: Credentials,
    remote_path: str,
    local_path: str,
    *,
    client: paramiko.SSHClient | None = None,
) -> None:
    """SFTP download a remote file to local."""
    own_client = client is None
    if own_client:
        client = connect(creds)
    try:
        sftp = client.open_sftp()
        try:
            local_p = Path(local_path)
            local_p.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote_path, str(local_p))
        except FileNotFoundError as e:
            raise SshExecError(f"remote not found: {remote_path}") from e
        finally:
            sftp.close()
    finally:
        if own_client:
            client.close()


def _should_exclude(
    rel_posix: str,
    *,
    exclude_dirs: set[str],
    exclude_suffixes: set[str],
) -> bool:
    parts = rel_posix.split("/")
    for part in parts[:-1]:
        if part in exclude_dirs:
            return True
    name = parts[-1] if parts else ""
    if name in exclude_dirs:
        return True
    lower = name.lower()
    for suf in exclude_suffixes:
        if lower.endswith(suf):
            return True
    return False


def upload_dir(
    creds: Credentials,
    local_dir: str,
    remote_dir: str,
    *,
    exclude_dirs: set[str] | None = None,
    exclude_suffixes: set[str] | None = None,
    client: paramiko.SSHClient | None = None,
) -> UploadDirResult:
    """Recursively upload a local directory via SFTP (single connection)."""
    local_root = Path(local_dir).resolve()
    if not local_root.is_dir():
        raise FileNotFoundError(f"local dir not found: {local_dir}")

    ex_dirs = set(exclude_dirs or DEFAULT_EXCLUDE_DIR_NAMES)
    ex_suf = set(exclude_suffixes or DEFAULT_EXCLUDE_FILE_SUFFIXES)
    remote_root = remote_dir.replace("\\", "/").rstrip("/")

    own_client = client is None
    if own_client:
        client = connect(creds)
    result = UploadDirResult()
    try:
        sftp = client.open_sftp()
        try:
            _ensure_remote_dir(sftp, remote_root)
            for dirpath, dirnames, filenames in os.walk(local_root):
                # prune excluded dirs in-place
                dirnames[:] = [d for d in dirnames if d not in ex_dirs]
                rel_dir = Path(dirpath).relative_to(local_root).as_posix()
                if rel_dir == ".":
                    rel_dir = ""
                remote_subdir = (
                    remote_root if not rel_dir else f"{remote_root}/{rel_dir}"
                )
                _ensure_remote_dir(sftp, remote_subdir)
                for name in filenames:
                    rel = f"{rel_dir}/{name}" if rel_dir else name
                    rel = rel.replace("\\", "/")
                    if _should_exclude(rel, exclude_dirs=ex_dirs, exclude_suffixes=ex_suf):
                        result.skipped += 1
                        continue
                    local_file = Path(dirpath) / name
                    remote_file = f"{remote_root}/{rel}"
                    sftp.put(str(local_file), remote_file)
                    size = local_file.stat().st_size
                    result.uploaded += 1
                    result.bytes_sent += size
                    result.files.append(rel)
        finally:
            sftp.close()
    finally:
        if own_client:
            client.close()
    return result


def _ensure_remote_dir(sftp: "paramiko.SFTPClient", remote_dir: str) -> None:
    """Recursively ensure a remote directory exists via SFTP. Idempotent."""
    if not remote_dir or remote_dir in (".", "/"):
        return
    remote_dir = remote_dir.replace(chr(92), "/").rstrip("/")
    absolute = remote_dir.startswith("/")
    parts = [p for p in remote_dir.split("/") if p]
    cur = "" if absolute else "."
    for part in parts:
        cur = f"/{part}" if cur == "" else f"{cur}/{part}"
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            try:
                sftp.mkdir(cur)
            except OSError:
                pass



def remote_http_request(
    creds: Credentials,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: int = 60,
    client: paramiko.SSHClient | None = None,
) -> ExecResult:
    """Run curl on the remote host (for dashboard bound to 127.0.0.1)."""
    # Build a safe curl command. Body via stdin-ish: use --data-binary with printf
    # For simplicity write body to a temp file when present.
    import base64
    import shlex

    method = method.upper()
    hdr_args = []
    for k, v in (headers or {}).items():
        hdr_args.append(f"-H {shlex.quote(f'{k}: {v}')}")
    hdr_s = " ".join(hdr_args)

    if body is not None:
        b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
        cmd = (
            f"BODY=$(printf '%s' {shlex.quote(b64)} | base64 -d) && "
            f"curl -sS -X {shlex.quote(method)} {hdr_s} "
            f"--data-binary \"$BODY\" "
            f"-w '\\n__HTTP_STATUS__:%{{http_code}}' "
            f"{shlex.quote(url)}"
        )
    else:
        cmd = (
            f"curl -sS -X {shlex.quote(method)} {hdr_s} "
            f"-w '\\n__HTTP_STATUS__:%{{http_code}}' "
            f"{shlex.quote(url)}"
        )
    return exec_command(creds, cmd, timeout=timeout, client=client)


# ---------------------------------------------------------------------------
# Convenience: invoke_shell for interactive commands (astrbot init etc.)
# ---------------------------------------------------------------------------

def invoke_shell_send(
    creds: Credentials,
    lines: list[str],
    *,
    read_timeout: float = 5.0,
    inter_send_delay: float = 1.5,
) -> str:
    """Open an interactive shell, send lines one by one, return full output.

    Use ONLY for commands that need terminal interaction (e.g. `astrbot init`
    with Y/n prompts). For normal commands use exec_command.
    """
    client = connect(creds)
    try:
        ch = client.invoke_shell()
        ch.settimeout(read_timeout)
        out_buf: list[str] = []
        for i, line in enumerate(lines):
            if i == 0:
                time.sleep(inter_send_delay)
                while ch.recv_ready():
                    out_buf.append(ch.recv(4096).decode("utf-8", errors="replace"))
            ch.send(line + "\n")
            time.sleep(inter_send_delay)
            while ch.recv_ready():
                out_buf.append(ch.recv(4096).decode("utf-8", errors="replace"))
        ch.close()
        return "".join(out_buf)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Self-test when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys as _sys

    p = argparse.ArgumentParser(description="SSH common lib self-test")
    p.add_argument("--login-config")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("show-creds", help="parse + print credentials only")
    sub.add_parser("skill-root", help="print resolved skill root")
    s_exec = sub.add_parser("exec", help="run one command to verify connectivity")
    s_exec.add_argument("command")
    args = p.parse_args()
    if args.action == "skill-root":
        print(skill_root())
        raise SystemExit(0)
    creds = load_credentials(explicit_path=args.login_config)
    if args.action in (None, "show-creds"):
        print(f"host={creds.host} port={creds.port} user={creds.username} source={creds.source}")
    elif args.action == "exec":
        r = exec_command(creds, args.command)
        print(r.stdout, end="")
        if r.stderr:
            print(r.stderr, end="", file=_sys.stderr)
        print(f"[rc={r.rc}]", file=_sys.stderr)
