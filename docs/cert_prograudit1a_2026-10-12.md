# Акт независимой сертификации PROGR-AUDIT-1A-CERT (2026-10-12)

**Задача:** plan_progress_audit.md §9, AUDIT-1a — сброс и восстановление
цели/происхождения: единый effective-target reducer, согласованная пара
target/source в run-метаданных (миграция 0003), restore пары без
повторного авто-выбора (коммит 5364d41 поверх 09e312f).
**Аудитор:** независимая сессия (PROGR-AUDIT-1A-CERT). Правила AGENTS.md
соблюдены: commit/push НЕ выполнялись; продуктовый код и тесты
репозитория не изменялись — только артефакты аудита (все untracked;
все пять затронутых мутационной кампанией продуктовых файлов после
проб md5 == HEAD побайтово, diff-контроль git status: только untracked
артефакты + журнальная запись онбординга).
**Постановка тимлида:** «честно сертифицируй PROGR-AUDIT-1A.
Спроектируй и реализуй данную Сертификацию. Используй мутантов на своих
мутантах, оракулов на своих данных».
**Окружение:** Python 3.12.15, pandas 2.2.3, statsmodels 0.15.0
(подъём с 0.14.5 по полю requirements.txt), fakeredis 2.34.1, FastAPI
0.128.0, pytest 9.0.2; pgserver + psycopg 3.3.6 — живой PostgreSQL-
контур; лёгкая модельная группа R6 (arch/ruptures/statsforecast/
prophet/PyWavelets/pandera) — `apps.api.main` импортируется. Нейро-
группа не установлена: её отсутствие в 1A-контуре не участвует, а 3
средовых падения модельного класса документированы ниже (§2).
**База аудита:** main@5364d41 (HEAD = коммит задачи; предыдущий
09e312f — принятая PROGR-AUDIT-5B; синхронизация по прямому указанию
тимлида; локальный конфликт журнала разрешён сохранением обеих записей
— онбординг ONBOARD-2026-10-12 и upstream-запись PROGR-AUDIT-1A).

---

## 1. Сверка реализации с кодовой базой (5364d41)

Все точки карточки §9 плана и контракта v0.7-1A (§17) на месте:

- `app/core/effective_target.py` (НОВЫЙ, лист app/core) — ЕДИНСТВЕННЫЙ
  редьюсер `effective_target(events) → EffectiveTarget{target, origin,
  source_event_id}` + `resolved` (property по source_event_id):
  различение «фактов нет» (resolved=False, хранимое не трогается) и
  «сброс» (resolved=True, очистить). Правила: непустая строка — выбор;
  пустая строка — legacy-сброс (канон PROGR-15-B); нестроковый target —
  НЕ факт; `target_column_cleared` — сброс пары (origin=None, НЕ
  "user"); прочее — пропуск. `normalize_target_origin`: "auto"/"user"
  — канон; None/"" — "user" (legacy PROGR-25-A у ВЫБОРА); мусор —
  None (unknown, спека §8.2). Ленивый импорт event_to_dict (разрыв
  цикла node_status→effective_target).
- `app/core/mentor_rules.py` — тройка `_target_confirmed`/
  `_target_origin`/`_phase_event_text_facts` — делегирование редьюсеру,
  собственные проходы сняты; семантика уточнена (мусорный source →
  None; пустая строка → сброс — паритет).
- `app/core/node_status.py` — reason-марка «(авто)» через
  `normalize_target_origin` (единая нормализация; прежнее поведение для
  валидного корпуса сохранено).
- `apps/api/research_runs.py` — `ResearchRun.target_column_source`
  (аддитивный Optional; to_dict — ключ ВСЕГДА в словаре — целевая пара,
  None осознанное значение; from_dict — щит типов: нестроковый → None);
  `record_run_event` — ветки цели через `effective_target((event,))`
  при `state.resolved`; `MIGRATION_STATEMENTS_0003` + `MIGRATION_FILES`
  (+файл-дубль); `_RUN_COLUMNS`/`_UPSERT_RUN_SQL` — 12 колонок, пара
  пишется НАПРЯМУЮ (`target_column_source = EXCLUDED.…` — НЕ COALESCE,
  parity target_column); `_run_from_row` — индекс 11.
- `apps/api/migrations/0003_audit1a_target_source.sql` (НОВЫЙ) —
  `ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS target_column_source
  TEXT`; NULL — честное отсутствие (сброс/повреждение/legacy).
- `apps/api/routers/progress.py` — `restore_run`: пара (target, origin)
  из редьюсера над ПОЛНЫМ ledger (`eff.resolved` → пара редьюсера, иначе
  fallback метаданных); применимость цели к raw — ЕДИННЫЙ примитив
  `numeric_columns` singleton-правила (импорт `target_column_rule`, без
  второй pandas-реализации); `session.target_column_source =
  restore_origin` — парная запись; повторный авто-выбор не выполняется;
  `RestoreResponse.target_column_source` — аддитивно (N-3).
- `tests/api/test_progress_audit_1a.py` (НОВЫЙ, 36 тестов) — оракул
  исполнителя; `tests/api/test_research_runs_postgres.py` — versioned-
  каталог миграций 0001+0002+0003 + round-trip пары на живом PG.

Периметр коммита — 11 файлов; UI (.ts/.tsx) не затронут — jest/tsc вне
периметра (паттерн PROGR-19/20/21/24-C).

## 2. Независимая верификация базлайнов (1:1 с журналом)

- Оракул исполнителя `tests/api/test_progress_audit_1a.py`:
  **36/36 passed** — заявление журнала 1:1.
- Postgres-сюита `tests/api/test_research_runs_postgres.py` на свежем
  живом pgserver: **18/18 passed** (включая round-trip пары
  auto-durable / прямая запись None / legacy NULL) — 1:1.
- Адресные сюиты, группа 1 (25a/25c/25d/H1/target_column/
  research_runs/trace_events/node_status_engine/mentor_rules):
  **352 passed** — 1:1 с журналом.
- Адресные сюиты, группы 2/3 журнала (panel/5b/6a/C/S/trace_hook/
  session_store/run_report + tests/integration; 13a-c/16/17/18/23):
  **336 passed / 17 skipped + 112 passed** — ЗАЯВЛЕННАЯ ГРАНУЛЯЦИЯ
  (448/17 и 282) выбранным составом не воспроизводится 1:1: суммарно
  те же названия файлов дают 448 (=336+112) при объединении двух групп,
  а «282» не выводится из названного состава (фактически в файлах
  13a-c/16/17/18/23 — 112 тестов). ДЕЛЬТА ПАДЕНИЙ 0 в обоих вариантах
  состава — на вердикт не влияет; замечание о неточности описания
  состава — R1 (§7).
- Полный регресс tests/api + tests/integration: **1698 passed / 3
  failed / 18 skipped**. Все 3 failed — задокументированный средовой
  класс (production dispatch моделей вне контура «Прогресса»):
  test_modeling_workflow ×1, test_models_backtest_neural_capacity ×1,
  test_models_candidates ×1; воспроизведены на чистом worktree базы
  09e312f (3 failed / 83 passed на тех же файлах) — дельта к базлайну
  0. Журнальные «19 failed» (sandbox без лёгкой группы) в R6-среде
  сняты до 3 (16 падений test_forecasting_session — параметрическая
  симуляция на statsmodels 0.14.x — устранены установкой 0.15.0).
- RED-протокол исполнителя воспроизведён на worktree 09e312f (с копией
  их нового тест-файла — тот же метод, что у исполнителя): **32 failed
  / 4 passed** — 1:1 с scripts/prograudit1a_red_protocol.txt (14
  ImportError редьюсера, 5 AttributeError origin, restore-группа
  KeyError/поведение F03, 4 PASSED — регресс-пины).
- Сборка: импорт `apps.api.main` OK; py_compile всех пяти продуктовых
  файлов задачи OK; миграция 0003 идемпотентна на живой БД (см. PG-гр.).

## 3. RED-воспроизведение СВОИХ оракулов на 09e312f

git-worktree 09e312f, прогон scripts/prograudit1acert_oracles.py:
**54 FAIL / 9 PASS (EXIT=1)** — протокол scripts/prograudit1acert_red_repro.txt.
54 отказа — ожидаемые дефекты базы: ImportError `effective_target`
(редьюсера не существует), AttributeError
`ResearchRun.target_column_source` (origin в run-метаданных не
существовал), TypeError/форма словаря (пара отсутствует), поведенческие
отказы restore-группы (F03). 9 PASS — регресс-пины УЖЕ работавшего
поведения, обязанные остаться зелёными и на HEAD (сброс-согласованность
H1: CLR2-CLR6/CYC2; маркировка/факты, не зависящие от 1A-семантики:
NRK1/NRK2/MEN5). Ложно-зелёных среди контрактных групп нет: ни один
оракул групп NRM/RED/RUN/RST/PG не проходит на базе.

## 4. Оракулы на СВОИХ данных — scripts/prograudit1acert_oracles.py: 63/63 PASS (EXIT=0)

Свои данные сертификатора, дизъюнктные данным исполнителя (их корпуса
rain/snow, run-фикстуры TestEffectiveTargetReducer): CSV-корпуса
agro_nov.csv (date/soy — одна числовая), two_channels.csv (date/soy/
maize — две), кириллица.csv (date/продажи), texty.csv (date/city/soy —
строковая ПРИСУТСТВУЮЩАЯ колонка); свои run_id (RUN-C1A-*), свои
payload-значения (в т.ч. кириллическая колонка «продажи», source="bot"/
"cron"), свои event_id (фабричные), живой pgserver с ЧИСТОЙ схемой на
каждый PG-оракул.

- **NRM (8)**: normalize_target_origin — auto/user канон; None/"" →
  user (legacy-контракт PROGR-25-A); мусор "bot"/123/"AUTO" (регистр)/
  " user" (пробел) → None: повреждённое происхождение НЕ фабрикует
  пользователя (спека §8.2); чувствительность канона к регистру/пробелам.
- **RED (14)**: редьюсер на своих корпусах — выбор auto/legacy-user/
  повреждённый-source (origin None, target сохранён); cleared сбрасывает
  ПАРУ и source_event_id = cleared; пустая строка — сброс (канон
  PROGR-15-B); мусор 123 после выбора состояние не трогает; пустой
  корпус unresolved; шум не сбрасывает; last-wins в ОБОИХ порядках;
  TraceEvent == dict; мусорный корпус деградирует честно; source_event_id
  = последний факт; cleared→пустая строка (оба сбросы, last = строка);
  кириллический выбор — полноценный факт.
- **MEN (5)**: тройка Наставника на СВОЁМ смешанном корпусе
  == редьюсеру (confirmed/origin/фаз-факты); различители: мусорный
  source → _target_origin=None; факт колонки сохранён в тексте при
  unknown-origin (ловит CM-12).
- **RUN (8)**: mirror record_run_event — пара (soy, auto);
  (maize, user) без source; cleared → (None, None); мусор после выбора
  метаданные не трогает (не «123»); пустая строка — парный сброс;
  round-trip auto/user/None; from_dict мусор → None (щит, не str);
  to_dict ВСЕГДА несёт ключ пары (форма §17.2).
- **RST (9)**: restore через живой API — auto-пара в ответе/сессии/
  селекторе/шапке /trace при ровно ОДНОМ выборе (второго нет); reset→
  restore — без воскрешения и БЕЗ авто-пере-выбора (raw с единственной
  числовой — пере-выбор дал бы её); demo→manual→user; ledger авторитетен
  над stale-метаданными (цель «воскресла» вне событий — не восстановится);
  legacy-fallback метаданных при корпусе без фактов цели (origin None);
  ghost-цель — пара пуста; **нечисловая ПРИСУТСТВУЮЩАЯ цель (строковая
  city) — пара пуста** (различитель числовой проверки — RST7);
  два числовых — честная неоднозначность; шапка /trace — та же пара.
- **CLR (6)**: сброс-согласованность P03-corrected — сессия+run парная
  очистка, ровно ОДИН cleared с честным payload (reset_reason/
  before_target); Наставник НЕ утверждает выбор и просит подтвердить
  (свой метод наблюдения — без привязки к шаблону исполнителя); reason
  снят; preview не сбрасывает; 422 на пустой POST (сброс через выбор
  невозможен); заголовок отчёта не называет цель.
- **NRK (2)**: reason-марка — «(авто)» при auto, её отсутствие при
  manual (ловит CM-11).
- **CYC (3)**: полный цикл auto→reset→manual на своём двухканальном
  корпусе (сессия == run после цикла); manual→reset — парная очистка,
  выбор сохранён исторически (1 choice + 1 cleared, before_target
  честен); кириллический корпус — полный честный цикл.
- **PG (8)**: живой pgserver — паритет record_run_event (пара durable
  auto); ПРЯМАЯ запись пары (None стирает auto — НЕ COALESCE);
  legacy-строка NULL — честное отсутствие; DDL-эквивалентность файла
  0003 == MIGRATION_STATEMENTS_0003 (собственный нормализующий разбор);
  каталог MIGRATION_FILES (0001+0002+0003); legacy-корпус (0001+0002+
  своя строка) → применение ФАЙЛА 0003 → колонка NULL, читаем;
  повторное применение файла — no-op (одна колонка); паритет Memory/PG
  полного mirror-потока (choice+cleared → (None, None) на ОБОИХ).

## 5. Мутационная кампания СВОИХ мутантов — 12/12 KILLED, 0 SURVIVED; контроль выжил

scripts/prograudit1acert_mutations.py. Набор ДИЗЪЮНКТЕН по точкам/
классам от проб исполнителя (мутационная кампания в 1A не велась — их
RED-протокол) и от CM-1..9 камеры 6A-CERT (там ledger/sequence/receipt/
CAS, здесь семантика choice/reset/origin/пара/restore/марка/факты).
Дисциплина: backup → единственный якорь (PATTERN-MISS = аварийный
останов) → патч → оба канала → побайтовое восстановление → md5 после
каждого мутанта и в finally: **md5 всех 5 файлов == HEAD**. Каналы:
oracle (63 своих) + repo (36 тестов исполнителя).

| Мутант | Класс / точка | Oracle | Repo | Вердикт |
|---|---|---|---|---|
| CM-0 | no-op контроль | EXIT=0 | 36 passed | SURVIVED (харнесс достоверен) |
| CM-1 | normalize: мусор→"user" (фабрика origin) | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-2 | normalize: None/""→None (legacy сломан) | EXIT=1 | 6 failed | KILLED-BOTH |
| CM-3 | reducer: cleared не сбрасывает | EXIT=1 | 9 failed | KILLED-BOTH |
| CM-4 | reducer: пустая строка не факт | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-5 | reducer: фабрика str(raw) из мусора | EXIT=1 | 2 failed | KILLED-BOTH |
| CM-6 | record_run_event: resolved-щит снят | EXIT=1 | 1 failed | KILLED-BOTH |
| CM-7 | PG upsert: пара без EXCLUDED (COALESCE-стиль) | EXIT=1 | 36 passed | KILLED-ORACLE-ONLY |
| CM-8 | restore: редьюсер игнорируется (if False) | EXIT=1 | 2 failed | KILLED-BOTH |
| CM-9 | restore: числовая проверка снята | EXIT=1 | 36 passed | KILLED-ORACLE-ONLY |
| CM-10 | restore: origin в сессию не пишется | EXIT=1 | 3 failed | KILLED-BOTH |
| CM-11 | node_status: инверсия марки «(авто)» | EXIT=1 | 36 passed | KILLED-ORACLE-ONLY |
| CM-12 | mentor: текст-условие на origin | EXIT=1 | 36 passed | KILLED-ORACLE-ONLY |

## 6. Эволюция оракулов (открытая фиксация, прецедент PROGR-24-C-CERT R4 / 6A §6)

Первая редакция (63 оракула) на HEAD дала 3 FAIL — все три ДЕФЕКТЫ
ХАРНЕССА сертификатора, не продукта: (1) CLR2 — завязка на точечный
шаблон-подстроку исполнителя («Подтвердите целевой признак» вместо
своего метода наблюдения честности текста: НЕ утверждает выбор + просит
подтвердить; шаблон зависит от факта подтверждения структуры —
исполнитель сеял его фикстурой); (2) PG1/PG8 — `record_run_event` пишет
в СИНГЛТОН хранилища: PG-оракул требовал переключения направления
синглтона на живой DSN (паттерн test_research_runs_postgres), иначе
проверялся Memory. После усиления — 63/63. В первой редакции
мутационного харнесса была ИНВЕРСИЯ вердиктов (survived/killed) —
обнаружена контрольно-обратной проверкой CM-0 (HARNESS-FAIL), исправлена
до основной кампании; финальная кампания честная (CM-0 SURVIVED).
Вторая редакция RED-прогона на базе подтверждает честность RED: 54/9.

## 7. Находки

- **F-1A1 (РЕКОМЕНДАЦИЯ, покрытие repo)**: 4 из 12 мутантов (CM-7/9/
  11/12) пережили repo-канал — сюита исполнителя 1A не пинит: (а)
  поведение пары в Postgres вообще (fixture Memory-only: прямая запись
  None не COALESCE); (б) восстановление нечисловой ПРИСУТСТВУЮЩЕЙ
  колонки (их RST-отрицательный кейс — только ghost, отсутствующая);
  (в) reason-марку «(авто)» (успешно пинится смежными сюитами
  PROGR-25-C, но не 1A); (г) фаз-факты при unknown-origin. Все 4
  прикрыты оракулами сертификации (PG2, RST7, NRK1/2, MEN5); перенос
  пинов в repo-сюиты рекомендован следующей тестовой задачей (по
  прецеденту F-6A1).
- **R1 (наблюдение, журнал)**: грануляция адресных групп регресса в
  журнале задачи (352/448+17/282) не воспроизводится 1:1 по названному
  составу (см. §2) — дельта падений 0 при любой грануляции, на вердикт
  не влияет; суммарный полный прогон совпадает по классу.
- **R2 (наблюдение, среда)**: журнальный базлайн «19 failed (sandbox)»
  снят R6-средой до 3 failed модельного класса (оба варианта
  воспроизводимы на чистой базе — дельта 0; класс вне контура
  «Прогресса»).
- **R3 (Info)**: границы совпадают с заявленными: raw restore-семантика
  и historical/validity — AUDIT-8; шаблоны фактов отчёта («(авто)» в
  документе) — AUDIT-7B; payload ручного маршрута остаётся legacy
  {target_column} (PROGR-25-A); restore выполняет НОЛЬ повторных
  авто-выборов — подтверждено RST-группой.

## 8. Регрессионный контур и границы сертификации

- Оракул исполнителя 36/36; postgres-сюита 18/18 (живой pgserver);
  адресные группы — без падений; полный tests/api+integration
  1698/3/18 (средовой класс воспроизведён на базе, дельта 0).
- Продуктовые файлы после мутационной кампании md5 == HEAD побайтово;
  все артефакты сертификации untracked; UI не затронут (jest/tsc вне
  периметра).
- Сертифицируется реализация задачи AUDIT-1a на коммите 5364d41.
  Live-PostgreSQL — временный pgserver-инстанс (паттерн Донастройка_2
  п.1); production Redis/Postgres render.com, Vercel-деплой и браузерные
  потоки — вне периметра. Проверки H29/H30 (эксплуатационные) — вне
  периметра настоящей сертификации.

## 9. Вердикт: PASSED

Ядро приёмки AUDIT-1a подтверждено независимо на своих данных: единый
effective-target reducer существует в единственной точке и его
семантика честна (выбор/legacy-сброс/повреждённый-unknown/cleared/
мусор-не-факт, last-wins по данному порядку, resolved различает «нет
фактов» и «сброс»); все четыре потребителя делегируют (Наставник —
тройкой, reason — единой нормализацией origin, run-метаданные —
инкрементальным mirror с resolved-щитом, restore — replay полного
ledger с fallback метаданных и применимостью цели по единому числовому
примитиву); пара target/source durable на ОБОИХ хранилищах с паритетом
и прямой записью (сброс пары не COALESCE-фабрика); restore возвращает
СОГЛАСОВАННУЮ пару без потери origin (F03/P04 закрыты) и без второго
авто-выбора; миграция 0003 аддитивна, эквивалентна файлу и применима к
legacy-корпусу (идемпотентна). RED обеих сторон воспроизведён 1:1
(32/4 исполнителя; 54/9 своих с 9 регресс-пинами); базлайны совпали
(36/36, 18/18, адресные — 0 дельта, полный 1698/3/18 со средовым
классом на базе); 63/63 оракулов; 12/12 своих мутантов убиты
(8 — обоими каналами, 4 — оракулом с задокументированными repo-гэпами
F-1A1), контроль выжил. Противоречий «код vs контракт v0.7-1A §17» не
найдено.

**Deliverable:** ZIP cisstat-prograudit1a-certification.zip → открытый
контейнер сессии (download): docs/cert_prograudit1a_2026-10-12.md,
scripts/prograudit1acert_oracles.py (+ results .txt),
scripts/prograudit1acert_red_repro.txt,
scripts/prograudit1acert_mutations.py (+ _mutation_results.txt),
worklog/worklog9.md. Без commit/push (AGENTS.md).
