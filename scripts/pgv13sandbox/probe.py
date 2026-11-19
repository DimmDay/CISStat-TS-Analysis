"""Three-arm (optional fourth chroot arm) disposable-container seccomp diagnostic. Never deploys a policy.

Runs the immutable image of the existing renderer with unchanged AppArmor and
hardening. Docker builtin != pinned reference; only reference->namespaces is a
controlled diff. Exit 0 means a diagnostic candidate, NOT PGV-13 certification.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

NODE=r'''
const fs=require('node:fs');
const {spawnSync}=require('node:child_process');
const {PrintRenderWorker,readConfig}=require('./apps/print-renderer/dist/apps/print-renderer/src/renderWorker.js');
const {runProbeSmoke}=require('./apps/print-renderer/dist/apps/print-renderer/src/smokeScenarios.js');
(async()=>{
 const status=fs.readFileSync('/proc/self/status','utf8');
 const field=n=>status.match(new RegExp('^'+n+':\\s*(.*)$','m'))?.[1].trim();
 const namespace=spawnSync('unshare',['-Ur','true'],{encoding:'utf8',timeout:5000});
 const mountns=spawnSync('unshare',['-m','true'],{encoding:'utf8',timeout:5000});
 let root_write_blocked=false;
 const sentinel='/app/.pgv13-probe-'+process.pid;
 try{fs.writeFileSync(sentinel,'probe',{flag:'wx'});fs.unlinkSync(sentinel)}
 catch(e){root_write_blocked=['EROFS','EACCES'].includes(e.code)}
 const isolation_ok=process.getuid()===10001 && field('NoNewPrivs')==='1' &&
   field('Seccomp')==='2' && /^0+$/.test(field('CapEff')??'') &&
   root_write_blocked && !mountns.error && mountns.status!==0;
 const worker=new PrintRenderWorker(readConfig());
 let launch_verified=false;
 let launch_flags=[];
 const real=require('playwright-core').chromium;
 worker.playwrightModule={chromium:new Proxy(real,{get(target,key){
   if(key==='launchServer') return async options=>{
     launch_flags=options.args??[];
     launch_verified=options.chromiumSandbox===true && !launch_flags.some(a=>['--no-sandbox','--disable-namespace-sandbox','--disable-setuid-sandbox'].includes(a));
     if(!launch_verified) throw new Error('Sandbox launch options not preserved');
     return target.launchServer(options);
   };
   const value=Reflect.get(target,key,target);
   return typeof value==='function'?value.bind(target):value;
 }})};
 let smoke;
 try{smoke=await runProbeSmoke(worker)}catch(e){smoke={verdict:'failed',error:e.message}}
 finally{await worker.shutdown()}
 const report={isolation_ok:isolation_ok&&launch_verified,launch_verified,launch_flags,security:{uid:process.getuid(),NoNewPrivs:field('NoNewPrivs'),Seccomp:field('Seccomp'),CapEff:field('CapEff'),apparmor:fs.readFileSync('/proc/self/attr/current','utf8').trim(),root_write_blocked,mountns_blocked:!mountns.error&&mountns.status!==0},namespace:{status:namespace.status,error_code:namespace.error?.code??null,stderr:namespace.stderr?.slice(0,2000)},smoke};
 console.log('PGV13_SANDBOX_RESULT '+JSON.stringify(report));
 process.exitCode=report.isolation_ok&&smoke.verdict==='passed'?0:1;
})().catch(e=>{console.error(e.message);process.exitCode=2});
'''


def profiles():
    raw=(HERE/'vendor/default.json').read_bytes()
    metadata=json.loads((HERE/'vendor/source.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=metadata['sha256']:
        raise ValueError('Pinned reference checksum mismatch')
    base=json.loads(raw)
    changed=copy.deepcopy(base)
    changed['syscalls'].append({'names':['clone','setns','unshare'],'action':'SCMP_ACT_ALLOW','args':[]})
    return base,changed


def chroot_profile(namespace_profile):
    changed=copy.deepcopy(namespace_profile)
    changed['syscalls'].append({'names':['chroot'],'action':'SCMP_ACT_ALLOW','args':[]})
    return changed


def smoke_error_excerpt(error):
    lines=error.splitlines()
    fatal=[line for line in lines if 'Check failed:' in line or 'FATAL:' in line]
    return '\n'.join((fatal or lines[:2])[:4])[:1600]


def run_arm(arm,image,profile):
    name='cisstat-pgv13-probe-'+uuid4().hex
    args=['docker','run','--rm','--name',name,'--pull=never','--init',
          '--network=none','--user=10001:10001','--read-only','--cap-drop=ALL',
          '--security-opt=no-new-privileges:true','--security-opt=apparmor=docker-default',
          '--tmpfs=/tmp:rw,noexec,nosuid,size=512m,mode=1777','--shm-size=256m',
          '--memory=2g','--pids-limit=128','--label=cisstat.pgv13sandbox.probe=true',
          '--env=HOME=/tmp','--env=CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S=60',
          '--env=CISSTAT_PRINT_RENDERER_MAX_CONCURRENT=2','--env=CISSTAT_PRINT_RENDERER_TMP_DIR=/tmp']
    if arm!='builtin': args.append('--security-opt=seccomp='+str(profile))
    args+=['--entrypoint=node',image,'-e',NODE]
    try:
        result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=90)
        probe=None
        for line in result.stdout.splitlines():
            if line.startswith('PGV13_SANDBOX_RESULT '):
                probe=json.loads(line.split(' ',1)[1])
        return {'arm':arm,'exit':result.returncode,'probe':probe,'stderr':result.stderr[-8000:]}
    except subprocess.TimeoutExpired:
        return {'arm':arm,'exit':124,'probe':None,'error':'container probe timed out'}
    finally:
        # CLI timeout alone does not stop a daemon-owned container. Unique name
        # belongs only to this invocation; never stop/recreate the real renderer.
        subprocess.run(['docker','rm','-f',name],capture_output=True,text=True,timeout=15)


def classify(rows):
    if len(rows) not in (3,4) or any(not isinstance(r.get('probe'),dict) for r in rows):
        return 'INCONCLUSIVE_SETUP'
    if any(r['probe'].get('isolation_ok') is not True for r in rows):
        return 'INCONCLUSIVE_ISOLATION'
    passed=[r['exit']==0 and r['probe'].get('smoke',{}).get('verdict')=='passed' for r in rows]
    if passed[0]: return 'BASELINE_PASSED'
    if passed[1]: return 'REFERENCE_DIFF_UNATTRIBUTED'
    if passed[2]: return 'NAMESPACE_RULES_CANDIDATE'
    if len(passed)==4 and passed[3]: return 'CHROOT_RULE_CANDIDATE'
    return 'STILL_BLOCKED'


def docker_value(args):
    result=subprocess.run(['docker',*args],cwd=ROOT,capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise RuntimeError('Docker metadata command failed, exit='+str(result.returncode))
    return result.stdout.strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,help='Optional JSON report (no environment dump)')
    parser.add_argument('--with-chroot',action='store_true',help='Add a fourth arm: namespace profile plus only chroot ALLOW')
    opts=parser.parse_args()
    try:
        if opts.out:
            opts.out.write_text(json.dumps({'conclusion':'RUNNING','pgv13_certified':False})+'\n',encoding='utf-8')
        compose='apps/print-renderer/build/deployment/docker-compose.yml'
        cid=docker_value(['compose','-f',compose,'ps','-q','print-renderer'])
        if not cid or '\n' in cid: raise ValueError('Expected one running renderer container')
        image=docker_value(['inspect','--format','{{.Image}}',cid])
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',image): raise ValueError('Expected immutable local image ID')
        apparmor=docker_value(['inspect','--format','{{.AppArmorProfile}}',cid])
        if apparmor!='docker-default': raise ValueError('Source AppArmor differs; no controlled comparison possible')
        base,changed=profiles()
        with tempfile.TemporaryDirectory(prefix='cisstat-pgv13-seccomp-') as temp:
            reference=Path(temp)/'reference.json';reference.write_text(json.dumps(base))
            namespaces=Path(temp)/'namespaces.json';namespaces.write_text(json.dumps(changed))
            arms=[('builtin',reference),('reference',reference),('namespaces',namespaces)]
            if opts.with_chroot:
                chroot=Path(temp)/'namespaces-chroot.json';chroot.write_text(json.dumps(chroot_profile(changed)))
                arms.append(('namespaces-chroot',chroot))
            rows=[]
            for arm,path in arms:
                print('Running isolated arm: '+arm,flush=True)
                rows.append(run_arm(arm,image,path))
        conclusion=classify(rows)
        report={'kind':'disposable-container controlled diagnostic; NOT production acceptance',
                'image_id':image,'apparmor':apparmor,'reference':json.loads((HERE/'vendor/source.json').read_text()),
                'conclusion':conclusion,'pgv13_certified':False,'rows':rows}
        encoded=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
        if opts.out:
            opts.out.write_text(encoded,encoding='utf-8')
            summary={'conclusion':conclusion,'pgv13_certified':False,'report_path':str(opts.out),'arms':[]}
            for row in rows:
                p=row.get('probe') or {}
                smoke=p.get('smoke') or {}
                summary['arms'].append({'arm':row['arm'],'exit':row['exit'],'isolation_ok':p.get('isolation_ok'),
                    'namespace_status':p.get('namespace',{}).get('status'),'smoke_verdict':smoke.get('verdict'),
                    'no_usable_sandbox':'No usable sandbox' in smoke.get('error',''),
                    'smoke_error':smoke_error_excerpt(smoke.get('error','')),
                    'setup_error':row.get('stderr','')[:400] if not p else None})
            print(json.dumps(summary,ensure_ascii=False,indent=2))
        else:
            print(encoded)
        return 2 if conclusion.startswith('INCONCLUSIVE') else (0 if conclusion in {'NAMESPACE_RULES_CANDIDATE','CHROOT_RULE_CANDIDATE'} else 1)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        report={'conclusion':'INCONCLUSIVE_SETUP','pgv13_certified':False,'error_type':type(error).__name__,'detail':str(error)}
        if opts.out:
            try: opts.out.write_text(json.dumps(report)+'\n',encoding='utf-8')
            except OSError as write_error: report['report_write_error']=type(write_error).__name__
        print(json.dumps(report))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
