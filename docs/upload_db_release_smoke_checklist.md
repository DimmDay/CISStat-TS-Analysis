# Смоук-чеклист релиза UPLOAD-DB (эпик «Загрузка → База данных (SQL)»)

> Задача UPLOAD-DB-9 (spec_database_plan.md, фаза D «выпуск»). Чеклист — быстрый приёмочный
> прогон релиза БД-дорожки в среде тимлида: контур ядра, API, безопасность, окружение,
> документация. Помечено, что проверяется в CI без сервисов, а что требует реальных серверов
> (стенд UPLOAD-DB-8 — roadmap). Гвард соответствия документации коду —
> `tests/unit/test_upload_db9_docs.py`; факт-скан кода — `scripts/upload_db9_fact_scan.py`.

## 1. Окружение и сборка

- [ ] Python-контур: `pip install -r apps/api/requirements.txt` — без ошибок; гвард-импорты
      дают в логе `db-track deps OK (UPLOAD-DB-4)` и `db-track C OK (UPLOAD-DB-7)`.
- [ ] Docker-сборка apps/api: `docker build -f apps/api/Dockerfile .` (контекст — корень
      репозитория); слой unixodbc+msodbcsql18 собирается, в логе
      `msodbcsql18 registered (UPLOAD-DB-7)`.
      ⚠️ Проверка выполняется в среде с docker-демоном (в песочнице разработки недоступна —
      слой реализован по официальной инструкции Microsoft для Debian 12, синтаксис проверен
      `bash -n`; DoD-остаток честно задокументирован в UPLOAD-DB-7).
- [ ] Закрытый контур без apt-репозитория Microsoft: сборка с
      `--build-arg INSTALL_MSODBCSQL18=false` успешна; в логе
      `INSTALL_MSODBCSQL18=false: MSSQL via pymssql-fallback (S2/RP2)`.
- [ ] Старт API: `uvicorn apps.api.main:app` — `/health` отвечает, OpenAPI `/docs`
      показывает 4 пути `/v1/{internal|public}/upload/db/{test|load}`.

## 2. Ядро (pytest, CI без сервисов)

- [ ] DB-трек юниты: `pytest tests/unit/test_db_connectors.py tests/unit/test_db_guard.py
      tests/unit/test_db_embedded.py tests/unit/test_db_connection.py` — все зелёные
      (базлайн задачи: 155/155 на 659f8fd).
- [ ] Гвард документации: `pytest tests/unit/test_upload_db9_docs.py` — все зелёные
      (docs соответствуют коду — DoD UPLOAD-DB-9).
- [ ] API-контракт: `pytest tests/api/test_upload_db.py` — все зелёные (базлайн 31/31);
      `pytest tests/api/test_docker_image_layout.py` — 4/4.
- [ ] Импорт-безопасность без sqlalchemy: реестр читаем без зависимостей (юнит-пин
      TestImportSafety), открытие соединения даёт дружественный ImportError с подсказкой
      pip-установки (D2) — включая fallback-подсказку pymssql для MSSQL (UPLOAD-DB-7).

## 3. Сквозной Test→Load (CI-класс, без серверов)

- [ ] Создать `sample.db` (SQLite) и `sample.duckdb` + один Parquet/CSV; положить в путь,
      видимый контуру apps/api.
- [ ] `POST /v1/internal/upload/db/test` (SQLite, `path`) → `200 {ok: true, db_type:
      "sqlite", server_version: null, latency_ms ≥ 0}`.
- [ ] `POST /v1/internal/upload/db/test` (DuckDB по `.csv`) → `ok: true` (прямой SELECT
      по файлу, UPLOAD-DB-3).
- [ ] `POST /v1/internal/upload/db/load` (SQLite, `sql: "SELECT * FROM t LIMIT 100"`) →
      `200 UploadResponse`: preview, columns_info, quality, parse_warnings; сессия создана
      (cookie `cisstat_session_id`), остановка `upload=done`, событие трассы
      `upload_completed` — новых типов событий нет.
- [ ] `size_label` БД-источника — объём фрейма в памяти, ≠ «0 B»; fingerprint пустой
      (БД-дорожка).

## 4. Серверные СУБД (требуют серверов — матрица «зажигания», стенд UPLOAD-DB-8 — roadmap)

- [ ] PostgreSQL / Postgres Pro: «Тест» → `ok: true`, `server_version` содержит вендор
      (`PostgreSQL 16 …` / `Postgres Pro …`); Load по `SELECT` — UploadResponse.
- [ ] ClickHouse: «Тест» → `ok: true` (HTTP 8123); Load — UploadResponse.
- [ ] MySQL / MariaDB: «Тест» → `ok: true` (caching_sha2_password — с пином cryptography);
      MariaDB — вендор в `server_version`.
- [ ] MS SQL Server: «Тест» → `ok: true` (pyodbc + ODBC Driver 18); при
      `INSTALL_MSODBCSQL18=false` — переключение env `UPLOAD_DB_MSSQL_DRIVER=pymssql`
      даёт успешную пробу тем же контрактом.
- [ ] Неверные креды каждой серверной СУБД: `/test` → `200 {ok: false, error:
      маскированная причина}` (пароль отсутствует в тексте), `/load` → `400` (маскировано).

## 5. Безопасность

- [ ] Read-only guard (D6): `DELETE`/`INSERT`/`UPDATE`/мультистейтмент/комментированный DML
      → `422`, сессия не создаётся (fail-closed).
- [ ] `WITH x AS (DELETE …)` (CTE-обход) → `422`; `SELECT … FOR UPDATE` → `422`;
      `SELECT pg_sleep(10)` → `422`.
- [ ] Host-whitelist (D5/S5): с env `UPLOAD_DB_HOST_WHITELIST=10.0.0.0/8` запрос к чужому
      хосту → `422 HostNotAllowed`; без env — off (песочница).
- [ ] Маскирование (D4): во всех ошибках `/test` и `/load` пароль заменён `****`; в объекте
      URL соединения пароля нет ни для одной СУБД (включая MSSQL — connect_args PWD,
      UPLOAD-DB-7).
- [ ] «Тест» не создаёт сессию и не растит существующую трассу (probe-чистота).

## 6. Окружение-переключатели (env)

- [ ] `UPLOAD_DB_ROW_LIMIT=100` + запрос с большим результатом → датасет усечён до 100,
      `parse_warnings` содержит пометку усечения; `UPLOAD_DB_ROW_LIMIT=0`/мусор → дефолт
      1 000 000 (тихо-безопасное поведение env-парсера).
- [ ] `UPLOAD_DB_CHUNKSIZE=1000` — загрузка успешна (стриминг чанками).
- [ ] `UPLOAD_DB_CONNECT_TIMEOUT=2` / `UPLOAD_DB_QUERY_TIMEOUT=5` — недоступный хост падает
      быстро с маскированной ошибкой.
- [ ] `UPLOAD_DB_MSSQL_DRIVER=nonsense` → громкий `ValueError` (не тихое игнорирование);
      `pyodbc`/`pymssql` — принимаются.

## 7. Фронтенд и документация

- [ ] Раздел «Обучение и база знаний» (/education): статья «Подключение к базам данных»
      доступна в библиотеке на стадии «Загрузка» (реестр
      `packages/ui/lib/knowledge/articles.ts`, article_id `upload-db-connections`).
- [ ] README: раздел «Загрузка из баз данных (SQL)» отражает матрицу 6 СУБД, драйверы,
      env-лимиты, API-пути; ссылки на `docs/upload_db_connections_help.md` и этот чеклист
      открываются.
- [ ] Честный статус UI в README: форма подключения к БД на странице «Загрузка» — заглушка
      (ядро Фазы A и API Фазы B готовы; форма UPLOAD-DB-5 и навигатор UPLOAD-DB-6 —
      roadmap эпика).
- [ ] jest-регресс базы знаний/образования: `npx jest knowledge education` — без новых
      падений; `npm run typecheck:all` — 0 ошибок.

## 8. Негативный контроль сборки (защита от регрессии)

- [ ] Сборка образа без `shared/` падает на гварде pipeline-graph (известный класс DEPLOY-1)
      — гварды не ослаблены задачами UPLOAD-DB.
- [ ] `pytest tests/api/test_docker_image_layout.py` — структура requirements/Dockerfile не
      пинится жёстче фактов (тест структурный, 4/4).
