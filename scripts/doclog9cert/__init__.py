# scripts/doclog9cert/__init__.py
"""DOCLOG-9-CERT (2026-10-24): корпус независимой сертификации DOCLOG-9
«Профили организации» (цель аудита -- коммит 06b920c, дерево 5856764).

Методология «оракулы на своих данных, мутанты на своих мутантах»
(прецедент DOCLOG-3/4/5/6/7/8-CERT). Namespace сертификатора дизъюнктен
repo-корпусам (RUN-D9A*, d9-*, d9prof-*) и корпусам предыдущих
сертификаторов (d6cert-*, d7c-*, d8cert-*): **RUN-D9C*, d9cert-*,
ctx-d9cert-*, subj-d9cert*, d9cert-session-***, свой AC-сентинел env
CISSTAT_D9C_SECRET_SENTINEL, свои ключи X-API-Key d9cert-key-*.

Продуктовый код аудитом НЕ меняется (md5 файлов-целей байт-идентичен
git HEAD до/после кампании -- MV3 + build_check).
"""
