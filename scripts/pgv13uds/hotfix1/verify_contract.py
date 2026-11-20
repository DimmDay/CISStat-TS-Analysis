"""Fault controls for the AUTH-00 worker contract; no source/INDEX writes."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    'inventory_tests', ROOT / 'tests/unit/test_auth00_inventory.py'
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Case = module.InventoryTests
DOCUMENT = 'test_pgv09_pgv10_documentation_surfaces_are_honestly_classified'
WATCHDOG = 'test_pgv13_uds_watchdog_is_control_not_render_authority'


def run_contract(report, method):
    setup = Case.setUp

    def with_report(self):
        setup(self)
        self.mod.build = lambda root: report

    result = unittest.TestResult()
    with patch.object(Case, 'setUp', with_report):
        Case(method).run(result)
    if result.errors or result.skipped or result.testsRun != 1:
        raise AssertionError(result.errors or 'Control did not execute')
    return not result.failures


def main():
    case = Case(DOCUMENT)
    try:
        case.setUp()
        report = case.mod.build(ROOT)
    finally:
        case.doCleanups()
    assert run_contract(report, DOCUMENT)
    assert run_contract(report, WATCHDOG)
    outcomes = {}
    for name in ['missing_ipc', 'extra_thread', 'duplicate_operation',
                 'missing_ipc_effect', 'extra_effect', 'wrong_authority',
                 'wrong_target', 'watchdog_authority', 'watchdog_effect']:
        altered = copy.deepcopy(report)
        entries = altered['entries']
        ipc = next(e for e in entries if e['canonical_operation'] == 'renderer.ipc.render')
        legacy = next(e for e in entries if e['canonical_operation'].endswith(':_target via _run_with_deadline'))
        watchdog = next(e for e in entries if e['canonical_operation'] == 'renderer.ipc.deadline')
        if name == 'missing_ipc':
            entries.remove(ipc)
        elif name == 'extra_thread':
            extra = copy.deepcopy(ipc)
            extra.update(id='worker:unexpected', canonical_operation='unexpected')
            entries.append(extra)
        elif name == 'duplicate_operation':
            legacy['canonical_operation'] = ipc['canonical_operation']
        elif name == 'missing_ipc_effect':
            ipc['effects'] = ['thread_dispatch']
        elif name == 'extra_effect':
            legacy['effects'].append('private_renderer_request')
        elif name == 'wrong_authority':
            ipc['policy'] = 'renderer.ipc'
        elif name == 'wrong_target':
            ipc['path'] = 'other'
        elif name == 'watchdog_authority':
            watchdog['policy'] = 'worker.authority'
        elif name == 'watchdog_effect':
            watchdog['effects'] = ['thread_dispatch']
        method = WATCHDOG if name.startswith('watchdog_') else DOCUMENT
        outcomes[name] = not run_contract(altered, method)
    print(json.dumps({'positive_controls': 2, 'mutations_rejected': outcomes}, indent=2))
    assert all(outcomes.values()), 'Worker contract accepted a mutated boundary'


if __name__ == '__main__':
    main()
