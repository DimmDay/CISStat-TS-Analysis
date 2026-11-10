"""AUTH-19 task-only zip. No staging/commit/push; exact manifest/bytes/CRC/SHA256."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "8ec771d"
NEW = (
    "scripts/auth19/",
    "docs/auth19/",
    "apps/api/authentication/providers/",
    "apps/api/authentication/email_challenges.py",
    "apps/api/authentication/oidc.py",
    "apps/api/authentication/auth19_migrations.py",
    "apps/api/migrations/0031_auth19_email_oidc.sql",
    "packages/ui/components/auth19-login.test.tsx",
    "tests/unit/test_auth19_challenges.py",
    "tests/unit/test_auth19_routes.py",
    "tests/integration/test_auth19_email_oidc.py",
    ".github/workflows/auth19.yml",
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
        | {"scripts/auth19/files.txt"}
    )
    manifest = ROOT / "scripts/auth19/files.txt"
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
    archive = out / "cisstat-auth19-8ec771d.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == names
        assert all(z.read(n) == (ROOT / n).read_bytes() for n in names)
    (out / "auth19-files.txt").write_bytes(manifest.read_bytes())
    (out / "worklog12-auth19.md").write_bytes(
        (ROOT / "worklog/worklog12.md").read_bytes()
    )
    (out / "auth19-vm.md").write_bytes((ROOT / "docs/auth19/deploy.md").read_bytes())
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
