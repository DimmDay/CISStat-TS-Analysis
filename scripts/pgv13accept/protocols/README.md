# Evidence provenance

`red.txt`: first 16 tests fail because the new module does not exist.
`unit-final.txt`: 28 controls; Docker orchestration/receipt positives use explicit
subprocess doubles. JSON printed there is a test double, NOT a VM receipt.
`native-final.txt`: actual PostgreSQL 16.2 + real production ASGI application,
AuthSession/CSRF, managed worker, jobs/download/audit and 11 cases. PNG transport
is an explicitly controlled loopback TCP double; NOT Chromium/UDS/OCR evidence.
`postgres-environment.json` and `postgres-cleanup.json`: actual local PG facts.
`ocr-final.txt`: actual Tesseract on known synthetic Cyrillic PNG pixels, with
positive/missing-text/wrong-number controls. NOT the product P01/P02 PNG corpus.

Earlier intermediate outputs are retained, including unavailable local Unix
sockets and own fixture/oracle errors. They are not product findings.
`renderer-build.txt`, `release-regression.txt`, `routes.txt`, `local-gates.txt`
and `overlay.txt` document the corresponding final local checks.

Docker/image-native run and human visual review require the VM commands in
`docs/pgv13_document_acceptance.md`. No native image acceptance, human approval
or whole PGV13 certification is claimed by these local protocols.
