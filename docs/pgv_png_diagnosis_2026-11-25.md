# PGV PNG: исследование отказов перед сертификацией

Дата: 25.11.2026 (Москва). База: `389b93031f7e84bd626a4c5fd8fd1bfb0f2b11cd`.
Запрос: воспроизвести и объяснить последовательность `source_unavailable`
→ `visual_export_unavailable`. Изменения runtime не входят в эту задачу.

## План и границы

1. Сопоставить тексты UI с HTTP-кодами, пройти producer → durable result →
   print snapshot → revision → managed job.
2. Повторить вход, загрузку и повторное открытие через полный `apps.api.main`
   с настоящими PostgreSQL/AuthSession/CSRF/ownership/AUTH-13; исходники продукта
   оставить неизменными. Данные, учётные записи и БД — только одноразовые тестовые.
3. Проверить несколько видов, перехватить исходное исключение без изменения
   поведения, проверить причинность отдельным диагностическим контролем.
4. Отделить факты воспроизведения от гипотез о VM; не получать секреты,
   не подключаться к production, не заменять HTTP-прогон браузерным актом.
5. Сохранить протоколы, выводы, рабочую запись и task-only ZIP. Проверить
   неизменность runtime и AUTH-00. Сборка продукта не требуется при отсутствии
   runtime-изменений; границы проверок указать явно.

Известные риски: fixtures PGV с заранее seeded ненулевой ревизией могут
маскировать начальное состояние настоящей загрузки. Нельзя выдавать новый
producer GET за повторный экспорт без науки. Нельзя объявлять renderer
неисправным по ошибке, возникшей до постановки задания.

## Вердикт

**Дефекты воспроизведены на неизменённом runtime `389b930`. PGV-CERT
заблокирован. Это два последовательных дефекта продуктового пути A.**
Синхронизация сервера с этим коммитом не устраняет их: они присутствуют в нём.
Это заключение по коду и локальному native HTTP-воспроизведению; свежие логи,
фактические образы и действия в браузере production этой сессией не исследованы.

## Воспроизведение и факты

Команда из корня checkout (каталог `--out` должен быть новым и вне checkout):

```bash
python scripts/pgv_png_diagnosis/reproduce.py --out /tmp/pgv-png-diag-NEW
```

Нужны зависимости импорта API, `psycopg[binary]`, `pgserver`.
Скрипт запускает отдельный PostgreSQL 16.2 по TCP, создаёт/удаляет одноразовую БД
через существующий AUTH-CERT harness. Браузерные AuthSession cookie, Origin,
CSRF, ownership, required storage, startup warmup и AUTH-13 — настоящие.
SMTP/production/секреты VM не используются. Клиент — HTTP TestClient, не браузер.
Для графика передаётся минимальный безопасный SVG: проверяется admission
экспорта, а не точность печатной геометрии. Render worker выключен;
рисование PNG не является предметом этого воспроизведения.

Сценарий: личный вход → CSV 120 месячных наблюдений, `date,value` → явное
подтверждение даты → `/progress/trace` → POST visuals → GET dataset → POST visuals.
Далее открываются ещё три настоящих producer endpoint.

| Шаг / вид | HTTP | Результат |
|---|---:|---|
| После upload, до GET dataset: `upload.overview.tech_table` | 409 | `source_unavailable` |
| После GET dataset: тот же вид | 503 | `visual_export_unavailable` |
| GET timeseries → `upload.chart.series` | 503 | Тот же дефект версии |
| GET stats → `eda.descriptive.stats` | 503 | Тот же дефект версии |
| GET missing-profile → `preprocessing.missing.overview` | 503 | Тот же дефект версии |
| Диагностический контроль: только сохранить `0` как `"0"` в новом снимке | 202 | Настоящее managed задание `queued` |

Все producer GET вернули 200 и `X-Visual-Result-Ref`; все visual_result
сохранились с `data_revision=0`. До контрольного опыта `document_jobs` пуст:
отказы происходят **до очереди и до IPC/Chromium**. В контрольном опыте
создана одна запись `auth_worker_jobs`; PNG-байты не строились.
После прогона одноразовых БД не осталось.

## F-PNG-01 — показан результат upload, но отсутствует frozen visual_result

`apps/api/upload_common.py::register_uploaded_dataframe` сохраняет датасет и
вызывает `notify_data_version_registered`, но не `notify_visual_result` для
трёх видов Обзора. Возвращённый UploadResponse уже содержит preview,
columns_info и quality. `TsAnalysisUpload.tsx::acceptUploadedData` сразу
показывает его; эффект GET `/dataset` прекращается при наличии `uploadData`.
Таким образом, видимый результат и активная кнопка не означают, что источник
печати был зафиксирован.

Первый POST достигает `resolve_frozen_result`, не находит visual_result и
получает `VisualSourceUnavailable` → 409 `source_unavailable`.
UI (`visualExports.ts::visualExportErrorText`) показывает точную первую фразу
пользователя. После ухода/возврата GET `/dataset` проходит
`get_session_dataset::notify_visual_result` и сохраняет три результата.
Первый блокер снимается, но обнаруживается следующий.

Граница: такой начальный пропуск доказан для Обзора upload. Не утверждается,
что каждый научный endpoint пропускает свой producer. Самостоятельно
загружаемый график может сразу дойти до F-PNG-02 без первого 409.

## F-PNG-02 — валидная нулевая ревизия теряется при сборке print snapshot

Начальная `AnalysisSession.data_revision` равна **0**. Это нормальная версия,
а не отсутствие результата: загрузка устанавливает 0; изменение данных
повышает счётчик. `build_visual_print_snapshot`, `visual_exports.py:1057`:

```python
"artifact_version": str(
    getattr(result_artifact, "data_revision", "") or ""
),
```

Выражение `0 or ""` даёт пустую строку. При этом соседнее поле
`expected_context.data_revision` использует проверку `is not None` и
правильно содержит `"0"`: snapshot внутренне противоречив.
`print_schema.validate_print_snapshot` закономерно возвращает
`missing_data_version@data_artifact.artifact_version`; `persist_visual_artifact`
выбрасывает `ArtifactPayloadInvalid`. Общий `except Exception` маршрута
POST visuals превращает его в 503 `visual_export_unavailable`, а клиент —
в точную вторую фразу пользователя. Реальный источник сбоя — программная
ошибка до создания печатной ревизии/задания, а не временная перегрузка.

Контроль причинности: в отдельной mock-обёртке тестового процесса после вызова
настоящего builder только `artifact_version` заменён на `str(actual_revision)`.
При фактической ревизии 0 исходное значение было `""`; после сохранения `"0"`
тот же запрос прошёл все последующие настоящие слои и дал 202 queued.
Обёртка не записывалась в код продукта и не является поставкой исправления.

Область дефекта — общий V01 builder PGV-10/11/12 для результатов с нулевой
ревизией. На четырёх видах проверено фактически; полного обхода всех sites,
modeling/forecasting jobs и новых PNG этой диагностикой не выполнено.
Паспорта P01/P02 используют другие builders: прежняя их приёмка не покрывает
этот дефект пути A.

## Почему зелёные тесты и прошлые акты его не обнаружили

Повторный PGV-10 — **46/46 PASS**, но fixture задаёт `DATA_REVISION=7` и
заранее создаёт frozen result. В PGV-11 fixture — 3, PGV-12 — 7.
UI-тесты отдельно подменяют ответ запроса экспорта.
Это не сценарий «новая загрузка ревизии 0 → реальный UI input → очередь».
Журнал PGV-10 честно ограничивает приёмку Memory/fake-renderer и исключает
живую браузерную приёмку; акты PGV-13/14 ориентированы на P01/P02.
Структурный registry coverage не доказывает успешность первого экспорта.

Новый opt-in acceptance oracle:

```bash
python -m pytest scripts/pgv_png_diagnosis/test_revision_contract.py -q
```

На базе: **1 FAIL (0 → пустая строка), 1 PASS (положительный контроль 7)**.
Это ожидаемый незакрытый RED; default pytest (`testpaths=tests`) не изменён.
Новый Jest-прогон настоящего VisualExportButton с записанными native HTTP
ответами воспроизводит обе точные фразы при unmount/remount: **1/1 PASS**.
Это тест отображения записанных ответов, не живая browser-E2E.

## Дополнительный разрыв восстановления (наблюдение по коду)

UI экспорт передаёт view/context/SVG, но не result_ref из producer response;
в `RequestVisualExportInput` такого поля нет. Lazy fallback
`_freeze_saved_fallback` без result_ref немедленно возвращает пустой список.
При сбое первоначального freeze кэш сохранённого ответа не спасает такой
клик. Это не причина `missing_data_version`; отдельный риск спецификации
§6 (экспорт именно показанного результата, CAS/result token).

## Следующий исправляющий срез и условия пересертификации

1. Сохранять 0 как настоящую версию, сохранив честный отказ для None.
2. Замкнуть producer freeze в первоначальном общем пути file/DB upload,
   не заставлять пользователя переоткрывать вид для служебной записи.
3. Проверить связывание кнопки с ref/context/version **показанного** результата
   и безопасный lazy transfer; не запускать научные GET из export.
4. Закрепить настоящий fresh-upload сценарий revision 0 и проверку всех
   применимых render sites. Отдельно проверить unconfirmed/no-date состояния,
   чужие refs, context change, store failure и разрешённые исторические версии.
5. После исправления — согласованные образы и реальный путь до ready PNG,
   скачивания и просмотра в обеих оболочках. Текущий опыт доказывает admission,
   но не заменяет final-image/render/visual приёмку.

В этой задаче runtime/HTTP-поверхность/DDL/deployment/gates не меняются.
Карта AUTH-00 не требует регенерации. Результаты проверок и exact состав
поставки — `scripts/pgv_png_diagnosis/protocols/` и `files.txt`.
