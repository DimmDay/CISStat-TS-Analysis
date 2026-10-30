# AUTH-00 — процесс, полнота и применение

**Статус:** реализован source inventory/review gate и threat model AUTH-00 на
`962ccda96c15aed5d1a6661364d8c50d8a301cbe` (30.10.2026, Москва).
AuthN endpoints, MFA, Accounts, DemoGrants и CU ledger эта задача не создаёт.
Основание: AUTH-00 в `spec_auth_architecture.md` §9 и границы §1/3/5/8/10/12;
прочитаны также `spec_auth.md`, `docs/ROLES_AND_PLANS_SPEC.md` и соответствующие
Account/CU-контракты `spec_billing_accounts.md`.

## Приёмка и итоговые артефакты

| Требование AUTH-00 | Реализация / доказательство |
|---|---|
| Каждый вход classified | 531 запись, явные bindings в policy_review.json; нет default policy для нового ID |
| Полные API mounts | 217 прикладных method/path записей, 215 handler identities; factory DB зарегистрирована дважды |
| Direct internal / DB probe | Отдельные public/internal DB test/load, включая probe до создания сессии; observed key gate сохраняется только на public mount |
| Task aliases | Четыре href и существующий causes endpoint; canonical application stages scenario/causal/decision/monitoring отдельно от EDA и DOCLOG |
| File paths и выдача | HTTP preview/content/export/report/restore, DB local paths, uploads/checkpoints/artifact roots и rule templates |
| Workers и legacy app | Реальные thread launches, логические run_once/process/system read, клиентские model steps, legacy authority и widgets/rerun transport |
| Threat model | 20 T01…T20, активы/actors/B1…B8, AS-IS gaps и существующие controls, follow-up AUTH IDs и AC01…30 |
| TDD / проверяемая полнота | unittest на source fixtures и live snapshot, RED→GREEN, source/policy/route drift, новые формы registration не игнорируются |
| Сборка и поставка | Python compile, renderer build/typecheck, протоколы, worklog11 и ZIP; точный состав/байты проверяются |

Состав 531: 217 api + 8 framework metadata methods + 4 renderer HTTP +
27 Next pages + 2 rewrites + 1 static asset + 4 task aliases +
250 legacy widget call sites + 1 legacy authority + 6 worker execution/dispatch
records + 6 storage boundaries + 3 internal execution operations + 2 transports.
Эти величины не складываются в «531 REST endpoint» или «250 бизнес-операций».

## Источники и поля

- [inventory.json](inventory.json) — воспроизводимая детальная карта.
- [inventory.md](inventory.md) — полный человекочитаемый индекс, таблица policies.
- [policy_review.json](policy_review.json) — явные reviewed bindings/semantic annotations;
  `extra_surfaces` помечают внутренние границы, а не добавляют вымышленные HTTP routes.
- [threat_model.md](threat_model.md) — source-based STRIDE-сценарии и будущие негативные oracle.
- [operation_variants.md](operation_variants.md) — parameter/format/model/job selector semantics, mirrors и application stage aliases.
- `scripts/auth00/inventory.py` — stdlib-only discovery/build/check/write, не policy engine.
- `tests/unit/test_auth00_inventory.py` — unittest, также собирается pytest по обычному пути tests/unit.
- `.github/workflows/auth00.yml` — отдельная проверка inventory в Linux/Windows без установки scientific stack.

У каждой записи: kind, method/path, source operation, canonical_operation,
stage_namespace/stage, resource, effects/admission, policy и source:line evidence.
API дополнительно несут constructor/decorator/function Depends и **direct call
mentions**. Последние не являются доказательством исполнения guards: статический
call mention не устанавливает control-flow/return value/transitive authorization.
Observed policy описывает прочитанный существующий контур; target — требование
будущих задач. Разрешения для конечного пользователя этот JSON не выдаёт.

## Discovery и fail-on-drift

1. AST-разбор всех Python-модулей apps/api, без import/application startup/side effects.
2. Constructor prefixes/dependencies, декораторы, literal method/path, nested include_router,
   alias imports, локальные register(router) factories; mounted dependencies объединяются.
3. Отдельные FastAPI metadata defaults (GET/HEAD), Node HTTP conditions renderer,
   Next pages/redirects/rewrite/public assets и task hrefs, Streamlit widget calls,
   существующие Python thread launch sites.
4. Явные reviewed entries для CORS/Streamlit transport и внутренних worker/storage
   границ; source evidence имеет проверенные существование и номера строк.
5. Полное совпадение discovery IDs и review IDs. Новый/удалённый ID, duplicate
   method/path, nonliteral path, unmounted router, unsupported registration или
   новые Next route handlers/middleware требуют расширения collector и review.
   Новые FastAPI/Starlette/Flask roots и Node createServer вне известных модулей
   apps также отвергаются; это поддержанные startup constructs, не поиск любого
   возможного сетевого сервера в произвольном Python-коде.
6. Текстовые source fingerprints нормализуют CRLF→LF, поэтому обычный Windows
   checkout не считается изменением безопасности. BOM допускается при AST parse;
   бинарный public asset не нормализуется. Fingerprints охватывают весь apps/api
   Python, страницы, legacy app и выбранные auth/DB/UI/worker источники.
7. `--check` независимо пересобирает карту и сравнивает её с JSON **и** Markdown.
   Изменение тела guard даже без смены URL/decorator даёт drift.

Сборщик поддерживает формы регистрации, наблюдаемые на целевой базе и
дополнительно покрытые fixtures. Это не универсальная эмуляция Python/Next/ASGI.
Неизвестные метапрограммируемые формы нужно добавить явно, не отключая проверку.
FastAPI metadata и Streamlit-managed transport обозначены отдельно от исходных
application routes; настоящий app import/route serving не подменялся stub-сервером.

## Review границ операций

- API `/v1/models/*`, `/v1/internal/models/*` и `/v1/session/modeling/*` сопоставлены
  по canonical backtest/candidates/diagnostics/tune. Входной model_id/folds/trials
  всё ещё определяет baseline/advanced вариант; финальный versioned registry — AUTH-01.
- `/v1/session/demo` — загрузка подготовленного dataset, а не форумный login.
- `/session/modeling/jobs/*` сейчас относятся только к tuning по Literal selector;
  generic URL не переводит их в baseline. `/v1/models/train` — заглушка, отражающая
  сырой principal_id; риск DTO зафиксирован для AUTH-03, а не исправлен скрыто в AUTH-00.
- `/tasks/causes` соответствует application stage `causal`; EDA Granger остаётся `eda`.
  DOCLOG run monitoring остаётся documentation/service, а не платным task monitoring.
- GET restore помечен как session/file mutation; GET scientific profiles не названы
  безусловно read-only. Output routes требуют повторного object/version decision.
- DB `test` учитывается независимо от load/создания session. SQL read-only guard
  и host whitelist не заменяют AuthN, egress и разрешение на локальный файл.
- Legacy controls перечислены на уровне source-visible UI call sites. Полный rerun
  app.py может выполнять код и вне кнопок; общая legacy authority вынесена отдельно.
- Существующий object/scopes/audit/lease контроль не объявляется отсутствующим
  только потому, что ещё нет личной AuthSession; он должен быть сохранён миграцией.

## Проверки и риски

Начальный RED: collector отсутствует. После реализации выделенные RED проверки
поймали BOM/trailing-slash и CRLF snapshot drift; отдельный review-integrity RED
проверяет запрет менять source path через semantic binding, придумывать manual
HTTP entries и ссылаться на неизвестную threat. Протоколы разделены по итерациям.
Fixtures также проверяют new route, guard-body edit, router factory/mount, Depends,
duplicate, unsupported registration и полный текущий snapshot.

Source fingerprint не заменяет ручное чтение новой policy. Обновление `--write`
является явным действием разработчика после review, а не автоматическим исправлением
в CI. Hash-значения — evidence consistency, а не security credentials или
манифест ZIP. Данные и secrets окружения collector не читает.

На текущей базе уже есть `apps/api/migrations/0016_pgv2_print_documents.sql`.
При AUTH-02 следующий номер следует перепроверить (на этой базе свободен 0017),
а не перезаписывать 0016 по историческому описанию архитектуры.

Изменений production handlers/auth/resolver/stores/научных алгоритмов нет.
Новые guards не включаются раньше следующих AUTH задач. Проверки AUTH-00 не
являются негативными API-тестами будущего login/CSRF/grant enforcement.
Поскольку FastAPI/scientific dependencies не установлены в этой сессии, настоящий
API import/serve, Redis/PostgreSQL и deployment ACL не проверялись. Это явная
граница статического аудита; неизвестная production конфигурация не названа безопасной.

Фактические результаты/exit codes — `scripts/auth00/protocols/summary.json`.
Итог на этой базе: **26/26 unittest GREEN**, inventory `--check` PASS,
независимая арифметика 215 declarations + 2 DB factory expansion = 217 API methods,
Python compile PASS, renderer tsc build PASS, typecheck embedded/standalone PASS.
CI YAML проверен локально; нативный Windows job и новый удалённый workflow
не запускались. CRLF/BOM проверены fixtures, а не объявлены нативным Windows E2E.
Следующий функциональный шаг — AUTH-01; AUTH-02 может проектироваться на тех же
выявленных identity/account boundaries. Forum activation остаётся закрытым до
durable AuthN, budget admission и worker guards по общему плану.

## Команды

Из корня (Python 3.12; scientific packages не нужны):

```sh
python3 -m unittest discover -s tests/unit -p test_auth00_inventory.py -v
python3 scripts/auth00/inventory.py --check
```

При легитимном изменении source поверхности: прочитать diff и обновить точные
bindings/semantics/threat follow-ups, при необходимости collector fixtures и
baseline metadata, затем `python3 scripts/auth00/inventory.py --write` и повторить
проверки. Не применять generic allow/default к неизвестному входу.
На Windows ту же команду можно запускать настоящим `python` вместо `python3`.

Распаковать ZIP поверх `962ccda`, сохранив полный worklog11.md. Публикация/commit/push
не выполнялись по AGENTS.md. Новые production credentials и users не создавались.
