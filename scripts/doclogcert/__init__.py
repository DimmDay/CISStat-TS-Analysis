# scripts/doclogcert
"""DOCLOG-CERT (2026-10-24): сквозная приёмка сервиса документирования
и логирования (DOCLOG-0…9). Независимый корпус сертификатора.

Пакет-маркер: pytest собирает оракулы из этого каталога
(test_e2cert_oracle_unit/api/static). Namespace дизъюнктен repo-корпусам
DOCLOG-0..9 и корпусам предыдущих сертификаторов (d6cert-*, d7c-*,
d8cert-*): RUN-E2C*, e2cert-session-*, ctx-e2c-*, fc-e2c-*, subj-e2c-*,
tenant-e2c-2, sentinel CISSTAT_E2C_SECRET_SENTINEL.
"""
