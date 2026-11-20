# PGV-13-LOCAL-CERT — независимая локальная приёмка, этап 3

База `fe9d131c643baf8840ae9079237fbed409893b25`, 20.11.2026.
Область: durable P01/P02 → настоящая compiled TypeScript validation/SSR.
Это отдельный локальный этап; итоговый PNG/VM сертификат не выдаётся.

## Дизайн и риски

1. Независимые данные принадлежат первоначальному cert-корпусу, а не
   авторским fixtures `tests/api`. Собственные группы, нулевой базис,
   категории, списки, неизвестная группа и причины отсутствующих значений
   сохраняются. Исследовательская сессия и DataFrame не создаются.
2. В JUnit каждого backend-зависимого случая проверяются фактические
   классы четырёх registries (runs/artifacts/snapshots/documents). В Memory
   дочерний процесс очищает inherited `CISSTAT_PGV13_CERT_DSN`; PostgreSQL
   без disposable DSN даёт exit2 до сборки, без Memory fallback.
3. Перед тестами `dist` удаляется и TypeScript собирается заново. Каждый
   положительный SSR получает ровно production output
   `build_print_render_payload_from_basis`, без `diagnostic_envelope`,
   ручного дописывания обязательных полей или renderer mock. SHA256
   исходников и compiled JS до/после фиксируются в `summary.json`.
4. Раннер сверяет JUnit с versioned exact manifest47, проверяет backend
   properties и exit code. Missing/invalid/zero/substituted/duplicate,
   failures/errors/skips/xfail не PASS. `PYTEST_ADDOPTS` не может незаметно
   сузить selection. Старый PASS заменяется RUNNING до preflight и
   затем BLOCKED/FAIL при ошибке; отчёт пишется атомарно.
5. Порча/удаление выполняется на настоящих временных content-addressed
   файлах собственного ObjectStore. Missing bytes при сохранённом registry
   record — integrity/content gap (`corrupt`), а не выдуманный паспорт.
   Partial P01/P02 остаётся пригоден для compiled SSR с явным gap.
6. Перезагрузка PG registries проверяет новые соединения и сохранность
   basis/revision/job, не заявляет restart всего сервера. Уже выданный frozen
   basis печатается после удаления исходных паспортных объектов; новый
   запрос по испорченному source подчиняется существующему source guard.
7. Полномочия проверяются через доверенный SubjectRef и реальные run/ref
   ownership gates. Это не новая сертификация browser login/AUTH13 worker.
   Foreign run даёт тот же отказ, что missing run; foreign ref в своём run
   эквивалентен missing ref, приватный контент не попадает в SSR.
8. Новые тесты не исправляют алгоритмы и не ослабляют отсутствующую
   метаинформацию. Для panel-несовместимости используется канонический
   `panel_entry` и явная проверка universe; неизвестный stage не считается
   доказанной panel-вселенной.

## Матрица независимых оракулов

| Корпус | Число на backend | Проверяемое поведение |
|---|---:|---|
| Исходные независимые contracts | 24 | F-C13-00…03, full groups, hash, raw Python→TS, profiles, checkpoint/reuse, retry-time identity, legacy cache, foreign run, gap |
| Registry reread | 3 | single/set/compare, тот же basis/revision/job и SSR; в PG фабрики пересозданы |
| Фактические missing/corrupt object bytes | 6 | single отказывает; set/compare partial без ложных таблиц и утечки повреждённого содержимого |
| Foreign ref против missing ref | 3 | single/set/compare, uniform outcome и отсутствие foreign content |
| Несовместимость | 3 | target/schema/single–panel, машиночитаемая причина, без новых print artifacts |
| Поздний паспорт того же этапа | 1 | исторический checkpoint не подменяется latest |
| Утрата источников после freeze | 3 | полный immutable print basis остаётся самодостаточным |
| Deployment source contracts | 4 | image pin/web build/UDS overlays/security; это source checks, не native VM |
| **Всего** | **47** | **43 backend-dependent + 4 source checks** |

## Воспроизведение

Нужны Node/npm и установленные locked workspace dependencies (`npm ci`),
Python dependencies из `scripts/pgv13cert/requirements.txt` и существующий
scientific/API runtime. Новых runtime requirements нет.

```bash
python -m unittest discover -s tests/unit -p test_pgv13_local_gate.py -v
python scripts/pgv13local/verify.py --memory --out ../pgv13local-memory
# CISSTAT_PGV13_CERT_DSN уже задан в защищённом окружении и указывает
# ТОЛЬКО на disposable PostgreSQL с CREATE/DROP DATABASE.
python scripts/pgv13local/verify.py --both --out ../pgv13local-both
# Либо отдельный PostgreSQL прогон:
python scripts/pgv13local/verify.py --postgres --out ../pgv13local-postgres
```

Каждый контракт создаёт отдельную тестовую БД и удаляет её. Production DSN
использовать нельзя. Раннер сам не создаёт PostgreSQL daemon/DSN и не читает
`.env`. В сессии использован native PostgreSQL16.2 из pgserver, UID1000,
UTF8, loopback TCP с отключёнными Unix sockets. Это не Docker/VM PostgreSQL.

`scripts/local_gates.py` не меняется: нужен явный специализированный прогон,
без включения PostgreSQL в default. AUTH-00 отдельно проверяется штатно.
После ZIP: явно stage `scripts/pgv13local/files.txt`, затем
`python scripts/local_gates.py --only auth00 --skip-install`.

## Результат и доказательства

* На историческом `2014fdf` тот же независимый corpus24 воспроизвёл
  **17 FAIL / 7 PASS**, без skips/errors. Исторический renderer отдельно
  собран из своего source, без подстановки нового compiled JS.
* На текущем source: Memory47/47 и native PostgreSQL47/47, ноль
  failures/errors/skips, exact manifest и registry evidence. После native
  прогона тестовых БД не осталось.
* Контракт раннера: первоначальный RED отсутствующего модуля → GREEN9/9.
  Во время разработки неверный `PYTHONUTF8=utf-8` не позволял запустить
  Python; отдельный реальный subprocess RED, исправление на `1`, затем
  GREEN. Промежуточные FAIL сохранены и не выданы за продуктовые findings.
* Первый panel-fixture использовал неизвестный stage `panel`, поэтому
  universe был unknown. Исправлен вход на действительный `panel_entry`,
  добавлен пин доказанной universe; производственный guard не менялся.
* Два канала executable mutation campaign: controls39+3 GREEN,
  drop_group/wrong_source_hash/wrong_job_id убиты обоими каналами,
  без collection/setup errors/skips. Runtime source bytes неизменны.
* TS regression: rendererCore/printLayout/printPassport/printSchema —
  137/137, 4 suites. Fresh renderer tsc build PASS.

Протоколы и XML: `scripts/pgv13local/protocols/`. `final-both/summary.json`
содержит оба результата, checksums actual source/compiled JS и всегда
`full_pgv13_certified:false`. Роуты/strict INDEX/ZIP overlay фиксируются
в отдельных protocols перед передачей.

Runtime исходники, HTTP paths/methods, DTO, OpenAPI/proxy/Compose и DDL
не меняются. AUTH-00 обновляется только для review/source fingerprints
сертификационных файлов. Сборка новых образов, миграции и recreate на VM
из-за этой поставки не нужны; после push тимлида достаточно `git pull --ff-only`.
Необходимые UDS image/transport/PNG испытания прежнего rollout сохраняются.

**Вердикт этапа 3: локальные durable/SSR контракты приняты.** Полный PGV-13
по-прежнему требует отдельной native UDS/final-image/P01-P02 PNG/content/
visual/OCR/job-download приёмки. Windows/PG18, полные default/scientific
suites и production builds обеих web shells этой работой не заявляются.
