"""Offline activation/preflight contracts, no live Docker assertion."""
import json
from pathlib import Path
import subprocess

import pytest

IMAGE='sha256:'+'a'*64


def evidence():
    from scripts.pgv13sandbox.probe import HERE
    rows=[]
    for name in ('builtin','reference','namespaces','namespaces-chroot'):
        passed=name=='namespaces-chroot'
        rows.append({'arm':name,'exit':0 if passed else 1,'probe':{
            'isolation_ok':True,'launch_verified':True,
            'security':{'uid':10001,'NoNewPrivs':'1','Seccomp':'2','CapEff':'0000000000000000',
                        'root_write_blocked':True,'mountns_blocked':True,'apparmor':'docker-default (enforce)'},
            'smoke':{'verdict':'passed' if passed else 'failed','error':None if passed else 'blocked'}}})
    return {'image_id':IMAGE,'conclusion':'CHROOT_RULE_CANDIDATE','pgv13_certified':False,
            'reference':json.loads((HERE/'vendor/source.json').read_text()),'rows':rows}


def config(profile,rollback=False):
    security=['no-new-privileges:true'] if rollback else ['no-new-privileges:true','apparmor=docker-default','seccomp='+str(profile)]
    return {'services':{'print-renderer':{'image':IMAGE,'user':'10001:10001','network_mode':'none',
        'read_only':True,'cap_drop':['ALL'],'security_opt':security,'init':True,
        'mem_limit':'2147483648','pids_limit':128 if rollback else 512,'shm_size':'268435456',
        'tmpfs':['/tmp:rw,noexec,nosuid,size=512m,mode=1777']}}}


def test_committed_profile_is_exactly_the_tested_candidate():
    from scripts.pgv13sandbox.activate import PROFILE
    from scripts.pgv13sandbox.probe import profiles,chroot_profile
    assert json.loads(PROFILE.read_text())==chroot_profile(profiles()[1])


def test_valid_report_accepted_and_invalid_candidates_denied():
    from scripts.pgv13sandbox.activate import validate_report
    assert validate_report(evidence())==IMAGE
    for mutate in (
        lambda r:r.update(conclusion='STILL_BLOCKED'),
        lambda r:r.update(image_id='mutable:tag'),
        lambda r:r['reference'].update(sha256='wrong'),
        lambda r:r['rows'][-1]['probe']['security'].update(CapEff='0000000000000001'),
        lambda r:r['rows'][-1]['probe'].update(launch_verified=False),
        lambda r:r['rows'].reverse(),
        lambda r:r['rows'][0]['probe']['smoke'].update(verdict='passed'),
    ):
        report=evidence();mutate(report)
        with pytest.raises(ValueError):validate_report(report)


@pytest.mark.parametrize('field,value',[
    ('image','mutable:tag'),('user','0'),('network_mode','host'),('read_only',False),
    ('cap_add',['SYS_ADMIN']),('privileged',True),('ports',['8907:8907']),
    ('volumes',['/:/host']),('security_opt',['seccomp=unconfined']),
    ('mem_limit',0),('pids_limit',-1),('tmpfs',[]),
])
def test_compose_hardening_drift_blocks_activation(field,value):
    from scripts.pgv13sandbox.activate import PROFILE,validate_config
    valid=config(PROFILE)
    validate_config(valid,IMAGE,False)
    valid['services']['print-renderer'][field]=value
    with pytest.raises(ValueError):validate_config(valid,IMAGE,False)


@pytest.mark.parametrize('apply',[False,True])
def test_preflight_and_apply_pin_image_and_profile_without_unrequested_recreate(monkeypatch,tmp_path,capsys,apply):
    from scripts.pgv13sandbox import activate as A
    report=tmp_path/'report.json';report.write_text(json.dumps(evidence()))
    calls=[]
    current={'image':IMAGE,'apparmor':'docker-default','mounts':[]}
    def fake(args,**kwargs):
        calls.append((args,kwargs))
        if args[1]=='inspect': return subprocess.CompletedProcess(args,0,json.dumps(current),'')
        if 'ps' in args:return subprocess.CompletedProcess(args,0,'container-id','')
        if 'config' in args:return subprocess.CompletedProcess(args,0,json.dumps(config(A.PROFILE)),'')
        return subprocess.CompletedProcess(args,0,'','')
    monkeypatch.setattr(A.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['activate.py','--report',str(report)]+(['--apply'] if apply else []))
    assert A.main()==0
    if not apply:
        assert not any('up' in c[0] for c in calls)
        assert json.loads(capsys.readouterr().out)['action']=='check'
        return
    up=[c for c in calls if 'up' in c[0]]
    assert len(up)==1
    command,kwargs=up[0]
    assert command[-1]=='print-renderer'
    assert str(A.CAPACITY_OVERRIDE) in command
    for flag in ('--no-deps','--no-build','--pull','never','--force-recreate'):assert flag in command
    assert kwargs['env']['CISSTAT_VALIDATED_RENDERER_IMAGE']==IMAGE
    assert Path(kwargs['env']['CISSTAT_RENDERER_SECCOMP_FILE']).is_absolute()
    assert json.loads(capsys.readouterr().out)['readiness_checked'] is False


def test_image_mismatch_never_runs_up(monkeypatch,tmp_path):
    from scripts.pgv13sandbox import activate as A
    report=tmp_path/'report.json';report.write_text(json.dumps(evidence()))
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if args[1]=='inspect':return subprocess.CompletedProcess(args,0,json.dumps({'image':'sha256:'+'b'*64,'apparmor':'docker-default','mounts':[]}),'')
        return subprocess.CompletedProcess(args,0,'container-id','')
    monkeypatch.setattr(A.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['activate.py','--report',str(report),'--apply'])
    assert A.main()==2
    assert not any('up' in c for c in calls)


def test_rollback_keeps_image_override_but_removes_sandbox_overlay(monkeypatch,tmp_path):
    from scripts.pgv13sandbox import activate as A
    report=tmp_path/'report.json';report.write_text(json.dumps(evidence()))
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if args[1]=='inspect':return subprocess.CompletedProcess(args,0,json.dumps({'image':IMAGE,'apparmor':'docker-default','mounts':[]}),'')
        if 'ps' in args:return subprocess.CompletedProcess(args,0,'container-id','')
        if 'config' in args:return subprocess.CompletedProcess(args,0,json.dumps(config(A.PROFILE,True)),'')
        return subprocess.CompletedProcess(args,0,'','')
    monkeypatch.setattr(A.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['activate.py','--report',str(report),'--rollback'])
    assert A.main()==0
    up=next(c for c in calls if 'up' in c)
    assert str(A.IMAGE_OVERRIDE) in up
    assert str(A.SANDBOX_OVERRIDE) not in up
    assert str(A.CAPACITY_OVERRIDE) not in up


def test_equivalent_docker_security_option_separators_keep_same_policy():
    from scripts.pgv13sandbox.activate import PROFILE,validate_config
    model=config(PROFILE)
    model['services']['print-renderer']['security_opt']=[
        'no-new-privileges=true','apparmor:docker-default','seccomp:'+str(PROFILE)]
    validate_config(model,IMAGE,False)


def test_compose_up_failure_reports_possible_mutation_without_automatic_rollback(monkeypatch,tmp_path,capsys):
    from scripts.pgv13sandbox import activate as A
    report=tmp_path/'report.json';report.write_text(json.dumps(evidence()))
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if args[1]=='inspect':return subprocess.CompletedProcess(args,0,json.dumps({'image':IMAGE,'apparmor':'docker-default','mounts':[]}),'')
        if 'ps' in args:return subprocess.CompletedProcess(args,0,'container-id','')
        if 'config' in args:return subprocess.CompletedProcess(args,0,json.dumps(config(A.PROFILE)),'')
        return subprocess.CompletedProcess(args,1,'','up failed')
    monkeypatch.setattr(A.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['activate.py','--report',str(report),'--apply'])
    assert A.main()==2
    error=json.loads(capsys.readouterr().err)
    assert error['preflight_ok'] is True and error['mutation_started'] is True
    assert sum('up' in c for c in calls)==1


def test_bounded_capacity_overlay_and_forward_budget():
    from scripts.pgv13sandbox import activate as A
    import yaml
    overlay=yaml.safe_load(A.CAPACITY_OVERRIDE.read_text())
    assert overlay=={'services':{'print-renderer':{'pids_limit':512}}}
    forward=config(A.PROFILE);forward['services']['print-renderer']['pids_limit']=512
    A.validate_config(forward,IMAGE,False)
    forward['services']['print-renderer']['pids_limit']=128
    with pytest.raises(ValueError):A.validate_config(forward,IMAGE,False)


def test_explicit_legacy_budget_keeps_sandbox_for_capacity_rollback():
    from scripts.pgv13sandbox import activate as A
    legacy=config(A.PROFILE);legacy['services']['print-renderer']['pids_limit']=128
    A.validate_config(legacy,IMAGE,False,pids_limit=128)
    with pytest.raises(ValueError):A.validate_config(legacy,IMAGE,False,pids_limit=-1)


def test_legacy_capacity_apply_retains_sandbox_and_omits_capacity_override(monkeypatch,tmp_path,capsys):
    from scripts.pgv13sandbox import activate as A
    report=tmp_path/'report.json';report.write_text(json.dumps(evidence()))
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if args[1]=='inspect':return subprocess.CompletedProcess(args,0,json.dumps({'image':IMAGE,'apparmor':'docker-default','mounts':[]}),'')
        if 'ps' in args:return subprocess.CompletedProcess(args,0,'container-id','')
        if 'config' in args:
            model=config(A.PROFILE);model['services']['print-renderer']['pids_limit']=128
            return subprocess.CompletedProcess(args,0,json.dumps(model),'')
        return subprocess.CompletedProcess(args,0,'','')
    monkeypatch.setattr(A.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['activate.py','--report',str(report),'--apply','--pids-limit','128'])
    assert A.main()==0
    up=next(c for c in calls if 'up' in c)
    assert str(A.SANDBOX_OVERRIDE) in up and str(A.CAPACITY_OVERRIDE) not in up
    assert json.loads(capsys.readouterr().out)['pids_limit']==128


def test_legacy_activator_refuses_running_uds_volume(monkeypatch,tmp_path,capsys):
    from scripts.pgv13sandbox import activate as A
    report=tmp_path/'ab.json';report.write_text(json.dumps(evidence()))
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if args[1]=='inspect':return subprocess.CompletedProcess(args,0,json.dumps({'image':IMAGE,'apparmor':'docker-default','mounts':[{'Destination':'/run/cisstat-renderer'}]}),'')
        if 'ps' in args:return subprocess.CompletedProcess(args,0,'container-id','')
        if 'config' in args:return subprocess.CompletedProcess(args,0,json.dumps(config(A.PROFILE)),'')
        if 'up' in args:return subprocess.CompletedProcess(args,0,'','')
        raise AssertionError(args)
    monkeypatch.setattr(A.subprocess,'run',fake)
    monkeypatch.setattr('sys.argv',['activate.py','--report',str(report),'--apply'])
    assert A.main()==2
    result=json.loads(capsys.readouterr().err)
    assert result['preflight_ok'] is False and result['mutation_started'] is False
    assert 'UDS' in result['detail']
    assert not any('up' in call for call in calls)
