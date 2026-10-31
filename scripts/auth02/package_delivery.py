#!/usr/bin/env python3
"""Package exactly this task's files with byte/CRC verification. No commit/push."""
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT.parent / "upload"
FILES = {
    ".github/workflows/auth02.yml",
    "apps/api/migrations/0019_auth02_identity_accounts.sql",
    "docs/auth02/design.md",
    "docs/auth00/policy_review.json", "docs/auth00/inventory.json",
    "docs/auth00/inventory.md", "docs/auth00/operation_variants.md",
    "scripts/auth00/inventory.py", "scripts/local_gates.py",
    "tests/unit/test_auth00_inventory.py", "tests/unit/test_auth02_storage.py",
    "tests/integration/test_auth02_postgres.py", "worklog/worklog11.md",
    "scripts/auth02/files.txt",
}


def main():
    for script in ("scripts/auth01/generate.py", "scripts/auth00/inventory.py"):
        subprocess.run([sys.executable, script, "--check"], cwd=ROOT, check=True)
    files = FILES.copy()
    for directory in ("apps/api/authentication", "apps/api/accounts"):
        files |= {p.relative_to(ROOT).as_posix() for p in (ROOT/directory).glob("*.py")}
    for directory in ("scripts/auth02", "scripts/auth02/protocols"):
        files |= {p.relative_to(ROOT).as_posix() for p in (ROOT/directory).glob("*") if p.is_file()}
    names = "\n".join(sorted(files)) + "\n"
    (ROOT/"scripts/auth02/files.txt").write_text(names, encoding="utf-8", newline="\n")
    changed = set(subprocess.check_output(["git", "diff", "--name-only", "-z"], cwd=ROOT).decode().strip("\0").split("\0"))
    changed |= set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().strip("\0").split("\0"))
    changed.discard("")
    if changed != files:
        raise ValueError("ZIP inventory differs from git changes: " + repr(sorted(changed ^ files)))
    OUTPUT.mkdir(exist_ok=True)
    target = OUTPUT/"cisstat-auth02-649027e.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT/name, name)
    with ZipFile(target) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != files:
            raise ValueError("ZIP CRC/inventory mismatch")
        for name in files:
            if archive.read(name) != (ROOT/name).read_bytes():
                raise ValueError("ZIP bytes mismatch: " + name)
    shutil.copyfile(ROOT/"worklog/worklog11.md", OUTPUT/"worklog11-auth02.md")
    (OUTPUT/"auth02-files.txt").write_text(names, encoding="utf-8", newline="\n")
    print(f"ZIP verified: {target}; {len(files)} files; {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
