"""AUTH-20 task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "c08ee9e"
NEW = (
    "scripts/auth20/",
    "docs/auth20/",
    "apps/api/authentication/auth20_migrations.py",
    "apps/api/authentication/ops_service.py",
    "apps/api/authentication/ops_sweeper.py",
    "apps/api/authentication/ops_health.py",
    "apps/api/authentication/lockdown.py",
    "apps/api/migrations/0032_auth20_audit_ops.sql",
    "tests/unit/test_auth20_ops.py",
    "tests/api/test_auth20_health.py",
    "tests/integration/test_auth20_reconciliation.py",
    ".github/workflows/auth20.yml",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    head = git("rev-parse", "HEAD")[0]
    if not head.startswith(BASE):
        raise ValueError("reviewed base required: " + BASE)
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("no deletes expected")
    names = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | {
            x
            for x in git("ls-files", "--others", "--exclude-standard")
            if x.startswith(NEW)
        }
        | {"scripts/auth20/files.txt"}
    )
    # worklog is delivered alongside the zip, not inside it (AUTH-19 precedent)
    names = [n for n in names if n != "worklog/worklog12.md"]
    manifest = ROOT / "scripts/auth20/files.txt"
    names = sorted(set(names))
    manifest.write_text("\n".join(names) + "\n", encoding="utf-8", newline="\n")
    if any(
        Path(n).is_absolute()
        or ".." in Path(n).parts
        or not (ROOT / n).is_file()
        or (ROOT / n).is_symlink()
        for n in names
    ):
        raise ValueError("regular relative files only")
    out = ROOT.parent / "download"
    out.mkdir(exist_ok=True)
    archive = out / "cisstat-auth20-c08ee9e.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == names
        assert all(z.read(n) == (ROOT / n).read_bytes() for n in names)
    (out / "auth20-files.txt").write_bytes(manifest.read_bytes())
    (out / "worklog12-auth20.md").write_bytes(
        (ROOT / "worklog/worklog12.md").read_bytes()
    )
    (out / "auth20-runbook.md").write_bytes(
        (ROOT / "docs/auth20/runbook.md").read_bytes()
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n")
    print(
        json.dumps(
            {
                "archive": str(archive),
                "files": len(names),
                "bytes": archive.stat().st_size,
                "sha256": digest,
                "crc_and_bytes": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
