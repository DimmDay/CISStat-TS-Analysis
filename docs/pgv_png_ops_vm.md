# VM: PGV-PNG-OPS — восстановление worker credential

База кода `20b835b`; 26.11.2026 (Москва). Подтверждённый вывод оператора:
`worker_credential.state=missing`, document worker running/last_run_at=null,
289 ошибок worker_service_unavailable, print renderer UDS ready. Ошибка
при admission, PNG jobs отсутствуют. Предыдущий transport live PASS не
проверял process-wide credential. Это не доказательство переполненной очереди.

## Немедленное восстановление на текущих образах

Новые образы и миграции для этой операции **не нужны**: официальный
`apps.api.workers.bootstrap ensure` уже находится в текущем API. На VM
после pull обновлённого среза использовать репозиторный путь
`scripts/pgv_png_ops/worker_ops.py`; отдельно сохранять копию в корне не нужно. Один оператор;
произойдёт краткий recreate только API. Текущие задания перед рестартом
операционно завершить; uncertain/финансовые holds ради этого не снимать.
По диагностике данного инцидента активных PNG jobs нет.

```bash
cd /opt/cisstat/CISStat-TS-Analysis
python3 scripts/pgv_png_ops/worker_ops.py check
python3 scripts/pgv_png_ops/worker_ops.py repair
python3 scripts/pgv_png_ops/worker_ops.py check
```

У `check` exit2 и ready=false
при missing ожидаемы; не объединять первый check с repair через `&&` или
`set -e` (он намеренно сигнализирует неготовность). `repair` exit0 означает
успешный цикл worker, usable render credential и готовый renderer.

Скрипт выводит только безопасные состояния. Он:

- Не читает/не печатает Config.Env, ключи, DSN, дайджесты или dotenv-содержимое.
  Docker stderr/stdout не ретранслируются; разрешены только разобранные поля.
- Берёт project и ordered Compose files из metadata живого API. Проверяет
  `cisstat-stack`, наличие фактических файлов и соответствие image pin текущему
  API через два безопасных `compose config --images api` без config/env dump.
  Вывод включает зависимости (например, postgres:16). API определяется
  read-only probe с временной подстановкой только api.image; multiset разницы
  должен соответствовать живому API image. Порядок и дубликаты не важны;
  совпадения image только у зависимости недостаточно. Probe-файл удаляется
  и никогда не передаётся в bootstrap/recreate. Подробнее docs/pgv_png_pinfix.md.
  Если файлы релиза перемещены или pin изменён, операция останавливается.
- Сначала вызывает bootstrap ensure из тех же Compose inputs: существующий
  валидный ключ в `.env` повторно использует, без ротации. Только при missing
  генерирует `cwk_` внутри процесса и дописывает строку прямо в закрытый `.env`
  (0600, regular file, no symlink, exclusive operator lock, fsync). Старые
  значения не читаются/не копируются; Compose использует последнюю запись.
- Через ensure регистрирует только hash в БД; expired/revoked/invalid не
  воскрешает. Секрет не передаёт в argv/stdout. Старые shell-export overrides
  WORKER_KEY/MFA убирает только из дочернего окружения Compose.
- Делает `up -d --no-deps --no-build --pull never --force-recreate api` с
  теми же project/env/ordered overlays; renderer/web/postgres/volumes не
  пересоздаёт. Повторно проверяет image/inputs и успешный worker cycle.
  Квоты, reservations и holds не исправляет принудительно.

При reason!=null/exit2 не удалять данные и не печатать env/config. Если
`worker_cycle_not_ready_check_locally`, подождать обычный старт и повторить
только check; бездумный повтор recreate не нужен. Сбой после private append
оставляет пригодную конфигурацию для повторного ensure/repair. При
`credential_not_usable_no_automatic_rotation` нужна отдельная штатная ротация,
данная команда её намеренно не выполняет. Права Docker/.env должны быть у
оператора. Скрипт локально протестирован; настоящий Docker/VM запуск —
отдельный операторский результат, которого локальный протокол не заменяет.

## После восстановления

Проверить UI: новый датасет → Обзор/график/Валидация → «Скачать PNG»;
queued/running → ready → фактически открыть скачанный файл. Повторить для
ранее сохранённого исследования без пересчёта науки. Критерий восстановления:
check ready=true, новые managed render jobs и реальные PNG; одного health ok
или отсутствия toast недостаточно. Результаты UI/VM дописать в worklog12.

## Выкладка исправленной обработки ошибок API/UI

В ZIP дополнительно исправлены routes orchestration: trusted AuthHTTPException
сохраняет status/code/headers; произвольный upstream HTTPException остаётся
безопасным503. Клиенты visual/passport читают detail/error/flat и различают
не настроенный worker, занятый слот, квоту и вход. Это требует **новых API/web
образов**. Тимлид после review/gates размещает task-only файлы и делает свой
commit/push. Далее выполнить полный штатный coherent build/candidate/recreate/
check/drain/apply/live по `docs/pgv_png_fix_vm.md`, выбрав новый bundle:

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
python3 scripts/pgv_png_ops/worker_ops.py check
export PGV13_BUNDLE="/opt/cisstat/releases/pgv-png-ops-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    python3 scripts/pgv13release/release.py "$@"
}
pgv13_release build --bundle "$PGV13_BUNDLE"
```

Дальнейшие шаги2–3 прежней инструкции выполняются с **этим** новым bundle,
включая capture/source pins/prepare-ipc из шага1. Не запускать её первый блок
с другим export PGV13_BUNDLE второй раз. Сохранять прежние bundle/evidence/
pins/volumes. Transport live проверяет renderer; перед и после apply отдельно
`python3 scripts/pgv_png_ops/worker_ops.py check`, затем реальная UI-приёмка.
Полная PGV-CERT/пиксельная сертификация не заявляется этой поставкой.
