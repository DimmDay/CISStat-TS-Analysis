"""Package only this task's changes; verify inventory, CRC and exact bytes."""
from pathlib import Path
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'scripts/jest505/'
PROTOCOLS = [
    'red.json', 'red.txt', 'npm_ci.txt', 'dependency_recheck.txt',
    'full_before.json', 'full_before_parallel.txt', 'guard_fixture_red.txt',
    'h28_delayed_red.json', 'h28_delayed_red.txt',
    'eda_green.json', 'eda_green_final.txt',
    'full_final.json', 'full_final.txt', 'environment.json', 'summary.json',
    'repeat_summary.json', 'renderer_build.txt', 'typecheck.txt',
    'build_all.txt', 'build_standalone.txt', 'doc_guard.txt',
] + [f'repeat_{n}.txt' for n in range(1, 6)]

def main():
    final = json.loads((ROOT / PREFIX / 'protocols/full_final.json').read_text())
    assert final['success'] and final['numFailedTests'] == 0
    assert final['numPassedTests'] == final['numTotalTests'] == 2728
    assert final['numPassedTestSuites'] == final['numTotalTestSuites'] == 236
    assert final['numPendingTests'] == final['numRuntimeErrorTestSuites'] == 0
    modified = subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT, text=True).splitlines()
    expected = {'apps/print-renderer/src/launchGuard.test.ts',
                'packages/ui/components/TsAnalysisEDA.tsx',
                'packages/ui/components/TsAnalysisUpload.test.tsx',
                'packages/ui/components/prograudit0_h28_viewed_transfer.test.tsx',
                'worklog/worklog11.md'}
    assert set(modified) == expected, modified
    names = sorted(expected | {'docs/jest_505c304_fix.md', PREFIX + 'README.md',
                              PREFIX + 'files.txt', PREFIX + 'package_delivery.py'} |
                   {PREFIX + 'protocols/' + p for p in PROTOCOLS})
    (ROOT / PREFIX / 'files.txt').write_text('\n'.join(names) + '\n')
    target = ROOT.parent / 'upload/cisstat-jest-fix-505c304.zip'
    target.parent.mkdir(exist_ok=True)
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in names:
            path = ROOT / name
            assert path.is_file() and not path.is_symlink(), name
            z.write(path, name)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert z.namelist() == names
        for name in names:
            assert z.read(name) == (ROOT / name).read_bytes(), name
    print(json.dumps({'zip':str(target), 'files':len(names),
                      'bytes':target.stat().st_size, 'CRC':'PASS', 'exact_bytes':'PASS'}))

if __name__ == '__main__':
    main()
