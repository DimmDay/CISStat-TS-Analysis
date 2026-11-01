#!/usr/bin/env python3
"""Package exactly AUTH-04 changes; verify inventory, CRC and every byte."""

from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT.parent / "upload"
FILES = {
    ".github/workflows/auth04.yml",
    "apps/api/access_registry.v1.json",
    "apps/api/authentication/audit_outbox.py",
    "apps/api/authentication/context.py",
    "apps/api/authentication/credentials.py",
    "apps/api/authentication/csrf.py",
    "apps/api/authentication/password_blocklist.txt",
    "apps/api/authentication/session_migrations.py",
    "apps/api/authentication/sessions.py",
    "apps/api/main.py",
    "apps/api/migrations/0020_auth04_sessions.sql",
    "apps/api/requirements.txt",
    "apps/api/routers/authentication.py",
    "apps/api/security_audit.py",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    "docs/auth00/operation_variants.md",
    "docs/auth00/policy_review.json",
    "docs/auth01/openapi.json",
    "docs/auth04/design.md",
    "packages/ui/lib/access-contract.generated.ts",
    "scripts/auth00/inventory.py",
    "scripts/local_gates.py",
    "tests/api/test_doclog8_monitoring.py",
    "tests/integration/test_auth04_sessions.py",
    "tests/unit/test_auth00_inventory.py",
    "tests/unit/test_auth04_password_transport.py",
    "tests/unit/test_auth04_routes.py",
    "worklog/worklog11.md",
}


def main():
    for script in ("scripts/auth01/generate.py", "scripts/auth00/inventory.py"):
        subprocess.run([sys.executable, script, "--check"], cwd=ROOT, check=True)
    files = FILES | {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "scripts/auth04").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    files.add("scripts/auth04/files.txt")
    names = "\n".join(sorted(files)) + "\n"
    (ROOT / "scripts/auth04/files.txt").write_text(
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
    target = OUTPUT / "cisstat-auth04-d3f78a7.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT / name, name)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == files
        for name in files:
            assert archive.read(name) == (ROOT / name).read_bytes(), name
    shutil.copyfile(ROOT / "worklog/worklog11.md", OUTPUT / "worklog11-auth04.md")
    (OUTPUT / "auth04-files.txt").write_text(names, encoding="utf-8", newline="\n")
    print(f"ZIP verified: {target}; {len(files)} files; {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
