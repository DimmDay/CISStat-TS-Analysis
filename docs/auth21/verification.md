# AUTH-21 — матрица проверки

База `a0a2af6`. Native-среда: disposable PostgreSQL 16.2 (pgserver, отдельная схема на тест). Норматив: `spec_billing_accounts.md` §13, E1–E6; `spec_auth_architecture.md` AUTH-21.

## TDD

- **RED**: `tests/unit/test_auth21_wallet.py` — 18 контрактных тестов на отсутствующем модуле `apps/api/billing/wallet.py` (suite-level ImportError) — зафиксирован до реализации.
- **GREEN unit**: 18/18 (`auth21` gate). Включая FEFO-порядок (§13.5), точные целые сплиты (D7), классификацию хвостов по expiry (E2), границы выдачи (purchased бессрочен, included требует cycle-expiry, promotional требует основание).
- **GREEN native** (`tests/integration/test_auth21_wallet.py`, `scripts/auth21/verify_postgres.py`): **17/17 PASS, 0 skips**:

| Оракул | Пример/правило |
|---|---|
| Миграция: apply→repeat False→check_schema→checksum | прежние SQL/checksums не менялись (цепочка 0019…0032) |
| SQL-гварды: счётчик/DELETE/проводку нельзя править напрямую | D2, immutable-история |
| Unique-основания: повтор `issue_included('base')`, повтор `origin_order` | E3/E6: двойное начисление невозможно |
| **E1**: reserve 2 050 000 → settle → included 0 / purchased 150 000 | included расходуется раньше purchased |
| FEFO-порядок: included → promotional → purchased (равный expiry), умирающие раньше бессрочных | §13.5 |
| Недостаток: 402 `cu_insufficient` с required/available | §13.6 |
| Гонка за последние 10: ровно один reserve, второй 402 | E3 |
| Release после sweep: хвост → `expired`, не оживает | E2/D6 |
| Settle по pinned после sweep: spent честно | D6 |
| Extend: дельта-pinning; extend «позднего» резервации — весь hold | D5 |
| Locked: 403 `wallet_locked`, разблокировка явная с CAS | D12 |
| Refund: refund_pending исключает расход; reserved нельзя вернуть (409 `refund_not_eligible`); refund_failed/confirmed | E4 |
| Sweep: только available→expired, reserved не трогает, идемпотентен | D17 |
| Без кошелька: резервации/проводки не создаются, поведение прежнее | D1 (аддитивность) |
| cu=0: кошелёк не трогается | unpriced-дефолт AUTH-14 |
| Отказ аудита откатывает выдачу кредита целиком | D9/R7 |
| Дубликат create_wallet / план demo отказ | D1 |

## Регресс (тот же disposable PG 16.2)

- AUTH-12 `test_auth12_ledger`: **35/35** — coordinator-семантика не задета.
- AUTH-18 `test_auth18_saga`: **16/16**.
- AUTH-20 `test_auth20_reconciliation`: **43/43**.
- AUTH-13…19 (`test_auth13_workers`, `13_bootstrap`, `14_compute`, `15_demo`, `16_lifecycle`, `17_team`, `19_email_oidc`): **161/162**; единственный FAIL — `test_auth14_compute.test_pelt_actual_fits_are_charged_and_get_rejects_corrupted_profile` («applicable») — предсуществующий средовый класс песочницы (стек ruptures/scipy, зафиксирован в AUTH-19/AUTH-15 записях), к AUTH-21 не относится: протокол `native-regression.txt`.

## AUTH-00 (check_routes)

- Новых/удалённых HTTP-маршрутов **нет**; изменения исполнения — внутри существующих handlers AUTH-12.
- `scripts/auth06/check_routes.py`: `status ok, actual_api=274=inventory_api, registry_bindings=278, added=[], missing=[]`.
- `scripts/auth00/inventory.py --write`: entries 651 (counts без изменений), source_fingerprints 456→464 (`billing/wallet.py`, `billing/wallet_migrations.py` + reviewed_sources AUTH-21).
- `docs/auth00/policy_review.json`: новый policy `billing.wallet` (threats T02/T06/T11/T13/T15, follow_up AUTH-21/22/23/24/CERT) + 6 reviewed_sources.
- AUTH-00 unit (`test_auth00_inventory`, `test_auth00_precommit`): **53/53 OK**.

## Каталог аудита и пины

- `auth_wallet_changed` — обязательный (fail-closed); каталог **42→43**.
- Пины обновлены честно с обоснованием: `tests/unit/test_auth20_ops.py::test_catalog_size_43`, комментарий/проверка в `tests/api/test_doclog8_monitoring.py`.
- Движения резерваций остаются под обязательным `auth_reservation_changed` (той же транзакции).

## Гейты локально

- `auth21` (unit) — PASS; `auth21-postgres` — PASS на disposable PG (native 17/17, 0 skips).
- compileall/`py_compile` изменённых и новых модулей — PASS.
- `auth00` unittest 53/53; фактический ASGI — PASS (см. выше).

## Границы честности

- Docker engine в сессии отсутствует: сборка образов и VM-деплой не выполнялись (команды — `docs/auth21/deploy.md`, сборка api на VM; web не менялся).
- Windows/PG18 — удалённая CI-матрица (`auth21.yml`), локально не запускались.
- Полный Jest/production-билды не запускались: UI/фронтенд-файлы задачей не менялись (web-образ прежний).
- Деньги/платежи/возвраты как HTTP и UI — AUTH-22/23; wallet UI/DTO — AUTH-24; AUTH-CERT не объявляется.
- До провижининга кошелька оператором поведение платформы идентично AUTH-20 (аддитивный выключатель).
