# Акт независимой сертификации PROGR-AUDIT-4-CERT (2026-10-12)

**Задача:** plan_progress_audit.md §10, AUDIT-4 — outcome и детали
коррекции: единый вывод исхода (changed/no_change/violations/clean/
unknown), честные статус/reason/бейдж коррекций, счётчик следует за
reason-событием (P16), невалидный status — аномалия (P15), параметры
результата в dedupe (P19) (коммит 0af1ea5 поверх 02ac7ff).
**Аудитор:** независимая сессия (PROGR-AUDIT-4-CERT). Правила AGENTS.md
соблюдены: commit/push НЕ выполнялись; продуктовый код и тесты
репозитория не изменялись — только артефакты аудита (все untracked;
оба продуктовых файла, затронутых мутационной кампанией, после проб
md5 == HEAD побайтово, diff-контроль git status: только untracked
артефакты сертификации).
**Постановка тимлида:** «честно сертифицируй PROGR-AUDIT-4 — outcome
и детали коррекции. Спроектируй и реализуй данную Сертификацию.
Используй мутантов на своих мутантах, оракулов на своих данных».
**Окружение:** Python 3.12.15, pandas 2.2.3, statsmodels 0.15.0,
fakeredis, FastAPI 0.128.0, pytest 9.0.2 — та же лёгкая группа R6, что
в сертификациях 6A/5B/1A (`apps.api.main` импортируется). pgserver не
участвует: AUDIT-4 хранилища/миграции не трогает (журнал: «postgres-
сюита вне дельты задачи»).
**База аудита:** main@3322e4a (HEAD = коммит 1A-CERT; предыдущие
0af1ea5 — аудируемая реализация AUDIT-4, 02ac7ff — принятая 5B-CERT;
дельта 0af1ea5→3322e4a не касается продуктового кода — только артефакты
сертификаций 5B/1A; синхронизация по прямому указанию тимлида).

---

## 1. Сверка реализации с кодовой базой (0af1ea5 == 3322e4a)

Все точки карточки §10 плана и контракта v0.8-4A (§18) на месте:

- `app/core/node_status.py` — ЕДИНСТВЕННАЯ проекция исхода
  `resolve_correction_outcome(data)`: preview — по диагностике ДО
  (`CORRECTION_VIOLATIONS_KEYS`), apply — по прямым отчётам объёма
  (`CORRECTION_CHANGED_KEYS`), fallback-пара до/после (regularity),
  половина пары/пусто — честный unknown; щит счётчиков тот же, что
  `_clean_summary_count` (bool/строка/дробь/отрицательное — не факт);
  `correction_reason` — канонические тексты сохранены для доказуемых
  исходов, новые честные тексты для clean/partial/no_change/unknown
  (`_CORRECTION_REASON_BY_OUTCOME`); `_correction_summary_count` —
  исход-осознанный бейдж (apply — remaining→before→changed, preview —
  найденные нарушения, unknown — прежний плоский приоритет
  `NODE_SUMMARY_COUNT_KEYS`, расширенный фактами до/после с сохранением
  прежнего порядка ключей); `_override_status_field_invalid` — P15
  (ПРИСУТСТВУЮЩИЙ невалидный status override-типа; None/отсутствие —
  легаси-ветка); `NodeStateFold.apply` — решающая ветка коррекций:
  reason/бейдж/`_outcome` из фактов ТОГО ЖЕ события, статус из исхода
  (violations/remaining>0 → warning; changed → done; clean/no_change-
  прочее/unknown → статус не утверждается), валидный карточный override
  (C5/PROGR-23) приоритетен, map-фолбэк исходом не считается; P16 в
  ОБОИХ ветках (коррекционной и не-коррекционной) — счётчик следует за
  reason-событием, без фактов бейдж очищается; P15-аномалия целиком
  вне decision details (касание остаётся); `resolve_event_status` НЕ
  менялся (словарная проекция для гейтов фаз); evidence
  `node_states_with_evidence` аддитивно несёт `outcome` (7-польный
  §3-контракт не менялся); `export_state`/`restore_state` несут детали
  (outcome/anomalies переживают checkpoint — проверено PRJ2).
- `apps/api/trace_hook.py` — whitelist `_CORRECTION_PAYLOAD_KEYS`
  расширен фактами «нарушения до/после» (total_still_*, still_*,
  rows_changed/added/dropped, total_violations_before/after,
  duplicate_rows — отсутствующие опускаются); P19/F13:
  `DEDUPE_PARAM_KEYS=("method","mode")` + `_event_params` (нестроковые
  — честно None, несловарный payload — None) + сравнение параметров с
  последним stored-событием того же (event_type, node_id) в
  `_node_picture_unchanged`: смена параметров при равной картине —
  новый факт, refetch — dedupe, легаси-событие без параметров
  самозаживляется.
- Батч-функции (`derive_node_statuses`/`derive_pipeline_node_states`)
  — развёртка того же `NodeStateFold`: второй реализации семантики
  нет (прецедент свёртки 5B).

Периметр задачи — 2 продуктовых файла + тесты/документация; UI (.ts/
.tsx) не затронут — jest/tsc вне периметра (паттерн 1A/5B).

## 2. Независимая верификация базлайнов (1:1 с журналом)

- Оракул исполнителя `tests/api/test_progress_audit_4.py`:
  **48/48 passed** — заявление журнала 1:1.
- Адресные сюиты журнала (engine/progr23/trace_hook/panel/5b/1a/6a/C/
  S/H1/mentor/admin_progress/admin_analytics — 13 файлов):
  **508 passed / 17 skipped** — без падений, дельта 0.
- Полный регресс tests/api + tests/integration: **1746 passed / 3
  failed / 18 skipped**. Все 3 failed — задокументированный средовой
  класс (production dispatch моделей вне контура «Прогресса»:
  modeling_workflow, backtest_neural_capacity, models_candidates —
  тот же класс, что в 1A-CERT, где он воспроизведён на чистой базе).
  Арифметика согласована: 1746 = 1698 (полный прогон базы 1A на
  5364d41) + 48 (новый оракул AUDIT-4) — versioned-обновления пинов
  число тестов не меняли. Журнальные «19 failed» (sandbox без лёгкой
  группы) в R6-среде сняты до 3 — тот же редукционный эффект, что
  задокументирован в 1A-CERT (statsmodels 0.15.0).
- Сборка: импорт `apps.api.main` OK; py_compile обоих продуктовых
  файлов OK.

## 3. RED-протокол исполнителя на базе 02ac7ff

git-worktree 02ac7ff с копией их итогового тест-файла: **40 failed /
8 passed** против заявленных 39/8. Набор PASSED совпал **1:1** (те же
8: violations-preview канон, C5-override ×2, status None/мусорный
resolve_event_status, nonnumeric summary, dedupe refetch/picture).
Дельта 1 тест объяснена точно: RED-протокол снят на 47 тестах, GREEN-
файл содержит 48 — panel-тест `test_partial_apply_panel_warning_
and_remaining_badge` между RED и GREEN разделён на два
(`test_flag_apply_no_elimination_is_warning` +
`test_full_apply_panel_badge_is_after_state`); 48−8=40, 47−8=39.
Документированная эволюция оракула исполнителя, на вердикт не влияет
(замечание R2, §7). Ложно-зелёных среди контрактных групп нет: все
группы outcome/reason/честного статуса/P16/P15/evidence/whitelist/
P19-метода/панели отказывают на базе.

## 4. Оракулы на СВОИХ данных — scripts/prograudit4cert_oracles.py: 50/50 PASS (EXIT=0)

Свои данные сертификатора, дизъюнктные данным оракула исполнителя
(их корпуса frame_with_missing a/b/c, frame_clean, frame_spike
seed=20261012): CSV-корпуса cert4_prodazhi.csv (продажи — чистый),
cert4_gidro.csv (уровень/расход/температура — 4+1 пропуска),
cert4_nagruzka.csv (нагрузка, seed 40407, выброс [20]=60 —
iqr/zscore одна картина), cert4_reg.csv (дубли дат, неупорядоченность);
свои run_id RUN-C4-*, свои event_id c4-ev-*, свои контексты, свои
payload-значения; наблюдательные методы сертификатора (fold-доказательства,
anomaly_count, evidence-поля; e2e — свои корпуса через живой API).

- **OUT (11)**: вывод исхода на своих payload — preview violations/
  clean/без фактов unknown/мусор-счётчики (строка/bool/отрицательное/
  дробь) unknown; apply changed/no_change/fallback-пара (обе ветки)/
  половина пары unknown; приоритет прямых фактов над парой;
  не-коррекционный тип unknown; детерминизм «первый валидный факт по
  порядку ключей группы» на противоречивом синтетическом payload.
- **RSN (7)**: канонические тексты сохранены (violations-preview,
  changed-apply, remaining=0); честные тексты «применена частично»/
  «не изменила данные»/«не устранила»/unknown без претензий качества
  (лексический щит: unknown-текст не содержит «применена/устранила/
  Найдены»); integrity карты EVENT_NODE_REASON.
- **FLD (13)**: чистая проекция fold — clean preview не красит (P14)
  с честным reason; violations preview → warning+бейдж до; no-op при
  remaining>0 → warning с бейджем «после»; частичное → warning+
  remaining; полное → done+бейдж 0 (состояние после, не диагностика
  до); unknown не утверждает и не понижает чужие узлы; **P16** —
  бейдж очищается без фактов (не наследует цифру прежней диагностики),
  evidence count_source==reason_source; **P15** — мусорный/нестроковый
  status → аномалия с нетронутыми деталями и живым last_touched_at,
  status None — не аномалия (исход changed даёт done), контракт
  resolve_event_status прежний; C5-override обе ветки; пин PROGR-11
  (мусор одного счётчика); **FLD13 — no_change-прочее статус не
  утверждает** (пин, добавленный по результату мутанта CM-10, §5/§6).
- **EVD (3)**: outcome в доказательствах аддитивен (7-польный контракт
  не сужен); clean в evidence; None без коррекций и на чужих узлах.
- **PRJ (2)**: паритет батч/инкремент на коррекционном потоке
  (статусы/reason/бейджи); 5B-инвариант replay == snapshot+tail на
  потоке с коррекциями и аномалией — anomalies/outcome переживают
  checkpoint.
- **DQ (6)**: P19 на своих данных — iqr→zscore при равной картине:
  два факта (методы сохранены); refetch — один факт; смена картины
  (disabled) пишется независимо; `DEDUPE_PARAM_KEYS`/`_event_params`
  честные None; mode-канал (unit): смена mode при равной картине —
  новый факт, refetch — dedupe; легаси-самозаживление (первое новое
  событие с параметрами пишется, после — прежняя семантика).
- **PNL (8)**: панель e2e на своих корпусах — чистый preview pending
  без «Найдены нарушения»; flag-стратегия (changed=0, remaining>0) →
  warning с бейджем remaining; полное исправление → done+канон+бейдж 0;
  повторный no-op → «Коррекция не изменила данные» при сохранном done;
  scaling (без фактов) → pending «исход не подтверждён»; regularity
  sort e2e (пары до/после: 6→3) → warning+бейдж 3+«не устранила»
  (находка F-4C1/R1); карточка выбросов после полной cap-коррекции →
  done+бейдж 0 (C5); надстройка карточки стадии отражает честные
  статусы узлов (attention/warning_nodes/done_count).

## 5. RED-воспроизведение СВОИХ оракулов на 02ac7ff

git-worktree базы, прогон scripts/prograudit4cert_oracles.py:
**42 FAIL / 8 PASS (EXIT=1)** — протокол
scripts/prograudit4cert_red_repro.txt. 42 отказа — контрактные группы
AUDIT-4: ImportError своего API (resolve_correction_outcome/
correction_reason/DEDUPE_PARAM_KEYS — по-оракульная грануляция благодаря
ленивым импортам), поведенческие H14 (clean-preview/no-op фабрики
статусов), P16 (наследование цифры), P15 (аномалии), P19 (метод в
dedupe), честные reason, whitelist, evidence-outcome, панель e2e.
8 PASS — регресс-пины УЖЕ работавшего поведения, обязанные остаться
зелёными и на HEAD (DQ2/DQ3 — картинный dedupe PROGR-23, FLD2 —
violations-preview, FLD8 — count_source при наличии счётчика, FLD11 —
C5-override, PNL7 — карточка выбросов, PRJ1 — паритет редьюсера 5B,
RSN7 — канон-словарь). Ложно-зелёных среди контрактных групп нет.

## 6. Мутационная кампания СВОИХ мутантов — 13/13 KILLED; контроль выжил

scripts/prograudit4cert_mutations.py. Набор ДИЗЪЮНКТЕН по точкам/
классам: исполнитель AUDIT-4 мутационную кампанию не вёл (их RED-
протокол 39/8); камеры 6A-CERT (ledger/sequence/receipt/CAS), 5B-CERT
(проекция/watermark), 1A-CERT (choice/reset/origin/пара/restore) не
затрагивают семантику исхода коррекции. Дисциплина: backup →
единственный якорь (PATTERN-MISS = аварийный останов; все 13 якорей
проверены на единственность) → патч → оба канала → побайтовое
восстановление → md5-контроль в finally: **md5 обоих файлов == HEAD**.
Каналы: oracle (50 своих) + repo (48 тестов исполнителя). Кампания
проведена ДВУМЯ волнами (открытая фиксация, §7): волна 1 (49 оракулов)
— CM-10 выжил в ОБОИХ каналах; после усиления оракула (FLD13) волна 2
(50 оракулов) — финальная, все мутанты убиты.

| Мутант | Класс / точка | Oracle | Repo | Вердикт |
|---|---|---|---|---|
| CM-0 | no-op контроль | EXIT=0 | 48 passed | SURVIVED (харнесс достоверен) |
| CM-1 | preview-инверсия clean↔violations (H14-фабрика) | EXIT=1 | 6 failed | KILLED-BOTH |
| CM-2 | preview без фактов → violations (легаси-фабрика) | EXIT=1 | 2 failed | KILLED-BOTH |
| CM-3 | changed>=0 — no_change мёртв | EXIT=1 | 3 failed | KILLED-BOTH |
| CM-4 | fallback-пара ==/!= инверсия | EXIT=1 | 2 failed | KILLED-BOTH |
| CM-5 | половина пары выдаёт исход | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-6 | частичность скрыта в reason | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-7 | бейдж apply — диагностика ДО | EXIT=1 | 4 failed | KILLED-BOTH |
| CM-8 | P16 снят (наследование цифры) | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-9 | P15-щит снят (мусор в деталях) | EXIT=1 | 2 failed | KILLED-BOTH |
| CM-10 | no_change → done (H14) | EXIT=1 | 48 passed | KILLED-ORACLE-ONLY (волна 1: SURVIVED-оба) |
| CM-11 | unknown → done | EXIT=1 | 4 failed | KILLED-BOTH |
| CM-12 | P19 снят: DEDUPE_PARAM_KEYS=() | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-13 | whitelist без пары до/после | EXIT=1 | 1 failed | KILLED-BOTH |

ИТОГО волны 2: 12 KILLED-BOTH + 1 KILLED-ORACLE-ONLY, 0 SURVIVED среди
мутантов; контроль CM-0 SURVIVED (харнесс достоверен).

## 7. Эволюция оракулов (открытая фиксация, прецедент 24-C R4 / 6A / 5B / 1A)

Первая редакция (49 оракулов) на HEAD дала 42/49 — все 7 отказов
ДЕФЕКТЫ ХАРНЕССА сертификатора, не продукта: (1) CSV_PURE без строки
заголовка → колонки col_0/col_1; (2) сигнатура `_node_picture_unchanged`
+ session-объект без атрибута `pipeline_trace`; (3) неполные stored-
события (без stage/ts/actor) ломали before-картину dedupe; (4) FLD10 —
неверное ожидание легаси-ветки (map-фолбэк «done» при status=None
возникает через ИСХОД при фактах результата, не напрямую из карты);
(5) PNL6 — запрос без `apply: true` (preview, честный warning по
диагностике до); (6) PNL8 — семантика fold карточки стадии
(«attention», не «warning»/«done»); (7) DQ6 — инверсия чтения
самозаживления («первое новое событие с параметрами ПИШЕТСЯ»).
Вторая редакция: 47/49; третья: 49/49; финальная — 50/50 (добавлен
FLD13, см. ниже). Ни одна итерация не потребовала изменения продукта.

**Находка кампании (главный результат «мутантов на своих мутантах»):**
в волне 1 мутант CM-10 (no_change → done) пережил И оракулы
сертификатора (49), И сюиту исполнителя (48/48 passed) — контрактное
правило v0.8-4A §18.2 «no_change-прочее/unknown → статус НЕ
утверждается» не пинилось никем: все существующие no-op-тесты либо
remaining>0 (warning), либо на уже-done узле (исход неотличим).
Добавлен оракул FLD13 (preview-warning → no-op apply {нули, remaining=0}
→ узел ОБЯЗАН остаться warning); точечная проверка на мутанте —
единственный отказ FLD13; волна 2 — CM-10 KILLED-ORACLE-ONLY.
RED-протокол на базе переснят (42/8).

## 8. Находки

- **F-4C1 (РЕКОМЕНДАЦИЯ, покрытие repo)**: сюита исполнителя AUDIT-4
  не пинит правило «no_change-прочее → статус не утверждается» (CM-10
  пережил repo-канал; killed только оракулом FLD13 сертификатора) и
  также не пинит mode-канал параметров dedupe (CM-12 убит repo лишь
  косвенно через method — прямого mode-пина в repo нет). Перенос пинов
  в repo-сюиты рекомендован следующей тестовой задачей (прецеденты
  F-6A1/F-1A1).
- **R1 (наблюдение, семантика e2e)**: fallback-пара до/после
  (v0.8-4A §18.1) e2e для regularity sort недостижима: маршрут всегда
  сообщает `rows_added` (0 при sort) — прямой факт, и приоритет прямых
  фактов даёт исход no_change («Коррекция не устранила нарушения» при
  remaining>0), а не changed-по-паре («применена частично»). ЭТО НЕ
  ПРОТИВОРЕЧИТ КОНТРАКТУ (fallback определён как «прямых фактов нет»),
  все честные претензии сохранены (warning + бейдж remaining + отказ
  от done). Нюанс reason-текста для отчёта — учесть в AUDIT-7B
  (шаблоны фактов отчёта).
- **R2 (наблюдение, журнал)**: RED-протокол исполнителя снят на 47
  тестах, GREEN-файл содержит 48 — panel-тест разделён на два между
  RED и GREEN; наборы PASSED совпали 1:1, дельта падений объяснена
  полностью (40 vs 39), на вердикт не влияет.
- **R3 (Info)**: `/trace`-схема NodeStateOut не несёт `outcome`
  (Pydantic-дроп аддитивного поля fold-доказательств) — согласуется с
  журналом («outcome — аддитивное поле evidence-вида, UI не менялся,
  N-3»); outcome доступен в fold/projection-evidence (проверено EVD/PRJ2).
- **R4 (Info)**: границы совпадают с заявленными: отложенная математика
  PROGR-23 не исправлялась (карточная шкала сохранена — FLD11/PNL7);
  шаблоны отчёта — AUDIT-7B; v2-envelope/контекстные гейты коррекций —
  AUDIT-2A/6B; durable result_id — AUDIT-6B/7A.

## 9. Регрессионный контур и границы сертификации

- Оракул исполнителя 48/48; адресные 13 сюит 508/17 skipped — 0 дельта;
  полный tests/api+integration 1746/3/18 (средовой класс вне контура,
  арифметика с базой 1A сходится точно).
- Продуктовые файлы после мутационной кампании md5 == HEAD побайтово
  (node_status 59bd8b8c…, trace_hook fd544977…); py_compile/импорт OK;
  все артефакты сертификации untracked; UI не затронут.
- Сертифицируется реализация задачи AUDIT-4 на коммите 0af1ea5
  (продуктовый код 3322e4a идентичен). Live-PostgreSQL вне дельты
  задачи (хранилища/миграции не тронуты — паритет хранилищ
  сертифицирован в 6A/5B/1A и не менялся); production render.com/
  Vercel и браузерные потоки — вне периметра; H29/H30 — вне периметра.

## 10. Вердикт: PASSED

Ядро приёмки AUDIT-4 подтверждено независимо на своих данных: исход
коррекции выводится ЕДИНСТВЕННОЙ проекцией фактов результата и честен
на всех формах фактов/не-фактов (clean preview не фабрикует «Найдены
нарушения», no-op не удостоверяет устранение, half-pair/мусор — честный
unknown); статус/reason/бейдж — из исхода и фактов того же события
(P16: счётчик следует за reason-событием, бейдж очищается без фактов;
P15: невалидный статус — аномалия целиком вне decision details с
нетронутым касанием; канонические тексты сохранены, честные тексты не
претендуют на качество); специальный исход выбросов (карточная шкала
C5) сохранён и приоритетен при валидном payload.status; параметры
результата (method/mode) входят в ключ dedupe (смена метода при равной
картине — новый факт, refetch — нет, легаси самозаживляется);
evidence аддитивно несёт outcome; паритет батч/инкремент и 5B-инвариант
snapshot+tail сохранены на коррекционных потоках. RED обеих сторон
воспроизведён (39/8 исполнителя — с полным объяснением дельты 40/39;
42/8 своих с 8 регресс-пинами); базлайны совпали (48/48, адресные — 0
дельта, полный 1746/3/18 со средовым классом); 50/50 своих оракулов;
13/13 своих мутантов убиты (12 обоими каналами, CM-10 — оракулом после
закрытия им же обнаруженного гэпа покрытия), контроль выжил.
Противоречий «код vs контракт v0.8-4A §18» не найдено.

**Deliverable:** ZIP cisstat-prograudit4-certification.zip → открытый
контейнер сессии (download): docs/cert_prograudit4_2026-10-12.md,
scripts/prograudit4cert_oracles.py (+ results .txt),
scripts/prograudit4cert_red_repro.txt,
scripts/prograudit4cert_mutations.py (+ _mutation_results.txt),
worklog/worklog9.md. Без commit/push (AGENTS.md).
