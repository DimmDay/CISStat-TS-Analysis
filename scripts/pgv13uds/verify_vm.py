"""Native API-image/API-service → UDS → pinned Chromium renderer acceptance.

No service recreate or host policy changes. Candidate mode creates one disposable
API-image client container, with network:none and a read-only IPC volume only.
Success is transport/structural PNG evidence, never full PGV-13 certification.
"""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib
import uuid

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.pgv13sandbox.activate import validate_report
PROFILE=ROOT/'apps/print-renderer/build/deployment/chromium.seccomp.json'
SOCKET='/run/cisstat-renderer/render.sock'
DEPLOY='apps/print-renderer/build/deployment/docker-compose.yml'
FIELDS=['Image','User','NetworkMode','ReadOnlyRootfs','CapDrop','Privileged','PidsLimit','Memory','SecurityOpt','PortBindings','UsernsMode','CapAdd','Devices']
META='{"Image":{{json .Image}},"User":{{json .Config.User}},'+','.join('"'+k+'":{{json .HostConfig.'+('ReadonlyRootfs' if k=='ReadOnlyRootfs' else k)+'}}' for k in FIELDS[2:])+',"Mounts":{{json .Mounts}}}'


def require(ok,message):
    if not ok:raise ValueError(message)


def validate_renderer_meta(meta):
    require(meta['User']=='10001:10001','renderer UID/GID changed')
    require(meta['NetworkMode']=='none' and not meta['PortBindings'],'renderer network/ports changed')
    require(meta['ReadOnlyRootfs'] is True and meta['Privileged'] is False and meta['CapDrop']==['ALL'],'renderer hardening changed')
    require(meta['PidsLimit']==512 and meta['Memory']==2147483648,'renderer finite budgets changed')
    security=meta['SecurityOpt']
    require('no-new-privileges:true' in security,'renderer NNP missing')
    require([s for s in security if s.startswith('apparmor=')]==['apparmor=docker-default'],'renderer AppArmor differs')
    require(not meta.get('CapAdd') and not meta.get('Devices'),'renderer caps/devices added')
    sec=[s.split('=',1)[1] for s in security if s.startswith('seccomp=')]
    require(len(sec)==1,'reviewed seccomp profile missing')
    if sec[0].lstrip().startswith('{'):
        require(json.loads(sec[0])==json.loads(PROFILE.read_text()),'seccomp content differs')
    else:
        try:matches=json.loads(Path(sec[0]).read_text(encoding='utf-8'))==json.loads(PROFILE.read_text(encoding='utf-8'))
        except (OSError,ValueError):matches=False
        require(matches,'seccomp profile content differs')
    mounts=meta['Mounts']
    require(len(mounts)==1,'renderer extra mounts are forbidden')
    m=mounts[0]
    require(m.get('Type')=='volume' and m.get('Destination')=='/run/cisstat-renderer' and m.get('RW') is True,'renderer IPC volume differs')
    name=m.get('Name','')
    require(bool(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',name)),'unsafe volume name')
    return name


def png_checks(data,expected):
    checks={'signature':data.startswith(b'\x89PNG\r\n\x1a\n'),'crc':True,'dimensions':False,'phys_300ppi':False,'idat':False,'iend':False}
    pos=8
    while checks['signature'] and pos+12<=len(data):
        length=int.from_bytes(data[pos:pos+4],'big');kind=data[pos+4:pos+8]
        if pos+12+length>len(data):checks['crc']=False;break
        content=data[pos+8:pos+8+length]
        crc=int.from_bytes(data[pos+8+length:pos+12+length],'big')
        checks['crc'] &= (zlib.crc32(kind+content)&0xffffffff)==crc
        if kind==b'IHDR' and len(content)==13:checks['dimensions']=struct.unpack('>II',content[:8])==tuple(expected)
        if kind==b'pHYs' and len(content)==9:checks['phys_300ppi']=struct.unpack('>IIB',content)==(11811,11811,1)
        if kind==b'IDAT':checks['idat'] |= bool(content)
        pos+=12+length
        if kind==b'IEND':checks['iend']=length==0 and pos==len(data);break
    return checks


def validate_client_result(result):
    expected=hashlib.sha256((ROOT/'apps/api/png_renderer_client.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    require(result.get('passed') is True and result.get('readiness') is True and result.get('readonly') is True,'native API evidence incomplete')
    require(result.get('client_source_sha256')==expected,'API client source is stale')
    require(result.get('negative_checks')=={'cancel':True,'deadline':True,'request_cap':True},'native cancel/deadline/limit controls incomplete')
    ids=result.get('cancel_request_ids') or []
    require(len(ids)==2 and len(set(ids))==2 and all(re.fullmatch(r'pgv13-uds-[a-f0-9]{32}',v) for v in ids),'native cancellation correlation absent')
    rows=result.get('scenarios') or []
    require([r.get('profile') for r in rows]==['figure-landscape','a4-landscape','a4-portrait'],'native scenarios differ')
    keys={'signature','crc','dimensions','phys_300ppi','idat','iend'}
    for row in rows:
        checks=row.get('checks') or {}
        require(set(checks)==keys and all(value is True for value in checks.values()),'native PNG checks incomplete')
        require(row.get('bytes',0)>512 and bool(re.fullmatch('[a-f0-9]{64}',row.get('sha256',''))),'native PNG evidence malformed')
    require(len({r['sha256'] for r in rows})==3,'native PNG hashes not distinct')


NODE_STATE=r'''
const fs=require('node:fs'),net=require('node:net');
const dir='/run/cisstat-renderer',path=dir+'/render.sock';
const numeric=p=>{try{return Number(fs.readFileSync('/sys/fs/cgroup/'+p,'utf8').trim())}catch{return null}};
const counters=p=>{try{return Object.fromEntries(fs.readFileSync('/sys/fs/cgroup/'+p,'utf8').trim().split('\n').map(s=>{const[k,v]=s.trim().split(/\s+/);return[k,Number(v)]}))}catch{return null}};
const stat=fs.lstatSync(path),folder=fs.lstatSync(dir),status=fs.readFileSync('/proc/self/status','utf8');
const parent_hardening=process.getuid()===10001&&process.getgid()===10001&&/NoNewPrivs:\s+1/.test(status)&&/CapEff:\s+0{16}/.test(status)&&/Seccomp:\s+2/.test(status);
const sock=net.createConnection({host:'127.0.0.1',port:8907});sock.setTimeout(500);
const report=closed=>console.log(JSON.stringify({parent_hardening,tcp_closed:closed,uid:stat.uid,gid:stat.gid,mode:stat.mode&511,directory_mode:folder.mode&511,inode:stat.ino,pids_current:numeric('pids.current'),pids_max:numeric('pids.max'),pids_peak:numeric('pids.peak'),memory_max:numeric('memory.max'),pids_events:counters('pids.events'),memory_events:counters('memory.events')}));
sock.once('connect',()=>{sock.destroy();report(false)});sock.once('timeout',()=>{sock.destroy();report(false)});sock.once('error',e=>report(e.code==='ECONNREFUSED'));
'''
EXPORT_SCENARIOS=r"const s=require('./apps/print-renderer/dist/apps/print-renderer/src/smokeScenarios');process.stdout.write(JSON.stringify([s.cyrillicScenario(),s.ihScenario(),s.a4Scenario()]));"
CLIENT=r'''
import os,json,sys,stat,hashlib,uuid,threading,time,copy
from pathlib import Path
from apps.api import png_renderer_client as module
client=module.PngRendererClient()
print('PGV13_API_PREFLIGHT '+json.dumps({'uid':os.getuid(),'groups':os.getgroups(),'ipc_selected':client.ipc_socket=='/run/cisstat-renderer/render.sock','enabled':client.enabled}),file=sys.stderr,flush=True)
assert client.ipc_socket=='/run/cisstat-renderer/render.sock' and client.enabled
module._validate_unix_endpoint(client.ipc_socket)
marker=Path(client.ipc_socket).parent/('readonly-probe-'+uuid.uuid4().hex)
readonly=False
try:
    marker.write_bytes(b'permission-probe')
except OSError as error:
    import errno
    readonly=error.errno==errno.EROFS
else:marker.unlink()
assert readonly,'API IPC volume must be read-only, even for root'
ready=client.readiness()
assert ready.get('status')=='ready' and ready.get('dependency_status')=='available'
payloads=json.load(sys.stdin)
assert len(payloads)==3
negative_checks={};cancel_ids=[]
for mode in ('cancel','deadline'):
    payload=copy.deepcopy(payloads[-1]);payload['request_id']='pgv13-uds-'+uuid.uuid4().hex
    cancel_ids.append(payload['request_id'])
    cancel=threading.Event();timer=None
    if mode=='cancel':
        timer=threading.Timer(.05,cancel.set);timer.start()
    try:
        client.render_page(payload,timeout_s=5 if mode=='cancel' else .05,cancel_event=cancel)
        raise AssertionError('negative render unexpectedly completed')
    except module.RendererCancelled:
        assert mode=='cancel';negative_checks[mode]=True
    except module.RendererTimeout:
        assert mode=='deadline';negative_checks[mode]=True
    finally:
        if timer:timer.cancel()
    time.sleep(.25)
try:
    client.render_page({'oversize':'x'*module.MAX_REQUEST_BYTES})
    raise AssertionError('oversize request accepted')
except module.RendererPayloadTooLarge:negative_checks['request_cap']=True
results=[]
for payload,geometry in zip(payloads,[(2400,1500),(3508,2480),(2480,3508)]):
    data=client.render_page(payload)
    checks=png_checks(data,geometry)
    assert all(checks.values()) and len(data)>512
    results.append({'profile':payload['snapshot']['print']['profile_id'],'checks':checks,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
assert len({r['sha256'] for r in results})==3
source=Path(module.__file__).read_bytes().replace(b'\r\n',b'\n')
print(json.dumps({'passed':True,'readiness':True,'readonly':readonly,'uid':os.getuid(),'groups':os.getgroups(),'client_source_sha256':hashlib.sha256(source).hexdigest(),'negative_checks':negative_checks,'cancel_request_ids':cancel_ids,'scenarios':results}))
'''
CLIENT='import struct,zlib\n'+inspect.getsource(png_checks)+'\n'+CLIENT


def command(args,*,data=None,timeout=30):
    r=subprocess.run(args,cwd=ROOT,input=data,capture_output=True,text=True,timeout=timeout)
    if r.returncode:
        diagnostic={}
        for line in r.stderr.splitlines():
            if line.startswith('PGV13_API_PREFLIGHT '):
                try:diagnostic['client_preflight']=json.loads(line.split(' ',1)[1])
                except ValueError:pass
            match=re.match(r'(?:[\w.]+\.)?(Renderer\w+|AssertionError|PermissionError|FileNotFoundError|ModuleNotFoundError):',line)
            if match:diagnostic['reason_type']=match.group(1)
        error=RuntimeError('command failed: '+args[0]+' (exit '+str(r.returncode)+')')
        error.diagnostic=diagnostic
        raise error
    return r.stdout.strip()


def metrics_ok(before,after):
    for row in (before,after):
        require(row.get('parent_hardening') is True and row.get('tcp_closed') is True,'native parent/TCP invariant failed')
        require((row.get('uid'),row.get('gid'),row.get('mode'),row.get('directory_mode'))==(10001,10001,0o660,0o750),'native socket UID/GID/mode failed')
        require(row.get('pids_max')==512 and row.get('memory_max')==2147483648,'native cgroup budget failed')
    for field,counter in [('pids_events','max'),('memory_events','oom'),('memory_events','oom_kill')]:
        a=(before.get(field) or {}).get(counter);b=(after.get(field) or {}).get(counter)
        require(isinstance(a,int) and isinstance(b,int) and b==a,'new/missing PID or OOM events')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renderer-project',required=True)
    parser.add_argument('--api-project',default='cisstat-stack')
    parser.add_argument('--sandbox-report',type=Path,required=True)
    parser.add_argument('--api-image',help='Candidate mode: disposable API-image client; otherwise live cisstat-stack api')
    parser.add_argument('--previous-report',type=Path,help='Require successful acceptance across a deliberate renderer recreate')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    report={'passed':False,'pgv13_certified':False}
    disposable_name=None
    args.out.write_text(json.dumps({**report,'state':'RUNNING'})+'\n')
    try:
        report['phase']='sandbox_report'
        expected_image=validate_report(json.loads(args.sandbox_report.read_text()))
        require(os.environ.get('CISSTAT_UDS_RENDERER_IMAGE')==expected_image,'pin must match new-image A/B report')
        report['phase']='renderer_metadata'
        compose=['docker','compose','-p',args.renderer_project,'-f',DEPLOY]
        cid=command(compose+['ps','-q','print-renderer'])
        require(bool(cid) and '\n' not in cid,'expected one renderer')
        meta=json.loads(command(['docker','inspect','--format',META,cid]))
        require(meta['Image']==expected_image,'running renderer is not the tested image')
        volume=validate_renderer_meta(meta)
        report.update(image_id=expected_image,renderer_container_id=cid,volume=volume,phase='lifetime_lock')
        # Exit73 is reserved by flock for an actual lock conflict, not an
        # arbitrary setup failure. No node/browser process starts in this probe.
        lock_name='cisstat-uds-lock-'+uuid.uuid4().hex
        try:
            locked=subprocess.run(['docker','run','--rm','--name',lock_name,'--pull=never','--network=none','--read-only',
                '--user=10001:10001','--cap-drop=ALL','--security-opt=no-new-privileges:true',
                '--mount','type=volume,source='+volume+',target=/run/cisstat-renderer',expected_image,
                'flock','--nonblock','--conflict-exit-code','73','/run/cisstat-renderer/renderer.lock','true'],
                cwd=ROOT,capture_output=True,text=True,timeout=30)
            require(locked.returncode==73,'renderer does not hold the exclusive lifetime lock')
        finally:
            subprocess.run(['docker','rm','-f',lock_name],capture_output=True,timeout=15)
        before=json.loads(command(compose+['exec','-T','print-renderer','node','-e',NODE_STATE]))
        report.update(before=before,phase='api_png_roundtrip')
        payloads=command(compose+['exec','-T','print-renderer','node','-e',EXPORT_SCENARIOS])
        if args.api_image:
            report['api_image_id']=command(['docker','image','inspect','--format','{{.Id}}',args.api_image])
            require(re.fullmatch('sha256:[a-f0-9]{64}',report['api_image_id']),'candidate API image ID malformed')
            disposable_name='cisstat-uds-api-'+uuid.uuid4().hex
            api=['docker','run','--rm','--name',disposable_name,'-i','--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true',
                 '--group-add=10001','--memory=512m','--pids-limit=32',
                 '--mount','type=volume,source='+volume+',target=/run/cisstat-renderer,readonly,volume-nocopy',
                 '--env','CISSTAT_PNG_RENDERER_IPC='+SOCKET,'--env','CISSTAT_PNG_RENDERER_ENABLED=1',args.api_image,'python','-c',CLIENT]
        else:
            api_compose=['docker','compose','-p',args.api_project,'--project-directory','deployment/cisstat-stack','-f','deployment/cisstat-stack/docker-compose.yml','-f','deployment/cisstat-stack/docker-compose.renderer-uds.yml']
            api_cid=command(api_compose+['ps','-q','api'])
            require(bool(api_cid) and '\n' not in api_cid,'expected one live API')
            api_meta=json.loads(command(['docker','inspect','--format',META,api_cid]))
            mounts=[m for m in api_meta['Mounts'] if m.get('Destination')=='/run/cisstat-renderer']
            require(len(mounts)==1 and mounts[0].get('Name')==volume and mounts[0].get('RW') is False,'API volume differs/not RO')
            require(api_meta['UsernsMode']==meta['UsernsMode'],'API/renderer userns differ')
            api=api_compose+['exec','-T','api','python','-c',CLIENT]
        result=json.loads(command(api,data=payloads,timeout=300))
        validate_client_result(result)
        # The client exception alone is not proof that renderer saw disconnect.
        raw_logs=command(['docker','logs','--since','10m',cid])
        cancelled=set()
        for line in raw_logs.splitlines():
            try:entry=json.loads(line)
            except ValueError:continue
            if entry.get('event')=='render_cancelled':cancelled.add(entry.get('request_id'))
        require(set(result['cancel_request_ids'])<=cancelled,'renderer did not observe correlated disconnects')
        after=json.loads(command(compose+['exec','-T','print-renderer','node','-e',NODE_STATE]))
        report.update(after=after,phase='native_metrics')
        metrics_ok(before,after)
        if args.previous_report:
            previous=json.loads(args.previous_report.read_text())
            require(previous.get('passed') is True and previous.get('image_id')==expected_image,'previous acceptance differs')
            require(previous.get('renderer_container_id')!=cid,'renderer was not recreated')
            require(previous.get('volume')==volume,'recreate must keep the same IPC volume')
        report.update(passed=True,phase='complete',lifetime_lock=True,image_id=expected_image,renderer_container_id=cid,volume=volume,
            mode='candidate-api-image' if args.api_image else 'live-api',before=before,after=after,client=result,
            recreate_verified=bool(args.previous_report))
        code=0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.SubprocessError) as error:
        report.update(setup_error=type(error).__name__,detail=str(error),**getattr(error,'diagnostic',{}));code=2
    finally:
        if disposable_name:
            try:subprocess.run(['docker','rm','-f',disposable_name],capture_output=True,timeout=15)
            except (OSError,subprocess.SubprocessError):pass
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
