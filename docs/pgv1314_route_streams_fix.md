# PGV1314 — отделить route JSON от диагностического stderr

24.11.2026. Дополнение к CI fix на базе086b4f6; применять поверх предыдущего
пакета `CISStat-PGV1314-CI-fix-086b4f6.zip`. Commit/push выполняет тимлид.

## Подтверждённая причина

Пользовательский `pgv1314-failure.zip` содержит все10 command exits=0,
pytest161, Jest357 и обе успешные production-сборки. Все12 хешей файлов
совпадают. Итог FAIL случился в `evidence_validation`: JSONDecodeError,
line1 column1. `routes.log` начинается тремя DEBUG строками tzlocal и
clickhouse_connect, затем содержит корректный JSON с status=ok,
284API/288bindings/668entries и пустыми added/missing.

Runner объединял stderr и stdout каждого subprocess; validator строго
читал routes.log как JSON. Импортируемые библиотеки в Windows окружении
печатали DEBUG в stderr. Ошибка не свидетельствует об изменении маршрутов
или провале сборок. Предыдущий GitHub web_builds failure остаётся отдельным
случаем с неизвестной причиной; этот Windows архив его не диагностирует.

## Решение и риски

Только для этапа routes runner сохраняет stdout в routes.log, stderr — в
routes.stderr.log. Context manager закрывает оба потока при успехе,
ненулевом exit и timeout. Оба файла включаются в существующий raw SHA256
manifest и CI artifact. При провале routes summary дополнительно содержит
failed_stderr_log, console печатает bounded/redacted stderr tail.

JSON reader остаётся строгим: лишний текст в stdout всё ещё FAIL. Не
извлекаем «последний JSON», не переписываем DEBUG log, не игнорируем
ненулевой exit. 11 native scenarios, every-page PNG/OCR/review, source
fingerprints и task flags не ослаблены. Исходный пользовательский FAIL
архив не переделывается в PASS; после обновления нужен новый local report.

TDD controls: валидный JSON + DEBUG stderr даёт PASS и hashed stderr;
ненулевой route exit остаётся FAIL с диагностикой stderr; шум в stdout
остаётся FAIL даже при валидном JSON в последней строке. На старом runner
первые два controls RED, третий negative control GREEN. Существующие161
exact cases сохранены, добавлены3; итог pytest164, controls28. CI matrix
и default local gate уже вызывают этот модуль, новые команды не нужны.

## Применение (PowerShell, из корня checkout)

Распаковать delta ZIP поверх предыдущего CI пакета. Node22.23.5/npm10.9.9
у пользователя уже установлены. Зависимости прежние.

```powershell
python scripts/local_gates.py --only pgv1314cert --skip-install
git add --pathspec-from-file=scripts/pgv1314cert/routefix/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

Первый gate сообщает новый каталог evidence вне checkout; теперь там14
файлов, включая routes.stderr.log. После успешной проверки commit/push
выполняет тимлид; новый GitHub run подтверждает CI и native Windows controls.
Linux regressions/OS-stream control не подменяют запуск Windows у пользователя.

AUTH00 collector обновляет reviewed host source hashes. HTTP paths/methods,
route checker, guard/DTO/runtime, SQL и Dockerfiles не изменены. На VM
пересборка образов/миграции/перезапуск сервисов для этого fix не требуются.
