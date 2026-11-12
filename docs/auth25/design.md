# AUTH-25 — Payment reconciliation/restore и launch runbook (design)

Дата: 12.11.2026. База: `main@f6dbec9` (AUTH-24), сервер и образы VM на ней.
Статус: проект реализации; не сертификация. Commit/push/VM-операции из сессии не выполняются (AGENTS.md).

## 1. Нормативные источники и постановка

- `spec_auth_architecture.md` §9 строка AUTH-25: зависимости AUTH-23/AUTH-24/AUTH-20; точки изменения
  «billing/reconciliation, ops, integration tests»; критерий приёмки — **«Crash/backup/provider replay
  не создают дубликаты; terms/catalog подтверждены до real checkout»**.
- `spec_auth_architecture.md` §12.2: `billing/reconciliation` — новый логический модуль, использующий
  существующие provider adapter/inbox/outbox; credit/order/audit коммитятся одной транзакцией; unique
  credit-per-order плюс provider_event_id предотвращают два начисления.
- `spec_auth_architecture.md` §12.4: рестарт, backup и reconcile не воскрешают consumed credits,
  refunded lots или старые reservations; при uncertain financial state — hold, а не подстановка
  Memory wallet.
- `spec_auth_architecture.md` §12.5/§13.9: релиз R4 открывает реальный checkout только после того,
  как provider/условия/каталог и reconciliation готовы; «До продаж: price/terms/catalog, provider
  amount/currency semantics, refund procedure, retention/reconciliation и пользовательское раскрытие
  условий готовы».
- `spec_billing_accounts.md` §13.9: «Пока это не выполнено, кнопка покупки выключена; тестовые credits
  не маркируются реальными оплатами. Необратимый запуск реальных платежей — отдельная поставка».
- E6 (§13.10): рестарт/backup/reconcile не дублируют cycle credit, topup credit, settlement/refund.
- Зависимость AUTH-20: механизм marks вне pgdata + reconcile re-apply для терминальных security-состояний
  (`apps/api/authentication/ops_service.py`, `scripts/auth20/reconcile.py`) — образец для
  финансового watermark; принцип «обязательный audit в той же транзакции».

Прочитаны: AGENTS.md, обе спецификации, записи AUTH-20…24 в worklog12, реализованный код
(`billing/wallet.py`, `billing/topups.py`, `billing/refunds.py`, `billing/wallet_views.py`,
`billing/provider.py`, миграции 0033/0034/0035, `authentication/ops_service.py`,
`scripts/auth20..24`, native-фикстуры AUTH-21/22/23/24, инвентарь AUTH-00).

## 2. Границы задачи

**AUTH-25 — reconciliation/restore-безопасность и launch runbook.** Только:

- детектирующий read-only сервис `billing/reconciliation` (отчёт консистентности, watermark,
  карантинная блокировка flagged-кошельков, pre-launch проверка);
- ops CLI (без единого нового HTTP-маршрута — check_routes обязан показать паритет 281/658);
- native integration-оракулы и юнит-контракты;
- runbook запуска (документ), фиксирующий, что терминальный переход к реальным платежам —
  **отдельная поставка** (§13.9): launch-check подтверждает готовность terms/catalog, но не
  включает ничего.

Никаких: новых мутаций баланса вне существующих trusted-команд, авто-«переналожения» денег при
restore (только детектирование + подсказка оператору), DDL (схема 0033–0035 достаточна), изменений
UI/оболочек, изменений роутов/инвентаря/реестра операций, provider-вызовов в production-конфигурации.

## 3. Решения

**D1 — один read-mostly сервис `apps/api/billing/reconciliation.py`.**
`FinancialReconciliationService(store, clock=None)` поверх существующего `PostgresAccessStore`
(дисциплина транзакций сохраняется; отчёты — `transaction(readonly=True)`). Репортируемые коды
находок (bounded 500, каждая — {code, severity, subject, detail≤512}):

| Код | Серьёзность | Инвариант |
|---|---|---|
| `credit_order_mismatch` | blocking | credited-заказ имеет ровно один purchased-lot с origin_order=order_id; lot с origin_order без credited-заказа (orphan credit); credited-заказ без лота |
| `payment_id_collision` | blocking | один payment_id на двух заказах (defense-in-depth: 0034 UNIQUE уже не допускает; проверка ловит деградацию схемы) |
| `refund_state_mismatch` | blocking | refund-заказ vs buckets лота: state='refunded' при lot.refunded=0 или остатке refund_pending; state='pending'/'review_required' без refund_pending; refund на не-credited заказе |
| `dispute_state_mismatch` | blocking | открытый спор при незаблокированном кошельке; won-спор при заблокированном только из-за этого спора (вычислимо по auth_disputes/wallet.locked_reason) |
| `lot_projection_drift` | blocking | сумма проводок по buckets ≠ колонкам лота (restore/DBA-артефакт поверх «projection only by postings») |
| `lot_balance_violation` | blocking | issued ≠ available+reserved+spent+expired+refund_pending+refunded (CHECK 0033 обычно предотвращает) |
| `paid_review_open` | info | захваченные деньги ждут операторского credit_paid (это штатный путь D5 AUTH-22, не дефект) |
| `inbox_unowned_event` | info | события inbox для payment_id, не привязанных к заказу (спуф-остаток, не влияет на деньги) |
| `audit_outbox_pending` | info | недоставленные обязательные audit-intents (AUTH-20 tie-in) |
| `restore_regression` | blocking | watermark-факт исчез/регрессировал после restore (только режим reconcile-watermark) |

`report()` никогда не мутирует. ok = нет blocking-находок.

**D2 — финансовый watermark вне pgdata (`cisstat-auth25-watermark/1`).**
Образец — AUTH-20 marks. `export_watermark(path)`: атомарная запись (tmp+rename, 0600), bounded
≤100000 записей терминальных финансовых фактов — credited-заказы (order_id/payment_id/credited_at),
терминальные возвраты (refund_id/state/decided_at), разрешённые споры (dispute_id/state/resolved_at).
Никаких секретов и amounts — только идентификаторы/состояния (id не секрет, §13.8).
`reconcile_watermark(document, reason)`: сравнение с текущей БД; **деньги не перенакладываются
никогда** — каждая потеря/регресс терминального факта становится `restore_regression` с
bounded row-image и подсказкой существующей trusted-команды (manage_topups reconcile/credit-paid,
manage_refunds refund-reconcile, manage_wallet adjust/lock/unlock, manage_refunds dispute-resolve).
Сам прогон пишет один audit-intent в auth_audit_outbox в той же транзакции (fail-closed, образец
AUTH-20). Повторный прогон по тому же watermark безопасен: отчёт идемпотентен, дубликатов не создаёт.

**D3 — карантин неопределённого финансового состояния: `lock_flagged(reason)`.**
§12.4 «при uncertain financial state — hold, а не подстановка Memory wallet» и §8 «при сомнении
… закрываются до reconciliation». Оператор одной командой блокирует кошельки (status='locked',
locked_reason='auth25-reconciliation: <reason>'≤256) только тех аккаунтов, у которых есть blocking-находки;
используется существующий `WalletService.set_status` с CAS по version. Audit — той же транзакцией.
Разблокировка — существующий audited `manage_wallet.py unlock` после ручного разбора (не автоматическая).

**D4 — pre-launch gate «terms/catalog подтверждены до real checkout»: `launch_check()`.**
Проверки (каждая — {name, status: ok|blocked|warn, detail}):
1. `schema_ready` — to_regclass 0033/0034/0035 (без применения DDL);
2. `catalog_valid` — каждый enabled-пакет проходит `validate_package` (integer money/units, RUB,
   versioned price/terms); пустой каталог = blocked с подсказкой «каталог выключен — checkout
   недоступен» (это штатное состояние до провижининга, не дефект);
3. `refund_window` — `CISSTAT_TOPUP_REFUND_DAYS` парсится и в границах 0…90 (default 14);
4. `provider_mode` — только факт конфигурации: `CISSTAT_YOOKASSA_ENABLED` отсутствует → `not_configured`
   (ok: checkout выключен, 503 billing_not_configured на admission); `test` → `sandbox`; любое другое
   значение или попытка live-credentials → `blocked` («live launch is separately gated» — код
   провайдера конструирует только test-shop, `sandbox=True`);
5. `reconciliation_clean` — `report().ok`;
6. `audit_delivery` — счётчик pending audit-intents (warn при >0, не блокирует: доставка — AUTH-20 runbook).

Вердикт `ok`/`blocked` + reasons[]; команда **ничего не включает** — терминальное открытие
реального checkout остаётся отдельной поставкой с правкой провайдера (§13.9). Launch-check —
условие готовности, а не выключатель.

**D5 — ops CLI `scripts/auth25/reconcile.py` (CLI-first, ни одного HTTP-маршрута).**
Взаимоисключающие режимы: `--report`, `--export-watermark PATH`, `--reconcile-watermark --watermark
PATH --reason R`, `--lock-flagged --reason R`, `--launch-check [--allow-empty-catalog]`.
JSON в stdout, exit 0/1 (blocked/находки)/2 (нет DSN — как verify-раннеры AUTH-22..24).
DSN — `CISSTAT_AUTH_DATABASE_URL`/`DATABASE_URL`. `verify_postgres.py` — обязательный native-гейт
(disposable DSN, skips запрещены), `requirements.txt` от auth22/23.

**D6 — TDD-оракулы.**
Юнит (`tests/unit/test_auth25_reconciliation.py`): bounding отчёта, валидация watermark-документа
(формат/лимит/виды записей/обязательные поля), сборка вердикта launch-check (чистые функции),
парсинг refund-window, маппинг restore-regression → подсказки команд, reason-валидация.
Native (`tests/integration/test_auth25_reconciliation.py`, фикстура наследует TopupSQLTests AUTH-22,
как AUTH-24 наследует её же): честная сага → отчёт чист; hold возврата/спора — легитимен, не находка;
orphan credit и credited-без-лота ловятся; refund-регресс через adjust-проводку (симуляция
restore-артефакта) ловится; спор при разлоченном кошельке ловится; DB-уникальности payment_id
доказываются (INSERT дубликата → unique_violation: provider replay не создаёт дубликат);
рестарт саги не удваивает credit; watermark export/reconcile + регрессия ловится и НЕ чинится
автоматически; lock_flagged бьёт только виновных; launch_check ok/blocked по каталогу и находкам.

**D7 — гейты.** `local_gates.py`: пары auth25 (unittest) + auth25-postgres (opt-in) добавляются
одним изменением с `--with-auth25-postgres` и excluded.add (урок AUTH-22-HOTFIX-01); человекочитаемые
списки имён строятся программно (урок AUTH-23). `local_gates.md` — раздел AUTH-25. CI —
`.github/workflows/auth25.yml` (контракты ubuntu/windows + postgres PG16/18).

**D8 — риски и исключения.**
- Ложные срабатывания на легитимных состояниях: hold возврата/спора, paid_review, пустой каталог,
  недоставленный audit — отнесены к info/легитимным; в отчёте разделены severity.
- Восстановление из backup «отматывает» и заказ, и лот вместе (одна транзакция) — внутренне
  консистентное состояние; регрессия обнаруживается только против watermark вне pgdata. Отчёт
  прямо говорит: watermark отсутствует → сравнение невозможно (warning, не blocking).
- N+1/тяжёлые запросы: все проверки — bounded SQL с LIMIT; отчёт ≤500 находок; watermark ≤100000.
- Не заявляются: реальные сети/магазин, Docker-сборка (VM), автоматическое восстановление денег,
  включение live-платежей.

## 4. Точки изменения (полный список файлов)

Новые: `apps/api/billing/reconciliation.py`; `tests/unit/test_auth25_reconciliation.py`;
`tests/integration/test_auth25_reconciliation.py`; `scripts/auth25/{reconcile.py,verify_postgres.py,
requirements.txt,package_delivery.py,files.txt}`; `.github/workflows/auth25.yml`;
`docs/auth25/{design.md,deploy.md,verification.md,runbook.md}`.
Обновляемые: `scripts/local_gates.py`, `scripts/local_gates.md`, `worklog/worklog12.md`.
Не затрагиваются: `apps/api/routers/**`, `access_registry.v1.json`, `docs/auth00/inventory.*`,
`docs/auth01/openapi.json`, UI/оболочки, миграции.
