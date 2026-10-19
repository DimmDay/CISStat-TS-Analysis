# UPLOAD-DB-FIX-UI-1 — исправления аудита и рабочая форма БД

База: `354dfa5ea4e43cc0378dea9d96d03454eea28ae5`. Отдельная detached-копия;
прежние рабочие копии и их незакоммиченные изменения сохранены.
Задача выполнена по `AGENTS.md`, `spec_database_plan.md` (S2/S3/S4,
UPLOAD-DB-5/6), с учётом аудита в конце `worklog/worklog10.md`.

## Проект решения и риски

Исправления выполняются в существующем реестре коннекторов и SQL guard.
Форма переиспользует готовые `/upload/db/test` и `/upload/db/load`;
результат проходит общий с файловой загрузкой приём `UploadResponse`.
Схемы API, события трассы и вычисление статусов «Прогресса» не расширяются.

| Риск / требование | Решение | Проверка |
|---|---|---|
| MSSQL fallback игнорирует TLS | `pymssql`: `encryption=require/off`; нужен pymssql >=2.2.8 | kwargs при ssl=True/False; ошибка несовместимого драйвера не превращается в downgrade |
| Query timeout не доходит до драйвера | MySQL: read/write_timeout; pymssql: timeout; pyodbc: Connection.timeout через connect event | отдельные connect=3 / query=7; callback нового DBAPI connection |
| ClickHouse теряет warning на границе | Запрос `max_result_rows=limit+1`, затем клиентский срез до limit | результаты 0, limit−1, limit, limit+1, больше limit |
| Version probe пишет секрет в лог | `mask_secrets` перед logger | HTTP и захваченный log не содержат owned sentinel |
| Раздельные пути файла и БД расходятся | общий `acceptUploadedData`, общий DTO | реальная форма + родитель: preview, shell, target, refresh, upload-stops |
| Пароль остаётся после переключения | креды только в React state, очистка при смене типа/успешной загрузке | смена режима, отсутствие server-полей в embedded payload |
| Повторная отправка / поздний ответ | busy/ref guard, AbortController, mounted guard | отключённые кнопки, unmount отменяет запрос |
| Ресурсы соединения живут до GC | API `finally`: dispose/close, маскированные ошибки cleanup | probe c ошибкой версии освобождает engine |

TLS `require` в pymssql запрещает незашифрованное соединение; политику проверки
CA/имени задаёт FreeTDS. MySQL read/write timeout ограничивает операции сети,
а не гарантирует единый wall-clock deadline SQL/HTTP. FreeTDS может применять
таймауты на уровне процесса. Это явно описано в справке.

## Что реализовано

`DbConnectionForm` предлагает PostgreSQL / Postgres Pro, ClickHouse,
MS SQL Server, MySQL / MariaDB, DuckDB и SQLite. Четыре серверных профиля
имеют host/port/database/user/password/TLS; два встроенных — путь на сервере
API. Дефолт-порты: 5432/8123/1433/3306. Начальный SQL: TOP (1000) для MSSQL,
LIMIT 1000 для остальных; для CSV/Parquet в DuckDB подставляется экранированный
путь. Пользовательский SQL сохраняется при редактировании пути.

Лимит формы — 1 000 000 (S4), сервер дополнительно ограничивает его env-потолком.
«Тест подключения» показывает версию/latency только при `ok=true`;
HTTP 200 с `ok=false` — отказ. «Загрузить из БД» принимает штатный
`UploadResponse`, обновляет предпросмотр, статистики, исследуемый признак,
AppShell и сессию; существующий механизм отправляет статусы остановок.
Оба запроса передают first-party cookie через `credentials: include`.

В форме есть связанные label/input, клавиатурная отправка, role=status/alert,
адаптивная сетка и общие цветовые токены платформы. Навигатор показывает
шесть источников, server/embedded и реальный общий путь регистрации.
README, ARCHITECTURE, справка и smoke checklist приведены к реализации.

## Практическая приёмка

1. Установить зависимости API и UI, запустить API и standalone с настроенным
   API_URL согласно README. Для MSSQL нужны ODBC Driver 18 + pyodbc либо
   явно выбранный `UPLOAD_DB_MSSQL_DRIVER=pymssql` и pymssql >=2.2.8.
2. В «Загрузка» выбрать «База данных (SQL)», тип и параметры.
   Host и embedded path относятся к машине API, а не браузера.
3. Нажать «Тест подключения». Затем заменить `your_table` реальной таблицей,
   задать SELECT/WITH и нажать «Загрузить из БД».
4. Проверить строки preview, типы/качество, выбранный признак и «Прогресс»;
   после перезагрузки страницы датасет должен восстановиться из сессии.
5. Повторить для всех шести типов; Postgres Pro и MariaDB проверять отдельно
   от PostgreSQL и MySQL, MSSQL — обоими драйверами. Для DuckDB проверить
   .duckdb/.csv/.parquet. Лимит L испытать на L и L+1 строках, DELETE должен
   вернуть 422, неверные креды — маскированный отказ.

Полная server/vendor/TLS матрица требует собственных доступных серверов.
Автоматического docker-compose стенда UPLOAD-DB-8 пока нет. В этой среде
серверные handshake/TLS и браузерная визуальная приёмка не удостоверены.
Проверки здесь включают настоящие SQLite/DuckDB API-тесты и симуляцию
границы драйверов; утверждение о live-подключении ко всем БД не делается.

## Воспроизводимость и результаты

Протоколы находятся в `scripts/db_form_validation/`. RED выполнен до
продуктовых исправлений; отдельный RED лимита формы проверяет S4.

Команды из корня (в обычном окружении с установленными зависимостями):

```bash
python -m pytest tests/unit/test_db_upload_fixes.py tests/unit/test_db_connectors.py tests/unit/test_db_guard.py tests/unit/test_db_embedded.py tests/unit/test_db_connection.py tests/unit/test_upload_db9_docs.py tests/api/test_upload_db.py -q
npx jest --runInBand
npm run typecheck:all
npm run build:all
python -m pytest tests/api tests/unit tests/integration -q --disable-warnings
```

| Проверка | До изменений | Финальный результат |
|---|---|---|
| DB unit/docs/API | прежний дефект изоляции pymssql | 260 passed |
| UI: форма + интеграция + upload + схема | новая форма отсутствовала | 77 passed |
| Родитель навигатора | пин прежних двух типов | 87 passed |
| Полный Jest | 1 failed, 2175 passed, 193 suites | 2189 passed, 195 suites |
| Полный Python | 100 failed, 3743 passed, 65 skipped, 3 errors | 99 failed, 3755 passed, 65 skipped, 3 errors |
| TypeScript обоих приложений | — | без ошибок |
| Production build обоих приложений | — | блокирован системным ENOENT |

Поимённое сравнение полного Python: новых FAILED/ERROR нет, прежнее падение
изоляции pymssql устранено (сабпроцесс теперь блокирует все три драйвера).
Прежние 99 падений и 3 ошибки сохранены, общая Python-регрессия не зелёная.
Первый общий Jest-прогон выявил устаревший пин родителя навигатора и
падение EDA S4; пин обновлён для шести типов, код EDA не менялся, финальный
полный прогон проходит. Отрицательные протоколы также сохранены.
Подробности — в записи UPLOAD-DB-FIX-UI-1 в `worklog/worklog10.md`.
Production build нужно повторить вне текущей песочницы: Next.js прекращает
сборку на системном `ENOENT: uv_resident_set_memory`, воспроизводимом
вызовом `process.memoryUsage()` без приложения. Гварды сборки не отключались.

ZIP содержит только новые/изменённые файлы задачи и manifest SHA256.
Commit, push и deploy не выполнялись.

## Пути поставки

- `ARCHITECTURE.md`
- `README.md`
- `app/data/db_connectors.py`
- `app/data/db_guard.py`
- `apps/api/routers/upload_db.py`
- `docs/database_fixes_form_2026-10-19.md`
- `docs/upload_db_connections_help.md`
- `docs/upload_db_release_smoke_checklist.md`
- `packages/ui/components/DbConnectionForm.test.tsx`
- `packages/ui/components/DbConnectionForm.tsx`
- `packages/ui/components/NavigatorSourceFileDbPreview.test.tsx`
- `packages/ui/components/NavigatorSourceFileDbPreview.tsx`
- `packages/ui/components/TsAnalysisNavigator.test.tsx`
- `packages/ui/components/TsAnalysisUpload.database.test.tsx`
- `packages/ui/components/TsAnalysisUpload.tsx`
- `packages/ui/lib/upload.ts`
- `tests/unit/test_db_connectors.py`
- `tests/unit/test_db_guard.py`
- `tests/unit/test_db_upload_fixes.py`
- `tests/unit/test_upload_db9_docs.py`
- `worklog/worklog10.md`
- `scripts/db_form_validation/` — README, RED/GREEN, базовые и итоговые протоколы.

Полный пофайловый перечень с SHA256 — `MANIFEST.sha256` в ZIP.
