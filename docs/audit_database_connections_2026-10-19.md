# Аудит подключений к БД: текущее состояние и практическая проверка

Дата: 2026-10-19. Точный коммит: `079e352bd924c708ea6d563c1d01b2a5007882d1`.
Основание: `spec_database_plan.md`, `worklog/worklog10.md`, реализация и
собственные изолированные проверки. Продуктовый код не изменялся.

## Ответ на главный вопрос

**Сейчас весь набор коннекторов практически проверяется через API:**
Swagger `/docs`, curl, Postman или вызов того же API из браузера.
В standalone поле «База данных (SQL)» по-прежнему содержит текст
«форма подключения к БД — заглушка». Для полноценного пользовательского
проверочного маршрута ещё нужны UPLOAD-DB-5/6; для автоматической
проверки серверной матрицы — UPLOAD-DB-8.

«Шесть БД» в плане означает шесть **типов коннекторов**, а не шесть
независимо испытанных серверов. Postgres Pro нужно проверить отдельно
от PostgreSQL, MariaDB отдельно от MySQL, оба пути MSSQL — отдельно,
если предполагается эксплуатация fallback.

## Что действительно реализовано

| Контур | Факт на данном коммите |
|---|---|
| Ядро | Шесть записей `DB_CONNECTORS`: postgresql, clickhouse, mssql, mysql, duckdb, sqlite. SQLAlchemy для пяти типов; ClickHouse — native clickhouse-connect. |
| API | Четыре маршрута: POST `/v1/internal/upload/db/test`, `/load`; POST `/v1/public/upload/db/test`, `/load`. Публичное семейство требует `X-API-Key`. Internal — без API-ключа. |
| Данные | `/load` использует общий `register_uploaded_dataframe`, возвращает файловый UploadResponse, создаёт cookie-сессию, запускает обычный upload pipeline. |
| Embedded | Реальное чтение SQLite, DuckDB, CSV/Parquet через DuckDB; путь относится к файловой системе API-сервера. Drag-and-drop файлов БД вне v1. |
| UI standalone | Заглушка в `packages/ui/components/TsAnalysisUpload.tsx`; `DbConnectionForm` не реализован. Навигатор не заменяет форму. |
| Legacy Streamlit | Только PostgreSQL и ClickHouse. У PG-кнопки дополнительный `conn.execute("SELECT version()")` остаётся сырой строкой, несовместимой с SQLAlchemy 2.0. Для приёмки шести типов этот путь не подходит. UPLOAD-DB-10 не завершена. |
| Серверный стенд | `docker-compose.db-bench.yml` отсутствует; серверных Test→Load интеграций в `tests/integration` нет. Обычный `docker-compose.yml` поднимает legacy Streamlit, а не БД-стенд. |
| Документация | UPLOAD-DB-9 и её сертификация завершены в собственном документальном периметре. Это не сертификация настоящего handshake всех СУБД. |

Окончание worklog10 прямо оставляет UPLOAD-DB-8, UPLOAD-DB-5/6 и
опциональную UPLOAD-DB-10 следующими шагами. Наличие DB-9 после DB-7
не означает выполнения пропущенных задач.

## Практический маршрут проверки

### 1. Выбрать расположение API и БД

Для первой полной проверки удобнее **локальный API и тестовые БД
в той же машине/сети**. Это исключает неопределённость версии Render
и сетевого доступа из облака.

Из корня репозитория в подготовленном окружении:

```bash
python -m pip install -r apps/api/requirements.txt
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Затем открыть `http://127.0.0.1:8000/docs` и найти семейство `upload`.
Проверять именно `/v1/internal/upload/db/test` и `/load`.

MS SQL Server требует не только pip-пакет `pyodbc`, но и unixODBC/
ODBC Driver 18. Сборка Linux-образа проекта:

```bash
docker build -f apps/api/Dockerfile -t cisstat-api:db-audit .
```

В закрытом контуре:

```bash
python -m pip install pymssql
```

и перед запуском API установить `UPLOAD_DB_MSSQL_DRIVER=pymssql`.
**Это явный выбор fallback, не автоматическое переключение после
ошибки подключения.** Если pyodbc импортируется, но системного ODBC
Driver 18 нет, авторезолюция продолжит выбирать pyodbc. После изменения
env сервер нужно перезапустить.

Параметры сети интерпретируются со стороны API:

- Локальный API → опубликованные Docker-порты: host=`127.0.0.1`.
- API в Docker → БД в одной Docker-сети: host=имя сервиса БД;
  `localhost` означает контейнер API.
- API на Render → host должен быть доступен **из Render**. Ввод
  `localhost` или локального пути компьютера пользователя не создаёт
  доступ к его компьютеру.
- Embedded: файл должен уже находиться на сервере API; для контейнера
  требуется volume с нужным файлом, например `/data/smoke.sqlite`.

### 2. Минимальная матрица

На каждом тестовом сервере заранее создать таблицу `cisstat_smoke`
с полями `date`, `value`, 12 известными строками и отдельного пользователя
с правом SELECT. Создание таблиц выполняется администратором стенда,
а не через `/upload/db/load`.

| Что испытывать | `db_type` API | Порт для обычного тестового сервера | SQL для загрузки |
|---|---|---:|---|
| PostgreSQL | `postgresql` | 5432 | `SELECT date, value FROM cisstat_smoke ORDER BY date LIMIT 10` |
| Postgres Pro — другой настоящий сервер | `postgresql` | 5432 | Тот же SQL; отдельно сверить `server_version`. |
| ClickHouse | `clickhouse` | 8123 HTTP | `SELECT date, value FROM cisstat_smoke ORDER BY date LIMIT 10` |
| MySQL | `mysql` | 3306 | Тот же SELECT с LIMIT. |
| MariaDB — другой настоящий сервер | `mysql` | 3306 | Тот же SELECT; отдельно сверить `server_version`. |
| MS SQL Server, основной драйвер | `mssql` | 1433 | `SELECT TOP (10) date, value FROM dbo.cisstat_smoke ORDER BY date` |
| MS SQL Server, fallback | `mssql` | 1433 | Тот же SQL после перезапуска API с `UPLOAD_DB_MSSQL_DRIVER=pymssql`. |
| SQLite | `sqlite` | — | `SELECT date, value FROM cisstat_smoke ORDER BY date LIMIT 10` |
| DuckDB-файл | `duckdb` | — | Тот же SELECT с LIMIT. |
| CSV/Parquet через DuckDB | `duckdb` | — | `SELECT * FROM '/data/smoke.parquet' LIMIT 10` либо соответствующий CSV. |

Для ClickHouse TLS-хостинга часто нужен иной явно заданный порт:
не оставлять 8123 автоматически при переходе на защищённый endpoint.
Для MSSQL `ssl=true` в основном ODBC-пути требует доверенного сертификата:
API не предоставляет отдельного переключателя TrustServerCertificate
или выбора CA. Прохождение локального `ssl=false` не удостоверяет TLS.

API принимает **канонические id**, а не подписи/alias: для Postgres Pro
посылать `postgresql`, для MariaDB — `mysql`.

### 3. Пример «Тест» и «Загрузить»

Создать локальный `db-test.json` для собственного тестового сервера:

```json
{
  "connection": {
    "db_type": "postgresql",
    "host": "127.0.0.1",
    "port": 5432,
    "database": "cisstat_test",
    "user": "cisstat_ro",
    "password": "REPLACE_WITH_TEST_PASSWORD",
    "ssl": false
  }
}
```

```bash
curl -sS -H 'Content-Type: application/json' \
  --data-binary @db-test.json \
  http://127.0.0.1:8000/v1/internal/upload/db/test
```

Успех — **`ok:true`**, а не просто HTTP 200. Неверный пароль,
отсутствующий драйвер и недоступный сервер могут дать HTTP 200 с
`ok:false`. Версия best-effort: её отсутствие при `ok:true` не означает
провала основного SELECT 1, но vendor-проверка тогда не завершена.

Для `db-load.json` добавить на верхнем уровне:

```json
{
  "connection": {
    "db_type": "postgresql", "host": "127.0.0.1", "port": 5432,
    "database": "cisstat_test", "user": "cisstat_ro",
    "password": "REPLACE_WITH_TEST_PASSWORD", "ssl": false
  },
  "sql": "SELECT date, value FROM cisstat_smoke ORDER BY date LIMIT 10",
  "row_limit": 5
}
```

```bash
curl -sS -c db-cookies.txt -b db-cookies.txt \
  -H 'Content-Type: application/json' --data-binary @db-load.json \
  http://127.0.0.1:8000/v1/internal/upload/db/load

curl -sS -b db-cookies.txt http://127.0.0.1:8000/v1/progress/trace
```

Проверить: `rows=5`, две колонки, ожидаемые значения preview,
непустые `columns_info`/`quality`, cookie `cisstat_session_id`,
событие `upload_completed`. После этого открыть локальную standalone
с **тем же API и браузерной cookie-сессией** и пройти обычные остановки.
Cookie curl не попадает в браузер автоматически; для исследования
данных в UI удобно отправлять POST из same-origin браузерного клиента
или импортировать cookie вручную в собственном тестовом окружении.

Embedded-профиль вместо серверных полей:

```json
{
  "connection": {"db_type": "sqlite", "path": "/data/smoke.sqlite"},
  "sql": "SELECT date, value FROM cisstat_smoke ORDER BY date LIMIT 10",
  "row_limit": 5
}
```

Для `/test` оставить только `connection`. Для DuckDB заменить id и путь.

**Самая короткая проба handshake+чтения без создания таблицы:**
после успешного `/test` передать `/load` SQL `SELECT 1 AS value`.
Это проверит получение DataFrame и регистрацию датасета, но не права
на конкретную таблицу, корректность дат и реальную выборку.

### 4. Проверка через размещённую standalone

По `apps/standalone/next.config.mjs` прокси имеет вид:

```text
https://ts-standalone.vercel.app/api/v1/internal/upload/db/test
https://ts-standalone.vercel.app/api/v1/internal/upload/db/load
```

Это **POST**, тот же JSON, cookie с `credentials: "include"`.
Например, из DevTools собственной открытой платформы:

```javascript
const connection = {
  db_type: "postgresql", host: "YOUR_REACHABLE_TEST_DB_HOST", port: 5432,
  database: "cisstat_test", user: "cisstat_ro", password: "TEST_PASSWORD", ssl: true
};
const tested = await fetch("/api/v1/internal/upload/db/test", {
  method: "POST", credentials: "include",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({connection})
}).then(r => r.json());
console.log({ok: tested.ok, version: tested.server_version, error: tested.error});
```

Только после `ok:true` выполнить аналогичный `/load` с SQL и row_limit.
Результат попадёт в эту браузерную сессию. Тестовые креды не включать
в отчёты/скриншоты. Само GET-открытие URL в адресной строке не запускает
проверку подключения.

В настоящем аудите внешних POST не выполнялось: read-only GET по
правильному proxy-адресу дал 405, что совместимо с POST-маршрутом, но
**не доказывает** развёртывание данного коммита или рабочий DB-driver.
GET `/health` и `/openapi.json` на указанном в конфиге Render-host
истекли по таймауту. Из этого нельзя заключить, что сервис отсутствует:
deployment и сеть требуют отдельной проверки. Проверка прямого Render
host также не равна проверке фактического `API_URL` в настройках Vercel.

### 5. Негативные и повторные пробы

Для каждого настоящего сервера: неверный пароль → `/test ok:false`,
`/load 400`; запретный SQL → 422; повтор Test→Load; правильные/неправильные
TLS-настройки; таблица без SELECT-grant; 12 строк при `row_limit=5`.
Проверять значения и warning усечения, а не только код HTTP.
Настройка `UPLOAD_DB_HOST_WHITELIST` относится к процессу API; CIDR
проверяет введённые IP, DNS-имена не резолвятся для проверки CIDR.

## Что проверено заново

Команда существующего корпуса:

```bash
python -m pytest tests/unit/test_db_connectors.py tests/unit/test_db_guard.py \
  tests/unit/test_db_embedded.py tests/unit/test_db_connection.py \
  tests/unit/test_upload_db9_docs.py tests/api/test_upload_db.py -q --disable-warnings
```

Результат: **248 passed / 1 failed**. Единственное падение:
`TestUploadDb7DriverHandoff.test_module_importable_without_pyodbc_pymysql`.
Дочерний процесс блокирует `pyodbc` и `pymysql`, но затем утверждает,
что `pymssql` тоже отсутствует, хотя не блокирует его. В окружении с
установленным разрешённым fallback это неверное ожидание теста.
Тест не переписывался и не скрывался. Реального подключения к SQL Server
этот тест не выполняет.

Собственные пробы `scripts/database_connections_audit.py`:

| Проба | Наблюдение |
|---|---|
| SQLite-файл → Test→Load | Настоящий файловый SQLite, 12→5 строк, warning, cookie, upload event, DELETE=422. |
| DuckDB-файл → Test→Load | То же на настоящем DuckDB-файле. |
| CSV через DuckDB → Test→Load | То же при прямом чтении CSV. |
| Parquet через DuckDB → Test→Load | То же при прямом чтении Parquet. |
| Серверная матрица | Настоящие PG/Postgres Pro/CH/MySQL/MariaDB/MSSQL не подключались: серверы и креды не предоставлены. Unit-моки не заменяют эти испытания. |
| MSSQL окружение | В этой песочнице `pyodbc` не импортируется из-за отсутствующего libodbc.so.2; `pymssql` импортируется. Docker отсутствует. Это факт среды, не доказательство дефекта Docker-образа. |

Зависимости добавлены только в отдельный scratch-каталог:
SQLAlchemy 2.1.5, DuckDB 1.5.6, duckdb-engine 0.17.0,
clickhouse-connect 1.11.0, PyMySQL 1.2.3, cryptography 50.0.2,
pyodbc 5.3.0, pymssql 2.4.4. Основа: Python 3.12.14, pytest 9.1.1,
FastAPI 0.143.0, pandas runtime 2.3.3. Requirements проекта не менялись.
Полный регресс приложения и сборка не запускались: продуктовый код
не менялся, предмет этого прогона — аудит и DB-проверки.

## Подтверждённые замечания реализации

| ID / приоритет | Установлено | Значение для проверки / следующий шаг |
|---|---|---|
| DB-A1 / высокий | UPLOAD-DB-5/6/8 отсутствуют; серверные API-тесты используют моки. | Сейчас API-тестирование ручное. Выполнить стенд DB-8 и UI-форму DB-5/6; документационная сертификация не закрывает live-матрицу. |
| DB-A2 / высокий | `ssl=true/false` даёт одинаковые kwargs в `mssql+pymssql`: password + login_timeout. | Нельзя удостоверить TLS этим флагом для fallback. Нужна явная настройка encryption/проверки сертификата либо отказ неподдерживаемой гарантии; затем настоящий TLS integration test. |
| DB-A3 / средний | Query-timeout=60 передаётся PostgreSQL через statement_timeout и CH через send_receive_timeout; для MySQL read/write timeout отсутствуют, для MSSQL передан только login/connect timeout. | Общего 60-секундного query deadline для всех типов нет. В MSSQL fallback API драйвера отдельно имеет query timeout и encryption; в pyodbc нужен отдельный statement timeout. Исправить и испытать длительный SELECT в стенде. CH socket timeout не равен строгому общему deadline запроса. |
| DB-A4 / средний | Симуляция CH-сервера: из 12 строк сервер вернул ровно 5 согласно max_result_rows; `_load_clickhouse` помечает truncated только при len>limit, поэтому результат truncated=false. | Точный warning усечения на границе не доказан. Нужен limit+1/другая проверяемая стратегия и live CH тест. Сам контрпример синтетический, а не наблюдение настоящего CH. |
| DB-A5 / высокий | Сбой `_server_version` логируется как сырое `exc`, в обход mask_secrets. Собственный fake-secret остался в log, но не в HTTP-ответе. | Исправить логирование этой ветки, добавить caplog-тест с sentinel. Реальных паролей аудит не использовал. |
| DB-A6 / существенная граница | Server engines не включают server-side read-only transaction автоматически; защита — лексический guard плюс права пользователя. DuckDB по одному выбранному CSV позволил SELECT read_text другого собственного файла. | Это не sandbox выбранного файла. Справочная фраза «все открываются только на чтение» слишком сильна для серверных БД. Использовать SELECT-only grants; для недоверенного embedded-доступа потребуется ограничение файлов/расширений/внешних обращений. Подтверждение сделано только на собственном marker-файле. |
| DB-A7 / средний | В API нет явного finally с engine.dispose()/native client.close() после Test/Load. | Жизненный цикл ресурсов не управляется явно, есть риск накопления до GC. Настоящее исчерпание соединений не измерялось; добавить repeated-probe интеграцию и явное освобождение. |
| DB-A8 / средний | Legacy PG Test выполняет SQLAlchemy 2 execute от сырой строки; Streamlit-селектор содержит только PG/CH. | Использовать новый API для приёмки; завершить DB-10 отдельно. |
| DB-A9 / тест | Import-safety test не изолирует установленный pymssql. | Исправить fixture, сохранив проверку импорта и отдельную проверку fallback. Это единственное наблюдаемое падение адресного корпуса. |

Возвращаемый row_limit ограничивает DataFrame, но не удостоверяет
ограничение вычислений/буферизации на сервере: SQLAlchemy-ветка использует
pandas chunksize без stream_results и без переписывания SQL в LIMIT/TOP.
Для первых живых проб использовать маленький SQL с LIMIT/TOP, как выше.

У DB-датасета `dataset_fingerprint` пуст: он не сохраняется как исходный
файл для raw restore. Продолжение исследования в текущей сессии работает;
восстановление после потери сессии не следует выводить из успешного Load.

## Рекомендуемый следующий шаг

Сначала закрыть DB-A2/A3/A5 и тестовую изоляцию; затем выполнить
UPLOAD-DB-8 с настоящими серверами, контрольными таблицами, pytest
integration и зафиксированной матрицей vendor/driver/TLS/Test/Load.
Параллельно по отдельной команде — DB-5/6, чтобы тот же маршрут стал
доступен пользователю через интерфейс. Автоматический стенд и UI в
настоящем аудите не реализовывались; продуктовый код не менялся.
