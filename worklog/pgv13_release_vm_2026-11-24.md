# PGV-13 — акт развёртывания согласованного релиза (e2da22c, PGV-15 включён)

Дата: 24.11.2026. Источник: консольные результаты с VM, предоставленные
тимлидом в текущем диалоге. Агент не выполнял Docker/SSH на VM; bash-команды
выдавались пошагово (9 шагов) и исполнялись оператором по
`docs/pgv13_release.md`. Это сводка; полные исходные отчёты
(`manifest.json`, `pins.env`, `baseline.json`, `ab.json`,
`candidate-first.json`, `candidate-recreated.json`, `live.json`,
`operation.json`, build-логи) находятся в release bundle на VM.

Ревизия: `e2da22cbd655107bd27d793094bad01464ad7ffd` (origin/main; включает
поставку PGV-15). Git tree фиксируется в bundle (`PGV13_SOURCE_TREE` в
`pins.env` и `manifest.json`) и из диалога не перепечатывается.
Bundle: `/opt/cisstat/releases/pgv15-e2da22c-20261124T135954Z`
(каталог назван оператором под выпуск сборки оболочки PGV-15; пайплайн —
`docs/pgv13_release.md`). Release ID: `922ff70c2381`.

| Сервис | Развёрнутый image ID |
| --- | --- |
| api | `sha256:a6e81bda07d4ccf2cdd65b0e22a5f783f1bb4baac2ba50b65688bb53f7ec1cf8` |
| web | `sha256:b749c5f1cbc871534456a0f2c0d03b8e58d834a05575e58113cfb51da7c76b2c` |
| print-renderer | `sha256:992efeda3aee7e99ff43a8cf70e1db284d7a50a884fbd0f686bd16f1530bd767` |

## Подтверждённые шаги

| Шаг | Операторский результат |
| --- | --- |
| Discovery renderer project | production = `deployment`; 4 оставшихся candidate-проекта прежних попыток не тронуты |
| Build (до пайплайна) | `pull`/`export`/`build --bundle` выполнены оператором; манифест `BUILT`, `pins.env` создан |
| Baseline capture | `captured: true`, transport `uds` (baseline после релиза 20.11), capture не пересоздавал сервисы |
| IPC prepare | `prepared: true`: `cisstat_renderer_ipc_922ff70c2381` и `_candidate`, метка `io.cisstat.release.id` |
| Новый A/B, 512 PID | `CHROOT_RULE_CANDIDATE`; builtin/reference — namespace failure, namespaces — chroot gate, namespaces-chroot — smoke passed; `isolation_ok` во всех четырёх arms |
| Первый candidate | `passed: true`, `mode: candidate-api-image`, matching API/renderer IDs |
| SIGKILL и recreate candidate | `passed: true`, `recreate_verified: true`, новый container ID при том же image/volume |
| Release preflight | `passed: true`, `rollback: false` |
| Операционный drain | подтверждён оператором; uncertain/financial holds не снимались |
| Apply `--quiesced` | `phase: started`, три запущенных image IDs совпадают с bundle, `readiness_checked: false` |
| Production native | `passed: true`, `mode: live-api` |
| Внешний API health | `{"status":"ok"}` |

В A/B builtin/reference дают ожидаемый namespace failure; namespaces проходит
namespace probe, но даёт chroot failure. Только namespaces-chroot проходит
smoke. Старые отчёты (renderer `1837bee8…`) в приёмке нового image не
участвовали; `--expected-revision/--expected-tree` сверены с метками образа.

## Live UDS

Renderer container:
`46954b4899bdb0a9f6adf0fd7ef4d1a090c744a29113dda48d074fffaf5d90c5`.
Production volume: `cisstat_renderer_ipc_922ff70c2381`.
Candidate volume: `cisstat_renderer_ipc_922ff70c2381_candidate`.

Подтверждены parent hardening, закрытый TCP, UID/GID `10001:10001`, socket
`0660`, directory `0750`, read-only API mount и lifetime lock. Readiness,
readonly и отрицательные контроли клиента (cancel, deadline, request cap)
прошли. PID max 512, live peak 150; PID max-events 0. Memory max
`2147483648` bytes; все memory events, включая OOM/kill, 0. Client disposable
API-image контейнер candidate-режима и live-прогон дали одинаковый
`client_source_sha256: 2793ae6c74bdc46acf34d182b10efb30b36f8cd4f18b7ca93aae79acd8d46d46`.

Три PNG-профиля прошли signature/CRC/dimensions/pHYs 300ppi/IDAT/IEND; байты
и hashes совпали в candidate-first, после recreate candidate и в live:

| Профиль | Bytes | SHA-256 |
| --- | --- | --- |
| figure-landscape | 244388 | `f465b1e3da9f9eb20131fd413f25d76c0fdf782400f0f0632fc977ce9a99813a` |
| a4-landscape | 320733 | `c74acbcc278e8404c593ff9c732176b5db2948a050df9aa7334508fc34bef841` |
| a4-portrait | 205445 | `680d5e5b5074369b8e8e6c824468c559fd0715f74da21379448f254e14e65bac` |

`recreate_verified: false` в live ожидаем: deliberate SIGKILL/recreate
проверялся на отдельном candidate, не в production. Live report не содержит
отдельного `api_image_id`: три текущих IDs отражены в apply output;
native-клиент выполнен в действующем API.

## Откат и сохранность

Capture сохранил прежние образы (текущий UDS baseline перед этим apply):

| Сервис | Baseline image ID |
| --- | --- |
| api | `sha256:cb1635c695dab6878a5c0a98b0b62b3e93f2b029b10b9ceffaf8fac2a7fadccc` |
| web | `sha256:0c74b32bb600a4f9e13e81778941d7793b4f0d5acf8fb471744cb7f682ba5c67` |
| print-renderer | `sha256:55278b45e6168bba78cd7229f549ce4414d056ad4e280c38df60409bbd8f7afc` |

Фактический rollback на VM не выполнялся — только сохранённый baseline и
локальные controls; это не акт проверенного VM rollback. Сохранять bundle,
`pins.env`, baseline, исходные Compose inputs, прежние images и volumes до
принятия релиза. Для будущих service recreates использовать base stack inputs
+ `stack.json` и renderer base + `renderer.json` с теми же project names
(`deployment`, `cisstat-stack`); base-only up вернёт прежнюю topology.
Candidate-проект ещё работает; остановка только `down` БЕЗ `-v` теми же
`-p/-f`. Порядок отката — `docs/pgv13_release.md` (`rollback --quiesced`).

## Границы результата

Этап 4 согласованного релиза e2da22c развёрнут и прошёл live UDS проверку.
Развёрнутые образы включают поставку PGV-15 (печатные семейства Documents,
picker/preview/PNG/ZIP UI, маршрут GET print-documents). Полный PGV-13
**NOT CERTIFIED**: остаётся приёмка P01/P02 content/visual/OCR/job-download
и итоговый акт. Этот акт не заменяет исходные JSON-отчёты и manifest на VM.

Правило секретов соблюдено: извлечение секретов с VM bash-командами не
производилось и не запрашивалось; отчёты пайплайна по конструкции не содержат
Env/DSN/SMTP/MFA dump. DDL/DB/ключи/квоты/holds/volumes командами пайплайна
не менялись; маршруты HTTP-поверхности не менялись этой VM-активностью
(карта 285/289/669 — из коммита e2da22c). Дополнение содержит только акт и
дописанный `worklog/worklog12.md`; source-код, роуты, AUTH-00 policy и
local_gates не меняются; rebuild/DDL не нужны.
