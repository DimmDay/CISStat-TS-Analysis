# JEST-PORTABILITY — отказы после 781de34

Дата: 29.10.2026 (Europe/Moscow). База: `781de348decc9549919831039f51df32b3339142`.
Без commit/push. Рабочий процесс и поставка — по `AGENTS.md`.

## Причины и исправления

| Отказ | Причина | Исправление |
|---|---|---|
| Три shell-теста: `spawnSync /bin/sh ENOENT` | Тесты требуют абсолютный Unix-путь даже при запуске Node в Windows. До исполнения wrapper дело не доходит. | Проверяемый поиск POSIX shell: Unix `/bin/sh`, Windows — MSYS shell Git for Windows (PATH и стандартные каталоги). Проверяется возможность `/bin/mv`. Пути аргументов и путей внутри wrapper нормализуются для Git sh; на Unix буквальные backslash сохранены. |
| B1: команда `python3 …` возвращает только `Python` | Жёсткое имя команды, отсутствующее или указывающее на alias, не подтверждает работающий Python. Лог соответствует такому классу Windows-окружений; устройство машины пользователя здесь не исследовалось. | Выбор настоящего Python пробным исполнением; Windows: `python`, `py -3`, `python3`. `execFileSync` без промежуточного shell, `-X utf8` для кириллицы. Ошибка самого гварда распространяется, повтор другим интерпретатором не маскирует её. |
| B1 после восстановления Python: 62 ≠ 41 | Исходная запись PGV-07 в HEAD всё ещё заявляет 62/62. Поздняя запись JEST-505-FIX заявляет исправление, которого нет в исходной строке. | Исправлена именно исходная строка на фактические 41/41. Арифметический оракул и число проверок гварда сохранены. |
| Две suite: TS2307 `playwright-core` | Renderer workspace объявляет пакет, корневой Jest — нет. Полная корневая установка на Linux уже работает, но исключение workspace оставляет корень без пакета. Точная команда установки пользователя неизвестна. | Прямой root devDependency `playwright-core: 1.57.0`, тот же pin в renderer и lock. Без ambient-заглушек, глобальных пакетов и загрузки Chromium. |

`scripts/testing/runtimes.ts` содержит только инфраструктуру тестов.
`launchGuard.ts` получил нормализацию Windows-путей; Linux shell gate,
`set -eu`, атомарная запись PID, cancellation gate, SIGKILL группы и
контейнерный `/bin/sh` в `renderWorker.ts` сохранены.

## Проверки и риски

- Исходный адресный Linux-прогон после чистого `npm ci`: 1 failed / 64 passed;
  воспроизведён B1 (62 против 41). Остальные присланные ошибки зависят от
  установленных инструментов: в этой среде POSIX shell/Python доступны.
- Новые тесты проверяют Windows-ветви поиска на управляемых subprocess-ответах:
  alias вместо Python, `py -3`, резервный Python, стандартный и нестандартный
  Git, отсутствие инструмента, пути с пробелами/кавычками, UTF-8 и перенос
  nonzero-кода гварда. Прямой локальный pin проверяется отдельно от глобального.
- Первый запуск нового теста с `@jest-environment node` упал в старом
  `jest.setup.js` на `window`: это дефект настройки нового теста, не RED продукта.
  Аннотация снята, используется штатная jsdom-конфигурация. Ошибка spy на
  транспилированном namespace устранена CJS-доступом к `child_process`.
- Первый полный прогон: 236 passed / 1 failed suite, 2729 passed tests;
  новый runtime-suite не компилировался из-за глобального расширения
  `ProcessEnv.NODE_ENV` в Next. Исправлено определение env на
  `Record<string, string | undefined>`, лишние type assertions сняты.
  Диагностика TypeScript не отключалась; полный прогон повторён.
- Второй полный прогон: 1 failed / 2738 passed, все 237 suites исполнились.
  Предсуществующий PROGR-15-A Upload-тест ожидал любой первый POST до
  действия `warning → pending`; он мог наблюдать ещё pending до детекции.
  Изолированный исходный сценарий прошёл (1 passed / 45 filtered).
  Усилено предусловие: ждать фактического warning-отчёта, затем менять
  решение. Проверки >=2 POST, pending/done и правильных URL сохранены;
  таймауты не увеличивались, продуктовый Upload/hook не менялись.
  После уточнения весь Upload-файл прошёл 46/46.
- Содержательный RED root dependency получен на исходном `package.json`;
  итоговый файл восстановлен в `finally`. Отдельная чистая установка
  `npm ci --workspaces=false` с исходными manifests даёт MODULE_NOT_FOUND,
  с исправленными — локальную 1.57.0. `NODE_PATH` исключён из этой пробы:
  первая попытка обнаружила глобальную 1.62.1 и не считается доказательством.
- Реальные shell-кейсы выполняются, не заменены mock/skip. При отсутствии
  предпосылок тест падает с инструкцией установки. Добавлен обязательный
  CI matrix Ubuntu/Windows: весь Jest, renderer build, typecheck обеих apps.
- Нативная Windows-машина в этой сессии недоступна. Симуляция выбора инструмента
  не равна выполнению shell на Windows; новый CI workflow ещё не запускался.
- Chromium/final Docker image и production-сертификация PGV-08 этой задачей
  не пересматриваются. Renderer по-прежнему предназначен для Linux-контейнера.

Финал: **237/237 suites, 2739/2739 тестов**, 0 failed/skipped/runtime errors.
Адресный срез 76/76, Upload 46/46; renderer build и обе typecheck — PASS.
PGV-07 guard 41/41, PGV-08 guard 48/48. Обе production Next-сборки —
BLOCKED средой `ENOENT uv_resident_set_memory` (без обхода проверок памяти).

Итоговые числа и коды выхода — `scripts/jest-portability/protocols/` и запись
JEST-PORTABILITY в `worklog/worklog11.md`.

## Установка и воспроизведение

Распаковать ZIP поверх `781de34`. Из корня проекта (не папки отдельного frontend):

```sh
npm ci --include=dev --workspaces --include-workspace-root --ignore-scripts --no-audit --no-fund
npx jest --maxWorkers=2
npm run build --workspace=@cisstat/print-renderer
npm run typecheck:all
npm run build:all
```

На Windows нужны установленный Python 3 (рекомендуется 3.12) и Git for Windows
с POSIX shell. WSL launcher не используется. Для нестандартных установок можно
явно задать пути исполняемых файлов в PowerShell (без дополнительных аргументов):

```powershell
$env:CISSTAT_TEST_SH = 'D:\Tools\Git\bin\sh.exe'
$env:CISSTAT_TEST_PYTHON = 'D:\Tools\Python312\python.exe'
npx jest --maxWorkers=2
```

Эти переменные меняют только поиск инструментов тестов, не настройки renderer.
При исправной автоматической настройке они не нужны. При необходимости
убрать только их: `Remove-Item Env:CISSTAT_TEST_SH, Env:CISSTAT_TEST_PYTHON`.

Первичные справочные источники:

- [Node.js child_process: ENOENT](https://nodejs.org/api/child_process.html#event-error)
- [Python 3.12 в Windows: launcher и aliases](https://docs.python.org/3.12/using/windows.html)
- [npm install: workspaces и include-workspace-root](https://docs.npmjs.com/cli/v11/commands/npm-install/)

ZIP содержит только новые/изменённые файлы этой задачи. `files.txt` перечисляет
их пути от корня. Проверка поставки — CRC и точное сравнение архивных байтов с
файлами рабочего дерева; отдельный SHA-манифест не создаётся.
