# PGV13/14 CASEFIX — точный каталог Jest после PGV-PNG-SSR

База5ce19a0d59b15a00716bf1aa2b0e8faea22de58c,27.11.2026 Москва.
AGENTS/структура/CI/runner/сертификационный валидатор изучены.
Приложенный auth00(8).log: INDEX/source parity PASS,61 tests PASS,669 entries.
Git push состоялся; падает проверка evidence, а не Git transport.

Воспроизведение на точной базе: выбранные20 Jest suites —367/367 PASS;
фиксированный каталог содержит357 случаев. Missing0, unexpected10, все из
apps/print-renderer/src/backendPayload.test.tsx предыдущей SSR-поставки.
Термин coverage в ошибке относится к составу тестов, не проценту Istanbul.
Упущение прошлой поставки: новый default/CI SSR gate добавлен, а отдельный
каталог полной PGV13/14 процедуры не обновлён.

Проект до кода:
1. Добавить только10 фактически исполненных и просмотренных SSR случаев в
   jest-cases.json; старые357 сохранить. Не исключать suite/не принимать
   произвольное superset/не заменять точное равенство нижней границей.
2. Сохранять строгие успех/числа/статусы/path confinement/Counter точных
   file+fullName. Ошибка показывает expected/total/passed/observed и количество
   missing/unexpected с bounded sample, чтобы новые случаи были видны.
3. При evidence_validation failure создавать настоящий диагностический лог
   и включать его digest в FAIL report. Все task certification flags false;
   hash/source fences, native/OCR/review/pins не ослаблять.
4. TDD: реальный367-case JSON отвергается старым каталогом; новые unit controls
   на диагностику/multiplicity/реальный failure log RED→GREEN. Каталог pytest
   дополнить только новыми контрольными тестами этой задачи, сохранив165 старых.
5. Проверить полную pgv1314cert процедуру на Node22, Ubuntu-style workflow,
   её pytest/Jest/typography/CP1252/routes/inventory/typecheck/обе web builds.
   AUTH00 separate INDEX/actual routes и task-only ZIP поверх точной базы.

Риски: каталог нельзя обновлять вслепую из отчёта с потерянными старыми cases;
перенос Windows/Linux не должен менять portable paths/fullName. FAILED report
не становится certificate, а новый log не переписывает исходные evidence.
Runtime/HTTP/worker/квоты/VM images не меняются. Новая VM-сборка этой host-only
поставке не нужна; сами ранее поставленные SSR образы всё ещё развёртываются
по отдельной инструкции. Никаких commit/push/VM secret reads агентом.


Проверки:32 certification/CI controls, новый pytest catalog168 (старые165+3
контроля), Jest catalog367 (старые357+10 SSR), без удалённых старых cases.
Реальный367-case JSON даёт RED со старым каталогом и GREEN с новым.
Полная процедура наNode22.23.5 проходит все10 этапов, включая renderer tsc,
pytest/Jest, typography18, CP1252 parity, routes/inventory, typecheck и обе
Next production builds. Это local evidence PASS, а не native/VM certificate;
PGV-13/14 task flags остаются false. Итоговые протоколы — casefix/protocols.

После добавления/переименования scoped tests просмотреть delta из сообщения,
обновить соответствующий фиксированный каталог и запустить полный гейт.
Не обновлять expected по отчёту, если пропал хоть один прежний случай без
явного review. Для этой host-only правки images/DB/worker не меняются.
После ZIP поверх5ce19a0: npm ci (если сменился checkout), Python deps из
apps/api/requirements.txt и scripts/pgv1314cert/requirements.txt, Node22;
явно подготовить файлы по casefix/files.txt, затем:
`python scripts/local_gates.py --only pgv1314cert,auth00 --skip-install`.
Перед push после commit — `--auth00-target head`. Commit/push выполняет тимлид.
