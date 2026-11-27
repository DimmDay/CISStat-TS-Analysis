"""Fresh bounded local probes; these alone never issue task certificates."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from scripts.pgv1314cert.verify import ROOT, require, read, sha, validate_files, validate_junit, validate_jest, source_fingerprints

SELECTION=['scripts/pgv13cert/test_contracts.py','scripts/pgv13cert/test_local_acceptance.py',
 'scripts/pgv13cert/test_deployment.py','tests/api/test_pgv13_passport_documents.py',
 'scripts/pgv14/test_page_sets.py','tests/unit/test_pgv13_accept.py','tests/unit/test_pgv14_accept.py',
 'tests/unit/test_pgv1314_certification.py','tests/unit/test_pgv1314_ci.py']
CHECKS=('workspace_dependencies','renderer_build','pytest','print_jest','typography','windows_parity','routes','inventory','typecheck','web_builds')


def validate_local(path):
    path=Path(path).resolve();report=read(path)
    require(report.get('schema_version')=='pgv1314.local/1' and report.get('state')=='PASS' and report.get('passed') is True,'Complete local probes required')
    require(report.get('source_fingerprints')==source_fingerprints(),'Local report has stale sources')
    require(set(report.get('checks',{}))==set(CHECKS) and all(row.get('exit')==0 for row in report['checks'].values()),'Local command coverage/exit incomplete')
    validate_files(path.parent,report['files'])
    expected=read(ROOT/'scripts/pgv1314cert/pytest-cases.json')
    validate_junit(path.parent/'pytest.xml',expected)
    # Actual registry backend properties are emitted by the independent fixture.
    import xml.etree.ElementTree as ET
    for case in ET.parse(path.parent/'pytest.xml').iter('testcase'):
        if case.get('classname','') in ('scripts.pgv13cert.test_contracts','scripts.pgv13cert.test_local_acceptance'):
            props={p.get('name'):p.get('value') for p in case.findall('./properties/property')}
            require(props.get('backend')=='memory','Actual Memory contract backend missing')
    validate_jest(read(path.parent/'jest.json'),read(ROOT/'scripts/pgv1314cert/jest-cases.json'))
    text=(path.parent/'typography.log').read_text(encoding='utf-8')
    for key,value in [('tests',18),('pass',18),('fail',0),('skipped',0),('todo',0),('cancelled',0)]:
        require(re.search(r'^# '+key+r' '+str(value)+r'\s*$',text,re.M),'Typography controls incomplete')
    require('CP1252 filesystem parity: PASS' in (path.parent/'windows_parity.log').read_text(encoding='utf-8'),'CP1252 parity missing')
    route=read(path.parent/'routes.log')
    require(route.get('status')=='ok' and not route.get('added') and not route.get('missing'),'Actual route parity failed')
    return report


def diagnostic_tail(path,limit=60):
    """Console diagnostics only; raw hashed evidence stays byte-exact on disk."""
    path=Path(path)
    if not path.is_file():return 'Diagnostic log is unavailable'
    text='\n'.join(path.read_bytes().decode('utf-8',errors='replace').splitlines()[-limit:])[-12288:]
    text=re.sub(r'([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@',r'\1[REDACTED]@',text)
    text=re.sub(r'(?i)(authorization\s*:\s*)(?:Bearer|Basic)\s+\S+',r'\1[REDACTED]',text)
    text=re.sub(r'(?i)\b(password|passwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)[^\s,;]+',r'\1\2[REDACTED]',text)
    return text


def run_local(out):
    out=Path(out).resolve()
    require(not out.exists() and out!=ROOT and ROOT not in out.parents,'Use a new local evidence directory outside checkout')
    out.mkdir(parents=True,mode=0o700)
    report={'schema_version':'pgv1314.local/1','state':'RUNNING','passed':False,
        'task_certification':{'PGV-13':False,'PGV-14':False},'checks':{}}
    def save():
        target=out/'summary.json';temp=out/'summary.tmp';temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(target)
    save()
    # No production DB/session/worker credentials enter the local probes.
    env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','HOME','USERPROFILE','APPDATA','LOCALAPPDATA','SYSTEMROOT','COMSPEC','PATHEXT','TEMP','TMP','TMPDIR','LANG','LC_ALL','TZ','HTTP_PROXY','HTTPS_PROXY','NO_PROXY','NODE_EXTRA_CA_CERTS','SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE'}}
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',NEXT_TELEMETRY_DISABLED='1',CI='true')
    try:
        report['source_fingerprints']=source_fingerprints();save()
        dist=ROOT/'apps/print-renderer/dist'
        if dist.exists():shutil.rmtree(dist)
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm');require(npm,'npm missing')
        with tempfile.TemporaryDirectory(prefix='pgv1314-',dir=ROOT.parent) as tmp:
            workspace_probe="""const f=require('fs');const lock=JSON.parse(f.readFileSync('package-lock.json','utf8'));const v={node:process.version};for(const n of ['typescript','jest','playwright-core']){v[n]=require(n+'/package.json').version;if(v[n]!==lock.packages['node_modules/'+n].version)throw Error('Installed dependency differs from lock: '+n);}for(const d of ['packages/ui','apps/embedded','apps/standalone','apps/print-renderer']){const n=JSON.parse(f.readFileSync(d+'/package.json','utf8')).name;if(f.realpathSync('node_modules/'+n)!==f.realpathSync(d))throw Error('Workspace resolves another checkout: '+n);}console.log(JSON.stringify(v));"""
            commands={
                'workspace_dependencies':['node','-e',workspace_probe],
                'renderer_build':[npm,'run','build','--workspace=@cisstat/print-renderer'],
                'pytest':[sys.executable,'-m','pytest',*SELECTION,'-q','-o','addopts=','-o','junit_family=xunit1','--basetemp='+str(Path(tmp)/'pytest'),'--junitxml='+str(out/'pytest.xml')],
                'print_jest':['node','node_modules/jest/bin/jest.js','packages/ui/print','apps/print-renderer/src','scripts/pgv07cert','scripts/pgv08cert','--runInBand','--json','--outputFile='+str(out/'jest.json')],
                'typography':['node','--test','--test-reporter=tap','scripts/pgv13typocert/oracle.spec.js','scripts/pgv13typocert/contracts.spec.js'],
                'windows_parity':[sys.executable,'scripts/pgv14/cifix/windows_parity.py'],
                'routes':[sys.executable,'scripts/auth06/check_routes.py'],
                'inventory':[sys.executable,'scripts/auth00/inventory.py','--check'],
                'typecheck':[npm,'run','typecheck:all'],
                'web_builds':[npm,'run','build:all']}
            for name,command in commands.items():
                report['active_check']=name;save()
                print('PGV13/14 local: '+name,flush=True)
                shell=os.name=='nt' and str(command[0]).lower().endswith(('.cmd','.bat'))
                with ExitStack() as streams:
                    log=streams.enter_context((out/(name+'.log')).open('w',encoding='utf-8'))
                    # routes.log is a strict JSON protocol, not a merged console stream.
                    errors=streams.enter_context((out/(name+'.stderr.log')).open('w',encoding='utf-8')) if name=='routes' else subprocess.STDOUT
                    run=subprocess.run(subprocess.list2cmdline(command) if shell else command,cwd=ROOT,env=env,stdout=log,stderr=errors,timeout=900,shell=shell)
                if name=='print_jest' and run.returncode==0:
                    # Portable evidence: retain exact test names, remove machine-root dependence.
                    data=read(out/'jest.json')
                    for suite in data['testResults']:
                        path=Path(suite['name']).resolve();require(path.is_relative_to(ROOT),'Foreign Jest source')
                        suite['name']=path.relative_to(ROOT).as_posix()
                    (out/'jest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                report['checks'][name]={'exit':run.returncode};save()
                require(run.returncode==0,'Local '+name+' failed; inspect its log')
        report['active_check']='source_fence';save()
        require(report['source_fingerprints']==source_fingerprints(),'Source changed during local probes')
        report['files']={p.name:sha(p.read_bytes()) for p in sorted(out.iterdir()) if p.name not in ('summary.json','summary.tmp')}
        report.update(state='PASS',passed=True);save()
        report['active_check']='evidence_validation';save()
        validate_local(out/'summary.json')
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        report.update(state='FAIL',passed=False,error_type=type(error).__name__)
        if isinstance(error,ValueError):report['detail']=str(error)
        report['failed_check']=report.get('active_check','preflight')
        if isinstance(error,subprocess.TimeoutExpired):report['detail']='Local '+report['failed_check']+' timed out'
        log=out/(report['failed_check']+'.log');report['failed_log']=str(log)
        if report['failed_check']=='evidence_validation':
            # This stage is Python validation, not a subprocess. Keep an actual
            # diagnostic artifact instead of pointing at a nonexistent log.
            if not log.exists():
                log.write_text(json.dumps({'check':'evidence_validation',
                    'error_type':report['error_type'],'detail':report.get('detail',type(error).__name__)},
                    ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            report.setdefault('files',{})[log.name]=sha(log.read_bytes())
        stderr_log=out/(report['failed_check']+'.stderr.log')
        if stderr_log.is_file():report['failed_stderr_log']=str(stderr_log)
        save()
        print('PGV13/14 failed check: '+report['failed_check']+'; log: '+str(log),flush=True)
        for line in diagnostic_tail(log).splitlines():print('PGV13/14 diagnostic | '+line,flush=True)
        if stderr_log.is_file():
            print('PGV13/14 stderr log: '+str(stderr_log),flush=True)
            for line in diagnostic_tail(stderr_log).splitlines():print('PGV13/14 diagnostic | '+line,flush=True)
    print(json.dumps({k:report[k] for k in ('state','passed','task_certification','failed_check','failed_log','failed_stderr_log','detail','error_type') if k in report},ensure_ascii=False))
    return 0 if report['passed'] else 1
