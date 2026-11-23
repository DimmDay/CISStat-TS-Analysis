"""PGV14: package boundary and real document lifecycle; no Chromium claim."""
import copy,hashlib,io,json,struct,zipfile,zlib
import pytest
from apps.api.print_page_sets import validate_page_set, PageSetInvalid
from scripts.pgv13cert.test_contracts import facts, request, basis


def png(width,height):
    def chunk(name,data):
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    raw=zlib.compress((b'\0'+b'\xff\xff\xff\xff'*width)*height)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'pHYs',struct.pack('>IIB',11811,11811,1))+chunk(b'IDAT',raw)+chunk(b'IEND',b'')


def package(payload,n=2,mutate=None):
    from apps.api.print_schema import resolve_print_profile
    profile=resolve_print_profile(payload['snapshot']['print']['profile_id'])
    width,height=profile['width_px'],profile['height_px']
    data=png(width,height)
    metadata=json.dumps({'schema_version':'pgv.page_metadata/1','source_payload':payload,'renderer_version':'print-renderer/1','font_profile':'print-fonts-dejavu/1','page_count':n},ensure_ascii=False).encode()
    refs=[s['record']['snapshot_ref'] for s in payload['sections'] if s['kind']=='passport_record']
    manifest={'schema_version':'pgv.print_manifest/1','page_set_version':'pgv.page_set/1','set_id':payload['request_id'],'render_version':'print-renderer/1','metadata_filename':'metadata.json','data_included':False,'profile_id':profile['id'],'width':width,'height':height,'ppi':300,'unit_count':n,'page_count':n,
        'metadata':{'filename':'metadata.json','size_bytes':len(metadata),'sha256':hashlib.sha256(metadata).hexdigest()},
        'pages':[{'index':i+1,'filename':f'page-{i+1:03}.png','size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                  'role':'P01','section_index':0,'source_refs':refs,'unit_ids':[f'0:{i}']} for i in range(n)]}
    for p in manifest['pages']:p.update(page_role=p['role'],png_sha256=p['sha256'],width_px=width,height_px=height)
    manifest['dependencies']=sorted(set(refs));manifest['intended_size_mm']={'width':profile['width_mm'],'height':profile['height_mm']}
    meta=json.loads(metadata);meta['pages']=copy.deepcopy(manifest['pages']);metadata=json.dumps(meta,ensure_ascii=False).encode()
    manifest['metadata']={'filename':'metadata.json','size_bytes':len(metadata),'sha256':hashlib.sha256(metadata).hexdigest()}
    members={p['filename']:data for p in manifest['pages']};members['metadata.json']=metadata
    if mutate:mutate(manifest,members)
    members['manifest.json']=json.dumps(manifest).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_STORED) as z:
        for name,content in members.items():z.writestr(name,content)
    return out.getvalue()


def payload_of(facts):
    from apps.api.print_render_payload import build_print_render_payload_from_basis
    o=request(facts,mode='single',snapshot_refs=[facts.refs[0]],profile_id='a4-portrait')
    return build_print_render_payload_from_basis(basis(o),request_id='test-pgv14'),o


def test_single_png_and_metadata_are_bound_to_exact_frozen_input(facts):
    p,_=payload_of(facts);result=validate_page_set(package(p,1),p)
    assert result.format=='png' and result.content.startswith(b'\x89PNG')
    assert json.loads(result.metadata)['page_count']==1


def test_many_pages_deliver_zip_with_every_hash_checked(facts):
    p,_=payload_of(facts);raw=package(p,3);result=validate_page_set(raw,p)
    assert result.format=='zip' and result.content==raw


@pytest.mark.parametrize('mutation',[
 lambda m,f:m['pages'][0].update(sha256='0'*64),
 lambda m,f:m['pages'].reverse(),
 lambda m,f:m['pages'][1].update(unit_ids=['0:0']),
 lambda m,f:m['pages'][0].update(source_refs=['rs-foreign']),
 lambda m,f:f.update({'unexpected.csv':b'raw data'}),
 lambda m,f:m.update(ppi=96),
 lambda m,f:f.update({'metadata.json':b'{}'}),
])
def test_bad_packages_never_reach_ready(facts,mutation):
    p,_=payload_of(facts)
    with pytest.raises(PageSetInvalid):validate_page_set(package(p,2,mutation),p)


def test_source_payload_cannot_be_replaced(facts):
    p,_=payload_of(facts);q=copy.deepcopy(p);q['sections'][0]['record']['target_column']='foreign'
    with pytest.raises(PageSetInvalid):validate_page_set(package(q),p)


def test_real_worker_publishes_zip_and_json_sidecar_and_replays_same_job(facts):
    from apps.api.document_render_worker import DocumentRenderWorker
    from apps.api.document_jobs import DocumentDeliveryService
    p,o=payload_of(facts)
    class Renderer:
        def render_page(self,payload):return package(payload,2)
    worker=DocumentRenderWorker(png_renderer=Renderer());worker.run_once()
    service=DocumentDeliveryService.create_default();job=service.registry.get_job(o['job']['job_id'])
    assert job.state=='ready'
    main=service.registry.get_rendition(job.rendition_id)
    assert main.format=='zip' and main.media_type=='application/zip'
    meta=service.registry.find_print_rendition(job.print_revision_id,'json',job.redaction_profile)
    assert meta and meta.state=='ready'
    assert json.loads(service.read_rendition_content(meta,facts.owner))['page_count']==2
    again=request(facts,mode='single',snapshot_refs=[facts.refs[0]],profile_id='a4-portrait')
    assert again['job']['job_id']==job.job_id


def test_every_single_and_multi_case_is_retained():
    from scripts.pgv13accept.client import CASES as before
    from scripts.pgv14.client import CASES as after
    assert len(after)==11 and after==before


def test_metadata_failure_cannot_publish_half_a_page_set(facts,monkeypatch):
    from apps.api.document_jobs import DocumentDeliveryService
    from apps.api.document_render_worker import DocumentRenderWorker
    p,o=payload_of(facts);service=DocumentDeliveryService.create_default()
    original=service.registry.register_rendition
    def broken(r):
        if r.format=='json':raise RuntimeError('sidecar storage fault')
        return original(r)
    monkeypatch.setattr(service.registry,'register_rendition',broken)
    class Renderer:
        def render_page(self,payload):return package(payload,2)
    DocumentRenderWorker(png_renderer=Renderer()).run_once()
    job=service.registry.get_job(o['job']['job_id'])
    assert job.state!='ready' and not job.rendition_id
    assert not any(r.state=='ready' for r in service.registry._renditions.values())


def test_cancel_before_publication_does_not_leave_ready_pages_or_metadata(facts):
    from apps.api.document_jobs import DocumentDeliveryService
    from apps.api.document_render_worker import DocumentRenderWorker
    p,o=payload_of(facts);service=DocumentDeliveryService.create_default()
    class Renderer:
        def render_page(self,payload):
            service.cancel_job(o['job']['job_id'],facts.owner)
            return package(payload,2)
    DocumentRenderWorker(png_renderer=Renderer()).run_once()
    assert service.registry.get_job(o['job']['job_id']).state=='cancelled'
    assert not any(r.state=='ready' for r in service.registry._renditions.values())

@pytest.mark.parametrize('fault',['crc','profile'])
def test_last_page_is_decoded_even_when_all_manifest_hashes_match(facts,fault):
    p,_=payload_of(facts)
    def tamper(m,files):
        last=m['pages'][-1];data=files[last['filename']]
        if fault=='crc':
            broken=bytearray(data);broken[40]^=1;data=bytes(broken)
        else:data=png(2400,1500)
        files[last['filename']]=data
        last.update(sha256=hashlib.sha256(data).hexdigest(),png_sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data))
        meta=json.loads(files['metadata.json']);meta['pages'][-1]=copy.deepcopy(last)
        files['metadata.json']=json.dumps(meta).encode()
        m['metadata'].update(sha256=hashlib.sha256(files['metadata.json']).hexdigest(),size_bytes=len(files['metadata.json']))
    with pytest.raises(PageSetInvalid,match='PNG'):validate_page_set(package(p,3,tamper),p)


def test_page_budget_is_terminal_and_a_single_page_set_still_delivers_zip(facts):
    p,_=payload_of(facts)
    with pytest.raises(PageSetInvalid):validate_page_set(package(p,21),p)
    p['snapshot'].setdefault('documents',{})['mode']='set'
    assert validate_page_set(package(p,1),p).format=='zip'
