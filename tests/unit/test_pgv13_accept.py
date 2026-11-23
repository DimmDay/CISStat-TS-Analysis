"""Fail-closed document acceptance controls; fixtures never mean VM acceptance."""
import csv
import hashlib
import io
import json
import argparse
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def image_bytes(blank=False, alpha=255):
    im = Image.new('RGBA', (2480, 3508), (255, 255, 255, alpha))
    if not blank:
        ImageDraw.Draw(im).rectangle((100, 100, 900, 180), fill=(0, 0, 0, alpha))
    out = io.BytesIO()
    im.save(out, format='PNG', dpi=(300, 300))
    return out.getvalue()


def tsv(words):
    fields = ['level','page_num','block_num','par_num','line_num','word_num',
              'left','top','width','height','conf','text']
    result = io.StringIO()
    writer = csv.DictWriter(result, fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    for i, word in enumerate(words):
        writer.writerow(dict(zip(fields, [5,1,1,1,1,i+1,100+i*110,100,100,30,95,word])))
    return result.getvalue()


class OracleTests(unittest.TestCase):
    def setUp(self):
        from scripts.pgv13accept import oracles
        self.o = oracles

    def test_valid_png(self):
        result = self.o.check_png(image_bytes(), 'a4-portrait')
        self.assertTrue(result['passed'])
        self.assertGreater(result['ink_fraction'], 0)

    def test_blank_png_is_not_visual_success(self):
        with self.assertRaisesRegex(ValueError, 'blank|ink'):
            self.o.check_png(image_bytes(blank=True), 'a4-portrait')

    def test_wrong_profile(self):
        with self.assertRaisesRegex(ValueError, 'dimensions|geometry'):
            self.o.check_png(image_bytes(), 'figure-landscape')

    def test_transparent_png(self):
        with self.assertRaisesRegex(ValueError, 'opaque|alpha'):
            self.o.check_png(image_bytes(alpha=0), 'a4-portrait')

    def test_corrupt_png(self):
        data = bytearray(image_bytes())
        data[40] ^= 1
        with self.assertRaises(ValueError):
            self.o.check_png(bytes(data), 'a4-portrait')

    def test_ocr_cyrillic_and_numbers_from_pixels(self):
        result = self.o.check_ocr(tsv(['Паспорт','БЕРЕЗА','37']), ['паспорт','берёза'], ['37'], (2480,3508))
        self.assertTrue(result['passed'])

    def test_missing_group_fails_ocr(self):
        with self.assertRaisesRegex(ValueError, 'OCR'):
            self.o.check_ocr(tsv(['Паспорт']), ['Вейвлет'], [], (2480,3508))

    def test_reused_set_requires_three_visible_passport_tail_markers(self):
        with self.assertRaisesRegex(ValueError,'occurrence'):
            self.o.check_ocr(tsv(['БЕРЕЗА']),['БЕРЕЗА'],[],(2480,3508),{'БЕРЁЗА':3})
        self.assertTrue(self.o.check_ocr(tsv(['БЕРЕЗА']*3),['БЕРЕЗА'],[],(2480,3508),{'БЕРЁЗА':3})['passed'])

    def test_low_confidence_text_not_counted(self):
        with self.assertRaises(ValueError):
            self.o.check_ocr(tsv(['Паспорт']).replace('\t95\t','\t1\t'), ['Паспорт'], [], (2480,3508))

    def test_ocr_outside_image(self):
        with self.assertRaisesRegex(ValueError, 'bounds|clipp'):
            self.o.check_ocr(tsv(['Паспорт']).replace('\t100\t100\t','\t2470\t100\t'), ['Паспорт'], [], (2480,3508))

    def test_ocr_empty_or_malformed(self):
        for value in ['', 'not tsv', tsv([])]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.o.check_ocr(value, ['Паспорт'], [], (2480,3508))

    def test_missing_russian_language_is_not_skip_or_fallback(self):
        with patch.object(self.o, 'capture', return_value='List of available languages:\neng\nosd\n'):
            with self.assertRaisesRegex(ValueError, 'rus'):
                self.o.ocr_environment('tesseract')

    def test_profile_catalog_dimensions_are_exact(self):
        self.assertEqual(self.o.GEOMETRY['figure-landscape'], (2400,1500))
        self.assertEqual(self.o.GEOMETRY['a4-landscape'], (3508,2480))

    def test_review_requires_exact_report_and_images(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            folder = Path(temp)
            (folder/'one.png').write_bytes(b'controlled image bytes')
            report = {'schema_version':'pgv13.documents/1','automated_passed':True,
                      'cases':[{'id':'one','png':'one.png','png_sha256':hashlib.sha256((folder/'one.png').read_bytes()).hexdigest()}]}
            raw = json.dumps(report).encode()
            (folder/'report.json').write_bytes(raw)
            review = {'schema_version':'pgv13.visual_review/1','report_sha256':hashlib.sha256(raw).hexdigest(),
                      'reviewer':'operator','reviewed_at':'2026-11-20T14:00:00+03:00',
                      'cases':{'one':dict.fromkeys(self.o.REVIEW_CHECKS, True)}}
            self.assertTrue(self.o.validate_review(folder/'report.json', review)['p01_p02_accepted'])
            (folder/'one.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed|hash'):
                self.o.validate_review(folder/'report.json', review)

    def test_review_rejects_pending_and_missing_case(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            folder = Path(temp)
            (folder/'report.json').write_text(json.dumps({'schema_version':'pgv13.documents/1','automated_passed':True,'cases':[{'id':'one'}]}), encoding='utf-8')
            review = {'schema_version':'pgv13.visual_review/1','report_sha256':hashlib.sha256((folder/'report.json').read_bytes()).hexdigest(),
                      'reviewer':'operator','reviewed_at':'2026-11-20T14:00:00+03:00','cases':{}}
            with self.assertRaises(ValueError):
                self.o.validate_review(folder/'report.json', review)


class NativeClientContractTests(unittest.TestCase):
    def test_uniform_denial_ignores_only_correlation_not_message_or_code(self):
        from scripts.pgv13accept.client import public_error
        def response(nonce,code='not_found'):
            return SimpleNamespace(json=lambda:{'detail':{'request_id':nonce,'code':code,'message':'same'}})
        self.assertEqual(public_error(response('one')),public_error(response('two')))
        self.assertNotEqual(public_error(response('one')),public_error(response('two','different')))
        self.assertEqual(public_error(SimpleNamespace(json=lambda:{'code':'not_found','request_id':'one'})),
                         public_error(SimpleNamespace(json=lambda:{'code':'not_found','request_id':'two'})))

    def test_fixed_manifest_includes_profiles_reuse_gaps_and_comparison(self):
        from scripts.pgv13accept.client import CASES
        self.assertEqual(len(CASES), 11)
        self.assertEqual(len({c['id'] for c in CASES}), 11)
        self.assertEqual({c['profile'] for c in CASES}, {'figure-landscape','a4-landscape','a4-portrait'})
        self.assertTrue({'p01-reused','p02-reused','p01-missing','p01-corrupt','p02-missing'} <= {c['id'] for c in CASES})

    def test_production_dsn_rejected_before_any_connection(self):
        from scripts.pgv13accept.client import check_disposable_database
        with patch('psycopg.connect') as connect:
            for dsn in ['dbname=postgres','dbname=cisstat','dbname=pgv13accept_not_random']:
                with self.subTest(dsn=dsn), self.assertRaises(ValueError):
                    check_disposable_database(dsn)
            connect.assert_not_called()

    def test_foreign_runtime_source_rejected(self):
        from scripts.pgv13accept.client import check_sources
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            root = Path(temp)
            (root/'a.py').write_text('real code\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'source'):
                check_sources(root, {'a.py':'0'*64})
            check_sources(root, {'a.py':hashlib.sha256(b'real code\n').hexdigest()})


def native_double():
    from scripts.pgv13accept.client import CASES
    checks=('full_durable_content','queued_http','managed_worker','ready_http','download_digest',
        'repeat_download','queued_idempotency','ready_idempotency','foreign_job_404','foreign_download_404',
        'anonymous_denied','download_headers','download_audit')
    cases=[]
    for plan in CASES:
        from scripts.pgv13accept.oracles import GEOMETRY
        image=Image.new('RGB',GEOMETRY[plan['profile']],'white')
        ImageDraw.Draw(image).rectangle((100,100,900,180),fill='black')
        out=io.BytesIO();image.save(out,format='PNG',dpi=(300,300))
        cases.append({**plan,'checks':dict.fromkeys(checks,True),'png_base64':base64.b64encode(out.getvalue()).decode(),
            'expected_text':['Паспорт'],'expected_numbers':['37'],
            'payload':{'schema_version':'pgv.render_payload/1','snapshot':{'print':{'profile_id':plan['profile']}},'sections':[{'synthetic_test_double':True}]}})
    return {'passed':True,'backend':'postgres','cases':cases,
            'backend_proof':{'scientific_session_rows':0,'completed_workers':len(CASES),'held_reservations':0,
                'registry_types':['PostgresResearchRunStore','PostgresArtifactRegistry','PostgresSnapshotRegistry','PostgresDocumentRegistry']},
            'negative_controls':dict.fromkeys(('foreign_create_404','missing_single_409','panel_single_409','csrf_required'),True)}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        from scripts.pgv13accept import verify_vm
        self.v=verify_vm

    def test_missing_case_duplicate_and_missing_control_are_rejected(self):
        for mutation in ('missing','duplicate','flag','negative'):
            report=native_double()
            if mutation=='missing':
                report['cases'].pop()
            elif mutation=='duplicate':
                report['cases'][-1]['id']=report['cases'][0]['id']
            elif mutation=='flag':
                report['cases'][0]['checks']['download_digest']=False
            else:
                report['negative_controls'].pop('csrf_required')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.v.check_client_result(report)

    def test_bootstrap_does_not_expose_unknown_exception_detail(self):
        code="CURRENT_CASE='one'\nclass AcceptanceFailure(ValueError):pass\ndef run(config):raise RuntimeError('SECRET-DSN')"
        import subprocess, sys
        result=subprocess.run([sys.executable,'-c',self.v.BOOTSTRAP],input=json.dumps({'source':code,'config':{}}),capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertNotIn('SECRET',result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['case'],'one')

    def test_cleanup_refuses_foreign_label(self):
        with patch.object(self.v,'command',return_value=SimpleNamespace(returncode=0,stdout='{"unrelated":"x"}')) as command:
            with self.assertRaisesRegex(ValueError,'unrelated'):
                self.v.cleanup_owned('container','test','owned')
            self.assertEqual(command.call_count,1)

    def test_cleanup_removes_only_owned_container_and_its_anonymous_volumes(self):
        with patch.object(self.v,'command',side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps({self.v.LABEL:'owned'})), '']) as command:
            self.v.cleanup_owned('container','temporary','owned')
            self.assertEqual(command.call_args.args[0],['docker','container','rm','-f','-v','temporary'])

    def test_no_docker_writes_failure_not_success(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            out=Path(temp)/'evidence'
            args=argparse.Namespace(out=out)
            with patch.object(self.v.shutil,'which',return_value=None):
                self.assertEqual(self.v.run(args),2)
            report=json.loads((out/'report.json').read_text(encoding='utf-8'))
            self.assertFalse(report['automated_passed'])
            self.assertFalse(report['pgv13_certified'])
            self.assertFalse((out/'review.template.json').exists())

    def test_existing_evidence_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            target=Path(temp)
            (target/'report.json').write_text('original', encoding='utf-8')
            with self.assertRaises(ValueError):
                self.v.run(argparse.Namespace(out=target))
            self.assertEqual((target/'report.json').read_text(encoding='utf-8'),'original')

    def test_native_pipeline_writes_bound_images_and_pending_visual_review(self):
        report=self.run_pipeline()
        self.assertTrue(report['automated_passed'])
        self.assertFalse(report['p01_p02_accepted'])
        self.assertFalse(report['pgv13_certified'])
        self.assertEqual(report['visual_review'],'PENDING')
        self.assertEqual(len(report['cases']),11)

    def test_production_renderer_is_refused_before_temporary_resources(self):
        report=self.run_pipeline(project='deployment')
        self.assertFalse(report['automated_passed'])
        self.assertIn('dedicated',report['detail'])

    def test_finalize_requires_human_review_and_binds_payload_ocr(self):
        self.run_pipeline(finalize=True)

    def test_missing_image_assets_stop_before_test_postgres_is_created(self):
        report=self.run_pipeline(assets_valid=False)
        self.assertFalse(report['automated_passed'])
        self.assertEqual(report['phase'],'api_print_assets')
        self.assertIn('config/print_schema.json',report['detail'])

    def run_pipeline(self,project='candidate',finalize=False,assets_valid=True,page_sets=False):
        from contextlib import ExitStack
        m={'images':{'api':'sha256:'+'a'*64,'web':'sha256:'+'9'*64,'print-renderer':'sha256:'+'b'*64},
           'revision':'c'*40,'tree':'d'*40,'candidate_project':'candidate','candidate_volume':'candidate-volume','volume':'production-volume'}
        calls=[]
        def verify_assets(*args):
            if not assets_valid:
                raise ValueError('API print asset missing: config/print_schema.json')
            return {'catalogs_valid':True,'files':{name:{'present':True,'sha256':self.v.O.sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))} for name in self.v.PRINT_ASSETS}}
        def command(cmd,**kwargs):
            calls.append((cmd,kwargs))
            if cmd[:3]==['docker','image','inspect']:
                return 'sha256:'+'f'*64
            if cmd[:3]==['git','rev-parse','HEAD']:
                return 'e'*40
            if cmd[:3]==['docker','ps','-q']:
                return 'renderer-id'
            if cmd[:2]==['docker','inspect']:
                return json.dumps({'Image':m['images']['print-renderer']})
            if cmd[:3]==['docker','exec','renderer-id']:
                if cmd[-1]==self.v.COMPILED_HASHES or (page_sets and 'pageSet.js' in cmd[-1]):
                    return json.dumps({str(i):'1'*64 for i in range(7 if page_sets else 6)})
                return '{}'
            if 'pg_isready' in cmd:
                return SimpleNamespace(returncode=0)
            if cmd[:3]==['docker','run','--rm'] and self.v.BOOTSTRAP in cmd:
                return SimpleNamespace(returncode=0,stdout=json.dumps(__import__('tests.unit.test_pgv14_accept',fromlist=['page_native_double']).page_native_double() if page_sets else native_double()))
            return ''
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp, ExitStack() as patches:
            root=Path(temp);bundle=root/'bundle';bundle.mkdir()
            for name,value in [('ab.json',{}),('candidate-recreated.json',{}),('live.json',{'passed':True,'mode':'live-api','image_id':m['images']['print-renderer'],'volume':m['volume']})]:
                (bundle/name).write_text(json.dumps(value), encoding='utf-8')
            args=argparse.Namespace(out=root/'out',bundle=bundle,renderer_project=project,postgres_image='sha256:'+'f'*64,tesseract='tesseract')
            for obj,name,value in [(self.v,'command',command),(self.v,'image_marker',lambda *a:None),
                (self.v,'product_sources',lambda *a:{name:self.v.O.sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n')) for name in self.v.PRINT_ASSETS}),
                (self.v,'verify_api_print_assets',verify_assets),
                (self.v.R,'bundle_load',lambda *a:(bundle,m)),
                (self.v.R,'validate_evidence',lambda *a:None),(self.v.V,'validate_renderer_meta',lambda *a:m['candidate_volume']),
                (self.v.V,'metrics_ok',lambda *a:None),(self.v,'cleanup_owned',lambda *a:None),
                (self.v.O,'ocr_environment',lambda *a:{'unit_double':True,'traineddata_sha256':{'rus':'1'*64,'eng':'2'*64}}),
                (self.v.O,'capture',lambda *a,**k:tsv(['Паспорт','Источник','Стр','1','2','37'] if page_sets else ['Паспорт','37'])),(self.v.shutil,'which',lambda *a:'/docker')]:
                patches.enter_context(patch.object(obj,name,value))
            code=self.v.run(args,page_sets=True) if page_sets else self.v.run(args)
            result=json.loads((args.out/'report.json').read_text(encoding='utf-8'))
            if project=='candidate' and assets_valid:
                self.assertEqual(code,0,result)
                client_cmd=next(cmd for cmd,_ in calls if self.v.BOOTSTRAP in cmd)
                self.assertIn('--read-only',client_cmd)
                self.assertIn('--pull=never',client_cmd)
                self.assertTrue(any('readonly,volume-nocopy' in item for item in client_cmd))
                self.assertFalse(any(item.startswith('--publish') for item in client_cmd))
                self.assertTrue((args.out/'review.template.json').is_file())
                template=json.loads((args.out/'review.template.json').read_text(encoding='utf-8'))
                self.assertTrue(all(not flag for value in template['cases'].values() for flags in (value['pages'].values() if page_sets else [value]) for flag in flags.values()))
                if finalize:
                    review_path=args.out/'review.json'
                    review_path.write_text(json.dumps(template), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        self.v.finalize(SimpleNamespace(report=args.out/'report.json',review=review_path),page_sets=page_sets)
                    template.update(reviewer='unit double operator',reviewed_at='2026-11-20T15:00:00+03:00')
                    for case in template['cases'].values():
                        for flags in (case['pages'].values() if page_sets else [case]):flags.update(dict.fromkeys(flags,True))
                    review_path.write_text(json.dumps(template), encoding='utf-8')
                    self.assertEqual(self.v.finalize(SimpleNamespace(report=args.out/'report.json',review=review_path),page_sets=page_sets),0)
                    accepted=json.loads((args.out/'accepted.json').read_text(encoding='utf-8'))
                    self.assertTrue(accepted['p01_p02_accepted'])
                    self.assertFalse(accepted['pgv13_certified'])
                    (args.out/'accepted.json').unlink()
                    (args.out/(self.v.C.CASES[0]['id']+'.payload.json')).write_text('{}', encoding='utf-8')
                    with self.assertRaisesRegex(ValueError,'hash|changed'):
                        self.v.finalize(SimpleNamespace(report=args.out/'report.json',review=review_path),page_sets=page_sets)
            else:
                self.assertFalse(any(cmd[:3]==['docker','network','create'] for cmd,_ in calls))
            return result


if __name__ == '__main__':
    unittest.main()
