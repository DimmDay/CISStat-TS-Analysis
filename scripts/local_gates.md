# Локальные гейты перед передачей в GitHub

База AUTH-08: `76eb8db`. Источник исполняемых команд — `scripts/local_gates.py`, список: `python scripts/local_gates.py --list`.

Обычный прогон: `python scripts/local_gates.py`. После установленного окружения: `python scripts/local_gates.py --skip-install`. В main по умолчанию включены auth08, auth06, auth07, auth05, auth04, auth03, auth02, auth01, auth00, rules, jest. Jest включает renderer build и typecheck обеих оболочек. Native SQL требует отдельных opt-in-гейтов; их отсутствие не является проверкой долговечности.

AUTH-08 отдельно:

```bash
python scripts/local_gates.py --only auth08,auth00 --skip-install
```

Live PostgreSQL (только одноразовая тестовая БД, НЕ рабочая БД сервера): задайте `CISSTAT_AUTH_TEST_DSN` через защищённое окружение, затем:

```bash
python scripts/local_gates.py --only auth08,auth08-postgres --skip-install
# либо добавить к стандартному прогону:
python scripts/local_gates.py --with-auth08-postgres --skip-install
```

Без DSN `auth08-postgres` завершается ошибкой, а не skip/PASS. CI `auth08.yml` обязательно выполняет native PostgreSQL 16/18; unit contracts — Ubuntu/Windows. Frontend AUTH-08 покрыт стандартными Jest/auth06-гейтами. `auth07` дополнительно проверяет импорт без Unix-only `resource`.

`auth00` проверяет inventory, исходники и паритет discovery с HEAD. Перед коммитом тимлида изменение HTTP/page/worker surface закономерно требует включения всех файлов; AUTH-08 не добавляет HTTP/page/worker routes. Новая вручную reviewed operator boundary не подменяет HTTP-маршрут. После коммита на локальной машине повторите гейты до push; pull/build на VM — только после зелёного CI.

Next production builds проверяются отдельно: `npm run build:all`. Ошибка среды не считается успешной сборкой. Полный научный pytest при изменениях вычислительного слоя: `--with-pytest`; при средовых отказах сравниваются FAILED-ID на чистой базе той же среды.
