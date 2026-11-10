"""AUTH-18 task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "3ca5e4ed0742b5dce6c811f048ed3648817eafa6"
NEW = (
    "scripts/auth18/",
    "docs/auth18/",
    "apps/api/billing/provider.py",
    "apps/api/billing/subscription",
    "apps/api/migrations/0030_auth18_provider.sql",
    "apps/api/routers/billing.py",
    "packages/ui/components/BillingPanel.tsx",
    "packages/ui/components/auth18-billing.test.tsx",
    "packages/ui/lib/billing.ts",
    "tests/unit/test_auth18_provider.py",
    "tests/integration/test_auth18_saga.py",
    ".github/workflows/auth18.yml",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE] or git(
        "diff", "--name-only", "--diff-filter=D", "HEAD"
    ):
        raise ValueError("reviewed base/no deletes required")
    names = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | {
            x
            for x in git("ls-files", "--others", "--exclude-standard")
            if x.startswith(NEW)
        }
        | {"scripts/auth18/files.txt"}
    )
    manifest = ROOT / "scripts/auth18/files.txt"
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
    archive = out / "cisstat-auth18-3ca5e4e.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == names
        assert all(z.read(n) == (ROOT / n).read_bytes() for n in names)
    (out / "auth18-files.txt").write_bytes(manifest.read_bytes())
    (out / "worklog12-auth18.md").write_bytes(
        (ROOT / "worklog/worklog12.md").read_bytes()
    )
    (out / "auth18-vm.md").write_bytes((ROOT / "docs/auth18/deploy.md").read_bytes())
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
