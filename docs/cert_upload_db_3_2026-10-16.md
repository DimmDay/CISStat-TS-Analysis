# Акт независимой сертификации UPLOAD-DB-3 (2026-10-16)
## Фаза A «коннекторное ядро», цикл 3: embedded-режим реестра — SQLite (.db/.sqlite) и DuckDB (.db/.duckdb) по пути к файлу + прямой DuckDB-SELECT по Parquet/CSV; обе встроенные СУБД строго read-only; сквозной Test→Load зелёный без сервисов (коммит 88a5459)

Дата: 2026-10-16. Аудитор: независимый сертификатор (Senior-разработчик
платформы). База аудита: `main@6cff336` (HEAD; код фазы A — коммит
`88a5459`; между 88a5459 и 6cff336 код `app/data/*` и `tests/unit/*`
ИДЕНТИЧЕН побайтово — `git diff 88a5459..6cff336 -- app/ tests/unit/`
пуст, промежуточные коммиты 1531c7d (усиление тестов tests/api) и
6cff336 (UPLOAD-DB-4: apps/api) фазу A не трогают — проверено диффом).
Рабочее дерево чистое в течение всего аудита; код и тесты репозитория
НЕ изменялись — только артефакты сертификации (префикс `dbcert_`).
Постановка аудита: «провести честную сертификацию задачи Task ID:
UPLOAD-DB-3 (2026-10-16) — Фаза A «коннекторное ядро». Используй
мутантов на своих мутантах и оракулов на своих данных» — по практике
проекта (прецеденты DATASET-VIEW-EDITOR-1-CERT, PROGR-25-CERT):
сверка фактов worklog10.md с кодовой базой, GREEN/RED-воспроизведение,
НЕЗАВИСИМЫЕ оракулы на СВОИХ данных, НЕЗАВИСИМЫЙ мутационный прогон на
СВОИХ мутантах с контролем самого харнесса (no-op-мутант «мутант на
мутанте»). AGENTS.md соблюдены: commit/push НЕ выполнялись.

---

## 1. Предмет сертификации (контракты UPLOAD-DB-3 по worklog10.md и плану)

- **C1 (path-режим реестра)**: `db_connectors.open_embedded(spec, path)` —
  валидация пути `_validate_embedded_path` (непустой; расширение из
  `path_extensions` записи с честным перечислением; `os.path.isfile` →
  FileNotFoundError; expanduser), SQLite → URI
  `sqlite:///file:<квотиованный путь>?mode=ro&uri=true`, DuckDB
  .db/.duckdb → `duckdb:///<путь>` + `connect_args read_only=True`,
  DuckDB .parquet/.csv → `duckdb:///:memory:`.
- **C2 (честный «Тест»)**: `probe_connection(spec, conn, path=...)` для
  Parquet/CSV исполняет прямое чтение ПЕРВОЙ строки самого файла
  (`SELECT * FROM '<path>' LIMIT 1`, эскейп одинарных кавычек) —
  «Тест» проверяет читаемость источника, а не только загрузку движка.
- **C3 (строго read-only)**: обе встроенные СУБД открываются только на
  чтение (SQLite mode=ro на уровне файла; DuckDB connect read_only=True).
- **C4 (file_loader)**: embedded-ветка `init_db_connection(..., path=...)`
  — open_embedded → probe_connection(path); ImportError/ValueError/
  FileNotFoundError пробрасываются как есть (дружественные), остальное →
  ConnectionError; host/port/креды игнорируются и задокументированы.
- **C5 (пины зависимостей)**: requirements.txt — `duckdb>=1.0.0` +
  `duckdb-engine>=0.13.0` (RP3 закрыт RED-пробами совместимости с
  sqlalchemy>=2.0).
- **C6 (DoD)**: сквозной Test→Load на SQLite и DuckDB зелёный в CI без
  внешних сервисов; guard действует на embedded-дорожке.
- **C7 (средовой факт)**: DuckDB не допускает открытие одного файла с
  разными конфигурациями в одном процессе; платформа открывает
  встроенные СУБД ТОЛЬКО read-only → конфликт недостижим в продукте;
  тесты отпускают пулы (dispose) перед read_only-открытием.

## 2. Сверка реализации с кодовой базой (все точки на месте, 88a5459)

`app/data/db_connectors.py`: `open_embedded` (:374-403) — C1 полностью
(URI-ветки, quote с safe="/", in-memory для query_file_extensions);
`_validate_embedded_path` (:406-423) — непустой/расширение/isfile/
expanduser, честные сообщения с перечислением ожидаемых расширений;
`probe_connection` (:426-454) — C2 (file_sql с LIMIT 1 и
`replace("'", "''")`); реестр: sqlite `.db/.sqlite`, duckdb
`.db/.duckdb/.parquet/.csv` + `query_file_extensions=(".parquet",".csv")`,
default_port=None у обеих. `app/data/file_loader.py`: embedded-ветка
(:118-127) — C4 (перечень исключений и обёртка ConnectionError ровно как
задекларировано; docstring задокументировал игнорирование host/port/
кредов). `requirements.txt`: пины C5 на месте (psycopg[binary]/
psycopg2-binary/duckdb/duckdb-engine). D1-фикс ядра: контрольные запросы
реестра — готовые text()-объекты; `tests/unit/test_db_connection.py`
VERSIONED — пин `_assert_test_query_is_textclause` (sent.text ==
"SELECT 1"). Задокументированный остаток D1 в legacy-UI (app.py:520,
`conn.execute("SELECT version()")` сырой строкой) подтверждён — скоуп
UPLOAD-DB-10, не фазы A; legacy-обёртка app.py:388-395 (6 позиционных
аргументов) сигнатурно совместима с новой функцией (ssl/path имеют
дефолты). Модули реестра не импортируют streamlit (Правило 14), import-
безопасность без sqlalchemy реализована try/except-заглушками.

## 3. Окружение и независимая верификация сертификатора

Окружение: контейнер сессии; venv `/home/z/.venv`; доустановка
duckdb 1.5.6 + duckdb-engine (заявленные в worklog версии совпали:
sqlalchemy 2.1.4, duckdb 1.5.6), arch/PyWavelets/pandera (известный
средовой класс полного юнит-набора; pyarrow в контейнере нет — корпус
Parquet собирался duckdb COPY, без новых зависимостей).

- **GREEN repo-тестов**: test_db_embedded.py — **17/17**; полный корпус
  фазы A (connectors 36 + guard 72 + embedded 17 + db_connection 5 +
  file_loader 7) — **137/137**; смежный контур consumers file_loader
  (test_upload.py + test_dataset_rows.py + test_dataset_derived_columns.py
  + test_progress_progr17.py) — **35/35** — в точности заявления worklog.
- **Полный tests/unit**: 1650 passed / 45 failed / 24 skipped / 3 errors
  — ПОБАЙТОВАЯ сверка ID падений (FAILED/ERROR-строки) с чистой базой
  68fd65d: **ИДЕНТИЧНО 48/48**, ДЕЛЬТА 0; прирост passed ровно **+125**
  = 36+72+17 новых тестов — сходится с заявлением worklog 1:1 (средовой
  класс падений: statsmodels 0.14.5 против пина 0.15, snapshot-ambr,
  нейро-каталог, forecasting/garch — вне периметра).
- **RED-воспроизведение (scripts/dbcert_red_repro.py/.txt)**:
  (1) все 5 файлов фазы A (db_connectors.py, db_guard.py,
  test_db_embedded.py, test_db_connectors.py, test_db_guard.py)
  ОТСУТСТВУЮТ на 68fd65d — collection честно красный;
  (2) D1-дефект живьём: legacy file_loader@68fd65d (изолированная
  песочница через git show, рабочее дерево не тронуто) с реальным
  движком — `conn.execute("SELECT 1")` сырой строкой → **ObjectNotExecutableError:
  Not an executable object: 'SELECT 1'** (упакован legacy-обёрткой в
  ConnectionError без `from e` — источник в __context__);
  (3) композиция RED полная: на 68fd65d ветки embedded НЕ СУЩЕСТВОВАЛО —
  'SQLite'/'DuckDB' уходили в else → `logger.warning('Unsupported
  database type')` → return None. Падают ровно killer'ы контрактов
  задачи.

## 4. Оракулы сертификатора на СВОИХ данных — 18/18 PASS

Корпус ДИЗЪЮНКТЕН repo-тестам (scripts/dbcert_oracles.py, протокол
.txt): SQLite «station telemetry.sqlite» (ПРОБЕЛ в имени файла! таблица
sensor_readings, 20 строк reading_id/station/temperature/humidity),
DuckDB «cargo_flow.duckdb» (7 строк, кириллические регионы), CSV
«макро_ряд 2024.csv» (юникод+пробел в пути, 2 пропуска, 8 строк),
Parquet «wind_probe.parquet» (15 строк wind_speed/direction, собран
duckdb COPY), битые источники: garbage.csv (бинарный мусор), later_bad.csv
(28 КБ валидных строк + битый UTF-8 В ГЛУБИНЕ — за 20КБ-снапшотом
сниффера), garbage.duckdb; фейковый HOME для expanduser-оракула.

O01 (реестр: 6 записей, path-метаданные, корпус покрыт расширениями);
O02 (SQLite Test→Load 20 строк, точечные значения, СУММА температур
сошлась, **md5 файла не изменился**); O03 (SQLite строго read-only:
INSERT/CREATE → OperationalError, md5 цел); O04 (**SQLite путь с
ПРОБЕЛОМ** — repo покрывает пробел только для DuckDB/CSV); O05 (DuckDB
файл: Test→Load 7 строк, INSERT отклонён, md5 цел); O06 (CSV юникод+
пробел+пропуски: 8 строк, NaN сохранены); O07 (Parquet: 15 строк, точные
float); O08 (битый CSV → ConnectionError на фазе «Тест» — probe честно
читает файл); O09 (мусорный UTF-8 в глубине 28КБ-файла: DuckDB-сниффер
сканирует весь файл при детекции схемы → «Тест» падает ещё до загрузки
— сильнее проверки первой строки); O10 (битый .duckdb → ConnectionError);
O11 (матрица валидации пути: пустой/без расширения/.txt-для-duckdb/
.csv-для-sqlite/отсутствующий/каталог-с-расширением.db — все честно
отклонены); O11b (**expanduser: путь `~/dbcert_home.db` при фейковом
HOME** резолвится и читается); O12 (guard на embedded: DELETE/UPDATE/
DROP/INSERT/CREATE/ALTER/мультистейтмент — 7/7 DbQueryRejected; лимит
5 из 7 строк → 5 + truncated=True честный; лимит 50 → 7 без обрезки);
O12b (env-капа UPLOAD_DB_ROW_LIMIT=3 сильнее параметра 50 → 3 строки);
O13 (chunksize=7 по 20 строкам: 20 строк, сумма точная); O14 (импорт-
безопасность в изолированном процессе с sys.modules-заглушками: реестр
читаем, 6 записей, open_embedded → ImportError с pip-подсказкой
«duckdb duckdb-engine»); O15 (резолюция id/alias case-insensitive +
честные негативы: UI-подпись «DuckDB (встроенная)» → ValueError,
"oracle"/None/"" → ValueError); O16 (средовой факт C7 изолированными
процессами: rw-коннект удерживается → read-only «Тест» падает
ConnectionException «different configuration»; в чистом процессе
read-only путь работает — 7 строк).

**3 ошибки СВОЕГО корпуса найдены и исправлены в ходе отладки (не кода)**:
(1) later_bad.csv с незакрытой кавычкой DuckDB терпит (сниффер
строгий к UTF-8, но не к кавычкам) — заменено на битый UTF-8;
(2) ожидание `truncated=False` при лимите 5 из 7 строк было неверным —
обрезка клиентская, честный флаг True (уточнён оракул); (3) O16 внутри
одного процесса отравлялся собственным неудачным открытием (внутренняя
регистрация duckdb) — разведено на изолированные процессы. Parquet
корпуса собирается duckdb COPY (pyarrow в контейнере нет). Код продукта
не менялся.

## 5. Мутационный прогон — свои мутанты, двухканальная схема

Каналы: **repo** — 5 сюитов фазы A (137); **oracle** — 18 своих
оракулов. Контроль харнесса: MB-00 no-op обязан выжить в обоих
(«мутант на мутанте» — харнесс достоверен). Восстановление побайтовое
с md5-паспортом (db_connectors.py=6664774a, file_loader.py=820b8a2d);
финальный контроль: md5 СХОДИТСЯ, git diff пуст. Протокол:
scripts/dbcert_backend_mutation_results.txt.

- **MB-00 no-op — SURVIVED в ОБОИХ** (OK-CONTROL).
- **KILLED ОБОИМИ (7)**: MB-01 (снят mode=ro SQLite), MB-02 (снят
  uri=true — квотирование), MB-03 (снят read_only DuckDB), MB-04 (снят
  isfile), MB-05 (снят контроль расширения), MB-10 (ValueError/
  FileNotFoundError завёрнуты в ConnectionError — нарушен дружественный
  контракт ошибок), MB-11 (расширение .sqlite снято с реестра).
- **repo SURVIVED / oracle KILLED (3) — находки F1/F2 (repo-гэпы,
  прикрыты оракулами сертификации)**: MB-06 (снят file-probe Parquet/CSV
  на слое db_connectors — «Тест» перестаёт читать файл; убит O08/O09),
  MB-13 (тот же дефект на слое file_loader — path не передан в probe;
  убит O08), MB-12 (снят expanduser — пути ~/...; убит O11b).
  repo-тесты прогоняют только валидные источники и «локальные» пути —
  честность probe и expanduser repo-каналом не пинятся.
- **DUAL-SURVIVORS (3) — пережили ОБА канала, задокументированы честно**:
  **MB-07** (снят quote() SQLite-URI): пробел sqlite-URI терпит и без
  квотирования (repo-гэп O04 прикрыт... сам O04 на пробеле проходит —
  поведение эквивалентно); НО при исследовании обнаружен РЕАЛЬНЫЙ
  edge-case (находка F3 ниже): имя файла с «#» ломает подключение ДАЖЕ
  С quote(). **MB-08** (in-memory заменён `duckdb:///{path}` для
  Parquet/CSV): поведение эквивалентно на наблюдаемой поверхности —
  probe и Load работают, md5 источника стабилен (duckdb аттачит файл
  только на чтение; show tables показывает служебные вьюхи); риск
  внутренний, рекомендация — белый пин in-memory URL (F4). **MB-09**
  (снят LIMIT 1 file-probe): сниффер DuckDB сканирует весь CSV — битые
  строки ловятся и без LIMIT; для Parquet семантика LIMIT никем не
  пинится (F5). Материальность всех трёх — низкая (поведение продукта
  на наблюдаемой поверхности не меняется), но пины дёшевы.

## 6. Сверка заявлений worklog10.md с фактами

- «17 тестов, 14 RED (NotImplementedError заглушки) + 3 тривиально-
  зелёных» — RED-фаза была внутри цикла разработки (фаза A закоммичена
  одним коммитом); независимо воспроизведён честный RED против 68fd65d
  (файлы отсутствуют + D1 живьём + embedded-ветки не существовало).
- «исправлена ошибка КОРПУСА (не кода): UI-подпись → ValueError +
  case-insensitive id» — подтверждено кодом теста
  test_embedded_ids_case_insensitive и оракулом O15.
- «сквозной Test→Load 12 строк SQLite / 9 строк DuckDB; read-only
  пинится; .txt/.xlsx → ValueError; FileNotFoundError; alias sqlite3;
  CSV 3 строки; Parquet 9 строк; пробел в пути (DuckDB); guard DELETE →
  DbQueryRejected» — подтверждено прогоном 17/17.
- «137/137 фаза A (36+72+17+5+7)» — подтверждено прогоном.
- «Полный tests/unit 1650/45/24/3; ID падений идентичны базе 68fd65d
  48/48; прирост +125» — подтверждено побайтовой сверкой.
- «Смежный контур 35/35» — подтверждено.
- «py_compile OK; импорт-безопасность без sqlalchemy; 6 записей» —
  подтверждено (py_compile + O14).
- «Средовой факт DuckDB: одна конфигурация на файл; тесты отпускают
  пулы (dispose)» — подтверждено: факт воспроизведён изолированно
  (O16), dispose-паттерн в repo-тестах на месте (_write_sqlite).
- «D1-остаток app.py:520 — скоуп UPLOAD-DB-10» — подтверждено чтением
  кода (сырая строка в legacy-UI).
- Заявленных противоречий «код vs журнал» не обнаружено.

## 7. Находки

- **F1 (РЕКОМЕНДАЦИЯ — repo-гэп: честность probe)**: мутанты MB-06/MB-13
  (file-probe снят на слоях db_connectors/file_loader) пережили
  repo-канал — repo-тесты не подают битых источников. Прикрыто
  оракулами сертификации O08/O09 (ConnectionError на «Тест»). Предложение:
  repo-пин «garbage.csv → init_db_connection raises ConnectionError».
- **F2 (РЕКОМЕНДАЦИЯ — repo-гэп: expanduser)**: мутант MB-12 пережил
  repo-канал (нет путей ~/ в repo-тестах); убит оракулом O11b.
  Предложение: repo-пин expanduser (фейковый HOME).
- **F3 (EDGE-CASE, некритичный, реальный)**: имя файла с «#» (URI-
  фрагмент) ломает embedded-SQLite ДАЖЕ С quote(): sqlite-direct тем же
  URI файл открывает, а через sqlalchemy create_engine — «no such
  table» (mode=ro на несуществующий путь тихо открывает пустую память).
  Наблюдается и через URL.create — SQLAlchemy-диалект рендерит database-
  часть с частичным процент-энкодингом (':' → %3A, пробел сырым),
  URI-соглашение sqlite нарушается на слое SQLAlchemy 2.1.4.
  Материальность низкая (редкий кластер символов; «Тест» падает честно,
  не тихо), но ошибка запутанная — рекомендация: учесть в UPLOAD-DB-4
  (API-контракт: валидация пути) или UPLOAD-DB-9 (документация);
  кандидат в defect-репорт по решению тимлида.
- **F4 (dual-survivor MB-08)**: in-memory → duckdb:///{path} для
  Parquet/CSV поведенчески эквивалентен на наблюдаемой поверхности
  (probe/Load/md5 идентичны); внутренне движок аттачит файл. Предложение:
  белый repo-пин «open_embedded для query_file_extensions возвращает
  in-memory URL».
- **F5 (dual-survivor MB-09)**: LIMIT 1 file-probe не пинится никем;
  сниффер DuckDB сканирует весь CSV (probe честен и так), для Parquet
  семантика LIMIT не покрыта. Предложение: пин через oversized-файл или
  мок; материальность низкая.
- **R1 (средовое)**: доустановка duckdb/duckdb-engine (версии совпали с
  заявленными в worklog), arch/PyWavelets/pandera; pyarrow нет — корпус
  Parquet собран duckdb COPY; полный юнит-набор согласован с базлайном
  68fd65d (48/48 ID, дельта +125).
- **R2 (методологическая гарантия подтверждена)**: обе встроенные СУБД
  физически read-only (мутанты MB-01/MB-03 убиты ОБОИМИ каналами;
  md5-инварианты O02/O05); guard действует на embedded-дорожке
  (MB-семейство guard'а убито, O12 — 7/7 запретов).

## 8. Вердикт: PASSED

Ядро приёмки UPLOAD-DB-3 подтверждено НЕЗАВИСИМО на базе 88a5459
(≡6cff336 для фазы A): (1) path-режим реестра с честной валидацией пути
(матрица 6 сценариев + expanduser); (2) строго read-only обеих
встроенных СУБД на уровне файла/коннекта (md5-инварианты); (3) честный
«Тест» по Parquet/CSV (probe читает сам источник — битые источники
отклоняются на фазе «Тест», включая мусор за снапшотом сниффера);
(4) сквозной Test→Load на SQLite и DuckDB без внешних сервисов (DoD);
(5) guard и лимиты действуют на embedded-дорожке (env-капа сильнее
параметра); (6) пины зависимостей и import-безопасность. GREEN 17/17 +
137/137 + 35/35; полный юнит-регресс сходится с базлайном побайтово
(48/48 ID, +125). RED честный. Оракулы 18/18 на дизъюнктном корпусе
(3 ошибки корпуса исправлены в ходе отладки, код не менялся).
Мутационный прогон: 7/13 убиты ОБОИМИ каналами, 3 repo-гэпа (F1/F2)
прикрыты оракулами сертификации, 3 dual-survivors (F3-F5) задокументированы
с оценкой материальности — поведение продукта на наблюдаемой поверхности
не нарушено; no-op-контроль выжил (харнесс достоверен); восстановление
побайтовое (md5-паспорт, git diff пуст). Deliverable: ZIP
cisstat-upload-db-3-cert.zip → открытый контейнер сессии (download +
upload): акт docs/, оракулы+мутационный харнесс+RED-протокол+протоколы
scripts/, worklog/worklog10.md. Без commit/push (AGENTS.md).
