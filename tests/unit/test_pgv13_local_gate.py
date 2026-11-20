"""The local acceptance gate must fail closed on incomplete evidence."""
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.pgv13local import verify as gate


class LocalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'junit.xml'
        self.case_id = 'scripts.pgv13cert.test_contracts::test_real'

    def xml(self, body='', backend='memory', name='test_real', properties=True):
        props = f'<properties><property name="backend" value="{backend}"/></properties>' if properties else ''
        return f'<testcase classname="scripts.pgv13cert.test_contracts" name="{name}">{props}{body}</testcase>'

    def write(self, cases):
        self.path.write_text('<testsuites><testsuite>'+cases+'</testsuite></testsuites>', encoding='utf-8')

    def check(self):
        return gate.validate_report(self.path, [self.case_id], 'memory')

    def test_exact_success_with_real_backend_evidence(self):
        self.write(self.xml())
        self.assertEqual(self.check()['tests'], 1)

    def test_missing_empty_and_invalid_junit_are_not_pass(self):
        with self.assertRaises(ValueError):
            self.check()
        for content in ['<testsuites/>', '<bad', 'not xml']:
            with self.subTest(content=content):
                self.path.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.check()

    def test_failures_errors_and_skips_are_rejected(self):
        for kind in ['failure', 'error', 'skipped']:
            with self.subTest(kind=kind):
                self.write(self.xml(f'<{kind}/>'))
                with self.assertRaises(ValueError):
                    self.check()

    def test_substitution_duplicate_and_deselection_are_rejected(self):
        for cases in [self.xml(name='another'), self.xml()+self.xml(), '']:
            with self.subTest(cases=cases):
                self.write(cases)
                with self.assertRaises(ValueError):
                    self.check()

    def test_missing_or_wrong_backend_is_not_native_proof(self):
        for case in [self.xml(backend='postgres'), self.xml(properties=False)]:
            self.write(case)
            with self.assertRaises(ValueError):
                self.check()

    def test_memory_cannot_silently_inherit_native_dsn_or_pytest_filter(self):
        env = gate.backend_environment({'CISSTAT_PGV13_CERT_DSN': 'private',
                                        'PYTEST_ADDOPTS': '-k nonexistent'}, 'memory')
        self.assertNotIn('CISSTAT_PGV13_CERT_DSN', env)
        self.assertNotIn('PYTEST_ADDOPTS', env)

    def test_native_requires_dsn_without_memory_fallback(self):
        with self.assertRaises(ValueError):
            gate.backend_environment({}, 'postgres')
        self.assertEqual(gate.backend_environment({'CISSTAT_PGV13_CERT_DSN': 'private'},
                                                 'postgres')['CISSTAT_PGV13_CERT_DSN'], 'private')

    def test_utf8_environment_starts_actual_python(self):
        result = subprocess.run([sys.executable, '-c', 'print("Паспорт")'],
                                env=gate.backend_environment(os.environ, 'memory'),
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'Паспорт')

    def test_missing_dsn_invalidates_old_success_before_build(self):
        out = Path(self.tmp.name)
        (out/'summary.json').write_text('{"passed":true}', encoding='utf-8')
        with patch.dict(gate.os.environ, {}, clear=True), patch.object(gate, 'run_logged') as run:
            self.assertEqual(gate.main(['--postgres', '--out', str(out)]), 2)
        run.assert_not_called()
        summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['state'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
