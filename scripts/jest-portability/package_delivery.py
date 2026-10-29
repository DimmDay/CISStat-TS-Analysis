"""Package this task's exact source/evidence inventory, verify CRC and bytes."""
from pathlib import Path
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "scripts/jest-portability"
UPLOAD = ROOT.parent / "upload"


def main() -> None:
    files = [
        ".github/workflows/jest.yml",
        "apps/print-renderer/src/launchGuard.ts",
        "apps/print-renderer/src/launchGuard.test.ts",
        "package.json",
        "package-lock.json",
        "packages/ui/components/TsAnalysisUpload.test.tsx",
        "scripts/pgv07cert/test_p7cert_findings.test.tsx",
        "scripts/testing/runtimes.ts",
        "scripts/testing/runtimes.test.ts",
        "scripts/jest-portability/package_delivery.py",
        "scripts/jest-portability/files.txt",
        "docs/jest_portability_781de34.md",
        "worklog/worklog11.md",
    ]
    files += [p.relative_to(ROOT).as_posix() for p in (TASK / "protocols").iterdir() if p.is_file()]
    files = sorted(files)
    (TASK / "files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    UPLOAD.mkdir(exist_ok=True)
    archive = UPLOAD / "cisstat-jest-portability-781de34.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(ROOT / rel, rel)
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == files
        for rel in files:
            assert zf.read(rel) == (ROOT / rel).read_bytes(), rel
    shutil.copyfile(ROOT / "worklog/worklog11.md", UPLOAD / "worklog11.md")
    shutil.copyfile(TASK / "files.txt", UPLOAD / "jest-portability-files.txt")
    print(json.dumps({"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size,
                      "crc": "OK", "exact_bytes": "OK"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
