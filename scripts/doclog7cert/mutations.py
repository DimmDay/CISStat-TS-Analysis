#!/usr/bin/env python3
"""DOCLOG-7-CERT: мутационная кампания («мутанты на своих мутантах»).

Двухканальная схема (прецедент DOCLOG-6-CERT):
  REPO    -- tests/api/test_doclog{7,3,4,6}_*.py (поверхность DOCLOG-7
             + фундаментальные пины telemetry/audit/delivery/каталогов,
             231 тест);
  ORACLE  -- scripts/doclog7cert (собственный корпус сертификатора, 73).

Классификация: DUAL-KILLED / REPO-ONLY / ORACLE-ONLY / SURVIVED.
Контрольные (no-op) мутанты обязаны остаться ALIVE в обоих каналах.

Мета-валидация:
  MV1 patch-applies: каждый мутант применяется ровно один раз по
      уникальному якорю (счётчик обязан быть = 1);
  MV2 classifier self-test: сверка с синтетикой;
  MV3 RESTORE: после каждого мутанта файл восстановлен байт-в-байт
      (md5-сверка; счётчик RESTORE-FAIL обязан быть 0);
  MV4 controls: 3 no-op контроля ALIVE (каналы не «косят» всё);
  MV5 (адъюдикация): скан хвостов каналов на посторонние падения --
      выполняется вручную по протоколам mut_*.json.

Resume: существующие protocols/mut_<name>.json не пересчитываются.
После кампании md5 всех целей обязан совпасть с HEAD (проверка сборки).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/z/CISStat-TS-Analysis")
CERT_DIR = REPO / "scripts" / "doclog7cert"
PROTOCOLS = CERT_DIR / "protocols"

ADMIN_LOGS = REPO / "apps" / "api" / "admin_logs.py"
LOGS_ROUTER = REPO / "apps" / "api" / "routers" / "logs.py"
DOC_JOBS = REPO / "apps" / "api" / "document_jobs.py"
SECURITY = REPO / "apps" / "api" / "security_audit.py"

REPO_CMD = [
    sys.executable, "-m", "pytest",
    "tests/api/test_doclog7_logs_support.py",
    "tests/api/test_doclog3_telemetry_audit.py",
    "tests/api/test_doclog4_document_delivery.py",
    "tests/api/test_doclog6_approvals_archive.py",
    "-q", "--tb=no", "-p", "no:cacheprovider",
]
ORACLE_CMD = [
    sys.executable, "-m", "pytest",
    "scripts/doclog7cert/test_d7cert_oracle_unit.py",
    "scripts/doclog7cert/test_d7cert_oracle_api.py",
    "scripts/doclog7cert/test_d7cert_oracle_static.py",
    "-q", "--tb=no", "-p", "no:cacheprovider",
]

# ── Мутанты: (имя, файл, старое, новое) ───────────────────────────────

BATTLE: list[tuple[str, Path, str, str]] = [
    # ── Эффективный доступ (§15.1) ──
    ("M01_admin_role_bypass", ADMIN_LOGS,
     '    is_admin = role_value == Role.ADMIN or role_value == "admin"',
     "    is_admin = True"),
    ("M02_grants_ignored_in_resolve", ADMIN_LOGS,
     """    grants: list[SupportGrantRecord] = []
    if subject_id:
        store = registry or get_support_grant_registry()
        grants = [
            g for g in store.list_grants(subject_id=subject_id)
            if not _is_expired(g)
        ]""",
     "    grants: list[SupportGrantRecord] = []"),
    ("M03_key_scopes_ignored", ADMIN_LOGS,
     "    effective = scopes | grant_scopes",
     "    effective = grant_scopes"),
    ("M04_tenant_gate_off", ADMIN_LOGS,
     """    tenant = query.filters.get("tenant_id")
    if tenant is not None and access.tenants and tenant not in access.tenants:
        raise LogsAccessDenied("tenant_id вне границы support grant")""",
     """    tenant = query.filters.get("tenant_id")
    if False:
        raise LogsAccessDenied("tenant_id вне границы support grant")"""),
    ("M05_run_gate_off", ADMIN_LOGS,
     """    run = query.filters.get("run_id")
    if run is not None and access.runs and run not in access.runs:
        raise LogsAccessDenied("run_id вне границы support grant")""",
     """    run = query.filters.get("run_id")
    if False:
        raise LogsAccessDenied("run_id вне границы support grant")"""),
    ("M06_narrow_tenant_check_off", ADMIN_LOGS,
     """    tenant = record.get("tenant_id")
    if access.tenants and tenant not in access.tenants:
        return False""",
     """    tenant = record.get("tenant_id")
    if False:
        return False"""),
    # ── Гранты: валидация/whitelist/TTL (§14.2/§15) ──
    ("M07_grant_scopes_widened_data", ADMIN_LOGS,
     '''GRANT_SCOPES: frozenset[str] = frozenset(
    {"logs.read", "audit.read", "logs.export"}
)''',
     '''GRANT_SCOPES: frozenset[str] = frozenset(
    {"logs.read", "audit.read", "logs.export", "artifact.data.read"}
)'''),
    ("M08_ttl_upper_bound_off", ADMIN_LOGS,
     "        if ttl <= 0 or ttl > GRANT_TTL_MAX_HOURS:",
     "        if ttl <= 0:"),
    ("M09_is_expired_fail_open", ADMIN_LOGS,
     """    expires = _parse_iso(grant.expires_at)
    if expires is None:
        return True  # невалидная дата -- fail-closed
    return expires <= moment""",
     """    expires = _parse_iso(grant.expires_at)
    if expires is None:
        return False
    return expires <= moment"""),
    ("M10_revoked_grants_counted", ADMIN_LOGS,
     "            g for g in store.list_grants(subject_id=subject_id)",
     "            g for g in store.list_grants(\n                subject_id=subject_id, include_revoked=True)"),
    ("M11_revoke_idempotency_off", ADMIN_LOGS,
     """        if record.revoked_at is not None:
            return record  # идемпотентный повторный отзыв""",
     """        if False:
            return record  # идемпотентный повторный отзыв"""),
    ("M12_revoke_state_not_persisted", ADMIN_LOGS,
     "        return self.registry.update_grant(revoked)",
     "        return revoked"),
    # ── Запрос журнала: окно/лимиты/cursor/фильтры (§14.2) ──
    ("M13_window_check_off", ADMIN_LOGS,
     "    if to_ts - from_ts > timedelta(days=WINDOW_MAX_DAYS):",
     "    if False:"),
    ("M14_limit_upper_off", ADMIN_LOGS,
     "    if limit < 1 or limit > QUERY_LIMIT_MAX:",
     "    if limit < 1:"),
    ("M15_filters_whitelist_off", ADMIN_LOGS,
     """    unknown = set(filters) - whitelist
    if unknown:""",
     """    unknown = set(filters) - whitelist
    if False:"""),
    ("M16_cursor_validation_off", ADMIN_LOGS,
     """        if not isinstance(data, dict) or "t" not in data or "id" not in data:
            raise ValueError""",
     """        if not isinstance(data, dict) or "t" not in data or "id" not in data:
            data = {"t": "", "id": ""}"""),
    ("M17_retention_horizons_swapped", ADMIN_LOGS,
     """TELEMETRY_RETENTION_DAYS = 30  # §16.1
AUDIT_RETENTION_DAYS = 365     # §16.1""",
     """TELEMETRY_RETENTION_DAYS = 365  # §16.1
AUDIT_RETENTION_DAYS = 30     # §16.1"""),
    ("M18_retention_note_off", ADMIN_LOGS,
     """        if from_ts < edge:
            meta["retention_note"] = (""",
     """        if False:
            meta["retention_note"] = ("""),
    # ── Саможурналирование (§14.2, AC11) ──
    ("M19_stream_self_audit_off", LOGS_ROUTER,
     '''    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",''',
     '''    return payload
    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",'''),
    ("M20_stream_self_audit_mandatory", LOGS_ROUTER,
     '''    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",''',
     '''    __import__("apps.api.security_audit", fromlist=["x"]).record_mandatory(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",'''),
    ("M21_authz_denied_on_deny_off", LOGS_ROUTER,
     '''    from apps.api.identity import subject_pseudonym

    record_standard(
        "authz_denied",''',
     '''    from apps.api.identity import subject_pseudonym

    if True:
        return JSONResponse(
            status_code=403,
            content={
                "code": "logs_access_denied",
                "message": "Доступ к журналам не выдан (§15)",
                "request_id": current_request_id(),
            },
        )
    record_standard(
        "authz_denied",'''),
    ("M22_export_mandatory_audit_standard", LOGS_ROUTER,
     '''        from apps.api.security_audit import record_mandatory

        bundle_id = record_mandatory(''',
     '''        from apps.api.security_audit import record_standard

        bundle_id = record_standard('''),
    ("M23_download_triple_noop", LOGS_ROUTER,
     '''    record_standard(
        ACTION_DOWNLOAD_REQUESTED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="logs export policy",
    )''',
     '''    (lambda *a, **k: None)(
        ACTION_DOWNLOAD_REQUESTED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="logs export policy",
    )'''),
    ("M24_stream_finished_noop", LOGS_ROUTER,
     '''    record_standard(
        ACTION_RESPONSE_STREAM_FINISHED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="details",
    )''',
     '''    (lambda *a, **k: None)(
        ACTION_RESPONSE_STREAM_FINISHED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="details",
    )'''),
    ("M25_export_window_parse_bogus", LOGS_ROUTER,
     '''        parsed = parse_query(
            "telemetry",  # валидация окна/лимитов; потоки -- отдельно''',
     '''        parsed = parse_query(
            "bogus",  # валидация окна/лимитов; потоки -- отдельно'''),
    # ── Диагностический пакет (AC10/AC19) ──
    ("M26_export_scope_check_off", ADMIN_LOGS,
     '''    if not access.export:
        raise LogsAccessDenied("logs.export отсутствует")''',
     '''    if False:
        raise LogsAccessDenied("logs.export отсутствует")'''),
    ("M27_bundle_unrestricted_access", LOGS_ROUTER,
     '''        zip_bytes, bundle_id, filename = build_diagnostic_bundle(
            parsed, access, streams=streams
        )''',
     '''        zip_bytes, bundle_id, filename = build_diagnostic_bundle(
            parsed,
            EffectiveLogAccess(telemetry=True, audit=True, delivery=True,
                               export=True, grants_management=True),
            streams=streams
        )'''),
    ("M28_bundle_members_sha256_zero", ADMIN_LOGS,
     '''        "members_sha256": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in members
        },''',
     '''        "members_sha256": {
            name: "0" * 64
            for name, content in members
        },'''),
    ("M29_bundle_excluded_dropped", ADMIN_LOGS,
     '        "excluded": list(BUNDLE_EXCLUDED),',
     '        "excluded": [],'),
    ("M30_zip_dates_not_fixed", ADMIN_LOGS,
     "    info = zipfile.ZipInfo(name, date_time=BUNDLE_DATE_TIME)",
     "    info = zipfile.ZipInfo(name)"),
    # ── Delivery-проекция (document_jobs.py) ──
    ("M31_delivery_summary_leaks_content_key", DOC_JOBS,
     '''                    "kind_code": (
                        document.kind_code if document is not None else None
                    ),
                }
            )''',
     '''                    "kind_code": (
                        document.kind_code if document is not None else None
                    ),
                    "content_bytes": "d7c-leak",
                }
            )'''),
    ("M32_delivery_state_filter_off", DOC_JOBS,
     """            if state is not None and job.state != state:
                continue""",
     """            if False and state is not None and job.state != state:
                continue"""),
    ("M33_delivery_kind_code_join_off", DOC_JOBS,
     '''                    "kind_code": (
                        document.kind_code if document is not None else None
                    ),''',
     '''                    "kind_code": (
                        None
                    ),'''),
    # ── Uniform-ошибки роутера ──
    ("M34_denied_403_to_404", LOGS_ROUTER,
     '''    return JSONResponse(
        status_code=403,
        content={
            "code": "logs_access_denied",''',
     '''    return JSONResponse(
        status_code=404,
        content={
            "code": "logs_access_denied",'''),
    ("M35_missing_key_401_to_422", LOGS_ROUTER,
     '''        raise HTTPException(
            status_code=401,
            detail="Требуется API-ключ (X-API-Key)",''',
     '''        raise HTTPException(
            status_code=422,
            detail="Требуется API-ключ (X-API-Key)",'''),
    ("M36_grant_404_to_403", LOGS_ROUTER,
     '''            status_code=404,
            content={
                "code": "grant_not_found",''',
     '''            status_code=403,
            content={
                "code": "grant_not_found",'''),
    # ── Прочие поверхности ──
    ("M37_pg_narrow_clauses_off", ADMIN_LOGS,
     """    if access.tenants:
        placeholders = ", ".join(["%s"] * len(access.tenants))
        clauses.append(f"tenant_id IN ({placeholders})")
        params.extend(sorted(access.tenants))""",
     """    if False and access.tenants:
        placeholders = ", ".join(["%s"] * len(access.tenants))
        clauses.append(f"tenant_id IN ({placeholders})")
        params.extend(sorted(access.tenants))"""),
    ("M38_pg_audit_list_recent_drops_actor_column", SECURITY,
     '            "SELECT audit_id, schema_version, occurred_at, actor_subject,"',
     '            "SELECT audit_id, schema_version, occurred_at,"'),
]

CONTROLS: list[tuple[str, Path, str, str]] = [
    ("C1_docstring_only", ADMIN_LOGS,
     "DOCLOG-7 (spec_documentation_logging.md §14.2, §15, §19 строка\nDOCLOG-7): журналы и поддержка -- чтение durable-журналов, support\ngrants, диагностический пакет.",
     "DOCLOG-7 (spec_documentation_logging.md §14.2, §15, §19 строка\nDOCLOG-7): журналы и поддержка -- чтение durable-журналов, support\ngrants, диагностический пакет. [контроль C1]"),
    ("C2_comment_only", LOGS_ROUTER,
     "# ── Потоки журналов ──────────────────────────────────────────────────",
     "# ── Потоки журналов [контроль C2 -- no-op] ───────────────────────────"),
    ("C3_docstring_only", DOC_JOBS,
     '''        """DOCLOG-7 (§14.2 вкладка «Доставка и документы»): безопасные
        metadata доставки (jobs + rendition/document цепочка) для админ-
        журналов. БЕЗ content_bytes/payload -- только состояния. Порядок
        (created_at DESC, job_id DESC). Структурный паритет Memory/
        Postgres обязателен (урок F-D2C1)."""''',
     '''        """DOCLOG-7 (§14.2 вкладка «Доставка и документы»): безопасные
        metadata доставки (jobs + rendition/document цепочка) для админ-
        журналов. БЕЗ content_bytes/payload -- только состояния. Порядок
        (created_at DESC, job_id DESC). Структурный паритет Memory/
        Postgres обязателен (урок F-D2C1).

        [контроль C3 -- no-op]."""'''),
]


def classify(repo_ok: bool, oracle_ok: bool) -> str:
    """MV2-классификатор (сверен с синтетикой в self_test)."""
    if repo_ok and oracle_ok:
        return "SURVIVED"
    if not repo_ok and not oracle_ok:
        return "DUAL-KILLED"
    if not repo_ok and oracle_ok:
        return "REPO-ONLY"
    return "ORACLE-ONLY"


def self_test_classifier() -> bool:
    return (
        classify(True, True) == "SURVIVED"
        and classify(False, False) == "DUAL-KILLED"
        and classify(False, True) == "REPO-ONLY"
        and classify(True, False) == "ORACLE-ONLY"
    )


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_channel(cmd: list[str], cwd: Path, timeout: int = 420) -> tuple[bool, str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    tail = "\n".join(result.stdout.strip().splitlines()[-6:])
    return result.returncode == 0, tail


def apply_mutant(path: Path, old: str, new: str) -> bool:
    """MV1: якорь обязан встречаться ровно один раз."""
    content = path.read_text(encoding="utf-8")
    if content.count(old) != 1:
        return False
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True


def restore(path: Path, md5_original: str, original: str) -> bool:
    path.write_text(original, encoding="utf-8")
    return md5_of(path) == md5_original


def run_one(name: str, path: Path, old: str, new: str, kind: str) -> dict:
    protocol_file = PROTOCOLS / f"mut_{name}.json"
    if protocol_file.exists():
        return json.loads(protocol_file.read_text(encoding="utf-8"))
    original = path.read_text(encoding="utf-8")
    md5_before = md5_of(path)
    entry: dict = {
        "name": name, "kind": kind, "file": path.name,
        "patch_applies": apply_mutant(path, old, new),  # MV1
    }
    if entry["patch_applies"]:
        time.sleep(0.2)
        repo_ok, repo_tail = run_channel(REPO_CMD, REPO)
        oracle_ok, oracle_tail = run_channel(ORACLE_CMD, REPO)
        entry.update({
            "repo_pass": repo_ok,
            "oracle_pass": oracle_ok,
            "classification": classify(repo_ok, oracle_ok),
            "repo_tail": repo_tail,
            "oracle_tail": oracle_tail,
            "restored": restore(path, md5_before, original),  # MV3 md5
        })
        if not entry["restored"]:
            entry["classification"] = "RESTORE-FAIL"
    else:
        entry.update({
            "repo_pass": None, "oracle_pass": None,
            "classification": "PATCH-FAIL", "restored": True,
        })
    protocol_file.write_text(
        json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return entry


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
    universe = [
        (name, path, old, new, "battle")
        for name, path, old, new in BATTLE
    ] + [
        (name, path, old, new, "control")
        for name, path, old, new in CONTROLS
    ]
    if not self_test_classifier():
        print("MV2 classifier self-test FAILED")
        return 2
    print("MV2 classifier self-test OK", flush=True)
    restore_failures = 0
    patch_failures = 0
    for index, (name, path, old, new, kind) in enumerate(universe):
        if not (start <= index < end):
            continue
        entry = run_one(name, path, old, new, kind)
        if entry["classification"] == "RESTORE-FAIL":
            restore_failures += 1
        if entry["classification"] == "PATCH-FAIL":
            patch_failures += 1
        print(
            f"[{index:02d}] {name:44s} {entry['classification']}",
            flush=True,
        )
    print(f"restore_failures={restore_failures} patch_failures={patch_failures}")
    # сводка
    entries = []
    for name, path, old, new, kind in universe:
        f = PROTOCOLS / f"mut_{name}.json"
        if f.exists():
            entries.append(json.loads(f.read_text(encoding="utf-8")))
    summary = {
        "total": len(entries),
        "battle": sum(e.get("kind") == "battle" for e in entries),
        "controls": sum(e.get("kind") == "control" for e in entries),
        "DUAL-KILLED": sum(e["classification"] == "DUAL-KILLED" for e in entries),
        "REPO-ONLY": sum(e["classification"] == "REPO-ONLY" for e in entries),
        "ORACLE-ONLY": sum(e["classification"] == "ORACLE-ONLY" for e in entries),
        "SURVIVED": sum(e["classification"] == "SURVIVED" for e in entries),
        "PATCH-FAIL": sum(e["classification"] == "PATCH-FAIL" for e in entries),
        "RESTORE-FAIL": sum(e["classification"] == "RESTORE-FAIL" for e in entries),
        "controls_alive": sum(
            e["classification"] == "SURVIVED"
            for e in entries if e.get("kind") == "control"
        ),
    }
    (PROTOCOLS / "mutations_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
