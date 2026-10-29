"""Targeted recertification: fixes + known-green controls, restore exact bytes."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'scripts/pgv08fix/protocols'
CORE='apps/print-renderer/src/rendererCore.tsx';WORK='apps/print-renderer/src/renderWorker.ts';GUARD='apps/print-renderer/src/launchGuard.ts';SMOKE='apps/print-renderer/src/smokeScenarios.ts'
FILES=[CORE,WORK,GUARD,SMOKE];original={f:(ROOT/f).read_bytes() for f in FILES}
SUITES=['apps/print-renderer/src/rendererFix.test.ts','apps/print-renderer/src/rendererCore.test.ts','apps/print-renderer/src/launchGuard.test.ts','scripts/pgv08cert/test_p8cert_red_evidence.test.ts']
def jest(label):
 cmd=['node','node_modules/jest/bin/jest.js','--runInBand','--silent','--json',f'--outputFile={OUT/(label+".json")}','--runTestsByPath',*SUITES]
 with (OUT/(label+'.txt')).open('w') as log:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=90)
 data=json.loads((OUT/(label+'.json')).read_text());failed=[t['fullName'] for s in data['testResults'] for t in s['assertionResults'] if t['status']=='failed']
 return r.returncode,failed
cases=[
 ('M01-url',CORE,'return !(normalized === "" || normalized === "about:blank" || normalized.startsWith("data:"));','return false;'),
 ('M02-scale',CORE,'scale < 0.05 || scale > 1','scale < 0.05'),
 ('M03-launch-budget',WORK,'      timeout: remainingMs(),','      timeout: 30_000,'),
 ('M04-sandbox',WORK,'chromiumSandbox: true','chromiumSandbox: false'),
 ('M05-ih',SMOKE,'n_observations: 600','n_observations: 601'),
 ('M06-phys',CORE,'if (type !== "pHYs") chunks.push','if (true) chunks.push'),
 ('M07-cold-gate',GUARD,'then exit 125; fi','then :; fi'),
 ('M08-process-group',GUARD,'process.kill(-Number(raw), "SIGKILL");','void raw;'),
 ('M09-ssr-abort',WORK,'signal.addEventListener("abort", cancel, { once: true });','// signal abort listener disabled'),
]
records=[]
def restore():
 for f,b in original.items():(ROOT/f).write_bytes(b)
 assert all((ROOT/f).read_bytes()==b for f,b in original.items())
def apply(items):
 for _,f,old,new in items:
  p=ROOT/f;s=p.read_text();assert s.count(old)==1,(f,old,s.count(old));p.write_text(s.replace(old,new))
try:
 code,failed=jest('mutation-baseline');assert code==0,(code,failed)
 for item in cases:
  restore();apply([item]);name=item[0]
  if name=='M09-ssr-abort':
   with (OUT/(name+'.txt')).open('w') as log:
    build=subprocess.run(['npm','run','build','--workspace=@cisstat/print-renderer'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    assert build.returncode==0,'invalid compile mutant'
    r=subprocess.run(['node','scripts/pgv08fix/verify_runtime.cjs'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=30,env=dict(os.environ,TMPDIR=str(ROOT.parent/'pgv08-tmp')))
   code=r.returncode;failed=['actual compiled worker thread abort oracle'] if code else []
  else:code,failed=jest(name)
  records.append({'id':name,'killed':code!=0 and bool(failed),'failed_oracles':failed})
  assert records[-1]['killed'],name
 restore();code,failed=jest('K01-noop');records.append({'id':'K01-noop','alive':code==0,'failed_oracles':failed});assert code==0
 for label,items in [('S01-url-scale',[cases[0],cases[1]]),('S02-sandbox-gate',[cases[3],cases[6]])]:
  restore();apply(items);code,failed=jest(label)
  required=['URL','invalid production scale'] if label.startswith('S01') else ['late launch','cancellation before spawn']
  dual=all(any(t in name for name in failed) for t in required)
  records.append({'id':label,'killed':code!=0,'dual_kill':dual,'failed_oracles':failed});assert dual,label
finally:
 restore()
 (OUT/'mutations.json').write_text(json.dumps({'records':records,'restored_exact_bytes':True,'verdict':'PASS' if len(records)==12 and all(x.get('killed',x.get('alive',False)) for x in records) else 'FAIL'},ensure_ascii=False,indent=2)+'\n')
print('Mutation campaign:',len(records),'records; restored exact modified-worktree bytes.')
