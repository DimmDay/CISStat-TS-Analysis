# TASK-1…7 certification runners

`requirements.txt` + normal project npm/API/AUTH dependencies. All commands run at repo root.

- `python scripts/local_gates.py --only kabinet-demo-cert --skip-install`:5 deployment/spec oracles +8 targeted Jest suites (70 tests). Native/browser not implicit.
- `CISSTAT_AUTH_TEST_DSN` disposable PostgreSQL: `python scripts/kabinet_demo_cert/verify_postgres.py`. Zero DSN→exit2, skip→FAIL. Applies existing AUTH migrations in test fixtures, never target production.
- Protocol `native-authcert-demo.txt`: additional six existing AUTH-CERT demo tests through full apps.api.main. This execution used real PG16.2 TCP because the sandbox has no Unix sockets. The production/test authority code was unchanged.
- `browser_smoke.cjs SHELL enabled|disabled [http-only]`: production Next `.next` required. Default tries Chromium (path `CISSTAT_CHROMIUM` or /usr/bin/chromium); missing/blocked browser is FAIL, never silent skip. HTTP-only is explicitly compiled SSR/static JS + HTTPS/real first-party proxy with controlled authority stub; it does NOT execute client navigation/render geometry. Synthetic public pair only, conflicting runtime pair intentionally cannot replace the build value. No real production service/configuration is contacted.

Reproduce fixture builds on a separate test checkout (PowerShell):

```powershell
$env:NEXT_PUBLIC_DEMO_LOGIN = 'cert-public-demo'
$env:NEXT_PUBLIC_DEMO_PASSWORD = 'cert-public-pair-not-personal'
npm run build:all
node scripts/kabinet_demo_cert/browser_smoke.cjs standalone enabled http-only
node scripts/kabinet_demo_cert/browser_smoke.cjs embedded enabled http-only
# Optional real Chromium client E2E on a host that permits its IPC:
node scripts/kabinet_demo_cert/browser_smoke.cjs standalone enabled
node scripts/kabinet_demo_cert/browser_smoke.cjs embedded enabled
Remove-Item Env:NEXT_PUBLIC_DEMO_LOGIN, Env:NEXT_PUBLIC_DEMO_PASSWORD
npm run build --workspace=@cisstat/ts-analysis-standalone
node scripts/kabinet_demo_cert/browser_smoke.cjs standalone disabled http-only
```

Never build a production deployment with cert fixtures as working credentials. Real public campaign configuration and VM commands: docs/kabinet_demo_cert/deploy.md.
Full default run in default-gates.txt occurred during oracle development: it has initial oracle whitespace/map failures. final-gates.txt proves corrected kabinet-demo-cert + AUTH00; consolidated-gates.json explicitly combines29 unchanged default PASS with2 final PASS. Full Jest2902/2 skips, renderer/typechecks were green; no claim of a single uninterrupted31/31 default invocation.
