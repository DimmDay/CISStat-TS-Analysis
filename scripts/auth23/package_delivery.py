"""AUTH-23 task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "004dba5"
NEW = (
    "scripts/auth23/",
    "docs/auth23/",
    "apps/api/billing/refund",
    "apps/api/billing/refunds.py",
    "apps/api/migrations/0035_auth23_refunds.sql",
    "tests/unit/test_auth23_refunds.py",
    "tests/integration/test_auth23_refunds.py",
    ".github/workflows/auth23.yml",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("no deletes required")
    names = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | {
            x
            for x in git("ls-files", "--others", "--exclude-standard")
            if x.startswith(NEW)
        }
        | {"scripts/auth23/files.txt"}
    )
    manifest = ROOT / "scripts/auth23/files.txt"
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
    archive = out / "cisstat-auth23-004dba5.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            z.write(ROOT / name, name)
    payload = archive.read_bytes()
    digests = []
    with ZipFile(archive) as z:
        for info in z.infolist():
            data = z.read(info.filename)
            digests.append(
                {"name": info.filename, "size": len(data), "crc32": f"{info.CRC:08x}"}
            )
    (out / "auth23-files.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    (out / "cisstat-auth23-004dba5.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "  cisstat-auth23-004dba5.zip\n",
        encoding="utf-8",
    )
    (out / "auth23-manifest.json").write_text(
        json.dumps(
            {
                "base": BASE,
                "archive": archive.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "files": digests,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "files": len(names), "archive": archive.name}))


if __name__ == "__main__":
    sys.exit(main())
