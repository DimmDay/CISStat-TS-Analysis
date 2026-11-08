"""AUTH-14 task-only overlay: reviewed base, manifest, ZIP CRC and exact bytes."""

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "a16b31bd0c3d49586de24d3556a39e43b9cc3321"
NEW_FILES = {
    ".github/workflows/auth14.yml",
    "tests/unit/test_auth14_compute.py",
    "tests/integration/test_auth14_compute.py",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE]:
        raise ValueError("Reviewed base required")
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("Overlay does not support deletions")
    untracked = git("ls-files", "--others", "--exclude-standard")
    unexpected = [
        p
        for p in untracked
        if p not in NEW_FILES
        and not p.startswith(
            ("scripts/auth14/", "docs/auth14/", "apps/api/billing/compute")
        )
    ]
    if unexpected:
        raise ValueError(
            "Unrelated generated files before delivery: " + str(unexpected[:8])
        )
    paths = sorted(
        set(git("diff", "--name-only", "HEAD"))
        | set(untracked)
        | {"scripts/auth14/files.txt"}
    )
    manifest = ROOT / "scripts/auth14/files.txt"
    manifest.write_text("\n".join(paths) + "\n", encoding="utf-8", newline="\n")
    if any(
        not (ROOT / p).is_file()
        or (ROOT / p).is_symlink()
        or Path(p).is_absolute()
        or ".." in Path(p).parts
        for p in paths
    ):
        raise ValueError("Repository-relative regular files required")
    out = ROOT.parent / "download"
    out.mkdir(exist_ok=True)
    archive = out / "cisstat-auth14-a16b31b.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in paths:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        if z.testzip() is not None or z.namelist() != paths:
            raise ValueError("ZIP CRC/manifest mismatch")
        for name in paths:
            if z.read(name) != (ROOT / name).read_bytes():
                raise ValueError("ZIP payload bytes changed")
    (out / "auth14-files.txt").write_bytes(manifest.read_bytes())
    (out / "worklog12-auth14.md").write_bytes(
        (ROOT / "worklog/worklog12.md").read_bytes()
    )
    print(
        json.dumps(
            {
                "archive": str(archive),
                "files": len(paths),
                "bytes": archive.stat().st_size,
                "crc_and_bytes": "ok",
            }
        )
    )


if __name__ == "__main__":
    main()
