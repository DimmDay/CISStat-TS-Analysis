# AUTH-21 — Source-aware Wallet/CreditLot и миграция: проектирование

База: `a0a2af6c6490f81620b16d0da8453d044657eb67` (AUTH-20). Задача из `spec_auth_architecture.md` (строка AUTH-21: области `billing/wallet, ledger, migrations`; критерий: «Included отделён от purchased; integer rounding, expiry/reserve и cycle rollover не теряют средства», зависимости AUTH-12, AUTH-18). Нормативные правила — `spec_billing_accounts.md` §13 (включая приёмочные примеры E1–E6); GP-15/RP-15 (CU-WALLET-1). Правила AGENTS.md соблюдены; commit/push не выполняются.

## Объём и границы

**В объёме:** durable source-aware кошелёк Account (lots: included/purchased/promotional), append-only balanced postings как источник истины, проекция счётчиков лот-строк через триггеры (паритет AUTH-12), pinned-аллокации резерваций, FEFO-расход, settle/release по закреплённым lots, expiry-sweep, блокировка кошелька, trusted-операторские CLI (provisioning/issue/sweep/lock/status), миграция `0033_auth21_wallet.sql` с защитными триггерами, интеграция хуками в AUTH-12 coordinator (reserve/extend/settle/release) в той же транзакции, новый обязательный аудит `auth_wallet_changed` (каталог 42→43), гейты auth21/auth21-postgres, CI-матрица, Dockerfile import-guard.

**Вне объёма (честные границы):** деньги и покупки — AUTH-22 (topup checkout, provider inbox кредитование); self-service возврат как HTTP/UI — AUTH-22/23; dispute/chargeback/exposure — AUTH-23 (схема лота уже несёт refund_pending/refunded, переходы реализованы как trusted-команды и протестированы нативно); wallet UI/DTO — AUTH-24 (эндпоинт `show()` и поле `spendable_credit_issued` не меняются); реального прайса/каталога пакетов поставка не создаёт; критерий E3 «callback browser ничего не начисляет» относится к AUTH-22 (browser-путь ещё не существует).

## Решения

**D1. Один кошелёк на Account; строка `auth_wallets` — аддитивный выключатель исполнения.** Кошелёк существует только там, где создан trusted-командой оператора (CLI, reason+audit). Account без строки кошелька ведёт себя ровно как сегодня (AUTH-12 бюджеты) — исторические Account/резервации/проводки не затрагиваются («Начальный исторический usage/финансовые credits не выдумываются» — паритет AUTH-12). Создание отказывает для план `demo`/`internal` (§13.2/§13.3: demo — sponsor-бюджеты, INTERNAL не выпускает wallet units). Провижининг не происходит автоматически ни из `provision_cycle` (AUTH-18), ни из загрузок: контракт AUTH-18 «spendable_credit_issued: False» сохраняется до явной команды.

**D2. Проводки — источник истины; счётчики лота — проекция.** Паритет AUTH-12: append-only `auth_wallet_postings` с балансом (сумма дельт = 0), AFTER INSERT-триггер двигает счётчики лота, прямой UPDATE счётчиков вне триггер-глубины запрещён (`pg_trigger_depth()<2`), история immutable. `issued` — неизменяемая привязка лота (исходное количество), начальное состояние строки сбалансировано (`available=issued`, остальные 0); «issue-проводки» нет — лот-строка сама является записью начисления, последующие движения — проводки. Инвариант строки: `available+reserved+spent+expired+refund_pending+refunded = issued`, переполнение BIGINT отсечено numeric-CHECK.

**D3. FEFO-порядок (§13.5):** ключ сортировки `(expires_at IS NULL ASC, expires_at ASC NULLS LAST, rank(source), lot_id)`, rank: included=0, promotional=1, purchased=2. К отгрузке доступны только лоты с `available>0` и `expires_at > now` (ленивое исключение — страховка на случай без sweep). При равной дате — included→promotional→purchased, затем стабильный `lot_id`. Порядок закреплён чистой функцией и индексом.

**D4. Двойной гейт расхода.** Резервация с `cost.micro_cu>0` проходит и AUTH-12 бюджетный потолок (policy limit), и кредитное покрытие кошелька. Недостаток кредита — `402 cu_insufficient` с безопасной оценкой `required/available` (§13.6); заблокированный кошелёк — `403 wallet_locked`; техническая недоступность схемы — честная ошибка транзакции, а не «ложный нулевой баланс». `cost.micro_cu=0` (unpriced `unpriced-auth13/1`, дефолт AUTH-14) кошелёк не трогает вовсе; api/analysis/concurrency метрики не кошелёчные.

**D5. Pinned-аллокации.** `auth_reservation_lot_allocations(reservation_id, lot_id, units)` — «ReservationAllocation хранит ссылки на source lots» (§13.8). Reserve закрепляет весь `micro_cu`; extend — дельту, а для резерваций, начатых до провижининга кошелька (без аллокаций), — весь текущий `held_cu` (иначе settle не покрыл бы actual; fail-closed при нехватке). Гвард аллокаций: привязка неизменяема, `units` только растёт (extend), DELETE запрещён. Ретроактивного закрепления исторических резерваций нет — только явный extend.

**D6. Settle/release по закреплённым lots.** Settle распределяет `actual` по аллокациям в FEFO-порядке (умирающий included расходуется раньше purchased — §13.5/E2), хвост аллокации освобождается по своему лоту: если лот истёк — `reserved→expired` (никогда не оживает), иначе `reserved→available`. «Обратный порядок освобождения хвоста» §13.5 при pinned-аллокациях вырождается в выбор без альтернатив (каждый хвост привязан к своему лоту) — существенный инвариант «средства не теряются и источник не меняется», он проверяется тестами. Settle в истёкший посреди исполнения лот списывает spent честно (работа сделана под валидным admission; «на следующем цикле такой резерв не списывается второй раз»).

**D7. Только integer micro-CU.** Все суммы BIGINT; сплиты аллокации суммируются ровно в запрошенную величину (без округлений и потерь — критерий «integer rounding … не теряют средства»); переполнение отсечено на уровне SQL (numeric-сравнения с 2^63-1) и сервисных границ.

**D8. Никаких денег в AUTH-21.** purchased/promotional лоты выпускаются только trusted-командой с явным основанием (`origin_order`/`origin_ref`, reason, обязательный аудит). Идемпотентность начисления — частичные уникальные индексы: `(account_id, origin_order) WHERE origin_order IS NOT NULL` (unique credit-per-order, защита E3/E6 от двойного кредита) и `(account_id, origin_cycle, origin_ref) WHERE origin_cycle IS NOT NULL` (одно основание на цикл: `ref='base'` — базовое начисление, `ref='proration:…'` — прорейтированная дельта будущего AUTH-18-расширения). Included-лот обязан иметь `expires_at` (= `ends_at` цикла, берётся из строки цикла, не от клиента) и согласованную величину: сервис сверяет с `cumulative_allocation` цикла (формула AUTH-18) и отказывает при расхождении; purchased в v1 без срока сгорания (CHECK `source<>'purchased' OR expires_at IS NULL`).

**D9. Аудит.** Новый каталог-экшен `auth_wallet_changed`, обязательный (mandatory, fail-closed), пишется в `auth_audit_outbox` в одной транзакции с мутацией (create/issue/sweep/lock/adjust — паритет `auth_budget_changed` AUTH-12). Движения резерваций (reserve/extend/settle/release) покрываются существующим обязательным `auth_reservation_changed` той же транзакции — отдельная запись не дублирует.

**D10. Каталог аудита 42→43** — честное versioned-обновление пинов (`test_auth20_ops`, комментарий в `test_doclog8_monitoring`) с обоснованием AUTH-21, без правки оракулов под реализацию.

**D11. Summary — проекция из lots.** Разбивка по источникам (available/reserved/…), ближайшее сгорание, статус; считается из лот-строк (сами они — проекция проводок). Поле `Account.compute_unit_pool_balance` в коде отсутствует — мигрировать нечего; «wallet summary projection» реализуется сервисом.

**D12. wallet.status `active|locked`.** Locked закрывает новые CU-резервации (`403 wallet_locked`), существующие резервации не перепроверяются (паритет lockdown-семантики AUTH-20); снятие — явная audited-команда с CAS по версии. Chargeback-автоматика — AUTH-23; механизм готов схемой.

**D13. HTTP-поверхность не меняется.** Ни одного нового/удалённого маршрута; `routers/billing.py` и DTO `show()` не тронуты (AUTH-24). Изменения исполнения — только внутри существующих handlers AUTH-12 (coordinator) → гейт check_routes ожидает «added/missing=[]», inventory меняется отпечатками исходников, не записями.

**D14. Порядок блокировок (anti-deadlock).** Все пути кошелька: `auth_wallets (FOR UPDATE)` → лоты строго `ORDER BY lot_id FOR UPDATE`; settle/release сначала читают аллокации, затем лоты по lot_id; sweep — `SKIP LOCKED` + `ORDER BY lot_id` с ограничением порции. Совпадает с направлением AUTH-18 `finish` (identity→account→…). Гонки «последние 10 CU» и «refund vs reserve» закрываются блокировкой строки лота (E3/E4).

**D15. Миграция `0033_auth21_wallet.sql` — аддитивная.** Цепочка через `auth20_migrations.apply_migration` (гарантирует 0030/0031/0032 до 0033), checksum-регистрация, повтор apply=false, прежние SQL/checksums не меняются. `check_schema`: колонки 4 таблиц + 5 включённых триггеров (`auth21_wallet_guard`, `auth21_lot_guard`, `auth21_posting_guard`, `auth21_posting_projection`, `auth21_lot_allocation_guard`). Хук координатора защищён `to_regclass('auth_wallets')` (паритет AUTH-12 `_locked`): порядок развёртывания «код → миграция» не ломает существующие маршруты в окне обновления.

**D16. События проводок:** `reserve|settle|release|expire|refund_hold|refund_confirmed|refund_failed|adjust` с по-событийными паттернами дельт (fail-closed: у каждой ровно одна пара «источник→приёмник»); `adjust` — операторская корректировка с произвольным сбалансированным перераспределением и обязательным аудитом (не переписывает историю, отрицательный available невозможен по CHECK). Refund-переходы в v1 доступны как trusted-команды (используются AUTH-22/23; целостность правила «целый неиспользованный purchased lot» проверена нативно).

**D17. Expiry-sweep** — bounded (LIMIT, SKIP LOCKED), идемпотентная trusted-команда: только `available→expired` у истёкших lots; зарезервированные (pinned) не трогаются. Sweep — гигиена отчётности, корректность FEFO не зависит от него (D3).

**D18. Cycle rollover:** новый период = новое основание начисления; остаток старого included уходит в `expired` по sweep на `ends_at`; purchased не обнуляется и не умножается; spent не переносится (§13.6, E1: 650 = 500 новых included + 150 purchased). Продление/создание нового цикла — контракт AUTH-18 (сейчас `UNIQUE(account_id)` на цикле), AUTH-21 только честно проводит начисление/сгорание.

## Риски и снятие

| Риск | Снятие |
|---|---|
| R1: хуки в coordinator ломают семантику AUTH-12 | Хуки no-op без кошелька (`to_regclass`+`wallet row`); полный нативный регресс `test_auth12_ledger` обязан остаться зелёным без правок |
| R2: line-shift в coordinator.py рушит AUTH-00 evidence | Точные якоря известны (reserve@260, ledger@236 до вставок, settle@578/585); после правок — перегенерация `inventory.py --write` и адресная правка evidence в `policy_review.json` (паритет AUTH-13-HOTFIX-1) |
| R3: разрыв цепочки миграций | Аддитивная 0033; цепочка идемпотентна (паттерн AUTH-20); checksums 0019–0032 не меняются |
| R4: дедлоки на общих лотах | D14: единый порядок (wallet→lots по lot_id) во всех путях; нативные конкурентные тесты |
| R5: пин каталога 42 | D10: честное обновление двух тестов с комментариями |
| R6: Docker-сборка без новых файлов | COPY только существующих CLI + import-guard RUN (fail-closed, философия DEPLOY-1) |
| R7: двойное начисление | Частичные уникальные индексы (D8) + транзакционность кредит+аудит; отказ вставки аудита откатывает кредит (нативный fault-тест) |

## Проверки (TDD)

RED: отсутствующий модуль `apps/api/billing/wallet.py` (suite-level) + контрактные unit-тесты. GREEN: unit-гейт; native PostgreSQL 16.2 (pgserver, disposable schema): миграция/checksum/триггеры, E1/E2/E4/E5/E6, FEFO-порядок, гонки, refund-переходы, уникальности, audit-fault, регресс AUTH-12/18. Гейт check_routes: added/missing=[]; регенерация inventory; локальные гейты auth21 (новый default) и auth21-postgres (opt-in) в `scripts/local_gates.py/.md`; CI `.github/workflows/auth21.yml` (Ubuntu/Windows contracts + PG16/18 native, Windows/PG18 в сессии не запускаются).
