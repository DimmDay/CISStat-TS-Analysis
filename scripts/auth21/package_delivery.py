"""AUTH-21 task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "a0a2af6c6490f81620b16d0da8453d044657eb67"
NEW = (
    "scripts/auth21/",
    "docs/auth21/",
    "apps/api/billing/wallet",
    "apps/api/migrations/0033_auth21_wallet.sql",
    "tests/unit/test_auth21_wallet.py",
    "tests/integration/test_auth21_wallet.py",
    ".github/workflows/auth21.yml",
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
        | {"scripts/auth21/files.txt"}
    )
    manifest = ROOT / "scripts/auth21/files.txt"
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
    archive = out / "cisstat-auth21-a0a2af6.zip"
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
    (out / "auth21-files.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    (out / "cisstat-auth21-a0a2af6.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "  cisstat-auth21-a0a2af6.zip\n",
        encoding="utf-8",
    )
    (out / "auth21-manifest.json").write_text(
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
    main()
