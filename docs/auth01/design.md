# AUTH-01 — versioned capability / stage / operation registry

База `dfe1941405bae6fc5f370c354cdfcc709741242f`, 31 октября 2026, Москва.
Контракты: spec_auth_architecture.md §3/§9 (AUTH-01), spec_auth.md,
ROLES_AND_PLANS_SPEC.md RP-04/08/09; ограничения billing §5 уточнены RP-08.
Исторический blocker 21946a7 в spec_auth не относится к прочитанной базе.

## Процесс, точки изменения и риски

1. Изолированное detached дерево на точном SHA, чтение AGENTS, спецификаций,
   worklog11 (AUTH-00, Windows/CRLF, PGV-09/10/11), plans/auth/main,
   AUTH-00 inventory, model_execution, UI stages/navigator/plans.
2. TDD: отрицательные проверки отсутствующего registry → реализация; затем
   отдельные RED для OpenAPI integration/serialization, чтения saved outputs
   и пересечения effective dataset ceiling; протоколы scripts/auth01/protocols.
3. Существующий plans.py расширяется аддитивно; старый can_train_models не
   переименован и сохраняет False у demo/starter. Старые зависимости и handlers
   не переключаются на более широкое право без объектного контекста/лимитов.
4. Генератор экспортирует Pydantic serialization schemas в OpenAPI/3.1 и TS.
   Он импортирует только лёгкие contract-модули, без main/science/DB/workers.
   --check ничего не перезаписывает; неизвестный JSON Schema construct — ошибка.
5. AUTH-00 сверяется до/после review; обновляются fingerprints и evidence lines.
   Затем unit/ASGI, TS, сборки и локальные gates, worklog, ZIP без commit/push.

Основные риски: baseline-флаг как обход tuning; трактовка deny-list как allow
неизвестной операции; совпадающие stage names; потеря model context при чтении
старых результатов; ручной TS drift; нестабильный порядок frozenset; null defaults
в FastAPI; CRLF. Эти случаи входят в негативные тесты. Временный role→staff
adapter явно именован INTERNAL_CAPABILITIES, не выдаёт admin permission. Account
INTERNAL entitlement, membership и немедленный downgrade — AUTH-08.

## Версии и источники истины

| Данные | Источник | Версия |
|---|---|---|
| Capabilities, тарифы, finite baseline ceilings | apps/api/plans.py | capabilities_version=2 |
| Stage/operation/bindings + baseline model allowlist | apps/api/access_registry.v1.json | authz-registry/1 |
| Валидатор и функциональное решение | apps/api/access_registry.py | тот же registry_version |
| Wire DTO + metadata | docs/auth01/openapi.json | OpenAPI 3.1; info.version=authz-registry/1 |
| TS wire types, UX camelCase, values, converter | packages/ui/lib/access-contract.generated.ts | generated из Python/OpenAPI |
| Совместимые getCapabilities/Capabilities imports | packages/ui/lib/plans.ts | legacy UX facade |

Registry содержит **203 canonical operations, 224 explicit entry bindings**:
все **220 API method/path templates + 4 task aliases** из AUTH-00. Это не 224
новых endpoint. Renderer, Next page/proxy, storage, legacy и worker surfaces
остаются в полном AUTH-00 (534 записи); не становятся клиентскими analytical
permissions автоматически. Workers требуют service/object/grant/fencing authority
в AUTH-13. modeling.custom.train — зарезервированная функциональная операция,
не обещание реализованного custom-training endpoint. Существующий /models/train
остаётся unavailable placeholder в новом registry; его старый runtime не изменён.

Изменение meaning/allowlist/ceilings/bindings — policy review и новая версия
registry при несовместимом/меняющем права обновлении. Capabilities shape имеет
собственную версию. Операция/job должна сохранять версию и normalized context;
неизвестная версия не исполняется. Persistence/entitlement versions — следующие
AUTH-задачи, данный registry не является хранилищем Account policy.

## Возможности и baseline policy

| План | baseline | tuning | custom/non-baseline fit | legacy train | restricted application stages |
|---|---|---|---|---|---|
| demo | true | false | false | false | scenario, causal, decision, monitoring |
| starter | true | false | false | false | — |
| professional / enterprise | true | true | true | true | — |
| legacy staff adapter | true | true | true | true | — |

Неизвестный operation/entry/stage/namespace/version закрыт даже при пустом
restricted_stage_ids и полных caps. ADMIN/OWNER не выводятся из analytical caps.
Admin/logs/org-profile policy bindings возвращают external_policy_required.

Baseline allowlist — точные runtime IDs **naive, seasonal_naive, drift**.
mean присутствует в scientific runtime, но не выбран в ограниченный каталог v1.
Переименование, регистр, суффикс или mixed baseline+advanced список не baseline.
Custom parameters тоже требуют can_train_custom_models. Runtime readiness и
существование advanced model проверяет scientific coordinator отдельно.

| Policy ceiling | demo | starter / pro / enterprise / legacy staff |
|---|---:|---:|
| Rows | 5 000 | 50 000 |
| Folds | 3 | 5 |
| Horizon | 24 | 48 |
| Seasonal period | 366 | 366 |
| Models in one baseline operation | 3 | 3 |

Это **начальные технические policy ceilings, не измеренная ёмкость, SLA или CU
coefficients**. До production activation обязательны AUTH-14 benchmark и
AUTH-11/12/13 guards/reservations. Они не меняют существующие коммерческие
row/API/analysis/trial параметры. max_dataset_rows из effective caps дополнительно
пересекается с workload; для advanced fit registry не изобретает ресурсные цены.

ModelWorkload содержит положительные строгие integer rows/folds/horizon/seasonal
period, непустой уникальный список model_ids и явный custom_parameters. Bool,
float, пустые/дублирующиеся модели и неизвестные поля не принимаются. Это данные
**серверной нормализации фактического запроса/сохранённого результата**, не
доверенная клиентская декларация baseline=true. Mixed selector не раздаёт
частичные права на оставшиеся advanced модели. Candidates требуют сначала
ограничения серверного каталога, затем проверки фактического набора.

Backtest/candidates/diagnostics зеркала имеют один canonical operation. Все
jobs/start/step/status/cancel, включая старый /tuning path, остаются tuning.
Чтение карт/прогнозов, state (возвращает полный modeling_artifacts), export,
compare/select также требуют saved model context.
Context и skip tuning не считаются выполнением tuning. Пустой metadata-only
state требует отдельной серверной проекции при интеграции AUTH-11; нельзя
объявить текущий /state метаданными и выдать все advanced artifacts. Авторизация
списков требует фильтрации/проверки каждого фактического объекта в AUTH-11.

## Stage namespaces и транспорт

Scientific: upload, validation, preprocessing, eda, modeling, forecasting —
совпадают с существующими STAGE_DEFS, не добавлены в session progress.
Application: scenario, causal, decision, monitoring — совпадают с Navigator.
Service: platform, documentation, observability, education.

Demo имеет все шесть scientific этапов. /tasks/causes и alias — application:causal.
EDA correlation/Granger не application:causal; DOCLOG monitoring — service:documentation.
soon/readiness не является entitlement и не открывает отсутствующий handler.
Динамический session/stage/{stage}, dataset/passport/{stage} принимает только
известные scientific stage IDs. Нет prefix/fuzzy matching пути, aliases явные.

evaluate_entry добавляет can_use_api ceiling для public/models API family;
это не определитель подлинности credentials по URL. У browser/session/internal
не появляется доверие к ключу/Origin/режиму. AUTH-10/11 coordinator обязан отдельно
проверять реальный credential/channel, scopes ceiling, Account и объект.

## OpenAPI и TS

install_openapi_contract подключён к существующему app.openapi после создания
FastAPI: добавляет DTO components, x-cisstat-access-registry и operation IDs к
известным path/method. Нового HTTP route и auth/me-заглушки нет. Полный app import
не нужен генератору. Конфликт schemas проверяется; единственная нормализация —
default:null, который FastAPI опускает при сериализации. /openapi.json содержит
только общую policy metadata, без identities/credentials/balances.

plans.ts сохраняет camelCase/getCapabilities API для существующего TrainModelButton.
Это совместимость UX; новые потребители используют capabilitiesFromDTO с
эффективными серверными полями и проверкой версии. /auth/me ещё AUTH-04/08,
фронтенд не назначает актуальный Account plan. TypeScript не становится вторым
policy engine. Порядок restricted_stage_ids сортируется при сериализации;
generated writes LF, --check читает universal newlines.

## Команды и границы приёмки

```sh
python -m pip install -r scripts/auth01/requirements.txt
python -m unittest discover -s tests/unit -p test_auth01_registry.py -v
python scripts/auth01/generate.py --check
python -m unittest discover -s tests/unit -p test_auth00_inventory.py -v
python scripts/auth00/inventory.py --check
npx jest packages/ui/lib/plans.auth01.test.ts --runInBand
npm run build --workspace=@cisstat/print-renderer
npm run typecheck:all
python scripts/local_gates.py --skip-install --only auth01,auth00
```

Регенерация только после source/policy review: generate.py --write, затем
inventory.py --write. CI auth01.yml Linux/Windows и local_gates.py проверяют
паритет; существующий AUTH-00 CI сохраняется. Pydantic pinned в tooling и API
requirements для воспроизводимой DTO/schema формы.

Протоколы фиксируют фактические локальные результаты. Tiny FastAPI ASGI test
проверяет интеграцию схемы/serialization без запуска научного приложения.
Live production origins, AuthN/MFA/Account, PostgreSQL/Redis, workers и реальные
Demo computations не сертифицированы этой задачей. **functional_allowed означает
только прохождение функционального фильтра**, не разрешение на объект, admission,
reservation или действующий вход. Старые незащищённые /internal не объявляются
закрытыми; runtime rollout требует AUTH-03…13.

## Локальные результаты

- AUTH-01: 26/26 unittest, включая tiny ASGI/OpenAPI и отрицательный drift test.
- AUTH-00: 27/27 unittest; inventory --check PASS, 534 записи / API 220.
- TS contract: 6/6; полный Jest: 245 suites, 2791/2791, один worker, 98.087 s.
- npm ci, renderer build, typecheck обеих оболочек, Python compile: PASS.
- local_gates auth01/auth00 и rules: PASS. Для rules в изолированное окружение
  доставлен отсутствовавший pandera; requirements продукта этим не расширены.
- Generator --check: PASS при PYTHONHASHSEED=1/12/777; byte tamper тест отклонён.
- Next production build попытка: BLOCKED, ENOENT uv_resident_set_memory в
  process.memoryUsage (Node 24.22.1; sandbox /proc недоступен). Типы проверены,
  успешная production Next сборка здесь не заявляется.
- Полный scientific pytest, реальный API main startup/DB/Redis/browser и native
  Windows CI не запускались; CI workflow подготовлен, удалённый run не создавался.

Применить ZIP поверх dfe1941, установить зависимости согласно lockfile/API
requirements, затем прогнать local_gates.py в обычном окружении. Commit/push нет.
