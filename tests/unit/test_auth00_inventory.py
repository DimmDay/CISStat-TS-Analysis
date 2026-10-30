"""AUTH-00: discovery and drift checks use source fixtures, no API imports."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/auth00/inventory.py"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), "AUTH-00 inventory collector is missing")
        spec = importlib.util.spec_from_file_location("auth00_inventory", MODULE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def api(self, body, router='router = APIRouter()\n'):
        self.put("apps/api/main.py", 'from fastapi import FastAPI\nfrom apps.api.routers import demo\napp = FastAPI()\napp.include_router(demo.router, prefix="/v1/a")\n')
        self.put("apps/api/routers/demo.py", "from fastapi import APIRouter, Depends\n" + router + body)

    def test_method_path_prefix_and_dependencies(self):
        self.api('@router.post("/work", dependencies=[Depends(gate)])\ndef work(): pass\n', 'router = APIRouter(prefix="/nested", dependencies=[Depends(key)])\n')
        routes = self.mod.api_routes(self.root)
        route = next(x for x in routes if x['path'] == '/v1/a/nested/work')
        self.assertEqual(route['method'], 'POST')
        self.assertIn('key', route['dependencies'])
        self.assertIn('gate', route['dependencies'])

    def test_factory_expands_both_mounts_without_losing_key_gate(self):
        self.api('def register(r):\n @r.post("/probe")\n def probe(): pass\nregister(router)\nregister(public_router)\n', 'router = APIRouter()\npublic_router = APIRouter(dependencies=[Depends(key)])\n')
        with (self.root / 'apps/api/main.py').open('a') as f:
            f.write('app.include_router(demo.public_router, prefix="/v1/b")\n')
        routes = [x for x in self.mod.api_routes(self.root) if x['path'].endswith('/probe')]
        self.assertEqual([x['path'] for x in routes], ['/v1/a/probe', '/v1/b/probe'])
        self.assertEqual(routes[0]['dependencies'], [])
        self.assertEqual(routes[1]['dependencies'], ['key'])

    def test_nested_router_and_multiple_methods(self):
        self.api('sub = APIRouter()\n@sub.api_route("/x", methods=["GET", "POST"])\ndef x(): pass\nrouter.include_router(sub, prefix="/child")\n')
        routes = [x for x in self.mod.api_routes(self.root) if x['path'].endswith('/x')]
        self.assertEqual({(x['method'], x['path']) for x in routes}, {('GET', '/v1/a/child/x'), ('POST', '/v1/a/child/x')})

    def test_dynamic_path_is_not_silently_ignored(self):
        self.api('@router.get(compute_path())\ndef x(): pass\n')
        with self.assertRaises(ValueError):
            self.mod.api_routes(self.root)

    def test_trailing_slash_is_a_distinct_route(self):
        self.api('@router.get("/x/")\ndef x(): pass\n@router.get("/x")\ndef y(): pass\n')
        routes = self.mod.api_routes(self.root)
        self.assertIn('/v1/a/x/', {r['path'] for r in routes})
        self.assertIn('/v1/a/x', {r['path'] for r in routes})

    def test_utf8_bom_is_supported(self):
        self.api('@router.get("/x")\ndef x(): pass\n')
        p = self.root / 'apps/api/routers/demo.py'
        p.write_bytes(b'\xef\xbb\xbf' + p.read_bytes())
        self.assertTrue(any(r['path'] == '/v1/a/x' for r in self.mod.api_routes(self.root)))

    def test_duplicate_method_path_fails(self):
        self.api('@router.get("/x")\ndef a(): pass\n@router.get("/x")\ndef b(): pass\n')
        with self.assertRaises(ValueError):
            self.mod.api_routes(self.root)

    def test_unmounted_router_fails(self):
        self.api('lost = APIRouter()\n@lost.get("/hidden")\ndef hidden(): pass\n')
        with self.assertRaises(ValueError):
            self.mod.api_routes(self.root)

    def test_new_registration_form_requires_collector_review(self):
        self.api('router.add_api_route("/x", handler, methods=["GET"])\n')
        with self.assertRaises(ValueError):
            self.mod.api_routes(self.root)

    def test_functional_route_registration_is_not_silently_skipped(self):
        self.api('router.get("/x")(handler)\n')
        with self.assertRaises(ValueError):
            self.mod.api_routes(self.root)

    def test_binding_threat_reference_must_exist(self):
        self.snapshot_fixture()
        self.edit_review(lambda r: r['entries']['api:GET:/v1/a/x'].update(threats=['T999']))
        with self.assertRaises(ValueError):
            self.mod.build(self.root)

    def test_repository_snapshot_and_all_entries_classified(self):
        report = self.mod.build(ROOT)
        self.assertGreater(len(report['entries']), 220)
        self.mod.check(ROOT, report)
        for entry in report['entries']:
            self.assertIn(entry['policy'], report['policies'])
            self.assertTrue(entry['operation'])
            self.assertTrue(entry['evidence'])

    def test_new_route_cannot_inherit_a_generic_allow_classification(self):
        report = self.mod.build(ROOT)
        mutated = copy.deepcopy(report)
        mutated['entries'].append({'id': 'api:POST:/v1/internal/not-reviewed', 'policy': 'public'})
        with self.assertRaises(ValueError):
            self.mod.check(ROOT, mutated)

    def test_policy_drift_and_unclassified_entry_are_rejected(self):
        report = self.mod.build(ROOT)
        for mutate in [lambda r: r['entries'].pop(), lambda r: r['entries'][0].update(policy='unclassified'), lambda r: r['policies'].clear()]:
            changed = copy.deepcopy(report)
            mutate(changed)
            with self.assertRaises(ValueError):
                self.mod.check(ROOT, changed)

    def test_named_bypass_surfaces_are_present(self):
        report = self.mod.build(ROOT)
        ids = {e['id'] for e in report['entries']}
        for key in ['api:POST:/v1/internal/upload/db/test', 'api:POST:/v1/public/upload/db/test', 'api:POST:/v1/session/modeling/jobs/{job_id}/step', 'api:GET:/v1/session/tasks/causes', 'api:GET:/v1/documentation/renditions/{rendition_id}/content', 'renderer:POST:/v1/render']:
            self.assertIn(key, ids)
        self.assertTrue(any(e['kind'] == 'legacy_widget' for e in report['entries']))
        self.assertTrue(any(e['kind'] == 'worker' for e in report['entries']))
        self.assertTrue(any(e['kind'] == 'task_alias' for e in report['entries']))

    def snapshot_fixture(self):
        self.api('@router.get("/x")\ndef x(): return False\n')
        raw = self.mod.discovery(self.root)
        review = {'baseline': 'fixture', 'scope': 'source fixture', 'policies': {'fixture': {'observed': 'fixture', 'target': 'fixture', 'follow_up': [], 'threats': []}}, 'entries': {e['id']: {'policy': 'fixture', 'stage': 'platform', 'stage_namespace': 'service', 'resource': 'fixture', 'effects': ['read'], 'canonical_operation': e['operation'], 'admission': 'fixture'} for e in raw}, 'reviewed_sources': [], 'extra_surfaces': []}
        self.put('docs/auth00/policy_review.json', json.dumps(review))
        report = self.mod.build(self.root)
        self.put('docs/auth00/inventory.json', self.mod.json_text(report))
        self.put('docs/auth00/inventory.md', self.mod.markdown(report))
        return report

    def test_real_new_route_has_no_review_binding(self):
        self.snapshot_fixture()
        with (self.root / 'apps/api/routers/demo.py').open('a') as f:
            f.write('@router.post("/not-reviewed")\ndef added(): pass\n')
        with self.assertRaises(ValueError):
            self.mod.build(self.root)

    def test_guard_body_change_invalidates_snapshot(self):
        self.snapshot_fixture()
        p = self.root / 'apps/api/routers/demo.py'
        p.write_text(p.read_text().replace('return False', 'return True'))
        with self.assertRaises(ValueError):
            self.mod.check(self.root)

    def test_crlf_checkout_does_not_change_source_fingerprints(self):
        self.snapshot_fixture()
        for p in (self.root / 'apps/api').rglob('*.py'):
            p.write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))
        self.mod.check(self.root)

    def edit_review(self, fn):
        p = self.root / 'docs/auth00/policy_review.json'
        review = json.loads(p.read_text())
        fn(review)
        p.write_text(json.dumps(review))

    def test_review_cannot_overwrite_a_discovered_path(self):
        self.snapshot_fixture()
        self.edit_review(lambda r: r['entries']['api:GET:/v1/a/x'].update(path='/invented'))
        with self.assertRaises(ValueError):
            self.mod.build(self.root)

    def test_manual_extra_cannot_invent_an_http_route(self):
        self.snapshot_fixture()
        def invent(r):
            r['extra_surfaces'].append({'id': 'fake-http', 'kind': 'api', 'method': 'GET', 'path': '/fake', 'operation': 'fake', 'evidence': [{'source': 'apps/api/main.py', 'line': 1}]})
            r['entries']['fake-http'] = dict(r['entries']['api:GET:/v1/a/x'])
        self.edit_review(invent)
        with self.assertRaises(ValueError):
            self.mod.build(self.root)

    def test_policy_threat_reference_must_exist(self):
        self.snapshot_fixture()
        self.edit_review(lambda r: r['policies']['fixture'].update(threats=['T999']))
        with self.assertRaises(ValueError):
            self.mod.build(self.root)

    def test_disabled_docs_do_not_invent_framework_routes(self):
        self.api('@router.get("/x")\ndef x(): pass\n')
        p = self.root / 'apps/api/main.py'
        original = p.read_text()
        p.write_text(original.replace('FastAPI()', 'FastAPI(docs_url=None)'))
        paths = {r['path'] for r in self.mod.api_routes(self.root) if r['kind'] == 'framework'}
        self.assertEqual(paths, {'/openapi.json', '/redoc'})
        p.write_text(original.replace('FastAPI()', 'FastAPI(openapi_url=None)'))
        self.assertFalse(any(r['kind'] == 'framework' for r in self.mod.api_routes(self.root)))

    def test_foreign_asgi_root_requires_review(self):
        self.snapshot_fixture()
        self.put('apps/other/main.py', 'from fastapi import FastAPI\napp = FastAPI()\n')
        with self.assertRaises(ValueError):
            self.mod.discovery(self.root)

    def test_foreign_http_server_requires_review(self):
        self.snapshot_fixture()
        self.put('apps/other/server.ts', 'import {createServer} from "node:http";\ncreateServer(handler);\n')
        with self.assertRaises(ValueError):
            self.mod.discovery(self.root)

    def test_invalid_methods_cannot_be_split_into_characters(self):
        self.api('@router.api_route("/x", methods="GET")\ndef x(): pass\n')
        with self.assertRaises(ValueError):
            self.mod.api_routes(self.root)

    def test_pgv09_pgv10_documentation_surfaces_are_honestly_classified(self):
        report = self.mod.build(ROOT)
        by_id = {e['id']: e for e in report['entries']}
        # PGV-09: печатная ревизия -> queued PNG job; семья документа,
        # command (202 + job), тот же обработчик, что в evidence.
        renditions = by_id['api:POST:/v1/documentation/print-revisions/{print_revision_id}/renditions']
        self.assertEqual(renditions['policy'], 'document.object')
        self.assertEqual(renditions['effects'], ['command', 'possible_compute_or_persistence'])
        self.assertEqual(renditions['canonical_operation'], 'apps.api.routers.documentation:request_print_rendition')
        # PGV-10: экспорт научных визуализаций; GET -- только frozen
        # метаданные (read), POST -- 202 command с durable freeze.
        sources = by_id['api:GET:/v1/documentation/runs/{run_id}/visual-sources']
        self.assertEqual(sources['policy'], 'document.object')
        self.assertEqual(sources['effects'], ['read'])
        self.assertEqual(sources['canonical_operation'], 'apps.api.routers.documentation:list_visual_sources_route')
        export = by_id['api:POST:/v1/documentation/runs/{run_id}/visuals']
        self.assertEqual(export['policy'], 'document.object')
        self.assertEqual(export['effects'], ['command', 'possible_compute_or_persistence'])
        self.assertEqual(export['canonical_operation'], 'apps.api.routers.documentation:request_visual_export_route')
        # Реальные daemon-потоки document_render_worker.py: два старта
        # (render-deadline и фоновый loop) классифицированы как
        # worker.authority, а не списаны на generic allow.
        workers = {e['id']: e for e in report['entries'] if e['kind'] == 'worker' and 'document_render_worker' in e['id']}
        self.assertEqual(len(workers), 2, sorted(workers))
        for wid, w in sorted(workers.items()):
            self.assertEqual(w['policy'], 'worker.authority', wid)
            self.assertEqual(w['effects'], ['thread_dispatch'], wid)
            self.assertTrue(w['canonical_operation'], wid)

    def test_generic_model_jobs_are_classified_as_tuning(self):
        report = self.mod.build(ROOT)
        by_id = {e['id']: e for e in report['entries']}
        for key in ['api:POST:/v1/session/modeling/jobs/start', 'api:POST:/v1/session/modeling/jobs/{job_id}/step', 'api:GET:/v1/session/modeling/jobs/{job_id}', 'api:POST:/v1/session/modeling/jobs/{job_id}/cancel']:
            self.assertTrue(by_id[key]['canonical_operation'].startswith('modeling.tune.'), key)


if __name__ == '__main__':
    unittest.main()
