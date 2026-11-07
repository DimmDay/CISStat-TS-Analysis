#!/usr/bin/env python3
"""Task-only overlay ZIP; exact changed/untracked set, CRC and byte checks."""

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "c2217ec5ba38116e9da6413dc2c56794aefb89b5"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE]:
        raise ValueError("Delivery must be based on the reviewed commit")
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("Deletions need a separate explicit delivery contract")
    paths = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | set(git("ls-files", "--others", "--exclude-standard"))
        | {"scripts/auth09/files.txt"}
    )
    allowed_new = {
        ".github/workflows/auth09.yml",
        "apps/api/ownership.py",
        "apps/api/accounts/ownership_migration.py",
        "apps/api/migrations/0023_auth09_account_ownership.sql",
        "packages/ui/lib/researchOwnership.ts",
        "packages/ui/lib/researchOwnership.test.ts",
        "tests/unit/test_auth09_ownership.py",
        "tests/integration/test_auth09_objects.py",
        "tests/api/test_auth09_visual_export.py",
    }
    unexpected = [
        p
        for p in git("ls-files", "--others", "--exclude-standard")
        if p not in allowed_new
        and not p.startswith(("scripts/auth09/", "docs/auth09/"))
    ]
    if unexpected:
        raise ValueError(
            "Remove generated/unrelated artifacts before task-only delivery: "
            + str(unexpected[:8])
        )
    manifest = ROOT / "scripts/auth09/files.txt"
    manifest.write_text("\n".join(paths) + "\n", encoding="utf-8", newline="\n")
    if any(
        not (ROOT / p).is_file() or Path(p).is_absolute() or ".." in Path(p).parts
        for p in paths
    ):
        raise ValueError("Only existing repository-relative files may be packaged")
    target = ROOT.parent / "download"
    target.mkdir(exist_ok=True)
    archive = target / "cisstat-auth09-c2217ec.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in paths:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        if z.testzip() is not None or z.namelist() != paths:
            raise ValueError("ZIP CRC/inventory mismatch")
        for name in paths:
            if z.read(name) != (ROOT / name).read_bytes():
                raise ValueError("ZIP bytes changed during packaging")
    (target / "auth09-files.txt").write_bytes(manifest.read_bytes())
    (target / "worklog11-auth09.md").write_bytes(
        (ROOT / "worklog/worklog11.md").read_bytes()
    )
    print(
        json.dumps(
            {
                "archive": str(archive),
                "files": len(paths),
                "bytes": archive.stat().st_size,
                "crc_and_bytes": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
