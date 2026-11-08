"""AUTH-11 task-only overlay; verify base, manifest, ZIP CRC and exact bytes."""

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "bf5763051285f1f1e74d14e2ce3680a47493c0ca"
NEW_FILES = {
    ".github/workflows/auth11.yml",
    "apps/api/scientific.py",
    "apps/api/scientific_workload.py",
    "packages/ui/lib/scientificErrors.ts",
    "packages/ui/lib/scientificErrors.test.ts",
    "tests/unit/test_auth11_scientific.py",
    "tests/integration/test_auth11_scientific.py",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()


def main():
    if git("rev-parse", "HEAD") != [BASE]:
        raise ValueError("Delivery must use the reviewed base")
    if git("diff", "--name-only", "--diff-filter=D", "HEAD"):
        raise ValueError("This overlay does not support deletions")
    untracked = git("ls-files", "--others", "--exclude-standard")
    unexpected = [
        p for p in untracked
        if p not in NEW_FILES and not p.startswith(("scripts/auth11/", "docs/auth11/"))
    ]
    if unexpected:
        raise ValueError("Remove unrelated/generated files before delivery: " + str(unexpected[:8]))
    paths = sorted(set(git("diff", "--name-only", "HEAD")) | set(untracked) | {"scripts/auth11/files.txt"})
    manifest = ROOT / "scripts/auth11/files.txt"
    manifest.write_text("\n".join(paths) + "\n", encoding="utf-8", newline="\n")
    if any(not (ROOT / p).is_file() or Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
        raise ValueError("Only repository-relative existing files may be packaged")
    target = ROOT.parent / "download"
    target.mkdir(exist_ok=True)
    archive = target / "cisstat-auth11-bf57630-final.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for name in paths:
            z.write(ROOT / name, name)
    with ZipFile(archive) as z:
        if z.testzip() is not None or z.namelist() != paths:
            raise ValueError("ZIP CRC/inventory mismatch")
        for name in paths:
            if z.read(name) != (ROOT / name).read_bytes():
                raise ValueError("ZIP bytes changed during packaging")
    (target / "auth11-final-files.txt").write_bytes(manifest.read_bytes())
    (target / "worklog11-auth11-final.md").write_bytes((ROOT / "worklog/worklog11.md").read_bytes())
    print(json.dumps({"archive": str(archive), "files": len(paths), "bytes": archive.stat().st_size, "crc_and_bytes": "ok"}))


if __name__ == "__main__":
    main()
