#!/usr/bin/env python3
"""Package exactly AUTH-03 changes; verify inventory, CRC and every byte."""

from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT.parent / "upload"
FILES = {
    ".github/workflows/auth03.yml",
    "apps/api/auth.py",
    "apps/api/identity.py",
    "apps/api/plans.py",
    "apps/api/authentication/context.py",
    "apps/api/authentication/legacy.py",
    "apps/api/routers/logs.py",
    "apps/api/routers/progress.py",
    "docs/auth03/design.md",
    "docs/auth00/policy_review.json",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    "docs/auth00/operation_variants.md",
    "scripts/local_gates.py",
    "tests/unit/test_auth03_context.py",
    "tests/unit/test_auth03_http.py",
    "tests/integration/test_auth03_postgres.py",
    "tests/api/test_auth03_adapters.py",
    "tests/api/test_admin_progress_api.py",
    "tests/api/test_doclog6_approvals_archive.py",
    "tests/api/test_mentor_rules.py",
    "tests/api/test_run_report.py",
    "worklog/worklog11.md",
}


def main():
    for script in ("scripts/auth01/generate.py", "scripts/auth00/inventory.py"):
        subprocess.run([sys.executable, script, "--check"], cwd=ROOT, check=True)
    files = FILES | {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "scripts/auth03").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    files.add("scripts/auth03/files.txt")
    names = "\n".join(sorted(files)) + "\n"
    (ROOT / "scripts/auth03/files.txt").write_text(
        names, encoding="utf-8", newline="\n"
    )
    changed = set()
    for command in (
        ["git", "diff", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        changed.update(
            subprocess.check_output(command, cwd=ROOT)
            .decode("utf-8")
            .strip("\0")
            .split("\0")
        )
    changed.discard("")
    if changed != files:
        raise ValueError(
            "Delivery differs from git changes: " + repr(sorted(changed ^ files))
        )
    OUTPUT.mkdir(exist_ok=True)
    target = OUTPUT / "cisstat-auth03-be553b8.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT / name, name)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == files
        for name in files:
            assert archive.read(name) == (ROOT / name).read_bytes(), name
    shutil.copyfile(ROOT / "worklog/worklog11.md", OUTPUT / "worklog11-auth03.md")
    (OUTPUT / "auth03-files.txt").write_text(names, encoding="utf-8", newline="\n")
    print(f"ZIP verified: {target}; {len(files)} files; {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
