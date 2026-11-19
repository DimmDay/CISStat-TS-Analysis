"""Execute the actual Node HTTP verification client with mocked fs/fetch only."""
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('scenario,passed',[
    ('ok',True),('pids',False),('oom',False),('old_budget',False),('readiness',False),('smoke',False),('missing',False),('transport',False),
])
def test_service_client_observes_cgroup_and_uses_existing_http_worker(scenario,passed):
    from scripts.pgv13sandbox.verify_service import NODE
    harness=r'''
const vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let after=false;const calls=[];const output=[];const state={getuid:()=>10001,exitCode:0};
const fs={readFileSync(path){
 if(input.scenario==='missing'&&path.endsWith('/pids.events'))throw new Error('not exposed');
 const data={
 '/proc/self/status':'NoNewPrivs:\t1\nSeccomp:\t2\nCapEff:\t0000000000000000\n',
 '/sys/fs/cgroup/pids.current':'70','/sys/fs/cgroup/pids.peak':'220',
 '/sys/fs/cgroup/pids.max':input.scenario==='old_budget'?'128':'512',
 '/sys/fs/cgroup/pids.events':'max '+(after&&input.scenario==='pids'?2:0)+'\n',
 '/sys/fs/cgroup/memory.current':'250000000','/sys/fs/cgroup/memory.max':'2147483648',
 '/sys/fs/cgroup/memory.events':'oom '+(after&&input.scenario==='oom'?1:0)+'\noom_kill 0\n'};
 if(!(path in data))throw new Error('unexpected read '+path);return data[path];
}};
const fetch=async(url,options={})=>{
 calls.push({url,method:options.method??'GET'});
 if(url.endsWith('/healthz'))return{status:200,json:async()=>({status:'ok'})};
 if(url.endsWith('/v1/smoke')){
  if(input.scenario==='transport')throw new Error('connection lost');
  after=true;return{status:input.scenario==='smoke'?503:200,json:async()=>({verdict:input.scenario==='smoke'?'failed':'passed',error:null,checks:{cyrillic:true,ih:true,a4:true,distinct_hashes:true}})};
 }
 if(url.endsWith('/readyz'))return{status:input.scenario==='readiness'?503:200,json:async()=>({status:input.scenario==='readiness'?'unavailable':'ready',checks:{smoke:input.scenario!=='readiness'}})};
 throw new Error('unexpected request '+url);
};
const result=vm.runInNewContext(input.code,{require:n=>{if(n!=='node:fs')throw new Error('worker import forbidden '+n);return fs},process:state,fetch,AbortSignal:{timeout:()=>null},console:{log:s=>output.push(s)},setTimeout:fn=>fn()});
Promise.resolve(result).then(()=>process.stdout.write(JSON.stringify({report:JSON.parse(output.at(-1)),exit:state.exitCode,calls}))).catch(e=>{console.error(e);process.exit(2)});
'''
    run=subprocess.run(['node','-e',harness],input=json.dumps({'code':NODE,'scenario':scenario}),text=True,capture_output=True,cwd=ROOT,timeout=10)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert (result['exit']==0) is passed
    assert result['report']['passed'] is passed
    assert result['report']['pgv13_certified'] is False
    if scenario=='transport':
        assert result['report']['before'] is not None and result['report']['after'] is not None
        assert result['exit']==2
        return
    assert [x['method'] for x in result['calls']]==['GET','POST','GET']
    assert [x['url'] for x in result['calls']]==['http://127.0.0.1:8907/healthz','http://127.0.0.1:8907/v1/smoke','http://127.0.0.1:8907/readyz']


@pytest.mark.parametrize('child_exit,passed,expected_exit',[(0,True,0),(1,False,1),(0,False,2),(1,True,2)])
def test_verification_report_replaces_stale_success_and_matches_child_exit(monkeypatch,tmp_path,capsys,child_exit,passed,expected_exit):
    from scripts.pgv13sandbox import verify_service as V
    out=tmp_path/'report.json';out.write_text(json.dumps({'passed':True}))
    def fake(args,**kwargs):
        assert args[:2]==['docker','compose'] and 'exec' in args
        assert 'new PrintRenderWorker' not in args[-1]
        return subprocess.CompletedProcess(args,child_exit,json.dumps({'passed':passed,'pgv13_certified':False,'checks':{}}),'')
    monkeypatch.setattr(V.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['verify_service.py','--out',str(out)])
    assert V.main()==expected_exit
    stored=json.loads(out.read_text())
    assert stored['passed'] is (expected_exit==0)
    assert stored['pgv13_certified'] is False
