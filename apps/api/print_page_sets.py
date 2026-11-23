"""PGV14 renderer boundary. Bounded, frozen-input-bound PNG page archives.

No science or session reads. All members verified before any ready publication.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import hashlib
import io
import json
import re
import struct
import zlib
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from apps.api.png_renderer_client import RendererBadOutput

MAX_BYTES=50*1024*1024
MAX_PAGES=20

class PageSetInvalid(RendererBadOutput):
    pass

@dataclass(frozen=True)
class PageSetResult:
    format: str
    content: bytes
    metadata: bytes
    manifest: dict


def _require(ok, reason):
    if not ok:raise PageSetInvalid('renderer_bad_output: page_set '+reason)


def _sha(b):return hashlib.sha256(b).hexdigest()


def _json(data):
    def pairs(items):
        d={}
        for k,v in items:
            _require(k not in d,'duplicate JSON key');d[k]=v
        return d
    return json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _same(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return type(a) is type(b) and a==b
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(_same(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(_same(x,y) for x,y in zip(a,b))
    return a==b


def validate_png(data:bytes,width:int,height:int):
    _require(len(data)<=MAX_BYTES and data.startswith(b'\x89PNG\r\n\x1a\n'),'PNG signature/size')
    pos=8;names=[];compressed=[];phys=False
    while pos+12<=len(data):
        n=struct.unpack_from('>I',data,pos)[0];kind=data[pos+4:pos+8];end=pos+12+n
        _require(end<=len(data),'PNG chunk length');body=data[pos+8:pos+8+n]
        _require(zlib.crc32(kind+body)&0xffffffff==struct.unpack_from('>I',data,pos+8+n)[0],'PNG CRC')
        names.append(kind)
        if kind==b'IHDR':_require(n==13 and struct.unpack('>IIBBBBB',body)==(width,height,8,6,0,0,0) or n==13 and struct.unpack('>IIBBBBB',body)==(width,height,8,2,0,0,0),'PNG geometry/encoding');color=body[9]
        if kind==b'pHYs':_require(body==struct.pack('>IIB',11811,11811,1),'PNG density');phys=True
        if kind==b'IDAT':compressed.append(body)
        if kind==b'IEND':_require(n==0,'PNG IEND length')
        _require(kind[:1].islower() or kind in (b'IHDR',b'PLTE',b'IDAT',b'IEND'),'PNG unknown critical chunk')
        pos=end
        if kind==b'IEND':break
    _require(names and names.count(b'IHDR')==1 and names.count(b'pHYs')==1 and names.count(b'IEND')==1 and names[0]==b'IHDR' and names[-1]==b'IEND' and pos==len(data) and phys and compressed,'PNG completeness')
    idats=[i for i,k in enumerate(names) if k==b'IDAT']
    _require(idats==list(range(idats[0],idats[-1]+1)) and names.index(b'pHYs')<idats[0],'PNG chunk order')
    stride=1+width*(4 if color==6 else 3)
    expected=stride*height
    decoder=zlib.decompressobj();decoded=decoder.decompress(b''.join(compressed),expected+1)
    _require(len(decoded)==expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'PNG raster length')
    _require(all(decoded[i]<=4 for i in range(0,expected,stride)),'PNG scanline filter')


def validate_page_set(raw:bytes,payload:dict)->PageSetResult:
    from apps.api.print_schema import resolve_print_profile, validate_print_set_manifest
    try:
        _require(isinstance(raw,bytes) and len(raw)<=MAX_BYTES,'archive size')
        profile=resolve_print_profile(payload['snapshot']['print']['profile_id'])
        _require(profile is not None,'profile')
        width,height=profile['width_px'],profile['height_px']
        _require(width*height<=12_000_000,'pixel cap')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();names=[e.filename for e in entries]
            _require(len(names)==len(set(names)) and 3<=len(names)<=MAX_PAGES+2,'member count/duplicates')
            _require(all(not e.flag_bits&1 and e.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for e in entries),'ZIP encoding')
            _require(sum(e.file_size for e in entries)<=MAX_BYTES and all(e.file_size<=MAX_BYTES for e in entries),'expanded size')
            _require(all(re.fullmatch(r'page-\d{3}\.png|manifest\.json|metadata\.json',n) for n in names),'member path')
            m=_json(archive.read('manifest.json'));meta_bytes=archive.read('metadata.json');meta=_json(meta_bytes)
            pages=m['pages'];count=len(pages)
            _require(type(m['page_count']) is int and m['page_count']==count and 1<=count<=MAX_PAGES,'page count')
            _require(names==[f'page-{i+1:03}.png' for i in range(count)]+['metadata.json','manifest.json'],'member order')
            _require(not validate_print_set_manifest(m) and m['page_set_version']=='pgv.page_set/1' and m['set_id']==payload['request_id'] and m['render_version']=='print-renderer/1' and m['metadata_filename']=='metadata.json' and m['data_included'] is False and m['profile_id']==profile['id'] and m['width']==width and m['height']==height and m['ppi']==300,'manifest profile')
            _require(m['metadata']=={'filename':'metadata.json','size_bytes':len(meta_bytes),'sha256':_sha(meta_bytes)},'metadata hash')
            _require(meta['schema_version']=='pgv.page_metadata/1' and _same(meta['source_payload'],payload),'frozen input binding')
            _require(meta['renderer_version']=='print-renderer/1' and meta['font_profile']=='print-fonts-dejavu/1','renderer binding')
            _require(meta['page_count']==count and len(meta['pages'])==count,'metadata count')
            units=[];sections=[];data=[]
            for i,p in enumerate(pages):
                _require(p['index']==i+1 and p['filename']==f'page-{i+1:03}.png','page order')
                section=p['section_index'];_require(type(section) is int and 0<=section<len(payload['sections']),'section index')
                s=payload['sections'][section]
                refs=([s['record']['snapshot_ref']] if s['kind']=='passport_record' else [r for r in s['comparison']['ordered_refs'] if r])
                _require(p['source_refs']==refs and p['role']==('P01' if s['kind']=='passport_record' else 'P02'),'source identity')
                _require(isinstance(p['unit_ids'],list) and all(isinstance(u,str) and re.fullmatch(str(section)+r':\d+',u) for u in p['unit_ids']),'unit identifiers')
                units.extend(p['unit_ids']);sections.append(section)
                content=archive.read(p['filename'])
                _require(len(content)==p['size_bytes'] and _sha(content)==p['sha256']==p['png_sha256'] and p['page_role']==p['role'] and p['width_px']==width and p['height_px']==height,'page hash/role/geometry')
                validate_png(content,width,height);data.append(content)
                mp=meta['pages'][i]
                _require(all(mp.get(k)==p.get(k) for k in ('index','filename','sha256','size_bytes','source_refs','role','section_index','unit_ids')),'metadata page identity/hash')
            _require(sections==sorted(sections) and set(sections)==set(range(len(payload['sections']))),'section coverage/order')
            _require(type(m['unit_count']) is int and len(units)==m['unit_count']==len(set(units)),'unit coverage')
            for section in set(sections):
                ids=[int(u.split(':')[1]) for u in units if u.startswith(str(section)+':')]
                _require(ids==list(range(len(ids))),'unit order/gap')
            expected_refs=sorted({r for p in pages for r in p['source_refs']})
            _require(sorted(m['dependencies'])==expected_refs and m['intended_size_mm']=={'width':profile['width_mm'],'height':profile['height_mm']},'dependencies/physical intent')
            force_zip=payload['snapshot'].get('documents',{}).get('mode')=='set'
            return PageSetResult('zip' if count>1 or force_zip else 'png',raw if count>1 or force_zip else data[0],meta_bytes,m)
    except PageSetInvalid:raise
    except Exception as exc:raise PageSetInvalid('renderer_bad_output: invalid page_set '+type(exc).__name__) from None


@contextmanager
def _publication(registry):
    from apps.api.document_jobs import MemoryDocumentRegistry
    from apps.api.workers.connection import BOUND,bind_connection
    if isinstance(registry,MemoryDocumentRegistry):
        with registry._lock:
            old_jobs=copy.deepcopy(registry._jobs);old_renditions=copy.deepcopy(registry._renditions)
            try:yield
            except BaseException:
                registry._jobs=old_jobs;registry._renditions=old_renditions;raise
    elif BOUND.get() is not None:
        yield  # AUTH13 already owns the bound publication transaction.
    else:
        with registry._connect() as c,bind_connection(c,SimpleNamespace(_dsn=registry._dsn,schema='public')):yield


def publish_page_set(service,job,result:PageSetResult,source_sha256):
    from apps.api.document_jobs import DocumentRenditionRecord,new_rendition_id,JOB_READY
    from apps.api.document_renditions import RENDITION_FORMATS
    with _publication(service.registry):
        finished,main=service.complete_render(job,RENDITION_FORMATS[result.format],result.content,None,source_sha256=source_sha256)
        if finished.state!=JOB_READY:return finished,main
        staged=service.objects.stage_bytes(result.metadata,'application/json');key=service.objects.commit_staged(staged)
        prior=service.registry.find_print_rendition(job.print_revision_id,'json',job.redaction_profile)
        sidecar=DocumentRenditionRecord(rendition_id=prior.rendition_id if prior else new_rendition_id(),revision_id='',snapshot_id='',run_id=job.run_id,
            format='json',redaction_profile=job.redaction_profile,media_type='application/json',size_bytes=len(result.metadata),content_sha256=_sha(result.metadata),
            storage_key=key,job_id=job.job_id,created_by=job.created_by,snapshot_payload_sha256=source_sha256,
            print_revision_id=job.print_revision_id,content_bytes=result.metadata if hasattr(service.registry,'_renditions') else None)
        if prior:service.registry.update_rendition(sidecar)
        else:service.registry.register_rendition(sidecar)
        return finished,main
