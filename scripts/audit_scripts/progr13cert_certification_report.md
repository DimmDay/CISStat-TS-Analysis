# Сертификационный отчёт PROGR-13-CERT

**Объект:** Tasks PROGR-13-A («Полнота Загрузки: общий реестр 5 остановок, разведение фактов upload_completed/structure_confirmed, контракт POST /v1/progress/upload-stops») и PROGR-13-B («Компактное backend-исправление дефекта 2 + нормализация legacy node_id корпуса слоя 2»).
**База:** main@f607ccc (коммиты 7cb4535 = B, f607ccc = A).
**Сертификатор:** независимый аудитор (Senior-разработчик, вне цепочки реализации).
**Дата:** 2026-10-02.
**Вердикт: PASSED WITH REMARKS** (замечания R-1, R-2 — малые дыры pytest-покрытия, найденные мутационно; R-3 — уточнение учёта RED-прогона; блокеров нет).

---

## 1. Методика и независимость

Сертификация выполнена по четырём независимым контурам, НЕ опирающимся на
тесты разработчика: (1) независимый запуск целевых и полного pytest-сьютов;
(2) верификация TDD RED-claims на базовых коммитах через git worktree;
(3) собственные оракул-проверки на СВОИХ данных (`scripts/progr13cert_oracles.py`,
64 оракула, ожидания закодированы из постановок и spec_progress.md, случайные
данные с фиксированными seed'ами); (4) мутационный прогон на СВОИХ мутантах
(`scripts/progr13cert_mutations.py`, 23 мутанта — точечные правки рабочего кода
в ключевых точках решений задач A/B). Дополнительно: live-репродукция обоих
дефектов штатным скриптом, полный jest, typecheck, build.

## 2. Проверка контрактов по коду (соответствие постановкам)

PROGR-13-B — подтверждено:
- **B1** `app/core/node_status.py::derive_last_active_stage` — фаза = стадия
  последнего УЗЛОВОГО факта решения (гейт resolve_event_status +
  resolve_node_id + is_known_node); stage-level события (node_id=None) фазу
  не двигают; `get_mentor_next_step` и `restore` (progress.py) используют
  её вместо `events[-1].stage`.
- **B2** `apps/api/trace_hook.py` — динамическая паспортная строка развёрнута
  в 4 литеральные (start→upload, validation→validation, exit→eda,
  modeling_entry→modeling, node_id=None, payload stage/snapshot_id/fingerprint);
  STAGE_EVENT_TYPES расширен passport_captured на upload/validation/modeling.
- **B3** LEGACY_NODE_IDS/normalize_legacy_node_id вшиты в resolve_node_id —
  единственную точку вывода узла; трасса-журнал не переписывается (нормализация
  только на чтении).

PROGR-13-A — подтверждено:
- **A1** `shared/pipeline_nodes/upload_stops.json` (5 остановок) — единый
  источник для pipeline_graph (общее fail-closed ядро _load_pipeline_node_defs),
  TsAnalysisUpload.tsx (STOPS из JSON, вшитой список удалён) и progress.ts
  (зеркало + метки из JSON).
- **A3** upload_completed → узел overview (3 строки хука); POST /date-column →
  upload/structure, structure_confirmed (payload date_column); EVENT_NODE_REASON
  «Датасет загружен, превью доступно» (ложь дефекта 1б устранена).
- **A4** PAYLOAD_STATUS_EVENT_TYPES/resolve_event_status (whitelist
  CHECK_STATUS_VALUES, мусор → None); POST /v1/progress/upload-stops —
  fail-closed валидация ДО первой записи (пустая/чужая/битая/неполная карты
  = 422 all-or-nothing), 400 без датасета, 5 событий в каноническом порядке
  реестра, слой 1 + зеркало слоя 2 (record_run_event).
- **A5** run_report: метки из UPLOAD_STOP_DEFS, строки фактов
  structure_confirmed/upload_stop_status без выдуманных фактов; спецификация
  spec_progress.md §2/§4.1 актуализирована.

## 3. Результаты контуров

### 3.1 Целевые и полные pytest-сьюты
- Целевые файлы `test_progress_progr13a.py` (25) + `test_progress_progr13b.py`
  (19) + `test_progress_defects_progr13.py` (8): **52 passed**.
- Полный `tests/api/`: **1282 passed / 1 skipped / 0 failed** (единственный
  skip — Postgres-интеграция без CISSTAT_TEST_PG_DSN; паттерн модуля).
  Claim worklog A «1263 passed + 19 средовых» в среде сертификатора без
  полной зависимости-группы нейро; счётчики сходятся: 1263 + 19 = 1282.
  В полной среде (arch, prophet, tbats, statsforecast, torch+neuralforecast,
  statsmodels 0.15.0, psycopg, sqlalchemy) все 19 «средовых» падений
  воспроизводились как зелёные — падений нет.

### 3.2 Верификация TDD RED-claims (git worktree на базовых коммитах)
- **PROGR-13-A (база 7cb4535):** контракты `test_progress_defects_progr13.py`
  падают РОВНО 5/8 (граф == 5 id; зеркало progress.ts == 5 id;
  upload_completed не красит structure; upload_completed красит overview;
  POST /upload-stops — 404), 3 B-контракта зелёные — **дословное совпадение**
  с claim worklog.
- **PROGR-13-B (база 2d2d05c):** `test_progress_progr13b.py` (коммитнутая
  версия) — **17 failed / 2 passed** (passed: параметр [exit-eda] —
  совпадение со старой динамической строкой; test_mentor_phase_for_legacy_corpus_run
  — регрессионный guard). Claim «16 содержательных + 2 совпадения + 1 guard»
  расходится в учёте на 1 тест — объяснимо миграцией фикстуры карточки в A
  (R-3). Суть RED-claim подтверждена: тесты падают на базе массово и
  диагностично (ImportError новых функций внутри тестов), зелёные на f607ccc.

### 3.3 Оракулы на своих данных — 64/64 PASS
`scripts/progr13cert_oracles.py`, группы: A — property-based нормализация
legacy node_id (идемпотентность 500 проб, ограничение стадией, fuzz 500
«фантомов нет», все 50 канонических id насквозь, история слоя 2 не потеряна);
B — движок статусов (whitelist на 11 видах мусора, last-wins на 200 случайных
хронологиях, «панель == модулю» на 200 случайных снапшотах stopStatus,
фантом-фри на 120 шумовых событиях, полный узел §3, свёртка §12 п.10);
C — фаза Наставника (stage-level/run-level/паспорт не двигают; последний
узловой факт выигрывает; инвариант на 150 случайных хронологиях);
D — HTTP-контракт POST /upload-stops (all-or-nothing с проверкой нуля записей
в слое 1, зеркало слоя 2, канонический порядок, run_id pinning, 400 без
датасета, last-wins с /date-column); E — отчёт §5.4 (30 комбинаций
остановка×статус, отсутствие колонки без выдумок, FALLBACK-реестр);
F — таблица хука (4 литеральные паспортные точки, /date-column, upload→overview,
fail-closed неизвестной точки); G — общий реестр (5 id, порядок степпера,
fail-closed загрузчика на 5 видах порчи, синхронность .tsx/.ts).

### 3.4 Мутационный прогон — 20 KILLED / 2 SURVIVED / 1 контроль
`scripts/progr13cert_mutations.py`: 23 мутанта, целевые срезы сьютов на
мутанта, бэкап/восстановление файла, порог KILLED = падение любого теста.
- Контроль сети M-CTRL (правка докстринга): SURVIVED — как ожидалось (сеть
  не убивает по тексту).
- 20/22 содержательных мутанта KILLED: оба рецидива дефекта 1 (одна остановка;
  зелёная «Структура» против жёлтого модуля), рецидив дефекта 2 (фаза по
  хвосту трассы), снятая нормализация legacy (функция И вызов-сайт),
  cross-stage перезапись, снятый whitelist payload-статусов, выпавшие
  payload-типы, выпавший structure_confirmed, лживая причина upload_completed,
  все 5 снятых fail-closed проверок POST /upload-stops (полная карта, чужие
  узлы, битые статусы, зеркало слоя 2, run_id, 400), мисаттрибуция паспортов
  (validation→eda, node_id в паспортной точке), /date-column→overview,
  обрезка реестра до 1 остановки, снятый fail-closed дубликатов, сырые id
  вместо меток реестра в отчёте §5.4.
- **2 SURVIVED — находки (см. R-1, R-2).**

### 3.5 Live-репродукция, фронтенд, сборка
- `scripts/progr13_repro_defects.py`: ДЕФЕКТ 1 ИСПРАВЛЕН — панель 5 остановок
  (overview/chart/distribution done, structure/quality warning, fold=attention
  3/5), «Панель == модулю: True»; ДЕФЕКТ 2 закрыт — оба сценария (с паспортом
  и без) дают last_active_stage='upload', phase_text «Загрузка».
- Jest: **148 сюит / 1781 тестов, все зелёные** (совпадает с claim).
- typecheck:all — чисто (exit 0); build:all — оба приложения
  «Compiled successfully».

## 4. Замечания

- **R-1 (Minor, тест-покрытие):** мутант M-B1-2 выжил — в
  `derive_last_active_stage` снятие гейта resolve_event_status (фазу двигают
  узловые события с НЕразрешимым статусом: неизвестный тип при известном
  node_id, upload_stop_status с мусорным payload) не ловится ни одним
  pytest-тестом. Не эквивалентный мутант: выход фазы меняется. В проде риск
  мал (статусы валидируются сервером), но контракт «только факты решения
  двигают фазу» заслуживает прямого теста. Рекомендация: добавить кейс в
  test_progress_progr13b (отдельным тикетом, не в сертификате).
- **R-2 (Minor, тест-покрытие):** мутант M-A5-2 выжил — в
  `run_report._structure_confirmed_line` подмена «отсутствующая колонка →
  честная строка без выдумок» на «выдуманный unknown_column» не ловится
  pytest (контракт покрыт только оракулом E3 сертификатора — вне сьюта).
  Рекомендация: добавить тест в test_run_report.py.
- **R-3 (Info, учёт):** на базе 2d2d05c коммитнутая версия B-файла даёт
  17 failed / 2 passed против claim «16 содержательных + 2 совпадения +
  1 guard» (18). Расхождение в 1 тест объясняется тем, что RED-версия файла
  не коммитилась, а после A мигрировала 1 фикстура
  (test_panel_keeps_history_for_legacy_layer1_corpus). Суть RED-claim
  (массовый диагностичный RED на базе → GREEN на f607ccc) подтверждена;
  на 7cb4535 A-контракты 5/5 — дословное совпадение.
- **R-4 (Info, среда):** «19 предсуществующих средовых» падений в worklog —
  артефакт неполной зависимости-среды сертификатора задачи (нет
  arch/prophet/tbats/statsforecast/neural-группы; statsmodels 0.14.5). В
  полной среде те же тесты зелёные; счётчики 1263+19=1282 сходятся с полным
  прогоном 0 failed. Это не замечание к задачам A/B.
- **R-5 (Info, граница, перенесена из B):** stage_for_run_level_event
  (research_runs.py) по-прежнему штампует run_paused/resumed/checkpoint по
  хвосту трассы — осознанная граница компактной B (кандидат на отдельную
  задачу), на контракты A/B не влияет.

## 5. Артефакты сертификации

- `scripts/progr13cert_oracles.py` — 64 оракула на своих данных (NEW).
- `scripts/progr13cert_mutations.py` — 23 мутанта (NEW).
- `docs/progr13cert_certification_report.md` — этот отчёт (NEW).
- `worklog/worklog8.md` — запись PROGR-13-CERT (CHANGED).
- Запуск: `python3 scripts/progr13cert_oracles.py` (exit 0);
  `python3 scripts/progr13cert_mutations.py` (exit 0 = все содержательные
  KILLED + контроль SURVIVED; текущий прогон даёт 2 находки R-1/R-2 —
  скрипт возвращает 1 по дизайну «расхождений с ожиданием»).
