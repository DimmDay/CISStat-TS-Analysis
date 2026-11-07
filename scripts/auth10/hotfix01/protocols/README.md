# AUTH-10-HOTFIX01 — проверка составной поставки

Исходный cisstat-auth10-c13a52b.zip сохранён неизменным. c13a52b + ZIP без git add даёт ожидаемый строгий отказ (red-unstaged.txt): 4 HTTP methods, operator и fingerprints существуют только в worktree. Тимлид подтвердил отсутствие git add перед его прогоном; исходный полный Windows traceback не сохранился.

red-output.txt — новые оракулы на старом runner (порядок/лог/метаданные ошибки) RED. green-output.txt — финальные5/5: ранний и финальный parity fences, UTF-8 child при cp1251 parent, exit7, полный успешный log, прежний другой gate, FAILED STEP/путь лога/команды staging в сводке и неизменность index. Все тесты исполняются без production credentials/БД.

unstaged-runner.txt — ранний FAIL с подсказками нового runner. routes.txt / routes-runtime.txt — inventory и actual ASGI239/registry243/inventory572, unchanged methods/paths. ruff.txt — обновлённый runner/новые tests/packager; EXE001 исключён для существующего CLI, запускаемого через python. Compilation отдельно проверена compileall. Windows здесь не запускался; Unicode/codepage subprocess contract проверен на Linux, CI auth00.yml уже включает Windows/Ubuntu wildcard test_auth00*.py.

delivery.txt — чистый c13a52b → original ZIP → delta ZIP → явный git add обоих manifests → auth00/auth01/auth10/rules, включая49 AUTH-00 tests и обе INDEX parity проверки; независимый actual routes check. API/UI/SQL файлы составного overlay сравниваются byte-for-byte с original ZIP. После записи протокола/финального worklog delta перепакована и все байты/CRC/manifest сверены. Новых runtime changes нет; scientific/native PG/Jest/Next повторно не запускались: исходный runtime неизменён, ранее проверен и тимлидом отмечен PASS.
