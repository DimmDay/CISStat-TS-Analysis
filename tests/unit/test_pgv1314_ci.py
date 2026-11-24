"""CI/local parity, diagnostic visibility and artifact path regression controls."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

from scripts.pgv1314cert import local as L
from scripts.pgv1314cert.cifix import verify_ci_local as D

ROOT=Path(__file__).resolve().parents[2]


def route_stream_probe(route_exit=0, dirty_stdout=False):
    """Exercise runner I/O with controlled commands and the real strict JSON reader."""
    with tempfile.TemporaryDirectory() as tmp:
        project=Path(tmp)/'repo';project.mkdir();out=Path(tmp)/'evidence'
        route={'status':'ok','added':[],'missing':[]}
        def command(cmd,**kwargs):
            output=next((p.split('=',1)[1] for p in cmd if p.startswith('--outputFile=')),None)
            if output:Path(output).write_text('{"testResults":[]}',encoding='utf-8')
            if 'scripts/auth06/check_routes.py' in cmd:
                kwargs['stdout'].write(('unexpected stdout\n' if dirty_stdout else '')+json.dumps(route)+'\n')
                target=kwargs['stdout'] if kwargs['stderr']==subprocess.STDOUT else kwargs['stderr']
                target.write('DEBUG:tzlocal:Looking up time zone info from registry\n')
                if route_exit:target.write('Error: route collector failed\n')
                return subprocess.CompletedProcess(cmd,route_exit)
            kwargs['stdout'].write('controlled command\n')
            return subprocess.CompletedProcess(cmd,0)
        def validate(path):
            actual=L.read(Path(path).parent/'routes.log')
            L.require(actual==route,'Wrong controlled route result')
        capture=io.StringIO()
        with patch.object(L,'ROOT',project),patch.object(L,'source_fingerprints',return_value={}),patch.object(L.shutil,'which',return_value='/mock/npm'),patch.object(L.subprocess,'run',side_effect=command),patch.object(L,'validate_local',side_effect=validate),contextlib.redirect_stdout(capture):
            code=L.run_local(out)
        files={p.name:p.read_bytes() for p in out.iterdir()}
        return code,json.loads(files['summary.json']),files,capture.getvalue()


class CIParityTests(unittest.TestCase):
    def test_route_stderr_is_separate_hashed_evidence_and_stdout_is_strict_json(self):
        code,report,files,_=route_stream_probe()
        self.assertEqual(code,0);self.assertTrue(report['passed'])
        self.assertEqual(json.loads(files['routes.log'])['status'],'ok')
        self.assertIn(b'DEBUG:tzlocal:',files['routes.stderr.log'])
        self.assertEqual(report['files']['routes.stderr.log'],L.sha(files['routes.stderr.log']))
        self.assertFalse(any(report['task_certification'].values()))

    def test_route_failure_keeps_stderr_diagnostics_and_nonzero_exit(self):
        code,report,files,console=route_stream_probe(route_exit=1)
        self.assertEqual(code,1);self.assertFalse(report['passed'])
        self.assertEqual(report['failed_check'],'routes')
        self.assertIn('route collector failed',console)
        self.assertTrue(report['failed_stderr_log'].endswith('routes.stderr.log'))
        self.assertIn(b'route collector failed',files['routes.stderr.log'])
        self.assertFalse(any(report['task_certification'].values()))

    def test_route_stdout_noise_is_still_rejected_even_with_valid_json_last(self):
        code,report,_,_=route_stream_probe(dirty_stdout=True)
        self.assertEqual(code,1);self.assertFalse(report['passed'])
        self.assertEqual(report['failed_check'],'evidence_validation')
        self.assertEqual(report['error_type'],'JSONDecodeError')
        self.assertFalse(any(report['task_certification'].values()))

    def test_workflow_uses_one_absolute_runner_temp_path_for_run_and_upload(self):
        job=yaml.safe_load((ROOT/'.github/workflows/pgv1314cert.yml').read_text(encoding='utf-8'))['jobs']['local-evidence']
        self.assertNotIn('runner.',str(job.get('env',{})))
        run=next(s for s in job['steps'] if s.get('id')=='local')
        value=run['env']['PGV1314_LOCAL_OUT']
        self.assertEqual(value,'${{ runner.temp }}/pgv1314-local')
        upload=next(s for s in job['steps'] if s.get('uses')=='actions/upload-artifact@v6')
        self.assertEqual(upload['with']['path'],value)
        self.assertIn('always()',upload['if']);self.assertEqual(upload['with']['if-no-files-found'],'error')
        run=next(s for s in job['steps'] if s.get('id')=='local')
        self.assertIn('scripts/pgv1314cert/cifix/verify_ci_local.py',run['run'])
        self.assertIn('$PGV1314_LOCAL_OUT',run['run'])

    def test_default_gate_runs_full_ci_pipeline_and_has_its_dependencies(self):
        from scripts import local_gates
        gate=next(g for g in local_gates.GATES if g[0]=='pgv1314cert')
        self.assertTrue(any('scripts/pgv1314cert/cifix/verify_ci_local.py' in c for c in gate[3]))
        self.assertTrue(any('apps/api/requirements.txt' in c and 'scripts/pgv1314cert/requirements.txt' in c for c in gate[3]))

    def test_driver_rejects_wrong_node_major_before_claiming_parity(self):
        with patch.object(D.subprocess,'check_output',return_value='v24.22.3\n'),patch.object(D,'run_local') as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(D.main([]),2);run.assert_not_called()

    def test_driver_runs_same_pipeline_outside_checkout_and_keeps_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp);project=parent/'project';project.mkdir();seen=[]
            def failed(out):
                seen.append(out);out.mkdir();(out/'summary.json').write_text('{"state":"FAIL"}',encoding='utf-8');return 1
            with patch.object(D,'ROOT',project),patch.object(D.subprocess,'check_output',return_value='v22.23.5\n'),patch.object(D,'run_local',side_effect=failed),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(D.main([]),1)
            self.assertEqual(len(seen),1);self.assertFalse(seen[0].is_relative_to(project))
            self.assertTrue((seen[0]/'summary.json').exists())

    def test_diagnostics_show_reason_but_redact_credentials_and_bound_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'build.log';text='prefix\n'*90+'Error: next/font failed\nhttps://user:PASSWORD@proxy.example\ntoken=SECRET\n'
            path.write_text(text,encoding='utf-8');before=path.read_bytes();tail=L.diagnostic_tail(path,limit=8)
            self.assertIn('next/font failed',tail);self.assertNotIn('PASSWORD',tail);self.assertNotIn('SECRET',tail)
            self.assertLessEqual(len(tail.splitlines()),8);self.assertEqual(path.read_bytes(),before)

    def test_web_build_error_is_visible_and_cannot_become_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'repo';project.mkdir();out=Path(tmp)/'evidence'
            def command(cmd,**kwargs):
                output=next((p.split('=',1)[1] for p in cmd if p.startswith('--outputFile=')),None)
                if output:Path(output).write_text('{"testResults":[]}',encoding='utf-8')
                code=1 if 'build:all' in cmd else 0
                kwargs['stdout'].write('Error: compiler failed\n' if code else 'controlled command\n')
                return subprocess.CompletedProcess(cmd,code)
            capture=io.StringIO()
            with patch.object(L,'ROOT',project),patch.object(L,'source_fingerprints',return_value={'test':'0'*64}),patch.object(L.shutil,'which',return_value='/mock/npm'),patch.object(L.subprocess,'run',side_effect=command),contextlib.redirect_stdout(capture):
                self.assertEqual(L.run_local(out),1)
            r=json.loads((out/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(r['state'],'FAIL');self.assertEqual(r['failed_check'],'web_builds')
            self.assertIn('compiler failed',capture.getvalue());self.assertIn('web_builds.log',capture.getvalue())
            self.assertFalse(any(r['task_certification'].values()))

    def test_timeout_has_a_stage_and_diagnostic_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'repo';project.mkdir();out=Path(tmp)/'evidence'
            def command(cmd,**kwargs):
                kwargs['stdout'].write('partial before timeout\n');raise subprocess.TimeoutExpired(cmd,900)
            with patch.object(L,'ROOT',project),patch.object(L,'source_fingerprints',return_value={}),patch.object(L.shutil,'which',return_value='/mock/npm'),patch.object(L.subprocess,'run',side_effect=command),contextlib.redirect_stdout(io.StringIO()) as capture:
                self.assertEqual(L.run_local(out),1)
            r=json.loads((out/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(r['failed_check'],'workspace_dependencies');self.assertIn('partial before timeout',capture.getvalue())
            self.assertFalse(r['passed'])

    def test_node22_driver_preserves_an_explicit_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'chosen'
            with patch.object(D.subprocess,'check_output',return_value='v22.23.5\n'),patch.object(D,'run_local',return_value=0) as run,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(D.main(['--out',str(out)]),0)
            run.assert_called_once_with(out.resolve())

if __name__=='__main__':unittest.main()
