# AUTH-24 — Wallet permissions/UI и lifecycle (design)

Дата: 12.11.2026. База: `main@32e0f50` (AUTH-23-DEPLOYFIX-01), сервер и образы VM на ней.
Статус: проект реализации; не сертификация. Commit/push/VM-операции из сессии не выполняются (AGENTS.md).

## 1. Нормативные источники и постановка

- `spec_auth_architecture.md` §9 строка AUTH-24: зависимости AUTH-22/AUTH-23/AUTH-08; точки изменения
  «accounts, billing DTO, обе оболочки»; критерий приёмки — **«OWNER покупает, MEMBER только
  разрешённо расходует; expiry/seat/owner change сохраняют purchased»**.
- `spec_auth_architecture.md` §12.2/§12.3: summary в me/Account UI — ограниченная проекция; цены и
  денежные платёжные документы доступны OWNER (или уполномоченной support policy), не всем MEMBER;
  «Аккаунт → Баланс CU»: available по источникам, reserved, дата сгорания included/promotional,
  purchased без срока сгорания в v1, история операций и pending/locked.
- `spec_auth_architecture.md` §12.5: объём проверки — seat churn, Account switch, финансовая
  приватность MEMBER, purchased на смене цикла.
- `spec_billing_accounts.md` §13.2/13.3/13.6/13.8: lots показываются отдельно по источникам;
  `can_purchase_cu` — effective permission только OWNER оплачиваемого активного Account (v1 без
  demo/internal); `can_spend_cu` — разрешённый участник; suspended/expired подписка **не сжигает
  purchased**, но блокирует новые платные вычисления — UI показывает сохранённый баланс и причину;
  смена OWNER не перемещает кошелёк; MEMBER при нехватке получает «Обратитесь к владельцу аккаунта»;
  предлагаемые API: `GET wallet (breakdown/reserved/status)`, `GET ledger (OWNER: полный финансовый
  журнал; MEMBER: только разрешённые usage сведения)`.
- Отложенные в worklog12 обязательства: AUTH-21 — «show()/DTO не тронуты (UI — AUTH-24)»;
  AUTH-22 — «wallet/ledger READ-эндпоинты и приватность MEMBER — AUTH-24»; AUTH-23 — «refund-UI и
  wallet/ledger READ-эндпоинты — AUTH-24».

Прочитаны: AGENTS.md, обе спецификации, записи AUTH-12…23 в worklog11/worklog12, реализованный код
(`billing/wallet.py`, `billing/topups.py`, `billing/refunds.py`, `billing/coordinator.py`,
`routers/billing.py`, `accounts/team.py`, `accounts/entitlements.py`, `access_registry.py`,
UI `AccountScreen`/`TopupPanel`/`lib/billing.ts`, инвентарь AUTH-00/01).

## 2. Границы задачи

**AUTH-24 — только READ-поверхность, DTO, UI и lifecycle-инварианты.** Никаких новых мутаций
баланса, никакой DDL (схема 0033 достаточна), никаких provider-вызовов. Запись (credit/spend/
refund/dispute) остаётся у AUTH-21/22/23. До провижининга кошелька поведение платформы идентично
AUTH-23 байт-в-байт (паритет AUTH-21 D1).

## 3. Решения

**D1 — два READ-эндпоинта под существующим префиксом `/v1/billing`:**
- `GET /v1/billing/{account_id}/wallet` — для активного member (OWNER или MEMBER) текущего
  персонального входа. OWNER получает полную проекцию: buckets по трём источникам
  (issued/available/reserved/spent/expired/refund_pending/refunded), суммарный reserved, next_expiry
  (ближайшее сгорание среди лотов с available>0), status, locked_reason, флаги `can_purchase_cu`/
  `can_spend_cu`, `account_active`/`spending_blocked_reason`. MEMBER получает ограниченную
  usage-проекцию: суммарные available/reserved, next_expiry, status, `can_spend_cu`/
  `can_purchase_cu`, `account_active`/`spending_blocked_reason` — БЕЗ разбивки по источникам, БЕЗ
  issued/spent/expired/refund-истории, БЕЗ locked_reason, БЕЗ каких-либо денег (§13.8 «MEMBER:
  только разрешённые usage сведения»; §12.5 «финансовая приватность MEMBER»).
- `GET /v1/billing/{account_id}/wallet/ledger` — **только OWNER**: полный финансовый журнал —
  bounded-проекции проводок, лотов с происхождением (origin_order/cycle/ref), заказов, возвратов и
  споров с деньгами (amount_minor/currency/price/terms). MEMBER → 403 `owner_required`
  («Действие доступно владельцу аккаунта» — существующий safe-код, §13.6).

**D2 — admission читается существующими гейтами, новых кодов нет.** Чужой/не-member → 404
`account_not_found` (uniform с team.py); demo-grant аккаунт → 403 `team_unavailable`; аккаунт без
кошелька → 403 `wallet_required` (кошелёк существует только там, где провижинирован оператором);
статус аккаунта != active → 403 `account_expired`. Ни одного нового элемента `_MESSAGES`.

**D3 — сохранённый баланс при блокировках (§13.3) и честная ревизия по коду AUTH-08.** Слой сессий
AUTH-08 (`SessionService._load`) отказывает **любую** верификацию сессии на аккаунте с истёкшим
`plan_expires_at` (403 `account_expired`) — READ-эндпоинт через живую сессию на expired-плане
недостижим, и выдумывать обходной путь (второй, ослабленный транспорт) AUTH-24 не имеет права.
Норматив «suspended/expired не сжигает purchased, UI показывает сохранённый баланс и причину»
реализуется там, где это достижимо честно: (а) структурная гарантия схемы — expiry плана не касается
таблиц кошелька (native-оракул: до/во время/после истечения лоты байт-в-байт неизменны, восстановление
entitlement возвращает тот же баланс к spendable); (б) достижимая причина блокировки — `wallet_locked`
(активный аккаунт, заблокированный кошелёк): READ отдаёт сохранённый баланс + `status="locked"` +
`spending_blocked_reason="wallet_locked"` + locked_reason (OWNER); (в) проекция `wallet_view`
содержит `account_active`/`spending_blocked_reason="account_expired"` как контракт функции
(юнит-оракул + defense-in-depth на случай будущего read-only допуска expired-планов в AUTH-08),
без заявления, что production-сессия на expired-плане возможна сегодня.

**D4 — `can_purchase_cu`/`can_spend_cu` вычисляются сервером** (§13.3, §12.1 — «effective
permissions, вычисляемые сервером»):
- `can_purchase_cu` = текущий OWNER + paid-MULTI + активный аккаунт + активный кошелёк (паритет
  допуска AUTH-22 `_topup_account` без gateway-зависимости); false для MEMBER, MONO, demo/internal,
  locked/no-wallet/expired.
- `can_spend_cu` = активный member + активный аккаунт + активный кошелёк; false при
  wallet_locked/account_expired/отсутствии кошелька.
Флаги — справочные поля READ-ответа для UI; admission к расходу по-прежнему решает coordinator
AUTH-12 в транзакции admission. Флаг никогда не является признаком платёжеспособности или
допуска к операции.

**D5 — ledger bounded и без служебных полей.** Лимиты: 200 проводок (новейшие сначала), 100 лотов,
20 orders + refunds + disputes. Переиспользуются безопасные проекции `TopupService.view`,
`refund_view`, `dispute_view` (AUTH-22/23) — ни lease/fence/owner_id, ни секретов; проводки
отдаются целочисленными дельтами по шести bucket'ам без интерпретаций.

**D6 — UI в обеих оболочках через общий слой packages/ui:**
- NEW `WalletPanel` («Аккаунт → Баланс CU»): для платных аккаунтов (plan != internal/demo) обеих
  оболочек. OWNER: разбивка available по источникам, reserved, дата сгорания, подпись «purchased не
  сгорает в v1», баннер locked с причиной, кнопка «Показать журнал» (OWNER-only ledger).
  MEMBER: суммарный available/reserved, next_expiry и постоянная строка «Пополнение и возвраты —
  через владельца аккаунта» (§13.6); без денег/источников/журнала. 403 `wallet_required` — панель не
  рендерится вовсе (кошелёк не провижинирован; ничего не выдумываем).
- `TopupPanel` (покупка) переводится на OWNER-only рендер по `can_manage` (критерий «OWNER покупает,
  MEMBER только разрешённо расходует»): сервер и раньше требовал OWNER (403 `owner_required`), но
  MEMBER видел панель покупки — это расходится с §13.3; исправляется на клиенте, сервер остаётся
  authority.
- `TopupPanel` дополняется self-service возвратом (AUTH-23): на credited-заказах OWNER видит
  «Запросить возврат» → `POST /topups/{order_id}/refunds` {expected_version, reason,
  idempotency_key}; состояние возврата рендерится из ответа; повторный клик возвращает тот же
  refund (идемпотентность сервера). Кнопки возврата у MEMBER нет.
- `lib/billing.ts` дополняется RU-сообщениями для `refund_not_eligible`/`refund_window`/
  `refund_not_found` (после AUTH-23 UI не существовало) и wallet-веткой.

**D7 — lifecycle-инварианты пиннуются native-тестами** (критерий приёмки). Схема уже гарантирует
их структурно (кошелёк привязан к account_id, membership/seat/owner-операции таблиц кошелька не
касаются); AUTH-24 фиксирует это оракулами: seat churn (invite→accept→remove), OWNER transfer,
MONO↔MULTI, cycle rollover (новый included, purchased цел, spent не восстанавливается — E1),
expiry sweep (included→expired, purchased не тронут), повторный вход/account switch (тот же
wallet_id, второй кошелёк не создаётся), READ поверх expired-плана (D3), refund_pending виден в
проекции OWNER. Parity-оракул: sources OWNER-проекции == `WalletService.summary()` того же
аккаунта.

**D8 — роуты затронуты: +2 GET.** Реестр AUTH-01: операция `billing.wallet`
(service/platform, authority external) + 2 binding'а. Порядок регенерации «производные → inventory»:
access_registry.v1.json → policy_review.json (+политика billing.wallet, +2 entries, +reviewed_sources)
→ `inventory.py --write` → `auth01/generate.py --write` (OpenAPI/TS) → `generate_proxy_routes.py
--write` → `check_routes.py` (actual == inventory). Гейт AUTH-00 обязателен (AGENTS.md).

**D9 — деплой.** Никаких миграций и новых обязательных env; API-образ пересобирается (python-код
попадает через существующий `COPY apps/api/`), web-образ пересобирается (UI в бэкенде Next build).
Прошлые команды `migrate --apply` не требуются: 0033–0035 уже применены.

**D10 — честные границы.** Реальный магазин/сеть не вызывались; native — disposable PG16.2;
PG18/Windows — удалённая CI-матрица; полный pytest всего проекта и browser E2E не заявляются;
коммерческий запуск (реальный каталог/прайс/live checkout) — AUTH-25; AUTH-CERT не объявляется.
Refund-решения спора/обязательные возвраты остаются trusted-контуром (§13.7), HTTP-поверхности у
них нет и в AUTH-24 не появляется.

## 4. Точки изменения и риски

| Точка | Изменение | Риск | Митigation |
|---|---|---|---|
| `apps/api/billing/wallet_views.py` | NEW: WalletReadService + чистые view-функции | Утечка финансовых полей MEMBER | Юнит-оракулы «в member-проекции нет ключей источников/денег»; ledger OWNER-only тест |
| `apps/api/routers/billing.py` | +2 GET | Дрейф роутов | Гейт AUTH-00 + actual-ASGI; register до `/webhooks` не требуется (пути различны) |
| `apps/api/access_registry.v1.json` | +операция/+2 binding | Пустые допуски | `AccessRegistry`-валидатор; AUTH-01 generate --check |
| `docs/auth00/policy_review.json` | +политика billing.wallet, +2 entries | Unclassified entries | inventory build падает при расхождении — фиксируем до --write |
| UI `WalletPanel`/`TopupPanel`/`AccountScreen`/`billing.ts` | NEW/правки | MEMBER видит деньги/покупку | jest-оракулы: у MEMBER нет «Пополнить», нет кнопки возврата, нет цен; can_manage-гейт |
| `scripts/local_gates.py/.md` | гейты auth24 (+auth24-postgres opt-in) | Урок AUTH-22-HOTFIX-01 | флаг `--with-auth24-postgres` и `excluded.add` в одном изменении |
| tests unit/integration/Jest | NEW | — | TDD RED до реализации |

Проекция читает `auth_wallet_lots`/`auth_wallet_postings` без `FOR UPDATE` (read-only
транзакция `store.transaction(readonly=True)`) — не конкурирует с координатором за блокировки.

## 5. TDD-план

1. RED: `tests/unit/test_auth24_wallet_views.py` — контракт проекций (member-минимум, owner-полный
   набор, флаги, bounded ledger, отсутствие денег в wallet-проекции, parity bucket-математики).
2. RED: `tests/integration/test_auth24_wallet.py` — native PG 16.2: admission, privacy, ledger,
   lifecycle D7. Без DSN раннер возвращает 2 (не PASS).
3. RED: `packages/ui/components/auth24-wallet.test.tsx` — MEMBER/OWNER/locked/wallet_required.
4. GREEN реализации; гейты auth24, auth24-postgres, auth00, auth01, jest, typecheck, builds.
