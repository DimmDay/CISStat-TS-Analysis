# Акт независимой сертификации DOCLOG-9 (2026-10-24)

**Task ID:** DOCLOG-9-CERT. **Цель сертификации:** поставка DOCLOG-9
«Профили организации» (коммит **06b920c**; цель аудита — дерево
**5856764** = 06b920c + DOCLOG-8-CERT, продуктовые файлы DOCLOG-9
идентичны: DOCLOG-8-CERT добавляет только корпус сертификатора/акт/
worklog). **Метод:** «оракулы на своих данных, мутанты на своих
мутантах» (методология DOCLOG-3/4/5/6/7/8-CERT). Манифест sha256 не
ведётся и не используется (указание тимлида, прецедент
DOCLOG-2-FIX…8). Продуктовый код аудитом НЕ менялся: после кампании
md5 всех пяти файлов-целей байт-идентичен git HEAD (doc_profiles.py,
routers/doc_profiles.py, document_jobs.py, document_renditions.py,
document_render_worker.py), `git status` по продуктовой части пуст;
untracked — `scripts/doclog9cert/` (корпус) и этот акт.

## 1. Корпус сертификатора (оракулы на своих данных)

Namespace дизъюнктен repo-корпусам DOCLOG-0..9 (RUN-D9A\*, d9-\*,
d9prof-\*) и корпусам предыдущих сертификаторов (d6cert-\*, d7c-\*,
d8cert-\*): **RUN-D9C\*, d9cert-\*, ctx-d9cert-\*, subj-d9cert\***,
свои сессии d9cert-session-a/b/c (cookie-доступ к /v1/documentation),
свои ключи X-API-Key d9cert-key-\* — в том числе субъект с правом
**policy.admin через scopes БЕЗ роли admin** (d9cert-key-pol — §15
«permission sets через scopes, не новые роли» проверен дословно), свой
AC-сентинел env CISSTAT_D9C_SECRET_SENTINEL, свой ключ подписи.
Данные — СВОИ: собственные bound-runs, снимки (штатный
SnapshotService), документы/ревизии (ensure_document_revision), профили
(штатный OrgProfileService), свои рендер-цели.

**Итог: 71 GREEN ×2 (5.69 s / 5.53 s; финальная сверка после кампании
5.79 s / 5.88 s) на 5856764** — `scripts/doclog9cert/` (conftest.py,
test_d9cert_oracle_unit.py — 33, test_d9cert_oracle_api.py — 24,
test_d9cert_oracle_static.py — 14).

- **Unit (33), u01–u33**: каталоги профилей/валидаторов/подписи/WORM
  (u01); schema `doclog.org_profile/1` + disclaimer
  «not_a_legal_signature» (u02); имя обязательно/strip/prefix prof- (u03);
  version_no-каталог — 0/−1/«2»/1.5/None → отказ, **ПИН F-D9C2b: bool
  true проходит isinstance(int)** (u04); формат-каталог сервиса
  чувствителен к регистру (нормализация — роутер, u05); права §15:
  аноним → NotFound, без scope → AccessDenied, роль admin и scope
  policy.admin — оба пути (u06); **mandatory-аудит fail-closed + ПИН
  ПОРЯДКА F-D9C2: реестр пишется ДО аудита — при сбойном sink профиль
  остаётся созданным** (u07); retire — статусная запись,
  иммутабельность содержимого, идемпотентность (ровно одна
  audit-запись), атрибуция resource_id (u08); resolve: NotFound/
  FormatMismatch/Retired (u09); pdfa-валидатор: собственный рендер
  passed, поимённый каталог маркеров (header/pdfaid/conformance/
  outputintent/icc/fonts/encrypt/js/uri) с точными кодами findings
  (u10); обычный pdf НЕ проходит pdfa-валидатор (§20, u11); docx-
  валидатор: члены ZIP, внешние связи, xml_invalid, zip_invalid (u12);
  подпись: roundtrip, порча байтов → mac_mismatch, порча метаданных →
  mac_mismatch, MAC инвариантен к порядку ключей, mac_missing,
  **без ключа sign И verify БРОСАЮТ — ПИН F-D9C4: ветка key_unavailable
  недостижима (мёртвый код)** (u13); диспетчер валидаторов по
  ЗАПРОШЕННОМУ формату + переключатель validate_conformance (u14);
  docx-рендер: детерминизм, члены OOXML, гриф/футер/организация в
  байтах, пометка «Автоматически сгенерировано» (u15); экранирование
  недоверенного текста (u16); pdfa-рендер: маркеры, запрещённые
  включения отсутствуют, оформление в XMP (u17); **ПИН ДЕФЕКТА F-D9C1:
  pdfa-рендер НЕ байт-детерминирован через границу секунды** — область
  поражения ограничена (len равен, единичные байты), docx чист (u18);
  **ПИН механизма F-D9C1: ICC-заголовок littlecms несёт wall-clock
  (поля год/месяц/день/…/сек == текущий UTC)** (u19); расхождения двух
  рендеров лежат ТОЛЬКО в поле времени ICC-заголовков (область поражения
  точечно, u20); сквозной docx-цикл: ready + §19-доказательство
  (validation-record даже при passed, все привязки rendition/job/run/
  profile+version) (u21); failed-валидация: terminal failed
  profile_validation_failed, rendition_id="", findings сохранены (u22);
  подпись: манифест персистится, content_sha256 == rendition,
  независимая верификация сохранённых байтов (u23); без ключа — честный
  sign_key_unavailable, тихой неподписанной ready нет (u24); якорь:
  content_sha256/profile_id, append-only (u25); WORM: hold на документе
  с причиной `org_profile_worm:<profile_id>`, идемпотентный upsert
  (u26); mismatch: готовая цель и активное задание, тот же профиль —
  идемпотентно тот же job (u27); каталог гейтов заказа (Required/
  FormatMismatch/NotFound/Retired) (u28); policy-перепроверка на
  исполнении: retire между постановкой и рендером → terminal failed
  org_profile_unavailable (u29); безпрофильный legacy-выпуск не
  перекрывается профильным (u30); Memory-реестр: сортировка (name,
  version_no), фильтр, probe, find_duplicate (u31); привязка записи
  валидации к ВЕРСИИ профиля (u32); **структурная (pypdf) проверка
  каталога PDF/A: ровно один OutputIntent, /S == /GTS_PDFA1,
  DestOutputProfile — ссылка, /Metadata == XMP** (u33).
- **API (24), a01–a24**: аноним: uniform 404 на list/retire/validations/
  verify + **ПИН F-D9C5: POST create для анонима — 422
  org_profile_invalid вместо 404 (в create_org_profile нет ветки
  OrgProfileNotFound)** (a01); чужой аутентифицированный — список
  профилей видит (контракт), чужой rendition — uniform 404 (a02);
  201-контракт создания: schema/prefix/defaults/created_by==subject,
  audit ровно 1 (a03); 403 insufficient_scope (a04); **scope-based
  policy.admin без роли → 201** (§15 дословно, a05); 422-каталог с
  РАЗНЫМИ кодами (invalid vs format_mismatch, a06); 409 дубль, версия
  и имя по отдельности допустимы (a07); **ПИН F-D9C2b: JSON
  version_no=true → 201 с «version_no»: true** (a08); нормализация
  формата роутером (POST «PDFA», GET ?format=PDF), retired честно в
  списке (a09); retire-поток: статус/retired_by/audit ×1/идемпотентно/
  404/403 (a10); docx/pdfa без профиля → 422 (a11); каталог гейтов HTTP:
  422/404/409 с кодами (a12); сквозной docx: 202, org_profile_id в job
  metadata, ready, validations 200 с passed, скачивание — валидный OOXML
  с оформлением профиля (a13); mismatch 409 через HTTP (a14);
  failed-валидация через HTTP: job failed profile_validation_failed,
  ready-файла нет, GET validations по несуществующему rendition — 404,
  **доказательство живёт только в реестре по job — ПИН F-D9C3** (a15);
  verify-signature: passed → порча манифеста (append-запись с подменённым
  content_sha256) → mac_mismatch при неизменных байтах (a16);
  not_signed (a17); подписанный выпуск (без WORM) удалён draft-retention
  → verify честный **410 purged_artifact** (a18); **WORM-профиль:
  draft-retention НЕ удаляет выпуск (hold защитил, report честен)**
  (a19); **ломучий sink на mandatory-аудите через HTTP: 500 (не 503
  mandatory_audit_unavailable) И профиль остался созданным — ПИН
  F-D9C2** (a20); ломучий sink на standard-аудите НЕ ломает выпуск
  (§8/AC11) (a21); гигиена ошибок: без сентинела/traceback/postgres://
  (a22); org_profile_id переживает registry-roundtrip и виден в
  HTTP-выдаче jobs (a23); матрица доступа renditions-маршрутов: аноним/
  чужой ключ → 404, свой → 200 (a24).
- **Static (14), s01–s14**: миграция 0015 — файл↔каталог построчно,
  15 файлов/93 statement, 0015 == 8 statement (2 ALTER + 3 таблицы +
  3 индекса) (s01); DDL: БЕЗ FK на research_runs (org-сущность, паритет
  грантов 0013), JSONB findings/signature_manifest, индексы поимённо
  (s02); карта маршрутов: ровно 5 route-объектов / 4 пути с точной
  картой методов (s03); AUDIT_ACTIONS == 28 с четвёркой
  org_profile_*/rendition_*, классы mandatory/standard по каталогу
  требований (s04); в исходнике сервиса создание/retire —
  record_mandatory (через дефолт), валидация/якорь — record_standard
  ×2 (s05); frozen-каталоги PROFILE_FORMATS/KNOWN_VALIDATORS/
  SIGN_KEY_ENV/SIGNATURE_ALGORITHM/WORM_REASON_PREFIX + disclaimer в
  sign_content (s06); RENDITION_FORMATS docx/pdfa с точными media-type,
  HEAVY содержит docx/pdfa (s07); DOCUMENT_KINDS == 12 — DOCLOG-9 не
  добавляет вид (s08); чистота docx-рендера: фиксированные даты, без
  datetime.now/time.time в функции, экранирование в теле (s09);
  PG-реестр: 11 методов реализованы, якоря/валидации INSERT-only
  (без UPDATE/DELETE), UPDATE doc_profiles — только статусные поля,
  SQL без f-интерполяции (s10); выбор бекенда по
  CISSTAT_DOC_PROFILES_BACKEND/DATABASE_URL (s11); UI-панель: «use
  client» первой строкой, пять честных состояний, статус валидации
  ТЕКСТОМ («пройдена/не пройдена»), вызовы библиотечных функций (s12);
  UI-lib: documentationApiUrl/encodeURIComponent, ключ не в URL,
  org_profile_id в теле заказа, verify — POST (s13); контракт-док
  фиксирует честные границы («не названием файла», «НЕ юридическая ЭП»,
  «не переименование pdf», org_profile_worm, veraPDF — следующий срез)
  (s14).

## 2. RED на родителе

Корпус на родителе DOCLOG-9 **659db3d** через git-worktree: **collection
RED за 1.62 s** — `ImportError: cannot import name 'doc_profiles' from
'apps.api'`, **70 errors** (протокол protocols/red_parent.json, RED:
true). Корпус не вакуумный: тестирует именно поверхность DOCLOG-9.

## 3. Мутационная кампания («мутанты на своих мутантах»)

Двухканальная схема: **REPO** = test_doclog9_profiles +
test_doclog5_formats_worker + test_doclog4_document_delivery (161 тест;
флакующий repo-тест pdfa-детерминизма ИСКЛЮЧЁН из канала — см. F-D9C1:
зависимость от границы wall-clock секунды дал бы ложные киллы);
**ORACLE** = корпус сертификатора (71). **45 боевых мутантов + 3
no-op контроля** над пятью продуктовыми файлами.

**Итог: 27 DUAL-KILLED + 16 ORACLE-ONLY + 2 EQUIVALENT + 0 REPO-ONLY +
0 боевых SURVIVED; контроли 3/3 ALIVE; PATCH-FAIL 0; RESTORE-FAIL 0**
(protocols/mutations_summary.json, mut_\*.json; консолидация —
scripts/doclog9cert/consolidate.py, финальная MV3-сверка md5 файлов ==
git HEAD). Мета-валидация: **MV1** — dry-run 48/48 якорей (ровно одно
вхождение); **MV2** — классификатор сверен с синтетикой (PASS);
**MV3** — байт-в-байт восстановление после каждого мутанта (git
checkout -- + md5 == база; GUARD чистоты дерева перед порцией — урок
убитого посреди apply процесса); **MV4** — контроли C1–C3 ALIVE;
**MV5** — скан хвостов киллов: посторонних файлов нет.

**DUAL-KILLED (27):** M01 (pdfa без OutputIntent проходит), M04 (MAC
инвертирован), M05 (MAC не привязан к байтам), M06 (policy.admin не
проверяется), M08 (retired резолвится), M09 (формат не сверяется),
M10 (дубль допускается), M12 (passed-запись не пишется), M13
(WORM-причина теряет профиль), M14 (WORM никогда), M20 (uniform 404 →
403 списка), M21 (409→422 дубля), M22 (retire 404→422), M25
(безымянный выпуск разрешён), M28 (mismatch готовой цели снят), M30
(failed не останавливает выпуск), M31 (failed-запись не пишется), M32
(манифест не персистится), M33 (тихий неподписанный ready), M34 (якорь
не пишется), M35 (WORM не ставится), M36 (профиль не фиксируется в
metadata), M37 (passed-доказательство не пишется), M38 (экранирование
снято), M40 (pdfa = переименованный pdf), M42 (heavy снят), M45 (код
ошибки подменён).

**ORACLE-ONLY (16):** M02 (каталог шрифтов pdfa-валидатора), M03
(внешние связи docx), M07 (анонимный гейт управления), M11
(идемпотентность retire/двойной audit), M15 (класс аудита инвертирован
— repo не проверяет fail-closed слом), M16/M17/M18 (переключатель
политики conformance, фильтр и сортировка списков), M19 (префиксы id),
M23 (410 purged → 404), M24 (первая vs последняя подпись), M27 (resolve
на постановке — repo не различает фазу отказа), M29 (mismatch активного
задания), M39 (гриф не в байтах — repo проверяет лишь на docx-рендере
профиля-словаря), M41 (OutputIntent отвязан структурно — репо-проверка
текстуальная), M43 (фиксированные даты статикой). Перенос пинов в
repo-сюиту — кандидат N-плана (прецедент DOCLOG-8). **Атрибуция киллов
(протокол attribution.json): ни один ORACLE-ONLY не оживает без ЛЮБОГО
одного файла-оракула — каждый убит ≥2 файлами (избыточность покрытия,
нет единой точки отказа корпуса).**

**EQUIVALENT (2, честная классификация эквивалентных мутантов):**
**M26** — гейт PROFILE_FORMATS в request_rendition: resolve_profile
(fmt=…) проверяет ту же пару (формат профиля, формат рендера) на каждом
достижимом входе (формат профиля ограничен каталогом при создании),
тот же тип исключения; снят дублирующий слой защиты, поведенчески
неотличим. **M44** — предрендерная policy-перепроверка worker'а:
complete_render повторяет ту же проверку и роняет job тем же кодом
org_profile_unavailable, байты отбрасываются; наблюдаемое поведение
идентично (остаётся невыполняемая процессорная работа — вне контрактных
инвариантов; замечание для N-плана — см. N-D9C3).

**«Мутанты на своих мутантах» (2-й порядок, HO-срез): 6/6
DUAL-KILLED** (protocols/second_order_summary.json) — композиции пар из
разных функций: H01 (два маркера pdfa-валидатора), H02 (инверсия MAC +
отвязка байтов), H03 (гейт обязательности + resolve), H04 (экранирование
+ гриф DOCX), H05 (манифест + якорь), H06 (retired-резолв + mismatch).
**Маскирования нет:** ни одна композиция не ушла от обоих каналов.

## 4. Регресс и сборка

- **Полный tests/api дельта-0** (regress_delta0.py, кэш pytest
  отключён): цель **5856764+корпус 37F/2843P/42S** vs база 5856764
  (git-worktree) **37F/2772P/42S** — **множества FAILED-ID байт-идентичны
  (37/37, diff пуст, protocols/regress_delta0.json)**; +71 passed =
  ровно корпус сертификатора. Все 37F — предсуществующие средовые классы
  (duckdb/psycopg-DSN/моделинг и пр.), идентичны на обеих сторонах;
  флак F-D9C1 в обе стороны не попал (правило перепрогона зашито в
  regress_delta0.py на случай попадания).
- **Jest:** `doclog9-profiles-ui` + `doclog6-lifecycle-ui` = **23/23**
  (протокол jest_doclog9ui.txt).
- **Сборка:** import apps.api.main OK — **221 маршрут** (ровно 5
  route-объектов / 4 пути DOCLOG-9), миграции **15/93** (последняя 0015,
  8 statement), DOCUMENT_KINDS=12, AUDIT_ACTIONS=28 (четвёрка
  org_profile_\*/rendition_\*), HEAVY содержит docx/pdfa, schema
  `doclog.org_profile/1`; **продуктовое дерево чистое** (md5 пяти
  файлов-целей == git HEAD) — protocols/build_check.json, **BUILD: OK**.

## 5. Находки

- **F-D9C1 (СРЕДНЯЯ; пины u18/u19/u20): PDF/A-рендер не
  байт-детерминирован.** `render_snapshot_pdfa` нарушает заявленный пин
  AC03 («Рендер — чистая функция от (снимок, профиль)»; docstring
  `_pdfa_postprocess`: «Детерминизм: фиксированные даты (пин AC03)»).
  Причина: sRGB ICC-профиль, сгенерированный littlecms
  (`ImageCms.createProfile("sRGB")`), несёт **wall-clock создания в
  заголовке ICC (байты 24–36: год/месяц/день/час/минута/секунда)** —
  два рендера одного (снимок, профиль) через границу секунды дают
  разные байты → **разный content_sha256** (подпись/якорь/реестр
  фиксируют разные хэши одного выпуска; восстановление/повторный рендер
  не воспроизводимы байт-в-байт). Область поражения ограничена: длины
  равны, расхождения — единичные байты поля времени (u20); docx не
  затронут. Следствие: repo-тест
  `test_pdfa_render_markers_and_determinism` **флакует** (проба 14
  одиночных прогонов: 13 passed / 1 failed ≈ 7%; в полном прогоне
  files вероятность выше из-за холодного рендера). **Рекомендация**
  (DOCLOG-9-FIX): обнулять поле времени ICC-заголовка после генерации
  (байты 24–36 → константа) либо кэшировать профиль; после фикса
  инвертировать пины u18/u19 и вернуть флакующий repo-тест в канал.
- **F-D9C2 (СРЕДНЯЯ; пины u07/a20): mandatory-аудит создания профиля не
  fail-closed по состоянию.** `create_profile` пишет профиль в реестр
  ДО audit-записи; при недоступном audit-sink `record_mandatory` честно
  бросает MandatoryAuditFailure, но **профиль уже создан** (незарегистрированное
  защищённое действие; ретрай даёт 409 дубль). Дополнительно:
  routers/doc_profiles.py НЕ маппит MandatoryAuditFailure → **HTTP 500**
  (в documentation.py:306 тот же класс маппится в 503
  mandatory_audit_unavailable — паритет нарушен; retire-маршрут — та же
  картина). AC11-инвариант «защищённое действие НЕ выполняется»
  нарушен в части ПОРЯДКА (audit-после-записи). **Рекомендация:**
  audit ДО записи в реестр (или компенсация/saga-откат) + явная ветка
  MandatoryAuditFailure → 503 в обоих маршрутах.
- **F-D9C3 (низкая/средняя; пин a15): failed-доказательство недоступно
  через HTTP.** При failed-валидации запись пишется с `rendition_id=""`
  (rendition не существует) — единственный HTTP-каталог доказательств
  `GET /renditions/{id}/validations` по определению не отдаёт failed-
  записи; наружу торчит только `job.error_code`. §19 требует честной
  записи — она есть (реестр по job), но раскрытия нет. **Рекомендация:**
  каталог `GET /document-jobs/{id}/validations` (по job) либо
  `?include=failed` по run.
- **F-D9C4 (низкая; пины u13/P3): verify-signature без ключа —
  исключение, не честный failed.** В `_signature_validate` проверка
  ключа стоит ПОСЛЕ `_canonical_manifest` (который зовёт `_sign_key()`),
  поэтому ветка `key_unavailable` **недостижима (мёртвый код)**: при
  потере/ротации `CISSTAT_DOC_SIGN_KEY` верификация сохранённого
  манифеста бросает SignatureKeyUnavailable → на HTTP это 500 вместо
  honest failed-результата верификации. **Рекомендация:** вычислять
  expected только при наличии ключа (branch-order fix), тогда verify
  вернёт failed `key_unavailable` (после фикса инвертировать пины).
- **F-D9C5 (низкая; пин a01/P4): анонимный POST create — 422 вместо
  uniform 404.** В `create_org_profile` нет ветки OrgProfileNotFound:
  аноним падает в общий `OrgProfileError` → 422
  `org_profile_invalid` («Контур профилей недоступен»). Решающая
  таблица DOCLOG-0 (аноним — uniform 404, контур не дисклоужается)
  нарушена для одного маршрута из пяти. **Рекомендация:** добавить
  ветку OrgProfileNotFound → 404 (после фикса инвертировать a01).
- **N-D9C1 (низкая; пин u04/a08/P-… u04/a08): bool version_no
  принимается.** `isinstance(True, int)` == True → профиль
  `version_no=true` (JSON-ответ «version_no»: true; Memory-путь);
  durable-контур (INTEGER-колонка) рассинхронизирован. Аналог F-D7C2
  (NaN TTL). Рекомендация: явный `type(version_no) is int` либо
  `bool`-отсечение.
- **N-D9C2 (низкая/средняя; пин u14/P6): validate_conformance=false —
  выпуск без конформности.** Переключатель политики выключает
  валидатор: мусорные байты становятся ready с passed-записью
  («валидация отключена политикой профиля»). Колонка есть в схеме
  (0015), но контракт-док не описывает семантику false; для архивного
  pdfa это дыра в «проверяемой конформности». Рекомендация: описать в
  контракте и/или запретить false для pdfa.
- **N-D9C3 (низкая; зонд P5): worm_lock молча не ставится при пустом
  revision.** job.revision_id == "" (прямой сервисный заказ без
  ревизии) → apply_worm_hold возвращает False, значение игнорируется →
  выпуск ready БЕЗ WORM-холда (fail-open на краю). Через HTTP
  renditions всегда с ревизией (POST требует revision_id в пути), но
  сервисный контракт честнее сделать fail-closed: job failed
  `worm_hold_unavailable` либо обязательная ревизия для worm-профилей.
- **N-D9C4 (низкая): `GET /org-profiles?format=<неизвестный>` — 200 с
  пустым списком** (не 422): фильтр не валидируется по каталогу;
  согласуется с soft-фильтрами elsewhere, но для формата с каталогом
  допустим более честный 422.
- **N-D9C5 (наблюдение; пин a16):** verify-signature берёт ПОСЛЕДНЮЮ
  signature-запись ([-1]) — при нескольких записях верифицируется
  последняя; append-only реестр позволяет дописать запись (в a16 это
  использовано как честный тест порчи метаданных). Ограничение
  дописывания — на усмотрение владельца реестра (сейчас append_validation
  открыт на уровне API реестра).

## 6. Вердикт

**СЕРТИФИЦИРОВАНО С НАХОДКАМИ (PASSED WITH FINDINGS).** Поверхность
DOCLOG-9: критерий завершения §19 — «выбранный профиль подтверждён
валидатором и organisational policy, не названием файла» — подтверждён
двухканально:

- **Подтверждение валидатором (§19/§20):** failed-валидация — честный
  terminal failed `profile_validation_failed` без ready-файла (u22,
  a15, M30/M31); passed-выпуск несёт proof-запись с полными привязками
  (u21/u32, M12/M37); валидатор проверяет БАЙТЫ по поимённому каталогу
  маркеров (u10–u12, M01/M02/M03), обычный pdf не проходит pdfa (u11,
  M40), структурный каталог PDF/A подтверждён pypdf'ом (u33, M41).
- **Подтверждение policy (§19/§15):** профиль применяется только
  ACTIVE своего формата (u09/u28, M08/M09), право управления —
  policy.admin через scopes, не роль (u06/a05, M06/M07), аноним не
  дисклоужает контур (a01, M20; исключение — F-D9C5).
- **Одна визуальная форма на цель (§11/AC09):** mismatch готовой цели
  и активного задания, идемпотентность того же профиля (u27/a14,
  M28/M29), дубль (name, version_no) закрыт (a06, M10), безымянный
  выпуск запрещён (a11, M25).
- **Гарантии профиля:** подпись — двухканальная привязка
  метаданных+байтов, независимая верификация, честный отказ без ключа
  (u13/u23/u24, M04/M05/M32/M33); якорь — append-only по content_sha256
  (u25, M34); WORM — retention hold на документе с причиной
  `org_profile_worm:<profile_id>`, draft-retention не удаляет выпуск
  (u26/a19, M13/M14/M35), purged — честный 410 (a18, M23).
- **Аудит (§8/§14.1/AC11):** создание/retire — mandatory, валидация/
  якорь — standard (s04/s05, M15); ломучий sink не ломает standard-
  поток (a21); **ломучий sink на mandatory — операция прерывается, но
  состояние уже изменено (F-D9C2 — главная находка).**
- **Оформление и чистота (R06/AC03/AC05/AC16):** гриф/футер/организация
  в байтах, пометка generated, экранирование недоверенного текста
  (u15/u16, M38/M39), docx байт-детерминирован (u15, s09); **pdfa —
  НЕ детерминирован (F-D9C1 — вторая ключевая находка).**

27/45 боевых мутантов DUAL-KILLED, 16 ORACLE-ONLY (repo-канал слабее на
негативных ветках — перенос пинов в repo-сюиту = кандидат N-плана,
прецедент DOCLOG-8), 2 EQUIVALENT (дублирующие слои защиты, обоснование
в §3), 0 REPO-ONLY, 0 боевых SURVIVED, контроли 3/3 ALIVE; 2-й порядок
6/6 (маскирования нет); атрибуция — избыточность ≥2 файла-оракула на
каждый ORACLE-ONLY килл. Дельта-0: FAILED-ID идентичны 37/37, +71 =
корпус. Jest 23/23. BUILD: OK, продуктовое дерево чистое.

Находки F-D9C1…F-D9C5 и наблюдения N-D9C1…N-D9C5 — не блокеры поставки;
рекомендации сформулированы. Живой PostgreSQL-прогон 0015 — за границей
песочницы (честная граница, паттерн AUDIT-6A); pg-контур закреплён
статически (s01–s02/s10–s11).

**План DOCLOG-9-FIX (кандидат, по решению тимлида):** (1) F-D9C1 —
обнуление поля времени ICC-заголовка (байты 24–36) после генерации +
возврат repo-теста в канал; (2) F-D9C2 — audit ДО записи реестра +
маппинг MandatoryAuditFailure → 503 в create/retire; (3) F-D9C4 —
branch-order в _signature_validate (честный failed key_unavailable);
(4) F-D9C5 — ветка OrgProfileNotFound → 404 в create_org_profile;
(5) F-D9C3 — HTTP-каталог failed-доказательств по job; (6) N-D9C1 —
bool-отсечение version_no; (7) N-D9C2 — семантика validate_conformance
в контракте; (8) N-D9C3 — fail-closed для worm без ревизии; (9) перенос
ORACLE-ONLY пинов в repo-сюиту. Для (1)–(4) пересертификация адресная
(повторный прогон корпуса + целевые мутанты M01/M02/M04/M05/M07/M13/
M15/M20/M23/M24/M39/M41/M43), для (9) — прогон repo-канала.

Deliverable: ZIP cisstat-doclog9-cert.zip → открытый контейнер сессии
(download): scripts/doclog9cert/ (conftest, оракулы unit/api/static,
mutations.py, consolidate.py, regress_delta0.py, build_check.py,
red_parent.py, probe_findings.py, protocols/),
docs/cert_doclog9_2026-10-24.md (этот акт), worklog/worklog11.md
(запись). Веб-приложение :3000 — страница поставки с кнопкой
скачивания. Без commit/push (AGENTS.md). Манифест sha256 не ведётся
(указание тимлида, прецедент DOCLOG-2-FIX…8).
