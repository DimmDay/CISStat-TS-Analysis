"""Read cgroup evidence and invoke full smoke through the existing HTTP worker.

No second PrintRenderWorker/Chromium CLI, no container changes. Exit0 requires
full smoke, readiness, finite expected budgets and no new PID/OOM events.
This is V01 operational verification, never a whole-PGV13 certificate.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'apps/print-renderer/build/deployment/docker-compose.yml'
NODE=r'''
const fs=require('node:fs');
let evidenceBefore=null;let latestSnapshot=()=>null;
(async()=>{
 const read=p=>{try{return fs.readFileSync(p,'utf8').trim()}catch{return null}};
 const integer=s=>s!==null&&/^\d+$/.test(s)?Number(s):null;
 const events=s=>s===null?null:Object.fromEntries(s.split('\n').map(l=>{const [k,v]=l.trim().split(/\s+/);return[k,Number(v)]}));
 const snapshot=()=>({pids_current:integer(read('/sys/fs/cgroup/pids.current')),pids_max:integer(read('/sys/fs/cgroup/pids.max')),pids_peak:integer(read('/sys/fs/cgroup/pids.peak')),pids_events:events(read('/sys/fs/cgroup/pids.events')),memory_current:integer(read('/sys/fs/cgroup/memory.current')),memory_max:integer(read('/sys/fs/cgroup/memory.max')),memory_events:events(read('/sys/fs/cgroup/memory.events'))});
 latestSnapshot=snapshot;
 const status=read('/proc/self/status')??'';
 const field=n=>status.match(new RegExp('^'+n+':\\s*(.*)$','m'))?.[1].trim();
 // Liveness polling does not launch a browser. Wait only for the existing server.
 let live=false;
 for(let i=0;i<20;i++){
  try{const r=await fetch('http://127.0.0.1:8907/healthz',{signal:AbortSignal.timeout(2000)});if(r.status===200){live=true;break}}catch{}
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 if(!live)throw new Error('Existing HTTP server did not become live');
 const before=snapshot();evidenceBefore=before;
 const smokeResponse=await fetch('http://127.0.0.1:8907/v1/smoke',{method:'POST',signal:AbortSignal.timeout(210000)});
 const smoke=await smokeResponse.json();
 const readyResponse=await fetch('http://127.0.0.1:8907/readyz',{signal:AbortSignal.timeout(70000)});
 const readiness=await readyResponse.json();
 const after=snapshot();
 const delta=(b,a)=>Number.isFinite(b)&&Number.isFinite(a)?a-b:null;
 const pids_delta=delta(before.pids_events?.max,after.pids_events?.max);
 const oom_delta=delta(before.memory_events?.oom,after.memory_events?.oom);
 const oom_kill_delta=delta(before.memory_events?.oom_kill,after.memory_events?.oom_kill);
 const checks={
  full_smoke:smokeResponse.status===200&&smoke.verdict==='passed',
  readiness:readyResponse.status===200&&readiness.status==='ready'&&readiness.checks?.smoke===true,
  finite_budgets:before.pids_max===512&&after.pids_max===512&&before.memory_max===2147483648&&after.memory_max===2147483648,
  no_new_pids_failures:pids_delta===0,
  no_new_oom:oom_delta===0&&oom_kill_delta===0,
  parent_hardening:process.getuid()===10001&&field('NoNewPrivs')==='1'&&field('Seccomp')==='2'&&/^0+$/.test(field('CapEff')??'')
 };
 const passed=Object.values(checks).every(Boolean);
 console.log(JSON.stringify({passed,pgv13_certified:false,checks,before,after,deltas:{pids_max_events:pids_delta,oom:oom_delta,oom_kill:oom_kill_delta},http:{smoke:smokeResponse.status,readyz:readyResponse.status},smoke,readiness}));
 process.exitCode=passed?0:1;
})().catch(error=>{console.log(JSON.stringify({passed:false,pgv13_certified:false,before:evidenceBefore,after:latestSnapshot(),setup_error:error.message}));process.exitCode=2});
'''


def short_error(error):
    lines=str(error or '').splitlines()
    selected=[line for line in lines if any(marker in line for marker in ('Check failed:','FATAL:','pthread_create','Resource temporarily unavailable'))]
    return '\n'.join((selected or lines[:2])[:5])[:1800]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    opts=parser.parse_args()
    try:
        if opts.out:opts.out.write_text(json.dumps({'passed':False,'state':'RUNNING','pgv13_certified':False})+'\n',encoding='utf-8')
        result=subprocess.run(['docker','compose','-f',str(BASE),'exec','-T','print-renderer','node','-e',NODE],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=360)
        report=json.loads(result.stdout)
        if result.returncode not in (0,1,2):raise ValueError('Docker exec failed before complete verification')
        if not isinstance(report,dict):raise ValueError('Expected verification JSON object')
        if (result.returncode==0)!=(report.get('passed') is True):raise ValueError('Inconsistent verification exit/report')
        report['docker_exit']=result.returncode
        if opts.out:
            opts.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            summary={k:report.get(k) for k in ('passed','pgv13_certified','checks','before','after','deltas','http','setup_error')}
            summary['scenarios']=[{'scenario':s.get('scenario'),'checks':s.get('checks'),'error':short_error(s.get('error'))} for s in (report.get('smoke') or {}).get('scenarios',[])]
            summary['smoke_error']=short_error((report.get('smoke') or {}).get('error'))
            print(json.dumps(summary,ensure_ascii=False,indent=2))
        else:print(json.dumps(report,ensure_ascii=False,indent=2))
        return result.returncode
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        report={'passed':False,'pgv13_certified':False,'setup_error':type(error).__name__,'detail':str(error)}
        if opts.out:
            try:opts.out.write_text(json.dumps(report)+'\n',encoding='utf-8')
            except OSError:pass
        print(json.dumps(report));return 2


if __name__=='__main__':raise SystemExit(main())
