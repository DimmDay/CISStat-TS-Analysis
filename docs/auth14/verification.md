# AUTH-14 — протокол проверки

База a16b31bd0c3d49586de24d3556a39e43b9cc3321. Ни commit/push, ни установка VM из сессии не выполнялись. Итоговые stdout/stderr находятся в `scripts/auth14/protocols/`; намеренные RED сохранены отдельно от GREEN. Матрицы Windows/PG18 заданы в CI, здесь не исполнялись.

| Проверка | Факт |
|---|---|
| TDD RED | отсутствующий compute contract; deadline при заблокированном DB checkpoint; generated features и whole-plan/per-phase work limits — воспроизведённые FAIL |
| Минимальный runtime contracts |16/16 PASS; настоящий subprocess kill/progress, Linux native descendant stop, independent deadline, fixed-point/coverage/overflow/holdout/profile|
| AUTH-13 process regression |8/8 PASS|
| PostgreSQL AUTH-14 перед финальным общим прогоном |12/12 PASS на реальной disposable PG16.2; reserve/settle/retry/missing progress/audit fault/global capacity across Accounts; реальные PELT, sync, stateless и оба async aliases|
| Локальная calibration |90 реальных cases + capacity1;60 train/30 held-out;90 cost checks PASS; raw report, candidate, validation и точный checksum в reference/README.md|
| Profile validator | raw report→candidate reproducible, current environment/kernel check и atomic install PASS; live pricing не активировался|
| Actual routes |239 API,243 bindings; added=[],missing=[]; AUTH-00 inventory585→592 за счёт6 explicit internal surfaces и1 supervisor thread; automatic545→546|
| Documentation route parity |PASS:21 документационных маршрутов прежние, PGV объединённый scope55|
| BFF Idempotency-Key |11/11 focused Jest PASS|
| Scientific targeted regression |81 PASS /1 FAIL из82; существующая на чистой базе ошибка ожидания текста Deepar, см. ниже|

У scientific FAIL `test_workflow_rejects_catalog_only_model_instead_of_fabricating_metrics` baseline ожидает другой applicability message для `deepar`. Тот же FAIL повторён в отдельном чистом worktree **точно a16b31b**; оба протокола приложены. Production exception не заменена fabricated metrics. Это не зелёный полный pytest: полный API/scientific suite не заявляется пройденным. Фокусные scientific tests запускались до финального исправления supervisor и нормализации dimensions; окончательный runtime/adapter regression выполняется native/contract suites на финальных байтах.

Docker engine в контейнере отсутствует: выполнены imports/static/deployment checks и production web builds, но API/web Docker images здесь не собирались. VM benchmark/целевые лимиты/production throughput и Windows/PG18 native требуют отдельных прогонов по runbook. Локальный reference не сертифицирует всю VM/все модели/весь AUTH-CERT.

Дополнительно deployment/import/font guards:33/33 PASS. Обе production web builds PASS с реальными Inter woff2 из существующего локального кэша через документированный Next font-response hook. Обычный build: embedded PASS, standalone сетевой запрос fonts.gstatic.com заблокирован политикой сессии; эта средовая причина сохранена в web-builds.txt и не выдаётся за дефект кода. Повтор обеих сборок без сетевой загрузки — web-builds-cached-fonts.txt; application/dependency sources не менялись, hook не входит в deployment.

Финальный общий native AUTH-02…14 regression: **268/268 PASS**, skips0, PostgreSQL16.2,270.025с. AUTH-14 sync replay проверен на двух выбранных trials (не только один). Протокол native-all-auth.txt. Clean ZIP overlay проверен на отдельном detached worktree точной базы a16b31b: CRC и все payload bytes совпали, manifest явно staged только в delivery tree. **17/17 default gates PASS**; AUTH-00 INDEX проверен дважды,49 contract tests PASS, source INDEX остался пустым. Jest2838 PASS/2 штатных skips/0 FAIL (2840 total), renderer build и typecheck обеих оболочек PASS. Полный лог — delivery-overlay.txt. Его финальная фраза об opt-in PG относится к этому default runner: отдельный native-all-auth.txt подтверждает268/268 на живом PostgreSQL.

Итоговая поставка:65 task-only файлов, без зависимостей/generated data/deletions, overlay + manifest + worklog. После включения финального протокола сверены все bytes и неизменность тестировавшихся runtime/policy sources; final AUTH-00 INDEX/profile checks повторены. SHA-256 ZIP и delivery proof лежат рядом в download/. Коммитов/push нет.
