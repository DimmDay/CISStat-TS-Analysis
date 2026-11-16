"""Exact task-only overlay on reviewed 53ebba5; never stage/commit/push."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "53ebba5525814f6622774e86da319b274ef27946"
NEW = (
    "scripts/kabinet_demo_cert/",
    "docs/kabinet_demo_cert/",
    "tests/unit/test_kabinet_demo_cert.py",
    "packages/ui/lib/demo-cert.test.ts",
    ".github/workflows/kabinet_demo_cert.yml",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE] or git(
        "diff", "--name-only", "--diff-filter=D", "HEAD"
    ):
        raise ValueError("Reviewed base/no deletes required")
    names = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | {
            n
            for n in git("ls-files", "--others", "--exclude-standard")
            if n.startswith(NEW)
        }
        | {"scripts/kabinet_demo_cert/files.txt"}
    )
    manifest = ROOT / "scripts/kabinet_demo_cert/files.txt"
    manifest.write_text("\n".join(names) + "\n", encoding="utf-8", newline="\n")
    if any(
        Path(n).is_absolute()
        or ".." in Path(n).parts
        or not (ROOT / n).is_file()
        or (ROOT / n).is_symlink()
        for n in names
    ):
        raise ValueError("Regular relative payload only")
    if any(
        Path(n).suffix in {".pem", ".key"}
        or any(part.startswith("tls-") for part in Path(n).parts)
        for n in names
    ):
        raise ValueError("Stop temporary TLS/browser fixtures before packaging")
    out = ROOT.parent / "download"
    out.mkdir(exist_ok=True)
    archive = out / "cisstat-kabinet-demo-cert-53ebba5.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for n in names:
            z.write(ROOT / n, n)
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.namelist() == names
        assert all(z.read(n) == (ROOT / n).read_bytes() for n in names)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n")
    for source, target in [
        ("scripts/kabinet_demo_cert/files.txt", "kabinet-demo-cert-files.txt"),
        ("docs/kabinet_demo_cert/report.md", "kabinet-demo-cert-report.md"),
        ("docs/kabinet_demo_cert/deploy.md", "kabinet-demo-cert-vm.md"),
        ("worklog/worklog12.md", "worklog12-kabinet-demo-cert.md"),
    ]:
        if (ROOT / source).is_file():
            (out / target).write_bytes((ROOT / source).read_bytes())
    print(
        json.dumps(
            {
                "file": str(archive),
                "files": len(names),
                "bytes": archive.stat().st_size,
                "sha256": digest,
                "crc_bytes": "PASS",
            }
        )
    )


if __name__ == "__main__":
    main()
