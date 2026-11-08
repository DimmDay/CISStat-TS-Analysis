# AUTH-11 — закрытие пакета

**Статус: CLOSED. Дата: 08.11.2026, Москва.** База: bf5763051285f1f1e74d14e2ce3680a47493c0ca. Закрыт объём реализации, локальной проверки и подготовки поставки AUTH-11. Установка на VM идёт по согласованной цепочке тимлида после локального commit/push.

| Часть пакета | Итог | Доказательство |
|---|---|---|
| Проектирование и риски | Завершены | docs/auth11/design.md |
| Научный guard | 173 bindings /154 операции; Account/object/entitlement/actual workload | apps/api/scientific.py, scientific_workload.py |
| TDD | RED → GREEN, 9/9 minimal unit, 4/4 UI | scripts/auth11/protocols/red-*.txt, minimal-unit.txt, ui.txt |
| Реальный PostgreSQL16.2 | AUTH-11 23/23, общий AUTH-02…11 193/193, без skips | native-final.txt, native-regression.txt |
| Локальные гейты распакованного ZIP | Все14 PASS, AUTH-0049/49 и INDEX parity | delivery-overlay.txt, delivery-final.txt |
| UI и сборки | Jest2837 PASS, обе Next production builds, renderer и TypeScript PASS | jest.txt, builds.txt, renderer.txt, typecheck.txt |
| HTTP контракты | 239 methods/paths сохранены;243 registry bindings; полный inventory574 | routes.txt, routes-delta.json, docs/auth00/inventory.md |
| Scientific API регресс | 3451 PASS /43 skipped /11 прежних failures; новых нет | api-delta.json и оба full API протокола |
| Передача и эксплуатация | Полный ZIP, manifest, worklog; api+web rebuild, без SQL migrations | scripts/auth11/files.txt, docs/auth11/deploy.md |

Все названные txt/json протоколы находятся в scripts/auth11/protocols/. Проверки при закрытии документации — closure-checks.txt. ZIP проверяется по CRC, точному manifest и каждому payload byte, включая распаковку поверх базы. Runtime/API/UI/SQL при закрытии не менялись относительно поставленного AUTH-11.

Открытых пунктов внутри согласованного объёма AUTH-11 нет. Atomic quotas — AUTH-12, worker guard/fencing/settle — AUTH-13, anonymous Demo — AUTH-15, сквозная production сертификация — AUTH-CERT. Прежние11 scientific failures не исправлялись и не считаются PASS. Windows/PG18 jobs добавлены в CI; локально они не запускались. Authority fixture не является полной проверкой artifact promotion durability. Эти границы сохранены в design/worklog.

Поставка: cisstat-auth11-bf57630-final.zip, полный пакет поверх bf57630. Он заменяет прежний архив AUTH-11; применить один итоговый ZIP. Обязательно явно git add по scripts/auth11/files.txt до INDEX gate. Commit/push и VM deployment выполняет тимлид; текущая сессия их не выполняла. Для VM нужны оба образа api/web; новых миграций и обязательных env нет. Команды и smoke checks: deploy.md.
