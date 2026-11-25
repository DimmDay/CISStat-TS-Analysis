# PGV-PNG-FIX — первый экспорт новой загрузки

Дата: 25.11.2026, Москва. База: `389b93031f7e84bd626a4c5fd8fd1bfb0f2b11cd`.

## Проектирование

Два подтверждённых дефекта: первоначальный UploadResponse показан без frozen
visual_result Обзора; общий V01 builder теряет допустимую `data_revision=0`.
Результат исправления: три вида Обзора фиксируются в момент регистрации
загрузки, первый POST экспорта с ревизией 0 проходит до managed очереди без
повторного GET dataset. Прежние отказы доступа/контекста/недоступных источников
и обязательная валидация остаются в силе.

Решения:

1. В `register_uploaded_dataframe` сначала собрать окончательный UploadResponse
   с extra parse warnings, затем передать **тот же** JSON в существующий
   `promotion_integration.notify_visual_result` для preview/tech_table/quality.
   Использовать существующий best-effort producer, его receipt и заголовки.
   Одна точка покрывает file и DB load; научных запросов из export нет.
2. В `build_visual_print_snapshot` проверять отсутствие ревизии через `is None`.
   Ноль переносится как `"0"`, отсутствующая версия остаётся отсутствующей
   и отвергается прежним валидатором. Не подставлять фиктивную версию 1.
3. Приёмочные тесты: валидные 0/7 и отсутствующая версия; actual file/DB
   registration и best-effort сбой; полный native HTTP fresh upload → первый
   экспорт/повтор/idempotency/foreign denial, четыре вида трёх модулей.
4. Быстрый default local gate + отдельный strict native runner и CI PostgreSQL;
   отсутствие DSN/skip не считается native PASS. Не изменять старый акт
   диагностики или его RED-протоколы задним числом.

Риски: неканоничные producer данные не должны ломать upload; новый result_ref
не раскрывает credentials. Дополнительный freeze не меняет научный ledger,
семантику загрузки, контракт body или авторизацию. Смена даты после upload
не повышает data_revision: тест проверяет обычное подтверждение структуры.
Отсутствие даты/цели сохраняет честный source_unavailable. Привязка UI к
конкретному result_ref и общая историческая семантика экспортов — отдельная
задача; этот срез исправляет два доказанных блокера.

## Поставка и эксплуатация

Изменяются Python API и проверки. Новых HTTP methods/paths, DTO, DDL или
renderer/UI изменений нет. Новые fingerprints/evidence и reviewed test/tool
sources в AUTH-00 обновляются после проверки actual routes. Нужен новый API
образ. Действующий UDS rollout использует согласованные api/web/renderer
pins; выпуск — через `docs/pgv13_release.md`, с новым bundle и сохранением
текущих Compose inputs/volumes. Base-only `docker compose up` для работающего
UDS-релиза не подходит. Старый bundle/акт не переписывать под новые образы.

## Верификация

До runtime-правки: новые API-тесты **4 FAIL / 2 PASS** (ноль, отсутствие
producer freeze file/DB и его receipt). Настоящий native PostgreSQL —
**2 tests / 4 failing assertions**: нет трёх initial visual_result и 503
на графике/EDA/профиле пропусков. Протоколы RED сохранены как есть.

После исправления:

* API **6/6**, tooling gate **2/2**, default `pgv-png` PASS;
* PostgreSQL16.2 TCP/UTF8 **2/2**, skips0: первый экспорт без GET dataset,
  идемпотентный повтор/одна managed reservation, отмена, uniform404 чужому,
  график/EDA/профиль пропусков с revision0. Product/API/builders/registries
  не подменяются; worker выключен, это проверка настоящей очереди;
* совместно с существующим personal-demo HTTP/science корпусом **4/4**:
  verified email → upload → научный pipeline → forecast/CSV. Отдельные
  disposable DB очищены, native финальный повтор после fixture-isolation
  уточнения — **2/2**, skips0;
* PGV/Upload/DB/DOCLOG-recheck **682 PASS / 1 FAIL**. Тот же полный корпус
  на чистом `389b930` — **676 PASS / 1 FAIL**: один и тот же ID
  `TestCancelRaceGate::test_complete_render_finishes_running_job`,
  прежний fixture `SimpleNamespace` без `.format` против PGV14 complete_render.
  Дельта — только шесть новых зелёных тестов, существующий отказ не исправлялся;
* UI/print schema/registry — **122/122**, четыре Jest suites;
* renderer tsc и обе Next production сборки PASS (embedded20/standalone27).
  Обычная Next-сборка ожидала внешний Inter; завершённый прогон использовал
  штатный `NEXT_FONT_GOOGLE_MOCKED_RESPONSES` с настоящими локальными
  `@fontsource-variable/inter@5.3.0` файлами. Этот hook и font package — только
  окружение проверки, в API/web исходники, зависимости и ZIP не входят;
* AUTH00 unit **61/61**; actual routes **285 API / 289 bindings / 669 entries**,
  added/removed=[]; полный reviewed INDEX fence проверяется в итоговом
  delivery-протоколе с отдельным Git index без изменения рабочего INDEX.

Полный Jest не завершён (общий запуск остановлен на сборе suites без результата);
заявлен только завершённый адресный прогон. Native Windows/PG18 и remote CI,
Docker build/UDS/Chromium/реальные PNG/VM deploy не выполнялись. Они остаются
штатной CI/VM приёмкой. Это исправление двух блокеров, не полный PGV-CERT.

## Применение

ZIP распаковать в корень checkout `389b930`, затем:

```powershell
python scripts/local_gates.py --only pgv-png --skip-install
git add --pathspec-from-file=scripts/pgv_png_fix/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

Commit/push выполняет тимлид. VM-команды полного coherent выпуска с новым
bundle: `docs/pgv_png_fix_vm.md`. HTTP methods/paths/DTO/DDL не изменились;
AUTH-00 обновляет fingerprints reviewed источников, а не классификации.
`inventory.md` остался побайтно прежним (строки карты не изменились).
Старый диагностический акт/его файлы не требуются для применения этого ZIP.
