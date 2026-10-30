"""Package the document fix and independently verify the one-line patch."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "scripts/jest-1aa225c"
UPLOAD = ROOT.parent / "upload"
BASE = "1aa225ce22d162d837711e5e3d72bbe51817278e"


def main() -> None:
    files = [
        "worklog/worklog11.md",
        "docs/jest_1aa225c_worklog_fix.md",
        "scripts/jest-1aa225c/pgv07-count.patch",
        "scripts/jest-1aa225c/package_delivery.py",
        "scripts/jest-1aa225c/files.txt",
    ]
    files += [p.relative_to(ROOT).as_posix() for p in (TASK / "protocols").iterdir() if p.is_file()]
    files = sorted(files)
    (TASK / "files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    UPLOAD.mkdir(exist_ok=True)
    archive = UPLOAD / "cisstat-jest-1aa225c-worklog-fix.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(ROOT / rel, rel)
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == files
        for rel in files:
            assert zf.read(rel) == (ROOT / rel).read_bytes(), rel
        # Check the optional manual-transfer route against the original commit,
        # independently of the fixed full worklog also shipped in this ZIP.
        with tempfile.TemporaryDirectory(prefix="verify-pgv07-", dir=ROOT.parent) as tmp:
            control = Path(tmp)
            (control / "worklog").mkdir()
            original = subprocess.check_output(["git", "show", f"{BASE}:worklog/worklog11.md"], cwd=ROOT)
            (control / "worklog/worklog11.md").write_bytes(original)
            patch = control / "pgv07-count.patch"
            patch.write_bytes(zf.read("scripts/jest-1aa225c/pgv07-count.patch"))
            subprocess.run(["git", "apply", "--check", str(patch)], cwd=control, check=True)
            subprocess.run(["git", "apply", str(patch)], cwd=control, check=True)
            fixed = (control / "worklog/worklog11.md").read_bytes()
            before = "Doc-contract гвард scripts/pgv07/check_documents.py — 62/62.".encode()
            after = "Doc-contract гвард scripts/pgv07/check_documents.py — 41/41.".encode()
            assert fixed == original.replace(before, after, 1)
            assert zf.read("worklog/worklog11.md").startswith(fixed)
    shutil.copyfile(ROOT / "worklog/worklog11.md", UPLOAD / "worklog11-1aa225c.md")
    shutil.copyfile(TASK / "files.txt", UPLOAD / "jest-1aa225c-files.txt")
    shutil.copyfile(TASK / "pgv07-count.patch", UPLOAD / "pgv07-count-1aa225c.patch")
    print(json.dumps({"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size,
                      "crc": "OK", "exact_bytes": "OK", "patch_from_base": "OK"}))


if __name__ == "__main__":
    main()
