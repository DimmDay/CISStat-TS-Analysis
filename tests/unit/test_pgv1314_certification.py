"""Independent receipt/coverage controls; synthetic context is not VM evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import io
from unittest.mock import patch
from types import SimpleNamespace

from scripts.pgv1314cert import verify as C
from scripts.pgv14.client import CASES
from tests.unit.test_pgv13_release import manifest


def native_context():
    m=manifest()
    checks=('full_durable_content','queued_http','managed_worker','ready_http','download_digest','repeat_download',
            'queued_idempotency','ready_idempotency','foreign_job_404','foreign_download_404','anonymous_denied','download_headers','download_audit')
    report={'schema_version':'pgv13.documents/2','automated_passed':True,'image_revision':m['revision'],
            'image_tree':m['tree'],'images':copy.deepcopy(m['images']),'renderer_project':m['candidate_project'],
            'volume':m['candidate_volume'],'renderer_container_id':'candidate-new','cases':[],
            'compiled_renderer_sha256':dict.fromkeys(C.COMPILED_FILES,'1'*64),
            'negative_controls':dict.fromkeys(('foreign_create_404','missing_single_409','panel_single_409','csrf_required'),True),
            'backend_proof':{'scientific_session_rows':0,'completed_workers':11,'held_reservations':0,
                'registry_types':['PostgresResearchRunStore','PostgresArtifactRegistry','PostgresSnapshotRegistry','PostgresDocumentRegistry']}}
    for plan in CASES:
        text,numbers,counts=C.expected_case(plan)
        report['cases'].append({**plan,'checks':dict.fromkeys(checks,True),'expected_text':text,'expected_numbers':numbers,'expected_counts':counts})
    live={'images':copy.deepcopy(m['images']),'volume':m['volume'],'renderer_container_id':'production-new',
          'markers_verified':True,'api_ipc_readonly':True,'renderer_hardening':True}
    extra={'passed':True,'cleanup_passed':True,'checks':{
        'page_cap':{'passed':True,'code':'export_too_large','retryable':False,'http_status':413,'retryable_header':'false'},
        'oversized_atom':{'passed':True,'code':'render_content_overflow','retryable':False,'http_status':413,'retryable_header':'false'}},
        'image_id':m['images']['api'],'renderer_image_id':m['images']['print-renderer'],
        'volume':m['candidate_volume'],'renderer_container_id':'candidate-new'}
    row={'parent_hardening':True,'tcp_closed':True,'uid':10001,'gid':10001,'mode':0o660,'directory_mode':0o750,
         'pids_max':512,'memory_max':2147483648,'pids_events':{'max':0},'memory_events':{'oom':0,'oom_kill':0}}
    extra.update(before=copy.deepcopy(row),after=copy.deepcopy(row),source_sha256=C.sha((C.ROOT/'scripts/pgv1314cert/extra_client.py').read_bytes().replace(b'\r\n',b'\n')))
    return m,report,live,extra


class CertificationTests(unittest.TestCase):
    def test_valid_context_is_task_scoped(self):
        C.validate_context(*native_context())

    def test_old_capture_is_not_native_evidence(self):
        m,r,l,e=native_context()
        with self.assertRaises(ValueError):C.validate_context(m,{'captured':True,'pgv13_certified':False},l,e)

    def test_missing_case_duplicate_case_and_missing_worker_checks_fail(self):
        for kind in ('missing','duplicate','worker'):
            m,r,l,e=native_context()
            if kind=='missing':r['cases'].pop()
            if kind=='duplicate':r['cases'][-1]=r['cases'][0]
            if kind=='worker':r['cases'][0]['checks']['managed_worker']=False
            with self.subTest(kind=kind),self.assertRaises(ValueError):C.validate_context(m,r,l,e)

    def test_foreign_image_revision_volume_and_compiled_substitution_fail(self):
        for kind in ('image','revision','volume','compiled','live-api','live-web'):
            m,r,l,e=native_context()
            if kind=='image':r['images']['api']='sha256:'+'f'*64
            if kind=='revision':r['image_revision']='0'*40
            if kind=='volume':r['volume']=m['volume']
            if kind=='compiled':r['compiled_renderer_sha256']['wrong.js']=r['compiled_renderer_sha256'].pop(C.COMPILED_FILES[0])
            if kind=='live-api':l['images']['api']='sha256:'+'e'*64
            if kind=='live-web':l['images']['web']='sha256:'+'e'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):C.validate_context(m,r,l,e)

    def test_weakening_document_ocr_expectations_is_not_allowed(self):
        for field in ('expected_text','expected_numbers','expected_counts'):
            m,r,l,e=native_context();r['cases'][4][field]=[] if field!='expected_counts' else {'x':0}
            with self.subTest(field=field),self.assertRaises(ValueError):C.validate_context(m,r,l,e)

    def test_limits_need_exact_terminal_error_and_same_candidate(self):
        for kind in ('wrong-code','retryable','missing','cleanup','foreign'):
            m,r,l,e=native_context()
            if kind=='wrong-code':e['checks']['page_cap']['code']='payload_too_large'
            if kind=='retryable':e['checks']['page_cap']['retryable']=True
            if kind=='missing':e['checks'].pop('oversized_atom')
            if kind=='cleanup':e['cleanup_passed']=False
            if kind=='foreign':e['renderer_container_id']='other'
            with self.subTest(kind=kind),self.assertRaises(ValueError):C.validate_context(m,r,l,e)

    def test_scientific_session_and_remaining_holds_fail(self):
        for key in ('scientific_session_rows','held_reservations'):
            m,r,l,e=native_context();r['backend_proof'][key]=1
            with self.subTest(key=key),self.assertRaises(ValueError):C.validate_context(m,r,l,e)

    def test_changed_runtime_cannot_reuse_prebuilt_images(self):
        C.assert_host_only_changes(['docs/new.md','scripts/pgv1314cert/verify.py','tests/unit/one.py'])
        for path in ('apps/api/main.py','app/data/db_connectors.py','apps/standalone/Dockerfile','scripts/auth05/manage.py'):
            with self.subTest(path=path),self.assertRaises(ValueError):C.assert_host_only_changes([path])

    def test_delivery_manifest_is_host_only_after_docs_commit(self):
        """A docs/cert commit may ship the root delivery manifest; runtime bytes cannot."""
        C.assert_host_only_changes(['files.txt'])
        C.assert_host_only_changes(['files.txt','AGENTS.md','worklog/worklog12.md','docs/pgv1314_cert_vm_2026-11-24.md'])
        for path in ('package.json','apps/api/Dockerfile','app/core/passport/session.py'):
            with self.subTest(path=path),self.assertRaises(ValueError):C.assert_host_only_changes([path])

    def test_strict_junit_rejects_skips_xfail_missing_duplicates_and_substitutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tests.xml';expected=['suite::one','suite::two']
            body='<testcase classname="suite" name="one"/><testcase classname="suite" name="two"/>'
            path.write_text('<testsuite>'+body+'</testsuite>',encoding='utf-8');C.validate_junit(path,expected)
            for bad in (body.replace('/>','><skipped/></testcase>',1),body.replace('two','one'),body.replace('two','foreign'),body.split('<testcase')[0],body.replace('/>','><failure/></testcase>',1)):
                path.write_text('<testsuite>'+bad+'</testsuite>',encoding='utf-8')
                with self.assertRaises(ValueError):C.validate_junit(path,expected)

    def test_jest_rejects_pending_empty_wrong_selection_and_zero_exit_lie(self):
        expected=[['one.test.ts','group one']]
        data={'success':True,'numTotalTests':1,'numPassedTests':1,'numFailedTests':0,'numPendingTests':0,'numTodoTests':0,
              'testResults':[{'name':str(C.ROOT/'one.test.ts'),'status':'passed','assertionResults':[{'fullName':'group one','status':'passed'}]}]}
        C.validate_jest(data,expected)
        portable=copy.deepcopy(data);portable['testResults'][0]['name']='one.test.ts';C.validate_jest(portable,expected)
        for kind in ('pending','missing','foreign','success'):
            bad=copy.deepcopy(data)
            if kind=='pending':bad['testResults'][0]['assertionResults'][0]['status']='pending'
            if kind=='missing':bad['testResults']=[]
            if kind=='foreign':bad['testResults'][0]['assertionResults'][0]['fullName']='other'
            if kind=='success':bad['success']=False
            with self.subTest(kind=kind),self.assertRaises(ValueError):C.validate_jest(bad,expected)

    def test_jest_mismatch_names_the_case_delta_and_counts(self):
        data={'success':True,'numTotalTests':2,'numPassedTests':2,
              'testResults':[{'name':'one.test.ts','status':'passed','assertionResults':[
                  {'fullName':'original','status':'passed'}, {'fullName':'new SSR case','status':'passed'}]}]}
        with self.assertRaises(ValueError) as error:C.validate_jest(data,[['one.test.ts','original']])
        message=str(error.exception)
        for value in ('expected=1','total=2','passed=2','observed=2','missing=0','unexpected=1','new SSR case'):
            self.assertIn(value,message)

    def test_jest_exact_multiset_remains_required_with_duplicate_parameter_titles(self):
        expected=[['one.test.ts','same'],['one.test.ts','same'],['one.test.ts','different']]
        data={'success':True,'numTotalTests':3,'numPassedTests':3,
              'testResults':[{'name':'one.test.ts','status':'passed','assertionResults':[
                  {'fullName':name,'status':'passed'} for name in ('different','same','same')]}]}
        self.assertEqual(C.validate_jest(data,expected),3)
        for kind in ('removed','substituted','extra','count_lie','skip'):
            bad=copy.deepcopy(data)
            rows=bad['testResults'][0]['assertionResults']
            if kind=='removed':rows.pop();bad.update(numTotalTests=2,numPassedTests=2)
            if kind=='substituted':rows[-1]['fullName']='different'
            if kind=='extra':rows.append({'fullName':'extra','status':'passed'});bad.update(numTotalTests=4,numPassedTests=4)
            if kind=='count_lie':bad['numTotalTests']=4
            if kind=='skip':rows[-1]['status']='pending'
            with self.subTest(kind=kind),self.assertRaises(ValueError):C.validate_jest(bad,expected)

    def test_evidence_paths_are_confined_and_hashes_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').write_bytes(b'one');good={'data':hashlib.sha256(b'one').hexdigest()}
            C.validate_files(root,good)
            for bad in ({'../outside':'0'*64},{'/etc/passwd':'0'*64},{'data':'0'*64},{}):
                with self.assertRaises(ValueError):C.validate_files(root,bad)
            with patch.object(Path,'is_symlink',return_value=True),self.assertRaises(ValueError):C.validate_files(root,good)

    def test_native_refusal_harness_rejects_wrong_http_code_retryability_and_png_success(self):
        from scripts.pgv1314cert import extra_client
        from apps.api.png_renderer_client import PngRendererClient
        payload={'sections':[{'kind':'passport_record','record':{'passport':{}}}]}
        def response(*args,**kwargs):
            p=json.loads(args[2]);code='export_too_large' if len(p['sections'])==21 else 'render_content_overflow'
            raise urllib.error.HTTPError('http://private/v1/render',413,'refused',{'X-Render-Retryable':'false'},io.BytesIO(json.dumps({'error':{'code':code,'retryable':False}}).encode()))
        with patch.object(PngRendererClient,'_unix_request',side_effect=response):
            self.assertTrue(extra_client.run({'payload':payload,'socket':'/private'})['passed'])
        for kind in ('wrong-code','retryable','png'):
            def bad(*args,**kwargs):
                if kind=='png':return b'not an expected refusal'
                raise urllib.error.HTTPError('http://private/v1/render',413,'refused',{'X-Render-Retryable':'true'},io.BytesIO(json.dumps({'error':{'code':'payload_too_large' if kind=='wrong-code' else 'export_too_large','retryable':True}}).encode()))
            with self.subTest(kind=kind),patch.object(PngRendererClient,'_unix_request',side_effect=bad),self.assertRaises(extra_client.AcceptanceFailure):extra_client.run({'payload':payload,'socket':'/private'})

    def test_native_metrics_mutant_is_rejected(self):
        m,r,l,e=native_context();e['after']['memory_events']['oom_kill']=1
        with self.assertRaises(ValueError):C.validate_context(m,r,l,e)

    def test_resume_prints_the_existing_capture_chain_without_executing_apply(self):
        from scripts.pgv1314cert import resume
        with tempfile.TemporaryDirectory() as tmp:
            b=Path(tmp);m=manifest()
            def command(args,**kwargs):return b'' if 'status' in args else 'a'*40
            with patch.object(resume.R,'bundle_load',return_value=(b,m)),patch.object(resume.R,'load_baseline',return_value={'renderer_project':'deployment','stack_project':'cisstat-stack'}),patch.object(resume,'image_equivalence',return_value=[]),patch.object(resume.subprocess,'check_output',side_effect=command) as commands:
                plan=resume.plan_release(b)
                self.assertIn('git switch --detach',plan);self.assertIn('pgv1314_apply_after_drain()',plan)
                self.assertIn('candidate-recreated.json',plan);self.assertNotIn(' capture --bundle',plan);self.assertNotIn('source "$PGV13_BUNDLE/pins.env"',plan)
                self.assertTrue(all(c.args[0][0]=='git' for c in commands.call_args_list))
                (b/'ab.json').write_text('{}',encoding='utf-8')
                with self.assertRaises(ValueError):resume.plan_release(b)

    def test_task_flags_cannot_be_issued_without_native_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=SimpleNamespace(bundle=root/'missing',out=root/'certificate.json',local=root/'local.json',report=root/'report.json',review=root/'review.json')
            with self.assertRaises((ValueError,OSError)):C.issue(args)
            self.assertFalse(args.out.exists())

    def test_issue_revalidates_pages_and_writes_an_immutable_scoped_certificate(self):
        from scripts.pgv1314cert import local,vm
        m,report,live,extra=native_context()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);local_path=root/'local.json';local_path.write_text('{}',encoding='utf-8')
            for case in report['cases']:
                count=3 if case['kind']=='set' else 1
                case['pages']=[{'png':case['id']+f'-page-{i+1:03}.png'} for i in range(count)];case['delivery_format']='zip' if count>1 else 'png';case['download']=case['id']+'.'+case['delivery_format']
                kind='passport_comparison' if case['kind'].startswith('compare') else 'passport_record'
                (root/(case['id']+'.payload.json')).write_text(json.dumps({'sections':[{'kind':kind} for _ in range(count)]}),encoding='utf-8')
            (root/'report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
            (root/'page-budgets.json').write_text(json.dumps(extra),encoding='utf-8')
            (root/'review.json').write_text('{}',encoding='utf-8')
            for name in vm.native_evidence_files(report):
                if not (root/name).exists():(root/name).write_bytes(b'controlled evidence')
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.name in vm.native_evidence_files(report)}
            source={'unit.py':'0'*64};release={'manifest.json':'1'*64}
            (root/'bindings.json').write_text(json.dumps({'schema_version':'pgv1314.native_bindings/1','local_sha256':hashlib.sha256(local_path.read_bytes()).hexdigest(),
                'report_sha256':hashes['report.json'],'release_hashes':release,'source_fingerprints':source,'files':hashes}),encoding='utf-8')
            args=SimpleNamespace(bundle=root,local=local_path,report=root/'report.json',review=root/'review.json',out=root/'certificate.json')
            with patch.object(local,'validate_local',return_value={'checks':{'controlled_unit':{'exit':0}}}), \
                 patch.object(vm,'validate_release',return_value=(root,m,release)), \
                 patch.object(vm,'observe_live',return_value=live),patch.object(C.R,'load_baseline',return_value={}), \
                 patch.object(C,'image_equivalence',return_value=[]),patch.object(C,'source_fingerprints',return_value=source), \
                 patch.object(C.A,'validate_acceptance',side_effect=ValueError('last-page failed')) as validate:
                with self.assertRaises(ValueError):C.issue(args)
                self.assertFalse(args.out.exists())
                validate.side_effect=None;validate.return_value={'p01_p02_accepted':True,'reviewer':'controlled unit operator'}
                self.assertEqual(C.issue(args),0)
                validate.assert_called_with(args.report,args.review,page_sets=True)
                cert=json.loads(args.out.read_text(encoding='utf-8'))
                self.assertEqual(cert['task_certification'],{'PGV-13':True,'PGV-14':True})
                self.assertFalse(cert['full_pgv_certified']);self.assertEqual(cert['case_count'],11)
                with self.assertRaises(ValueError):C.issue(args)

    def test_expectations_preserve_known_numeric_and_reused_oracles(self):
        self.assertEqual(C.expected_case(CASES[4])[1],['7','100'])
        self.assertEqual(C.expected_case(CASES[3])[2],{'БЕРЁЗА':3})
        self.assertIn('corrupt',C.expected_case(CASES[9])[0])

if __name__=='__main__':unittest.main()
