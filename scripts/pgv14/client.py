"""Disposable-PostgreSQL native jobs client, executed in the pinned API image.

Only own generated accounts/runs. No identity overrides, fixture imports,
patched authority, payload padding, scientific capture or production DSN.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

CASES = [
    *[{'id':'p01-'+p,'kind':'single','profile':p} for p in ('figure-landscape','a4-landscape','a4-portrait')],
    {'id':'p01-reused','kind':'set','profile':'a4-portrait'},
    *[{'id':'p02-'+p,'kind':'compare','profile':p} for p in ('figure-landscape','a4-landscape','a4-portrait')],
    {'id':'p02-reused','kind':'compare-reused','profile':'a4-portrait'},
    {'id':'p01-missing','kind':'missing','profile':'a4-portrait'},
    {'id':'p01-corrupt','kind':'corrupt','profile':'a4-portrait'},
    {'id':'p02-missing','kind':'compare-missing','profile':'a4-portrait'},
]
GROUPS = ['Базовые статистики','Частота ряда','Стационарность','Детерминированность',
          'Автокорреляция','Тренд','Сезонность','seasonal_periods','FFT','Вейвлет']
ORIGIN = 'https://pgv13-accept.example'
CURRENT_CASE = 'setup'


class AcceptanceFailure(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise AcceptanceFailure(message)


def check_sources(root, expected):
    require(expected, 'Product source hashes required')
    for name,digest in expected.items():
        path = (Path(root)/name).resolve()
        require(path.is_relative_to(Path(root).resolve()), 'Unsafe source path')
        require(path.is_file() and hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest() == digest, 'Product source differs: '+name)


def public_error(response):
    """Compare the whole public denial DTO except its per-request correlation ID."""
    body={k:v for k,v in response.json().items() if k!='request_id'}
    if isinstance(body.get('detail'),dict):
        body={**body,'detail':{k:v for k,v in body['detail'].items() if k!='request_id'}}
    return body


def check_disposable_database(dsn):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    name = conninfo_to_dict(dsn).get('dbname','')
    require(re.fullmatch(r'pgv13accept_[a-f0-9]{32}', name), 'Dedicated randomly named disposable database required')
    with psycopg.connect(dsn) as c:
        require(c.execute('SELECT current_database()').fetchone()[0] == name, 'Disposable database mismatch')
        require(not c.execute("SELECT 1 FROM pg_tables WHERE schemaname='public' LIMIT 1").fetchone(), 'Disposable database must be empty; refusing existing data')


def passport(index):
    return {
        'basic_stats': {'n':37, 'mean':[0,7,11][index]},
        'freq': {'label':'месяц'},
        'stationarity': {'applicable':False,'reason':'SHORTSERIES'},
        'determinism': {'r2':0.25},
        'autocorrelation': {'lag1':0.5},
        'trend': {'direction':['flat','up','down'][index]},
        'seasonality': {'is_seasonal':bool(index)},
        'seasonal_periods': {'periods':[[4,9],[4],[4,12]][index]},
        'fft': {'periods':[4]},
        'wavelet': {'period':4},
        'certificate_tail': {'marker':'БЕРЁЗА КИРИЛЛИЦА'},
    }


def run(config):
    """Native work; exceptions are failures, never converted to acceptance."""
    import psycopg
    from psycopg.rows import dict_row
    dsn = os.environ.get('CISSTAT_PGV13_ACCEPT_DSN','')
    check_sources(Path.cwd(), config['api_sources'])
    check_disposable_database(dsn)
    with tempfile.TemporaryDirectory(prefix='pgv13-accept-') as scratch:
        # This is a new client process with explicitly supplied test-only env.
        # No .env is read and no production credentials are inherited by Docker.
        for key in ('DATABASE_URL','CISSTAT_AUTH_DATABASE_URL','CISSTAT_API_KEYS','REDIS_URL'):
            os.environ.pop(key,None)
        os.environ.update(DATABASE_URL=dsn,CISSTAT_AUTH_DATABASE_URL=dsn,
            CISSTAT_STORAGE_MODE='required',CISSTAT_IDENTITY_MODE='session_scoped',
            CISSTAT_DATA_DIR=scratch,CISSTAT_AUTH_ALLOWED_ORIGINS=ORIGIN,
            CISSTAT_AUTH_CSRF_KEY='pgv13-disposable-'+uuid4().hex+uuid4().hex,
            CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED='0',CISSTAT_AUTH_OPS_LEDGER_RETENTION_DAYS='180',
            CISSTAT_WORKER_PROOF_DIR=str(Path(scratch)/'proofs'),
            CISSTAT_PNG_RENDERER_IPC=config['socket'],CISSTAT_PNG_RENDERER_ENABLED='1',
            CISSTAT_PNG_RENDERER_URL=config.get('renderer_url',''))
        from apps.api.research_runs import run_migrations
        from apps.api.authentication.personal_demo_migrations import apply_migration
        with psycopg.connect(dsn,row_factory=dict_row) as connection:
            run_migrations(connection)
            apply_migration(connection)
        return exercise(config)


def exercise(config):
    global CURRENT_CASE
    from fastapi.testclient import TestClient
    from apps.api.authentication.storage import PostgresAccessStore
    from apps.api.authentication.sessions import SessionService
    from apps.api.workers.services import WorkerServices
    from apps.api.workers.authority import WorkerAuthority
    from apps.api.billing.policy import BudgetPolicy
    from apps.api.artifact_promotion import PromotionService
    from apps.api import artifact_store as A, report_snapshot as S, research_runs as R, document_jobs as D
    from apps.api import session_store
    from apps.api.main import app
    from apps.api.visual_artifacts import register_passport_checkpoint
    from apps.api.print_render_payload import load_print_render_input, build_print_render_payload_from_basis
    from apps.api.document_render_worker import DocumentRenderWorker

    access = PostgresAccessStore.from_env()
    auth = SessionService(access)
    actors = []
    password = 'PGV13 disposable password '+uuid4().hex
    for i in range(2):
        with access.transaction() as tx:
            person = tx.identities.create()
            account = tx.accounts.create(person.subject_id,plan='professional')
        auth.set_password(person.subject_id,'pgv13actor'+str(i),password)
        budget = BudgetPolicy(access)
        budget.create_scope('account',account_id=account.account_id,reason='PGV13 disposable fixture')
        budget.set_budget(account.account_id,'concurrency',limit_units=8,reason='PGV13 disposable fixture')
        budget.set_budget(account.account_id,'cu',limit_units=100,reason='PGV13 disposable fixture')
        actors.append((person,account))
    app.state.auth_access_store = access
    app.state.auth_session_service = auth
    clients = []
    for i,(_,account) in enumerate(actors):
        issued = auth.login('pgv13actor'+str(i),password,account.account_id,origin=ORIGIN)
        client = TestClient(app,base_url=ORIGIN)
        client.cookies.set('__Host-cisstat_auth',issued.token,domain='pgv13-accept.example',path='/')
        clients.append(client)
    owner,foreign = clients
    anonymous = TestClient(app,base_url=ORIGIN)
    # A trusted seed actor is used only for fixture persistence. Every tested
    # HTTP request resolves its own real AuthSession through production guards.
    from apps.api.identity import SubjectRef, Scope
    person,account = actors[0]
    subject = SubjectRef(subject_id=str(person.subject_id),account_id=str(account.account_id),
        tenant_id=str(account.tenant_id),via='auth_session',auth_method='auth_session',is_authenticated=True,
        scopes=frozenset(s.value for s in Scope))
    run_id = 'RUN-'+uuid4().hex[:8].upper()
    R.get_research_run_store().upsert_run(R.ResearchRun(run_id=run_id,session_id='lost-analysis-session',
        owner_account_id=str(account.account_id),owner_subject=str(person.subject_id),tenant_id=str(account.tenant_id),
        ownership='bound',ownership_version=1))
    promotion = PromotionService.create_default()
    refs, artifacts = [],[]
    for i,stage in enumerate(('start','validation','exit')):
        sid = 'pgv13-fixture-'+stage
        artifact = promotion._persist(run_id=run_id,subject=subject,kind='passport',producer_key='passport:'+sid,
            payload={'kind':'passport','snapshot_id':sid,'stage':stage,'passport':passport(i),
                'fingerprint':'fixture-'+stage,'target_column':'visits','date_column':'month',
                'passport_schema_version':'passport/1.2','calculation_version':'accept-fixture/1'})
        record = S.ReportSnapshot(snapshot_id=S.new_snapshot_id(),research_run_id=run_id,
            context_id='historical-fixture',data_revision=1,captured_at=f'2026-11-20T09:0{i}:00+00:00',
            kinds=['D02'],idempotency_key='pgv-passport:'+sid,request_fingerprint=stage,dependencies=['artifact:'+artifact.artifact_id])
        S.get_snapshot_registry().register_snapshot(record,dependencies=[])
        refs.append(record.snapshot_id);artifacts.append(artifact)
    checkpoint = 'pck-'+uuid4().hex
    register_passport_checkpoint(run_id,subject,payload={'schema_version':'pgv.passport_checkpoint/1',
        'checkpoint_id':checkpoint,'stage':'modeling_entry','confirmed_at':'2026-11-20T10:02:00+00:00',
        'confirmed_at_reason':None,'snapshot_ref':refs[-1],'previous_snapshot_ref':None,
        'flags':{'created':False,'reused':True,'unchanged':False},'stage_refs':dict(zip(('start','validation','exit'),refs)),
        'context':{'run_id':run_id,'context_id':'historical-fixture','data_revision':1},'provenance':{'source':'producer_capture'}})
    # A newer source in the same stage must not replace the selected history.
    late_id = 'pgv13-fixture-latest'
    late = promotion._persist(run_id=run_id,subject=subject,kind='passport',producer_key='passport:'+late_id,
        payload={'kind':'passport','snapshot_id':late_id,'stage':'start','passport':{'basic_stats':{'n':9999},'wrong_history':{'marker':'FORBIDDENLATEST'}},
            'fingerprint':'late-fixture','target_column':'visits','date_column':'month',
            'passport_schema_version':'passport/1.2','calculation_version':'accept-fixture/1'})
    S.get_snapshot_registry().register_snapshot(S.ReportSnapshot(snapshot_id=S.new_snapshot_id(),research_run_id=run_id,
        context_id='newer-unselected-context',data_revision=2,captured_at='2026-11-20T11:00:00+00:00',
        kinds=['D02'],idempotency_key='pgv-passport:'+late_id,request_fingerprint='late',dependencies=['artifact:'+late.artifact_id]),dependencies=[])
    panel_id='pgv13-panel-fixture'
    panel_artifact=promotion._persist(run_id=run_id,subject=subject,kind='passport',producer_key='passport:'+panel_id,
        payload={'kind':'passport','snapshot_id':panel_id,'stage':'panel_entry','passport':passport(0),
            'fingerprint':'panel-fixture','target_column':'visits','date_column':'month','entity_column':'entity',
            'passport_schema_version':'passport/1.2','calculation_version':'accept-fixture/1'})
    panel_ref=S.new_snapshot_id()
    S.get_snapshot_registry().register_snapshot(S.ReportSnapshot(snapshot_id=panel_ref,research_run_id=run_id,
        context_id='panel-fixture',data_revision=1,captured_at='2026-11-20T09:00:00+00:00',
        kinds=['D02'],idempotency_key='pgv-passport:'+panel_id,request_fingerprint='panel',dependencies=['artifact:'+panel_artifact.artifact_id]),dependencies=[])
    key = WorkerServices(access).issue(kinds=['render'],reason='PGV13 disposable acceptance')
    os.environ['CISSTAT_WORKER_KEY'] = key
    work = WorkerAuthority(access,key)
    worker = DocumentRenderWorker(worker_authority=work,max_attempts=1,render_timeout=60)
    registries=(R.get_research_run_store(),A.get_artifact_registry(),S.get_snapshot_registry(),D.get_document_registry())
    expected=(R.PostgresResearchRunStore,A.PostgresArtifactRegistry,S.PostgresSnapshotRegistry,D.PostgresDocumentRegistry)
    require(all(isinstance(store,kind) for store,kind in zip(registries,expected)), 'All registries must be native PostgreSQL')
    def no_session():
        raise ValueError('Scientific SessionStore access forbidden in durable document acceptance')
    session_store.get_session_store = no_session

    def post(client,path,body):
        proof = client.get('/v1/auth/csrf',headers={'Origin':ORIGIN})
        require(proof.status_code == 200, 'Real authenticated CSRF endpoint failed')
        return client.post(path,json=body,headers={'Origin':ORIGIN,'X-CSRF-Token':proof.json()['csrf_token']})
    path = '/v1/documentation/runs/'+run_id+'/passport-documents'
    selected={'mode':'single','snapshot_refs':refs[:1]}
    foreign_create=post(foreign,path,selected)
    missing_create=post(foreign,'/v1/documentation/runs/RUN-00000000/passport-documents',selected)
    require(foreign_create.status_code==missing_create.status_code==404 and public_error(foreign_create)==public_error(missing_create),
        'Foreign/missing document creation must be uniform 404: '+json.dumps({
            'foreign':{'status':foreign_create.status_code,'body':public_error(foreign_create)},
            'missing':{'status':missing_create.status_code,'body':public_error(missing_create)}},ensure_ascii=False))
    unavailable=post(owner,path,{'mode':'single','snapshot_refs':['rs-'+'d'*32]})
    require(unavailable.status_code==409 and unavailable.json().get('code')=='source_unavailable','Missing single source must be unavailable')
    incompatible=post(owner,path,{'mode':'compare','snapshot_refs':[refs[0],panel_ref]})
    require(incompatible.status_code==409 and incompatible.json().get('code')=='comparison_incompatible','Panel/single incompatibility must be closed')
    unproved=owner.post(path,json=selected,headers={'Origin':ORIGIN})
    require(unproved.status_code==403,'Document mutation without CSRF must be denied')
    records = []
    for case in CASES:
        CURRENT_CASE = case['id']
        kind = case['kind']
        selection = {'mode':'compare' if kind.startswith('compare') else ('single' if kind=='single' else 'set'), 'profile_id':case['profile']}
        if kind in ('set','compare-reused'):
            selection['checkpoint_id'] = checkpoint
        else:
            selection['snapshot_refs'] = refs[:1] if kind=='single' else refs[:2]
        if kind in ('missing','compare-missing'):
            selection['snapshot_refs'] = [refs[0],'rs-'+'d'*32] + ([refs[1]] if kind=='compare-missing' else [])
        original = None
        if kind=='corrupt':
            selection['snapshot_refs'] = [refs[0],refs[-1]]
            original = A.get_artifact_object_store().read_bytes(artifacts[-1].storage_key)
            A.get_artifact_object_store().path_for_key(artifacts[-1].storage_key).write_bytes(b'corrupt fixture')
        try:
            response = post(owner,path,selection)
            require(response.status_code == 202, 'Passport document HTTP admission failed: '+str(response.status_code))
            outcome = response.json()
            job_id = outcome['job']['job_id']
            basis = load_print_render_input(outcome['snapshot_artifact_id'])
            snapshot = basis['snapshot']
            sections = snapshot['display']['sections']
            require('FORBIDDENLATEST' not in json.dumps(snapshot), 'Selected historical refs replaced by latest source')
            for section in sections:
                if section.get('renderer_kind')=='passport_record':
                    record=section['record']
                    if record['content_status']=='present':
                        require(record['snapshot_ref'] in refs and record['passport']==passport(refs.index(record['snapshot_ref'])),'Full durable passport content changed')
                    else:
                        require(record['passport'] is None and record['content_gap_reason'],'Unavailable passport contains fabricated content')
            if selection['mode']=='single':
                require(sections[0]['record']['passport'] == passport(0), 'Full frozen passport groups differ')
                require(sections[0]['record']['source_hash'] == artifacts[0].payload_sha256, 'Passport source digest differs')
            if kind in ('set','compare-reused'):
                actual_checkpoint = snapshot['checkpoint']['checkpoint_id'] if kind=='set' else sections[0]['comparison']['checkpoint']['checkpoint_ref']
                require(actual_checkpoint == checkpoint, 'Reused checkpoint identity differs')
                if kind=='set':
                    require([s['record']['snapshot_ref'] for s in sections] == refs, 'Reused checkpoint duplicates or reorders physical passports')
            if kind=='compare':
                comp = sections[0]['comparison']
                require(comp['ordered_refs'] == refs[:2], 'Historical comparison refs changed')
                pair = comp['comparisons'][0]['comparison']
                require(pair['metrics']['Среднее']['delta']==7 and pair['metrics']['Среднее']['delta_pct']==100, 'Numeric/zero-base comparison differs')
                require(pair['categorical_changes'] and pair['list_changes'] and pair['qualitative_changes'], 'Comparison content groups missing')
                require('не определено' in comp['definitions']['zero_denominator_reason'],'Zero denominator explanation absent')
            if kind in ('missing','corrupt','compare-missing'):
                require(snapshot['display']['completeness']=='partial', 'Missing/corrupt source falsely complete')
            repeat = post(owner,path,selection)
            require(repeat.status_code==202 and repeat.json()['job']['job_id']==job_id and repeat.json()['print_revision_id']==outcome['print_revision_id'], 'Queued document idempotency failed')
            pending = owner.get('/v1/documentation/jobs/'+job_id)
            require(pending.status_code==200 and pending.json()['job']['state']=='queued', 'HTTP queued state missing')
            cycle = worker.run_once()
            ready = owner.get('/v1/documentation/jobs/'+job_id)
            require(ready.status_code==200 and ready.json()['job']['state']=='ready', 'Managed render worker did not publish ready job')
            require(work.find('render',job_id)['state']=='completed', 'AUTH13 managed worker completion missing')
            job = ready.json()['job']
            rendition_id = job['rendition']['rendition_id']
            url = '/v1/documentation/renditions/'+rendition_id+'/content'
            download = owner.get(url)
            require(download.status_code==200 and download.headers.get('content-type','').split(';')[0] in ('image/png','application/zip'), 'Authorized PNG/page-set download failed')
            require(download.headers.get('content-disposition','').startswith('attachment') and download.headers.get('x-content-type-options')=='nosniff', 'Download security headers differ')
            require('private' in download.headers.get('cache-control','') and 'no-store' in download.headers.get('cache-control',''), 'Download cache policy differs')
            require(hashlib.sha256(download.content).hexdigest()==job['rendition']['content_sha256'], 'Download bytes differ from stored rendition digest')
            require(owner.get(url).content==download.content, 'Repeat download changed bytes')
            actual_payload=build_print_render_payload_from_basis(basis,request_id='pgv:'+job_id)
            metadata_url=job.get('metadata_url')
            require(metadata_url,'Frozen metadata URL missing')
            metadata_response=owner.get(metadata_url)
            require(metadata_response.status_code==200 and metadata_response.headers.get('content-type','').startswith('application/json'),'Metadata download failed')
            metadata=metadata_response.json()
            require(metadata.get('source_payload')==actual_payload and metadata.get('page_count',0)>0,'Metadata binding/count differs')
            require(foreign.get(metadata_url).status_code==404 and anonymous.get(metadata_url).status_code in (401,404),'Metadata object authorization failed')
            if download.content.startswith(b'PK'):
                from apps.api.print_page_sets import validate_page_set
                verified=validate_page_set(download.content,actual_payload)
                require(verified.format=='zip','Unexpected single-page ZIP representation')
                require(verified.metadata==metadata_response.content,'ZIP/sidecar metadata differs')
            else:
                from apps.api.print_page_sets import validate_png
                from apps.api.print_schema import resolve_print_profile
                profile=resolve_print_profile(case['profile'])
                validate_png(download.content,profile['width_px'],profile['height_px'])
                require(metadata['page_count']==1 and metadata['pages'][0]['sha256']==hashlib.sha256(download.content).hexdigest(),'Single-page metadata digest differs')
            from apps.api.security_audit import ACTION_DOWNLOAD_REQUESTED, ACTION_RESPONSE_STREAM_STARTED, ACTION_RESPONSE_STREAM_FINISHED
            with access.transaction(readonly=True) as tx:
                audit={row['action']:row['n'] for row in tx.connection.execute(
                    'SELECT action,count(*) AS n FROM security_audit_records WHERE resource_id=%s AND actor_subject=%s GROUP BY action',
                    (rendition_id,str(person.subject_id))).fetchall()}
            require(all(audit.get(action,0)>=2 for action in (ACTION_DOWNLOAD_REQUESTED,ACTION_RESPONSE_STREAM_STARTED,ACTION_RESPONSE_STREAM_FINISHED)), 'Download audit triplet missing')
            again = post(owner,path,selection)
            require(again.status_code==202 and again.json()['job']['job_id']==job_id, 'Ready job idempotency failed')
            foreign_job = foreign.get('/v1/documentation/jobs/'+job_id)
            absent_job = foreign.get('/v1/documentation/jobs/'+job_id[:-8]+uuid4().hex[:8])
            foreign_file = foreign.get(url)
            absent_file = foreign.get('/v1/documentation/renditions/'+rendition_id[:-8]+uuid4().hex[:8]+'/content')
            require(foreign_job.status_code==absent_job.status_code==404 and public_error(foreign_job)==public_error(absent_job), 'Foreign/missing job must be uniform 404')
            require(foreign_file.status_code==absent_file.status_code==404 and public_error(foreign_file)==public_error(absent_file), 'Foreign/missing download must be uniform 404')
            require(anonymous.get(url).status_code in (401,404), 'Anonymous download disclosed content')
            needles = ['Паспорт свойств ряда',*GROUPS,'БЕРЁЗА'] if not selection['mode']=='compare' else ['Сравнение паспортов','Определения']
            numbers = ['37'] if selection['mode']!='compare' else []
            if kind=='compare':
                needles += ['Числовые метрики','Качественные и категориальные изменения','не определено']
                numbers = ['7','100']
            if kind=='set':
                needles += ['Подтверждение паспорта']
            if kind=='compare-reused':
                needles += ['Подтверждение чекпоинта']
            if kind in ('missing','corrupt'):
                needles += ['Паспорт недоступен', 'missing_artifact' if kind=='missing' else 'corrupt']
            if kind=='compare-missing':
                needles += ['Полнота','partial']
            records.append({'id':case['id'],'profile':case['profile'],'job_id':job_id,
                'print_revision_id':outcome['print_revision_id'],'basis_artifact_id':outcome['snapshot_artifact_id'],
                'rendition':{k:job['rendition'][k] for k in ('rendition_id','content_sha256','size_bytes','snapshot_payload_sha256')},
                'download_headers':{k:download.headers[k] for k in ('content-type','content-disposition','cache-control','x-content-type-options')},
                'payload':actual_payload,'metadata_base64':base64.b64encode(metadata_response.content).decode(), 'delivery_format':job['rendition']['format'],
                'download_base64':base64.b64encode(download.content).decode(), 'expected_text':needles,'expected_numbers':numbers,
                'expected_counts':{'БЕРЁЗА':3 if kind=='set' else 1} if selection['mode']!='compare' else {},
                'checks':dict.fromkeys(('full_durable_content','queued_http','managed_worker','ready_http','download_digest','repeat_download','queued_idempotency','ready_idempotency','foreign_job_404','foreign_download_404','anonymous_denied','download_headers','download_audit'),True),
                'worker_cycle':cycle})
        finally:
            if original is not None:
                A.get_artifact_object_store().path_for_key(artifacts[-1].storage_key).write_bytes(original)
    for client in (*clients,anonymous):
        client.close()
    with access.transaction(readonly=True) as tx:
        scientific_rows=tx.connection.execute('SELECT count(*) AS n FROM analysis_sessions').fetchone()['n']
        workers=tx.connection.execute("SELECT count(*) AS n FROM auth_worker_jobs WHERE state='completed'").fetchone()['n']
        active=tx.connection.execute("SELECT count(*) AS n FROM auth_reservations WHERE state IN ('pending','running','uncertain')").fetchone()['n']
    require(scientific_rows==0 and workers==len(CASES) and active==0,'Scientific session/terminal worker/held reservation proof failed')
    return {'passed':True,'backend':'postgres','authentication':'real AuthSession and CSRF; no identity override',
            'scientific_session':'absent; SessionStore access forbidden','cases':records,
            'backend_proof':{'registry_types':[type(x).__name__ for x in registries],
                'scientific_session_rows':scientific_rows,'completed_workers':workers,'held_reservations':active},
            'negative_controls':dict.fromkeys(('foreign_create_404','missing_single_409','panel_single_409','csrf_required'),True)}
