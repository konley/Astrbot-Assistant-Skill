#!/usr/bin/env python3
"""
AstrBot Skill - Git identity lock (from login.config personal identity).

Purpose: prevent accidental commit/push with the machine's global/company
git user. The single source of truth is login.config [git] (personal).

Usage:
    python git-identity.py show
    python git-identity.py status [--repo PATH]
    python git-identity.py fix [--repo PATH]          # set local = login.config
    python git-identity.py ensure [--repo PATH] [--fix]
    python git-identity.py check-push [--repo PATH]   # gate before push

Rules:
  - Only sets *local* repo config (never global).
  - check-push exits 2 if local identity != login.config — do NOT push.
  - Prefer `fix` over asking about company accounts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Credentials,
    SshConfigError,
    load_credentials,
)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def _find_git_root(start: Path) -> Path | None:
    start = start.resolve()
    p = _git(start, "rev-parse", "--show-toplevel")
    if p.returncode == 0 and p.stdout.strip():
        return Path(p.stdout.strip())
    return None


def _cfg_get(repo: Path, key: str, scope: str) -> str:
    args = ["config"]
    if scope:
        args.append(f"--{scope}")
    args += ["--get", key]
    r = _git(repo, *args)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _read_identities(repo: Path) -> dict:
    return {
        "local": {
            "user": _cfg_get(repo, "user.name", "local"),
            "email": _cfg_get(repo, "user.email", "local"),
        },
        "global": {
            "user": _cfg_get(repo, "user.name", "global"),
            "email": _cfg_get(repo, "user.email", "global"),
        },
        "effective": {
            "user": _cfg_get(repo, "user.name", ""),
            "email": _cfg_get(repo, "user.email", ""),
        },
    }


def _load(login_config: str | None) -> Credentials:
    return load_credentials(explicit_path=login_config, quiet=True, auto_template=False)


def cmd_list(creds: Credentials) -> int:
    """Show the personal identity from login.config."""
    p = creds.profile()
    print(f"source: {creds.source}")
    print(f"identity: {p.user} <{p.email}>")
    print(f"github:   {p.github or '(empty)'}")
    print("note: this is the ONLY identity used for plugin author / commit / push")
    print("      (locks out machine global/company git config)")
    profiles = creds.git_profiles or {}
    if len(profiles) > 1:
        print(f"profiles_loaded: {', '.join(profiles.keys())} (default={creds.git_default})")
    return 0


def cmd_status(creds: Credentials, repo: Path, as_json: bool) -> int:
    root = _find_git_root(repo)
    ids = (
        _read_identities(root)
        if root
        else {
            "local": {"user": "", "email": ""},
            "global": {"user": "", "email": ""},
            "effective": {"user": "", "email": ""},
        }
    )
    active = creds.profile()
    match_local = bool(
        root
        and ids["local"]["user"] == active.user
        and ids["local"]["email"] == active.email
        and active.user
        and active.email
    )
    match_effective = bool(
        ids["effective"]["user"] == active.user
        and ids["effective"]["email"] == active.email
        and active.user
        and active.email
    )
    payload = {
        "login_config": creds.source,
        "identity": {
            "user": active.user,
            "email": active.email,
            "github": active.github,
        },
        "repo": str(root) if root else None,
        "git": ids,
        "match_local": match_local,
        "match_effective": match_effective,
        "warning": None,
    }
    if root and not match_local and active.user:
        payload["warning"] = (
            "Local git identity is NOT locked to login.config. "
            "Global/company identity may be used on push. "
            f"Run: python scripts/git-identity.py fix --repo {root}"
        )
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if match_local or not root else 3

    print(f"login_config: {payload['login_config']}")
    print(f"required (login.config): {active.user} <{active.email}>")
    print(f"github:                  {active.github or '(empty)'}")
    print(f"repo: {payload['repo'] or '(not a git repo)'}")
    print(f"git local:     {ids['local']['user']!r} <{ids['local']['email']!r}>")
    print(f"git global:    {ids['global']['user']!r} <{ids['global']['email']!r}>")
    print(f"git effective: {ids['effective']['user']!r} <{ids['effective']['email']!r}>")
    print(f"match_local: {match_local}")
    print(f"match_effective: {match_effective}")
    if payload["warning"]:
        print(f"WARNING: {payload['warning']}")
        return 3
    return 0


def cmd_use(creds: Credentials, profile: str | None, repo: Path) -> int:
    """Set local user.name/email from login.config identity."""
    root = _find_git_root(repo)
    if root is None:
        print(f"not a git repository: {repo}", file=sys.stderr)
        return 2
    p = creds.profile(profile)
    if not p.user or not p.email:
        print(
            f"login.config identity incomplete: user={p.user!r} email={p.email!r}\n"
            "Fill [git] user= and email= in login.config first.",
            file=sys.stderr,
        )
        return 2
    r1 = _git(root, "config", "--local", "user.name", p.user)
    r2 = _git(root, "config", "--local", "user.email", p.email)
    if r1.returncode != 0 or r2.returncode != 0:
        print((r1.stderr or r2.stderr or "git config failed").strip(), file=sys.stderr)
        return 1
    print(f"locked local identity on {root}")
    print(f"  user.name  = {p.user}")
    print(f"  user.email = {p.email}")
    print(f"  github     = {p.github or '(empty)'}")
    print("  (global config left unchanged)")
    return 0


def cmd_fix(creds: Credentials, repo: Path) -> int:
    """Force local user.name/email to login.config personal identity."""
    return cmd_use(creds, None, repo)


def cmd_ensure(creds: Credentials, profile: str | None, repo: Path, fix: bool) -> int:
    """Exit 0 if local matches login.config; 2 if mismatch."""
    root = _find_git_root(repo)
    if root is None:
        print(f"not a git repository: {repo}", file=sys.stderr)
        return 2
    p = creds.profile(profile)
    if not p.user or not p.email:
        print(
            "login.config [git] user/email empty — fill personal identity first.",
            file=sys.stderr,
        )
        return 2
    ids = _read_identities(root)
    ok = ids["local"]["user"] == p.user and ids["local"]["email"] == p.email
    if ok:
        print(f"OK local identity locked to login.config on {root}")
        print(f"  {p.user} <{p.email}>")
        return 0

    print(f"MISMATCH on {root}", file=sys.stderr)
    print(f"  login.config (required):     {p.user} <{p.email}>", file=sys.stderr)
    print(
        f"  git local:                   {ids['local']['user']} <{ids['local']['email']}>",
        file=sys.stderr,
    )
    print(
        f"  git global (often company):  {ids['global']['user']} <{ids['global']['email']}>",
        file=sys.stderr,
    )
    print(
        f"  git effective (would push):  {ids['effective']['user']} <{ids['effective']['email']}>",
        file=sys.stderr,
    )
    if fix:
        return cmd_use(creds, p.name if profile else None, root)
    print(
        "Refusing company/global fallback. Lock this repo to login.config:",
        file=sys.stderr,
    )
    print(f'  python scripts/git-identity.py fix --repo "{root}"', file=sys.stderr)
    print(
        "Then re-run check-push. (Only sets local config; global unchanged.)",
        file=sys.stderr,
    )
    return 2


def cmd_check_push(creds: Credentials, profile: str | None, repo: Path) -> int:
    """Gate before git push. Exit 0 only when local == login.config identity."""
    rc = cmd_ensure(creds, profile, repo, fix=False)
    if rc == 0:
        print("check-push: OK — will NOT fall back to company/global identity")
        return 0
    print(
        "check-push: BLOCKED — do NOT commit/push until identity is fixed.",
        file=sys.stderr,
    )
    print(
        "  python scripts/git-identity.py fix --repo <plugin_dir>",
        file=sys.stderr,
    )
    return 2


def _add_repo_arg(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--repo",
        default=".",
        help="repo path (default: cwd); may be after subcommand",
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Lock git local identity to login.config (avoid company global push)."
    )
    p.add_argument("--login-config")
    # Parent-level --repo works as: git-identity.py --repo PATH status
    p.add_argument("--repo", default=None, help="repo path (also accepted after subcommand)")
    p.add_argument("--json", action="store_true", dest="as_json")
    sub = p.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="show login.config personal identity")
    sub.add_parser("show", help="alias of list")
    s_st = sub.add_parser("status", help="compare login.config vs git config")
    _add_repo_arg(s_st)
    s_st.add_argument("--json", action="store_true", dest="as_json")
    s_use = sub.add_parser(
        "use",
        help="set *local* user.name/email from login.config (alias of fix)",
    )
    _add_repo_arg(s_use)
    s_use.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="optional profile name (default: login.config identity)",
    )
    s_fix = sub.add_parser(
        "fix",
        help="set local identity = login.config (recommended before push)",
    )
    _add_repo_arg(s_fix)
    s_en = sub.add_parser(
        "ensure",
        help="exit 2 if local identity != login.config",
    )
    _add_repo_arg(s_en)
    s_en.add_argument("--profile", help="optional profile name")
    s_en.add_argument(
        "--fix",
        action="store_true",
        help="apply login.config identity if mismatch",
    )
    s_cp = sub.add_parser(
        "check-push",
        help="pre-push gate: must match login.config (block company global)",
    )
    _add_repo_arg(s_cp)
    s_cp.add_argument("--profile")

    args = p.parse_args()
    repo_raw = getattr(args, "repo", None) or "."
    repo = Path(repo_raw).expanduser().resolve()
    try:
        creds = _load(args.login_config)
    except SshConfigError as e:
        print(f"credentials error: {e}", file=sys.stderr)
        return 2

    if args.action in ("list", "show"):
        return cmd_list(creds)
    if args.action == "status":
        return cmd_status(creds, repo, getattr(args, "as_json", False) or args.as_json)
    if args.action == "use":
        return cmd_use(creds, args.profile, repo)
    if args.action == "fix":
        return cmd_fix(creds, repo)
    if args.action == "ensure":
        return cmd_ensure(creds, args.profile, repo, args.fix)
    if args.action == "check-push":
        return cmd_check_push(creds, args.profile, repo)
    return 2


if __name__ == "__main__":
    _configure_stdio()
    sys.exit(main())