# scripts/doclog9cert/test_d9cert_oracle_static.py
"""DOCLOG-9-CERT: статические оракулы (s01–s14) -- контракты без HTTP.

Миграция 0015 (файл↔каталог, DDL), карта маршрутов, аудит-каталоги
(§8/§14.1), frozen-каталоги форматов/валидаторов, PG-паритет и
append-only, чистота рендеров, UI-контракт (use client, ключи/URL,
текстовый статус валидации).
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text("utf-8")


# ══════════════════════════════════════════════════════════════════════
# Миграция 0015
# ══════════════════════════════════════════════════════════════════════


def test_s01_migration_catalog_and_statement_counts():
    from apps.api import research_runs as rr

    assert rr.MIGRATION_FILES[-1][0].startswith("0015")
    assert len(rr.MIGRATION_STATEMENTS) == 93  # 85 (DOCLOG-8) + 8
    assert len(rr.MIGRATION_STATEMENTS_0015) == 8  # 2 ALTER + 3 таблицы + 3 индекса
    joined = "\n".join(rr.MIGRATION_STATEMENTS_0015)
    assert joined.count("CREATE TABLE") == 3
    assert joined.count("CREATE INDEX") == 3
    assert joined.count("ADD COLUMN IF NOT EXISTS org_profile_id") == 2
    # Файл-дубль согласован с каталогом по ключевым DDL-маркерам.
    sql_file = _read("apps/api/migrations/0015_doclog9_profiles.sql")
    for marker in (
        "CREATE TABLE IF NOT EXISTS doc_profiles",
        "CREATE TABLE IF NOT EXISTS doc_rendition_validations",
        "CREATE TABLE IF NOT EXISTS doc_anchor_records",
        "UNIQUE (name, version_no)",
        "ADD COLUMN IF NOT EXISTS org_profile_id TEXT NOT NULL DEFAULT ''",
    ):
        assert marker in sql_file, marker


def test_s02_ddl_org_entity_no_run_fk_jsonb_and_defaults():
    from apps.api import research_runs as rr

    joined = "\n".join(rr.MIGRATION_STATEMENTS_0015)
    # org-сущность tenant-уровня: БЕЗ FK на research_runs (паритет 0013).
    assert "REFERENCES research_runs" not in joined
    assert "doc_profiles" in joined
    # JSONB-поля доказательств.
    assert "findings JSONB" in joined
    assert "signature_manifest JSONB" in joined
    # Файл: те же свойства.
    sql_file = _read("apps/api/migrations/0015_doclog9_profiles.sql")
    assert "REFERENCES research_runs" not in sql_file
    assert sql_file.count("TIMESTAMPTZ") >= 4
    # Индексы поимённо (оба источника).
    for index in (
        "idx_doc_profiles_format",
        "idx_doc_validations_rendition",
        "idx_doc_anchors_rendition",
    ):
        assert index in joined, index
        assert index in sql_file, index


# ══════════════════════════════════════════════════════════════════════
# Маршруты и аудит-каталоги
# ══════════════════════════════════════════════════════════════════════


def test_s03_routes_catalog_exact():
    from apps.api import main as main_mod

    doc_routes = {}
    for route in main_mod.app.routes:
        path = getattr(route, "path", "")
        if "org-profiles" in path or "validations" in path or "verify-signature" in path:
            methods = frozenset(getattr(route, "methods", set())) - {"HEAD", "OPTIONS"}
            doc_routes.setdefault(path, set()).update(methods)
    expected = {
        "/v1/documentation/org-profiles": {"GET", "POST"},
        "/v1/documentation/org-profiles/{profile_id}/retire": {"POST"},
        "/v1/documentation/renditions/{rendition_id}/validations": {"GET"},
        "/v1/documentation/renditions/{rendition_id}/verify-signature": {"POST"},
    }
    assert doc_routes == expected


def test_s04_audit_actions_28_and_classes():
    from apps.api import security_audit as sa

    assert len(sa.AUDIT_ACTIONS) == 28
    for action in ("org_profile_created", "org_profile_retired",
                   "rendition_validated", "rendition_anchored"):
        assert action in sa.AUDIT_ACTIONS
    assert sa.AUDIT_REQUIREMENTS["org_profile_created"] == "mandatory"
    assert sa.AUDIT_REQUIREMENTS["org_profile_retired"] == "mandatory"
    assert sa.AUDIT_REQUIREMENTS["rendition_validated"] == "standard"
    assert sa.AUDIT_REQUIREMENTS["rendition_anchored"] == "standard"


def test_s05_service_audit_calls_match_classes():
    """В сервисе создание/retire -- record_mandatory; валидация/якорь --
    record_standard (§14.1); подмена источников исключает расхождение."""
    source = _read("apps/api/doc_profiles.py")
    mandatory_calls = source.count('requirement="mandatory"')
    standard_calls = source.count('requirement="standard"')
    # org_profile_created + org_profile_retired = 2 места с дефолтом mandatory
    # (в _audit дефолт mandatory; валидация/якорь передают standard явно)
    assert source.count('self._audit(\n            "org_profile_created"') == 1
    assert source.count('self._audit(\n            "org_profile_retired"') == 1
    assert standard_calls == 2  # record_validation + record_anchor
    assert "record_mandatory if requirement == \"mandatory\" else record_standard" in source


def test_s06_format_and_signature_catalogs_frozen():
    from apps.api import doc_profiles as dp

    assert isinstance(dp.PROFILE_FORMATS, frozenset)
    assert isinstance(dp.KNOWN_VALIDATORS, frozenset)
    assert dp.PROFILE_SCHEMA_VERSION == "doclog.org_profile/1"
    assert dp.SIGN_KEY_ENV == "CISSTAT_DOC_SIGN_KEY"
    assert dp.SIGNATURE_ALGORITHM == "HMAC-SHA256"
    assert dp.WORM_REASON_PREFIX == "org_profile_worm"
    # Подпись честно помечена не-юридической.
    assert "not_a_legal_signature" in inspect.getsource(dp.sign_content)


# ══════════════════════════════════════════════════════════════════════
# Каталог форматов rendition: docx/pdfa
# ══════════════════════════════════════════════════════════════════════


def test_s07_rendition_formats_docx_pdfa_heavy():
    from apps.api.document_renditions import (
        HEAVY_RENDITION_FORMATS,
        RENDITION_FORMATS,
    )

    assert "docx" in RENDITION_FORMATS and "pdfa" in RENDITION_FORMATS
    docx = RENDITION_FORMATS["docx"]
    pdfa = RENDITION_FORMATS["pdfa"]
    assert docx.media_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx.extension == "docx"
    assert pdfa.media_type == "application/pdf"
    assert pdfa.extension == "pdfa"
    assert {"docx", "pdfa"} <= set(HEAVY_RENDITION_FORMATS)


def test_s08_document_kinds_unchanged():
    """DOCLOG-9 не добавляет вид документа (профиль -- свойство
    выпуска, не новый D-kind)."""
    from apps.api.report_snapshot import DOCUMENT_KINDS

    assert len(DOCUMENT_KINDS) == 12
    assert "D12" in DOCUMENT_KINDS


def test_s09_render_purity_fixed_dates_no_wallclock_in_docx():
    """docx-рендер: фиксированные даты ZIP-членов, никакой времени
    стенки в теле функций DOCLOG-9 (пин AC03; про pdfa -- акт, F-D9C1:
    недетерминизм через ICC-заголовок зафиксирован отдельным u18/u19)."""
    source = _read("apps/api/document_renditions.py")
    assert "_DOCX_FIXED_DATE_TIME = (2026, 1, 1, 0, 0, 0)" in source
    docx_fn = source[source.index("def render_snapshot_docx"):]
    docx_fn = docx_fn[: docx_fn.index("\ndef ", 1)]
    assert "datetime.now" not in docx_fn
    assert "time.time" not in docx_fn
    assert "_docx_escape" in docx_fn


def test_s10_pg_registry_parity_and_append_only():
    """PG-реестр: все 10 методов ABC реализованы; INSERT-only для
    якорей/валидаций; UPDATE doc_profiles -- только статусные поля;
    SQL параметризован (без f-строк)."""
    source = _read("apps/api/doc_profiles.py")
    pg = source[source.index("class PostgresOrgProfileRegistry"):]
    pg = pg[: pg.index("\nclass ", 1)] if "\nclass " in pg else pg
    for method in (
        "create_profile", "get_profile", "find_duplicate", "list_profiles",
        "update_status", "append_validation", "list_validations",
        "list_validations_by_job", "append_anchor", "list_anchors",
        "readiness_probe",
    ):
        assert f"def {method}" in pg, method
        assert "NotImplementedError" not in pg.split(f"def {method}")[1].split("def ")[0]
    # Append-only: якоря/валидации -- только INSERT/SELECT.
    anchors_sql = pg[pg.index("def append_anchor"):]
    anchors_sql = anchors_sql[: anchors_sql.index("def readiness_probe")]
    assert "INSERT INTO doc_anchor_records" in anchors_sql
    assert "UPDATE doc_anchor_records" not in anchors_sql
    assert "DELETE FROM doc_anchor_records" not in anchors_sql
    validations_sql = pg[pg.index("def append_validation"):]
    validations_sql = validations_sql[: validations_sql.index("def append_anchor")]
    assert "INSERT INTO doc_rendition_validations" in validations_sql
    assert "UPDATE doc_rendition_validations" not in pg
    # UPDATE doc_profiles -- только статусные поля (retire).
    update = pg[pg.index("def update_status"):]
    update = update[: update.index("def append_validation")]
    assert "UPDATE doc_profiles SET status" in update
    assert "SET name" not in update and "SET footer_text" not in update
    # Параметризация: нет f-интерполяции SQL.
    for line in pg.splitlines():
        stripped = line.strip()
        if stripped.startswith(('query = f"', 'query += f"', 'conn.execute(f"')):
            raise AssertionError(f"f-string SQL: {stripped}")


def test_s11_registry_from_env_backends():
    """Выбор бекенда: CISSTAT_DOC_PROFILES_BACKEND=postgres ИЛИ DATABASE_URL
    -> Postgres; иначе Memory (advisory-режим, паритет durable-контуров)."""
    source = _read("apps/api/doc_profiles.py")
    assert 'os.environ.get("CISSTAT_DOC_PROFILES_BACKEND"' in source
    assert 'os.environ.get("DATABASE_URL")' in source
    assert "class MemoryOrgProfileRegistry" in source
    assert "class PostgresOrgProfileRegistry" in source


# ══════════════════════════════════════════════════════════════════════
# UI-контракт (source-level)
# ══════════════════════════════════════════════════════════════════════


def test_s12_ui_panel_use_client_first_line_and_states():
    source = _read("packages/ui/components/Doclog9ProfileControls.tsx")
    assert source.splitlines()[0].strip() == '"use client";'
    # Честные состояния (§12.3) -- все пять фаз.
    for phase in ('"loading"', '"ready"', '"empty"', '"forbidden"', '"error"'):
        assert phase in source, phase
    # Статус валидации ТЕКСТОМ (цвет не единственный носитель).
    assert "не пройдена" in source and "пройдена" in source
    # Панель вызывает библиотечные функции (данные -- ответы сервера).
    for fn in ("listOrgProfiles", "requestRendition",
               "getRenditionValidations", "verifyRenditionSignature"):
        assert fn in source, fn


def test_s13_ui_lib_client_contract():
    source = _read("packages/ui/lib/documentation.ts")
    # Относительные URL + экранирование параметров; ключ не в URL.
    assert "documentationApiUrl(" in source
    assert "encodeURIComponent(renditionId)" in source
    assert "encodeURIComponent(format)" in source
    assert "http://localhost" not in source
    # org_profile_id уходит в тело заказа рендера.
    assert "org_profile_id" in source
    # verify -- POST (мутация-верификация фиксируется честно).
    verify_part = source[source.index("export function verifyRenditionSignature"):]
    verify_part = verify_part[: verify_part.index("\nexport ", 1)]
    assert '{ method: "POST" }' in verify_part


def test_s14_contract_doc_and_honest_boundaries():
    """Контракт-док существует и фиксирует честные границы (не юр. ЭП;
    structural validator; не переименование pdf)."""
    doc = _read("docs/doclog9_profiles.md")
    assert "не названием файла" in doc
    assert "НЕ юридическая" in doc or "не юридическая" in doc.lower()
    assert "не переименование pdf" in doc or "НЕ переименование" in doc
    assert "org_profile_worm" in doc
    # Код: каталог исправных границ в docstring сервиса.
    source = _read("apps/api/doc_profiles.py")
    assert "не юридическая" in source.lower()
    assert "veraPDF" in source  # внешняя валидация -- честная граница
