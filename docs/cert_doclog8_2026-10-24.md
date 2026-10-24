# Акт независимой сертификации DOCLOG-8 (2026-10-24)

**Task ID:** DOCLOG-8-CERT. **Цель сертификации:** поставка DOCLOG-8
«Мониторинг — D12 «Сверка прогноза с фактом»» (коммит **afd971c**; цель
аудита — дерево **659db3d** = afd971c + DOCLOG-7-CERT, продуктовые файлы
идентичны: DOCLOG-7-CERT добавляет только корпус сертификатора/акт/
worklog). **Метод:** «оракулы на своих данных, мутанты на своих
мутантах» (методология DOCLOG-3/4/5/6/7-CERT). Манифест sha256 не
ведётся и не используется (указание тимлида, прецедент
DOCLOG-2-FIX…7). Продуктовый код аудитом НЕ менялся: после кампании
md5 всех трёх файлов-целей байт-идентичен git HEAD
(monitoring.py, routers/monitoring.py, snapshot_builder.py), `git
status` по продуктовой части пуст; untracked — `scripts/doclog8cert/`
(корпус) и этот акт.

## 1. Корпус сертификатора (оракулы на своих данных)

Namespace дизъюнктен repo-корпусам DOCLOG-0..8 (RUN-D8A\*, d8-\*,
ctx-d8-\*, fc-d8-\*) и корпусам предыдущих сертификаторов (d6cert-\*,
d7c-\*, RUN-D7C\*): **RUN-D8C\*, d8cert-\*, ctx-d8cert-\*, fc-d8cert-\***,
свои сессии d8cert-session-a/b/c (cookie-доступ к /v1/documentation —
паритет repo-паттерна DOCLOG-8), свой AC-сентинел env
(CISSTAT_D8C_SECRET_SENTINEL). Данные — СВОИ: собственные bound-runs,
собственные артефакты прогноза kind="forecast" (штатный
stage/commit/register), собственные actual vintages/сверки/решения
через штатный MonitoringService.

**Итог: 78 GREEN ×2 (3.39 s / 3.32 s) на 659db3d** — `scripts/doclog8cert/`
(conftest.py, test_d8cert_oracle_unit.py — 42, test_d8cert_oracle_api.py
— 22, test_d8cert_oracle_static.py — 14).

- **Unit (42), u01–u42**: чистая функция compute_comparison_result —
  выравнивание exact+strip (u01); незрелые горизонты — ЯВНЫЙ список
  excluded_labels, НЕ пары с нулевой ошибкой (u02, §6.1); факты вне
  горизонта — sorted-список (u03); точная математика на ручных числах
  (u04); факт-ноль → ape null+reason «actual_zero», mape null +
  mape_undefined_actual_zero + mape_zero_periods (u05); MASE без scale →
  mase_scale_required, с scale — mae/scale, scale<=0 →
  mase_scale_invalid (u06); покрытие интервала с включительной границей
  actual==ci_upper → hit (u07) и честный null + interval_bounds_missing
  при неполных границах (u08); нет зрелых — ВСЕ агрегаты null +
  no_matured_horizons, не 0 (u09); порог — граница операторов >/>= на
  равенстве (u10), not_evaluable с причиной (u11), bias_abs
  отрицательного bias = |bias| (u12), decision_action ВСЕГДА null даже
  при exceeded (u13, §6.1), схема/origin/label (u14); единицы (AC15):
  honest unknown с note (u15), as_is (u16), mismatch → отказ БЕЗ записи
  в реестре (u17), конверсия масштабирует значения + note персистится
  (u18), фактор 0/NaN/str/None/bool → 422, отрицательный фактор
  контрактно разрешён (u19), **ПИН F-D8C1: {factor} без note
  принимается** (u20); T8: порча байтов СОХРАНЯЯ валидность JSON →
  отказ ровно по ветке «Целостность» (u21; первая версия оракула
  портила JSON до невалидности — киллила parse-ветку, weakness
  исправлена в ходе кампании); чужой kind=model_card → отказ (u22);
  чужой run-артефакт → AccessDenied без записи (u23); пустой points и
  призрачный артефакт → отказ (u24); идемпотентность: same body →
  created=False (u25), conflict на другое тело (u26), пустой ключ —
  без дедупа (u27), fingerprint стабилен к порядку ключей (u28),
  сверка: повтор/конфликт/ровно одна запись (u29); каталог валидации
  партии — 14 корпусов отказов вкл. дубликаты периодов, NaN/Inf/bool/
  str-value, entity_id «», мусорный/пустой as_of, source_kind вне
  каталога (u30); as_of «Z»-раундтрип и честная наивная метка без
  фабрикации TZ (u31, **ПИН N-D8C2**); threshold-каталог сервиса:
  metric/operator/value/NaN/str/не-dict (u32); vintage-заморозка:
  ревизия = новая партия, старая байт-в-байт (u33), новая сверка не
  трогает старую (pairs+payload_sha256 frozen, u34 — критерий §19);
  read-only над научным слоем: байты прогноза/реестр артефактов/run
  не изменяются регистрацией+сверкой+решением (u35, AC05-дух);
  решения: каталог fail-closed, retrain_requested — запись-запрос
  (u36), rationale обязателен (u37), чужая сверка → NotFound (u38),
  append-only порядок decided_at ASC + атрибуция decided_by (u39);
  Memory-реестр: unknown → None, пустой ключ → None (u40), лимит и
  ASC-порядок списков (u41); **чужая партия факта в сверке → отказ
  (u42)**.
- **API (22), a01–a22**: uniform 404 анонима на ВСЕХ 7 маршрутах
  (a01) и чужой сессии (a02); 201-контракт регистрации: схема
  doclog.actual_vintage/1, префикс act-, Z-раундтрип as_of, notes/
  source_ref/created_by==subject (a03); 422-каталог с плоским телом
  {code,message,request_id} без detail/сентинела (a04);
  monitoring_units_mismatch — ОТДЕЛЬНЫЙ код 422 (a05, AC15);
  идемпотентность: created=False → 409 monitoring_idempotency_conflict
  (a06); 404 monitoring_forecast_unavailable (a07); чужой артефакт →
  uniform 404 run_not_found_or_forbidden (a08); 201-контракт сверки:
  schema/comparison_id mon-/matured/units_check/forecast_sha256/
  payload_sha256/threshold exceeded/decision_action null + повтор и
  детализация (a09); решения: flow + append-only + decided_by (a10),
  422-каталог действий/rationale (a11), чужая сверка → 404
  monitoring_not_found (a12); аудит-трио monitoring_\*: ровно по одной
  записи allowed с actor_subject/resource_kind=monitoring/run_id/
  policy_basis (a13); **§8/AC11: monitoring_\* — standard-класс:
  ломучий sink НЕ ломает научную операцию** (a14); GET не создаёт
  записей monitoring_\* и не меняет состояние (a15, §17); гигиена
  ошибок: без сентинела/traceback/postgres://, ровно 3 ключа тела
  (a16); каталог кодов {validation, forecast_unavailable, conflict,
  units_mismatch} дизъюнктен (a17); секция D12 снимка читает frozen
  сверку (id mon-, порог mae, exceeded, «решение человека: —», ref на
  артефакт) (a18) и пустая — честный unknown-claim (a19);
  source_kind="artifact" зарезервированный интерфейс принимается,
  "db" → 422 (a20); **ПИН N-D8C1: две формы тела uniform-404** (шлюз
  {"detail"} vs сервисное плоское — a21); **ПИН N-D8C4-контекст:
  сверка без зрелых горизонтов в D12-claim — «MAE=—», не
  фабрикованный «MAE=0»** (a22).
- **Static (14), s01–s14**: миграция 0014 — файл↔каталог MIGRATION_
  FILES[-1] построчно, ровно 7 statement (3 таблицы + 4 индекса)
  (s01); DDL fail-closed: 3×REFERENCES research_runs ON DELETE
  CASCADE, ровно 2×UNIQUE(run_id, idempotency_key) (партии+сверки),
  решения БЕЗ идемпотентности (append-only многих), JSONB
  actual_values/result, только CREATE-стейтменты (s02); 4 индекса
  поимённо (s03); роутер: ровно 7 маршрутов с точной картой
  методов/путей (s04); карта ошибок _error_response по исходнику
  (все 6 кодов + uniform-404 + current_request_id, s05); каталоги
  frozen: DECISION_ACTIONS/THRESHOLD_METRICS/THRESHOLD_OPERATORS/
  SOURCE_KINDS/DEFAULT_LIST_LIMIT=100 (s06); 5 schema-версий
  дословно (s07); AUDIT_ACTIONS==24 с трио monitoring_\* и
  **record_standard в сервисе, record_mandatory отсутствует** (§8)
  (s08); DOCUMENT_KINDS==12 с D12 forecast_vs_actual + resolve
  (s09); publish-политика «partial допустим для D01-D10 и D12»
  (s10); чистота compute: в исходнике нет os.environ/реестров/
  psycopg/print/datetime.now, входные payload/values не мутируются
  (s11); структурный паритет ABC/Memory/Postgres — 10 методов без
  NotImplementedError (s12, урок F-D2C1); Postgres-контур статически:
  без «SELECT \*», без UPDATE/DELETE/DROP (append-only AC15), без
  f-интерполяции SQL, 3×ON CONFLICT DO NOTHING (s13); UI-контракт:
  read-only клиент (ровно 2 запроса documentationApiUrl, credentials
  include, ключ не в URL) + **регрессионный пин «use client» первой
  строкой панели** (урок DOCLOG-8-UI-FIX) (s14).

## 2. RED на родителе

Корпус на родителе DOCLOG-8 **e33b08b** через git-worktree:
**collection RED за 0.30 s** — `ModuleNotFoundError: No module named
'apps.api.monitoring'` (1 error during collection; протокол
protocols/red_parent_summary.txt). Корпус не вакуумный: тестирует
именно поверхность DOCLOG-8.

## 3. Мутационная кампания («мутанты на своих мутантах»)

Двухканальная схема: **REPO** = test_doclog8 + test_doclog2 +
test_doclog6 (185 тестов — поверхность DOCLOG-8 + фундаментальные
пины каталогов видов/publish-политики); **ORACLE** = корпус
сертификатора (78). **37 боевых мутантов + 3 no-op контроля** над
тремя продуктовыми файлами (monitoring.py, routers/monitoring.py,
snapshot_builder.py).

**Итог: 28 DUAL-KILLED + 9 ORACLE-ONLY + 0 REPO-ONLY + 0 боевых
SURVIVED; контроли 3/3 ALIVE; PATCH-FAIL 0; RESTORE-FAIL 0**
(protocols/mutations_summary.json, протоколы mut_\*.json с tails обоих
каналов; консолидация — scripts/doclog8cert/consolidate.py с финальной
MV3-сверкой md5 файлов == git HEAD). Мета-валидация: **MV1** — dry-run
40/40 якорей (ровно одно вхождение); **MV2** — классификатор сверен с
синтетикой (self-test PASS); **MV3** — байт-в-байт восстановление
после каждого мутанта (git checkout -- + md5 == HEAD, финально
перепроверено консолидатором); **MV4** — контроли C1–C3 ALIVE —
каналы не «косят» всё; **MV5** — скан хвостов киллов на посторонние
файлы: упомянуты ТОЛЬКО файлы каналов — ложных киллов нет (урок N2
DOCLOG-6-CERT).

**Классификация боевых мутантов:**

- **DUAL-KILLED (28):** M01 (units mismatch молча as_is), M02 (фактор
  конверсии игнорируется), M03 (T8 sha256 off), M04 (чужой run-артефакт
  принят), M05 (kind-гейт off), M07 (конфликт идемпотентности off),
  M08 (дедуп партий off), M09 (MAPE фабрикуется 0 при нулевом факте),
  M10 (нет зрелых → 0 вместо null+reason), M11 (**§6.1 off: незрелый
  горизонт получает нулевую ошибку**), M12 (MASE из MAE без scale),
  M13 (покрытие при неполных границах), M14 (not_evaluable → within),
  M16 (**decision_action из статуса порога — автопереобучение**), M17
  (каталог действий открыт), M18 (rationale не обязателен), M19
  (решение на чужой сверке), M20 (дубликаты периодов), M21 (NaN/Inf/
  bool значения), M25 (вне-горизонтные факты скрываются), M26 (unknown
  фабрикуется as_is), M28 (as_of fail-open → now), M31 (409→422), M32
  (код 422 изменён), M33 (units_mismatch теряет код), M34 (created
  инвертирован), M35 (201→200), M36 (пустая D12-секция фабрикует
  current).
- **ORACLE-ONLY (9):** M06 (run-граница чужой партии — repo не
  тестирует foreign-batch), M15 (>= тихо сужен до > — repo не пинует
  границу равенства), M22 (аудит-action вне каталога — repo не пинует
  имена), M23 (**standard-аудит превращён в ломучий** — repo не
  проверяет §8-инвариант на ломучем sink), M24 (payload_sha256 не
  вычисляется — repo сравнивает лишь равенство list/detail), M27
  (пустой points принимается), M29 (source_kind каталог открыт), M30
  (uniform 404 → 403 на сервисном AccessDenied — repo не доходит по
  HTTP), M37 (отсутствующие агрегаты D12-claim фабрикуются «0» —
  убит УСИЛЕННЫМ a22; первичный a18 киллил по литералу f-строки,
  слабость первого оракула исправлена в ходе кампании, протокол
  перепрогнан). Перенос пинов M06/M15/M23/M24/M27/M29/M30/M37 в
  repo-сюиту — кандидат N-плана (прецедент N1 DOCLOG-6-CERT).

Слабости оракулов, найденные и исправленные В ХОДЕ кампании (честная
история): (1) u21 портила JSON до невалидности — килл шёл по
parse-ветке, не по T8; исправлено на порчу с сохранением валидности
JSON + match=«Целостность» (после фикса M03: ORACLE-мисс →
DUAL-KILLED); (2) a18 проверяла «решение человека: —» по литералу
f-строки, минуя _fmt — добавлен a22 с None-агрегатами (после фикса
M37: SURVIVED → ORACLE-ONLY); (3) u19 ошибочно требовала отказа на
отрицательный фактор — контракт требует лишь ненулевой (пин честной
границы). Все перепрогонные протоколы — в mut_\*.json.

## 4. Регресс и сборка

- **Полный tests/api дельта-0** (scripts/doclog8cert/regress_delta0.py,
  кэш pytest отключён — урок DOCLOG-8 о .pytest_cache): цель
  **659db3d+корпус 11F/2823P/42S** vs база 659db3d (git-worktree)
  **11F/2745P/42S** — **множества FAILED-ID байт-идентичны (11/11,
  diff пуст, protocols/regress_delta0.json)**; +78 passed = ровно
  корпус сертификатора. Все 11F — предсуществующие средовые классы
  (progress_audit_5b/psycopg-DSN 7, modeling-workflow/neural/
  candidates 3, progress-panel 1) — идентичны на обеих сторонах.
- **Jest:** `doclog8-monitoring-ui` **7/7** + `doclog6-lifecycle-ui`
  **15/15** = 22/22 (протокол jest_doclog8ui.txt).
- **Сборка:** import apps.api.main OK — **216 маршрутов** (ровно **7
  путей /monitoring/**), каталог **14 миграций / 85 statement**
  (последняя 0014), DOCUMENT_KINDS=12, AUDIT_ACTIONS=24 (трио
  monitoring_\*), DECISION_ACTIONS/THRESHOLD_METRICS по контракту,
  5 schema-версий дословно; **продуктовое дерево чистое** (md5 трёх
  файлов-целей == git HEAD) — protocols/build_check.json,
  **BUILD: OK**.

## 5. Находки

- **F-D8C1 (низкая, контракт↔код; пин u20):** `units_conversion.note`
  НЕ обязателен в коде ({factor} без note принимается, units_note=''
  записывается), хотя контрактный документ docs/doclog8_monitoring.md
  требует «converted (только явно переданный **{factor, note}**)».
  Расхождение документ↔реализация; данных/прав не затрагивает.
  Рекомендация: либо требовать непустой note в _validate, либо
  поправить контрактный документ (решение тимлида). Аналог F-D7C1.
- **N-D8C1 (наблюдение; пин a21):** uniform-404 имеет ДВЕ формы тела:
  шлюзовое отклонение (HTTPException _authorized_run_or_404 —
  {"detail": {…}}) и сервисный MonitoringAccessDenied (плоское
  {code, message, request_id}). Статус uniform, форма асимметрична.
  Рекомендация: унифицировать тело (паритет форм), либо зафиксировать
  решение в контракт-доке.
- **N-D8C2 (наблюдение; пин u31):** as_of принимает наивную ISO-метку
  и хранит её БЕЗ фабрикации TZ (честно), но в PG-пути колонка
  TIMESTAMPTZ + psycopg интерпретируют наивное значение в session TZ —
  семантический сдвиг Memory/PG для наивных меток. Живой PG-прогон —
  за границей песочницы (паттерн AUDIT-6A); рекомендация: требовать
  offset-aware метки либо фиксировать UTC при записи в durable-контуре.
- **N-D8C3 (robustness, гонка):** идемпотентность — check-then-insert,
  не атомарна: параллельные запросы с одним ключом в Memory создадут
  дубли (нет ограничения), в PG UNIQUE(run_id, idempotency_key)
  IntegrityError → 500 monitoring_internal (fail-safe направление:
  тихих дублей в PG нет, но код не uniform и операция не идемпотентна
  под гонкой). Однопоточный HTTP-контур песочницы не воспроизводит.
  Рекомендация: ловить unique-violation и возвращать существующую
  запись/409 (адресная пересертификация).
- **N-D8C4 (семантика поля; зонд protocols/probe_findings.json):**
  в списках actuals/comparisons `total` = len(items) при дефолтном
  лимите 100: при 105 зарегистрированных партиях listed=100 — поле
  показывает размер страницы, а не полное число (пилотный предел §18
  задокументирован; имя поля вводит в заблуждение). Рекомендация:
  либо переименовать (page_size/returned), либо отдавать честный total
  отдельным счётчиком.
- **N-D8C5 (крайний случай; зонд):** инвертированные CI-границы
  (ci_lower > ci_upper) не валидируются ни сервисом, ни чистой
  функцией: interval_hit всегда False, покрытие 0.0 — не фабрикация,
  но и не отказ/сигнал о некорректном прогнозе. Рекомендация: 422 на
  inverted bounds при построении сверки либо явная not_evaluable-
  причина.
- **N-D6 (контракт pure-функции):** compute_comparison_result при
  прямом вызове с value=None/missing бросает TypeError (сервис
  валидирует вход раньше; функция не защищена от misuse). На HTTP-
  контур не влияет; кандидат — MonitoringValidationError внутри
  compute либо фиксация «функция принимает уже валидированный вход»
  в докстринге.

## 6. Вердикт

**СЕРТИФИЦИРОВАНО С НАХОДКАМИ (PASSED WITH FINDINGS).** Поверхность
DOCLOG-8: критерий завершения §19 — «поздний факт и revise не
переписывают старый выпуск/OOF» — подтверждён двухканально:

- **Frozen-семантика (§19):** ревизия факта = НОВАЯ партия, старая
  байт-в-байт (u33); новая сверка не трогает старую — pairs и
  payload_sha256 заморожены (u34); прогноз читается read-only с T8-
  проверкой целостности (u21, M03), НИКОГДА не пересчитывается и не
  заменяется (M04/M05 чужой run/kind — убиты); научный слой не
  мутируется (u35, a15).
- **Незрелый горизонт ≠ нулевая ошибка (§6.1):** ЯВНОЕ исключение со
  списком меток (u02, M11-мутант убит), вне-горизонтные факты
  посчитаны отдельно (u03, M25), честные null+reason по всему каталогу
  AC12 (u05/u06/u08/u09, M09/M10/M12/M13), D12-claim снапшота не
  фабрикует нули (a22, M37).
- **Автопереобучение не следует из порога (§6.1):** decision_action
  всегда null (u13, M16-мутант убит), порог — факт exceeded/within/
  not_evaluable (u10/u11, M14/M15), решение — отдельная append-only
  запись человека с обязательным основанием и фиксированным каталогом
  (u36–u39, M17–M19).
- **Доступ и границы (T7/T15, решающая таблица DOCLOG-0):** чужой
  run/артефакт/партия/сверка не выдаются (M04/M06/M19; a02/a08/a12),
  аноним — uniform 404 на всех 7 маршрутах (a01), знание
  идентификатора не является правом.
- **Идемпотентность и аудит:** UNIQUE(run_id, idempotency_key) с
  честным конфликтом 409 (u25–u29, a06, M07/M08); аудит monitoring_\*
  — standard-класс по §8 (a13/a14, M22/M23), GET не имитирует научные
  операции (a15).

28/37 боевых мутантов DUAL-KILLED, 9 ORACLE-ONLY (репо-канал слабее на
негативных ветках — перенос пинов в repo-сюиту = кандидат N-плана),
0 SURVIVED, контроли 3/3 ALIVE. Находка F-D8C1 и наблюдения N-D8C1–
N-D8C5/N-D6 — низкий уровень, блокером не являются; рекомендации
сформулированы. Живой PostgreSQL-прогон 0014 — за границей песочницы
(честная граница, паттерн AUDIT-6A); pg-контур закреплён статически
(s01–s02/s12–s13).

**План DOCLOG-8-FIX (кандидат, по решению тимлида):** (1) F-D8C1 —
валидация note либо правка контракт-дока; (2) N-D8C3 — обработка
unique-violation в save_actual_batch/save_comparison + 409; (3) N-D8C5
— отказ/сигнал на инвертированные CI; (4) N-D8C1 — унификация тела
uniform-404; (5) N-D8C4 — семантика total; (6) перенос ORACLE-ONLY
пинов в repo-сюиту. Для (1)–(5) пересертификация адресная (повторный
прогон корпуса + целевые мутанты), для (6) — прогон repo-канала.

Deliverable: ZIP cisstat-doclog8-cert.zip → открытый контейнер сессии
(download): scripts/doclog8cert/ (conftest, оракулы unit/api/static,
mutations.py, consolidate.py, regress_delta0.py, build_check.py,
probe_findings.py, protocols/), docs/cert_doclog8_2026-10-24.md (этот
акт), worklog/worklog11.md (запись). Без commit/push (AGENTS.md).
