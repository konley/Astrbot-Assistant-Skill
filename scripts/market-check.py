#!/usr/bin/env python3
"""Validate an AstrBot plugin or plugin-market JSON source."""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

REPO_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+(?:\.git|/tree/[A-Za-z0-9_-]+)?$")


def check_plugin(path: Path) -> list[str]:
    issues: list[str] = []
    metadata = path / "metadata.yaml"
    if not metadata.is_file():
        metadata = path / "metadata.yml"
    if not metadata.is_file():
        return ["metadata.yaml or metadata.yml is missing"]
    try:
        import yaml

        data = yaml.safe_load(metadata.read_text(encoding="utf-8-sig")) or {}
    except ImportError:
        issues.append("PyYAML is unavailable; metadata was not parsed")
        data = {}
    except Exception as exc:
        return [f"metadata parse failed: {exc}"]
    for key in ("name", "author", "version", "repo", "desc"):
        if not data.get(key):
            issues.append(f"metadata.{key} is missing")
    if data.get("repo") and not REPO_RE.match(str(data["repo"]).rstrip("/")):
        issues.append("metadata.repo must be an HTTPS GitHub repository URL")
    if data.get("tags") is not None and not isinstance(data["tags"], list):
        issues.append("metadata.tags must be a list")
    if data.get("support_platforms") is not None and not isinstance(data["support_platforms"], list):
        issues.append("metadata.support_platforms must be a list")
    return issues


def check_market(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return [f"market JSON parse failed: {exc}"]
    if not isinstance(payload, dict) or not isinstance(payload.get("$meta"), dict):
        return ["market root must contain an object $meta"]
    if payload["$meta"].get("schema_version") != 1:
        issues.append("$meta.schema_version must be 1")
    seen: set[str] = set()
    for key, record in payload.items():
        if key == "$meta":
            continue
        if not isinstance(record, dict):
            issues.append(f"{key}: record must be an object")
            continue
        for field in ("author", "name", "version", "repo", "desc"):
            if not record.get(field):
                issues.append(f"{key}: {field} is missing")
        plugin_id = f"{record.get('author', '').strip()}/{record.get('name', '').strip()}"
        if key not in (plugin_id, record.get("name")):
            issues.append(f"{key}: key must equal {plugin_id}")
        normalized = plugin_id.lower()
        if normalized in seen:
            issues.append(f"duplicate plugin_id: {plugin_id}")
        seen.add(normalized)
        if record.get("repo") and not REPO_RE.match(str(record["repo"]).rstrip("/")):
            issues.append(f"{key}: repo is not a GitHub HTTPS repository URL")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AstrBot plugin marketplace metadata")
    parser.add_argument("path", type=Path)
    parser.add_argument("--market", action="store_true", help="validate market JSON instead of a plugin")
    parser.add_argument("--zip", dest="zip_path", type=Path, help="also check a package zip is <= 16MB")
    args = parser.parse_args()
    issues = check_market(args.path) if args.market else check_plugin(args.path)
    if args.zip_path:
        if not args.zip_path.is_file():
            issues.append("zip package is missing")
        elif args.zip_path.stat().st_size > 16 * 1024 * 1024:
            issues.append("zip package exceeds the 16MB marketplace limit")
        else:
            with zipfile.ZipFile(args.zip_path) as archive:
                bad = [n for n in archive.namelist() if ".git/" in n or "__pycache__/" in n or "node_modules/" in n]
                if bad:
                    issues.append(f"zip contains development files: {bad[:3]}")
    for issue in issues:
        print(f"FAIL: {issue}")
    if not issues:
        print("PASS")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
