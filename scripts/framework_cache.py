# -*- coding: utf-8 -*-
"""Local AstrBot framework source-cache helpers.

Design:
  - Remote runtime version is the source of truth.
  - Local ./AstrBot (and versioned cache/) is read-only reference only.
  - Never fall back to untagged latest when a pin is required.
  - Meta file records last successful pin for TTL / offline checks.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ASTRBOT_REPO_URL = "https://github.com/AstrBotDevs/AstrBot"
META_FILENAME = "framework-cache.meta.json"
ACTIVE_DIRNAME = "AstrBot"
VERSIONED_CACHE_REL = Path("cache") / "AstrBot"
DEFAULT_META_TTL_SECONDS = 6 * 3600  # 6h

_VERSION_RE = re.compile(
    r"v?(?P<ver>\d+\.\d+\.\d+(?:[0-9A-Za-z._+-]*)?)",
    re.IGNORECASE,
)


def normalize_version(value: str | None) -> str | None:
    """Normalize version strings for comparison.

    Accepts: 4.26.7 | v4.26.7 | astrbot 4.26.7 | 4.26.7+foo
    Returns bare version without leading v, or None if unparseable.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Prefer first semver-like token
    m = _VERSION_RE.search(text)
    if not m:
        return None
    ver = m.group("ver").strip()
    # Drop build metadata for equality (4.26.7+abc -> 4.26.7) but keep pre-release
    if "+" in ver:
        ver = ver.split("+", 1)[0]
    return ver or None


def versions_equal(a: str | None, b: str | None) -> bool:
    na, nb = normalize_version(a), normalize_version(b)
    if not na or not nb:
        return False
    return na.lower() == nb.lower()


def alignment_status(local_v: str | None, remote_v: str | None) -> str:
    """Return match|mismatch|local_missing|remote_unknown|unknown."""
    ln, rn = normalize_version(local_v), normalize_version(remote_v)
    if ln and rn:
        return "match" if ln.lower() == rn.lower() else "mismatch"
    if rn and not ln:
        return "local_missing"
    if ln and not rn:
        return "remote_unknown"
    return "unknown"


def meta_path(skill_root: Path) -> Path:
    return Path(skill_root) / META_FILENAME


def active_cache_path(skill_root: Path) -> Path:
    return Path(skill_root) / ACTIVE_DIRNAME


def versioned_cache_path(skill_root: Path, version: str) -> Path:
    ver = normalize_version(version) or str(version).strip().lstrip("v")
    return Path(skill_root) / VERSIONED_CACHE_REL / ver


def read_meta(skill_root: Path) -> dict[str, Any] | None:
    path = meta_path(skill_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_meta(skill_root: Path, payload: dict[str, Any]) -> Path:
    path = meta_path(skill_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def meta_is_fresh(
    meta: dict[str, Any] | None,
    *,
    ttl_seconds: int = DEFAULT_META_TTL_SECONDS,
    now: float | None = None,
) -> bool:
    if not meta:
        return False
    ts = meta.get("synced_at") or meta.get("updated_at")
    if not ts:
        return False
    try:
        # support Z
        text = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (now if now is not None else time.time()) - dt.timestamp()
        return 0 <= age <= max(0, int(ttl_seconds))
    except (TypeError, ValueError, OSError):
        return False


def _read_version_from_tree(cache: Path) -> str | None:
    if not cache.is_dir():
        return None
    pyproject = cache / "pyproject.toml"
    init_py = cache / "astrbot" / "__init__.py"
    if pyproject.is_file():
        m = re.search(
            r'(?m)^version\s*=\s*["\']([^"\']+)["\']',
            pyproject.read_text(encoding="utf-8", errors="replace"),
        )
        if m:
            return normalize_version(m.group(1))
    if init_py.is_file():
        m = re.search(
            r'__version__\s*=\s*["\']([^"\']+)["\']',
            init_py.read_text(encoding="utf-8", errors="replace"),
        )
        if m:
            return normalize_version(m.group(1))
    return None


def _git(cache: Path, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(cache), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return int(r.returncode or 0), (r.stdout or "").strip(), (r.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", f"{type(e).__name__}: {e}"


def local_framework_info(skill_root: Path) -> dict[str, Any]:
    root = Path(skill_root)
    cache = active_cache_path(root)
    meta = read_meta(root)
    info: dict[str, Any] = {
        "cache_path": str(cache),
        "exists": cache.is_dir(),
        "version": None,
        "git_head": None,
        "git_describe": None,
        "meta": meta,
        "versioned_caches": [],
    }
    ver_root = root / VERSIONED_CACHE_REL
    if ver_root.is_dir():
        for child in sorted(ver_root.iterdir()):
            if child.is_dir():
                info["versioned_caches"].append(
                    {"path": str(child), "version": _read_version_from_tree(child) or child.name}
                )
    if not cache.is_dir():
        # fall back to meta-reported versioned path
        if meta and meta.get("active_path"):
            alt = Path(str(meta["active_path"]))
            if alt.is_dir():
                cache = alt
                info["cache_path"] = str(cache)
                info["exists"] = True
        else:
            return info

    info["version"] = _read_version_from_tree(cache)
    rc, out, _ = _git(cache, "rev-parse", "--short", "HEAD")
    if rc == 0 and out:
        info["git_head"] = out
    rc, out, _ = _git(cache, "describe", "--tags", "--always")
    if rc == 0 and out:
        info["git_describe"] = out
    return info


def remote_version_probe_commands(
    *,
    astrbot_root: str = "/opt/astrbot",
    python_bin: str = "",
    unit: str = "astrbot",
) -> list[tuple[str, str]]:
    """Ordered (label, shell_command) probes. Prefer uv/tool/service python."""
    root = (astrbot_root or "/opt/astrbot").rstrip("/") or "/opt/astrbot"
    unit = (unit or "astrbot").strip() or "astrbot"
    py_snippet = (
        "import astrbot; print(getattr(astrbot,'__version__','') "
        "or getattr(astrbot,'VERSION',''))"
    )
    cmds: list[tuple[str, str]] = []

    if python_bin:
        pb = python_bin.replace("'", "'\"'\"'")
        cmds.append(
            (
                "paths.python_bin",
                f"'{pb}' -c \"{py_snippet}\" 2>/dev/null",
            )
        )

    # Common uv tool install
    uv_py = "/root/.local/share/uv/tools/astrbot/bin/python"
    cmds.append(
        (
            "uv.tool.python",
            f"test -x {uv_py} && {uv_py} -c \"{py_snippet}\" 2>/dev/null",
        )
    )

    # ExecStart from systemd (extract binary path heuristically)
    cmds.append(
        (
            "systemd.ExecStart.python",
            (
                f"bin=$(systemctl show {unit} -p ExecStart --value 2>/dev/null "
                f"| tr ' ' '\\n' | grep -E 'python|astrbot' | head -1); "
                f"if [ -n \"$bin\" ] && [ -x \"$bin\" ]; then "
                f"  if echo \"$bin\" | grep -qi python; then "
                f"    \"$bin\" -c \"{py_snippet}\" 2>/dev/null; "
                f"  else "
                f"    \"$bin\" version 2>/dev/null || \"$bin\" --version 2>/dev/null; "
                f"  fi; "
                f"fi"
            ),
        )
    )

    cmds.append(("astrbot.version", "astrbot version 2>/dev/null"))
    cmds.append(("astrbot.--version", "astrbot --version 2>/dev/null"))

    # PATH python may be wrong; keep late
    cmds.append(
        (
            "python3.import",
            f"python3 -c \"{py_snippet}\" 2>/dev/null",
        )
    )
    cmds.append(
        (
            "workdir.venv",
            (
                f"for p in {root}/.venv/bin/python {root}/venv/bin/python; do "
                f"  if [ -x \"$p\" ]; then \"$p\" -c \"{py_snippet}\" 2>/dev/null && break; fi; "
                f"done"
            ),
        )
    )
    return cmds


def parse_remote_probe_output(raw: str) -> str | None:
    if not raw:
        return None
    # skip noise
    for line in str(raw).splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if "unknown" in low and not _VERSION_RE.search(line):
            continue
        ver = normalize_version(line)
        if ver:
            return ver
    return normalize_version(raw)


@dataclass
class SyncResult:
    ok: bool
    version: str | None
    path: str
    message: str
    meta: dict[str, Any] | None = None
    rc: int = 0


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    log: Callable[[str], None] | None = None,
    timeout: int = 600,
) -> int:
    if log:
        log("$ " + " ".join(args))
    try:
        r = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
        return int(r.returncode or 0)
    except (OSError, subprocess.SubprocessError) as e:
        if log:
            log(f"error: {type(e).__name__}: {e}")
        return 1


def _clone_pinned(tag: str, dest: Path, *, log: Callable[[str], None] | None = None) -> int:
    """Shallow clone a specific tag/branch only. No default-branch fallback."""
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            tag,
            ASTRBOT_REPO_URL,
            str(dest),
        ],
        log=log,
    )


def _fetch_tag_into_repo(repo: Path, tag: str, *, log: Callable[[str], None] | None = None) -> int:
    """Fetch one tag into an existing or empty git repo and checkout."""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        rc = _run(["git", "init"], cwd=repo, log=log)
        if rc != 0:
            return rc
        rc = _run(["git", "remote", "add", "origin", ASTRBOT_REPO_URL], cwd=repo, log=log)
        if rc != 0:
            # remote may already exist
            _run(["git", "remote", "set-url", "origin", ASTRBOT_REPO_URL], cwd=repo, log=log)
    # fetch single tag
    rc = _run(
        ["git", "fetch", "--depth", "1", "origin", f"refs/tags/{tag}:refs/tags/{tag}"],
        cwd=repo,
        log=log,
    )
    if rc != 0:
        # some repos use branch-style tags already checked; try branch fetch
        rc = _run(
            ["git", "fetch", "--depth", "1", "origin", f"+refs/heads/{tag}:refs/tags/{tag}"],
            cwd=repo,
            log=log,
        )
    if rc != 0:
        return rc
    return _run(["git", "checkout", "--force", tag], cwd=repo, log=log)


def _path_present(path: Path) -> bool:
    """True if path exists or is a broken symlink/junction."""
    try:
        return path.exists() or path.is_symlink()
    except OSError:
        return True


def _remove_path(path: Path, *, log: Callable[[str], None] | None = None) -> bool:
    """Best-effort remove file/dir/symlink/junction so activate can replace it.

    Windows often leaves a real directory (previous full clone). rmtree alone
    can soft-fail; rename-aside then delete is more reliable when files are
    briefly locked.
    """
    if not _path_present(path):
        return True

    # Symlink / junction / file first
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return not _path_present(path)
    except OSError as e:
        if log:
            log(f"warn: unlink {path} failed: {e}")

    # Empty dir / junction via rmdir
    try:
        path.rmdir()
        if not _path_present(path):
            return True
    except OSError:
        pass

    # Rename aside then delete (helps on Windows with residual handles)
    trash = path.with_name(f".{path.name}.trash-{os.getpid()}-{int(time.time())}")
    try:
        if _path_present(trash):
            shutil.rmtree(trash, ignore_errors=True)
            try:
                if trash.is_symlink() or trash.is_file():
                    trash.unlink()
            except OSError:
                pass
        path.rename(trash)
        shutil.rmtree(trash, ignore_errors=True)
        try:
            if trash.is_symlink() or trash.is_file():
                trash.unlink()
            elif trash.exists():
                trash.rmdir()
        except OSError:
            pass
    except OSError as e:
        if log:
            log(f"warn: rename-aside {path} failed: {e}")
        shutil.rmtree(path, ignore_errors=True)

    if _path_present(path):
        # last resort direct rmtree
        shutil.rmtree(path, ignore_errors=True)

    ok = not _path_present(path)
    if not ok and log:
        log(f"error: could not remove existing path: {path}")
    return ok


def _activate_cache(versioned: Path, active: Path, *, log: Callable[[str], None] | None = None) -> bool:
    """Make active AstrBot/ point at versioned tree (junction/symlink or copy replace)."""
    versioned = versioned.resolve()
    active_parent = active.parent
    active_parent.mkdir(parents=True, exist_ok=True)

    # If already the same path, done
    try:
        if active.exists() and active.resolve() == versioned:
            return True
    except OSError:
        pass

    # Must clear existing active before symlink/junction/copytree
    if _path_present(active):
        if not _remove_path(active, log=log):
            if log:
                log(
                    "activate blocked: cannot replace existing AstrBot/ "
                    "(close handles / delete manually, then re-run sync)"
                )
            return False

    # Prefer symlink / directory junction
    try:
        active.symlink_to(versioned, target_is_directory=True)
        if log:
            log(f"activated symlink {active} -> {versioned}")
        return True
    except OSError as e:
        if log:
            log(f"symlink unavailable: {e}")

    if os.name == "nt":
        # Directory junction does not require admin
        rc = _run(
            ["cmd", "/c", "mklink", "/J", str(active), str(versioned)],
            log=log,
        )
        if rc == 0 and active.exists():
            if log:
                log(f"activated junction {active} -> {versioned}")
            return True

    # Fallback: copy tree into active (heavier but portable)
    if log:
        log(f"fallback: copy tree {versioned} -> {active}")
    try:
        if _path_present(active) and not _remove_path(active, log=log):
            return False
        shutil.copytree(versioned, active)
        return True
    except OSError as e:
        if log:
            log(f"activate failed: {e}")
        return False


def ensure_version_cache(
    skill_root: Path,
    version: str,
    *,
    log: Callable[[str], None] | None = None,
) -> SyncResult:
    """Ensure versioned cache exists for exact version; pin active AstrBot/; write meta.

    Never clones untagged latest. Fails hard if tag cannot be resolved.
    """
    root = Path(skill_root)
    ver = normalize_version(version)
    if not ver:
        return SyncResult(
            ok=False,
            version=None,
            path=str(active_cache_path(root)),
            message=f"invalid version pin: {version!r}",
            rc=2,
        )

    tag_candidates = [f"v{ver}", ver]
    versioned = versioned_cache_path(root, ver)
    active = active_cache_path(root)

    have = False
    if versioned.is_dir() and versions_equal(_read_version_from_tree(versioned), ver):
        have = True
        if log:
            log(f"reuse versioned cache {versioned}")
    else:
        # try clone by tag
        cloned = False
        for t in tag_candidates:
            if log:
                log(f"clone pin tag={t}")
            rc = _clone_pinned(t, versioned, log=log)
            if rc == 0 and versioned.is_dir():
                cloned = True
                break
        if not cloned:
            # try fetch-tag into repo (for tags not valid as --branch)
            if versioned.exists():
                shutil.rmtree(versioned, ignore_errors=True)
            versioned.mkdir(parents=True, exist_ok=True)
            for t in tag_candidates:
                if log:
                    log(f"fetch pin tag={t}")
                rc = _fetch_tag_into_repo(versioned, t, log=log)
                if rc == 0:
                    cloned = True
                    break
        if not cloned:
            return SyncResult(
                ok=False,
                version=ver,
                path=str(versioned),
                message=(
                    f"failed to fetch AstrBot tag for {ver} "
                    f"(tried {tag_candidates}). Refusing untagged latest fallback."
                ),
                rc=1,
            )
        tree_ver = _read_version_from_tree(versioned)
        if tree_ver and not versions_equal(tree_ver, ver):
            return SyncResult(
                ok=False,
                version=tree_ver,
                path=str(versioned),
                message=(
                    f"pinned tree version {tree_ver} != requested {ver}; "
                    "refusing to activate"
                ),
                rc=3,
            )
        have = True

    if not have:
        return SyncResult(
            ok=False,
            version=ver,
            path=str(versioned),
            message="versioned cache missing after sync attempts",
            rc=1,
        )

    if not _activate_cache(versioned, active, log=log):
        return SyncResult(
            ok=False,
            version=ver,
            path=str(versioned),
            message="failed to activate local AstrBot/ cache",
            rc=1,
        )

    local = local_framework_info(root)
    meta = {
        "remote_version": ver,
        "local_version": local.get("version") or ver,
        "tag": f"v{ver}",
        "commit": local.get("git_head"),
        "git_describe": local.get("git_describe"),
        "active_path": str(active),
        "versioned_path": str(versioned),
        "repo": ASTRBOT_REPO_URL,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source": "framework sync",
    }
    write_meta(root, meta)
    final_v = local.get("version") or ver
    if not versions_equal(final_v, ver):
        return SyncResult(
            ok=False,
            version=final_v,
            path=str(active),
            message=f"after sync local={final_v} still != pin={ver}",
            meta=meta,
            rc=3,
        )
    return SyncResult(
        ok=True,
        version=final_v,
        path=str(active),
        message=f"synced local cache -> version={final_v} git={local.get('git_describe') or local.get('git_head')}",
        meta=meta,
        rc=0,
    )


def build_check_payload(
    *,
    local: dict[str, Any],
    remote_version: str | None,
    remote_raw: str | None = None,
    remote_probe: str | None = None,
) -> dict[str, Any]:
    local_v = local.get("version")
    status = alignment_status(local_v, remote_version)
    advice: list[str] = []
    if status == "match":
        advice.append("Local source cache matches remote; safe for API reference.")
    elif status == "mismatch":
        advice.append(
            f"Version skew: remote={normalize_version(remote_version)} "
            f"local={normalize_version(local_v)}. "
            "Do NOT invent APIs from local cache without aligning. "
            "Run: python scripts/ssh-exec.py framework sync --yes"
        )
        advice.append(
            "Prefer runtime verification (logs / astrbot-api / remote package) "
            "over assuming local AstrBot/ tree is authoritative."
        )
    elif status == "local_missing":
        advice.append(
            "No usable local cache version. "
            "Use: python scripts/ssh-exec.py framework sync --yes"
        )
    elif status == "remote_unknown":
        advice.append(
            "Could not determine remote version. Check unit ExecStart / uv tool python "
            "or set [paths].python_bin; treat local cache as untrusted."
        )
    else:
        advice.append(
            "Both local and remote versions unknown. Do not rely on local AstrBot/ APIs."
        )

    meta = local.get("meta") if isinstance(local.get("meta"), dict) else None
    return {
        "status": status,
        "remote": {
            "version": normalize_version(remote_version),
            "raw": remote_raw,
            "probe": remote_probe,
        },
        "local": {
            "version": normalize_version(local_v),
            "cache_path": local.get("cache_path"),
            "exists": local.get("exists"),
            "git_head": local.get("git_head"),
            "git_describe": local.get("git_describe"),
            "versioned_caches": local.get("versioned_caches") or [],
        },
        "meta": meta,
        "meta_fresh": meta_is_fresh(meta),
        "advice": advice,
    }


def exit_code_for_status(status: str) -> int:
    if status == "match":
        return 0
    if status == "mismatch":
        return 3
    return 2
