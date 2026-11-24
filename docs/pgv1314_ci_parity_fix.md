# PGV13/PGV14 — CI artifacts, diagnostics and local parity

База: `086b4f69aed0b2862958e1eccbe0bf85cc498adb`, 24.11.2026.
GitHub run `45361226628`, job `138331498865`: оба controls jobs прошли,
`local-evidence` дошёл до `web_builds`, затем FAIL. Сам build log отсутствует
в доступном job output; artifact upload тоже упал. Точную историческую
причину сборки установить нельзя. Повторные обе production-сборки на Node
22.23.5 прошли; предположения о font/TLS/OOM не заменяют исходный лог.

## Решение и риски

1. Run и upload используют один абсолютный `${{ runner.temp }}/pgv1314-local`.
   Контекст `runner` допустим в step env/with, не job env. Удалён путь с `..`,
   отвергаемый upload-artifact v6. `always()` сохраняет результат неуспешного
   запуска; отсутствие файлов после попытки запуска остаётся ошибкой.
2. Общий host driver `scripts/pgv1314cert/cifix/verify_ci_local.py` вызывается
   из workflow и default `pgv1314cert` local gate. Проверяет Node22, запускает
   прежний полный `local.run_local`, сохраняет новый каталог evidence вне
   checkout. Локальный gate теперь включает обе production-сборки и требует
   полного API набора зависимостей. Один зелёный issuer controls больше
   не выдаётся за повторение полного CI job. `--only` других gates, как и
   прежде, не запускает PGV1314; `--skip-install` требует готовых зависимостей.
3. Runner сохраняет активный/упавший этап в summary, печатает имя файла и
   последние 60 строк (максимум 12 KiB) в CI console. URL credentials и
   стандартные token/password поля маскируются в console; исходные evidence
   logs сохраняют точные bytes/hashes. Строки имеют безопасный префикс.
   Ошибки/timeout продолжают завершать job с ненулевым exit.
4. В exact pytest manifest сохранены все153 старых cases и добавлены8
   regression cases. Workflow, gate, driver и тест заморожены fingerprint
   сертификатора; старый local report после этой поставки ожидаемо stale.
   Нужен новый local evidence bundle; проверки не ослаблены.

TDD: RED import отсутствующего driver/helper; GREEN controls25 (issuer17 +
CI8). Проверяются путь run/upload, допустимый контекст, полный gate,
Node22, failure/timeout diagnostics и сохранение отрицательных task flags.
Полный local прогон проверяет pytest161, Jest357, typography18, CP1252,
routes/inventory/typecheck и обе production-сборки. Это local contract
evidence, не native сертификат PGV13/PGV14; 11 VM scenarios и every-page
PNG/OCR/review остаются обязательными для `issue`.

## Применение и проверка

Наложить task ZIP на checkout указанной базы. Использовать Node22, Python3.12
и собственные npm workspaces этого checkout:

```bash
node --version
python -m pip install -r apps/api/requirements.txt -r scripts/pgv1314cert/requirements.txt
npm ci --include=dev --workspaces --include-workspace-root --ignore-scripts --no-audit --no-fund
python scripts/local_gates.py --only pgv1314cert --skip-install
# stdout сообщает новый каталог evidence вне checkout
git add --pathspec-from-file=scripts/pgv1314cert/cifix/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

Commit/push выполняет тимлид. Новый GitHub run должен пройти `local-evidence`
и upload; при новом FAIL причина будет в console и отдельном log artifact.
Реальный upload action и нативный Windows этим Linux-прогоном не исполняются.

HTTP paths/methods/DTO/guards, SQL, runtime и Dockerfiles не меняются.
AUTH00 карта обновляется штатным collector только для reviewed host sources;
семантика маршрутов должна оставаться равной базе. На VM ничего не запускалось;
пересборка образов/миграция/перезапуск сервисов для этого host CI fix не нужны.

Основные источники: GitHub job log (выдержка в protocols),
`https://github.com/actions/upload-artifact/blob/v6/README.md`,
`https://docs.github.com/en/actions/reference/workflows-and-actions/contexts`.
