# Подключение к базам данных (SQL) — справка платформы CISStat TS Analysis

> Раздел «Обучение» · эпик UPLOAD-DB · задача UPLOAD-DB-9 (spec_database_plan.md, фаза D «выпуск»).
> Справка — перенос и развитие legacy-подсказки «Как работать с платформой» (app.py:812–918:
> настройка серверов PostgreSQL, ClickHouse, устранение частых проблем) на утверждённую
> матрицу шести СУБД. Документация проверяется тестом-гвардом `tests/unit/test_upload_db9_docs.py`
> против кода: `app/data/db_connectors.py` (реестр коннекторов), `app/data/db_guard.py`
> (безопасность ядра), `apps/api/routers/upload_db.py` (API-контракт).

Платформа подключается к базе данных, исполняет **ровно один запрос чтения** и регистрирует
выборку как датасет — дальше она проходит тот же пятиостановочный пайплайн «Загрузки», что и
файл: превью, справка по колонкам, teaser качества, подтверждение автоопределения. Источник —
радио-переключатель «Файл / База данных (SQL)» на странице «Загрузка»; для БД задаются
параметры подключения и SQL-запрос с подсказкой `LIMIT`. Обе встроенные СУБД (DuckDB, SQLite)
и четыре серверные (PostgreSQL / Postgres Pro, ClickHouse, MS SQL Server, MySQL / MariaDB)
открываются **только на чтение** — платформа является потребителем данных, а не их владельцем.

## Матрица поддерживаемых СУБД (реестр `app/data/db_connectors.py`)

| СУБД (label реестра) | Режим | Диалект / клиент | Порт по умолчанию | Драйвер (pip) |
|---|---|---|---|---|
| PostgreSQL / Postgres Pro | server | `postgresql+psycopg` | 5432 | `psycopg[binary]` (v3, скоуп-решение S1) |
| ClickHouse | server | нативный клиент `clickhouse-connect` | 8123 | `clickhouse-connect` |
| MS SQL Server | server | `mssql+pyodbc` | 1433 | `pyodbc` + ODBC Driver 18; fallback `pymssql` (S2) |
| MySQL / MariaDB | server | `mysql+pymysql` | 3306 | `PyMySQL` + `cryptography` |
| DuckDB (встроенная) | embedded | `duckdb` (файл) | — | `duckdb duckdb-engine` |
| SQLite (встроенная) | embedded | `sqlite` (файл) | — | входит в стандартную библиотеку Python |

PostgreSQL и Postgres Pro — **одна запись реестра**: протокол совместим, вендор и версия
различаются автоматически контрольным запросом `SELECT version()` (подсказка «протокол
PostgreSQL» в UI). MariaDB распознаётся через алиасы записи MySQL — `SELECT VERSION()`
возвращает версию MariaDB тем же запросом. Aliases реестра (`postgres`, `pg`, `postgrespro`,
`ch`, `mariadb`, `sqlite3`, `sqlserver` и др.) — удобство резолюции; API принимает только
канонические `id` (`postgresql`, `clickhouse`, `mssql`, `mysql`, `duckdb`, `sqlite`).

SQL-запрос загрузки идёт через read-only guard ядра (D6): разрешены только `SELECT` и `WITH`,
запрещены мультистейтменты, DML/DDL-конструкции (в том числе внутри CTE PostgreSQL), блокировки
строк `FOR UPDATE / FOR SHARE` и известные опасные функции (`pg_sleep`, `pg_read_file`,
`dblink` и т.п.). Желаемый лимит строк жёстко ограничен env-потолком
`UPLOAD_DB_ROW_LIMIT` (дефолт 1 000 000, скоуп-решение S4), чтение выполняется
chunksize-стримингом без материализации всего результата в памяти.

## PostgreSQL / Postgres Pro

Драйвер — psycopg v3 (`postgresql+psycopg`), скоуп-решение S1; строка соединения собирается
без пароля (D4: пароль уходит через `connect_args`, в URL и в тексты исключений не попадает).
TLS-флаг формы управляет `sslmode`: включён — `require`, выключен — `disable` (находка D3:
legacy-прототип не задавал sslmode явно, поведение зависело от сервера).

**Настройка сервера (`postgresql.conf`):**

```conf
listen_addresses = '*'          # разрешить внешние подключения (или адрес платформы)
port = 5432                     # стандартный порт
password_encryption = scram-sha-256
ssl = on                        # если используется TLS-флаг подключения
```

**Настройка доступа (`pg_hba.conf`)** — разрешите подсеть платформы и потребуйте пароль:

```conf
# TYPE  DATABASE  USER  ADDRESS          METHOD
host    all       all   192.168.1.0/24   scram-sha-256
hostssl all       all   192.168.1.0/24   scram-sha-256   # если ssl = on
```

После правок перечитайте конфигурацию: `SELECT pg_reload_conf();` либо `systemctl reload
postgresql`. Убедитесь, что пользователь БД создан и имеет пароль:

```sql
CREATE ROLE cisstat_ro LOGIN PASSWORD '...' ;
GRANT CONNECT ON DATABASE analytics TO cisstat_ro;
GRANT USAGE ON SCHEMA public TO cisstat_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cisstat_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cisstat_ro;
```

**Рекомендация (риск RP4):** подключайтесь выделенным **read-only пользователем**. Lexический
guard платформы отсекает DML/DDL и опасные функции, но серверная защита правами пользователя —
вторая линия обороны, независимая от лексического анализа: даже непредвиденная функция чтения
с побочными эффектами не сможет исполниться. Выдача только `SELECT`-привилегий (см. выше)
делает ограничение структурным.

Postgres Pro и производные (TimescaleDB, Greenplum) работают по протоколу PostgreSQL —
отдельной настройки не требуют; вендор показывается в ответе «Тест» (`server_version` из
`SELECT version()`).

## ClickHouse

Драйвер — нативный клиент `clickhouse-connect` (как в legacy-прототипе), не SQLAlchemy.
TLS-флаг управляет параметрами `secure`/`verify` одновременно (D3: включён — трафик шифруется
и сертификат сервера проверяется; выключен — поведение паритетно legacy, открытым текстом).
Контрольный запрос «Тест» — `SELECT 1` + `ping`; версия сервера — `SELECT version()`.

**Настройка пользователя (users.xml)** — создайте профиль с паролем и подсетью платформы:

```xml
<users>
    <cisstat_ro>
        <password_sha256_hex>...</password_sha256_hex>  <!-- или <password> -->
        <networks><ip>192.168.1.0/24</ip></networks>
        <profile>readonly</profile>
        <grants><query>SELECT</query></grants>
    </cisstat_ro>
</users>
```

Современные установки (ClickHouse ≥ 22.x) предпочитают SQL-синтаксис вместо правки
`users.xml`:

```sql
CREATE USER cisstat_ro IDENTIFIED BY '...' SETTINGS readonly = 2;
GRANT SELECT ON analytics.* TO cisstat_ro;
```

`readonly = 2` разрешает чтение и запретит изменение настроек сессии — соответствует
рекомендации read-only кред (RP4). Платформа обращается на **HTTP-порт 8123** (не native
9000): проверьте, что порт открыт на фаерволе и что `<http_port>8123</http_port>` не
переопределён в конфигурации сервера.

Пример аналитического запроса с подсказкой LIMIT (перенос из UI_HELP):

```sql
SELECT
    toStartOfDay(timestamp) AS date,
    avg(value) AS metric
FROM events
WHERE date >= '2024-01-01'
GROUP BY date
ORDER BY date
LIMIT 10000
```

## MS SQL Server

Драйвер — `mssql+pyodbc` с системным **ODBC Driver 18 for SQL Server** (скоуп-решение S2:
официальная поддержка Microsoft). Пароль не включается в URL (D4) — передаётся через
`connect_args["PWD"]` с ODBC-экранированием спецсимволов (`;`, `{`, `}`); TLS-флаг управляет
`Encrypt=yes` + `TrustServerCertificate=no` (включён) либо `Encrypt=no` (выключен).

**Настройка сервера:**

1. Включите протокол **TCP/IP** (SQL Server Configuration Manager → SQL Server Network
   Configuration → Protocols) и перезапустите службу; порт по умолчанию 1433.
2. Включите **SQL-аутентификацию** (Server Properties → Security → «SQL Server and Windows
   Authentication mode») и задайте пароль пользователя.
3. Создайте пользователя только для чтения:

```sql
CREATE LOGIN cisstat_ro WITH PASSWORD = '...';
USE analytics;
CREATE USER cisstat_ro FOR LOGIN cisstat_ro;
EXEC sp_addrolemember 'db_datareader', 'cisstat_ro';   -- только SELECT
```

**Установка драйвера ODBC Driver 18:**

- Linux (контейнер apps/api): слой уже собран в `apps/api/Dockerfile`; в закрытом контуре без
  apt-репозитория Microsoft собирайте с `--build-arg INSTALL_MSODBCSQL18=false` и переводите
  MSSQL на fallback-драйвер `pymssql` (чистый pip, RP2): `pip install pymssql` и env
  `UPLOAD_DB_MSSQL_DRIVER=pymssql`. Резолюция драйвера: явный параметр → env → авто по
  доступности (pyodbc → pymssql), неверное значение env даёт громкий `ValueError`.
- Windows: установите «ODBC Driver 18 for SQL Server» с сайта Microsoft.

Только ODBC Driver 17 и ниже используют `TrustServerCertificate=yes` по умолчанию; драйвер 18
требует явного согласия на самоподписанный сертификат — именно поэтому платформа выставляет
`Encrypt`/`TrustServerCertificate` по TLS-флагу, а не «как получится».

## MySQL / MariaDB

Драйвер — `mysql+pymysql`; пин `cryptography` обязателен: MySQL 8 по умолчанию использует
аутентификацию `caching_sha2_password`, которую PyMySQL реализует только при наличии пакета
(в метаданных PyMySQL extra `cryptography` не существует — пин отдельный, уточнение UPLOAD-DB-7).
TLS-флаг управляет PyMySQL-флагами: включён — `ssl_verify_cert=True` (сертификат сервера
проверяется), выключен — `ssl_disabled=True` (D3).

**Создание пользователя и права:**

```sql
CREATE USER 'cisstat_ro'@'192.168.1.%' IDENTIFIED BY '...';
GRANT SELECT ON analytics.* TO 'cisstat_ro'@'192.168.1.%';
FLUSH PRIVILEGES;
```

**Настройка сервера (`mysqld.cnf` / `mysqld.cnf.d/bind.cnf`):**

```conf
bind-address = 0.0.0.0        # или адрес интерфейса платформы
port = 3306
# mysqlx_bind_address — при необходимости также для X-протокола
```

Для MariaDB синтаксис тот же; `SELECT VERSION()` вернёт строку `…-MariaDB…`, вендор
показывается в ответе «Тест». Если сервер старше MySQL 8 и использует
`mysql_native_password`, пин `cryptography` не мешает — он используется только по требованию
сервера.

## Встроенные СУБД: DuckDB и SQLite

Обе СУБД открываются **по пути к файлу на серверной ФС** (скоуп-решение S3: drag-and-drop
`.duckdb`/`.parquet` файлов вне v1) и **строго read-only** — платформа не создаёт, не
изменяет и не удаляет данные источника:

- **SQLite** (`.db`, `.sqlite`) — URI `file:…?mode=ro&uri=true`: операции записи на уровне
  файла невозможны;
- **DuckDB** (`.db`, `.duckdb`) — соединение `read_only=True`;
- **DuckDB по Parquet/CSV** (`.parquet`, `.csv`) — файл читается прямым
  `SELECT * FROM '<путь>'` без запуска сервера; контрольный запрос «Тест» честно читает
  первую строку самого файла.

Путь раскрывается с `~` (домашний каталог), расширение валидируется по таблице выше, файл
должен существовать. Контейнерный деплой: файл должен быть виден внутри контейнера
apps/api (смонтированный том либо путь в образе) — сетевого доступа у встроенных СУБД нет.

## Безопасность и лимиты платформы (что стоит знать владельцу источника)

| Механизм | Код | Поведение |
|---|---|---|
| Read-only guard | `app/data/db_guard.py::validate_readonly_sql` (D6) | только `SELECT`/`WITH`; запрет мультистейтментов, DML/DDL (вкл. внутри CTE), `FOR UPDATE/SHARE`, опасных функций; нарушение → 422 |
| Потолок строк | env `UPLOAD_DB_ROW_LIMIT`, дефолт 1 000 000 (S4) | запрос вызывающего жёстко обрезается потолком; усечение честно помечается в `parse_warnings` |
| Стриминг | env `UPLOAD_DB_CHUNKSIZE`, дефолт 50 000 | чтение чанками, без материализации всего результата |
| Таймауты | env `UPLOAD_DB_CONNECT_TIMEOUT` = 10 с, `UPLOAD_DB_QUERY_TIMEOUT` = 60 с (S4) | соединение и запрос не зависают; PG — `statement_timeout`, MSSQL — login-таймаут, CH — send/receive |
| Белый список хостов | env `UPLOAD_DB_HOST_WHITELIST` (D5/SSRF, S5) | пусто или `*` — off (песочница); список хостов/CIDR через запятую — вне списка отклоняется (`HostNotAllowed` → 422) |
| Маскирование секретов | `mask_secrets` (D4) | пароль не включается в URL ни для одной СУБД; в ошибках и логах заменяется на `****` |
| Драйвер MSSQL | env `UPLOAD_DB_MSSQL_DRIVER` (S2/RP2) | `pyodbc` (основной) \| `pymssql` (fallback); авто-резолюция по доступности |
| Read-only креды | рекомендация RP4 | выделенный пользователь БД с правами только `SELECT` — серверная защита поверх лексического guard'а |

Контрольный запрос «Тест» (`SELECT 1`) сознательно не создаёт сессию и не попадает в трассу —
фактом анализа считается только загрузка датасета. Ответ «Тест» отдаёт `ok`, `db_type`,
`server_version` (вендор-детекция PG-семейства) и `latency_ms`; отрицательный результат пробы —
это `200 {ok: false, error: маскированная причина}`, а не серверная ошибка.

## Устранение частых проблем

| Ошибка | Причина | Решение |
|---|---|---|
| `Не удалось подключиться к …` / `Connection timed out` | фаервол, `listen_addresses`/`bind-address`, `pg_hba.conf` | проверьте доступность host:port (5432/8123/1433/3306) с машины apps/api, правила pg_hba/bind-адрес |
| `authentication failed` | неверный пароль или метод аутентификации | пароль в форме; метод в `pg_hba.conf` (`scram-sha-256`/`md5`); MySQL 8 — см. `caching_sha2_password` |
| `Не установлен драйвер … Установите: pip install "…"` | драйвер СУБД не установлен в контуре | установите pip-пакет из таблицы матрицы; MSSQL — ODBC Driver 18 или fallback `pymssql` + `UPLOAD_DB_MSSQL_DRIVER=pymssql` |
| `Can't open lib 'ODBC Driver 18 for SQL Server'` | системный ODBC-драйвер отсутствует | установите msodbcsql18 (см. раздел MSSQL) или перейдите на pymssql-fallback |
| MySQL 8: `Authentication plugin 'caching_sha2_password' cannot be loaded` | нет пакета `cryptography` | `pip install "PyMySQL>=1.1.0" "cryptography>=41.0.0"` |
| `Хост … не входит в белый список UPLOAD_DB_HOST_WHITELIST` | D5/SSRF-защита включена | добавьте хост в env `UPLOAD_DB_HOST_WHITELIST` (хосты/CIDR через запятую) или выключите guard (пусто/`*`) в песочнице |
| `Запрещённая конструкция «INSERT»` / `Мультистейтмент запрещён` | read-only guard (D6) | отправьте один запрос чтения `SELECT`/`WITH`; загрузка данных на изменение не поддерживается платформой |
| `Выборка ограничена лимитом … строк` | сработал потолок S4 | уточните запрос (`WHERE`, агрегаты) или поднимите `UPLOAD_DB_ROW_LIMIT` с учётом памяти |
| `Недопустимое расширение …` / `Файл не найден` | embedded-путь | проверьте расширение (.db/.sqlite/.duckdb/.parquet/.csv) и видимость файла из контура apps/api |
| Таймаут запроса (60 с) | тяжёлый запрос | добавьте `LIMIT`, агрегируйте на стороне СУБД, проверьте индексы; при необходимости env `UPLOAD_DB_QUERY_TIMEOUT` |

## Ссылки

- Матрица СУБД, драйверы и env-лимиты в README: раздел «Загрузка из баз данных (SQL)».
- Архитектура реестра коннекторов: ARCHITECTURE.md, раздел «Реестр коннекторов БД».
- Смоук-чеклист релиза: `docs/upload_db_release_smoke_checklist.md`.
- Спека плана эпика: `spec_database_plan.md` (UPLOAD-DB-PLAN-1, задачи UPLOAD-DB-1…10).
