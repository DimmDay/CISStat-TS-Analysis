# Статус исторического evidence PGV-08

PNG pg v08-sample-* (файлы pgv08-sample-cyrillic.png, pgv08-sample-ih.png,
pgv08-sample-a4.png), smoke_run.json и local_verification.json относятся к
первоначальной поставке. Это НЕ новая приёмка исправлений PGV-08-FIX.
В частности, прежний IH sample был создан с несогласованным n_observations.
Fixtures исправлены; PNG не регенерирован, потому что Chromium download недоступен.
Не использовать эти файлы для заявления о готовности исправленного final image.

server_main.log и server_dependency.log — новые реальные журналы повторных HTTP
проб: slow shell launch через Playwright и missing_browser соответственно.
Они не заменяют и не имитируют утраченные старые PNG browser E2E логи.
Новый evidence: scripts/pgv08fix/protocols, акт docs/cert_pgv08_fix_2026-10-29.md.
