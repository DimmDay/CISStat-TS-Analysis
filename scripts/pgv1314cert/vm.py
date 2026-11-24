"""Native orchestration reuses the reviewed release/UDS/jobs/pixel pipeline."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from scripts.pgv1314cert.verify import ROOT, require, read, sha, write_new, validate_context, image_equivalence, source_fingerprints
from scripts.pgv13accept import verify_vm as A
from scripts.pgv13release import release as R
from scripts.pgv13uds import verify_vm as V


def validate_release(bundle):
    b,m=R.bundle_load(bundle);R.load_baseline(b)
    first=read(b/'candidate-first.json');again=read(b/'candidate-recreated.json');live=read(b/'live.json')
    R.validate_evidence(m,read(b/'ab.json'),again)
    require(first.get('passed') is True and first.get('mode')=='candidate-api-image','First candidate proof missing')
    require((first.get('api_image_id'),first.get('image_id'),first.get('volume'))==(m['images']['api'],m['images']['print-renderer'],m['candidate_volume']),'First candidate source differs')
    R.validate_native(first)
    require(first.get('renderer_container_id') and first['renderer_container_id']!=again.get('renderer_container_id'),'No actual candidate recreate')
    require(live.get('passed') is True and live.get('mode')=='live-api' and live.get('image_id')==m['images']['print-renderer'] and live.get('volume')==m['volume'],'Live transport proof differs')
    R.validate_native(live)
    names={'manifest.json','baseline.json','baseline-stack.json','baseline-renderer.json','ab.json','candidate-first.json','candidate-recreated.json','live.json',*m['files']}
    if (b/'baseline-seccomp.json').is_file():names.add('baseline-seccomp.json')
    return b,m,{name:sha((b/name).read_bytes()) for name in sorted(names)}


def selected_container(project,service):
    require(isinstance(project,str) and project,'Explicit recorded project required')
    cid=A.command(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service='+service])
    require(cid and '\n' not in cid,'Expected one running '+service)
    return cid


def observe_live(m,baseline):
    images={};cids={};meta={}
    for role in ('api','web','print-renderer'):
        project=baseline['renderer_project'] if role=='print-renderer' else baseline['stack_project']
        cid=selected_container(project,role);cids[role]=cid
        meta[role]=json.loads(A.command(['docker','inspect','--format',V.META,cid]));images[role]=meta[role]['Image']
        require(images[role]==m['images'][role],'Live '+role+' still uses baseline/foreign image')
        A.image_marker(images[role],m,role)
    volume=V.validate_renderer_meta(meta['print-renderer']);require(volume==m['volume'],'Live renderer volume differs')
    mounts=[p for p in meta['api']['Mounts'] if p.get('Destination')=='/run/cisstat-renderer']
    require(len(mounts)==1 and mounts[0].get('Name')==volume and mounts[0].get('RW') is False,'Live API socket mount not same/RO')
    require(meta['api']['UsernsMode']==meta['print-renderer']['UsernsMode'],'Live user namespace differs')
    return {'images':images,'volume':volume,'containers':cids,'renderer_container_id':cids['print-renderer'],
            'markers_verified':True,'api_ipc_readonly':True,'renderer_hardening':True}


def run_budgets(m,report,out):
    cid=report['renderer_container_id']
    meta=json.loads(A.command(['docker','inspect','--format',V.META,cid]))
    require(meta['Image']==m['images']['print-renderer'] and V.validate_renderer_meta(meta)==m['candidate_volume'],'Candidate changed after document run')
    before=json.loads(A.command(['docker','exec',cid,'node','-e',V.NODE_STATE]))
    source=(ROOT/'scripts/pgv1314cert/extra_client.py').read_text(encoding='utf-8')
    config={'socket':V.SOCKET,'payload':read(out/'p01-figure-landscape.payload.json')}
    run_id=uuid4().hex;name='cisstat-pgv1314-limits-'+run_id[:12];cleanup=False
    try:
        raw=A.command(['docker','run','--rm','--name',name,'--label',A.LABEL+'='+run_id,
            '-i','--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true',
            '--group-add=10001','--memory=2g','--pids-limit=256','--tmpfs','/tmp:rw,nosuid,size=768m',
            '--mount','type=volume,source='+m['candidate_volume']+',target=/run/cisstat-renderer,readonly,volume-nocopy',
            '--entrypoint','python',m['images']['api'],'-c',A.BOOTSTRAP],
            data=json.dumps({'source':source,'config':config}),timeout=180,check=False,heartbeat=True)
        require(raw.returncode==0,'Native page limit control failed (see isolated renderer logs)')
        result=json.loads(raw.stdout);require(result.get('passed') is True,'Native page limit controls failed')
    finally:
        A.cleanup_owned('container',name,run_id);cleanup=True
    after=json.loads(A.command(['docker','exec',cid,'node','-e',V.NODE_STATE]));V.metrics_ok(before,after)
    result.update(cleanup_passed=cleanup,source_sha256=sha(source.encode('utf-8')),image_id=m['images']['api'],
        renderer_image_id=m['images']['print-renderer'],volume=m['candidate_volume'],renderer_container_id=cid,before=before,after=after)
    A.write(out/'page-budgets.json',result)
    return result


def native_evidence_files(report):
    names={'report.json','page-budgets.json','review.html','review.template.json'}
    for case in report['cases']:
        names.update([case['download'],case['id']+'.payload.json',case['id']+'.metadata.json'])
        for page in case['pages']:
            stem=Path(page['png']).stem
            names.update([page['png'],stem+'.ocr.tsv',stem+'.latin.ocr.tsv'])
    return names


def run_native(args):
    from scripts.pgv1314cert.local import validate_local
    validate_local(args.local)
    b,m,_=validate_release(args.bundle);image_equivalence(m['revision'])
    observe_live(m,R.load_baseline(b))
    native=SimpleNamespace(bundle=b,renderer_project=m['candidate_project'],postgres_image=args.postgres_image,out=args.out,tesseract=args.tesseract)
    code=A.run(native,page_sets=True)
    if code:return code
    try:
        report=read(args.out/'report.json');extra=run_budgets(m,report,args.out)
        live=observe_live(m,R.load_baseline(b));validate_context(m,report,live,extra)
        _,_,hashes=validate_release(b)
        files={name:sha((args.out/name).read_bytes()) for name in sorted(native_evidence_files(report))}
        A.write(args.out/'bindings.json',{'schema_version':'pgv1314.native_bindings/1',
            'local_sha256':sha(args.local.read_bytes()),'report_sha256':sha((args.out/'report.json').read_bytes()),
            'release_hashes':hashes,'source_fingerprints':source_fingerprints(),'files':files,'observed_live':live})
        print(json.dumps({'state':'AWAITING_EVERY_PAGE_REVIEW','cases':11,'task_certification':{'PGV-13':False,'PGV-14':False}}))
        return 0
    except Exception:
        A.write(args.out/'certification-failure.json',{'state':'NOT_CERTIFIED','phase':'native_budget_or_bindings'})
        raise
