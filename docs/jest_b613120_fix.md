# JEST-B613120-FIX — Jest и GitHub Actions

База: `b613120f32138ff8530320660ddc991cb2778992`, 30.10.2026.
Синхронизация выполнена `git fetch origin main`; отдельное detached worktree
сохраняет предыдущие локальные изменения. `AGENTS.md` прочитан, commit/push нет.

## Диагноз по фактическим данным

Полные логи run [40932604002](https://github.com/DimmDay/CISStat-TS-Analysis/actions/runs/40932604002)
проверены для [Ubuntu job 123654681135](https://github.com/DimmDay/CISStat-TS-Analysis/actions/runs/40932604002/job/123654681135)
и [Windows job 123654681735](https://github.com/DimmDay/CISStat-TS-Analysis/actions/runs/40932604002/job/123654681735).
Оба job используют именно `b613120` и имеют **237 suites / 2739 tests**,
**1 failed / 2738 passed**, без ошибок компиляции renderer или запуска shell/Python.
Подлинные выдержки с результатами сохранены в `scripts/jest-b613120/protocols/ci-*.txt`.

Единственное падение: B1 в `scripts/pgv07cert/test_p7cert_findings.test.tsx`.
Исходная запись `## Task ID: PGV-07` всё ещё заявляет
`Doc-contract гвард scripts/pgv07/check_documents.py — 62/62.`,
но исполненный Python-гвард возвращает 41/41. Поздние записи JEST-505-FIX
и JEST-PORTABILITY утверждали, что эта строка исправлена, однако в коммите
такой правки нет. Исправлена сама исходная строка. Тест B1, его сравнение
и гвард оставлены без изменений.

Предоставленная локальная сводка **234 suites / 2666 tests, 8 failed suites /
13 failed tests** отличается от обоих CI jobs. Эти суммы не позволяют определить
имена и причины остальных ошибок. Нельзя заключить, что виноват только старый
checkout, зависимости или ОС. Воспроизводимый полный локальный прогон на чистом
`b613120` подтверждает результат CI; различие конкретной машины остаётся
неустановленным без полного лога и сведений о её окружении.

## Найденная при повторном полном прогоне гонка Upload

После исправления B1 следующий полный прогон дал **1 failed / 2738 passed**:
`UPLOAD-SEM-1` не дождался карты `overview=done`, `quality=pending`,
`chart=pending`. Протокол `upload-red-full.json` / `.txt` сохранён.
Это отдельное локальное свидетельство; оно не устанавливает состав 13 ошибок
на машине тимлида.

В эффекте просмотра Upload отсутствовала зависимость от `viewedStops`.
Сброс вселенной заменяет множество, затем быстрый seed устанавливает ready=true.
Если false→true объединены React batching, ready остаётся прежним, а эффект
в коммите смены uploadData уже был остановлен `uploadSeedReadyRef=false`.
Одной замены множества было недостаточно для повторной регистрации видимого
результата. Применён существующий паттерн EDA: `viewedStops` добавлен в
зависимости эффекта. Идемпотентный `prev.has(stopId) ? prev : new Set(...)`
не изменяет идентичность уже учтённого множества и предотвращает цикл.
Сброс вселенной, seed, удержание отчёта при неудачном seed и статусы не менялись.

Существующий семантический тест дополнен двумя режимами `/trace` (немедленный
Promise и ответ в следующей задаче event loop), действие загрузки выполнено
через awaited async `act`. Проверки полной карты и запрета warning сохранены.
Отдельная проба этих двух режимов **прошла ещё до изменения продуктового
эффекта** (`upload-race-probe.*`): она проверяет порядок ответов, но сама по
себе не является детерминированным RED для гонки. RED-свидетельство — полный
прогон исходного теста; ограничения не скрыты повторным запуском.

## Процесс и точки изменения

1. Синхронизация с точным SHA, чтение правил и проверка исходного дерева.
2. Чистый `npm ci` всех workspaces, полный RED и отдельный B1 RED.
3. Исправление первичного заявления PGV-07; существующий B1 проверяет результат.
4. Обновление `.github/workflows/jest.yml`, корневого `package.json`
   и `.gitignore` для воспроизводимого запуска и сохранения результатов.
5. Разбор дополнительного Upload RED, исправление эффекта и проверка вариантов
   быстрых/отложенных ответов.
6. Полный GREEN, сборки, проверки типов, ZIP с точной сверкой состава и байтов.

В workflow `actions/checkout@v6`, `actions/setup-node@v6`,
`actions/setup-python@v6`, `actions/upload-artifact@v6` используют Node 24.
Это проверено непосредственно в `action.yml` тегов; доказательство —
`protocols/actions-runtime.json`. Официальные источники:
[checkout](https://github.com/actions/checkout/blob/v6/action.yml),
[setup-node](https://github.com/actions/setup-node/blob/v6/action.yml),
[setup-python](https://github.com/actions/setup-python/blob/v6/action.yml),
[upload-artifact](https://github.com/actions/upload-artifact/blob/v6/action.yml).
Node приложения в `setup-node` остаётся 22: runtime самого Action и версия
Node для запуска проекта — разные настройки.

Матрица использует явные `ubuntu-24.04` / `windows-2025` из
[официальных образов](https://github.com/actions/runner-images).
Ссылка `ubuntu-latest` больше не вызывает незапланированную миграцию на Ubuntu 26.
Пин версии ОС не фиксирует все еженедельные обновления образа.
В исходном CI фактически использовались Ubuntu 24.04 и Windows 2025 VS2026.

`npm ci` явно включает dev dependencies, все workspaces и корневой пакет.
Новая общая команда `npm run test:ci` запускает весь Jest с прежними двумя
workers и записывает `jest-results.json`; exit code Jest сохраняется.
Отчёт содержит имена suites, тестов, ошибки assertions и runtime/compile errors.
Он исключён из Git и всегда загружается отдельным CI artifact для каждой ОС
после успешной установки, в том числе при падении Jest. Срок хранения — 14 дней.
SHA, версии инструментов и верхний уровень установленных зависимостей печатаются
перед тестами. Сборка renderer и typecheck выполняются после тестового сбоя,
если установка завершилась успешно и job не отменён.

## Риски и границы

- Продуктовая правка ограничена зависимостями эффекта просмотра Upload;
  нет отключения diagnostics, исключения suites, skip/xfail, изменения
  таймаутов или ослабления B1. Идемпотентность и смежные тесты проверяют риск цикла.
- Обновление Actions требует runner >= 2.327.1; предоставленные jobs работали
  на 2.338.0. Для self-hosted runner применима проверка версии.
- JSON-отчёт содержит локальные пути и диагностические сообщения; в CI он хранится
  как artifact этого репозитория. Произвольные переменные окружения не выводятся.
- Новый workflow не исполнялся удалённо: commit/push запрещён AGENTS.md.
  Windows GREEN после правки нельзя заявлять по Linux-прогону.
- Docker/Chromium-сертификация PGV-08 не входит в эту задачу.

## Повторение на машине тимлида

В чистом checkout `b613120` распаковать ZIP из корня, затем:

```sh
git rev-parse HEAD
node --version
npm --version
python --version
npm ci --include=dev --workspaces --include-workspace-root --ignore-scripts --no-audit --no-fund
npm ls jest ts-jest typescript playwright-core --depth=0
npm run test:ci
```

Если локальные падения сохранятся, нужны `jest-results.json`, полный вывод
команды и значения версий выше. Отчёт позволяет разбирать именно эти 8 suites /
13 тестов без догадок по общей сумме. Повторный запуск не заменяет исправление
воспроизводимого сбоя; исходный корпус базы — 237 suites / 2739 tests,
после добавления второго режима Upload — 237 suites / 2740 tests.

## Проверки

Чистый `npm ci` завершился успешно (520 packages). Исходный полный RED:
237 suites / 2739 tests, 1 failed / 2738 passed, B1 62≠41, runtime errors=0.
Отдельный B1 RED: 1 failed / 4 passed. После Upload-правки адресный срез
Upload+B1 — 52/52. Финальная общая команда `npm run test:ci`:
**237/237 suites, 2740/2740 tests, 0 failed/skipped/runtime errors**, 102.281 s.
Дельта +1 — второй режим ответа seed в существующем Upload-тесте.
Renderer `tsc` build и typecheck обеих оболочек прошли.
Production Next-сборки завершились неуспешно; детали и границы — в протоколах
сборок и `summary.json`. Средовой `ENOENT uv_resident_set_memory` воспроизведён
в обеих оболочках; `process.memoryUsage` не подменялся. Первый embedded-запуск
имел exit=1 без диагностики; последовательная перепроверка после typecheck
сохранила полный stack trace в `build-embedded-recheck.txt`.
Новый workflow проверен как YAML, runtime тегов проверен по первоисточникам;
удалённый запуск после фикса не выполнялся.

Фактические итоговые счётчики и exit codes: `scripts/jest-b613120/protocols/summary.json`.
Полный RED: `baseline.json` / `baseline.txt`; отдельный RED B1: `b1-red.json` /
`b1-red.txt`. GREEN и сборки зафиксированы отдельно, без перезаписи RED.
