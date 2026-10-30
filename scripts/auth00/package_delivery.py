"""Package only AUTH-00 changes; verify inventory, CRC and exact file bytes."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
UPLOAD = ROOT.parent / 'upload'
TASK = ROOT / 'scripts/auth00'


def main():
    subprocess.run([sys.executable, str(TASK / 'inventory.py'), '--check'], cwd=ROOT, check=True)
    files = [
        '.github/workflows/auth00.yml',
        'docs/auth00/design.md',
        'docs/auth00/inventory.json',
        'docs/auth00/inventory.md',
        'docs/auth00/operation_variants.md',
        'docs/auth00/policy_review.json',
        'docs/auth00/threat_model.md',
        'scripts/auth00/inventory.py',
        'scripts/auth00/package_delivery.py',
        'scripts/auth00/files.txt',
        'tests/unit/test_auth00_inventory.py',
        'worklog/worklog11.md',
    ]
    files += [p.relative_to(ROOT).as_posix() for p in (TASK / 'protocols').iterdir() if p.is_file()]
    files = sorted(files)
    (TASK / 'files.txt').write_text('\n'.join(files) + '\n', encoding='utf-8')
    changed = set(subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT, text=True).splitlines())
    added = set(subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines())
    assert set(files) == changed | added, ((changed | added) - set(files), set(files) - (changed | added))
    UPLOAD.mkdir(exist_ok=True)
    archive = UPLOAD / 'cisstat-auth00-962ccda.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(ROOT / rel, rel)
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == files
        for rel in files:
            assert zf.read(rel) == (ROOT / rel).read_bytes(), rel
    shutil.copyfile(ROOT / 'worklog/worklog11.md', UPLOAD / 'worklog11-auth00.md')
    shutil.copyfile(TASK / 'files.txt', UPLOAD / 'auth00-files.txt')
    print(json.dumps({'archive': str(archive), 'files': len(files), 'bytes': archive.stat().st_size,
                      'crc': 'OK', 'inventory': 'OK', 'exact_bytes': 'OK'}))


if __name__ == '__main__':
    main()
