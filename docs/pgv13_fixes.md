# PGV-13: F-C13-00…03, дизайн исправления (база 2014fdf)

Цель: закрыть четыре builder/lifecycle дефекта независимо от доступа к VM.
HTTP transport, sandbox rollout, PGV-14 pagination и PGV-15 picker вне задачи.

1. P01/P02 получают полный envelope, который реально читает PrintPageFrame.
   Sampling неприменим к переносу полных паспортов; общие computed/captured
   даты не синтезируются из первого/последнего паспорта: null + причина,
   исторические даты остаются в каждой записи. Result обозначает печатный
   вход, а не вымышленный VisualResult/научный расчёт.
2. Builder version `pgv.passport_documents/2`, mode, profile, run и весь frozen
   контент (включая checkpoint ID/время/flags/source и gaps) входят в digest.
   Только render_requested_at исключён. Lifecycle строит payload один раз,
   берёт producer key из него же: lookup и freeze используют одну identity.
   Старые артефакты/ревизии/jobs остаются неизменными; новый запрос не попадает
   в старый producer key. Изменений таблиц/миграций нет.
3. В checkpoint-комплекте физические rs refs печатаются по одному разу,
   порядок первого появления сохранён. Подтверждение — отдельный общий
   pure-компонент перед паспортами: полный checkpoint ID, stage, timestamp
   или причина отсутствия, точный source ref и reuse факт. Source берётся
   из проверенного payload checkpoint через новый внутренний атрибут reader
   `confirmed_snapshot_ref`, не выводится из stage/newest. Так сохраняется
   точная ссылка и при отсутствующем stage ref.
   Explicit refs и сравнение P02 сохраняют свою адресную семантику.
4. Независимые Memory и PostgreSQL тесты передают raw Python payload в
   compiled TS SSR без diagnostic_envelope. Проверяются профили всех трёх
   режимов, две исторические confirmation, старый cache key, повторный job,
   полные группы и отказы. Исправляется ошибочный старый oracle «4 полных
   секции на 3 refs», при сохранении контроля 3 scientific artifacts.

Риски: случайное объединение разных checkpoint, рассинхрон cache/freeze key,
повтор научного расчёта, потеря gaps и ложные общие timestamps. Защита — exact
content identity, единый producer key, durable readers, отдельные проверки.
Новые additive поля в frozen schema /1; HTTP endpoints/request DTO не меняются.
Полная сертификация PGV-13 остаётся открытой до transport/final-image/VM
P01/P02 приёмки. Локальный SSR не выдаётся за Chromium PNG/visual/OCR PASS.

## Проверка и поставка

TDD RED на чистой базе: 17 FAIL / 7 PASS; GREEN — 24 независимых + 39 author Python,
24 независимых на настоящем PostgreSQL 16.2; 160 TS print/renderer tests.
Обе Next production сборки и renderer tsc проверяются отдельно. Протоколы:
`scripts/pgv13fix/protocols/`. Timestamp oracle сравнивает моменты, потому что
PostgreSQL возвращает timestamptz с timezone соединения (+03:00).
В старом author reused-тесте ошибочный oracle 4 полных паспортов заменён на
3 unique refs + точный source из durable checkpoint, не «первый/latest».
P02 raw oracle проверяет действительный заголовок «Сравнение паспортов».

Расширенный PGV-05/06/09 прогон: 163 PASS / 1 FAIL (только старый docstring
`scripts/pgv05/check_reader.py`, текст «13 метрик»). Тот же FAIL отдельно на
чистом 2014fdf, оба протокола сохранены. Чужая задача не подкрашивается.
F-C13-04/deployment, финальный Chromium PNG/content/visual/OCR/job-download
и transport пока OPEN; сертификат всей PGV-13 не выдаётся.

AUTH-00: HTTP endpoints/методы/request DTO/BFF allowlist не изменены.
Карта обновляется по проверенному source fingerprint и line evidence;
семантика policies/resources/admission прежняя. Новые поля относятся к
замороженному печатному входу /1 и builder identity /2, не к HTTP selection.
Данные/сессии/паспорта не пересчитываются. Старые basis/revisions/jobs не
ремонтируются на месте: повтор создания документа получает новый basis и job.

## VM: сборка кандидата, без переключения рабочего сервиса

Нужны новые API и renderer образы. В этой задаче web исходники роутинга и
его compiled allowlist не меняются; обе оболочки собраны для регрессии общего
print-кода. Если VM web ещё не содержит прежние PGV-13 proxy paths, он требует
отдельной синхронной пересборки (старый F-C13-04b остаётся открытым).

После push/pull нового кода, из корня репозитория:

```bash
docker compose --project-directory deployment/cisstat-stack \
  -f deployment/cisstat-stack/docker-compose.yml build api
docker build -f apps/print-renderer/build/Dockerfile \
  -t cisstat-print-renderer:pgv13-fc13-v2 .
docker image inspect --format '{{.Id}}' cisstat-print-renderer:pgv13-fc13-v2
```

Это **только сборка**: команда `up` намеренно не включена. Рабочий renderer
сейчас закреплён на старом immutable image. Старый A/B report и old-image
ops PASS не распространяются на новый образ; `activate.py` проверяет совпадение
image ID и сам не является image-upgrade инструментом. Не подменять в старом
JSON image ID и не снимать его проверку. До переключения api+renderer нужен
следующий согласованный rollout с новым image preflight/A-B и повтором
working-service smoke, затем P01/P02 приёмка через исправленный transport.
Base Compose/sandbox/512 overlay/network/host policy в текущем ZIP прежние.
Миграции/host sysctl/AppArmor/capabilities не нужны. Коммита/push нет.

Отдельный крайний случай: обязательный stage_refs.start указывает на
отсутствующий rs, а подтверждённый source доступен под физическим stage=start.
Старый resolver по checkpoint.stage=modeling_entry терял источник. Для
валидной формы запроса зафиксирован RED1 → GREEN1; первый черновой fixture
без обязательного ключа был отклонён валидатором и не считался evidence.
Итоговый набор на чистой базе даёт RED17/7, после исправления24/24.
Final Python composite:226 PASS /1 baseline FAIL из227; target subset63/63.
Полный cert suite:25 PASS /3 deployment FAIL, без xfail/skips.
