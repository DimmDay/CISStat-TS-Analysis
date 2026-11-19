"""Offline controls of a VM diagnostic, never a real Docker/sandbox claim."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_reference_hash_and_only_three_namespace_syscalls_change():
    from scripts.pgv13sandbox.probe import profiles
    base,changed=profiles()
    meta=json.loads((ROOT/'scripts/pgv13sandbox/vendor/source.json').read_text())
    raw=(ROOT/'scripts/pgv13sandbox/vendor/default.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==meta['sha256']
    assert base['defaultAction']==changed['defaultAction']=='SCMP_ACT_ERRNO'
    assert changed['syscalls'][:-1]==base['syscalls']
    assert {k:v for k,v in changed.items() if k!='syscalls'}=={k:v for k,v in base.items() if k!='syscalls'}
    assert changed['syscalls'][-1]=={'names':['clone','setns','unshare'],'action':'SCMP_ACT_ALLOW','args':[]}
    clone3=[r for r in changed['syscalls'] if 'clone3' in r['names'] and r['action']=='SCMP_ACT_ERRNO']
    assert clone3 and clone3[0]['errnoRet']==38


@pytest.mark.parametrize('states,expected',[
    ([False,False,True],'NAMESPACE_RULES_CANDIDATE'),
    ([False,True,True],'REFERENCE_DIFF_UNATTRIBUTED'),
    ([False,False,False],'STILL_BLOCKED'),
    ([True,True,True],'BASELINE_PASSED'),
])
def test_classification_requires_reference_control(states,expected):
    from scripts.pgv13sandbox.probe import classify
    rows=[{'exit':0 if passed else 1,'probe':{'isolation_ok':True,'smoke':{'verdict':'passed' if passed else 'failed'}}} for passed in states]
    assert classify(rows)==expected


def test_instrument_failure_and_isolation_never_become_candidate():
    from scripts.pgv13sandbox.probe import classify
    rows=[{'exit':1,'probe':{'isolation_ok':True,'smoke':{'verdict':'failed'}}} for _ in range(3)]
    rows[-1]={'exit':0,'probe':{'isolation_ok':False,'smoke':{'verdict':'passed'}}}
    assert classify(rows)=='INCONCLUSIVE_ISOLATION'
    rows[1]={'exit':125,'probe':None}
    assert classify(rows)=='INCONCLUSIVE_SETUP'


def test_three_arms_keep_image_and_hardening_and_clean_up(monkeypatch,tmp_path):
    from scripts.pgv13sandbox import probe
    commands=[]
    def fake(args,**kwargs):
        commands.append(args)
        if args[:2]==['docker','run']:
            return subprocess.CompletedProcess(args,1,'PGV13_SANDBOX_RESULT '+json.dumps({'isolation_ok':True,'smoke':{'verdict':'failed'}})+'\n','')
        return subprocess.CompletedProcess(args,0,'','')
    monkeypatch.setattr(probe.subprocess,'run',fake)
    for name in ('builtin','reference','namespaces'):
        row=probe.run_arm(name,'sha256:'+'a'*64,tmp_path/'profile.json')
        assert row['probe']['smoke']['verdict']=='failed'
    runs=[c for c in commands if c[:2]==['docker','run']]
    assert len(runs)==3
    for c in runs:
        for flag in ('--read-only','--init','--rm','--network=none','--user=10001:10001','--cap-drop=ALL','--pull=never',
                     '--security-opt=no-new-privileges:true','--security-opt=apparmor=docker-default',
                     '--memory=2g','--pids-limit=128','--shm-size=256m'):
            assert flag in c
        assert 'sha256:'+'a'*64 in c
        docker_flags=c[:c.index('--entrypoint=node')]
        assert not any(x.startswith(('--privileged','--cap-add','--volume')) or 'unconfined' in x or '--no-sandbox' in x for x in docker_flags)
    assert not any(c.startswith('--security-opt=seccomp=') for c in runs[0])
    assert all(any(c.startswith('--security-opt=seccomp=') for c in args) for args in runs[1:])
    names=[c[c.index('--name')+1] for c in runs]
    assert len(set(names))==3 and all(n.startswith('cisstat-pgv13-probe-') for n in names)
    assert [c[3] for c in commands if c[:3]==['docker','rm','-f']]==names


def test_timeout_is_not_a_pass_and_only_own_container_is_removed(monkeypatch,tmp_path):
    from scripts.pgv13sandbox import probe
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if args[:2]==['docker','run']: raise subprocess.TimeoutExpired(args,90)
        return subprocess.CompletedProcess(args,0,'','')
    monkeypatch.setattr(probe.subprocess,'run',fake)
    row=probe.run_arm('builtin','sha256:'+'a'*64,tmp_path/'profile.json')
    assert row['probe'] is None and row['exit']==124
    assert calls[-1][:3]==['docker','rm','-f']
    assert calls[-1][3]==calls[0][calls[0].index('--name')+1]


def test_setup_failure_replaces_a_stale_positive_report(monkeypatch,tmp_path):
    from scripts.pgv13sandbox import probe
    out=tmp_path/'report.json'
    out.write_text(json.dumps({'conclusion':'NAMESPACE_RULES_CANDIDATE'}))
    monkeypatch.setattr('sys.argv',['probe.py','--out',str(out)])
    def unavailable(args): raise RuntimeError('Docker unavailable')
    monkeypatch.setattr(probe,'docker_value',unavailable)
    assert probe.main()==2
    report=json.loads(out.read_text())
    assert report['conclusion']=='INCONCLUSIVE_SETUP'
    assert report['pgv13_certified'] is False


def test_chroot_arm_changes_exactly_one_syscall_without_mutating_namespace_control():
    from scripts.pgv13sandbox.probe import profiles, chroot_profile
    _,namespace=profiles()
    original=copy.deepcopy(namespace)
    changed=chroot_profile(namespace)
    assert namespace==original
    assert changed['syscalls'][:-1]==namespace['syscalls']
    assert {k:v for k,v in changed.items() if k!='syscalls'}=={k:v for k,v in namespace.items() if k!='syscalls'}
    assert changed['syscalls'][-1]=={'names':['chroot'],'action':'SCMP_ACT_ALLOW','args':[]}


@pytest.mark.parametrize('fourth_passed,expected',[
    (True,'CHROOT_RULE_CANDIDATE'),(False,'STILL_BLOCKED'),
])
def test_fourth_arm_is_causal_chroot_control(fourth_passed,expected):
    from scripts.pgv13sandbox.probe import classify
    rows=[{'exit':1,'probe':{'isolation_ok':True,'smoke':{'verdict':'failed'}}} for _ in range(4)]
    if fourth_passed: rows[-1]={'exit':0,'probe':{'isolation_ok':True,'smoke':{'verdict':'passed'}}}
    assert classify(rows)==expected


@pytest.mark.parametrize('fourth_passed,error',[(True,None),(False,'Check failed: sys_chroot failed')])
def test_with_chroot_cli_runs_original_controls_and_a_fourth_temporary_container(monkeypatch,tmp_path,capsys,fourth_passed,error):
    from scripts.pgv13sandbox import probe
    seen=[]
    def metadata(args):
        if args[0]=='compose':return 'test-container'
        if '{{.Image}}' in args:return 'sha256:'+'a'*64
        return 'docker-default'
    def arm(name,image,path):
        seen.append((name,json.loads(path.read_text())))
        passed=name=='namespaces-chroot' and fourth_passed
        return {'arm':name,'exit':0 if passed else 1,'probe':{'isolation_ok':True,'smoke':{'verdict':'passed' if passed else 'failed','error':None if passed else (error or 'earlier arm blocked')}}}
    monkeypatch.setattr(probe,'docker_value',metadata)
    monkeypatch.setattr(probe,'run_arm',arm)
    monkeypatch.setattr('sys.argv',['probe.py','--with-chroot','--out',str(tmp_path/'report.json')])
    assert probe.main()==(0 if fourth_passed else 1)
    stdout=capsys.readouterr().out
    summary=json.loads(stdout[stdout.index('{'):])
    assert summary['conclusion']==('CHROOT_RULE_CANDIDATE' if fourth_passed else 'STILL_BLOCKED')
    assert summary['arms'][-1]['no_usable_sandbox'] is False
    assert summary['arms'][-1]['smoke_error']==('' if fourth_passed else error)
    saved=json.loads((tmp_path/'report.json').read_text())
    assert saved['rows'][-1]['probe']['smoke']['error']==error
    assert saved['conclusion']==summary['conclusion']
    assert [x[0] for x in seen]==['builtin','reference','namespaces','namespaces-chroot']
    assert seen[0][1]==seen[1][1]
    assert seen[3][1]['syscalls'][:-1]==seen[2][1]['syscalls']
    assert json.loads((tmp_path/'report.json').read_text())['pgv13_certified'] is False
