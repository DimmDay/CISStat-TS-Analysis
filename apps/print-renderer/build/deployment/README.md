# PGV-08 renderer deployment — recovery delivery

Build context is repository root. Dockerfile/compose/runbook are source files,
explicitly excepted from the repository's generic build/ ignore rule.

```bash
docker build -f apps/print-renderer/build/Dockerfile -t cisstat-print-renderer:pgv08-fix .
docker compose -f apps/print-renderer/build/deployment/docker-compose.yml config
docker compose -f apps/print-renderer/build/deployment/docker-compose.yml up -d
```

Isolation: network_mode: none (network none), USER 10001, read-only root,
cap_drop ALL, no-new-privileges, init/reaper, tmpfs /tmp noexec/nosuid, memory
2 GiB/pids 128. No host ports are published: network none and a host port mapping
are incompatible as a usable transport. For the standalone acceptance invoke
HTTP from inside the container via exec; Python job transport belongs to PGV-09.
Do not change to host networking for convenience.

```bash
docker compose -f apps/print-renderer/build/deployment/docker-compose.yml exec -T print-renderer node -e "fetch('http://127.0.0.1:8907/readyz').then(async r=>{console.log(r.status,await r.text());process.exit(r.ok?0:1)})"
docker compose -f apps/print-renderer/build/deployment/docker-compose.yml exec -T print-renderer node apps/print-renderer/dist/apps/print-renderer/src/smoke.js --smoke
docker compose -f apps/print-renderer/build/deployment/docker-compose.yml exec -T print-renderer id
```

Final image acceptance must run Cyrillic/IH/A4, pHYs 11811 px/m (300 ppi),
source-denominator checks, cold launch timeout and recovery. Node 24 supplies
zlib.crc32, playwright-core 1.57.0 is matched to chromium-1200. Runtime system
fonts are DejaVu Sans. node:24-bookworm-slim is a moving base tag: freeze its
resolved digest in the release pipeline before claiming byte-reproducible builds.

GET /healthz is liveness; GET /readyz checks browser/fonts/bundle and a mini-PNG.
Both successful and failed readiness results are cached for 30 seconds by
default (CISSTAT_PRINT_RENDERER_READYZ_CACHE_S), so repaired dependencies may
remain unavailable until TTL expiry. POST /v1/render accepts frozen payload only;
POST /v1/smoke runs the same pipeline. No browser cookies or platform credentials.
options.scale is finite 0.05..1, geometry also checked against the 12 MP catalog
limit; a mini-probe is not a production page. Invalid scale -> 422 before browser.

A render has its own BrowserServer and remaining-deadline launch/connect timeout.
Chromium sandbox is explicitly enabled, not inferred from absence of a flag in
our custom args. Deadline kills this server, never another request's browser;
a late launch is killed before newContext. Playwright also owns cold-launch
cleanup on launch timeout. Failed launch/readiness is fail-closed.

## Deployment risks and required host prerequisites

R1: Chromium sandbox needs kernel user namespaces and an appropriate seccomp
policy. Confirm on the target host; if Docker default policy denies required
userns syscalls, provide a reviewed restricted policy. Do NOT set --no-sandbox,
privileged, SYS_ADMIN or disable no-new-privileges as a workaround. Until the
host supports this profile readiness must fail rather than weaken isolation.
R2: Docker build/runtime and real browser/OCR cannot be inferred from static
checks. Run the final-image gate above and the recertification probes on the
actual target. This delivery does not claim an image was run where Docker is absent.
R3: Cold startup is now per job (isolation over warm-browser latency). Benchmark
CPU/memory at concurrency 2 before raising it; /tmp is ephemeral, no persisted HTML.
R4: Do not publish user-controlled SVG directly. Frozen producer SVG still passes
reference allowlist sanitation, JS-off/SW-block/CSP/request allowlist and network none.
