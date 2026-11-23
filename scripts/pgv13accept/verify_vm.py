"""Opt-in isolated P01/P02 jobs → current-image Chromium → pixels/OCR gate.

Creates only labelled temporary DB/client/network resources. No production DB,
HTTP listeners, Docker socket forwarding, image builds/pulls or service recreate.
Human visual review remains a distinct, hash-bound action.
"""
import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.pgv13accept import client as C, oracles as O
from scripts.pgv13release import release as R
from scripts.pgv13uds import verify_vm as V

LABEL = 'io.cisstat.pgv13.accept'
PRINT_ASSETS = ('config/print_schema.json','config/visual_registry.json')
API_PRINT_ASSETS = r'''
import hashlib,json,pathlib
result={'files':{},'catalogs_valid':False}
for name in ('config/print_schema.json','config/visual_registry.json'):
    p=pathlib.Path(name)
    result['files'][name]={'present':p.is_file()}
    if p.is_file():result['files'][name]['sha256']=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
try:
    from apps.api.print_schema import load_print_schema,load_visual_registry,profile_pixel_consistency
    s=load_print_schema();r=load_visual_registry()
    result['catalogs_valid']=(s['schema_version']=='pgv.print_schema/1' and r['schema_version']=='pgv.visual_registry/1'
        and {p['id'] for p in s['profiles']}=={'figure-landscape','a4-landscape','a4-portrait'}
        and all(profile_pixel_consistency(p) for p in s['profiles']))
except Exception as e:
    result['error_type']=type(e).__name__
print(json.dumps(result))
'''
BOOTSTRAP = r'''
import json,sys
envelope=json.load(sys.stdin)
scope={'__name__':'pgv13_accept_native'}
exec(compile(envelope['source'],'<pgv13-native-client>','exec'),scope)
try:
    result=scope['run'](envelope['config'])
except Exception as e:
    result={'passed':False,'case':scope.get('CURRENT_CASE','setup'),'error_type':type(e).__name__}
    if isinstance(e,scope['AcceptanceFailure']):result['detail']=str(e)
print(json.dumps(result,ensure_ascii=False))
sys.exit(0 if result.get('passed') is True else 1)
'''
COMPILED_HASHES = r'''
const f=require('node:fs'),h=require('node:crypto');
const root='apps/print-renderer/dist/';const files=['apps/print-renderer/src/rendererCore.js',
'apps/print-renderer/src/renderWorker.js','packages/ui/print/printPassport.js',
'packages/ui/print/printComparison.js','packages/ui/print/printLayout.js','packages/ui/print/printSchema.js'];
process.stdout.write(JSON.stringify(Object.fromEntries(files.map(p=>[p,h.createHash('sha256').update(f.readFileSync(root+p)).digest('hex')]))));
'''


def command(args, *, data=None, env=None, timeout=120, check=True, heartbeat=False):
    done=threading.Event()
    def progress():
        while not done.wait(10):
            print('PGV13 documents: native jobs still running',flush=True)
    if heartbeat:
        thread=threading.Thread(target=progress,daemon=True);thread.start()
    try:
        p = subprocess.run([str(a) for a in args],cwd=ROOT,input=data,env=env,
            capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    finally:
        done.set()
        if heartbeat:
            thread.join(timeout=1)
    if check:
        O.require(p.returncode==0,'Operator command failed: '+str(args[0])+' (output withheld; no credentials printed)')
    return p.stdout.strip() if check else p


def write(path, value):
    path = Path(path)
    tmp = path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.chmod(0o600)
    tmp.replace(path)


def image_marker(image, manifest, role):
    meta = json.loads(command(['docker','image','inspect','--format',R.IMAGE_META,image]))
    R.validate_image(meta,manifest,role)
    marker = json.loads(command(['docker','run','--rm','--pull=never','--network=none','--read-only',
        '--cap-drop=ALL','--security-opt=no-new-privileges:true','--entrypoint=cat',image,
        '/usr/local/share/cisstat/build.json']))
    O.require(marker=={'revision':manifest['revision'],'tree':manifest['tree']},'Inside-image revision marker differs')


def verify_api_print_assets(image):
    result=json.loads(command(['docker','run','--rm','--pull=never','--network=none','--read-only',
        '--cap-drop=ALL','--security-opt=no-new-privileges:true','--entrypoint','python',image,'-c',API_PRINT_ASSETS]))
    O.require(set(result.get('files',{}))==set(PRINT_ASSETS),'API print assets missing from image')
    for name in PRINT_ASSETS:
        expected=O.sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))
        row=result['files'][name]
        O.require(row.get('present') is True and row.get('sha256')==expected,'API print asset missing or differs: '+name)
    O.require(result.get('catalogs_valid') is True,'API print asset catalog validation failed')
    return result


def product_sources(revision):
    """A docs/cert commit may follow the image commit; product bytes must match."""
    paths = sorted(set(
        list((ROOT/'apps/api').rglob('*.py')) + list((ROOT/'apps/api/migrations').glob('*.sql')) +
        list((ROOT/'app/core').rglob('*.py')) + list((ROOT/'rules').rglob('*.yaml')) +
        list((ROOT/'apps/print-renderer/src').glob('*.ts')) + list((ROOT/'apps/print-renderer/src').glob('*.tsx')) +
        list((ROOT/'packages/ui/print').rglob('*.ts')) + list((ROOT/'packages/ui/print').rglob('*.tsx')) +
        list((ROOT/'packages/ui/lib').rglob('*.ts')) + list((ROOT/'packages/ui/lib').rglob('*.tsx')) +
        [ROOT/'package-lock.json',ROOT/'apps/print-renderer/tsconfig.build.json',
         ROOT/'apps/api/access_registry.v1.json',ROOT/'apps/api/requirements.txt',
         *(ROOT/name for name in PRINT_ASSETS)]))
    api = {}
    for path in paths:
        if path.name.startswith('test_') or '.test.' in path.name:
            continue
        name = path.relative_to(ROOT).as_posix()
        old = subprocess.run(['git','show',revision+':'+name],cwd=ROOT,capture_output=True,timeout=15)
        data = path.read_bytes().replace(b'\r\n',b'\n')
        O.require(old.returncode==0 and old.stdout.replace(b'\r\n',b'\n')==data,'Runtime source changed since pinned image: '+name)
        if name.startswith(('apps/api/','app/core/','rules/','config/')):
            api[name] = O.sha(data)
    return api


def check_client_result(result):
    O.require(result.get('passed') is True and result.get('backend')=='postgres','Native PostgreSQL client failed')
    expected_negatives={'foreign_create_404','missing_single_409','panel_single_409','csrf_required'}
    O.require(set(result.get('negative_controls',{}))==expected_negatives and all(v is True for v in result['negative_controls'].values()),'Native negative controls incomplete')
    proof=result.get('backend_proof',{})
    O.require(proof.get('scientific_session_rows')==0 and proof.get('completed_workers')==len(C.CASES) and
        proof.get('held_reservations')==0 and proof.get('registry_types')==['PostgresResearchRunStore','PostgresArtifactRegistry','PostgresSnapshotRegistry','PostgresDocumentRegistry'],
        'Native registry/session/terminal worker proof incomplete')
    cases = result.get('cases') or []
    O.require([c.get('id') for c in cases]==[c['id'] for c in C.CASES],'Exact native case coverage required')
    checks = {'full_durable_content','queued_http','managed_worker','ready_http','download_digest',
        'repeat_download','queued_idempotency','ready_idempotency','foreign_job_404','foreign_download_404',
        'anonymous_denied','download_headers','download_audit'}
    for case, expected in zip(cases,C.CASES):
        O.require(case.get('profile')==expected['profile'] and set(case.get('checks',{}))==checks and
                  all(v is True for v in case['checks'].values()),'Incomplete native job/download controls')


def cleanup_owned(kind,name,run_id):
    prefix = ['docker','network'] if kind=='network' else ['docker','container']
    probe = command(prefix+['inspect','--format','{{json .Labels}}' if kind=='network' else '{{json .Config.Labels}}',name],check=False)
    if probe.returncode:
        # Distinguish a missing resource from an unavailable Docker daemon.
        command(['docker','info','--format','{{.ServerVersion}}'])
        listing = command(prefix+['ls','-q'] if kind=='network' else ['docker','ps','-aq','--filter','name=^/'+name+'$'])
        if kind!='network' and not listing:
            return
        if kind=='network':
            existing=command(['docker','network','ls','--filter','name=^'+name+'$','--format','{{.Name}}'])
            if not existing:
                return
        raise ValueError('Unable to inspect temporary resource; not removing unknown ownership')
    O.require((json.loads(probe.stdout) or {}).get(LABEL)==run_id,'Refusing cleanup of unrelated resource')
    # Only these owned temporary containers: -v also removes image-declared
    # anonymous PG volumes; production IPC is a named volume and is retained.
    command(prefix+(['rm',name] if kind=='network' else ['rm','-f','-v',name]))


def run(args, *, page_sets=False):
    out = args.out.resolve()
    O.require(not out.exists() and out!=ROOT and ROOT not in out.parents,'Use a new evidence directory outside the checkout')
    out.mkdir(mode=0o700,parents=True)
    report = {'schema_version':'pgv13.documents/2' if page_sets else 'pgv13.documents/1','automated_passed':False,
        'p01_p02_accepted':False,'pgv13_certified':False,'phase':'environment','cases':[]}
    write(out/'report.json',report)
    owned = []
    run_id = uuid4().hex
    try:
        def phase(name):
            report['phase']=name;write(out/'report.json',report)
            print('PGV13 documents: '+name,flush=True)
        O.require(shutil.which('docker'),'Docker CLI required; no native acceptance ran')
        report['ocr_environment']=O.ocr_environment(args.tesseract)
        phase('reviewed_source')
        O.require(not command(['git','status','--porcelain','--untracked-files=normal']),'Acceptance requires a clean committed tool checkout')
        report['auth00_head']=command([sys.executable,'scripts/auth00/check_committed.py','--target','head'])
        report['tool_sources_sha256']={name:O.sha((ROOT/'scripts/pgv13accept'/name).read_bytes().replace(b'\r\n',b'\n'))
            for name in ('client.py','oracles.py','verify_vm.py','requirements.txt')}
        if page_sets:
            report['pgv14_tool_sources_sha256']={name:O.sha((ROOT/'scripts/pgv14'/name).read_bytes().replace(b'\r\n',b'\n')) for name in ('client.py','pages.py','verify_vm.py')}
        bundle,m = R.bundle_load(args.bundle)
        report.update(image_revision=m['revision'],image_tree=m['tree'],images=m['images'],
            tool_revision=command(['git','rev-parse','HEAD']),case_manifest_sha256=O.sha(json.dumps(C.CASES,sort_keys=True).encode()))
        phase('evidence_and_images')
        ab = json.loads((bundle/'ab.json').read_text())
        R.validate_evidence(m,ab,json.loads((bundle/'candidate-recreated.json').read_text()))
        live = json.loads((bundle/'live.json').read_text())
        O.require(live.get('passed') is True and live.get('mode')=='live-api' and live.get('image_id')==m['images']['print-renderer'] and live.get('volume')==m['volume'],'Matching successful live transport evidence required')
        for role in ('api','print-renderer'):
            image_marker(m['images'][role],m,role)
        api_sources = product_sources(m['revision'])
        report['api_source_fingerprints']=api_sources
        phase('api_print_assets')
        report['api_print_assets']=verify_api_print_assets(m['images']['api'])
        O.require(re.fullmatch(r'sha256:[a-f0-9]{64}',args.postgres_image),'Explicit immutable local PostgreSQL image ID required')
        O.require(command(['docker','image','inspect','--format','{{.Id}}',args.postgres_image])==args.postgres_image,'PostgreSQL image is unavailable locally')
        report['postgres_image_id']=args.postgres_image
        cid = command(['docker','ps','-q','--filter','label=com.docker.compose.project='+args.renderer_project,
            '--filter','label=com.docker.compose.service=print-renderer'])
        O.require(cid and '\n' not in cid,'Exactly one explicitly selected renderer required')
        meta = json.loads(command(['docker','inspect','--format',V.META,cid]))
        volume = V.validate_renderer_meta(meta)
        O.require(meta['Image']==m['images']['print-renderer'],'Renderer image differs from release')
        O.require(args.renderer_project==m['candidate_project'] and volume==m['candidate_volume'],
            'Document workload requires the dedicated release candidate, not the production renderer')
        report.update(renderer_container_id=cid,volume=volume,renderer_project=args.renderer_project)
        compiled_probe=COMPILED_HASHES.replace("'packages/ui/print/printSchema.js']","'packages/ui/print/printSchema.js','apps/print-renderer/src/pageSet.js']") if page_sets else COMPILED_HASHES
        report['compiled_renderer_sha256']=json.loads(command(['docker','exec',cid,'node','-e',compiled_probe]))
        before = json.loads(command(['docker','exec',cid,'node','-e',V.NODE_STATE]))
        report['before']=before
        phase('isolated_postgres')
        network = 'cisstat-pgv13accept-'+run_id[:12]
        db_container = network+'-db'
        api_container = network+'-api'
        db_name = 'pgv13accept_'+run_id
        password = secrets.token_hex(24)
        env = dict(os.environ,POSTGRES_PASSWORD=password,
                   CISSTAT_PGV13_ACCEPT_DSN='postgresql://postgres:'+password+'@'+db_container+':5432/'+db_name)
        owned.append(('network',network))
        command(['docker','network','create','--internal','--label',LABEL+'='+run_id,network])
        owned.append(('container',db_container))
        command(['docker','create','--pull=never','--name',db_container,'--label',LABEL+'='+run_id,'--network',network,
            '--memory=768m','--pids-limit=64','--env','POSTGRES_PASSWORD','--env','POSTGRES_DB='+db_name,
            '--env','PGDATA=/var/lib/postgresql/data/pgdata','--tmpfs','/var/lib/postgresql/data:rw,nosuid,size=512m',
            args.postgres_image],env=env)
        command(['docker','start',db_container])
        deadline=time.monotonic()+60
        while True:
            ready=command(['docker','exec',db_container,'pg_isready','-h','127.0.0.1','-U','postgres','-d',db_name],check=False)
            if ready.returncode==0:
                break
            O.require(time.monotonic()<deadline,'Isolated PostgreSQL readiness timeout')
            time.sleep(.5)
        phase('native_auth_jobs_download')
        config = {'socket':V.SOCKET,'api_sources':api_sources}
        payload = json.dumps({'source':(ROOT/('scripts/pgv14/client.py' if page_sets else 'scripts/pgv13accept/client.py')).read_text(encoding='utf-8'),'config':config})
        owned.append(('container',api_container))
        result = command(['docker','run','--rm','--name',api_container,'--label',LABEL+'='+run_id,
            '-i','--pull=never','--network',network,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true',
            '--group-add=10001','--memory=2g','--pids-limit=256','--tmpfs','/tmp:rw,nosuid,size=768m',
            '--mount','type=volume,source='+volume+',target=/run/cisstat-renderer,readonly,volume-nocopy',
            '--env','CISSTAT_PGV13_ACCEPT_DSN','--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1',
            '--entrypoint','python',m['images']['api'],'-c',BOOTSTRAP],data=payload,env=env,timeout=900,check=False,heartbeat=True)
        try:
            client_result=json.loads(result.stdout)
        except ValueError:
            raise ValueError('Native API client did not return a valid report; no success claimed') from None
        if result.returncode or client_result.get('passed') is not True:
            report['client_failure']={k:client_result[k] for k in ('case','error_type','detail') if k in client_result}
            raise ValueError('Native document acceptance failed; see client_failure')
        check_client_result(client_result)
        report['negative_controls']=client_result['negative_controls']
        report['backend_proof']=client_result['backend_proof']
        after=json.loads(command(['docker','exec',cid,'node','-e',V.NODE_STATE]))
        V.metrics_ok(before,after)
        report['after']=after
        phase('downloaded_png_pixels_and_ocr')
        failures=[]
        cards=[]
        for case in client_result['cases']:
            name=case['id']
            print('PGV13 documents OCR: '+name,flush=True)
            if page_sets:
                from scripts.pgv14.pages import process_case
                try:cards.append(process_case(case,out,args.tesseract))
                except ValueError as error:
                    case['pixel_ocr_failure']=str(error);failures.append(name)
                report['cases'].append(case)
                continue
            raw=base64.b64decode(case.pop('png_base64'),validate=True)
            png=out/(name+'.png');png.write_bytes(raw)
            case.update(png=png.name,png_sha256=O.sha(raw))
            payload=case.pop('payload')
            write(out/(name+'.payload.json'),payload)
            case['payload_sha256']=O.sha((out/(name+'.payload.json')).read_bytes())
            try:
                case['pixels']=O.check_png(raw,case['profile'])
                recognition=O.recognize_png(png,args.tesseract)
                text=recognition.pop('tsv')
                latin=recognition.pop('latin_tsv')
                case['ocr_input']=recognition
                (out/(name+'.latin.ocr.tsv')).write_text(latin,encoding='utf-8')
                case['latin_ocr_tsv_sha256']=O.sha((out/(name+'.latin.ocr.tsv')).read_bytes())
                (out/(name+'.ocr.tsv')).write_text(text,encoding='utf-8')
                case['ocr_tsv_sha256']=O.sha((out/(name+'.ocr.tsv')).read_bytes())
                case['ocr']=O.check_document_ocr(text,latin,case['expected_text'],case['expected_numbers'],O.GEOMETRY[case['profile']],case.get('expected_counts',{}))
            except ValueError as error:
                case['pixel_ocr_failure']=str(error);failures.append(name)
            report['cases'].append(case)
            cards.append('<section><h2>'+html.escape(name)+'</h2><p>Expected: '+html.escape('; '.join(case['expected_text']))+'</p><a href="'+name+'.png"><img src="'+name+'.png" style="max-width:100%;height:auto"></a></section>')
        (out/'review.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'"><title>PGV13 visual review</title><h1>Review all 11 PNGs at full size</h1>'+''.join(cards),encoding='utf-8')
        if page_sets:
            (out/'review.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'"><title>PGV14 page review</title><h1>Review EVERY page of all 11 cases</h1>'+''.join(cards),encoding='utf-8')
        report.update(automated_passed=not failures,visual_review='PENDING',phase='complete',failed_cases=failures)
        O.require(not failures,'PNG pixel/OCR checks failed for: '+', '.join(failures))
    except Exception as error:
        report.update(automated_passed=False,error_type=type(error).__name__,
            detail=str(error) if isinstance(error,ValueError) else 'Inspect local dependencies; no success claimed')
    finally:
        errors=[]
        for kind,name in reversed(owned):
            try:
                cleanup_owned(kind,name,run_id)
            except Exception:
                errors.append(name)
        report['temporary_cleanup']={'passed':not errors,'unremoved_resources':errors}
        if errors:
            report['automated_passed']=False
        write(out/'report.json',report)
    if report['automated_passed']:
        write(out/'review.template.json',{'schema_version':'pgv13.visual_review/1','report_sha256':O.sha((out/'report.json').read_bytes()),
            'reviewer':'','reviewed_at':'','cases':{c['id']:dict.fromkeys(O.REVIEW_CHECKS,False) for c in report['cases']}})
    if report['automated_passed'] and page_sets:
        from scripts.pgv14.pages import review_template
        template=review_template(report);template['report_sha256']=O.sha((out/'report.json').read_bytes());write(out/'review.template.json',template)
    print(json.dumps({k:report.get(k) for k in ('automated_passed','p01_p02_accepted','pgv13_certified','phase','detail','client_failure','failed_cases','temporary_cleanup')},ensure_ascii=False))
    return 0 if report['automated_passed'] else 2


def finalize(args, *, page_sets=False):
    report_path=args.report.resolve()
    report=json.loads(report_path.read_text())
    if page_sets:
        O.require(report.get('schema_version')=='pgv13.documents/2','PGV14 page-set report required')
        tools14={name:O.sha((ROOT/'scripts/pgv14'/name).read_bytes().replace(b'\r\n',b'\n')) for name in ('client.py','pages.py','verify_vm.py')}
        O.require(report.get('pgv14_tool_sources_sha256')==tools14,'PGV14 tools changed; rerun all pages')
    O.require(report.get('automated_passed') is True,
        'Automated pixel/OCR or native acceptance failed; inspect report detail/failed_cases before finalize')
    O.require([c['id'] for c in report.get('cases',[])]==[c['id'] for c in C.CASES],'Exact fixed case coverage required')
    O.require(report.get('temporary_cleanup',{}).get('passed') is True,'Temporary resource cleanup must pass')
    tools={name:O.sha((ROOT/'scripts/pgv13accept'/name).read_bytes().replace(b'\r\n',b'\n'))
        for name in ('client.py','oracles.py','verify_vm.py','requirements.txt')}
    O.require(report.get('tool_sources_sha256')==tools,'Acceptance tool changed; rerun automated evidence')
    assets=report.get('api_print_assets',{})
    O.require(assets.get('catalogs_valid') is True and set(assets.get('files',{}))==set(PRINT_ASSETS), 'API print assets evidence missing')
    for name in PRINT_ASSETS:
        row=assets['files'][name]
        O.require(row.get('present') is True and row.get('sha256')==report.get('api_source_fingerprints',{}).get(name), 'API print assets source/evidence differs')
    O.require(report.get('case_manifest_sha256')==O.sha(json.dumps(C.CASES,sort_keys=True).encode()),'Case manifest changed')
    O.require(set(report.get('ocr_environment',{}).get('traineddata_sha256',{}))=={'rus','eng'},'OCR language provenance missing')
    check_client_result({'passed':report.get('automated_passed'),'backend':'postgres',
        'cases':report['cases'],'negative_controls':report.get('negative_controls',{}),'backend_proof':report.get('backend_proof',{})})
    O.require(set(report.get('images',{}))=={'api','web','print-renderer'} and
        all(re.fullmatch('sha256:[a-f0-9]{64}',v) for v in report['images'].values()),'Exact release image IDs required')
    O.require(report.get('api_source_fingerprints') and len(report.get('compiled_renderer_sha256',{}))==(7 if page_sets else 6) and
        all(re.fullmatch('[a-f0-9]{64}',v) for v in report['compiled_renderer_sha256'].values()),'Native source/compiled provenance missing')
    V.metrics_ok(report['before'],report['after'])
    for case in report['cases']:
        if page_sets:
            from scripts.pgv14.pages import validate_saved_case
            validate_saved_case(case,report_path.parent)
            continue
        for suffix,key in [('.payload.json','payload_sha256'),('.ocr.tsv','ocr_tsv_sha256'),('.latin.ocr.tsv','latin_ocr_tsv_sha256')]:
            path=report_path.parent/(case['id']+suffix)
            O.require(O.sha(path.read_bytes())==case[key],'Reviewed payload/OCR evidence hash changed')
        payload=json.loads((report_path.parent/(case['id']+'.payload.json')).read_text())
        O.require(payload.get('schema_version')=='pgv.render_payload/1' and payload.get('snapshot',{}).get('print',{}).get('profile_id')==case['profile']
            and payload.get('sections'),'Raw frozen render payload evidence missing')
        O.require(case.get('pixels',{}).get('passed') is True and case.get('ocr',{}).get('passed') is True,'Pixel/OCR evidence must pass')
        O.require(case.get('ocr_input',{}).get('pipeline')==O.OCR_PIPELINE and
            case['ocr_input'].get('source_sha256')==case['png_sha256'],'OCR input/pipeline source differs')
        O.check_document_ocr((report_path.parent/(case['id']+'.ocr.tsv')).read_text(encoding='utf-8'),
            (report_path.parent/(case['id']+'.latin.ocr.tsv')).read_text(encoding='utf-8'),
            case['expected_text'],case['expected_numbers'],O.GEOMETRY[case['profile']],case.get('expected_counts',{}))
    result=O.validate_review(report_path,json.loads(args.review.read_text()))
    target=report_path.parent/'accepted.json'
    O.require(not target.exists(),'Acceptance receipt already exists; preserve immutable evidence')
    result.update(scope='P01/P02 document content, jobs/download, OCR and human visual review',
        review_sha256=O.sha(args.review.read_bytes()),images=report['images'],image_revision=report['image_revision'])
    write(target,result)
    print(json.dumps(result,ensure_ascii=False))
    return 0


def main(argv=None, *, page_sets=False):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    runp=sub.add_parser('run')
    runp.add_argument('--bundle',type=Path,required=True)
    runp.add_argument('--renderer-project',required=True)
    runp.add_argument('--postgres-image',required=True)
    runp.add_argument('--out',type=Path,required=True)
    runp.add_argument('--tesseract',default='tesseract')
    review=sub.add_parser('finalize')
    review.add_argument('--report',type=Path,required=True)
    review.add_argument('--review',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        return run(args,page_sets=True) if page_sets and args.action=='run' else finalize(args,page_sets=True) if page_sets else run(args) if args.action=='run' else finalize(args)
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
        print(json.dumps({'passed':False,'pgv13_certified':False,'error_type':type(error).__name__,
            'detail':str(error) if isinstance(error,ValueError) else 'Inspect local acceptance files/dependencies'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
