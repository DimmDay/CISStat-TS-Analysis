# PGV-13-UDS HOTFIX1 — AUTH-00 worker contract

База: `c305bd926fecdfa3cd97e307c064dc26360fc4f9`.

## Причина и решение

`auth00(5).log`: INDEX-parity уже PASS (602 discovery surfaces), затем
один FAIL среди 60 unittest. Это не ошибка распаковки, staging или CRLF.
GitHub AUTH-00 run [44598659941](https://github.com/DimmDay/CISStat-TS-Analysis/actions/runs/44598659941)
повторяет тот же FAIL на Ubuntu и Windows.

PGV-13-UDS добавил автоматическую thread boundary `renderer.ipc.render`
в `document_render_worker.py`: отменяемый IPC-вызов с эффектами
`thread_dispatch, private_renderer_request`. Прежние deadline и loop остались.
Старый тест требовал два потока, каждый только с `thread_dispatch`.
Поэтому замена одного числа 2→3 также воспроизводимо FAIL.

Исправляется тест, а не правильная классификация новой boundary:
точное множество трёх canonical operations, число экземпляров,
thread targets, authority и точные effects. Номера строк не закрепляются.
Ручные logical worker surfaces не смешиваются с автоматически найденными
thread starts. Отдельный тест проверяет, что client watchdog имеет только
`renderer.ipc`/`cancel_socket, deadline`, без полномочий публикации.

Риск ослабления теста проверяется двумя положительными и девятью
отрицательными controls: missing/extra/duplicate, подмена policy/target/effects.
Варианты применяются только к копиям отчёта, исходники/INDEX не меняются.
Сам изменённый тест добавлен в reviewed sources; inventory обновляется
официальным collector. Роуты, runtime, Compose и миграции не меняются.

## Применение на локальной машине

Распаковать ZIP поверх уже применённого PGV-13-UDS. Это hotfix overlay,
не замена исходной поставки. Из корня checkout:

```powershell
git status --short
git add --pathspec-from-file=scripts/pgv13uds/hotfix1/files.txt
git diff --cached --stat
python scripts/local_gates.py --only auth00 --skip-install
python scripts/pgv13uds/hotfix1/verify_contract.py
```

Полный default-прогон допустим обычной `python scripts/local_gates.py --skip-install`.
Runner не меняется: обновлённый и новый tests уже под шаблоном `test_auth00*.py`
в локальном gate и GitHub Linux/Windows workflow. После собственного commit
тимлида можно проверить `python scripts/auth00/check_committed.py --target head`.
Новый push запускает Actions на исправленном commit; rerun старого commit
использует прежний тест и снова FAIL.

## VM и границы проверки

Дополнительная пересборка образов/recreate/миграция из-за этого hotfix не нужна.
После своего push тимлид синхронизирует VM обычным `git pull --ff-only`.
Первоначальные build/rollout команды PGV-13-UDS и его native VM gate остаются
в `docs/pgv13_uds_transport.md`. Hotfix не подтверждает native UDS, sandbox,
P01/P02 PNG или окончательную сертификацию PGV-13.

Доказательства RED/count-only RED/GREEN, fault controls, AUTH-00,
actual routes, renderer build и clean ZIP overlay — в
`scripts/pgv13uds/hotfix1/protocols/`. Локальный Linux-прогон не заменяет
будущий Windows Actions. Полный scientific pytest не требуется для изменения
тестового контракта; runtime исходники этой поставкой не затрагиваются.
