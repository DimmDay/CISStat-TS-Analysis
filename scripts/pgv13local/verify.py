"""Step 3 only: strict Memory/PostgreSQL durable -> compiled TS acceptance."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SELECTION = ['scripts/pgv13cert/test_contracts.py',
             'scripts/pgv13cert/test_local_acceptance.py',
             'scripts/pgv13cert/test_deployment.py']


def backend_environment(base, backend):
    env = dict(base)
    env.pop('PYTEST_ADDOPTS', None)
    if backend == 'memory':
        env.pop('CISSTAT_PGV13_CERT_DSN', None)
    elif not env.get('CISSTAT_PGV13_CERT_DSN', '').strip():
        raise ValueError('Set CISSTAT_PGV13_CERT_DSN to disposable PostgreSQL with CREATE DATABASE')
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def validate_report(path, expected_cases, backend):
    try:
        cases = list(ET.parse(path).iter('testcase'))
    except (OSError, ET.ParseError) as error:
        raise ValueError('Missing or invalid JUnit evidence') from error
    actual = [c.get('classname', '')+'::'+c.get('name', '') for c in cases]
    if not actual or Counter(actual) != Counter(expected_cases) or len(set(actual)) != len(actual):
        raise ValueError('Incomplete, substituted or duplicate test selection')
    if any(c.find(kind) is not None for c in cases for kind in ['failure', 'error', 'skipped']):
        raise ValueError('Failures, errors, skips and xfail are not accepted')
    for case in cases:
        if case.get('classname', '').endswith('test_deployment'):
            continue
        props = {p.get('name'): p.get('value') for p in case.findall('./properties/property')}
        if props.get('backend') != backend:
            raise ValueError('Missing or wrong actual registry backend evidence')
    return {'tests': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0,
            'backend': backend, 'exact_manifest': True}


def write_summary(out, report):
    temp = out / 'summary.tmp'
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.replace(out/'summary.json')


def run_logged(command, path, env):
    run = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    text = run.stdout.replace(env.get('CISSTAT_PGV13_CERT_DSN') or '\0', '[REDACTED_DSN]')
    path.write_text(text, encoding='utf-8')
    return run.returncode


def fingerprints(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--memory', action='store_true')
    modes.add_argument('--postgres', action='store_true')
    modes.add_argument('--both', action='store_true')
    parser.add_argument('--out', type=Path, default=ROOT.parent/'pgv13local-results')
    args = parser.parse_args(argv)
    backends = ['memory', 'postgres'] if args.both else ['postgres' if args.postgres else 'memory']
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'state': 'RUNNING', 'passed': False, 'requested_backends': backends,
              'full_pgv13_certified': False, 'results': {}}
    write_summary(out, report)  # Invalidate any old PASS before preflight/build.
    try:
        environments = {b: backend_environment(os.environ, b) for b in backends}
    except ValueError as error:
        report.update(state='BLOCKED', reason=str(error))
        write_summary(out, report)
        print(report['reason'])
        return 2
    try:
        expected = json.loads((ROOT/'scripts/pgv13local/cases.json').read_text(encoding='utf-8'))
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise ValueError('npm is required for a fresh TypeScript build')
        dist = ROOT/'apps/print-renderer/dist'
        shutil.rmtree(dist, ignore_errors=False) if dist.exists() else None
        code = run_logged([npm, 'run', 'build', '--workspace=@cisstat/print-renderer'],
                          out/'build.txt', environments[backends[0]])
        if code:
            raise ValueError('Fresh renderer build failed; see build.txt')
        compiled = fingerprints(dist.rglob('*.js'))
        if not any(p.endswith('/rendererCore.js') for p in compiled):
            raise ValueError('Fresh compiled rendererCore.js is missing')
        source_paths = list((ROOT/'apps/api').rglob('*.py')) + list((ROOT/'packages/ui/print').rglob('*.tsx'))
        source_paths += [ROOT/p for p in SELECTION]
        frozen_sources = fingerprints(source_paths)
        report['compiled_js_sha256'] = compiled
        report['source_sha256'] = frozen_sources
        for backend in backends:
            junit = out/(backend+'.xml')
            junit.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(prefix='pgv13local-'+backend+'-', dir=ROOT.parent) as temp:
                code = run_logged([sys.executable, '-m', 'pytest', *SELECTION, '-q',
                                   '-o', 'addopts=', '-o', 'junit_family=xunit1',
                                   '--strict-markers', '--basetemp='+str(Path(temp)/'pytest'),
                                   '--junitxml='+str(junit)],
                                  out/(backend+'.txt'), environments[backend])
            try:
                result = validate_report(junit, expected, backend)
                if code:
                    raise ValueError('pytest returned a nonzero exit')
                report['results'][backend] = result
            except ValueError as error:
                report['results'][backend] = {'passed': False, 'reason': str(error), 'exit': code}
            if fingerprints(source_paths) != frozen_sources or fingerprints(dist.rglob('*.js')) != compiled:
                raise ValueError('Source or compiled renderer changed during the probes')
        passed = len(report['results']) == len(backends) and all(
            r.get('exact_manifest') for r in report['results'].values())
        report.update(state='PASS' if passed else 'FAIL', passed=passed,
                      both_backends_passed=passed and len(backends) == 2)
    except Exception as error:
        # Do not serialize DSNs, tracebacks or arbitrary exception messages.
        report.update(state='FAIL', error_class=type(error).__name__)
    write_summary(out, report)
    print(json.dumps({k: report[k] for k in ['state', 'passed', 'results', 'full_pgv13_certified']}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
