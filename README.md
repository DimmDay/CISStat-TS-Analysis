# CISStat TS Analysis — монорепозиторий (embedded + standalone + api)

Реализует два направления развития платформы при единой идентичности:

1. **`apps/embedded`** — раздел внутри портала CISStat (использует
   `PortalNavBar` — точную копию присланного `NavBar.tsx`).
2. **`apps/standalone`** — самодостаточный продукт для внешних покупателей,
   доступный в вебе и через API (`apps/api`), со своей шапкой
   (`ProductHeader`, пока заглушка), но той же дизайн-системой.
3. **`packages/ui`** — общий пакет: дизайн-токены (`tailwind-preset.ts`,
   `globals.css` — точные копии присланных файлов), общие примитивы
   (`Button`, `Metric`, `StatusIcon`), и, что важнее всего, сам
   **`TsAnalysisPreprocessing`** — компонент фичи анализа, используемый
   ОБОИМИ приложениями без дублирования кода.
4. **`apps/api`** — FastAPI-бэкенд, оборачивающий уже протестированные
   `app/core/passport.py` и `app/validation/regularity.py` из основного
   репозитория CISStat-TS-Analysis. Два семейства роутов:
   - `/v1/public/*` — авторизация по API-ключу, для внешних покупателей.
   - `/v1/internal/*` — для embedded-режима.

## ⚠️ Куда физически положить `apps/api`

Роутеры импортируют `app.core.passport` и `app.validation.regularity`
напрямую (`from app.core.passport import calculate_ts_passport`). Чтобы
это работало, `apps/api` нужно запускать там, где эти модули доступны
как Python-пакет — проще всего:

- либо скопировать папку `apps/api` в корень репозитория
  `CISStat-TS-Analysis` (рядом с `app.py`) и запускать `uvicorn` оттуда;
- либо, если предпочитаете держать монорепозиторий фронтендов отдельно,
  установить `CISStat-TS-Analysis` как зависимость/добавить его в
  `PYTHONPATH` при запуске API.

```bash
cd apps/api
pip install -r requirements.txt --break-system-packages
export CISSTAT_API_KEYS="test-key-123"   # для локальной разработки
uvicorn main:app --reload --port 8000
```

Проверка: `http://localhost:8000/docs` — автоматическая OpenAPI/Swagger
документация (важно для истории "самодостаточный продукт... для
интеграции в сторонние ИТ-системы" — задокументированный публичный API
уже есть из коробки, просто за счёт FastAPI).

## Загрузка из баз данных (SQL)

Эпик **UPLOAD-DB** (`spec_database_plan.md`): источник «База данных (SQL)»
сервиса «Загрузка» подключает СУБД утверждённой матрицы и регистрирует
выборку как датасет — дальше она проходит тот же пятиостановочный
пайплайн, что и файл. Единственная точка знания о СУБД — реестр
коннекторов `app/data/db_connectors.py` (архитектура — раздел «Реестр
коннекторов БД» в ARCHITECTURE.md); справка подключения (настройка
серверов всех шести СУБД) — `docs/upload_db_connections_help.md`;
приёмочный прогон релиза — `docs/upload_db_release_smoke_checklist.md`.

**Матрица СУБД** (реестр коннекторов, обе встроенные — строго read-only):

| СУБД | Режим | Диалект / клиент | Порт | Драйвер (pip) |
|---|---|---|---|---|
| PostgreSQL / Postgres Pro | server | `postgresql+psycopg` | 5432 | `psycopg[binary]` (v3, S1) |
| ClickHouse | server | нативный `clickhouse-connect` | 8123 | `clickhouse-connect` |
| MS SQL Server | server | `mssql+pyodbc` | 1433 | `pyodbc` + ODBC Driver 18, fallback `pymssql` (S2) |
| MySQL / MariaDB | server | `mysql+pymysql` | 3306 | `PyMySQL` + `cryptography` (caching_sha2_password) |
| DuckDB (встроенная) | embedded | `duckdb` (файл, read_only) | — | `duckdb duckdb-engine` (+ прямой SELECT по `.parquet`/`.csv`) |
| SQLite (встроенная) | embedded | `sqlite` (файл, `mode=ro`) | — | стандартная библиотека Python |

**API-контракт** (оба семейства, конвенция платформы):
`POST /v1/internal/upload/db/test` и `POST /v1/public/upload/db/test`
(проба: `200 {ok, db_type, server_version, latency_ms}` или
`200 {ok: false, error маскирован}`; контрактные нарушения — 422),
`POST /v1/internal/upload/db/load` и `POST /v1/public/upload/db/load`
(загрузка → тот же `UploadResponse`, что у файла; read-only guard
только `SELECT`/`WITH` → нарушение 422). Дискриминированный union
профиля по `db_type`: `ServerDbCredentials` (серверные) |
`EmbeddedDbSource` (путь к файлу). Пароль в URL соединения не попадает
ни для одной СУБД (D4), в ошибках маскируется.

**env-переменные дорожки** (дефолты — константы кода, S4/D5/S2):

| Переменная | Дефолт | Назначение |
|---|---|---|
| `UPLOAD_DB_ROW_LIMIT` | 1 000 000 | принудительный потолок строк выборки |
| `UPLOAD_DB_CHUNKSIZE` | 50 000 | размер чанка chunksize-стриминга |
| `UPLOAD_DB_CONNECT_TIMEOUT` | 10 (с) | таймаут подключения |
| `UPLOAD_DB_QUERY_TIMEOUT` | 60 (с) | PG statement_timeout; MySQL read/write; MSSQL statement/query; CH send/receive |
| `UPLOAD_DB_HOST_WHITELIST` | пусто (off) | белый список хостов/CIDR (D5/SSRF; `*` — off) |
| `UPLOAD_DB_MSSQL_DRIVER` | авто | `pyodbc` \| `pymssql` (S2/RP2: закрытый контур без apt MS) |

**Статус дорожки**: ядро и API UPLOAD-DB реализованы; форма
`DbConnectionForm` и навигатор UPLOAD-DB-5/6 реализованы для шести типов
источников. В «Загрузке» выберите «База данных (SQL)», задайте серверные
параметры либо путь к файлу на сервере API, нажмите «Тест подключения» и
«Загрузить из БД». Результат идёт в общий пятиостановочный pipeline.
Тест-стенд docker-compose UPLOAD-DB-8 и legacy-выравнивание UPLOAD-DB-10
остаются roadmap; успешная локальная проба не сертифицирует все серверы.

## Что ЗАГЛУШКА и требует вашего решения

| Файл | Статус |
|---|---|
| `packages/ui/components/PortalNavBar.tsx` | ✅ Точная копия присланного `NavBar.tsx` |
| `packages/ui/tailwind-preset.ts`, `globals.css` | ✅ Точные значения из присланных файлов |
| `apps/standalone/components/ProductHeader.tsx` | ⚠️ Придумано с нуля — нужно решить: свой суб-бренд или тот же логотип портала? |
| Логотип-шапка портала (синяя полоса с гербом/названием) | ❌ Ещё не прислана — `PortalNavBar` в присланном виде это ТОЛЬКО строка ссылок разделов, без верхней синей полосы и без строки поиска с ИИ-агентом. Если embedded-режим должен показывать их тоже — пришлите эти компоненты отдельно. |
| Авторизация между embedded и порталом | ❌ Не определена — JWT из сессии портала? Общий cookie? Нужно обсудить с командой портала. |
| Биллинг/лимиты для публичного API | ❌ `auth.py` сейчас проверяет ключи по переменной окружения — для продакшена нужна таблица ключей в БД с учётом использования. |

## Как запустить локально (после `npm install` в корне)

```bash
npm install
npm run dev:embedded    # http://localhost:3000
npm run dev:standalone  # http://localhost:3001 (порт задан в package.json, чтобы не конфликтовать)
```

**Не проверено реальной сборкой** (не было доступа к npm-реестру в
среде, где готовился скелет) — после `npm install` обязательно:

```bash
npm run typecheck:all
npm run build:all
```

и поправить любые несостыковки версий (`react-icons`, `next`, `react` —
зафиксируйте на тех версиях, что реально используются в репозитории
портала, если они отличаются от указанных здесь).

## Следующие шаги

1. Прогнать `npm install` + `typecheck` + `build`, прислать, если что-то
   упадёт — поправим.
2. Решить судьбу `ProductHeader` (свой бренд vs логотип портала).
3. Прислать компоненты верхней синей полосы (логотип) и строки поиска
   с ИИ-агентом, если они нужны в embedded-режиме.
4. Определиться с моделью авторизации между embedded и порталом.
5. Спроектировать биллинг/лимиты для публичного API (для внешних покупателей).
6. Расширить `apps/api` остальными функциями (`detect_and_convert_datetime`,
   валидаторы, `compute_text_violations` и т.д.) по мере надобности —
   сейчас реализованы только паспорт и регулярность как proof-of-concept.
