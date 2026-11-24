"""Print, never execute, the remainder after a successfully captured baseline."""
import shlex
import subprocess
from scripts.pgv1314cert.verify import ROOT, require, image_equivalence
from scripts.pgv13release import release as R


def plan_release(bundle):
    b,m=R.bundle_load(bundle);old=R.load_baseline(b)
    require(not subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT).strip(),'Generate the VM plan from a clean committed checkout')
    image_equivalence(m['revision'])
    require(not any((b/n).exists() for n in ('ab.json','candidate-first.json','candidate-recreated.json','live.json')),
            'Transport evidence already exists; preserve it and resume manually from the matching documented phase')
    tool=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    exports={'PGV13_BUNDLE':str(b),'PGV1314_TOOL_REVISION':tool,'PGV13_SOURCE_REVISION':m['revision'],'PGV13_SOURCE_TREE':m['tree'],
        'PGV13_API_IMAGE':m['images']['api'],'PGV13_WEB_IMAGE':m['images']['web'],
        'CISSTAT_UDS_RENDERER_IMAGE':m['images']['print-renderer'],'CISSTAT_VALIDATED_RENDERER_IMAGE':m['images']['print-renderer'],
        'CISSTAT_RENDERER_SECCOMP_FILE':str(b/'seccomp.json'),'CISSTAT_RENDERER_IPC_VOLUME':m['volume'],
        'PGV13_CANDIDATE_PROJECT':m['candidate_project'],'PGV13_RENDERER_PROJECT':old['renderer_project'],'PGV13_STACK_PROJECT':old['stack_project']}
    # Projects are passed as shell arguments, never evaluated or inferred via ls/latest.
    text='#!/usr/bin/env bash\nset -euo pipefail\n'
    text+='\n'.join('export '+k+'='+shlex.quote(v) for k,v in exports.items())+'\n'
    text+='''
# Source this reviewed file from the repository root. Existing baseline is retained.
# The existing release tool requires the exact image source HEAD for apply.
# Tool-only descendants return after transport; no release guard is weakened.
test -z "$(git status --porcelain --untracked-files=normal)"
git switch --detach "$PGV13_SOURCE_REVISION"
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY python3 scripts/pgv13release/release.py "$@"
}
pgv13_release prepare-ipc --bundle "$PGV13_BUNDLE"
python3 scripts/pgv13sandbox/probe.py --with-chroot --pids-limit 512 \
  --image "$CISSTAT_UDS_RENDERER_IMAGE" --expected-revision "$PGV13_SOURCE_REVISION" \
  --expected-tree "$PGV13_SOURCE_TREE" --out "$PGV13_BUNDLE/ab.json"
pgv1314_candidate() {
  docker compose -p "$PGV13_CANDIDATE_PROJECT" -f apps/print-renderer/build/deployment/docker-compose.yml \
    -f "$PGV13_BUNDLE/candidate.json" "$@"
}
pgv1314_candidate up -d --wait --wait-timeout 120 --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" --out "$PGV13_BUNDLE/candidate-first.json"
pgv1314_candidate kill -s SIGKILL print-renderer
pgv1314_candidate up -d --wait --wait-timeout 120 --force-recreate --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --previous-report "$PGV13_BUNDLE/candidate-first.json" --out "$PGV13_BUNDLE/candidate-recreated.json"
pgv13_release check --bundle "$PGV13_BUNDLE" --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"

# Definition only. Call explicitly AFTER operator drain, with no active/uncertain jobs.
pgv1314_apply_after_drain() {
  pgv13_release apply --quiesced --bundle "$PGV13_BUNDLE" \
    --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
  python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_RENDERER_PROJECT" --api-project "$PGV13_STACK_PROJECT" \
    --sandbox-report "$PGV13_BUNDLE/ab.json" --out "$PGV13_BUNDLE/live.json"
  git switch --detach "$PGV1314_TOOL_REVISION"
}
# Next: pgv1314_apply_after_drain ; then the new local/run/issue certification commands.
'''
    return text
