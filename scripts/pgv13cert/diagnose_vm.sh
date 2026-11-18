#!/usr/bin/env bash
# Read-only diagnostics. No .env dump, user payload, mutation, privilege or sandbox bypass.
set -uo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
printf 'PGV13 renderer diagnostics (no host changes)\n'
git rev-parse HEAD
uname -sr
for key in kernel.unprivileged_userns_clone user.max_user_namespaces kernel.apparmor_restrict_unprivileged_userns; do
  printf '%s=' "$key"
  sysctl -n "$key" 2>/dev/null || printf 'not_exposed\n'
done
if command -v unshare >/dev/null 2>&1; then
  if unshare -Ur true; then printf 'host_userns_probe=allowed\n'; else printf 'host_userns_probe=denied\n'; fi
fi
if ! command -v docker >/dev/null 2>&1; then
  printf 'Docker unavailable: final-image/VM result NOT CHECKED\n'
  exit 2
fi
docker version --format '{{.Server.Version}}' || exit 2
renderer_compose=apps/print-renderer/build/deployment/docker-compose.yml
cid="$(docker compose -f "$renderer_compose" ps -q print-renderer)"
if [ -z "$cid" ]; then printf 'No running print-renderer: BLOCKED\n'; exit 1; fi
docker inspect --format 'image={{.Config.Image}} image_id={{.Image}} user={{.Config.User}} network={{.HostConfig.NetworkMode}} readonly={{.HostConfig.ReadonlyRootfs}} security={{json .HostConfig.SecurityOpt}} caps={{json .HostConfig.CapDrop}}' "$cid"
# This is inside the same network namespace. Host 127.0.0.1:8907 is not this service.
docker compose -f "$renderer_compose" exec -T print-renderer node -e '
const fs=require("node:fs");
console.log(JSON.stringify({uid:process.getuid(),node:process.version,playwright:require("playwright-core/package.json").version}));
for(const path of ["/proc/self/status","/proc/sys/kernel/unprivileged_userns_clone","/proc/sys/user/max_user_namespaces"]){try{const value=fs.readFileSync(path,"utf8");console.log(path,path.endsWith("status")?value.split("\n").filter(l=>/^(NoNewPrivs|Seccomp|Seccomp_filters|CapEff):/.test(l)).join("; "):value.trim())}catch{console.log(path,"not_exposed")}}
fetch("http://127.0.0.1:8907/readyz",{signal:AbortSignal.timeout(15000)}).then(async r=>{console.log("renderer_readyz",r.status,await r.text());process.exit(r.ok?0:1)}).catch(e=>{console.log("renderer_readyz_error",e.name);process.exit(1)});
'
renderer_result=$?
printf 'API transport (credentials/environment are not printed)\n'
docker compose -f deployment/cisstat-stack/docker-compose.yml exec -T api python -c '
import json,urllib.request
from apps.api.png_renderer_client import PngRendererClient
c=PngRendererClient()
print(json.dumps({"renderer_enabled":c.enabled}))
try:
 with urllib.request.urlopen(c.base_url+"/readyz",timeout=10) as r: print("api_to_renderer",r.status)
except Exception as e:
 print("api_to_renderer_error",type(e).__name__);raise SystemExit(1)
'
transport_result=$?
if [ "$renderer_result" -ne 0 ] || [ "$transport_result" -ne 0 ]; then
  printf 'BLOCKED: inspect readiness and transport separately; no automatic settings change\n'
  exit 1
fi
printf 'Readiness/transport probes passed; P01/P02 final-image content still requires acceptance\n'
