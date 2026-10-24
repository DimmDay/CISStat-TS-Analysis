# DOCLOG-6 — Согласование и архив: контрактный документ

Задача §19, строка DOCLOG-6: «D10/D11, approvals/retract/supersede,
независимая от checkpoints retention, backup/restore». Зависимость 0–5
выполнена (DOCLOG-0…5 + сертификаты). Критерии завершения: «approval
bound hash, разделение прав, deletion/hold и restore drill».

База: main@e573ff3. Поставка по AGENTS.md: TDD RED→GREEN, без commit/push.

## 1. Постановка и граница

Реализуется ось СОДЕРЖАНИЯ жизненного цикла документов (§11): draft →
ready_for_review → approved → published; retracted/superseded/rejected —
терминальные/конечные состояния ревизии БЕЗ перезаписи байтов. Плюс
независимая от checkpoint-keeper'а retention (§16.1) и restore-drill
архивного пакета (§16/AC18). Ревизия остаётся непереписываемой ссылкой
на frozen-снимок (адаптер DOCLOG-4) — согласование НЕ меняет снимок.

ВНЕ границы (честно): полный редактор текста аналитика (AnalystStatement
§9.1 — D10 получает честный not_computed-claim для редактируемой части
+ факты решений из ledger); ZIP-envelope/подпись/WORM (DOCLOG-9);
реальное восстановление Postgres-инфраструктуры (drill проверяет
консистентность metadata+objects пакета, AC18 — «отсутствующие объекты
не маскируются»); D12 мониторинг (DOCLOG-8).

## 2. Ключевые решения

**D1. Каталог видов D10/D11** (`report_snapshot.py`): D10
«Рекомендации и ограничения» (recommendations_limits), D11 «Итоговый
отчёт» (final_report). resolve_kinds принимает D01–D11. Сборщик:
_section_d10 — факты решений из ledger (user-decision события с refs)
+ честное not_computed для редактируемого текста аналитика;
_section_d11 — сводка состояния запуска (выпущенные документы по видам,
data/cutoff/completeness-факты) + честное «публикация требует
согласования». R03: отсутствие источника — честная причина, не пустота.

**D2. Lifecycle-реестр — отдельный контур** (`document_lifecycle.py`):
ApprovalRecord / LifecycleRecord / RetentionRecord + реестр
DocumentLifecycleRegistry (ABC + Memory + Postgres-ленивый psycopg,
миграция 0012, паритет фабрик DOCLOG-4). Append-only: записи не
переписываются/не удаляются; состояние ревизии ВЫЧИСЛЯЕТСЯ из записей.

**D3. Состояния ревизии (§11)**: draft → ready_for_review (запрос
согласования) → approved | rejected; approved → published; published →
retracted (с причиной) | superseded (когда другая ревизия того же
документа публикуется). Переходы валидируются сервисом; незаконный
переход — 422 invalid_transition. rejected — конец для ревизии
(«отклонение возвращает к новой draft revision» — аналитик выпускает
новую ревизию существующим черновиковым контуром DOCLOG-4).

**D4. Approval bound hash (AC07)**: ApprovalRecord хранит ТОЧНЫЙ
revision_id, snapshot_payload_sha256 (registry-метаданные снимка) и
approval_manifest — [{rendition_id, format, content_sha256}] всех ready
renditions ревизии на момент утверждения. Publish перепроверяет: снимок
в реестре с тем же payload_sha256; каждый связанный rendition — с тем же
content_sha256. Расхождение/утрата — 409 approval_not_applicable
(«старое approval не переносится на новый hash», §11). Согласование
другой ревизии — другое согласование (UNIQUE нет; append-only).
Publish пинирует snapshot (ref_kind=snapshot, reason=document:{id}:
published:{version_no}) — deletion-защита независимо от checkpoint
keeper'а (§16/AC04-дух).

**D5. Разделение прав (§15)**: `lifecycle_rights(subject)` —
ADMIN-роль → approve+publish (§15.1 полный каталог); API-ключ с явным
scope documentation.approve/documentation.publish → соответствующее
право (basis=scope); cookie-суррогат в режимах session_scoped/
dev_single_user → право в пределах владения run (basis=session_owner_
pilot — честная пилотная непрерывность с DOCLOG-4, где owner-write был
достаточен для write-действий документного слоя); режим scoped/аноним →
права НЕТ (не фантазируются). Отказ в правах у ВЛАДЕЛЬЦА — 403
insufficient_scope (ресурс свой, существование известно); чужое/нет —
uniform 404 (без изменений). Run-уровень решающей таблицы DOCLOG-0
проходит ПЕРВЫМ на каждом методе (R09).

**D6. Policy согласования**: CISSTAT_DOCLOG_APPROVAL_POLICY =
single (дефолт пилота) | two_person (утверждающий != создатель ревизии
и != запросивший согласование). Незнакомое значение — fail-closed к
single + warning (прецедент identity-mode). Нарушение two_person —
422 self_approval_forbidden (субъект авторизован, операция по policy
запрещена — не утечка, не 403).

**D7. Mandatory audit (§14.1)**: approve/publish/retract —
record_mandatory fail-closed ДО действия (MandatoryAuditFailure →
операция не выполняется); retention hold/release, sweep, archive,
restore-drill — record_standard + действия из реестра: document_approved
/ document_published / document_revoked / retention_policy_changed /
cleanup_started / restore_started / integrity_verified /
integrity_failed / НОВОЕ archive_bundle_created (AUDIT_ACTIONS 20→21,
membership-пины совместимы).

**D8. Retention (§16.1) — независимо от checkpoints**:
RetentionRecord на (run, document): hold bool + reason. Sweep
(POST /runs/{run_id}/retention/sweep; CISSTAT_DOCUMENT_RETENTION_DRAFT_
DAYS=30): документ с published/approved ревизией — не очищается
(«опубликованные — до явного окончания archival policy»); hold —
приоритет, пропуск; draft-документ: ready-renditions старше N дней —
purge: байты из object store удаляются, rendition.state="purged"
(tombstone честен: запись/хэши сохранены, байтов нет), чтение контента
purged — 410 purged_artifact владельцу (§17). Отчёт счётчиками; audit
cleanup_started. Никогда не трогает: published/approved, hold, pinned
зависимости, научный слой.

**D9. Archive/restore drill (§16/AC18)**: POST /runs/{run_id}/archive —
bundle {DATA_DIR}/archive/{run_id}/{bundle_id}/: metadata.jsonl
(documents/revisions/renditions/approvals/lifecycle/retention/snapshots/
pins), objects/{sha256} (байты снимков+renditions), manifest.json
(sha256 каждого члена КРОМЕ самого манифеста — §13.3; без путей ФС
в ответе — bundle_id+manifest_sha256). POST /runs/{run_id}/archive/
verify — drill: манифест/члены/ссылочная целостность (revision→document,
rendition→revision, approval→revision, rendition.content_sha256 ==
объект), missing/mismatched ЯВНО перечислены (не маскируются),
duration_ms drill честно замерен (RPO/RTO не декларируются —
измеряется только drill-время этой поставки; §16.1).

**D10. Diff (§17)**: GET /revisions/{id}/diff?against= — обе ревизии
одного документа и авторизованы; сравнение metadata-полей снимков и
claims (added/removed/validity_changed) ПО ЗАМОРОЖЕННЫМ данным; никаких
пересчётов. Чужая/другого документа — 404/422 честно. Направление
(уточнено DOCLOG-6-CERT-FIX после находки сертификации F-D6C1):
diff(rev, against=prev) читается как изменения ОТ against К rev —
claims.added = утверждения, появившиеся в rev относительно against;
claims.removed = существовавшие в against и отсутствующие в rev;
metadata[...]/validity_changed: from = значение against, to = значение
rev — естественному чтению подписей панели doclog6-diff
(«Добавлено утверждений» / «Убрано утверждений»). Пин направления:
repo test_diff_direction_natural_semantics + оракул a35.

## 3. Карта изменений

Новые: `apps/api/document_lifecycle.py`; `apps/api/migrations/
0012_doclog6_approvals_archive.sql` (document_approvals/
document_lifecycle/document_retention, аддитивная); `docs/
doclog6_approvals_archive.md`; `tests/api/test_doclog6_approvals_archive.py`;
`packages/ui/doclog6-lifecycle-ui.test.tsx`.

Обновлённые: `report_snapshot.py` (+D10/D11), `snapshot_builder.py`
(+2 адаптера), `research_runs.py` (+0012, каталог 12/74), `routers/
documentation.py` (+9 маршрутов §17, lifecycle_state в revision-JSON,
410 purged), `security_audit.py` (+1 действие), `document_jobs.py`
(+RenditionPurgedError, honest 410), `packages/ui/lib/documentation.ts`
(+типы/клиенты), `packages/ui/components/DocumentationWorkspace.tsx`
(+панель жизненного цикла/действия/diff, D10/D11 в списке),
`tests/api/test_doclog3_telemetry_audit.py` (+честный пин каталога
миграций 11/67→12/74), `packages/ui/components/DocumentationWorkspace.
test.tsx` (пин 9→11 видов честно).

## 4. Критерии приёмки

AC07 (approve не переносится; publish без права/approval/зависимости —
отказ; подпись шаблона не даёт approval) — оракулами; AC04-дух (пин
publish переживает prune); AC05 (чтение lifecycle/diff не меняет науку);
AC06 (чужой — uniform 404 на всех новых маршрутах); AC11 (approve/
publish/retract fail-closed при отказе аудита); AC17 (UI: состояния/
403/409/422 текстом, role=status/alert); AC18 (drill: missing не
маскируются). Migration parity file↔каталог страхуется тестами.
