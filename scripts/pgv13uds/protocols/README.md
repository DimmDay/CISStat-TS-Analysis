# PGV13 UDS protocols

Final evidence: final-python251, overlay-python251 (clean db10ada + ZIP),
final-ts185, postgres24, strict-wire29, renderer-build, web-builds, index/routes.
summary.json/delivery.json identify the scope. No skips/xfail in final suites.

Other files are intermediate TDD/authoring runs and may contain failures.
In particular controls-intermediate and legacy-first-green-attempt retain
test-authoring failures before sys.argv/stderr corrections. Valid red-legacy
uses the pre-guard behavior (apply0 instead of refusal2), not that author error.
red-reader uses explicit HTTP Connection:close and retains the response object;
it fails without explicit reader.close.

Native AF_UNIX/Docker/Chromium acceptance: NOT RUN here (EPERM/no Docker).
flock-native is a separate real Linux exec/lock probe; it is not UDS evidence.
Wire tests are actual HTTP bytes with an explicit TCP socket adapter.
VM metadata/FS policy controls use doubles. Follow docs/pgv13_uds_transport.md.
