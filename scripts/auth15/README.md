# AUTH-15 delivery

Task-only overlay на b9af29bf9e359403db16b280fe8c1ab402597e85. План/риски: docs/auth15/design.md; установка/границы: docs/auth15/deploy.md. Состав: scripts/auth15/files.txt; packager проверяет reviewed base, ZIP CRC и каждый byte.

Default contracts: python -m unittest discover -s tests/unit -p 'test_auth15*.py' -v.
Native: scripts/auth15/verify_postgres.py; обязательно disposable CISSTAT_AUTH_TEST_DSN, отсутствие DSN/skip — не PASS. Настоящие PostgreSQL16/18 в CI; Windows contracts отдельно. Supplemental scripts/auth15/wasm_check.py с CISSTAT_AUTH15_WASM принимает каталог @electric-sql/pglite; это не production store и не native locking proof.

Локальная цепочка: unzip → review → git add --pathspec-from-file=scripts/auth15/files.txt → local_gates.py → собственный commit тимлида → local_gates --auth00-target head → push → VM pull/build/migrate. Source INDEX этой сессией не готовится; overlay proof выполняется отдельно. Никаких GitHub commit/push/VM операций.

Включённые protocols отражают реальные выполненные проверки; ранний RED и последующие исправления не подменяются заявлением о полной production-сертификации. AUTH-16 admission codes/cleanup/все дешёвые quotas и AUTH-CERT остаются отдельными задачами. Explicit device leave отзывает свой grant и cookies, но не обещает немедленное удаление научных объектов (cleanup AUTH-16).
