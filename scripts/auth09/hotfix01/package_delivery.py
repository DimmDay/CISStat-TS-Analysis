#!/usr/bin/env python3
"""Exact overlay delta on the delivered AUTH-09 ZIP; never commit/push."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[3]
BASE = "c2217ec5ba38116e9da6413dc2c56794aefb89b5"
BASE_ZIP_SHA256 = "16afa81fe202ddfb4d7d6dd110951e91657c7524b58771bba79b6eef5979b20e"
CANDIDATES = [
    ".github/workflows/auth00.yml",
    "scripts/auth00/check_committed.py",
    "scripts/local_gates.py",
    "scripts/local_gates.md",
    "tests/unit/test_auth00_precommit.py",
    "docs/auth00/policy_review.json",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    "docs/auth09/design.md",
    "docs/auth09/hotfix01.md",
    "worklog/worklog11.md",
]


def main():
    download = ROOT.parent / "download"
    download.mkdir(exist_ok=True)
    original = download / "cisstat-auth09-c2217ec.zip"
    if hashlib.sha256(original.read_bytes()).hexdigest() != BASE_ZIP_SHA256:
        raise ValueError("Original delivered ZIP identity mismatch")
    candidates = sorted(
        set(CANDIDATES)
        | {
            p.relative_to(ROOT).as_posix()
            for p in (ROOT / "scripts/auth09/hotfix01").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        | {"scripts/auth09/hotfix01/files.txt"}
    )
    paths = []
    with ZipFile(original) as base:
        for name in candidates:
            path = ROOT / name
            if name == "scripts/auth09/hotfix01/files.txt":
                paths.append(name)
                continue
            current = path.read_bytes()
            if name in base.namelist():
                old = base.read(name)
            else:
                result = subprocess.run(
                    ["git", "show", BASE + ":" + name],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                )
                old = result.stdout if result.returncode == 0 else None
            if old != current:
                paths.append(name)
    manifest = ROOT / "scripts/auth09/hotfix01/files.txt"
    manifest.write_text("\n".join(paths) + "\n", encoding="utf-8", newline="\n")
    target = download / "cisstat-auth09-hotfix01.zip"
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in paths:
            z.write(ROOT / name, name)
    with ZipFile(target) as z:
        assert z.testzip() is None and z.namelist() == paths
        assert all(z.read(name) == (ROOT / name).read_bytes() for name in paths)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n")
    (download / "auth09-hotfix01-files.txt").write_bytes(manifest.read_bytes())
    (download / "worklog11-auth09-hotfix01.md").write_bytes(
        (ROOT / "worklog/worklog11.md").read_bytes()
    )
    print(
        json.dumps(
            {
                "archive": str(target),
                "files": len(paths),
                "bytes": target.stat().st_size,
                "sha256": digest,
                "base_zip_sha256": BASE_ZIP_SHA256,
                "crc_and_bytes": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
