# AUTH-12 — протоколы

База ad4fd342eeba39161e69cce736d9d5d25f1cea2f. Linux/Python3.12/Node24/PostgreSQL16.2. Windows/PG18 локально не запускались; auth12.yml добавляет эти CI jobs. Docker build/VM не выполнялись.

- red-unit.txt — RED отсутствующего contract module до реализации, не результат финального кода.
- minimal-unit.txt / minimal-no-resource.txt —5/5 в минимальном AUTH venv, в том числе с resource заблокированным; не Windows certification.
- native-regression.txt —226/226 AUTH-02…12:193 прежних +33 AUTH-12; без skips. После него добавлены два оракула audit-fault rollback для settle/policy и завершена штатная конструкция SessionService.
- native-final.txt — финальные35/35 обязательного verify_postgres.py, реальный PostgreSQL, без skips. Последние CU/API/analysis/slot, shared sponsor/campaign/grant, normalized idempotency, current authority, rotation/downgrade/expiry/revoke, monthly rollover, reserve/extend/settle/release, overflow/SQL immutability, audit+job outbox faults, fresh process, clean DB CLI apply/retry/check, no auto-migration.
- native-no-dsn.txt — обязательный gate возвращает2 без DSN; native PASS не заявляется.
- gates.txt —auth12…01/rules PASS. Сообщение runner о невыбранных native gates относится к этому запуску; native проверен отдельно.
- jest.txt —2837 passed/2 skipped,254 passed suites/1 skipped. builds.txt — обе production Next builds; renderer.txt/typecheck.txt — renderer/обе оболочки.
- api-targeted.txt / api-baseline.txt / api-delta.json — затронутые audit/auth-adapter/deployment tests:115 passed/2 одинаковых прежних failures на кандидате и чистом ad4fd34. Старый require_admin_role signature и lazy FastAPI app.routes assertion; новых FAILED-ID нет. Полный scientific pytest не запускался и зелёным не объявляется; научные kernels/UI/HTTP handlers не менялись.
- routes.txt / routes-delta.json — actual ASGI239,registry243,inventory580; HTTP method/path delta пустой. Generated OpenAPI/TS/BFF прежние.
- ruff.txt — новые Python modules/tests/CLI. delivery-overlay.txt — чистый ad4fd34 → ZIP → явный task-only git add → local gates/INDEX parity.

Fixture AUTH-09/11 проверяет authority/ownership/scientific admission без полного artifact catalogue0007; optional promotion warning не считается artifact durability certification. AUTH-12 не включает broker consumer/реальные worker adapters или commercial CU launch (AUTH-13/14). Trusted coordinator доступен только серверному вызывающему после object/actual-workload guard.
