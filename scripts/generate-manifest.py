#!/usr/bin/env python3
"""Generate or verify the source scaffold's SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "eval-runs",
}
IGNORED_FILES = {
    ".env",
    ".env.phoenix",
    "SCAFFOLD_MANIFEST.json",
}


def included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in IGNORED_PARTS for part in relative.parts):
        return False
    if path.name in IGNORED_FILES or path.name.startswith(".env.bak-"):
        return False
    return path.is_file() and path.suffix != ".pyc"


def build_manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not included(path, root):
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {"schema_version": 1, "project": "serveshed", "files": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    target = root / "SCAFFOLD_MANIFEST.json"
    expected = build_manifest(root)
    if args.check:
        if not target.is_file():
            raise SystemExit(f"Missing {target}")
        actual = json.loads(target.read_text(encoding="utf-8"))
        if actual != expected:
            raise SystemExit("SCAFFOLD_MANIFEST.json is stale; regenerate it")
        print(f"PASS {len(expected['files'])} files match SCAFFOLD_MANIFEST.json")
        return 0
    target.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {target} with {len(expected['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
