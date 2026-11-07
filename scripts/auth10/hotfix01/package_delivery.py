#!/usr/bin/env python3
"""Strict byte delta over immutable AUTH-10 ZIP; no application changes allowed."""

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[3]
BASE = "c13a52bd754f753d9a842aa84af8548af3019fed"
PREFIX = "scripts/auth10/hotfix01/"
ALLOWED = {
    "scripts/local_gates.py",
    "scripts/local_gates.md",
    "docs/auth00/inventory.json",
    "docs/auth00/policy_review.json",
    "docs/auth10/hotfix01.md",
    "tests/unit/test_auth00_local_output.py",
    "worklog/worklog11.md",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    if git("rev-parse", "HEAD").decode().strip() != BASE:
        raise ValueError("Unexpected delivery base")
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("Deletion is not part of this overlay")
    target = ROOT.parent / "download"
    original = target / "cisstat-auth10-c13a52b.zip"
    manifest = ROOT / PREFIX / "files.txt"
    candidates = set(git("diff", "--name-only", "HEAD").decode().splitlines())
    candidates.update(
        git("ls-files", "--others", "--exclude-standard").decode().splitlines()
    )
    candidates.add(PREFIX + "files.txt")
    changed = []
    with ZipFile(original) as source:
        if source.testzip() is not None or len(source.namelist()) != 61:
            raise ValueError("Original AUTH-10 ZIP differs from reviewed delivery")
        originals = set(source.namelist())
        for name in sorted(candidates):
            if name == PREFIX + "files.txt":
                changed.append(name)
                continue
            path = ROOT / name
            if not path.is_file():
                raise ValueError("Missing candidate: " + name)
            before = (
                source.read(name)
                if name in originals
                else subprocess.run(
                    ["git", "show", "HEAD:" + name],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                ).stdout
            )
            if path.read_bytes() != before:
                changed.append(name)
    unexpected = [p for p in changed if p not in ALLOWED and not p.startswith(PREFIX)]
    if unexpected:
        raise ValueError("Unrelated delta must not be packaged: " + str(unexpected[:8]))
    if any(Path(p).is_absolute() or ".." in Path(p).parts for p in changed):
        raise ValueError("Unsafe path")
    manifest.write_text("\n".join(changed) + "\n", encoding="utf-8", newline="\n")
    archive = target / "cisstat-auth10-hotfix01.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in changed:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        if z.testzip() is not None or z.namelist() != changed:
            raise ValueError("ZIP CRC/manifest mismatch")
        for name in changed:
            if z.read(name) != (ROOT / name).read_bytes():
                raise ValueError("ZIP byte mismatch: " + name)
    (target / "auth10-hotfix01-files.txt").write_bytes(manifest.read_bytes())
    (target / "worklog11-auth10-hotfix01.md").write_bytes(
        (ROOT / "worklog/worklog11.md").read_bytes()
    )
    print(
        json.dumps(
            {
                "zip": str(archive),
                "files": len(changed),
                "bytes": archive.stat().st_size,
                "crc_and_bytes": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
