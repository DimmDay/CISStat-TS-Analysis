# AUTH-16

Task-only overlay поверх2f4812032240b35f1524d0bb31c58fcaf4bc3c85. Design/deploy/verification: docs/auth16. Exact file list: files.txt. Ничего не commit/push автоматически.

```bash
python -m unittest discover -s tests/unit -p 'test_auth16*.py' -v
# disposable database ONLY; no DSN/skip is never PASS:
python scripts/auth16/verify_postgres.py
python scripts/auth16/migrate.py --check
```

`--apply` — явный additive0028 deployment; production tests не запускать. `cleanup.py --sweep` — bounded SQL housekeeping; `--abandon-calls --quiesced` и `--collect-files --quiesced` — только при остановленных всех publishers. Physical GC intent audit фиксируется до unlink, referenced/held/unknown data сохраняются. Sweep автоматически работает в API required profile, finite batch25/5s, отключается CISSTAT_DEMO_SWEEPER_ENABLED=0; это не выключает expiry/quotas guards.

packager собирает только изменённые tracked и task-owned новые файлы, проверяет CRC/каждый byte и пишет ZIP/manifest/worklog/VM doc/SHA256 в download/. Посторонние untracked файлы не входят. Требует reviewed base HEAD и отсутствие deleted files.
