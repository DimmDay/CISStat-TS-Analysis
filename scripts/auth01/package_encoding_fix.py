#!/usr/bin/env python3
"""Package the locale fix over the already delivered AUTH-01 ZIP."""
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT.parent / "upload"
CHANGED = {
    ".github/workflows/auth01.yml", "scripts/local_gates.py",
    "tests/unit/test_auth01_registry.py", "worklog/worklog11.md",
}
NEW = {
    "scripts/auth01/windows_locale_check.py", "docs/auth01/encoding_fix.md",
    "scripts/auth01/package_encoding_fix.py", "scripts/auth01/encoding-fix-files.txt",
}


def main():
    subprocess.run([sys.executable, "scripts/auth01/generate.py", "--check"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/auth00/inventory.py", "--check"], cwd=ROOT, check=True)
    files = CHANGED | NEW | {p.relative_to(ROOT).as_posix() for p in (ROOT/"scripts/auth01/encoding-fix-protocols").glob("*") if p.is_file()}
    # The original delivery is a reference, never overwritten by this hotfix.
    with ZipFile(OUTPUT/"cisstat-auth01-dfe1941.zip") as previous:
        changed = {name for name in previous.namelist() if previous.read(name) != (ROOT/name).read_bytes()}
        if changed != CHANGED:
            raise ValueError("Unexpected changes since AUTH-01 delivery: " + repr(changed ^ CHANGED))
    names = "\n".join(sorted(files)) + "\n"
    (ROOT/"scripts/auth01/encoding-fix-files.txt").write_text(names, encoding="utf-8", newline="\n")
    target = OUTPUT/"cisstat-auth01-encoding-fix.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT/name, name)
    with ZipFile(target) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != files:
            raise ValueError("ZIP CRC/inventory mismatch")
        for name in files:
            if archive.read(name) != (ROOT/name).read_bytes():
                raise ValueError("ZIP bytes mismatch: " + name)
    shutil.copyfile(ROOT/"worklog/worklog11.md", OUTPUT/"worklog11-auth01-encoding-fix.md")
    (OUTPUT/"auth01-encoding-fix-files.txt").write_text(names, encoding="utf-8", newline="\n")
    print(f"ZIP verified: {target}; {len(files)} files; {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
