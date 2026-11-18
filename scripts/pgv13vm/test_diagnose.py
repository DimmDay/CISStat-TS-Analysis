"""Diagnostic-shell controls, with Docker stubbed; never a VM/sandbox test."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]

DOCKER = r'''
import errno, os, sys, types, urllib.error, urllib.request
args=sys.argv[1:]
scenario=os.environ['PGV13_DIAG_CASE']
if args[0]=='version': print('29.9.2')
elif args[0]=='info': print('["name=apparmor","name=seccomp,profile=builtin"]')
elif args[0]=='inspect':
 assert '.AppArmorProfile' in args[-2] and '.HostConfig.UsernsMode' in args[-2], args
 print('apparmor=docker-default userns= readonly=true')
elif 'ps' in args: print('cert-fake-container')
elif 'print-renderer' in args and 'exec' in args:
 code=args[-1]
 for path in ('/proc/self/attr/current','/proc/self/uid_map','/proc/self/gid_map'):
  assert path in code, path
 print('container sandbox profile evidence collected (stub)')
 print('renderer_readyz',503 if scenario=='browser_blocked' else 200)
 sys.exit(1 if scenario=='browser_blocked' else 0)
elif 'api' in args and 'exec' in args:
 # Execute the exact Python probe, injecting only its external dependencies.
 module=types.ModuleType('apps.api.png_renderer_client')
 class Client:
  enabled=True
  base_url='http://127.0.0.1:8907'
 module.PngRendererClient=Client
 sys.modules['apps.api.png_renderer_client']=module
 class Response:
  status=200
  def __enter__(self): return self
  def __exit__(self,*args): pass
 def request(*args,**kwargs):
  if scenario=='http_503':
   raise urllib.error.HTTPError('http://secret.invalid',503,'Unavailable',None,None)
  if scenario in ('unreachable','browser_blocked'):
   raise urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED,'credential-sentinel'))
  return Response()
 urllib.request.urlopen=request
 exec(compile(args[-1],'<real-api-probe>','exec'))
else: raise AssertionError(args)
'''


@pytest.mark.parametrize('scenario,expected_exit,marker', [
    ('http_503',1,'api_to_renderer_reached_http 503'),
    ('unreachable',1,'api_to_renderer_unreachable'),
    ('browser_blocked',1,'BLOCKED'),
    ('healthy',0,'Readiness/transport probes passed'),
])
def test_diagnostic_preserves_layers_and_exit_codes(tmp_path,scenario,expected_exit,marker):
    # Copy the real script to a minimal fake checkout, do not touch real Docker.
    script=tmp_path/'scripts/pgv13cert/diagnose_vm.sh'
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/'scripts/pgv13cert/diagnose_vm.sh',script)
    commands=tmp_path/'bin';commands.mkdir()
    docker=commands/'docker'
    docker.write_text('#!'+sys.executable+'\n'+DOCKER)
    docker.chmod(0o755)
    for name,body in [('git','echo cert-sha'),('sysctl','echo 1'),('unshare','exit 1')]:
        cmd=commands/name;cmd.write_text('#!/bin/sh\n'+body+'\n');cmd.chmod(0o755)
    result=subprocess.run(['bash',str(script)],text=True,capture_output=True,timeout=10,
        env={**os.environ,'PATH':str(commands)+os.pathsep+os.environ['PATH'],
             'PGV13_DIAG_CASE':scenario})
    assert result.returncode==expected_exit,(result.stdout,result.stderr)
    assert marker in result.stdout,(result.stdout,result.stderr)
    assert 'apparmor=docker-default' in result.stdout
    assert '"target_scope": "loopback"' in result.stdout
    assert 'credential-sentinel' not in result.stdout+result.stderr
    assert 'secret.invalid' not in result.stdout+result.stderr
    if scenario=='unreachable':
        assert '"reason_type": "ConnectionRefusedError"' in result.stdout
        assert '"errno": 111' in result.stdout
    assert 'Traceback' not in result.stderr
