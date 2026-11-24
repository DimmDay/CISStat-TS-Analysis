#!/usr/bin/env python3
"""Task-scoped PGV13/14 certification; never confuses contracts with native proof."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.pgv13accept import verify_vm as A
from scripts.pgv13release import release as R
from scripts.pgv14.client import CASES, expected_case

COMPILED_FILES=(
    'apps/print-renderer/src/rendererCore.js','apps/print-renderer/src/renderWorker.js',
    'packages/ui/print/printPassport.js','packages/ui/print/printComparison.js',
    'packages/ui/print/printLayout.js','packages/ui/print/printSchema.js','apps/print-renderer/src/pageSet.js')
HOST_PREFIXES=('docs/','worklog/','tests/','.github/','scripts/pgv13accept/','scripts/pgv14/',
               'scripts/pgv13cert/','scripts/pgv13local/','scripts/pgv1314cert/')
HOST_FILES={'scripts/local_gates.py','scripts/local_gates.md','AGENTS.md','spec_passport_graphics_visual.md'}


def require(value,message):
    if not value:raise ValueError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def read(path):
    def pairs(values):
        out={}
        for key,value in values:
            require(key not in out,'Duplicate JSON key');out[key]=value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=pairs,
        parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def write_new(path,value):
    path=Path(path)
    with path.open('xb') as f:
        os.chmod(path,0o600);f.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def safe_file(root,name):
    root=Path(root).resolve();part=Path(name)
    require(not part.is_absolute() and part.parts and '..' not in part.parts,'Unsafe evidence path')
    path=root/part
    require(all(not p.is_symlink() for p in [path,*path.parents] if p!=root and root in p.parents),'Evidence symlink forbidden')
    require(path.resolve().is_relative_to(root) and path.is_file(),'Evidence file missing/outside root')
    return path


def validate_files(root,files):
    require(isinstance(files,dict) and files,'Evidence hashes missing')
    for name,digest in files.items():
        require(isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest),'Invalid evidence digest')
        require(sha(safe_file(root,name).read_bytes())==digest,'Evidence hash changed: '+name)


def validate_junit(path,expected):
    cases=list(ET.parse(path).iter('testcase'))
    actual=[c.get('classname','')+'::'+c.get('name','') for c in cases]
    require(actual and Counter(actual)==Counter(expected),'Exact pytest contract coverage required')
    require(not any(c.find(k) is not None for c in cases for k in ('failure','error','skipped')),'JUnit errors/failures/skips/xfail forbidden')
    return len(cases)


def validate_jest(data,expected):
    require(data.get('success') is True,'Jest must succeed')
    require(data.get('numTotalTests')==data.get('numPassedTests')==len(expected),'Jest total coverage changed')
    require(all(data.get(k,0)==0 for k in ('numFailedTests','numPendingTests','numTodoTests')),'Jest incomplete')
    actual=[]
    for suite in data.get('testResults',[]):
        require(suite.get('status')=='passed','Jest suite failed')
        raw=Path(suite['name'])
        require('..' not in raw.parts,'Unsafe Jest path')
        path=(raw if raw.is_absolute() else ROOT/raw).resolve()
        require(path.is_relative_to(ROOT),'Foreign Jest path')
        for case in suite.get('assertionResults',[]):
            require(case.get('status')=='passed','Jest skipped/failed assertion')
            actual.append([path.relative_to(ROOT).as_posix(),case['fullName']])
    require(actual and Counter(map(tuple,actual))==Counter(map(tuple,expected)),'Jest exact names required')
    return len(actual)


def assert_host_only_changes(paths):
    require(all(p in HOST_FILES or p.startswith(HOST_PREFIXES) for p in paths),'Runtime differs from the pinned images; rebuild required')


def image_equivalence(revision):
    paths=subprocess.check_output(['git','diff','--name-only','-z',revision,'HEAD'],cwd=ROOT).decode('utf-8').rstrip('\0').split('\0')
    paths=[p for p in paths if p]
    assert_host_only_changes(paths)
    A.product_sources(revision)  # Every P01/P02/API/shared print runtime byte at image revision.
    return paths


def source_fingerprints():
    paths=set(subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0'))
    paths={p for p in paths if p.startswith(('app/','apps/','packages/','validation/','src/','rules/','shared/','config/'))
           and not p.endswith('.md') and '/protocols/' not in p}
    paths.update(['package.json','package-lock.json','.dockerignore','AGENTS.md','spec_passport_graphics_visual.md',
                  '.github/workflows/pgv1314cert.yml','scripts/local_gates.py',
                  'scripts/pgv13accept/verify_vm.py','scripts/pgv13accept/oracles.py','scripts/pgv14/client.py',
                  'scripts/pgv14/pages.py','scripts/pgv14/verify_vm.py','scripts/pgv14/cifix/windows_parity.py',
                  'scripts/pgv13typocert/contracts.spec.js','scripts/pgv13typocert/oracle.spec.js'])
    paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'scripts/pgv1314cert').glob('*') if p.suffix in ('.py','.json','.txt') and p.name!='files.txt')
    for directory in ('scripts/pgv13cert','scripts/pgv13local','scripts/pgv13accept','scripts/pgv14','scripts/pgv13typocert','scripts/pgv07cert','scripts/pgv08cert','scripts/auth00'):
        paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT/directory).glob('*') if p.suffix in ('.py','.js','.ts','.tsx','.json'))
    paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'scripts/pgv1314cert/cifix').glob('*.py'))
    paths.update(['tests/unit/test_pgv1314_ci.py','tests/unit/test_pgv1314_certification.py','tests/unit/test_pgv13_accept.py','tests/unit/test_pgv14_accept.py',
        'tests/unit/test_pgv13_release.py','tests/api/test_pgv13_passport_documents.py','scripts/auth06/check_routes.py',
        'docs/auth00/inventory.json','docs/auth00/policy_review.json','jest.config.js','jest.tsconfig.json','jest.setup.js'])
    out={}
    for name in sorted(paths):
        data=(ROOT/name).read_bytes()
        if Path(name).suffix in ('.py','.ts','.tsx','.js','.json','.txt','.sql','.yaml','.yml','.md') or Path(name).name in ('Dockerfile','.dockerignore'):
            data=data.replace(b'\r\n',b'\n')
        out[name]=sha(data)
    return out


def validate_context(m,report,live,extra):
    R.validate_manifest(m)
    require(report.get('schema_version')=='pgv13.documents/2','Native every-page report required; capture is not certification')
    require(report.get('images')==m['images'] and report.get('image_revision')==m['revision'] and report.get('image_tree')==m['tree'],'Native image identity differs')
    require(report.get('renderer_project')==m['candidate_project'] and report.get('volume')==m['candidate_volume'],'Dedicated candidate required')
    require(set(report.get('compiled_renderer_sha256',{}))==set(COMPILED_FILES),'Exact seven compiled modules required')
    A.check_client_result({'passed':report.get('automated_passed'),'backend':'postgres','cases':report.get('cases'),
        'backend_proof':report.get('backend_proof'),'negative_controls':report.get('negative_controls')})
    for actual,plan in zip(report['cases'],CASES):
        text,numbers,counts=expected_case(plan)
        require((actual.get('expected_text'),actual.get('expected_numbers'),actual.get('expected_counts'))==(text,numbers,counts),'Independent semantic oracle weakened')
    require(live.get('images')==m['images'] and live.get('volume')==m['volume'],'Live API/web/renderer pins differ')
    require(all(live.get(k) is True for k in ('markers_verified','api_ipc_readonly','renderer_hardening')),'Live hardening/markers incomplete')
    require(extra.get('passed') is True and extra.get('cleanup_passed') is True,'Native page budget controls/cleanup failed')
    require((extra.get('image_id'),extra.get('renderer_image_id'),extra.get('volume'),extra.get('renderer_container_id'))==
        (m['images']['api'],m['images']['print-renderer'],m['candidate_volume'],report.get('renderer_container_id')),'Budget controls used another image/candidate')
    A.V.metrics_ok(extra['before'],extra['after'])
    require(extra.get('source_sha256')==sha((ROOT/'scripts/pgv1314cert/extra_client.py').read_bytes().replace(b'\r\n',b'\n')),'Native control source changed')
    require(set(extra.get('checks',{}))=={'page_cap','oversized_atom'},'Exact native page budget controls required')
    for key,code in [('page_cap','export_too_large'),('oversized_atom','render_content_overflow')]:
        row=extra['checks'][key]
        require(row.get('passed') is True and row.get('code')==code and row.get('retryable') is False and row.get('http_status')==413 and row.get('retryable_header')=='false','Wrong native terminal page budget error')


def issue(args):
    from scripts.pgv1314cert.local import validate_local
    from scripts.pgv1314cert.vm import validate_release, observe_live
    require(not args.out.exists(),'Certificate is immutable; choose a new output path')
    local=validate_local(args.local)
    b,m,release_hashes=validate_release(args.bundle)
    image_equivalence(m['revision'])
    report=read(args.report);bindings=read(args.report.parent/'bindings.json')
    require(bindings.get('schema_version')=='pgv1314.native_bindings/1','Final native run bindings missing')
    require(bindings['local_sha256']==sha(args.local.read_bytes()) and bindings['report_sha256']==sha(args.report.read_bytes()),'Run/local/report binding changed')
    require(bindings['release_hashes']==release_hashes,'Release evidence changed after native run')
    require(bindings['source_fingerprints']==source_fingerprints(),'Tool/runtime sources changed after native run')
    from scripts.pgv1314cert.vm import native_evidence_files
    require(set(bindings['files'])==native_evidence_files(report),'Native evidence manifest incomplete')
    validate_files(args.report.parent,bindings['files'])
    extra=read(args.report.parent/'page-budgets.json')
    accepted=A.validate_acceptance(args.report,args.review,page_sets=True)  # Every PNG, OCR TSV and every page of review, again.
    require(accepted.get('p01_p02_accepted') is True,'Human every-page acceptance missing')
    live=observe_live(m,R.load_baseline(b))  # Read-only fresh live image identity, not a stale report flag.
    validate_context(m,report,live,extra)
    for case,plan in zip(report['cases'],CASES):
        p=read(args.report.parent/(case['id']+'.payload.json'))
        kind='passport_comparison' if plan['kind'].startswith('compare') else 'passport_record'
        require(p['sections'] and all(s['kind']==kind for s in p['sections']),'P01/P02 source role substituted')
        if plan['kind']=='set':require(len(p['sections'])==3 and case['delivery_format']=='zip','Reused must be exactly three physical passports')
    certificate={'schema_version':'pgv.tasks_certification/1','state':'CERTIFIED','issued_at':datetime.now(timezone.utc).isoformat(),
        'task_certification':{'PGV-13':True,'PGV-14':True},'full_pgv_certified':False,
        'scope':'PGV13 P01/P02 durable builders and PGV14 pagination/download; PGV15 UI/PGV16/PGV-CERT excluded',
        'case_count':11,'page_count':sum(len(c['pages']) for c in report['cases']),
        'images':m['images'],'image_revision':m['revision'],'image_tree':m['tree'],
        'reviewer':accepted['reviewer'],'review_sha256':sha(args.review.read_bytes()),
        'native_report_sha256':sha(args.report.read_bytes()),'bindings_sha256':sha((args.report.parent/'bindings.json').read_bytes()),
        'local_sha256':sha(args.local.read_bytes()),'release_hashes':release_hashes,'live_at_issue':live,
        'source_fingerprints':source_fingerprints(),'local_checks':local['checks']}
    write_new(args.out,certificate)
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    local=sub.add_parser('local');local.add_argument('--out',type=Path,required=True)
    plan=sub.add_parser('plan');plan.add_argument('--bundle',type=Path,required=True)
    run=sub.add_parser('run')
    for parser in (run,):
        parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--local',type=Path,required=True)
        parser.add_argument('--postgres-image',required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--tesseract',default='tesseract')
    cert=sub.add_parser('issue')
    for name in ('bundle','local','report','review','out'):cert.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.action=='issue':return issue(args)
        if args.action=='local':
            from scripts.pgv1314cert.local import run_local
            return run_local(args.out)
        if args.action=='plan':
            from scripts.pgv1314cert.resume import plan_release
            print(plan_release(args.bundle));return 0
        from scripts.pgv1314cert.vm import run_native
        return run_native(args)
    except (OSError,ValueError,KeyError,TypeError,ET.ParseError,subprocess.SubprocessError) as error:
        print(json.dumps({'state':'NOT_CERTIFIED','task_certification':{'PGV-13':False,'PGV-14':False},
            'error_type':type(error).__name__,'detail':str(error) if isinstance(error,ValueError) else 'Inspect evidence paths/dependencies; no certificate issued'},ensure_ascii=False))
        return 2

if __name__=='__main__':raise SystemExit(main())
