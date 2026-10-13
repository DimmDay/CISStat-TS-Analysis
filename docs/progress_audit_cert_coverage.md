# AUDIT-CERT — матрица доказательств P/H/F

Дата: 2026-10-13. База: `2a4cd6cf3cca02e09c9746a5bc7d3ca7b9a1d1b3`.
Матрица относится к **локальной приёмке**, не к Render/Vercel.
Исходный протокол `progress_audit_readonly_results.json` не изменён.

Обозначения оракулов:

- **I** — новые проверки `tests/integration/test_progress_audit_cert.py`;
  названия функций приведены ниже без префикса `test_`.
- **S** — новые contract tests `tests/api/test_progress_audit_cert_store.py`.
- **U** — новые React tests `packages/ui/hooks/prograuditcert_delivery.test.tsx`.
- **A-<ID>** — существующая suite `tests/api/test_progress_audit_<ID>.py`.
  Здесь ID записан в нижнем регистре, например `A-6a`.
- **UI-3** — `packages/ui/components/prograudit3cert_eda_seed_freshness.test.tsx`.
- **UI-2B** — `packages/ui/hooks/prograudit2bcert_useProgressMapDelivery.test.tsx`.

Ожидания I/S/U — явные значения статуса/числа/происхождения, идентификаторы
принятых событий и исходный receipt; отдельная копия reducer отсутствует.
I использует полный `apps.api.main`, реальные роутеры, middleware и
файловые артефакты в своём временном каталоге. S параметризована Memory/PG;
PG-клетки текущего прогона **SKIPPED**, а не PASSED. UI работает в jsdom с
контролируемыми HTTP-ответами; это не наблюдение живого браузера.

## P01–P25 и исходные H01–H25

Pxx и Hxx исходного аудита здесь имеют одну и ту же проверочную основу.
«Исправлено» означает отрицание найденного локального контрпримера,
а не универсальную гарантию для всего приложения.

| ID | Проверяемое свойство / оракул | Результат и граница |
|---|---|---|
| P01/H01 | I `singleton_identity_ambiguity_manual`, `demo_uses_same_singleton_rule`; A-1a, PROGR-25a/d | Сохранён: один shared choice id, auto/system; demo проверено на своём singleton CSV. |
| P02/H02 | I `singleton_identity_ambiguity_manual` | Сохранён: неоднозначность без выбора; manual имеет source=user. |
| P03/H03 | I `auto_convert_reset_restore_manual_consumers`; A-1a, A-h1 | Исправлен reset session/run/restore/reason; MC1 обнаружен. |
| P04/H04 | I `unmodified_auto_restore_preserves_source_without_new_choice`; A-1a | Auto восстанавливается без второго выбора. После clear цель не воскресает. |
| P05/H05 | I `auto_convert_reset_restore_manual_consumers`; A-8 | Raw явно обозначен; прежний data_types done — stale, не проверка новых данных. Replay промежуточного DataFrame не реализован по контракту. |
| P06/H06 | I `four_maps_form_stale_run_context_duplicate_and_conflict` ×4; A-2a | 422 формы до записи; v2 — **client_observation**, не независимое удостоверение статистического расчёта. Доверенный характер карты сохранён. |
| P07/H07 | I `four_maps_form_stale_run_context_duplicate_and_conflict` ×4; S `concurrent_duplicate_lost_receipt_one_batch_effect`; U H26 | V2 идемпотентен: прежний receipt, ноль новых событий, конфликт тела 409. Legacy остаётся отдельной ограниченной веткой. MC3 обнаружен. |
| P08/H08 | I `cache_failure_lost_receipt_retry_recovery_one_effect`; A-6b | Committed факты + pending outbox при cache failure; повтор возвращает receipt, worker доставляет один эффект. Не обещается общая транзакция Redis+PG. |
| P09/H09 | A-6c hook failure/log tests; A-6b producer registry | Advisory хук может потерять факт при 200; это **сохранённая явная граница**, а не исправленный required-путь. |
| P10/H10 | A-6a `test_target_metadata_atomic_with_event_on_mirror_failure`; S `outbox_failure_rolls_back_all_four_surfaces` | Memory rollback run/events/checkpoint/receipt/outbox проверен; выявленный дополнительный дефект исправлен. Свежая PG-половина открыта. |
| P11/H11 | I `full_projection_reverse_equal_clocks_forecast_identity`; A-5b | При >1000 фактов ранние статусы, start и полная позиция сохраняются; cap ограничивает список. MC5 обнаружен. |
| P12/H12 | I `full_projection_reverse_equal_clocks_forecast_identity`; A-5b, A-s `TestCanonicalOrder` | Последний committed факт побеждает обратные/equal clocks; все consumers читают канонический ledger. |
| P13/H13 | I `model_job_cancel_context_late_result_and_phase`; A-7a | Start=in_progress, cancel=pending; старый job stale/404, не done. Все семь типов имеют явную семантику; узлы без producer не фабрикуются. |
| P14/H14 | I `outcome_and_invalid_event_details` ×3; A-4 | Clean preview не утверждает warning/done; no-op/partial с остатком — warning и число после операции. Это проверка интерпретации результата, не аудит математики всех коррекций. |
| P15/H15 | I `outcome_and_invalid_event_details`; A-4 | Невалидное событие не меняет status/reason/count/source. |
| P16/H16 | I `full_projection_reverse_equal_clocks_forecast_identity`; A-4 | Done без count не наследует прежние 6; source принадлежит новому решению. |
| P17/H17 | I `forecast_merge_preserves_id_actor_and_independent_equal_actions`; A-s | Два независимых равных действия сохранены, зеркальные копии по id слиты; actor/run/id не теряются. MC4 обнаружен. |
| P18/H18 | I `reports_mentor_panel_one_watermark_provenance_and_validity`; A-7b | MD/HTML различают auto и историческую применимость, содержат watermark и event ids. |
| P19/H19 | A-7a `test_p19_method_change_same_count_is_new_fact_control`; A-4 method/refetch tests | IQR→zscore при равном count даёт новый факт, повтор того же результата — нет. |
| P20/H20 | S `concurrent_duplicate_lost_receipt_one_batch_effect`; A-6a dedup/sequence tests | Memory проверен конкурентно; новые PG contract tests подготовлены, но live parity этого запуска не подтверждён. |
| P21/H21 | A-6c required/advisory factory tests | Fail-closed при configuration/driver/probe failure локально; full-environment reload test имеет baseline failure из-за недоступных дополнительных моделей. Производственный backend не установлен. |
| P22/H22 | I cache/receipt/read-after-watermark; A-6b required/advisory registry | Required receipt читается по позиции; advisory after-response hook остаётся асинхронным. Живая гонка — H30, открыта. |
| P23/H23 | A-s `TestHonestTime`; A-6a envelope roundtrip | Raw invalid ts и качество времени не маскируются в Memory. Реальное PostgreSQL TIMESTAMPTZ roundtrip этого запуска открыто. |
| P24/H24 | I `four_maps_form_stale_run_context_duplicate_and_conflict` ×4; A-c, A-2a; U stale refresh | Strict v2: старый run/target-context отклонён до записи. MC2 обнаружен. Legacy compatibility не закрывает P24 для всех клиентов; data revision/scopes проверены A-c. |
| P25/H25 | I `eda_get_remount_pending_seed_failure_and_new_context`; A-3, UI-3 | GET/refetch не понижает показанный done; pending прежнего контекста не стирает просмотр. Новый target имеет новую применимость. MC7 обнаружен. |

## H26–H30

| ID | Оракулы / минимальная проверка | Итог |
|---|---|---|
| H26 | U lost-response и receipt tests; UI-2B; I cache failure+retry | Локальный strict v2 контрпример устранён: retry тем же ключом/телом, delivered только после receipt (MC6). Очередь браузера не переживает перезагрузку; legacy fallback не имеет этой гарантии. |
| H27 | UI-3 C2/C3; A-3; I EDA pending-seed scenario | Локально проверены удержание при seed failure/incomplete projection и сохранение прошлого done. |
| H28 | UI-3 C4/C7; A-c/A-3; I смена flow→stock | Локально проверены новый контекст и stale старого просмотра при неизменном datasetId; неизвестный legacy context не выдумывается. |
| H29 | Read-only deployment boot/backend logs + известный run/file до/после **уже состоявшегося** restart | **НЕ ПРОВЕРЕНО**: доступ не предоставлен. Нужны safe configured/effective backend, migration version, boot ids, наличие известного корпуса/файла; без DSN и сырых данных. |
| H30 | Уже имеющиеся response/read/commit логи одного correlation id и наблюдение UI | **НЕ ПРОВЕРЕНО**: production/browser access отсутствует. Локальный required receipt не доказывает отсутствие advisory гонок в эксплуатации. |

## F01–F17 → покрытие

| Факт | Связанные строки выше | Состояние |
|---|---|---|
| F01 | P01, P02 | Положительные каноны сохранены. |
| F02 | P03 | Локальный reset согласован; мутационный контрпример обнаружен. |
| F03 | P04, P05 | Происхождение и raw/historical semantics проверены. |
| F04 | P06, P24, H26 | Strict v2 исправлен; доверенность UI и compatibility границы остаются. |
| F05 | P08, P09, P10, P22 | Required-контракты в Memory проверены и усилены; fresh real-store gate открыт; advisory loss не скрыт. |
| F06 | P11 | Full projection вместо cap-tail проверена. |
| F07 | P07, P20 | Memory concurrent dedup проверен; fresh PG parity открыт. |
| F08 | P12 | Канонический порядок проверен. |
| F09 | P13 | Матрица Modeling и lifecycle проверены, сознательные exclusions сохранены. |
| F10 | P14–P16 | Outcome и freshness деталей проверены. |
| F11 | P17 | Identity/merge проверены. |
| F12 | P18 | MD/HTML origin/history/version проверены. |
| F13 | P19 | Метод различается с тем же count. |
| F14 | P21, H29 | Локальные fail-closed проверки есть; deployment неизвестен. |
| F15 | P22, H30 | Required/advisory явно разделены; живая гонка не проверена. |
| F16 | P23 | Memory time-quality проверена; fresh PG gate открыт. |
| F17 | P25, H27, H28 | Локальные EDA/UI контракты проверены. |

Полные имена baseline failures и их дельта хранятся в
`scripts/prograuditcert_protocol.json`; полные stdout — в
`scripts/prograuditcert_protocols/`. Наличие строки в матрице не превращает
SKIP, advisory-границу или непроверенный production в успешную сертификацию.
