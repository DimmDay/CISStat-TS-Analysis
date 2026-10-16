# Акт независимой сертификации задачи UPLOAD-DB-4 (2026-10-16)

**Задача:** Фаза B «новый контур»: API-контракт apps/api — эндпоинты POST
/v1/{internal|public}/upload/db/test + /load над ядром Фазы A
(commit 6cff336, база задачи ae9ae67).
**Метод:** мутанты на своих мутантах + оракулы на своих данных
(двухканальная схема repo+oracle, no-op-контроль, md5-паспорт).
**Вердикт: PASSED.**
**База аудита:** main@4c7bc16 (HEAD); ядро задачи
(routers/upload_db.py, schemas.py, upload_common.py, main.py,
trace_hook.py, test_upload_db.py) не менялось с 6cff336 —
git diff 6cff336..HEAD по шести файлам ПУСТ (последующие
UPLOAD-DB-7 / DATASET-VIEW-EDITOR-1-FIX трогали только
apps/api/requirements.txt, apps/api/Dockerfile и tests).
Дерево чистое на протяжении всего аудита; commit/push НЕ выполнялись.

## 1. Сверка с кодовой базой (статический аудит, все точки на месте)

1. apps/api/schemas.py — ServerDbCredentials{db_type ∈ {postgresql,
   clickhouse, mssql, mysql}, host, port None→default_port, database,
   user, password, ssl=False} | EmbeddedDbSource{db_type ∈ {duckdb,
   sqlite}, path}; ОБОЯ model_config extra="forbid";
   DbConnection = Annotated[Union[…], Field(discriminator="db_type")];
   DbTestRequest{connection}; DbTestResponse{ok, db_type,
   server_version, latency_ms ≥ 0, error?}; DbLoadRequest{connection,
   sql min_length=1, row_limit None→env-потолок}.
2. apps/api/routers/upload_db.py (НОВЫЙ) — router + public_router
   (dependencies=[Depends(require_api_key)]); _register регистрирует
   /test и /load НА ОБОИХ; карта ошибок в docstring/OpenAPI:
   /test — probe-семантика (ConnectionError/FileNotFoundError/
   ImportError → 200 {ok:false, error маскирован}; ValueError вкл.
   HostNotAllowed → 422); /load — 200 UploadResponse, guard
   DbQueryRejected/ValueError → 422, операционные → 400 (маскирование
   D4 слоем роутера + ядром); «Тест» вне TRACE_ROUTES и не создаёт
   сессию; password в ядро только kwargs (в URL не попадает);
   _server_version — version_probe реестра, best-effort;
   _source_name — «{label}: {database}» / basename(expanduser(path)).
3. apps/api/main.py — монтирование /v1/internal/upload/db и
   /v1/public/upload/db (один модуль реализации).
4. apps/api/trace_hook.py — +2 строки TRACE_ROUTES (54→56): оба
   семейства /upload/db/load → (upload, overview, upload_completed),
   payload_keys=(name, rows, columns, size_label); /test вне таблицы
   (fail-closed).
5. apps/api/upload_common.py — register_uploaded_dataframe: единая
   «хвостовая» регистрация (preview → dataset_id → cookie-сессия →
   set_dataset → auto_fix_and_seed (PROGR-25-A) → store.save →
   UploadResponse); handle_upload делегирует (файловая дорожка не
   дублируется); dataset_fingerprint="" у БД-дорожки (контракт
   «источник без файла»).
6. apps/api/requirements.txt — sqlalchemy>=2.0.0 (критичный пин:
   в образе API его не было — AST-разбор импортов РОУТЕРОВ не видит
   guarded-импорт реестра Фазы A), clickhouse-connect, duckdb,
   duckdb-engine. apps/api/Dockerfile — build-гвард импорта
   db-track deps. (После 6cff336 оба файла дополнены UPLOAD-DB-7
   аддитивно — PyMySQL/cryptography/pyodbc, ODBC-слой; контракт
   UPLOAD-DB-4 не затронут.)

## 2. Окружение и независимая верификация

venv Python 3.12.15: sqlalchemy 2.1.4, duckdb 1.5.6, duckdb-engine,
clickhouse-connect, statsmodels 0.14.5 (средовой класс: пин 0.15.0),
fakeredis, psycopg[binary], PyWavelets/pandera/arch (доустановлены —
известный средовой класс прошлых сертификаций).

GREEN repo-тестов задачи: tests/api/test_upload_db.py — **31/31**
(в точности заявление worklog); VERSIONED test_progress_trace_hook.py
+ test_upload.py + test_session_store.py — **144/144**.

Полный tests/api (дерево 4c7bc16): **2009 passed / 29 failed /
41 skipped**. Все 29 ID падений сняты в
scripts/db4cert_baseline_api_failed_ids.txt и относятся к известному
средовому классу (forecasting_session 16, modeling_workflow 4,
models_backtest_real 2, dataset_profile_detail_level 2,
progress_audit_6c 1, models_candidates 1, neural_capacity 1,
feature_regressors 1 — prophet/backtest при statsmodels 0.14.5,
нейро-каталог; состав согласуется с базлайном worklog UPLOAD-DB-7:
2000/38/41 — расхождение = состав опциональных зависимостей venv,
адресно проверено). **Ни одного падения в DB-контуре**
(test_upload*, test_progress_trace_hook, test_session*).

## 3. RED-воспроизведение (scripts/db4cert_red_repro.py/.txt)

Родитель ae9ae67 через git-worktree (дерево основного репозитория не
тронуто, cleanup выполнен): R1a routers/upload_db.py ОТСУТСТВУЕТ;
R1b tests/api/test_upload_db.py ОТСУТСТВУЕТ (repo-collection невозможен);
R2 DbTestRequest/DbConnection в schemas.py родителя ОТСУТСТВУЮТ;
R4 монтирование в main.py ОТСУТСТВУЕТ; R5 TRACE_ROUTES db/load
ОТСУТСТВУЮТ. Оракулы аудитора на родителе: **24/24 RED** (rc=1,
эндпоинты 404). Композиция RED полная: GREEN достигается только
реализацией UPLOAD-DB-4.

## 4. Оракулы на СВОИХ данных — 24/24 PASS

Корпус «припортовая гидрологическая сеть» (scripts/db4cert_oracles.py,
протокол scripts/db4cert_oracles.txt) дизъюнктен repo-корпусу
(sales.db/t/points.csv) и корпусам прошлых сертификаций (dvecert
«порт-звонки», dbcert «station telemetry»):
gauge_river.sqlite (9 строк, кириллица), tides_harbor.duckdb (7 строк),
«ледовые сводки 2024.csv» (юникод+пробел), sensor_grid.parquet (duckdb
COPY), broken.sqlite/broken.duckdb (мусорные), absent-файл,
gauge_notes.txt, riverside.db в fake HOME (единственная числовая
колонка); пароль-спецсимволы `P0rt-G@uge#2024$v;{}x`.

Поверхности дизъюнктны/глубже repo-сюиты:
- **O01** OpenAPI глубже repo: response-$ref DbTestResponse/UploadResponse
  в ОБОИХ семействах (repo пинит только requestBody);
- **O02** discriminated union ЧЕРЕЗ HTTP-провод: server+path /
  embedded+host / unknown db_type → 422 (repo пинит на уровне схем);
- **O03–O05** «Тест» на реальных источниках: SQLite/DuckDB файлы +
  DuckDB прямой probe по CSV (repo /test по CSV не имеет);
- **O06** битые источники через API-карту ошибок: 200 {ok:false}, НЕ 500;
- **O07** маскирование D4 сквозь оба эндпоинта (пароль-спецсимволы не в
  теле /test и /load);
- **O08–O09** /load полный контракт файла на своём корпусе (UUID-форма
  dataset_id, заголовок preview, columns_info, quality, size_label в
  единицах B/KB/MB/GB и ≠ «0 B»; сессия: fingerprint="", upload=done,
  окно offset/limit существующего GET живо);
- **O10** авто-фиксация цели PROGR-25-A сквозь БД-дорожку: /current →
  target_column=level, target_column_source="auto" + expanduser-пин
  (repo на БД-дорожке этого НЕ пинит);
- **O11** трасса: upload_completed@overview с payload (name/rows/
  size_label) + «Тест» НЕ растит СУЩЕСТВУЮЩУЮ трассу (repo — только
  отсутствие cookie);
- **O12** честность усечения: лимит 4 из 9 → пометка; env-капа 3 сильнее
  запроса 50; env 100 ≥ данных → пометки усечения НЕТ (нечестная
  пометка отвергнута);
- **O13** guard-матрица через API (5 SQL): DELETE/INSERT/UPDATE/
  мультистейтмент/комментированный DML → 422 и сессия НЕ создана
  (fail-closed);
- **O14** имена источников: «PostgreSQL / Postgres Pro: harbor_poc» +
  юникод basename («ледовые сводки 2024.csv») через реальное ядро;
- **O15** семейства: public без ключа → 401/422 и fail-closed без
  сессии; с валидным ключом (формат key:role:plan — corpus-урок:
  невалидная роль → запись пропускается → пустой реестр → 500) /test
  и /load 200; internal без ключа 200;
- **O16** сбой version_probe НЕ роняет подтверждённую пробу
  (best-effort; repo этой поверхности не имеет);
- **O17** персистенция на fakeredis: save→get СКВОЗЬ хранилище
  (класс PROGR-25-F1: Memory-алиасинг маскирует потерю save);
- **O18** валидация тела /load через провод (sql=""/row_limit 0/-5/
  без connection → 422);
- **O19** probe-чистота на уровне ХРАНИЛИЩА (peek_session_store без
  сессий);
- **O20** capture-kwargs на границе роутера: ssl=False safe-дефолт и
  port «как есть» (None; резолв default_port — контракт ядра Фазы A,
  сертифицирован UPLOAD-DB-3-CERT).

В ходе отладки исправлены 3 ошибки СВОЕГО корпуса (не кода): параметры
окна GET /dataset/rows — offset/limit, а не page/page_size (контракт
UI-UPLOAD-FULL-1); роль API-ключа «service» невалидна → запись
пропускается fail-closed → пустой реестр → 500 (замена на
internal_analyst); default_port резолвится ядром, на границе роутера
порт честно None (уточнён пин).

## 5. Мутационный прогон — свои мутанты, двухканальная схема

scripts/db4cert_mutations.py, протокол scripts/db4cert_mutations.txt.
md5-паспорт (upload_db.py=21861468, upload_common.py=6e0f4c90,
trace_hook.py, schemas.py=25103cc9), финальный контроль — md5 СХОДИТСЯ,
git diff пуст.

- **MB-00** no-op-контроль — SURVIVED в ОБОИХ (харнесс достоверен).
- **KILLED ОБОИМИ каналами (13):** MB-01 (probe лжёт ok=True), MB-02
  (снято маскирование /test), MB-03 (/test ValueError→400), MB-04
  (guard→400 вместо 422), MB-05 (/load init-сбой→422 вместо 400),
  MB-06 (снята пометка усечения), MB-07 (имя сервера без label), MB-08
  (имя embedded — полный путь), MB-12 (preview без заголовка), MB-13
  (путь TRACE_ROUTES разъехался), MB-14 (payload обеднен), MB-16
  (extra=forbid снят), MB-17 (снят API-ключ public).
- **repo SURVIVED / oracle KILLED (4) — repo-гэпы, прикрыты оракулами:**
  - **MB-15** (ssl-дефолт False→True): repo-тест
    test_server_credentials_ssl_default_false подаёт ssl ЯВНО в
    фикстуре — дефолт фактически НЕ прикрыт repo-каналом (имя теста
    шире его проверки); убит оракулом O20 (capture БЕЗ поля ssl).
  - **MB-10** (потеря store.save в register_uploaded_dataframe):
    Memory-алиасинг маскирует — класс PROGR-25-F1/MB-9 акта
    DATASET-VIEW-EDITOR-1-CERT; убит оракулом O17 (fakeredis).
  - **MB-11** (снята auto_fix_and_seed): авто-фиксация цели через БД-
    дорожку repo-сюитой не пинится; убит оракулом O10.
  - **MB-09** (size_label="0 B"): repo пинит только truthiness («0 B»
    truthy); в первом прогоне пережил ОБА канала — оракульный гэп
    (regex допускал константу); оракул O08 усилен пином «≠ 0 B»
    (честность размерности), повторный прогон — KILLED оракулом.
- **DUAL-SURVIVORS (пережили оба канала): 0.**

## 6. Находки и вердикт

**F1 (repo-гэп, тест-код):** пин «ssl default False» не покрывает
дефолт — фикстура repo-теста подаёт ssl явно; предложение: репо-пин
валидации DbTestRequest от payload БЕЗ поля ssl (уровень оракула O20).
**F2 (repo-гэп, класс PROGR-25-F1):** персистенционные пины upload-
дорожки на Memory-бэкенде; предложение: fakeredis-параметризация
ключевых пинов сессии test_upload_db.py (паттерн
DATASET-VIEW-EDITOR-1-FIX). **F3 (repo-гэп):** авто-фиксация цели на
БД-дорожке не прикрыта repo-каналом; предложение: repo-пин /current
после /load (уровень оракула O10). **F4 (закрыто в ходе аудита):**
нечестный size_label («0 B») был не виден обоими каналами — оракул O08
усилен (≠ «0 B»), мутант MB-09 переведён в KILLED.
**R2 (средовое):** 29 падений tests/api — средовой класс (statsmodels
0.14.5, нейро-каталог); DB-контур зелёный полностью. **R3 (главная
методологическая гарантия подтверждена независимо):** карта ошибок
probe/операционных сбоев, маскирование D4, read-only guard→422,
монтирование обоих семейств с ключом, отсутствие новых типов событий
трассы — мутанты этих свойств не переживают ни одного канала.

**ВЕРДИКТ: PASSED** — ядро приёмки UPLOAD-DB-4 подтверждено
независимо: контракты схем (union/discriminator/extra=forbid/safe-
дефолты), карта ошибок обоих эндпоинтов, паритет UploadResponse с
файлом, единая регистрация register_uploaded_dataframe (включая
авто-фиксацию цели и персистенцию), трасса без новых типов событий,
gating public-семейства. Код и тесты репозитория аудитом не менялись.
DoD задачи подтверждён: OpenAPI задокументирован (4 пути, requestBody-
и response-схемы), БД-датасет проходит 5-остановочный пайплайн без
новых событий трассы, отрицательные сценарии (неверные креды →
маскированная ошибка; guard → 422).

Артефакты: scripts/db4cert_oracles.py/.txt,
scripts/db4cert_mutations.py/.txt,
scripts/db4cert_red_repro.py/.txt,
scripts/db4cert_baseline_api_failed_ids.txt.
