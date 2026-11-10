# AUTH-17

Base201a3b1f12eac55525fb07301b5e37f8e962d938. Design/deploy/verification: docs/auth17. No commit/push/VM actions. Apply task ZIP to that base, stage only scripts/auth17/files.txt.

- `migrate.py --apply/--check`: explicit additive0029; never request-time DDL.
- `verify_postgres.py`: disposable CISSTAT_AUTH_TEST_DSN required; zero tests/skips/no DSN is failure.
- `manage_seats.py`: trusted interactive operator confirmation of an existing OWNER request after external entitlement verification. Not a payment verifier. No CU credit/reset. Not exposed by HTTP. Read current version using auth08/manage_account.py show.
- unit: `python -m unittest discover -s tests/unit -p 'test_auth17*.py' -v`.
- Native CI PostgreSQL16/18, unit Linux/Windows; complete provider/payment saga AUTH-18.

Tokens are shown once, hash-only in SQL; no GET token consumption or email dispatch. Personal sign-in to an active Account is required; new identity provisioning/email verification flows are AUTH-19. Email invitations require a unique verified contact; UUID invitations work for existing personal identities. Account switch invalidates old SID/research pointer and reloads UI without extending login lifetime.
