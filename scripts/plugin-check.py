#!/usr/bin/env python3
"""
AstrBot Skill - Plugin compliance checker + version field helper.

Usage:
    python plugin-check.py <plugin_dir>
    python plugin-check.py <plugin_dir> --profile personal
    python plugin-check.py <plugin_dir> --suggest-version patch|minor|major
    python plugin-check.py <plugin-dir> --apply-version 0.1.2
    python plugin-check.py <plugin_dir> --json

Exit codes:
    0 = all required checks passed (warnings allowed)
    1 = one or more FAIL
    2 = usage / path error
"""
from __future__ import annotations

import argparse
import json
import py_compile
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import SshConfigError, load_credentials  # noqa: E402

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


REQUIRED_META = ("name", "desc", "version", "author")
LOGO_NAMES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp")
ADAPTER_KEYS = {
    "aiocqhttp", "qq_official", "telegram", "wecom", "lark", "dingtalk",
    "discord", "slack", "kook", "vocechat", "weixin_official_account",
    "satori", "misskey", "line",
}


@dataclass
class Issue:
    level: str  # FAIL | WARN | INFO
    code: str
    message: str


@dataclass
class Report:
    plugin_dir: str
    ok: bool = True
    issues: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    suggested_version: str = ""
    logo: str | None = None
    expected_repo: str = ""
    expected_author: str = ""

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(Issue(level, code, message))
        if level == "FAIL":
            self.ok = False


def _has_bom(path: Path) -> bool:
    data = path.read_bytes()[:3]
    return data == b"\xef\xbb\xbf"


def _parse_metadata(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("metadata.yaml root must be mapping")
        return {str(k): v for k, v in data.items()}
    # minimal fallback parser for flat key: value
    out: dict = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        k, v = s.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _bump(version: str, kind: str) -> str:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(.*)$", (version or "0.1.0").strip())
    if not m:
        return "0.1.1" if kind == "patch" else ("0.2.0" if kind == "minor" else "1.0.0")
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    suffix = m.group(4) or ""
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif kind == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}{suffix}"


def _write_version(meta_path: Path, main_path: Path | None, new_ver: str) -> None:
    text = meta_path.read_text(encoding="utf-8-sig")
    if re.search(r"(?m)^version\s*:", text):
        text2 = re.sub(r"(?m)^version\s*:.*$", f"version: {new_ver}", text, count=1)
    else:
        text2 = text.rstrip() + f"\nversion: {new_ver}\n"
    meta_path.write_text(text2, encoding="utf-8", newline="\n")
    if main_path and main_path.is_file():
        mt = main_path.read_text(encoding="utf-8-sig")
        mt2 = re.sub(
            r'version\s*=\s*["\'][^"\']+["\']',
            f'version="{new_ver}"',
            mt,
            count=1,
        )
        if mt2 != mt:
            main_path.write_text(mt2, encoding="utf-8", newline="\n")



_LOGGER_IMPORT_RE = re.compile(
    r"(?:from\s+astrbot\.api\s+import\s+[^\n]*\blogger\b|"
    r"from\s+astrbot\.api\.logger\s+import\s+|"
    r"import\s+astrbot\.api\.logger\b|"
    r"from\s+astrbot\s+import\s+[^\n]*\blogger\b)"
)
_LOGGER_CALL_RE = re.compile(
    r"\blogger\.(?:debug|info|warning|warn|error|exception|critical)\s*\("
)
_PRINT_RE = re.compile(r"(?<![\w.])print\s*\(")


def _iter_plugin_py_files(plugin_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in plugin_dir.rglob("*.py"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        # tests are allowed to use print / skip logger
        if "tests" in path.parts:
            continue
        files.append(path)
    return files


def _line_is_comment_or_doc_noise(line: str) -> bool:
    s = line.strip()
    return (not s) or s.startswith("#")


def _check_logging(plugin_dir: Path, rep: Report) -> None:
    """Require ops-visible logger usage; warn on bare print() in plugin code."""
    py_files = _iter_plugin_py_files(plugin_dir)
    if not py_files:
        return

    has_import = False
    has_call = False
    print_hits: list[str] = []

    for path in py_files:
        try:
            src = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            rep.add("WARN", "logger.read", f"cannot read {path.relative_to(plugin_dir)}: {e}")
            continue

        if _LOGGER_IMPORT_RE.search(src):
            has_import = True
        if _LOGGER_CALL_RE.search(src):
            has_call = True

        rel = str(path.relative_to(plugin_dir)).replace("\\", "/")
        for lineno, line in enumerate(src.splitlines(), 1):
            if _line_is_comment_or_doc_noise(line):
                continue
            if _PRINT_RE.search(line):
                print_hits.append(f"{rel}:{lineno}")

    if not has_import:
        rep.add(
            "WARN",
            "logger.missing",
            "no `from astrbot.api import logger` in plugin code - "
            "runtime signals must go through astrbot logger for `log --profile plugin`",
        )
    elif not has_call:
        rep.add(
            "WARN",
            "logger.unused",
            "logger imported but no logger.info/error/exception calls found "
            "(log lifecycle + command/handler entry + failures)",
        )
    else:
        rep.add("INFO", "logger.ok", "astrbot.api logger import + calls present")

    if print_hits:
        sample = ", ".join(print_hits[:5])
        extra = f" (+{len(print_hits) - 5} more)" if len(print_hits) > 5 else ""
        rep.add(
            "WARN",
            "logger.print",
            f"found print() in plugin code: {sample}{extra}; "
            "prefer logger.* so remote journal queries work",
        )


def check_plugin(
    plugin_dir: Path,
    *,
    profile: str | None = None,
    login_config: str | None = None,
    suggest: str | None = None,
) -> Report:
    plugin_dir = plugin_dir.resolve()
    rep = Report(plugin_dir=str(plugin_dir))

    if not plugin_dir.is_dir():
        rep.add("FAIL", "path", f"not a directory: {plugin_dir}")
        return rep

    # credentials optional
    author_expect = ""
    github_root = ""
    try:
        creds = load_credentials(explicit_path=login_config, quiet=True, auto_template=False)
        p = creds.profile(profile)
        author_expect = p.user
        github_root = (p.github or "").rstrip("/")
        rep.expected_author = author_expect
    except SshConfigError:
        rep.add("WARN", "login", "login.config not found — skip author/repo identity checks")

    meta_path = plugin_dir / "metadata.yaml"
    if not meta_path.is_file():
        rep.add("FAIL", "metadata.missing", "metadata.yaml missing")
        return rep

    if _has_bom(meta_path):
        rep.add("FAIL", "bom.metadata", "metadata.yaml has UTF-8 BOM")

    try:
        meta = _parse_metadata(meta_path)
    except Exception as e:
        rep.add("FAIL", "metadata.parse", f"cannot parse metadata.yaml: {e}")
        return rep
    rep.metadata = {k: (v if not isinstance(v, (dict, list)) else str(v)) for k, v in meta.items()}

    for key in REQUIRED_META:
        if key not in meta or meta[key] in (None, ""):
            rep.add("FAIL", f"metadata.{key}", f"required field missing: {key}")

    name = str(meta.get("name") or "")
    folder = plugin_dir.name
    if name and name != folder:
        rep.add(
            "WARN",
            "name.mismatch",
            f"metadata.name={name!r} != directory name={folder!r}",
        )
    if name and not name.startswith("astrbot_plugin_") and not name.startswith("astrbot_"):
        rep.add(
            "WARN",
            "name.prefix",
            f"name {name!r} usually starts with astrbot_plugin_",
        )

    author = str(meta.get("author") or "")
    if author_expect and author and author != author_expect:
        rep.add(
            "WARN",
            "author.mismatch",
            f"author={author!r} != login.config profile user={author_expect!r} "
            f"(confirm intentional)",
        )
    elif author_expect and not author:
        rep.add("FAIL", "author.empty", "author empty")

    repo = str(meta.get("repo") or "").rstrip("/")
    if github_root and name:
        expected_repo = f"{github_root}/{name}"
        rep.expected_repo = expected_repo
        if not repo:
            rep.add(
                "WARN",
                "repo.missing",
                f"repo empty; suggested: {expected_repo} (ask user: new/fork/skip)",
            )
        elif repo != expected_repo and not repo.startswith(github_root + "/"):
            rep.add(
                "WARN",
                "repo.mismatch",
                f"repo={repo!r} does not match profile github root {github_root!r}",
            )
        elif repo != expected_repo:
            rep.add(
                "INFO",
                "repo.custom",
                f"repo={repo!r} (expected default {expected_repo!r})",
            )

    # Recommended metadata (WARN only — do not FAIL old plugins yet)
    if not meta.get("display_name"):
        rep.add(
            "WARN",
            "metadata.display_name",
            "display_name missing (recommended for WebUI; scaffold writes it by default)",
        )
    av = meta.get("astrbot_version")
    if av in (None, ""):
        rep.add(
            "WARN",
            "metadata.astrbot_version",
            'astrbot_version missing (recommended e.g. ">=4.16,<5"; keep WARN until ecosystem migrates)',
        )
    else:
        av_s = str(av).strip()
        if av_s and not any(ch in av_s for ch in "<>="):
            rep.add(
                "WARN",
                "metadata.astrbot_version.format",
                "astrbot_version=%r should be a PEP 440 specifier (e.g. \">=4.16,<5\")" % (av_s,),
            )

    platforms = meta.get("support_platforms")
    if platforms is not None:
        if isinstance(platforms, str):
            plats = [x.strip() for x in platforms.split(",") if x.strip()]
        elif isinstance(platforms, list):
            plats = [str(x) for x in platforms]
        else:
            plats = []
        bad = [x for x in plats if x not in ADAPTER_KEYS]
        if bad:
            rep.add("FAIL", "platforms", f"unknown support_platforms keys: {bad}")

    # logo
    logo = None
    for n in LOGO_NAMES:
        if (plugin_dir / n).is_file():
            logo = n
            break
    rep.logo = logo
    if not logo:
        rep.add(
            "WARN",
            "logo.missing",
            "no logo.png/jpg — ask user: provide image / skip / later "
            "(logo-process.py)",
        )
    else:
        rep.add("INFO", "logo.ok", f"found {logo}")

    # main.py register consistency
    main_py = plugin_dir / "main.py"
    if not main_py.is_file():
        # sometimes nested
        cands = list(plugin_dir.glob("**/main.py"))
        main_py = cands[0] if cands else main_py
    if main_py.is_file():
        if _has_bom(main_py):
            rep.add("FAIL", "bom.main", f"{main_py.name} has UTF-8 BOM")
        try:
            py_compile.compile(str(main_py), doraise=True)
        except py_compile.PyCompileError as e:
            rep.add("FAIL", "syntax.main", str(e))
        src = main_py.read_text(encoding="utf-8-sig", errors="replace")
        # @register("name", "author", "desc", version="x"
        m = re.search(
            r'@register\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']*)["\']'
            r'(?:[^)]*version\s*=\s*["\']([^"\']+)["\'])?',
            src,
        )
        if m:
            r_name, r_author, r_desc, r_ver = m.group(1), m.group(2), m.group(3), m.group(4)
            if name and r_name != name:
                rep.add(
                    "FAIL",
                    "register.name",
                    f"@register name={r_name!r} != metadata.name={name!r}",
                )
            if author and r_author != author:
                rep.add(
                    "WARN",
                    "register.author",
                    f"@register author={r_author!r} != metadata.author={author!r}",
                )
            ver = str(meta.get("version") or "")
            if r_ver and ver and r_ver != ver:
                rep.add(
                    "WARN",
                    "register.version",
                    f"@register version={r_ver!r} != metadata.version={ver!r}",
                )
        else:
            rep.add("WARN", "register.missing", "could not find @register(...) in main.py")
    else:
        rep.add("WARN", "main.missing", "main.py not found")

    # BOM sweep
    for path in plugin_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".py", ".json", ".yaml", ".yml"}:
            continue
        if path.name.startswith("."):
            continue
        if "__pycache__" in path.parts:
            continue
        if _has_bom(path):
            rep.add("FAIL", "bom", f"UTF-8 BOM: {path.relative_to(plugin_dir)}")

    # JSON parse
    for path in plugin_dir.rglob("*.json"):
        if "__pycache__" in path.parts:
            continue
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            rep.add("FAIL", "json", f"{path.relative_to(plugin_dir)}: {e}")

    # tests
    tests_dir = plugin_dir / "tests"
    if not tests_dir.is_dir():
        rep.add("WARN", "tests.missing", "tests/ directory missing")
    else:
        if not list(tests_dir.glob("test_*.py")):
            rep.add("WARN", "tests.empty", "no test_*.py under tests/")

    # requirements
    if not (plugin_dir / "requirements.txt").is_file():
        rep.add("INFO", "reqs.missing", "requirements.txt missing (ok if no deps)")

    # observability / logging contract
    _check_logging(plugin_dir, rep)

    # version suggestion
    cur = str(meta.get("version") or "0.1.0")
    if suggest in ("patch", "minor", "major"):
        rep.suggested_version = _bump(cur, suggest)
        rep.add(
            "INFO",
            "version.suggest",
            f"current={cur} suggest({suggest})={rep.suggested_version}",
        )
    else:
        # default info for finish gate
        rep.suggested_version = _bump(cur, "patch")
        rep.add(
            "INFO",
            "version.hint",
            f"if this change is a fix, consider version {rep.suggested_version}; "
            f"feature→{_bump(cur,'minor')}; breaking→{_bump(cur,'major')}",
        )

    return rep


def print_report(rep: Report, as_json: bool) -> int:
    if as_json:
        payload = {
            "plugin_dir": rep.plugin_dir,
            "ok": rep.ok,
            "metadata": rep.metadata,
            "logo": rep.logo,
            "expected_author": rep.expected_author,
            "expected_repo": rep.expected_repo,
            "suggested_version": rep.suggested_version,
            "issues": [asdict(i) for i in rep.issues],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if rep.ok else 1

    print(f"plugin: {rep.plugin_dir}")
    print(f"result: {'PASS' if rep.ok else 'FAIL'}")
    if rep.metadata:
        print(
            "metadata: "
            f"name={rep.metadata.get('name')!r} version={rep.metadata.get('version')!r} "
            f"author={rep.metadata.get('author')!r} repo={rep.metadata.get('repo')!r}"
        )
    if rep.expected_author:
        print(f"expected_author(profile): {rep.expected_author}")
    if rep.expected_repo:
        print(f"expected_repo: {rep.expected_repo}")
    print(f"logo: {rep.logo or '(none)'}")
    if rep.suggested_version:
        print(f"suggested_version: {rep.suggested_version}")
    print("issues:")
    if not rep.issues:
        print("  (none)")
    for i in rep.issues:
        print(f"  [{i.level}] {i.code}: {i.message}")
    return 0 if rep.ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description="AstrBot plugin compliance checker")
    p.add_argument("plugin_dir", type=Path)
    p.add_argument("--login-config")
    p.add_argument("--profile", help="git profile name from login.config")
    p.add_argument(
        "--suggest-version",
        choices=["patch", "minor", "major"],
        help="print suggested bump from current metadata.version",
    )
    p.add_argument(
        "--apply-version",
        metavar="VER",
        help="write version into metadata.yaml and main.py @register",
    )
    p.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        help="bump and apply version (implies write)",
    )
    p.add_argument("--json", action="store_true", dest="as_json")
    args = p.parse_args()

    rep = check_plugin(
        args.plugin_dir,
        profile=args.profile,
        login_config=args.login_config,
        suggest=args.suggest_version or args.bump,
    )

    apply_ver = args.apply_version
    if args.bump:
        apply_ver = rep.suggested_version or _bump(
            str(rep.metadata.get("version") or "0.1.0"), args.bump
        )

    if apply_ver:
        meta_path = Path(rep.plugin_dir) / "metadata.yaml"
        main_path = Path(rep.plugin_dir) / "main.py"
        if not main_path.is_file():
            cands = list(Path(rep.plugin_dir).glob("**/main.py"))
            main_path = cands[0] if cands else main_path
        if not meta_path.is_file():
            print("cannot apply version: metadata.yaml missing", file=sys.stderr)
            return 2
        _write_version(meta_path, main_path if main_path.is_file() else None, apply_ver)
        print(f"applied version: {apply_ver}")
        # re-check
        rep = check_plugin(
            args.plugin_dir,
            profile=args.profile,
            login_config=args.login_config,
            suggest=None,
        )

    return print_report(rep, args.as_json)


if __name__ == "__main__":
    _configure_stdio()
    sys.exit(main())
