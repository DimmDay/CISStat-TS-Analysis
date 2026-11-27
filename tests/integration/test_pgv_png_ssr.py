"""Real PG upload/freeze -> Python payload -> compiled Node SSR worker."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.integration import test_pgv_png_fix as png

Deployment = png.Deployment

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('CISSTAT_AUTH_TEST_DSN'), 'disposable PostgreSQL required')
class BackendSsrBoundary(unittest.TestCase):
    def test_fresh_backend_payloads_render_without_optional_enrichment(self):
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.document_render_worker import _build_print_payload, _load_print_render_input_default
        case=png.FreshUploadPngTests('test_full_slot_is_explicit_429_and_no_second_job')
        self.addCleanup(case.doCleanups)
        case.setUp()
        with case.dep.http() as client, tempfile.TemporaryDirectory() as directory:
            _,trace=case.prepare(client)
            for endpoint in ['/v1/session/dataset/timeseries?column=value&date_column=date', '/v1/session/dataset/distribution?column=value', '/v1/session/dataset']:
                response=client.get(endpoint)
                self.assertEqual(response.status_code,200,response.text)
            svg='<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300"><path d="M0 200 L600 0"/></svg>'
            files=[]
            for view in ['upload.chart.series','upload.distribution.histogram','upload.overview.tech_table']:
                queued=Deployment.post(client,f'/v1/documentation/runs/{trace["run_id"]}/visuals',json={'view_id':view,'screen_svg':svg,'expected_context_id':trace['context_id'],'date_column':'date'})
                self.assertEqual(queued.status_code,202,queued.text)
                job=DocumentDeliveryService.create_default().registry.get_job(queued.json()['job']['job_id'])
                payload=_build_print_payload(_load_print_render_input_default(job.basis_artifact_id),job)
                self.assertNotIn('warnings',payload['snapshot'])
                file=Path(directory)/(view+'.json')
                file.write_text(json.dumps(payload),encoding='utf8')
                files.append(str(file))
                case.cancel(client,job.job_id)
            # A renderer must receive no API authority secrets, even in this oracle.
            env={key:value for key,value in os.environ.items() if key.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','TMPDIR','LANG','LC_ALL','TZ'}}
            result=subprocess.run(['node','scripts/pgv_png_ssr/verify_ssr.js',*files],cwd=ROOT,env=env,text=True,encoding='utf8',capture_output=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(len(result.stdout.splitlines()),3)
            print(result.stdout,end='')
