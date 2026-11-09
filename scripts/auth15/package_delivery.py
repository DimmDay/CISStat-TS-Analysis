"""AUTH-15 task-only ZIP, CRC, exact payload bytes and SHA-256 manifest."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "b9af29bf9e359403db16b280fe8c1ab402597e85"
ALLOWED = (
    "scripts/auth15/",
    "docs/auth15/",
    "apps/api/authentication/demo",
    "apps/api/routers/demo.py",
    "apps/api/migrations/0027_auth15_demo.sql",
    "apps/standalone/app/demo/",
    "apps/embedded/app/demo/",
    "apps/standalone/app/admin/demo-campaigns/",
    "apps/embedded/app/admin/demo-campaigns/",
    "packages/ui/components/Demo",
    "packages/ui/components/auth15-demo.test.tsx",
    "packages/ui/lib/demo.ts",
    "tests/unit/test_auth15_demo.py",
    "tests/integration/test_auth15_demo.py",
    ".github/workflows/auth15.yml",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE]:
        raise ValueError("Reviewed base required")
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("No deleted files in overlay")
    untracked = git("ls-files", "--others", "--exclude-standard")
    if any(not p.startswith(ALLOWED) for p in untracked):
        raise ValueError("Unrelated untracked files")
    paths = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | set(untracked)
        | {"scripts/auth15/files.txt"}
    )
    manifest = ROOT / "scripts/auth15/files.txt"
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
    archive = out / "cisstat-auth15-b9af29b.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in paths:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == paths
        assert all(z.read(name) == (ROOT / name).read_bytes() for name in paths)
    (out / "auth15-files.txt").write_bytes(manifest.read_bytes())
    (out / "worklog12-auth15.md").write_bytes(
        (ROOT / "worklog/worklog12.md").read_bytes()
    )
    (out / "auth15-vm.md").write_bytes((ROOT / "docs/auth15/deploy.md").read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / "cisstat-auth15-b9af29b.zip.sha256").write_text(
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
