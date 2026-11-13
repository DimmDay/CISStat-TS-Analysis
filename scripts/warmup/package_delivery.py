"""AUTH-CERT-H1FIX task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "a38c4a4"
NEW = (
    "scripts/warmup/",
    "docs/authcert/h1fix.md",
    "docs/authcert/h1fix-deploy.md",
    "apps/api/storage_warmup.py",
    "tests/unit/test_warmup_fcert_h1.py",
    "tests/integration/test_warmup_fcert_h1.py",
    ".github/workflows/warmup.yml",
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
        | {"scripts/warmup/files.txt", "worklog/worklog12.md"}
    )
    manifest = ROOT / "scripts/warmup/files.txt"
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
    archive = out / "cisstat-h1fix-a38c4a4.zip"
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
    (out / "h1fix-files.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    (out / "cisstat-h1fix-a38c4a4.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "  cisstat-h1fix-a38c4a4.zip\n",
        encoding="utf-8",
    )
    (out / "h1fix-manifest.json").write_text(
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
