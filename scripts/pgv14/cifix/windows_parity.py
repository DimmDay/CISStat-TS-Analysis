#!/usr/bin/env python3
"""Reproduce the three Windows CP1252 failures even under PYTHONUTF8=1.

Only implicit pathlib text I/O uses CP1252. Explicit UTF-8 and binary hashes
retain their real behavior. Runs the unchanged 11-case host acceptance controls;
no Docker, Chromium or native Windows success is claimed.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
TESTS = (
    'tests.unit.test_pgv14_accept.EveryPageTests.test_all_eleven_page_sets_run_and_finalize_with_exact_page_review',
    'tests.unit.test_pgv13_accept.RunnerTests.test_finalize_requires_human_review_and_binds_payload_ocr',
    'tests.unit.test_pgv13_accept.RunnerTests.test_native_pipeline_writes_bound_images_and_pending_visual_review',
)


def main():
    original_open = Path.open
    original_read = Path.read_text
    original_write = Path.write_text

    def cp1252_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding in (None, 'locale'):
            encoding = 'cp1252'
        return original_open(path, mode, buffering, encoding, errors, newline)

    def cp1252_read(path, encoding=None, errors=None):
        return original_read(path, encoding=encoding or 'cp1252', errors=errors)

    def cp1252_write(path, data, encoding=None, errors=None, newline=None):
        return original_write(path, data, encoding=encoding or 'cp1252', errors=errors, newline=newline)

    with patch.object(Path, 'open', cp1252_open), \
         patch.object(Path, 'read_text', cp1252_read), \
         patch.object(Path, 'write_text', cp1252_write):
        # Prove the simulation still catches this defect when local_gates
        # forces PYTHONUTF8=1. Never replace/decode errors permissively.
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / 'unicode.json'
            probe.write_bytes('{"text":"Паспорт"}'.encode('utf-8'))
            try:
                probe.read_text()
            except UnicodeDecodeError:
                pass
            else:
                raise AssertionError('CP1252 negative control did not fail')
            assert probe.read_text(encoding='utf-8') == '{"text":"Паспорт"}'
        suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    ok = result.wasSuccessful() and result.testsRun == len(TESTS) and not result.skipped
    print('CP1252 filesystem parity: ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
