"""Package this task's sources and evidence, verifying exact changed inventory."""
from pathlib import Path
import json
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "scripts/jest-local-8014038"
UPLOAD = ROOT.parent / "upload"


def main() -> None:
    files = [
        "apps/print-renderer/build/Dockerfile",
        "apps/print-renderer/src/pngCrc32.ts",
        "apps/print-renderer/src/pngCrc32.test.ts",
        "apps/print-renderer/src/rendererCore.tsx",
        "apps/print-renderer/src/rendererCore.test.ts",
        "jest.config.js",
        "packages/ui/hooks/useChartDetailData.test.tsx",
        "packages/ui/components/validation-dataset-editor-toggle.test.tsx",
        "scripts/pgv08cert/test_p8cert_oracles.test.ts",
        "scripts/testing/pngCrc32Oracle.ts",
        "docs/jest_local_8014038_fix.md",
        "worklog/worklog11.md",
        "scripts/jest-local-8014038/without_native_crc.cjs",
        "scripts/jest-local-8014038/package_delivery.py",
        "scripts/jest-local-8014038/files.txt",
    ]
    files += [p.relative_to(ROOT).as_posix() for p in (TASK / "protocols").iterdir() if p.is_file()]
    files = sorted(files)
    (TASK / "files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    changed = set(subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines())
    added = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines())
    assert set(files) == changed | added, ((changed | added) - set(files), set(files) - (changed | added))
    UPLOAD.mkdir(exist_ok=True)
    archive = UPLOAD / "cisstat-jest-local-8014038-fix.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(ROOT / rel, rel)
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == files
        for rel in files:
            assert zf.read(rel) == (ROOT / rel).read_bytes(), rel
    shutil.copyfile(ROOT / "worklog/worklog11.md", UPLOAD / "worklog11-local-8014038.md")
    shutil.copyfile(TASK / "files.txt", UPLOAD / "jest-local-8014038-files.txt")
    print(json.dumps({"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size,
                      "crc": "OK", "inventory": "OK", "exact_bytes": "OK"}))


if __name__ == "__main__":
    main()
