"""AUTH-17 task-only ZIP, CRC, exact payload bytes and SHA-256 manifest."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "201a3b1f12eac55525fb07301b5e37f8e962d938"
ALLOWED = (
    "scripts/auth17/",
    "docs/auth17/",
    "apps/api/accounts/team",
    "apps/api/routers/accounts.py",
    "apps/api/migrations/0029_auth17_team.sql",
    "apps/embedded/app/account/",
    "apps/standalone/app/account/",
    "packages/ui/components/AccountScreen.tsx",
    "packages/ui/components/auth17-team.test.tsx",
    "packages/ui/lib/team.ts",
    "tests/unit/test_auth17_team.py",
    "tests/integration/test_auth17_team.py",
    ".github/workflows/auth17.yml",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE]:
        raise ValueError("Reviewed base required")
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("No deleted files in overlay")
    untracked = git("ls-files", "--others", "--exclude-standard")
    # Include only task-owned new files. Other untracked files never enter ZIP.
    untracked = [p for p in untracked if p.startswith(ALLOWED)]
    paths = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | set(untracked)
        | {"scripts/auth17/files.txt"}
    )
    manifest = ROOT / "scripts/auth17/files.txt"
    manifest.write_text("\n".join(paths) + "\n", encoding="utf-8", newline="\n")
    if any(
        not (ROOT / p).is_file()
        or (ROOT / p).is_symlink()
        or Path(p).is_absolute()
        or ".." in Path(p).parts
        for p in paths
    ):
        raise ValueError("Regular relative files only")
    out = ROOT.parent / "download"
    out.mkdir(exist_ok=True)
    archive = out / "cisstat-auth17-201a3b1.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in paths:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == paths
        assert all(z.read(name) == (ROOT / name).read_bytes() for name in paths)
    (out / "auth17-files.txt").write_bytes(manifest.read_bytes())
    (out / "worklog12-auth17.md").write_bytes(
        (ROOT / "worklog/worklog12.md").read_bytes()
    )
    (out / "auth17-vm.md").write_bytes((ROOT / "docs/auth17/deploy.md").read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / "cisstat-auth17-201a3b1.zip.sha256").write_text(
        digest + "  " + archive.name + "\n"
    )
    print(
        json.dumps(
            {
                "archive": str(archive),
                "files": len(paths),
                "bytes": archive.stat().st_size,
                "sha256": digest,
                "crc_and_bytes": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
