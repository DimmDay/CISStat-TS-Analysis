"""Native VM preflight controls. No Docker/AF_UNIX claim from these doubles."""
import copy
import importlib
import json
import struct
import zlib
from pathlib import Path

import pytest


def implementation(): return importlib.import_module('scripts.pgv13uds.verify_vm')


def meta():
    return {'Image':'sha256:'+'a'*64,'User':'10001:10001','NetworkMode':'none','ReadOnlyRootfs':True,
        'CapDrop':['ALL'],'Privileged':False,'PidsLimit':512,'Memory':2147483648,
        'SecurityOpt':['no-new-privileges:true','apparmor=docker-default','seccomp='+str(Path('apps/print-renderer/build/deployment/chromium.seccomp.json').resolve())],
        'PortBindings':{},'UsernsMode':'',
        'Mounts':[{'Type':'volume','Name':'cisstat_renderer_ipc_candidate','Destination':'/run/cisstat-renderer','RW':True}]}


def test_valid_renderer_boundary():assert implementation().validate_renderer_meta(meta())=='cisstat_renderer_ipc_candidate'


@pytest.mark.parametrize('key,value',[('User','0:0'),('NetworkMode','bridge'),('ReadOnlyRootfs',False),
    ('CapDrop',[]),('Privileged',True),('PidsLimit',0),('Memory',0),('SecurityOpt',[]),('PortBindings',{'8907/tcp':[{}]})])
def test_unsafe_renderer_refused(key,value):
    m=meta();m[key]=value
    with pytest.raises(ValueError):implementation().validate_renderer_meta(m)


def test_extra_mount_refused():
    m=meta();m['Mounts'].append({'Destination':'/var/run/docker.sock'})
    with pytest.raises(ValueError):implementation().validate_renderer_meta(m)


def png():
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,1,8,2,0,0,0))+chunk(b'pHYs',struct.pack('>IIB',11811,11811,1))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0\0\0\0'))+chunk(b'IEND',b'')


def test_png_oracle_crc_and_geometry():
    result=implementation().png_checks(png(),(2,1))
    assert all(result.values())
    corrupt=bytearray(png());corrupt[-5]^=1
    assert not all(implementation().png_checks(bytes(corrupt),(2,1)).values())
    assert not implementation().png_checks(png(),(3,1))['dimensions']


def test_native_metrics_require_no_new_failures():
    V=implementation()
    good={'parent_hardening':True,'tcp_closed':True,'uid':10001,'gid':10001,'mode':0o660,
          'directory_mode':0o750,'pids_max':512,'memory_max':2147483648,
          'pids_events':{'max':0},'memory_events':{'oom':0,'oom_kill':0}}
    V.metrics_ok(good,copy.deepcopy(good))
    for key in ('max','oom','oom_kill'):
        bad=copy.deepcopy(good)
        bad['pids_events' if key=='max' else 'memory_events'][key]=1
        with pytest.raises(ValueError):V.metrics_ok(good,bad)
    missing=copy.deepcopy(good);missing['memory_events']=None
    with pytest.raises(ValueError):V.metrics_ok(good,missing)


def test_native_gate_never_keeps_stale_pass(tmp_path):
    V=implementation();out=tmp_path/'report.json';out.write_text('{"passed":true}')
    code=V.main(['--renderer-project','candidate','--sandbox-report',str(tmp_path/'missing.json'),'--out',str(out)])
    assert code==2
    report=json.loads(out.read_text())
    assert report['passed'] is False and report['pgv13_certified'] is False


def client_result():
    V=implementation()
    import hashlib
    digest=hashlib.sha256((V.ROOT/'apps/api/png_renderer_client.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    return {'passed':True,'readiness':True,'readonly':True,'client_source_sha256':digest,'negative_checks':{'cancel':True,'deadline':True,'request_cap':True},'cancel_request_ids':['pgv13-uds-'+'a'*32,'pgv13-uds-'+'b'*32],
        'scenarios':[{'profile':profile,'bytes':1024,'checks':{k:True for k in ['signature','crc','dimensions','phys_300ppi','idat','iend']},'sha256':str(i)*64}
            for i,profile in enumerate(['figure-landscape','a4-landscape','a4-portrait'],1)]}


def test_native_client_evidence_is_not_just_passed_flag():
    V=implementation();V.validate_client_result(client_result())
    for field,value in [('scenarios',[]),('readonly',False),('readiness',False),('client_source_sha256','stale')]:
        report=client_result();report[field]=value
        with pytest.raises(ValueError):V.validate_client_result(report)


def test_cli_candidate_checks_and_cleanup(tmp_path,monkeypatch):
    V=implementation();out=tmp_path/'report.json';image='sha256:'+'a'*64
    monkeypatch.setenv('CISSTAT_UDS_RENDERER_IMAGE',image)
    evidence=tmp_path/'ab.json';evidence.write_text('{}')
    monkeypatch.setattr(V,'validate_report',lambda p:image)
    good={'parent_hardening':True,'tcp_closed':True,'uid':10001,'gid':10001,'mode':0o660,
          'directory_mode':0o750,'pids_max':512,'memory_max':2147483648,
          'pids_events':{'max':0},'memory_events':{'oom':0,'oom_kill':0}}
    calls=[]
    def command(args,**kwargs):
        calls.append(args)
        if 'inspect' in args:return json.dumps(meta())
        if 'logs' in args:return '\n'.join(json.dumps({'event':'render_cancelled','request_id':i}) for i in client_result()['cancel_request_ids'])
        if 'ps' in args:return 'candidate-cid'
        if V.NODE_STATE in args:return json.dumps(good)
        if V.EXPORT_SCENARIOS in args:return '[{},{},{}]'
        if V.CLIENT in args:return json.dumps(client_result())
        raise AssertionError(args)
    from types import SimpleNamespace
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=73 if 'flock' in args else 0)
    monkeypatch.setattr(V,'command',command);monkeypatch.setattr(V.subprocess,'run',run)
    assert V.main(['--renderer-project','candidate','--sandbox-report',str(evidence),'--api-image','api:candidate','--out',str(out)])==0
    result=json.loads(out.read_text())
    assert result['passed'] is True and result['pgv13_certified'] is False and result['lifetime_lock'] is True
    assert any(c[:3]==['docker','rm','-f'] and c[3].startswith('cisstat-uds-api-') for c in calls)
    client=next(c for c in calls if V.CLIENT in c)
    assert '--network=none' in client and '--group-add=10001' in client
    assert any('readonly,volume-nocopy' in arg for arg in client)


def test_inspect_template_uses_actual_docker_field_names():
    assert '.HostConfig.ReadonlyRootfs' in implementation().META
    assert '.HostConfig.ReadOnlyRootfs' not in implementation().META
