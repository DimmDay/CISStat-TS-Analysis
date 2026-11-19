"""Validate the successful A/B evidence and optionally recreate only renderer.

Default: read-only preflight. --apply attaches the exact tested seccomp profile;
--rollback returns to builtin seccomp on the same immutable image. No image
build/pull, host policy change, API/network fix or PGV-13 certification.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.pgv13sandbox.probe import profiles,chroot_profile,classify,HERE

DEPLOY=ROOT/'apps/print-renderer/build/deployment'
BASE=DEPLOY/'docker-compose.yml'
IMAGE_OVERRIDE=DEPLOY/'docker-compose.validated-image.yml'
SANDBOX_OVERRIDE=DEPLOY/'docker-compose.sandbox.yml'
PROFILE=DEPLOY/'chromium.seccomp.json'


def require(condition,message):
    if not condition: raise ValueError(message)


def validate_report(report):
    require(isinstance(report,dict),'Expected JSON object')
    require(report.get('conclusion')=='CHROOT_RULE_CANDIDATE','Expected successful chroot A/B candidate')
    require(report.get('pgv13_certified') is False,'Unexpected report certification marker')
    image=report.get('image_id','')
    require(isinstance(image,str) and re.fullmatch(r'sha256:[0-9a-f]{64}',image),'Expected immutable image ID')
    require(report.get('reference')==json.loads((HERE/'vendor/source.json').read_text()),'A/B reference differs from supplied profile source')
    rows=report.get('rows')
    require(isinstance(rows,list) and len(rows)==4,'Expected four A/B arms')
    require([r.get('arm') for r in rows]==['builtin','reference','namespaces','namespaces-chroot'],'Unexpected arm order')
    for i,row in enumerate(rows):
        p=row.get('probe') or {};s=p.get('security') or {};smoke=p.get('smoke') or {}
        require(p.get('isolation_ok') is True and p.get('launch_verified') is True,'A/B isolation/launch not verified')
        require(s.get('uid')==10001 and s.get('NoNewPrivs')=='1' and s.get('Seccomp')=='2','A/B UID/NNP/seccomp mismatch')
        require(s.get('CapEff')=='0000000000000000' and s.get('root_write_blocked') is True and s.get('mountns_blocked') is True,'A/B capability/filesystem controls missing')
        require(s.get('apparmor')=='docker-default (enforce)','A/B AppArmor mismatch')
        require(row.get('exit')==(0 if i==3 else 1) and smoke.get('verdict')==('passed' if i==3 else 'failed'),'A/B result/exit mismatch')
    require(classify(rows)=='CHROOT_RULE_CANDIDATE','A/B classifier does not confirm chroot candidate')
    require(json.loads(PROFILE.read_text())==chroot_profile(profiles()[1]),'Deployment profile differs from tested candidate')
    return image


def byte_size(value):
    text=str(value).lower()
    if text.isdecimal(): return int(text)
    match=re.fullmatch(r'(\d+)([kmg])b?',text)
    return int(match[1])*1024**('kmg'.index(match[2])+1) if match else -1


def validate_config(config,image,rollback):
    services=config.get('services') or {}
    require(set(services)=={'print-renderer'},'Merged config must contain only renderer')
    s=services['print-renderer']
    require(s.get('image')==image and s.get('user')=='10001:10001','Merged image/user mismatch')
    require(s.get('network_mode')=='none' and not s.get('networks'),'Renderer must retain network:none')
    require(s.get('read_only') is True and s.get('init') is True,'Readonly/init must remain enabled')
    require(s.get('cap_drop')==['ALL'] and not s.get('cap_add') and not s.get('privileged'),'Capabilities/privileged changed')
    require(not any(s.get(k) for k in ('ports','volumes','devices','pid','ipc')),'Unexpected exposure/mounts/shared namespaces')
    expected={'no-new-privileges:true'}
    if not rollback:expected|={'apparmor=docker-default','seccomp='+str(PROFILE)}
    normalized=set()
    for option in s.get('security_opt') or []:
        if option=='no-new-privileges=true':option='no-new-privileges:true'
        for name in ('apparmor','seccomp'):
            if option.startswith(name+':'):option=name+'='+option[len(name)+1:]
        normalized.add(option)
    require(normalized==expected,'Unexpected security_opt or lost NNP')
    require(byte_size(s.get('mem_limit'))==2*1024**3 and int(s.get('pids_limit',0))==128 and byte_size(s.get('shm_size'))==256*1024**2,'Resource limits changed')
    require(s.get('tmpfs')==['/tmp:rw,noexec,nosuid,size=512m,mode=1777'],'Unexpected tmpfs policy')


def command(args,env=None):
    result=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,timeout=120)
    if result.returncode: raise RuntimeError('Docker operation failed (exit='+str(result.returncode)+'); inspect the selected container/compose locally')
    return result.stdout.strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--apply',action='store_true')
    action.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    mutation_started=False
    try:
        image=validate_report(json.loads(args.report.read_text(encoding='utf-8')))
        cid=command(['docker','compose','-f',str(BASE),'ps','-q','print-renderer'])
        require(bool(cid) and '\n' not in cid,'Expected one running renderer')
        # Selected fields only; no Docker Env or platform credentials are read.
        template='{"image":{{json .Image}},"apparmor":{{json .AppArmorProfile}}}'
        current=json.loads(command(['docker','inspect','--format',template,cid]))
        require(current.get('image')==image,'Running image differs from A/B; repeat A/B for this image')
        require(current.get('apparmor')=='docker-default','Running AppArmor differs from A/B')
        env={**os.environ,'CISSTAT_VALIDATED_RENDERER_IMAGE':image,'CISSTAT_RENDERER_SECCOMP_FILE':str(PROFILE)}
        compose=['docker','compose','-f',str(BASE),'-f',str(IMAGE_OVERRIDE)]
        if not args.rollback:compose+=['-f',str(SANDBOX_OVERRIDE)]
        rendered=json.loads(command(compose+['config','--format','json'],env))
        validate_config(rendered,image,args.rollback)
        applied=args.apply or args.rollback
        if applied:
            mutation_started=True
            command(compose+['up','-d','--no-deps','--no-build','--pull','never','--force-recreate','print-renderer'],env)
        print(json.dumps({'preflight_ok':True,'action':'rollback' if args.rollback else ('apply' if args.apply else 'check'),
                          'image_id':image,'profile':None if args.rollback else str(PROFILE),'service_recreated':applied,
                          'readiness_checked':False,'pgv13_certified':False},ensure_ascii=False))
        return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RuntimeError,subprocess.SubprocessError) as error:
        print(json.dumps({'preflight_ok':mutation_started,'mutation_started':mutation_started,'readiness_checked':False,'error_type':type(error).__name__,'detail':str(error),'pgv13_certified':False}),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
