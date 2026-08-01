#!/usr/bin/env python3
"""Create and inspect a local AstrBot data backup."""
from __future__ import annotations

import argparse
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an AstrBot data backup")
    parser.add_argument("root", type=Path, help="AstrBot root directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--yes", action="store_true", help="required for backup creation")
    args = parser.parse_args()
    if not args.yes:
        parser.error("backup creation requires --yes")
    data = args.root / "data"
    if not data.is_dir():
        parser.error(f"data directory not found: {data}")
    include = ["cmd_config.json", "config", "plugins", "plugin_data", "skills", "workspaces", "knowledge_base"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w:gz") as archive:
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root": str(args.root.resolve()),
            "included": [name for name in include if (data / name).exists()],
            "note": "Secrets may be present; keep this archive private.",
        }
        manifest_path = data / ".astrbot-backup-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        try:
            for name in include:
                target = data / name
                if target.exists():
                    archive.add(target, arcname=f"data/{name}")
            archive.add(manifest_path, arcname="data/.astrbot-backup-manifest.json")
        finally:
            manifest_path.unlink(missing_ok=True)
    print(f"backup={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
