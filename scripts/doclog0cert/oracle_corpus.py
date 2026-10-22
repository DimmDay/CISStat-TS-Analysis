# scripts/doclog0cert/oracle_corpus.py
"""DOCLOG-0-CERT: собственный корпус сертификатора.

Дизъюнктен repo-корпусу (tests/api/test_doclog0_identity.py: run_id
RUN-D0xxxxxx, admin key "d0-admin-test-key", сессии "d0-sess-N") и всем
корпусам прошлых сертификаций: свои run_id RUN-DCAC0Axx, свои
cookie-сессии dca-cert-*, свой админ-ключ, свои явные субъекты и
tenants. Единый источник констант -- не копии строк по файлам.
"""
from __future__ import annotations

# run_id -- канон ^RUN-[0-9A-Z]{8}$, префикс DCAC0 нигде более не встречается.
RUN_OWNER = "RUN-DCAC0A01"
RUN_FOREIGN = "RUN-DCAC0A02"
RUN_TENANT = "RUN-DCAC0A03"
RUN_LEGACY = "RUN-DCAC0A04"
RUN_RESTORE = "RUN-DCAC0A05"
RUN_GUARD = "RUN-DCAC0A06"
RUN_NOPE = "RUN-DCAC0ZZZ"  # несуществующий (валидный по форме)

# Субъекты (суррогатные и явные).
SUBJ_OWNER = "subj-" + "c0de" * 4          # subj-c0dec0dec0dec0de
SUBJ_STRANGER = "subj-" + "dead" * 4       # subj-deaddeaddeaddead
SUBJ_THIRD = "subj-" + "beef" * 4
EXPLICIT_SUBJECT = "dca-portal-subject-42"  # явный ID реестра (не subj-*)
MATERIAL_COOKIE_A = "dca-cert-cookie-owner-a7f3"
MATERIAL_COOKIE_B = "dca-cert-cookie-stranger-b2e9"
MATERIAL_SECRET = "dca-cert-secret-material-8k2m-DoNotLeak-41"

# Tenants.
TENANT_DEFAULT = "tenant-default"
TENANT_ALPHA = "tenant-dca-alpha"
TENANT_BETA = "tenant-dca-beta"

# Реестр ключей (свой админ-ключ; роли/планы -- значения Role/PlanName).
ADMIN_KEY = "dca-cert-admin-key-7f3"
ANALYST_KEY = "dca-cert-analyst-key-5k1"
REGISTRY_EXTENDED = (
    f"{ADMIN_KEY}:admin::dca-portal-admin-7:{TENANT_ALPHA}:policy.admin+audit.read"
)
REGISTRY_LEGACY = f"{ANALYST_KEY}:internal_analyst:"

# Псевдонимы-фикстуры.
SESSION_CREATOR = "dca-cert-session-creator"
SESSION_INHERITED = "dca-cert-session-inherited"

# Salt-пары для ротации (свои, не dev-константы).
SALT_A = "dca-cert-salt-one"
SALT_B = "dca-cert-salt-two"

# Ожидаемый состав каталога Scope (§15 -- ровно 11 прав).
EXPECTED_SCOPE_VALUES = frozenset(
    {
        "documentation.read",
        "documentation.write",
        "documentation.export",
        "documentation.approve",
        "documentation.publish",
        "artifact.data.read",
        "logs.read",
        "logs.export",
        "audit.read",
        "support.grant",
        "policy.admin",
    }
)
