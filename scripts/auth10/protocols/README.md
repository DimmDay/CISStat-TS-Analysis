# AUTH-10 — фактические протоколы

База c13a52bd754f753d9a842aa84af8548af3019fed. Linux, Python3.12, Node24.22.1, native PostgreSQL16.2. Никаких соединений с production VM/DB. Чистый minimal venv отдельно от scientific API runtime.

- red-unit.txt — исходный RED: модуль API keys отсутствовал; red-diagnostics.txt — дополнительный RED: bare API secret не редактировался safe_error.
- unit.txt — 11 unit в minimal runtime; ruff.txt — новый Python код/CLI/tests.
- native-regression-final.txt — 169 native AUTH-02…10 (137 прежних +32 AUTH-10). native-final.txt — финальные33 AUTH-10 с дополнительным checksum oracle после общего регресса. Missing DSN/skip не PASS.
- migration-cli.txt — отдельная чистая native БД, фактические CLI apply / повтор apply / check и imports/files guard из Dockerfile. Docker engine/image build здесь не выполнялся.
- gates-core.txt — все core auth10…01/rules; auth00-index.txt — 44 unit + source inventory + полный reviewed INDEX snapshot на отдельном staged candidate. Legacy scoped ENV case обновлён в AUTH-03 согласно protected durable contract.
- routes-runtime.txt — независимый actual ASGI OpenAPI, registry и inventory; routes-final.txt — source collector; route-delta.json — ровно4 новых HTTP метода, ни одного удалённого, +1 local operator.
- targeted-api.txt — 76 compatibility API tests.
- jest.txt — 253 suites/2833 tests PASS, штатные skips1 suite/2 tests.
- builds.txt — обе production Next оболочки; renderer.txt — renderer build; typecheck.txt — обе TypeScript проверки (после production builds, чтобы не удалять .next параллельно сборке).
- api-full.txt / api-baseline.txt / api-delta.json — полный tests/api против чистого c13a52b в том же scientific runtime. Средовые/pre-existing failures учитываются по точным FAILED-ID; полный набор не объявляется зелёным при таких сбоях.
- delivery-overlay.txt — распаковка финального candidate ZIP поверх чистой базы, явный git add manifest, проверка INDEX/route/generated/unit, CRC/exact bytes. Протокол содержит итог проверки payload; после добавления протокола/итоговой записи worklog ZIP перепакован и все payload байты сверены повторно.

Native ownership fixture не разворачивает весь scientific artifact schema (в логе возможен безопасный optional artifact promotion failure/receipt); проверяются binding/owner и auth commands, а не полная публикация scientific artifacts. Windows и PostgreSQL18 локально не запускались — эти matrix jobs включены в auth10.yml. Browser E2E и VM deployment не выполнялись. Новые scientific entitlement guards/atomic CU/worker fencing относятся к AUTH-11/12/13.
