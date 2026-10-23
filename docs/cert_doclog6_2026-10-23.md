# Акт независимой сертификации DOCLOG-6 (2026-10-23)

**Task ID:** DOCLOG-6-CERT. **Цель сертификации:** поставка DOCLOG-6
«Согласование и архив» (upstream **70c9c1a** — коммит DOCLOG-6, HEAD
origin/main; клон по прямому указанию тимлида, рабочее дерево чистое,
расхождений с origin/main нет). **Метод:** «оракулы на своих данных,
мутанты на своих мутантах» (методология DOCLOG-3-CERT/4-CERT/5-CERT).
Манифест sha256 не ведётся и не используется (указание тимлида).
Продуктовый код аудитом НЕ менялся: md5 всех четырёх мутационных целей
до/после кампании байт-идентичен; `git status -- apps/ packages/ tests/`
пуст; changed tracked-файл единственный — `worklog/worklog10.md` (запись
сертификатора), untracked — `scripts/doclog6cert/` (корпус).

## 1. Корпус сертификатора (оракулы на своих данных)

Namespace дизъюнктен repo-корпусу DOCLOG-6 (RUN-D6A*/RUN-D6B*, d6-*,
ключи d6-admin-key-7f31/d6-reviewer-key-42ab) и корпусам 3/4/5-CERT:
**RUN-D6C\*, d6cert-\*, d6c-cert-\***, tenant `tenant-d6cert-b`, свои
API-ключи (admin/writer/documentation.write/approver/documentation.approve
в 6-сегментном формате реестра). Данные — СВОИ: собственные
frozen-снимки ПРЯМОЙ КОНСТРУКЦИИ ReportSnapshot (свои cutoff 61/2061 и
62/2062, captured_at, кириллические claims, ctx-d6cert-1/2,
data_revision 7/8/9, честные partial/complete/empty-полноты), валидные
id `rs-<hex32>` (SNAPSHOT_ID_PATTERN), регистрация в штатном
SnapshotRegistry со своим ObjectStore; approval связывает МОЙ
payload_sha256 (AC07 проверяется на собственных байтах).

**Итог: 79 GREEN (unit 25 + API 42 + static 12) на 70c9c1a** —
`scripts/doclog6cert/` (conftest.py, test_d6cert_oracle_unit.py,
test_d6cert_oracle_api.py, test_d6cert_oracle_static.py; финальный
прогон корпуса 79/79 ×3).

- **Unit (25), u01–u25**: fail-closed policy (двух лиц по env, case-
  нормализация значения, garbage→single с warning); retention-порог
  (дефолт 30, явный 45, отрицательный/garbage→дефолт, 0 легитимен);
  разделение прав lifecycle_rights по СВОИМ субъектам (аноним none,
  admin_full_catalog, гранулярность четырёх scopes api_key, scoped-
  режим без scopes — scoped_mode_no_pilot_rights, session-суррогат в
  пилоте и его же отказ в scoped); вычислимое состояние ревизии из
  append-only записей (draft/финал retracted/superseded); Memory-реестр
  (порядок approvals по (created_at, id), latest_approval,
  сервисный фильтр approve-only, retention upsert/get/list с копиями);
  контракт записей (policy_version, глубокая копия manifest);
  фабрика Memory по умолчанию; канонические JSON-хелперы (детерминизм
  по порядку вставки, раундтрип); replace_record без алиасинга;
  _flatten_claims ключом «секция:текст».
- **API (42), a01–a42**: полный поток на своих данных с ТОЧНЫМ
  expected_snapshot_sha256 (корректный hash принимается — репо-канал
  покрывает только отказ); honest details publish-записи (approval_id,
  snapshot hash, supersedes_revision_id=null для первой публикации);
  pin с ТОЧНЫМ reason `document:{id}:published:{version_no}` и
  ref_kind/ref_id/created_by (репо-канал проверяет только префикс);
  повторный request 422; publish после retract 422; повторный publish
  superseded 422; supersede с ОБЕИХ сторон (superseded_by v1 и
  supersedes_revision_id в publish-записи v2); **manifest только из
  ready-форм** (своя failed-формa исключена — M06-класс); 409 на
  подмену content_sha256 готовой формы; **409 на ПЕРЕМОРОЖЕННЫЙ под
  тем же id снимок** (байты/hash консистентны для loader'а T8, approval
  связан старый hash — M07-класс, репо-канал не достигает); approval
  не переносится на новую ревизию; uniform 404 чужому на ВСЕ ДЕСЯТЬ
  маршрутов DOCLOG-6 (включая archive/verify и diff — репо покрывает
  семь); аноним 404; scoped-режим 403; **гранулярность scopes на своём
  run key-субъекта**: writer запрашивает/не утверждает/не публикует
  (403 insufficient_scope — ресурс свой, права нет), не-admin ключ на
  чужой run — 404 решающей таблицы; второе лицо ADMIN (via=api_key,
  другой субъект); two_person: самосогласование владельца 422 без
  изменения состояния, reject-ветка вторым лицом (lifecycle
  [requested, rejected]); **mandatory audit fail-closed на publish**
  (503, состояние approved неизменно — репо покрывает approve/retract)
  и **восстановление после отказа sink'а** (повторное решение 200,
  публикация выполняется — «сжигание» согласования отсутствует);
  publish-policy на СВОИХ снимках: **пустые секции 422
  publish_blocked_gaps** (репо-канал недостижим — сборщик всегда
  строит секции), D10 partial публикуется, D11 partial блокируется;
  retention: hold/release с очисткой причины, invalid action 422,
  sweep с СВОИМ env=1 (draft_days отражён честно), **повторный sweep
  не пересчитывает tombstone**, **байты объекта удалены с диска**
  (path_for_key отсутствует — M18-класс, репо проверяет только флаг) +
  410 purged_artifact + content_bytes=None, sweep пустого run — нули;
  archive на run с ДВУМЯ документами + retention-записью + failed-
  формой: entity-линии document/revision/rendition/approval/lifecycle/
  **retention**/snapshot/pin, оба документа, МОЙ снимок с МОИМ hash в
  objects/, **ответ без путей ФС**, failed-форма в пакете не
  маскируется; **drill ref_errors при ВАЛИДНЫХ checksums** (вычёркивание
  document-линии metadata.jsonl с пересчётом member-sha256 →
  revision:…:document_missing — репо-канал принципиально не достигает
  ref_errors), **drill approval-hash ref_error** (подмена bound-hash с
  валидным checksum → approval:…:hash_mismatch), drill ok, неизвестный
  bundle 404; **diff-направление закреплено** (metadata from=URL/rev 8
  →to=against/rev 7; added=в AGAINST/removed=в URL; validity_changed
  stale→current на своих текстах) + cross-document 422
  diff_across_documents + чужая ревизия 404; **AC05-tripwire**: после
  publish/retract/lifecycle/diff — состав реестра снимков, payload
  bytes и счётчик событий durable-слоя неизменны; мусорное решение
  422 без изменения состояния (a39); ADMIN-запрос несёт честный
  basis=admin_full_catalog в lifecycle-details (a42).
- **Static (12), s01–s12**: миграция 0012 аддитивна (только CREATE
  TABLE/INDEX IF NOT EXISTS, без DROP/DELETE/UPDATE, шапка-комментарий
  не считается); состав 3 таблицы + 4 индекса + FK CASCADE
  (2/3/3 по связям); каталог 12 файлов/74 statement + полный паритет
  файл↔каталог 0012; структурный паритет Memory/Postgres реестра
  (9 методов, без NotImplementedError, урок F-D2C1); каталог ровно 11
  видов D01–D11; AUDIT_ACTIONS=21 c mandatory-классом трёх решений и
  standard-дефолтом retention/archive/drill; словарь 6 lifecycle-
  событий и 4 защищённых состояния; **9 новых маршрутов** в app.routes;
  purged-контракт (RENDITION_PURGED="purged", RenditionPurgedError
  после авторизации — урок порядка fail-closed); bound-hash колонки
  пишутся и читаются обоими бекендами; порядок «резолв → права» во
  всех девяти методах сервиса; фабрики create_default.

## 2. RED на родителе

Корпус на родителе DOCLOG-6 **e573ff3** через git-worktree: **collection
RED за 0.35 s** — `ImportError: cannot import name 'document_lifecycle'
from 'apps.api'` (2 errors during collection; exit 2). Корпус не
вакуумный: он тестирует именно поверхность DOCLOG-6
(protocols/red_parent.json).

## 3. Мутационная кампания («мутанты на своих мутантах»)

Двухканальная схема: **REPO** = test_doclog6 + test_doclog4 +
test_doclog5 + test_doclog2 + test_doclog3 (326 тестов — каталоги-пины
и смежные поверхности); **ORACLE** = корпус сертификатора (79).
**38 боевых мутантов + 3 no-op контроля** над 4 продуктовыми файлами
(document_lifecycle.py, routers/documentation.py, document_jobs.py,
security_audit.py).

**Итог: 27 DUAL-KILLED + 5 REPO-ONLY + 6 ORACLE-ONLY + 0 боевых
SURVIVED; контроли 3/3 ALIVE; PATCH-FAIL 0; RESTORE-FAIL 0**
(mutations_summary.json, протоколы mut_\*.json с tails обоих каналов).
После кампании md5 всех четырёх файлов == HEAD побайтово.

Мета-валидация: **MV1** — каждый мутант применён ровно один раз по
уникальному якорю (dry-run 41/41 якорей: ровно одно вхождение);
**MV2** — классификатор сверен с синтетикой (self-test pass);
**MV3** — байт-в-байт восстановление после каждого мутанта
(md5-сверка, RESTORE-FAIL 0); **MV4** — контроли C1–C3 (docstring/
комментарии) ALIVE — каналы не «косят» всё. **MV5 (гигиена флака)** —
хвосты всех каналов просканированы на посторонние падения: выявлен
один ложный kill (M11: первый прогон упал на несвязанном
TestXlsxRender::test_xlsx_five_sheets_and_determinism — средовой флак,
тест зелёный на чистом дереве); протокол M11 удалён и перепрогнан —
итог ORACLE-ONLY (ожидаемый). Остальные 40 протоколов чисты.

**Классификация боевых мутантов:**

- **DUAL-KILLED (27):** M01/M02 (ветви approved/published вычислимого
  состояния), M03 (гейт request инвертирован), M05 (expected-hash
  инвертирован), M08 (rendition-check publish off), M09 (D11-гейт
  инвертирован), M10 (D11 никогда не блокирует), M12 (superseded-запись
  off), M15 (mandatory audit→standard), M16 (pin-reason generic), M17
  (purge state ready), M21 (cutoff инвертирован), M22 (счётчик отчёта
  off), M23 (drill ok всегда), M26 (member sha256 пустышки), M27
  (self-hash манифеста), M28 (cross-doc diff off), M29 (recalculated
  true), M30 (validity_changed off), M31 (admin basis потерян — убит
  ОРАКУЛОМ a42 через lifecycle-details), M32 (scoped-утечка прав
  суррогата), M33 (unknown policy→two_person), M34 (lifecycle_state
  всегда draft), M35 (410→500), M36 (403→404), M37 (purged reader off),
  M38 (action unregistered).
- **REPO-ONLY (5):** M13 (гейт retract off — репо ловит повторным
  retract), M14 (retract пишет superseded), M19 (hold игнорируется),
  M20 (protected states игнорируются), M24 (digest-check drill off) —
  repo-сюита сильнее оракула на повторных retract, hold/published-защите
  sweep и digest-проверке drill; оракульный корпус заморожен (пины
  живут в repo — честная граница).
- **ORACLE-ONLY (6):** M04 (валидация decision off — репо не шлёт
  мусорных решений; пин a39), M06 (manifest включает не-ready формы —
  пин a10), M07 (snapshot-hash check publish off — репо не tamperит
  снимок; пин a40), M11 (пустые секции публикуются — репо недостижимо
  сборщиком; пин a22), M18 (purge без unlink — байты остаются на
  диске; пин a28 проверяет ФС), M25 (approval-hash ref_error drill off
  — репо не достигает ref_errors; пин a32). **Находка N1: эти 6 пинов
  существуют только в корпусе сертификатора** — рекомендация перенос в
  repo-сюиту (прецедент N1 3-CERT/4-CERT/5-CERT).

## 4. Регресс и сборка

- **Полный tests/ дельта-0 (сплит A/B обеих сторон):** цель
  **70c9c1a+корпус** (продукт = 70c9c1a): A **11F/2665P/42S**, B
  **20F/2064P/24S** vs база **e573ff3** (git-worktree): A **11F/2617P**,
  B **20F/2064P** — **множества FAILED-ID байт-идентичны в обеих
  частях (11/11 и 20/20, diff пуст)**; +48 passed = ровно корпус
  repo-тестов DOCLOG-6. Все 31F — средовые классы (psycopg-DSN
  progress_audit_5b, forecasting-session, modeling/neural, unit-бд
  sqlalchemy/duckdb) — идентичны на обеих сторонах. Примечание: в
  журнале поставки заявлено 30F — в среде сертификатора 31F
  (расхождение учётное, средовой состав; на дельту-0 не влияет).
- **Jest:** полный **2348/2349** (211 сюит) — 1 флак
  `prograudit3_eda_seed_freshness` S4 (jsdom-таймаут waitForPosts —
  ПРЕДСУЩЕСТВУЮЩИЙ средовой класс, задокументирован в поставках
  DOCLOG-4/5/6; в изоляции 5/5 PASS). Сюита поверхности
  `doclog6-lifecycle-ui` PASS.
- **Сборка:** import apps.api.main OK; **201 маршрут** (17
  документационных, из них 9 новых DOCLOG-6); каталог **12 миграций /
  74 statement**; DOCUMENT_KINDS=11 (D01–D11); AUDIT_ACTIONS=21;
  состояния/события/защищённые — по контракту; retention-дефолт 30,
  префикс пакетов d6arch-; **продуктовое дерево чистое** —
  protocols/build_check.json, **BUILD: OK**.

## 5. Находки

- **F-D6C1 (низкая, UI-семантика; зонд protocols/probe_findings.json):**
  направление diff-полей противоположно подписям UI.
  `diff_revisions(текущая, against=предыдущая)` возвращает
  `claims.added` = утверждения, существующие в AGAINST и отсутствующие
  в текущей, и `claims.removed` = наоборот; панель doclog6-diff
  (DocumentationWorkspace.tsx) подписывает added→«Добавлено
  утверждений», removed→«Убрано утверждений». Зонд: v1={A}, v2={A,NEW};
  diff(v2, against=v1) кладёт NEW в removed → UI покажет «Убрано: 1»
  при честном чтении «Добавлено: 1». Данные честны и заморожены
  (recalculated=false, метаданные/validity не зависят от направления,
  ни один claim не теряется); согласование/архив не затронуты.
  Рекомендация: поменять местами семантику added/removed в
  diff_revisions ЛИБО подписи панели; закрепить пин направления в
  repo-сюите (a35 дизъюнктен repo).
- **N1 (покрытие, 6 ORACLE-ONLY):** пины M04/M06/M07/M11/M18/M25 живут
  только в корпусе сертификатора — перенос в repo-сюиту.
- **N2 (гигиена мутационного канала):** единичный средовой флак в
  repo-канале (TestXlsxRender determinism при параллельной нагрузке)
  дал ложный DUAL-KILLED; обнаружен сканом хвостов MV5, устранён
  перепрогоном. Рекомендация: в будущих кампаниях скан хвостов на
  посторонние файлы — обязательный шаг адъюдикации.
- **N3 (полнота прав failed/pending форм в manifest):** approval
  manifest фиксирует ТОЛЬКО ready-формы на момент согласования (a10);
  формы, собранные ПОСЛЕ согласования, не получают статус утверждённых
  автоматически (§11, ожидаемо) — поведение подтверждено, отдельного
  теста на «rendition после approval» в repo нет; кандидат в пин при
  переносе N1.
- **Учётное:** в среде сертификатора полный tests/ даёт 31F (в журнале
  поставки 30F) — средовой состав, дельта-0 не нарушен.

## 6. Вердикт

**СЕРТИФИЦИРОВАНО С НАХОДКОЙ (PASSED WITH FINDINGS).** Поверхность
DOCLOG-6: критерий завершения §19 подтверждён двухканально —
**approval bound hash** (AC07: точная ревизия + payload hash снимка +
manifest ready-форм; перепроверка перед publish; 409 на подмену
рендition-хеша и на перемороженный снимок; непереносимость approval на
новую ревизию — a03/a10/a11/a12/a40/repo), **разделение прав** (§15/D5:
uniform 404 чужому на всех десяти маршрутах, 403 insufficient_scope
владельцу без scope, гранулярность write/approve на key-субъекте,
admin_full_catalog с честным basis, порядок «резолв → права» —
a13–a17/a42/s11/repo), **deletion/hold** (§16.1: hold приоритетен,
published/approved/retracted/superseded не очищаются, tombstone с
удалением байтов и честным 410, hold/release c аудитом — a25–a29/repo),
**restore drill** (AC18: ok/missing/mismatched/ref_errors явными
списками, ref-целостность при валидных checksums, bound-hash
сверка согласований, manifest без self-hash — a30–a34/repo).
D10/D11-адаптеры, mandatory audit fail-closed с восстановлением,
supersede append-only и diff-без-пересчётов подтверждены. 27/38 боевых
мутантов DUAL-KILLED, 0 выживших; 5 REPO-ONLY (сильнее репо-канал),
6 ORACLE-ONLY (сильнее оракул; N1). Вердикт НЕ засчитывает F-D6C1 как
блокер (UI-семантика, не контракт согласования) и выдвигает N1/N2 в
план следующего срезa.

**План DOCLOG-6-UI-FIX (кандидат):** (1) направление added/removed в
diff_revisions либо подписи панели doclog6-diff (F-D6C1); (2) перенос
6 ORACLE-ONLY пинов в repo-сюиту (N1); (3) по решению тимлида — пин
«rendition после approval не утверждена» (N3); пересертификация
затронутого контура не требуется для (2)/(3) (тестовые пины), для (1) —
адресная.

Deliverable: ZIP cisstat-doclog6-cert.zip → открытый контейнер сессии
(download): scripts/doclog6cert/ (conftest, оракулы unit/api/static,
red_parent.py, mutations.py, regress_delta0.py, build_check.py,
probe_findings.py, protocols/ 46 файлов), docs/cert_doclog6_2026-10-23.md
(этот акт), worklog/worklog10.md (запись). Без commit/push (AGENTS.md).
