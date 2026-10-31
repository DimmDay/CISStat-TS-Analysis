#!/usr/bin/env python3
"""Deliver only this task's reviewed changed files; no git commit/push."""
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT.parent / "upload"
FILES = {
    ".github/workflows/auth01.yml",
    "apps/api/access_registry.py", "apps/api/access_registry.v1.json",
    "apps/api/main.py", "apps/api/plans.py", "apps/api/requirements.txt",
    "docs/auth00/policy_review.json", "docs/auth00/inventory.json",
    "docs/auth00/inventory.md", "docs/auth00/operation_variants.md",
    "docs/auth01/design.md", "docs/auth01/openapi.json",
    "packages/ui/lib/access-contract.generated.ts", "packages/ui/lib/plans.ts",
    "packages/ui/lib/plans.auth01.test.ts", "scripts/local_gates.py",
    "scripts/auth01/generate.py", "scripts/auth01/requirements.txt",
    "scripts/auth01/package_delivery.py", "scripts/auth01/files.txt",
    "tests/unit/test_auth01_registry.py", "worklog/worklog11.md",
}


def main():
    for script in ("scripts/auth01/generate.py", "scripts/auth00/inventory.py"):
        subprocess.run([sys.executable, script, "--check"], cwd=ROOT, check=True)
    files = FILES | {p.relative_to(ROOT).as_posix() for p in (ROOT/"scripts/auth01/protocols").glob("*") if p.is_file()}
    names = "\n".join(sorted(files)) + "\n"
    (ROOT/"scripts/auth01/files.txt").write_text(names, encoding="utf-8", newline="\n")
    changed = set(subprocess.check_output(["git", "diff", "--name-only", "-z"], cwd=ROOT).decode().strip("\0").split("\0"))
    changed |= set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().strip("\0").split("\0"))
    changed.discard("")
    if files != changed:
        raise ValueError("Delivery files differ from git changed set: " + repr(sorted(files ^ changed)))
    OUTPUT.mkdir(exist_ok=True)
    target = OUTPUT/"cisstat-auth01-dfe1941.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT/name, name)
    with ZipFile(target) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != files:
            raise ValueError("ZIP CRC/file inventory mismatch")
        for name in files:
            if archive.read(name) != (ROOT/name).read_bytes():
                raise ValueError("ZIP content mismatch: " + name)
    shutil.copyfile(ROOT/"worklog/worklog11.md", OUTPUT/"worklog11-auth01.md")
    (OUTPUT/"auth01-files.txt").write_text(names, encoding="utf-8", newline="\n")
    print(f"ZIP verified: {target}; {len(files)} files; {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
