"""Package only JEST-B613120-FIX sources and evidence; verify inventory/bytes."""
from pathlib import Path
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "scripts/jest-b613120"
UPLOAD = ROOT.parent / "upload"


def main() -> None:
    files = [
        ".github/workflows/jest.yml",
        ".gitignore",
        "package.json",
        "packages/ui/components/TsAnalysisUpload.tsx",
        "packages/ui/components/TsAnalysisUpload.test.tsx",
        "worklog/worklog11.md",
        "docs/jest_b613120_fix.md",
        "scripts/jest-b613120/package_delivery.py",
        "scripts/jest-b613120/files.txt",
    ]
    files += [p.relative_to(ROOT).as_posix() for p in (TASK / "protocols").iterdir() if p.is_file()]
    files = sorted(files)
    (TASK / "files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    UPLOAD.mkdir(exist_ok=True)
    archive = UPLOAD / "cisstat-jest-b613120-fix.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(ROOT / rel, rel)
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == files
        for rel in files:
            assert zf.read(rel) == (ROOT / rel).read_bytes(), rel
    shutil.copyfile(ROOT / "worklog/worklog11.md", UPLOAD / "worklog11-b613120.md")
    shutil.copyfile(TASK / "files.txt", UPLOAD / "jest-b613120-files.txt")
    print(json.dumps({"archive": str(archive), "files": len(files),
                      "bytes": archive.stat().st_size, "crc": "OK", "exact_bytes": "OK"}))


if __name__ == "__main__":
    main()
