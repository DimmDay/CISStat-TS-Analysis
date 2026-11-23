"""Every-page review and transport controls; no browser/VM success claim."""
import copy,io,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from scripts.pgv13accept import oracles as O
from scripts.pgv14.pages import review_template

def page_native_double():
    # Controlled host orchestration fixture; real AuthSession/PG is test_native.py.
    import base64,zipfile
    from unittest.mock import patch
    from tests.unit.test_pgv13_accept import native_double
    from scripts.pgv14 import test_page_sets as P
    from PIL import Image,ImageDraw
    def png(w,h):
        image=Image.new('RGB',(w,h),'white');ImageDraw.Draw(image).rectangle((100,100,900,180),fill='black')
        out=io.BytesIO();image.save(out,format='PNG',dpi=(300,300));return out.getvalue()
    report=native_double()
    for case in report['cases']:
        payload={'request_id':'pgv:'+case['id'],'snapshot':{'print':{'profile_id':case['profile']}},'sections':[{'kind':'passport_record','record':{'snapshot_ref':'rs-unit'}}]}
        with patch.object(P,'png',png):raw=P.package(payload,2)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:metadata=z.read('metadata.json')
        case.pop('png_base64');case.update(payload=payload,delivery_format='zip',download_base64=base64.b64encode(raw).decode(),metadata_base64=base64.b64encode(metadata).decode())
    return report


class EveryPageTests(unittest.TestCase):
    def test_all_eleven_page_sets_run_and_finalize_with_exact_page_review(self):
        from tests.unit.test_pgv13_accept import RunnerTests
        runner=RunnerTests();runner.setUp()
        result=runner.run_pipeline(page_sets=True,finalize=True)
        self.assertEqual(len(result['cases']),11)
        self.assertTrue(all(len(c['pages'])==2 for c in result['cases']))

    def test_review_requires_all_pages_and_hashes_including_last_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pages=[]
            for i in range(3):
                p=root/f'page-{i+1:03}.png';p.write_bytes(b'controlled review bytes'+bytes([i]))
                pages.append({'png':p.name,'png_sha256':O.sha(p.read_bytes())})
            report={'schema_version':'pgv13.documents/2','automated_passed':True,'cases':[{'id':'case','pages':pages}]}
            path=root/'report.json';path.write_text(json.dumps(report))
            review=review_template(report);review.update(report_sha256=O.sha(path.read_bytes()),reviewer='unit operator',reviewed_at='2026-11-23T12:00:00+03:00')
            for flags in review['cases']['case']['pages'].values():flags.update(dict.fromkeys(O.REVIEW_CHECKS,True))
            self.assertTrue(O.validate_review(path,review)['p01_p02_accepted'])
            for mutation in ('missing','pending','extra'):
                bad=copy.deepcopy(review);flags=bad['cases']['case']['pages']
                if mutation=='missing':flags.pop('page-003.png')
                if mutation=='pending':flags['page-003.png']['no_clipping']=False
                if mutation=='extra':flags['extra.png']=dict.fromkeys(O.REVIEW_CHECKS,True)
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):O.validate_review(path,bad)
            (root/'page-003.png').write_bytes(b'changed last page')
            with self.assertRaisesRegex(ValueError,'changed'):O.validate_review(path,review)

    def test_renderer_limit_codes_remain_terminal_after_transport(self):
        from apps.api.png_renderer_client import PngRendererClient,RendererPageSetRefused
        from apps.api.document_render_worker import DocumentRenderWorker,TRANSIENT_ERROR_CODES
        for code in ('export_too_large','render_content_overflow'):
            error=urllib.error.HTTPError('http://127.0.0.1/v1/render',413,'refused',{},io.BytesIO(json.dumps({'error':{'code':code,'retryable':False}}).encode()))
            with patch('urllib.request.urlopen',side_effect=error),self.assertRaises(RendererPageSetRefused) as caught:
                PngRendererClient(base_url='http://127.0.0.1:8000',ipc_socket='').render_page({'options':{'page_set':True}})
            self.assertEqual(DocumentRenderWorker()._error_code(caught.exception),code)
            self.assertNotIn(code,TRANSIENT_ERROR_CODES)

    def test_new_vm_runner_cannot_use_legacy_single_page_mode(self):
        from scripts.pgv13accept import verify_vm
        with patch.object(verify_vm,'run',return_value=0) as run:
            self.assertEqual(verify_vm.main(['run','--bundle','x','--renderer-project','candidate','--postgres-image','sha256:'+'a'*64,'--out','out'],page_sets=True),0)
            self.assertTrue(run.call_args.kwargs['page_sets'])
