# PGV-13 — акт развёртывания согласованного релиза

Дата: 20.11.2026. Источник: консольные результаты с VM, предоставленные
тимлидом в текущем диалоге. Агент не выполнял Docker/SSH на VM. Это сводка;
полные исходные отчёты и baseline находятся в release bundle на VM.

Ревизия: `3b13214466a31fb9ceeebe583abd64812e3bd042`.
Git tree: `f0abfd62d55e154c015972b840626976958fa5d2`.
Bundle: `/opt/cisstat/releases/pgv13-3b13214-20261120T101532604464185Z`.

| Сервис | Развёрнутый image ID |
| --- | --- |
| api | `sha256:c528527413c43dcfab3249eb0b6c35c7b97d79c2c65174ae972838d1291803b6` |
| web | `sha256:b8549697adb53c6921704e25be601bdb7500e2c7a032ff43944bd5505d68655b` |
| print-renderer | `sha256:70d34cbc409dd5793ec7659c96dce891aad220bf91233a6f7131a60dc1577126` |

## Подтверждённые шаги

| Шаг | Операторский результат |
| --- | --- |
| AUTH-00 HEAD-parity | PASS, 602 discovery surfaces; отдельный прогон 13.979 с |
| Build | `built: true`, одна revision/tree для трёх образов |
| Новый A/B, 512 PID | `CHROOT_RULE_CANDIDATE`, isolation OK во всех четырёх arms |
| Baseline capture | `captured: true`, production renderer project `deployment`, transport `legacy` |
| IPC prepare | `prepared: true`, отдельные production/candidate volumes |
| Первый candidate | `passed: true`, matching API/renderer IDs |
| SIGKILL и recreate candidate | `passed: true`, `recreate_verified: true`, image и volume сохранены |
| Release preflight | `passed: true`, `rollback: false` |
| Apply | `phase: started`, три запущенных image IDs совпадают с bundle |
| Production native | `passed: true`, `mode: live-api` |
| Внешний API health | `{"status":"ok"}` |

В A/B builtin/reference дают ожидаемый namespace failure; namespaces проходит
namespace probe, но даёт chroot failure. Только namespaces-chroot проходит smoke.
Результат старого renderer `1837bee8…` не использовался как приёмка нового image.

## Live UDS

Renderer container:
`87f841c0fd3a2031bb2c743b55ef157262c89af6146d9937ffd630957474b575`.
Production volume: `cisstat_renderer_ipc_2fb1295ea78a`.
Candidate volume: `cisstat_renderer_ipc_2fb1295ea78a_candidate`.

Подтверждены parent hardening, закрытый TCP, UID/GID `10001:10001`, socket
`0660`, directory `0750`, read-only API mount и lifetime lock. Cancel, deadline
и request cap прошли. PID max 512, live peak вырос со 147 до 245; PID max-events
остался 0. Memory max 2147483648 bytes; все memory events, включая OOM/kill, 0.

Три PNG-профиля прошли signature/CRC/dimensions/pHYs 300ppi/IDAT/IEND;
байты и hashes совпали до и после recreate candidate и в live:

| Профиль | Bytes | SHA-256 |
| --- | --- | --- |
| figure-landscape | 73647 | `20f2d74835d6e70e0765801c5753ee59a167598011c483828adc760bd6fee087` |
| a4-landscape | 109965 | `36d4a7825468198a60bbd446c546175f01949235b61dfc046e75974c59a2eba7` |
| a4-portrait | 77659 | `647cf68e9cd18a683de807e70db6c717e96e5d118609e02e7ec2326b8908356a` |

`recreate_verified: false` в live ожидаем: deliberate SIGKILL/recreate
проверялся на отдельном candidate. Это не утверждение о production recreate.
Live report не содержит отдельного `api_image_id`: три текущих IDs отражены
в apply output; native-клиент выполнен в действующем API.

## Откат и сохранность

Capture сохранил прежние образы:

| Сервис | Baseline image ID |
| --- | --- |
| api | `sha256:20ab769e359ac3e3f95cd299556f624fbe6ad04efffd8f769e303e13e2a43c2d` |
| web | `sha256:05ec5c587e3e4bd9e5b1a32c137a19c2d0cb26edca1387067166a293c799a749` |
| print-renderer | `sha256:1837bee8994e42b97b548de5ecf4d3e026f8b3e6624d9ac42822a4ed290f81b3` |

Фактический rollback на VM не выполнялся. Возврат к этому legacy baseline
может вернуть прежний transport blocker. Сохранять bundle, `pins.env`, baseline,
исходные Compose inputs, прежние images и volumes. Для будущих service recreates
использовать pinned overlays из bundle; порядок — `docs/pgv13_release.md`.

## Границы результата

Этап 4 согласованного релиза развёрнут и прошёл live UDS проверку. Полный
PGV-13 **NOT CERTIFIED**: остаётся приёмка P01/P02 content/visual/OCR/job-download.
Этот акт не заменяет исходные `ab.json`, `candidate-first.json`,
`candidate-recreated.json`, `live.json` и release manifest на VM.

Дополнение содержит только этот акт и дописанный `worklog/worklog12.md`.
Runtime, routes, AUTH-00 policy и local_gates не меняются; rebuild/DDL не нужны.
