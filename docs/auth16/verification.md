# AUTH-16 — доказательства и границы

База:2f4812032240b35f1524d0bb31c58fcaf4bc3c85. Runtime изменён только в рамках task overlay; GitHub/VM не изменялись. Исходный INDEX не использовался для staging; strict review выполнялся с отдельным GIT_INDEX_FILE и в отдельном локальном checkout, получившем базу+ZIP.

| Проверка | Результат / протокол |
|---|---|
| TDD RED | Отсутствует demo_lifecycle; scripts/auth16/protocols/red.txt |
| Unit policy/hash | 2/2; unit.txt, default-gates.txt |
| Native PostgreSQL16.2 AUTH-16 | 13/13, zero skips; native-final.txt |
| Native regression AUTH-15 / AUTH-13 | 19/19 +34/34; native-regression.txt |
| Full local gates | 19/19 PASS; default-gates.txt; final-source-gates.txt перепроверяет финальные source bytes |
| Full Jest | 2865 passed,2 штатных skipped,259 suites passed; default-gates.txt |
| UI admission/body / one-time admin batch | 2/2; jest-auth16.txt |
| Existing demo/transport UI | 7/7; jest-targeted.txt |
| Compose/Dockerfile deployment contracts | 17/17; deployment.txt |
| Renderer build / embedded+standalone typecheck | PASS; default-gates.txt |
| Production embedded+standalone | PASS; build-all.txt |
| Actual ASGI / inventory / registry | 255/255 API,259 bindings,621 entries; routes.txt, overlay-routes.txt |
| Strict INDEX / extracted ZIP parity | 567 automatic discovery surfaces + reviewed full source parity; overlay-index.txt |
| Ruff новых lifecycle/CLI/tests | PASS; whitespace git diff --check PASS |
| ZIP | CRC + exact paths + каждый payload byte + SHA256; package_delivery.py |

Native proof включает одновременный code consume и request quota (ровно один победитель), hash-only code storage, idempotency payload conflict/replay, mandatory audit fault rollback, expiry/resume без продления, actual HTTP demo и own upload/413 (включая превышение body ceiling с учётом попытки), точный расход analysis, supervised legacy/full baselines→selection→forecast→export. Expired grant блокирует late worker publication; uncertain сохраняет concurrency reservation. Cleanup удерживает hold/running call/uncertain; quiesced crash HTTP recovery не возвращает request budget. File GC сохраняет referenced shared bytes, прекращает unlink при audit fault, повтор после успеха идемпотентен. В native fixtures используются настоящие PostgreSQL stores; `_schema_ready` установлен после явных scientific migrations для per-schema registry, потому что legacy readiness проверяет public schema.

После полного default прогона дополнительно усилен pre-copy body bound/учёт oversized attempts и перенесены новые imports наверх модулей; final native13/13 и final-source gates относятся к этим окончательным bytes. INDEX/overlay проверки не подменяют runtime concurrency, а production builds не объявляются Docker build.

Известные границы: PostgreSQL16.2 здесь; PG18/Windows — workflow, локально не исполнялись. Два существующих Jest skip сохранены. Docker engine и VM не доступны этой сессии: images должны быть пересобраны оператором. Full scientific pytest всего репозитория/AUTH-CERT, production capacity/backup restore и операционная нагрузка не сертифицированы. Best-effort artifact promotion в сквозном тесте журналирует producer-key409 при повторном freeze visual; расчёт/forecast/export проходит, документный rendering/export отдельно не заявлен. Калибровка изменённого image при включённом CU profile выполняется на VM; локальные profile hashes не выдаются за VM.

Поставка не включает .env/ключи/БД/научные данные/зависимости. Cleanup после retention не обещает немедленное удаление held/uncertain payload; shared physical bytes удаляет только явный quiesced GC. Runbook: docs/auth16/deploy.md. Inventory обновлена после содержательного review новых HTTP/worker/storage границ, проверки strict INDEX не ослаблены.
