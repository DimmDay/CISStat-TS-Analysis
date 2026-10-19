# Протоколы UPLOAD-DB-FIX-UI-1

База: 354dfa5ea4e43cc0378dea9d96d03454eea28ae5. Исходники и тесты
поставляются относительно этой базы, без commit/push/deploy.

## Команды и окружение

Python: `PYTHONPATH=/workspace/scratch/1e71cf0e34de/db-audit-deps:/workspace/scratch/1e71cf0e34de/audit-runtime`.
Зависимости установлены только в scratch, production requirements не менялись.
Python 3.12.14, pytest 9.1.1, SQLAlchemy 2.1.5, DuckDB 1.5.6,
duckdb-engine 0.17.0, clickhouse-connect 1.11.0, PyMySQL 1.2.3,
pymssql 2.4.4. Для pyodbc в этой среде нет libodbc.so.2; граница timeout
проверена тестовым DBAPI connection, live MSSQL не заявляется.
Node 24.19.0, зависимости UI установлены `npm ci --ignore-scripts`.

`python_baseline.txt` / `python_final.txt`:

```bash
python -m pytest tests/api tests/unit tests/integration -q --disable-warnings
```

Финальный прогон дополнительно задаёт `-o faulthandler_timeout=45` для
диагностики зависаний. `python_delta.txt` сравнивает поимённые FAILED/ERROR,
а не только суммы: новых нет, удалено одно старое падение изоляции pymssql.
В окружении отсутствуют необязательные model dependencies и snapshot
fixture; subprocess-проверки образа сбрасывают scratch PYTHONPATH и не
находят fastapi. Эти и остальные прежние отрицательные результаты оставлены
в полном протоколе, за зелёную общую сборку/регрессию не выдаются.

`backend_addressed_green.txt`:

```bash
python -m pytest tests/unit/test_db_connectors.py tests/unit/test_db_guard.py tests/unit/test_db_embedded.py tests/unit/test_db_connection.py tests/unit/test_db_upload_fixes.py tests/unit/test_upload_db9_docs.py tests/api/test_upload_db.py -q --disable-warnings
```

`jest_baseline.txt` / `jest_final.txt`: `npx jest --runInBand`.
Адресный `ui_addressed_green.txt`: DbConnectionForm, TsAnalysisUpload.database,
NavigatorSourceFileDbPreview и прежний TsAnalysisUpload.test.tsx.
`navigator_parent_green.txt`: весь TsAnalysisNavigator.test.tsx.
`typecheck.txt`: `npm run typecheck:all`.
`build_embedded.txt`: `npm run build:all` (останавливается на embedded).
`build_standalone.txt`: отдельный build standalone.
`node_memory_environment.txt`: `node -e 'console.log(process.memoryUsage())'`
воспроизводит системный ENOENT независимо от приложения.

## RED → GREEN

- `backend_red.txt`: 11 новых backend-проверок падают на неисправленной базе.
- `ui_red.txt`: отсутствует новый компонент (TS2307), сюит не запускается.
- `integration_red.txt`: прежняя заглушка вместо формы, 1 падение.
- `navigator_red.txt`: пины шести источников/нового общего пути против старой схемы.
- `ui_s4_red.txt`: 2 падения проверки дефолта формы, затем исправлен лимит S4.
- GREEN: 260 backend, 77 UI и 87 тестов родителя навигатора.

Логи используют искусственные sentinel-пароли и тестовые источники.
Реальные серверные доступы не предоставлялись; Docker недоступен.
Финальные сводки приведены в worklog/worklog10.md и отчёте docs/.
