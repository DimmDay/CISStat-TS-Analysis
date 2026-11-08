# AUTH-11 — протоколы поставки

Пакет CLOSED: docs/auth11/closure.md. Итоговый полный архив: cisstat-auth11-bf57630-final.zip. Проверки при закрытии документации: closure-checks.txt.

Base/VM: bf5763051285f1f1e74d14e2ce3680a47493c0ca. Linux, Python3.12, Node24; native PostgreSQL16.2. Windows и PostgreSQL18 локально не запускались, соответствующие jobs добавлены в auth11.yml. Docker/VM не выполнялись.

- red-unit.txt, red-json-suffix.txt, red-ui.txt — настоящие RED до исправлений, не результаты финального кода.
- unit-no-resource.txt — минимальный unit9/9 с заблокированным Unix-only resource; не заменяет Windows CI.
- unit.txt / minimal-unit.txt — 9/9, минимальный venv только scripts/auth11/requirements.txt, без полного scientific runtime.
- native-final.txt — обязательный verify_postgres.py, 23/23, без skips: реальные login/CSRF/Account, 173-route matrix, baseline pipeline, downgrade/revoke/outage, object/credential/scope/rows/model provenance, kernel input recheck.
- native-regression.txt — AUTH-02…11, 193/193, реальный disposable PostgreSQL; это authority/ownership fixture, без полного artifact promotion catalogue0007. Предупреждение promotion не считается проверкой durability публикации.
- panel-fix.txt — 70 passed /1 штатно skipped после исправления проверки PanelFrame.frame. Численный алгоритм не менялся.
- api-baseline.txt / api-full.txt / api-delta.json — чистый bf57630 и кандидат в одном окружении:3451 passed/43 skipped/11 failed, одинаковые FAILED-ID. Полный scientific suite НЕ зелёный. Прежние failures: pwsh, старые signature/ASGI lazy routes asserts, catalog/neural и certificate docs expectations. Новых failures нет.
- gates.txt — auth11…01/rules PASS. Native lifecycle проверен отдельно, сообщение runner о невыбранных PostgreSQL gates относится только к этому запуску.
- routes-delta.json — прямое сравнение HTTP method/path с Git HEAD bf57630: добавлений/удалений нет.
- routes.txt — независимый actual ASGI:239 HTTP == inventory239, registry243, full inventory574, added/missing пусты.
- generated-gates.txt — auth11/auth06/auth01 после обновления карты/контрактов PASS.
- delivery-final.txt — повтор auth11/auth01/auth00 с финальными комментариями/evidence: всё PASS, оба INDEX fences и49 unit.
- auth00-tests.txt и delivery-overlay.txt — AUTH-00 unit, INDEX parity и воспроизведение доставки: чистая база → ZIP → явный git add только task manifest → local gates. Source index не меняется, commit/push отсутствуют.
- jest.txt — 254 suites passed +1 skipped;2837 passed +2 skipped tests. ui.txt — адресные4/4.
- builds.txt / renderer.txt / typecheck.txt — production Next обе оболочки, renderer, TypeScript обе оболочки.
- ruff.txt — новые Python модули/тесты/CLI. Строгие frozen inventory/генерация повторно проверяются перед упаковкой.

ZIP содержит только изменённые/новые файлы AUTH-11; scripts/auth11/files.txt — полный состав. Package delivery проверяет CRC и каждый byte. После добавления финального delivery протокола и записи журнала ZIP перепаковывается и снова сверяется. Протоколы не имитируют runtime certification AUTH-12/13 или производство.
