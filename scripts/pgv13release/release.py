"""Coherent PGV-13 image bundle. Docker operations run only on the selected host.

Build/capture/check are separate; apply/rollback require a quiesced publisher
assertion. No DB mutation, image pull, volume deletion or automatic rollback.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.pgv13sandbox.activate import validate_report as validate_ab
from scripts.pgv13uds import verify_vm as V

PROFILE=ROOT/'apps/print-renderer/build/deployment/chromium.seccomp.json'
STACK=ROOT/'deployment/cisstat-stack/docker-compose.yml'
RENDERER=ROOT/'apps/print-renderer/build/deployment/docker-compose.yml'
SOCKET='/run/cisstat-renderer/render.sock'
ROLES=('api','web','print-renderer')
IPC_KEYS=('CISSTAT_PNG_RENDERER_IPC','CISSTAT_PNG_RENDERER_URL',
          'CISSTAT_PNG_RENDERER_ENABLED','CISSTAT_PNG_RENDERER_TIMEOUT_S')
DOCKERFILES={'api':'apps/api/Dockerfile','web':'apps/standalone/Dockerfile',
             'print-renderer':'apps/print-renderer/build/Dockerfile'}
IMAGE_META='{"id":{{json .Id}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},"tree":{{json (index .Config.Labels "io.cisstat.source-tree")}}}'
CURRENT_META='{"Image":{{json .Image}},"Mounts":{{json .Mounts}},"AppArmor":{{json .AppArmorProfile}},"User":{{json .Config.User}},"NetworkMode":{{json .HostConfig.NetworkMode}},"ReadOnly":{{json .HostConfig.ReadonlyRootfs}},"CapDrop":{{json .HostConfig.CapDrop}},"CapAdd":{{json .HostConfig.CapAdd}},"Privileged":{{json .HostConfig.Privileged}},"PidsLimit":{{json .HostConfig.PidsLimit}},"Memory":{{json .HostConfig.Memory}},"SecurityOpt":{{json .HostConfig.SecurityOpt}}}'
CURRENT_META=CURRENT_META[:-1]+',"PortBindings":{{json .HostConfig.PortBindings}},"Devices":{{json .HostConfig.Devices}},"Init":{{json .HostConfig.Init}},"ShmSize":{{json .HostConfig.ShmSize}},"UsernsMode":{{json .HostConfig.UsernsMode}},"Cmd":{{json .Config.Cmd}}}'


def require(value,message):
    if not value:raise ValueError(message)


def digest(data):return hashlib.sha256(data).hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.chmod(0o600);tmp.replace(path)


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def command(args,*,env=None,log=None):
    if log:
        with Path(log).open('w',encoding='utf-8') as out:
            r=subprocess.run(args,cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=3600)
        require(r.returncode==0,'Image build failed; inspect private build log')
        return ''
    r=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
    require(r.returncode==0,'Command failed; inspect Docker/Compose locally (output withheld)')
    return r.stdout.strip()


def validate_manifest(m):
    require(m.get('schema_version')=='pgv13.release/1' and m.get('state')=='BUILT','Incomplete release manifest')
    require(all(re.fullmatch('[a-f0-9]{40}',m.get(k,'')) for k in ['revision','tree']),'Unverified source revision/tree')
    require(re.fullmatch('[a-f0-9]{12}',m.get('release_id','')),'Invalid release ID')
    require(set(m.get('images',{}))==set(ROLES),'Three image roles required')
    require(all(re.fullmatch('sha256:[a-f0-9]{64}',x) for x in m['images'].values()),'Mutable/unverified image')
    require(len(set(m['images'].values()))==3,'Image roles cannot alias')
    prefix='cisstat_renderer_ipc_'+m['release_id']
    require(m.get('volume')==prefix and m.get('candidate_volume')==prefix+'_candidate','Dedicated distinct release volumes required')
    require(m.get('candidate_project')=='cisstat-pgv13-'+m['release_id']+'-candidate','Candidate project differs')
    require(m.get('profile_sha256')==digest(PROFILE.read_bytes()),'Reviewed profile changed')


def validate_image(meta,m,role):
    require(meta=={'id':m['images'][role],'revision':m['revision'],'tree':m['tree']},'Image ID/revision/tree mismatch: '+role)


def models(m,profile,candidate):
    volume=m['candidate_volume'] if candidate else m['volume']
    mount={'type':'volume','source':'renderer_ipc','target':'/run/cisstat-renderer'}
    definition={'renderer_ipc':{'external':True,'name':volume}}
    stack={'services':{'api':{'image':m['images']['api'],'pull_policy':'never',
        'environment':{'CISSTAT_PNG_RENDERER_IPC':SOCKET,'CISSTAT_PNG_RENDERER_ENABLED':'1','CISSTAT_PNG_RENDERER_TIMEOUT_S':'60'},
        'group_add':['10001'],'volumes':[{**mount,'read_only':True,'volume':{'nocopy':True}}]},
        'web':{'image':m['images']['web'],'pull_policy':'never'}},'volumes':definition}
    renderer={'services':{'print-renderer':{'image':m['images']['print-renderer'],'pull_policy':'never',
        'user':'10001:10001','network_mode':'none','read_only':True,'init':True,'cap_drop':['ALL'],
        'security_opt':['no-new-privileges:true','apparmor=docker-default','seccomp='+str(profile)],
        'mem_limit':'2g','pids_limit':512,'shm_size':'256m',
        'tmpfs':['/tmp:rw,noexec,nosuid,size=512m,mode=1777'],
        'environment':{'CISSTAT_PRINT_RENDERER_SOCKET':SOCKET,'CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S':'60',
                       'CISSTAT_PRINT_RENDERER_MAX_CONCURRENT':'2','CISSTAT_PRINT_RENDERER_TMP_DIR':'/tmp'},
        'volumes':[mount],
        'healthcheck':{'test':['CMD','node','apps/print-renderer/dist/apps/print-renderer/src/healthcheck.js']}}},'volumes':definition}
    return stack,renderer


def normalized_security(values):
    values=[s.replace('no-new-privileges=true','no-new-privileges:true') for s in values]
    return {s.replace('seccomp:','seccomp=',1).replace('apparmor:','apparmor=',1) for s in values}


def bytesize(v):
    text=str(v).lower();match=re.fullmatch('(\\d+)([mg])',text)
    return int(match[1])*1024**(2 if match[2]=='m' else 3) if match else int(text)


def validate_models(m,stack,renderer,profile):
    a=stack['services']['api'];w=stack['services']['web'];r=renderer['services']['print-renderer']
    require(a['image']==m['images']['api'] and w['image']==m['images']['web'] and r['image']==m['images']['print-renderer'],'Coherent image IDs lost')
    require(a['environment'].get('CISSTAT_PNG_RENDERER_IPC')==SOCKET and a['environment'].get('CISSTAT_PNG_RENDERER_ENABLED')=='1','API IPC differs')
    require('10001' in [str(v) for v in a.get('group_add',[])],'API supplementary GID lost')
    mounts=[v for v in a.get('volumes',[]) if v.get('target')=='/run/cisstat-renderer']
    require(len(mounts)==1 and mounts[0].get('source')=='renderer_ipc' and mounts[0].get('read_only') is True and mounts[0].get('volume',{}).get('nocopy') is True,'API IPC mount must remain RO/nocopy')
    require(r.get('user')=='10001:10001' and r.get('network_mode')=='none' and not r.get('networks') and not r.get('ports'),'Renderer UID/network changed')
    require(r.get('read_only') is True and r.get('init') is True and r.get('cap_drop')==['ALL'] and not r.get('cap_add') and not r.get('privileged'),'Renderer hardening changed')
    require(not any(r.get(k) for k in ['devices','pid','ipc','container_name']),'Renderer namespace/device exposure')
    require(a.get('userns_mode','')==r.get('userns_mode',''),'API/renderer user namespace configuration differs')
    require(bytesize(r['mem_limit'])==2147483648 and r['pids_limit']==512 and bytesize(r['shm_size'])==268435456,'Renderer budgets changed')
    require(r.get('tmpfs')==['/tmp:rw,noexec,nosuid,size=512m,mode=1777'],'Renderer tmpfs changed')
    require(normalized_security(r.get('security_opt',[]))=={'no-new-privileges:true','apparmor=docker-default','seccomp='+str(profile)},'Renderer policy changed')
    require(r['environment'].get('CISSTAT_PRINT_RENDERER_SOCKET')==SOCKET,'Renderer IPC differs')
    mounts=r.get('volumes') or []
    require(len(mounts)==1 and all(mounts[0].get(k)==v for k,v in {'type':'volume','source':'renderer_ipc','target':'/run/cisstat-renderer'}.items())
            and not mounts[0].get('read_only') and set(mounts[0].get('volume',{}))<=set(['nocopy'])
            and not mounts[0].get('volume',{}).get('nocopy'),'Renderer extra/missing mounts')
    for config in [stack,renderer]:
        require(config['volumes']['renderer_ipc']=={'external':True,'name':m['volume']},'Shared production volume differs')


def validate_native(native):
    require(native.get('lifetime_lock') is True,'Native lifetime lock not proven')
    V.validate_client_result(native.get('client',{}))
    V.metrics_ok(native['before'],native['after'])


def validate_evidence(m,ab,native):
    require(validate_ab(ab)==m['images']['print-renderer'],'A/B image differs from release')
    require(ab.get('image_id')==m['images']['print-renderer'] and ab.get('source_revision')==m['revision'] and ab.get('source_tree')==m['tree'],'A/B source identity differs; old reports cannot authorize new images')
    require(ab.get('pids_limit')==512 and all(row.get('probe',{}).get('limits')=={'pids_max':512,'memory_max':2147483648} for row in ab['rows']),'A/B finite capacity evidence differs')
    require(native.get('passed') is True and native.get('pgv13_certified') is False and native.get('recreate_verified') is True,'Successful candidate/recreate required')
    require(native.get('mode')=='candidate-api-image' and native.get('api_image_id')==m['images']['api'] and native.get('image_id')==m['images']['print-renderer'] and native.get('volume')==m['candidate_volume'],'Candidate image/IPC differs')
    validate_native(native)


def safe_baseline(stack,renderer,images,current):
    api=stack['services']['api'];r=renderer['services']['print-renderer']
    allowed={'image','user','network_mode','read_only','init','cap_drop','cap_add','privileged','security_opt','tmpfs','shm_size','mem_limit','pids_limit','environment','volumes','healthcheck','restart','stop_grace_period'}
    require(not r.get('container_name') and not any(r.get(k) for k in ['ports','devices','networks','pid','ipc','command','entrypoint','userns_mode']),'Unsupported baseline renderer exposure/command')
    known={'CISSTAT_PRINT_RENDERER_SOCKET','CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S','CISSTAT_PRINT_RENDERER_MAX_CONCURRENT','CISSTAT_PRINT_RENDERER_TMP_DIR','CISSTAT_PRINT_RENDERER_PORT','HOME'}
    require(set(r.get('environment',{}))<=known,'Unsupported renderer environment; review before capture')
    ipc=api.get('environment',{}).get('CISSTAT_PNG_RENDERER_IPC')
    transport='uds' if ipc else 'legacy'
    rr={k:copy.deepcopy(v) for k,v in r.items() if k in allowed}
    rr['image']=images['print-renderer'];rr['pull_policy']='never'
    s={'services':{'api':{'image':images['api'],'pull_policy':'never',
        'environment':{k:api.get('environment',{}).get(k) or '' for k in IPC_KEYS},
        'volumes':[copy.deepcopy(v) for v in api.get('volumes',[]) if v.get('target')=='/run/cisstat-renderer']},
        'web':{'image':images['web'],'pull_policy':'never'}}}
    if transport=='uds':
        s['services']['api']['environment']['CISSTAT_PNG_RENDERER_URL']=''
        require(ipc==SOCKET and r.get('environment',{}).get('CISSTAT_PRINT_RENDERER_SOCKET')==SOCKET,'Baseline IPC endpoints differ')
        require(len(rr.get('volumes',[]))==1 and len(s['services']['api']['volumes'])==1,'Baseline IPC mounts absent')
        s['services']['api']['group_add']=copy.deepcopy(api.get('group_add',[]))
        definitions=copy.deepcopy(renderer.get('volumes',{}))
        source=rr['volumes'][0]['source']
        require(source==s['services']['api']['volumes'][0]['source'],'Baseline volume keys differ')
        require(stack['volumes'][source].get('name')==definitions[source].get('name'),'Baseline volume names differ')
        definitions={source:definitions[source]};definitions[source].pop('driver',None)
        s['volumes']=copy.deepcopy(definitions)
    else:
        require(s['services']['api']['environment']['CISSTAT_PNG_RENDERER_URL'] in ['', 'http://127.0.0.1:8907'],'Custom legacy URL requires operator review, not secret serialization')
        require(not rr.get('volumes') and not s['services']['api']['volumes'] and not r.get('environment',{}).get('CISSTAT_PRINT_RENDERER_SOCKET'),'Ambiguous baseline IPC/legacy mixture')
        definitions={}
    return {'transport':transport,'images':images,'stack':s,
            'renderer':{'services':{'print-renderer':rr},'volumes':definitions}}


def validate_current(m,baseline,current,rollback,allow_missing=False):
    for role in ROLES:
        permitted={baseline[role],m['images'][role]} if rollback else {baseline[role]}
        if rollback and allow_missing:permitted.add(None)
        require(current.get(role) in permitted,'Live image changed since baseline capture: '+role)


def compose(project,files,renderer=False):
    result=['docker','compose','--project-directory',str(RENDERER.parent if renderer else STACK.parent),'-p',project]
    for f in files:result+=['-f',str(f)]
    return result


def current_state(stack_cmd,render_cmd,allow_missing=False):
    ids={};meta={};cids={}
    for role in ROLES:
        cmd=render_cmd if role=='print-renderer' else stack_cmd
        cid=command(cmd+['ps','-a','-q',role])
        if not cid and allow_missing:
            ids[role]=None;meta[role]={};cids[role]=None;continue
        require(bool(cid) and '\n' not in cid,'Expected exactly one existing service: '+role)
        data=json.loads(command(['docker','inspect','--format',CURRENT_META,cid]))
        ids[role]=data['Image'];meta[role]=data;cids[role]=cid
    return ids,meta,cids


def bundle_load(path):
    b=Path(path).resolve();m=read(b/'manifest.json');validate_manifest(m)
    require(set(m.get('files',{}))=={'stack.json','renderer.json','candidate.json','seccomp.json'},'Exact generated bundle file set required')
    for name,sha in m['files'].items():
        require(name in ['stack.json','renderer.json','candidate.json','seccomp.json'],'Unexpected generated bundle path')
        require(digest((b/name).read_bytes())==sha,'Generated bundle file changed')
    return b,m


def verify_images(m):
    for role in ROLES:
        meta=json.loads(command(['docker','image','inspect','--format',IMAGE_META,m['images'][role]]))
        validate_image(meta,m,role)
        marker=json.loads(command(['docker','run','--rm','--pull=never','--network=none','--read-only','--cap-drop=ALL',
            '--security-opt=no-new-privileges:true','--entrypoint=cat',m['images'][role],'/usr/local/share/cisstat/build.json']))
        require(marker=={'revision':m['revision'],'tree':m['tree']},'Inside-image revision marker differs: '+role)


def build(args):
    b=Path(args.bundle).resolve();require(ROOT not in b.parents and b!=ROOT,'Release bundle must be outside the checkout')
    require(not b.exists(),'Use a new empty bundle directory')
    b.mkdir(mode=0o700,parents=True)
    write(b/'manifest.json',{'schema_version':'pgv13.release/1','state':'BUILDING','pgv13_certified':False})
    require(not command(['git','status','--porcelain','--untracked-files=normal']),'Build requires a clean committed checkout')
    rev=command(['git','rev-parse','HEAD']);tree=command(['git','rev-parse','HEAD^{tree}']);rid=uuid4().hex[:12]
    command([sys.executable,'scripts/auth00/check_committed.py','--target','head'])
    tags={r:'cisstat-'+r+':pgv13-'+rev[:12]+'-'+rid for r in ROLES}
    write(b/'build-stack.json',{'services':{r:{'image':tags[r]} for r in ['api','web']}})
    files=[Path(f).resolve() for f in (args.stack_file or [STACK])]
    cmd=compose(args.stack_project,files+[b/'build-stack.json'])
    command(cmd+['build','--build-arg','CISSTAT_SOURCE_REVISION='+rev,'--build-arg','CISSTAT_SOURCE_TREE='+tree,'api','web'],log=b/'build-api-web.log')
    command(['docker','build','--build-arg','CISSTAT_SOURCE_REVISION='+rev,'--build-arg','CISSTAT_SOURCE_TREE='+tree,
             '-f',DOCKERFILES['print-renderer'],'-t',tags['print-renderer'],'.'],log=b/'build-renderer.log')
    images={r:command(['docker','image','inspect','--format','{{.Id}}',tags[r]]) for r in ROLES}
    m={'schema_version':'pgv13.release/1','state':'BUILT','revision':rev,'tree':tree,'release_id':rid,'images':images,
       'profile_sha256':digest(PROFILE.read_bytes()),'volume':'cisstat_renderer_ipc_'+rid,
       'candidate_volume':'cisstat_renderer_ipc_'+rid+'_candidate','candidate_project':'cisstat-pgv13-'+rid+'-candidate'}
    validate_manifest(m);verify_images(m)
    require(command(['git','rev-parse','HEAD'])==rev and not command(['git','status','--porcelain','--untracked-files=normal']),'Source changed while images were building')
    command([sys.executable,'scripts/auth00/check_committed.py','--target','head'])
    (b/'seccomp.json').write_bytes(PROFILE.read_bytes())
    stack,renderer=models(m,b/'seccomp.json',False);_,candidate=models(m,b/'seccomp.json',True)
    for name,obj in [('stack.json',stack),('renderer.json',renderer),('candidate.json',candidate)]:write(b/name,obj)
    m['files']={n:digest((b/n).read_bytes()) for n in ['stack.json','renderer.json','candidate.json','seccomp.json']}
    write(b/'manifest.json',m)
    pins={'CISSTAT_UDS_RENDERER_IMAGE':images['print-renderer'],'CISSTAT_VALIDATED_RENDERER_IMAGE':images['print-renderer'],
          'CISSTAT_RENDERER_SECCOMP_FILE':str(b/'seccomp.json'),'CISSTAT_RENDERER_IPC_VOLUME':m['volume'],
          'PGV13_CANDIDATE_PROJECT':m['candidate_project'],'PGV13_SOURCE_REVISION':rev,'PGV13_SOURCE_TREE':tree,
          'PGV13_API_IMAGE':images['api'],'PGV13_WEB_IMAGE':images['web']}
    (b/'pins.env').write_text(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in pins.items()),encoding='utf-8')
    return {'built':True,'revision':rev,'tree':tree,'images':images,'bundle':str(b),'pgv13_certified':False}


def check_baseline_live(stack,renderer,meta,cids,stack_cmd):
    r=renderer['services']['print-renderer'];live=meta['print-renderer']
    require(live['User']=='10001:10001' and live['NetworkMode']=='none' and live['ReadOnly'] is True and live['CapDrop']==['ALL'] and not live['CapAdd'] and not live['Privileged'] and live['AppArmor']=='docker-default','Unsupported live renderer hardening')
    require(not live['PortBindings'] and not live['Devices'] and live['Init'] is True and not live['UsernsMode'],'Unsupported live renderer exposure/namespaces/init')
    require(bytesize(r['shm_size'])==live['ShmSize'],'Baseline shared memory differs')
    require(live['Cmd']==json.loads(command(['docker','image','inspect','--format','{{json .Config.Cmd}}',live['Image']])),'Live renderer command overrides its image')
    require(r.get('user')=='10001:10001' and r.get('network_mode')=='none' and r.get('read_only') is True and r.get('cap_drop')==['ALL'],'Baseline files do not describe live renderer')
    require(int(r['pids_limit'])==live['PidsLimit'] and bytesize(r['mem_limit'])==live['Memory'],'Baseline resource limits differ')
    expected=normalized_security(r.get('security_opt',[]));actual=normalized_security(live['SecurityOpt'])
    require('no-new-privileges:true' in expected and 'no-new-privileges:true' in actual,'Baseline NNP absent')
    # Docker may normalize seccomp to inline JSON. Only the already-reviewed
    # profile or builtin is eligible for automatic rollback.
    for opts in [expected,actual]:
        for option in opts:
            if option.startswith('seccomp='):
                value=option.split('=',1)[1]
                policy=json.loads(value) if value.startswith('{') else read(value)
                require(policy==read(PROFILE),'Unknown baseline seccomp policy')
            else:require(option in ['no-new-privileges:true','apparmor=docker-default'],'Unknown baseline security option')
    require(any(v.startswith('seccomp=') for v in expected)==any(v.startswith('seccomp=') for v in actual),'Baseline seccomp selection differs')
    code='import os,json;print(json.dumps({k:os.getenv(k) or "" for k in '+repr(IPC_KEYS)+'}))'
    env=json.loads(command(stack_cmd+['exec','-T','api','python','-c',code]))
    require(env=={k:stack['services']['api'].get('environment',{}).get(k) or '' for k in IPC_KEYS},'Baseline API IPC settings differ from live service')
    node="console.log(JSON.stringify(Object.fromEntries("+json.dumps(list(r.get('environment',{}))+['CISSTAT_PRINT_RENDERER_SOCKET'])+".map(k=>[k,process.env[k]||'']))))"
    render_cmd=compose(command_project_from_cid(cids['print-renderer']),[RENDERER],True)
    renderer_env=json.loads(command(render_cmd+['exec','-T','print-renderer','node','-e',node]))
    require(renderer_env=={k:str(r.get('environment',{}).get(k) or '') for k in renderer_env},'Baseline renderer environment differs from live service')
    for role,model in [('api',stack['services']['api']),('print-renderer',r)]:
        actual=[v for v in meta[role]['Mounts'] if v['Destination']=='/run/cisstat-renderer']
        expected=[v for v in model.get('volumes',[]) if v.get('target')=='/run/cisstat-renderer']
        require(len(actual)==len(expected) and (role!='print-renderer' or len(meta[role]['Mounts'])==len(actual)),'Baseline live mount count differs')
        if expected:
            a,e=actual[0],expected[0];definition=(renderer if role=='print-renderer' else stack)['volumes'][e['source']]
            require(a.get('Type')=='volume' and a.get('Name')==definition.get('name') and a.get('RW') is (not e.get('read_only',False)),'Baseline live IPC mount differs')


def command_project_from_cid(cid):
    value=command(['docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',cid])
    require(bool(re.fullmatch('[a-z0-9][a-z0-9_-]*',value)),'Container project label missing')
    return value


def compose_files_from_cid(cid):
    value=command(['docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project.config_files"}}',cid])
    paths=[Path(p).resolve() for p in value.split(',') if p]
    require(paths and all(p.is_file() and p.suffix in ['.yml','.yaml','.json'] for p in paths),'Compose input labels unavailable; supply explicit original --stack-file/--renderer-file')
    return paths


def capture(args):
    b,m=bundle_load(args.bundle);require(not (b/'baseline.json').exists(),'Baseline is immutable; use a new release bundle')
    read_sc=compose(args.stack_project,[STACK]);read_rc=compose(args.renderer_project,[RENDERER],True)
    ids,meta,cids=current_state(read_sc,read_rc)
    sf=[Path(f).resolve() for f in args.stack_file] if args.stack_file else compose_files_from_cid(cids['api'])
    rf=[Path(f).resolve() for f in args.renderer_file] if args.renderer_file else compose_files_from_cid(cids['print-renderer'])
    require(sf==compose_files_from_cid(cids['web']),'API/web baseline compose input lists differ')
    sc=compose(args.stack_project,sf);rc=compose(args.renderer_project,rf,True)
    env={**os.environ,'CISSTAT_VALIDATED_RENDERER_IMAGE':ids['print-renderer'],
         'CISSTAT_UDS_RENDERER_IMAGE':ids['print-renderer'],'CISSTAT_RENDERER_SECCOMP_FILE':str(PROFILE)}
    ipc=[v for v in meta['print-renderer']['Mounts'] if v['Destination']=='/run/cisstat-renderer']
    if ipc:env['CISSTAT_RENDERER_IPC_VOLUME']=ipc[0]['Name']
    stack=json.loads(command(sc+['config','--format','json'],env=env));renderer=json.loads(command(rc+['config','--format','json'],env=env))
    check_baseline_live(stack,renderer,meta,cids,read_sc)
    old=safe_baseline(stack,renderer,ids,meta)
    # Preserve the old reviewed profile bytes instead of following a mutable path.
    opts=old['renderer']['services']['print-renderer'].get('security_opt',[])
    if any(s.startswith(('seccomp=','seccomp:')) for s in opts):
        (b/'baseline-seccomp.json').write_bytes(PROFILE.read_bytes())
        old['renderer']['services']['print-renderer']['security_opt']=[
            'seccomp='+str(b/'baseline-seccomp.json') if s.startswith(('seccomp=','seccomp:')) else s for s in opts]
    write(b/'baseline-stack.json',old.pop('stack'));write(b/'baseline-renderer.json',old.pop('renderer'))
    old.update(stack_project=args.stack_project,renderer_project=args.renderer_project,
        stack_files=[str(f) for f in sf],renderer_files=[str(f) for f in rf],
        inputs={str(f):digest(f.read_bytes()) for f in sf+rf},
        files={n:digest((b/n).read_bytes()) for n in ['baseline-stack.json','baseline-renderer.json']+(['baseline-seccomp.json'] if (b/'baseline-seccomp.json').exists() else [])})
    write(b/'baseline.json',old)
    return {'captured':True,'images':ids,'transport':old['transport'],'pgv13_certified':False}


def load_baseline(b):
    old=read(b/'baseline.json')
    for name,sha in old['inputs'].items():require(digest(Path(name).read_bytes())==sha,'Baseline compose input changed')
    for name,sha in old['files'].items():
        require(name in ['baseline-stack.json','baseline-renderer.json','baseline-seccomp.json'],'Unexpected baseline bundle path')
        require(digest((b/name).read_bytes())==sha,'Baseline snapshot changed')
    return old


def preflight(args,rollback=False):
    b,m=bundle_load(args.bundle);old=load_baseline(b)
    sc=compose(old['stack_project'],[STACK]);rc=compose(old['renderer_project'],[RENDERER],True)
    journal=read(b/'operation.json') if (b/'operation.json').exists() else {}
    missing_allowed=rollback and journal.get('mutation_started') is True and journal.get('action') in ['apply','rollback']
    ids,_,_=current_state(sc,rc,missing_allowed);validate_current(m,old['images'],ids,rollback,missing_allowed)
    if rollback:
        for image in old['images'].values():require(command(['docker','image','inspect','--format','{{.Id}}',image])==image,'Rollback image missing')
    else:
        require(command(['git','rev-parse','HEAD'])==m['revision'],'Use the exact source checkout that built this release')
        require(not command(['git','status','--porcelain','--untracked-files=normal']),'Deployment source is no longer clean')
        verify_images(m)
        validate_evidence(m,read(args.ab_report),read(args.native_report))
        newsc=compose(old['stack_project'],old['stack_files']+[str(b/'stack.json')])
        newrc=compose(old['renderer_project'],[RENDERER,b/'renderer.json'],True)
        stack=json.loads(command(newsc+['config','--format','json']));renderer=json.loads(command(newrc+['config','--format','json']))
        validate_models(m,stack,renderer,b/'seccomp.json')
        volume=json.loads(command(['docker','volume','inspect','--format','{{json .Labels}}',m['volume']]))
        require(volume.get('io.cisstat.release.id')==m['release_id'],'Production IPC volume was not prepared by this release')
        check_ipc_volume(m,m['volume'])
    return {'passed':True,'rollback':rollback,'images':old['images'] if rollback else m['images'],'pgv13_certified':False}


def prepare(args):
    b,m=bundle_load(args.bundle);verify_images(m)
    for name in [m['volume'],m['candidate_volume']]:
        command(['docker','volume','create','--label','io.cisstat.release.id='+m['release_id'],name])
        labels=json.loads(command(['docker','volume','inspect','--format','{{json .Labels}}',name]))
        require(labels.get('io.cisstat.release.id')==m['release_id'],'Existing unrelated IPC volume refused')
        command(['docker','run','--rm','--pull=never','--network=none','--read-only','--user=10001:10001',
            '--cap-drop=ALL','--security-opt=no-new-privileges:true','--mount','type=volume,source='+name+',target=/run/cisstat-renderer',
            '--env','CISSTAT_PRINT_RENDERER_SOCKET='+SOCKET,m['images']['print-renderer'],
            'node','apps/print-renderer/dist/apps/print-renderer/src/socketTransport.js'])
    return {'prepared':True,'volumes':[m['volume'],m['candidate_volume']],'pgv13_certified':False}


def check_ipc_volume(m,name):
    code="const f=require('node:fs');const d='/run/cisstat-renderer';for(const[p,mode,dir]of [[d,0o750,true],[d+'/renderer.lock',0o600,false],[d+'/.layout-v1',0o640,false]]){const s=f.lstatSync(p);if(s.uid!==10001||s.gid!==10001||(s.mode&0o7777)!==mode||s.isSymbolicLink()||(dir?!s.isDirectory():!s.isFile()))process.exit(2);}console.log('private IPC layout verified')"
    command(['docker','run','--rm','--pull=never','--network=none','--read-only','--user=10001:10001','--cap-drop=ALL',
        '--security-opt=no-new-privileges:true','--mount','type=volume,source='+name+',target=/run/cisstat-renderer,readonly,volume-nocopy',
        m['images']['print-renderer'],'node','-e',code])


def switch(args,rollback=False):
    b,m=bundle_load(args.bundle);old=load_baseline(b)
    sc=compose(old['stack_project'],old['stack_files']+[str(b/('baseline-stack.json' if rollback else 'stack.json'))])
    rc=compose(old['renderer_project'],[RENDERER,b/('baseline-renderer.json' if rollback else 'renderer.json')],True)
    journal={'action':'rollback' if rollback else 'apply','mutation_started':True,'phase':'stop_publishers','pgv13_certified':False}
    write(b/'operation.json',journal)
    try:
        command(sc+['stop','web','api'])
        journal['phase']='renderer';write(b/'operation.json',journal)
        command(rc+['up','-d','--no-deps','--no-build','--pull','never','--force-recreate','print-renderer'])
        journal['phase']='api_web';write(b/'operation.json',journal)
        command(sc+['up','-d','--no-deps','--no-build','--pull','never','--force-recreate','api','web'])
        ids,_,_=current_state(sc,rc)
        require(ids==(old['images'] if rollback else m['images']),'Started images differ from pinned release')
        journal.update(phase='started',images=ids,readiness_checked=False)
        write(b/'operation.json',journal)
        return journal
    except Exception:
        journal.update(failed=True,readiness_checked=False);write(b/'operation.json',journal)
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['build','capture','prepare-ipc','check','apply','rollback'])
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--stack-project',default='cisstat-stack')
    p.add_argument('--renderer-project')
    p.add_argument('--stack-file',action='append',type=Path)
    p.add_argument('--renderer-file',action='append',type=Path)
    p.add_argument('--ab-report',type=Path)
    p.add_argument('--native-report',type=Path)
    p.add_argument('--quiesced',action='store_true')
    a=p.parse_args(argv)
    try:
        if a.action in ['apply','rollback']:require(a.quiesced,'Drain jobs and assert --quiesced before publisher/service interruption')
        if a.action=='build':result=build(a)
        elif a.action=='capture':
            require(bool(a.renderer_project),'Explicit existing renderer project required');result=capture(a)
        elif a.action=='prepare-ipc':result=prepare(a)
        else:
            if a.action!='rollback':require(a.ab_report is not None and a.native_report is not None,'New-image A/B and native candidate/recreate reports required')
            result=preflight(a,a.action=='rollback')
            if a.action in ['apply','rollback']:result=switch(a,a.action=='rollback')
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__,'detail':str(error) if isinstance(error,ValueError) else 'Inspect local release bundle/Docker; no success is claimed','pgv13_certified':False}),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
