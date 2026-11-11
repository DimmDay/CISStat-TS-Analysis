"""AUTH-22 task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "7d233ad"
NEW = (
    "scripts/auth22/",
    "docs/auth22/",
    "apps/api/billing/topup",
    "apps/api/migrations/0034_auth22_topups.sql",
    "packages/ui/components/TopupPanel",
    "packages/ui/components/auth22-topup",
    "tests/unit/test_auth22_topups.py",
    "tests/integration/test_auth22_topups.py",
    ".github/workflows/auth22.yml",
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
        | {"scripts/auth22/files.txt"}
    )
    manifest = ROOT / "scripts/auth22/files.txt"
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
    archive = out / "cisstat-auth22-7d233ad.zip"
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
    (out / "auth22-files.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    (out / "cisstat-auth22-7d233ad.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "  cisstat-auth22-7d233ad.zip\n",
        encoding="utf-8",
    )
    (out / "auth22-manifest.json").write_text(
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
