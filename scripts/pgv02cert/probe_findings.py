# scripts/pgv02cert/probe_findings.py
"""Динамические пробы кандидатов в находки PGV-02 (read-only для продукта).

Namespace проб: RUN-P2CPROBE*, p2cert-probe-* (дизъюнктен repo и другим
сертификаторам). Каждая проба печатает исход и фиксирует факт для акта.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

tmp = tempfile.mkdtemp(prefix="p2cert-probe-")
os.environ["CISSTAT_DATA_DIR"] = tmp
# Среда сессии может нести посторонний DATABASE_URL (известный средовой
# класс psycopg-DSN) -- Memory-бекенд обязателен для детерминизма.
for _var in ("DATABASE_URL", "CISSTAT_RUNS_BACKEND", "CISSTAT_IDENTITY_MODE",
             "CISSTAT_API_KEYS", "CISSTAT_ARTIFACTS_BACKEND"):
    os.environ.pop(_var, None)

from apps.api import research_runs  # noqa: E402
from apps.api.artifact_store import (  # noqa: E402
    get_artifact_registry,
    reset_artifact_object_store_for_testing,
    reset_artifact_registry_for_testing,
)
from apps.api.document_jobs import reset_document_registry_for_testing  # noqa: E402
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef  # noqa: E402
from apps.api.research_runs import (  # noqa: E402
    ResearchRun,
    get_research_run_store,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import reset_session_store_for_testing  # noqa: E402

research_runs.reset_research_run_store_for_testing()
reset_artifact_registry_for_testing()
reset_artifact_object_store_for_testing()
reset_document_registry_for_testing()
reset_session_store_for_testing()

RUN = "RUN-P2CPROBE1"
SESS = "p2cert-probe-session-a"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_run(run_id: str = RUN, session_id: str = SESS, **kw) -> None:
    from dataclasses import replace as dc_replace

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p2cp" * 8,
        dataset_name="p2cert-probe",
        target_column="value",
        created_at=now(),
        last_active_at=now(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    if "context_id" in kw or "data_revision" in kw:
        run = dc_replace(
            run,
            context_id=kw.get("context_id", run.context_id),
            data_revision=kw.get("data_revision", run.data_revision),
        )
    get_research_run_store().upsert_run(run)


def visual_result(**ov):
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    r = {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": "upload.distribution.scatter",
        "payload": {"kind": "recharts_svg", "series_cap": None, "digest": "a" * 64, "digest_reason": None},
        "parameters": {"origin": "producer_freeze", "method": "scatter", "parameters": {}},
        "units": [{"value": "usd", "reason": None}],
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "exec-probe-1",
            "result_ref": "session:probe:v1",
            "computed_at": "2026-10-28T09:00:00Z",
            "computed_at_reason": None,
        },
    }
    r.update(ov)
    return r


def checkpoint(**ov):
    from apps.api.visual_artifacts import CHECKPOINT_SCHEMA_VERSION

    p = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_id": "pck-p2cert-probe-1",
        "stage": "modeling_entry",
        "confirmed_at": "2026-10-28T10:00:00Z",
        "confirmed_at_reason": None,
        "snapshot_ref": "rs-" + "0" * 32,
        "previous_snapshot_ref": None,
        "flags": {"created": True, "reused": False, "unchanged": False},
        "stage_refs": {"start": "rs-" + "1" * 32, "validation": "rs-" + "2" * 32, "exit": "rs-" + "3" * 32},
        "context": {"run_id": RUN, "context_id": "ctx-p2cert-1", "data_revision": 7, "target_column": "value", "entity_id": None},
        "provenance": {"source": "producer_capture"},
    }
    p.update(ov)
    return p


subject = SubjectRef.from_session(SESS)

print("=" * 72)
print("PROBE F1: ensure_print_document_revision -- несуществующие basis-артефакты")
print("=" * 72)
from apps.api.document_jobs import DocumentDeliveryService, get_document_registry  # noqa: E402

seed_run()
svc = DocumentDeliveryService.create_default()
try:
    doc, rev, created = svc.ensure_print_document_revision(
        RUN, subject, session_id=SESS,
        print_kind="V01", basis_kind="visual_print_snapshot",
        basis_artifact_ids=["art-" + "f" * 32],  # НЕ существует в реестре
    )
    print(f"создано: created={created}, revision={rev.print_revision_id}")
    print(f"basis_artifact_ids в ревизии: {rev.basis_artifact_ids}")
    pins = get_artifact_registry().list_pins(RUN, ref_kind="artifact")
    print(f"пины: {[(p.ref_id, p.reason) for p in pins]}")
    print("ИТОГ: dangling basis ПРИНЯТ (ревизия создана со ссылкой на несуществующий артефакт)")
except Exception as exc:
    print(f"ИТОГ: честный отказ: {type(exc).__name__}: {exc}")

print()
print("=" * 72)
print("PROBE F1b: basis-артефакт ЧУЖОГО run")
print("=" * 72)
RUN2 = "RUN-P2CPROBE2"
SESS2 = "p2cert-probe-session-b"
seed_run(RUN2, SESS2)
from apps.api.artifact_promotion import PromotionService  # noqa: E402

svc2 = PromotionService.create_default()
art = svc2.persist_visual_artifact(
    RUN2, subject, kind="visual_result", payload=visual_result(),
    producer_key="pgv.visual_result:probe:foreign", session_id=SESS2,
    context_id=None, data_revision=None,
)
reset_document_registry_for_testing()
svc3 = DocumentDeliveryService.create_default()
try:
    doc, rev, created = svc3.ensure_print_document_revision(
        RUN, subject, session_id=SESS,
        print_kind="V01", basis_kind="visual_print_snapshot",
        basis_artifact_ids=[art.artifact_id],  # чужой run
    )
    pins = get_artifact_registry().list_pins(RUN, ref_kind="artifact")
    print(f"создано: created={created}; пин в RUN на артефакт RUN2: {[p.ref_id for p in pins]}")
    print("ИТОГ: чужой basis ПРИНЯТ без проверки принадлежности run'у")
except Exception as exc:
    print(f"ИТОГ: честный отказ: {type(exc).__name__}: {exc}")

print()
print("=" * 72)
print("PROBE F2: CAS fail-open на нечисловой строке expected_context.data_revision")
print("=" * 72)
from apps.api.visual_artifacts import (  # noqa: E402
    PrintContextConflict,
    freeze_visual_print_snapshot,
)

seed_run(RUN, SESS, context_id="ctx-p2cert-1", data_revision=7)
snap_payload = {
    "schema_version": "pgv.visual_print_snapshot/1",
    "view_id": "upload.distribution.scatter",
    "scope": "research",
    "refs": {"context_id": "ctx-p2cert-1", "data_revision": "42", "target_column": "value",
             "date_column": "dt"},
    "result": {"result_ref": "artifact:p2cert-r", "result_schema_version": "pgv.visual_result/1",
               "result_digest": "a" * 64, "result_digest_reason": None},
    "data_artifact": {"artifact_id": "artifact:p2c", "artifact_version": "v7",
                      "source_hash": "b" * 64, "hash_algorithm": "sha256", "hash_reason": None},
    "expected_context": {"context_id": "ctx-p2cert-1", "data_revision": "abc", "expected_data_digest": None},
    "dimensions": {"target_column": "value", "date_column": "dt", "entity_column": None, "entity_id": None, "mode": "univariate"},
    "times": {"computed_at": "2026-10-28T09:00:00Z", "computed_at_reason": None,
              "captured_at": "2026-10-28T09:00:01Z", "captured_at_reason": None,
              "checkpoint_confirmed_at": None, "render_requested_at": "2026-10-28T09:00:02Z",
              "timezone": "UTC", "locale": "ru-RU"},
    "checkpoint": None,
    "display": {"title": "t", "subtitle": None, "detail_level": "compact", "sections": [{
        "section_id": "s1", "renderer_kind": "recharts_svg", "title": "Диаграмма",
        "axes": [{"name": "Дата", "units": {"value": "date", "reason": None}, "scale": "time", "limits": None},
                 {"name": "Ряд", "units": {"value": "usd", "reason": None}, "scale": "linear", "limits": None}],
        "legend_ordering": ["s"], "table_headings": None, "heatmap_scale": None,
        "units": [{"value": "usd", "reason": None}]}]},
    "method": {"origin": "producer_freeze", "method": "scatter", "parameters": {}},
    "selection": {"allowlist": [], "values": {}},
    "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
    "annotations": {"revision": 0, "author": "analyst", "text": None},
    "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
    "renderer_env": {"renderer_version": "x/1", "font_profile": "dejavu-sans/1",
                     "dependency_status": "available", "unavailable_reason": None},
    "data_flow": {"before_revision": None, "after_revision": None},
    "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "redacted"},
    "warnings": [],
}
before = len(get_artifact_registry().list_artifacts(RUN))
try:
    a = freeze_visual_print_snapshot(RUN, subject, payload=snap_payload, session_id=SESS)
    after = len(get_artifact_registry().list_artifacts(RUN))
    print(f"freeze ПРОШЁЛ (artifact={a.artifact_id}); артефактов {before} -> {after}")
    print("ИТОГ: CAS fail-open -- снапшот декларирует ревизию 42 (строкой в refs), "
          "expected='abc' нечисловая -> сверка ревизии ПРОПУЩЕНА (факт. 7)")
except PrintContextConflict as exc:
    print(f"ИТОГ: честный CAS-отказ: {exc}")

print()
print("=" * 72)
print("PROBE F3: manifest_artifact_id вне basis_fingerprint (тихий дроп)")
print("=" * 72)
doc, rev1, c1 = svc.ensure_print_document_revision(
    RUN, subject, session_id=SESS, print_kind="P01", basis_kind="passport",
    basis_artifact_ids=[], snapshot_id=None, manifest_artifact_id="art-" + "1" * 32,
)
doc2, rev2, c2 = svc.ensure_print_document_revision(
    RUN, subject, session_id=SESS, print_kind="P01", basis_kind="passport",
    basis_artifact_ids=[], snapshot_id=None, manifest_artifact_id="art-" + "2" * 32,
)
print(f"первый вызов: created={c1}, manifest={rev1.manifest_artifact_id}")
print(f"второй вызов: created={c2}, manifest={rev2.manifest_artifact_id}, id ревизии тот же: {rev1.print_revision_id == rev2.print_revision_id}")
dropped = rev2.manifest_artifact_id == rev1.manifest_artifact_id and rev1.manifest_artifact_id != "art-" + "2" * 32
print("ИТОГ: " + ("manifest_artifact_id молча отброшен на идемпотентном пути" if dropped else "учтён"))

print()
print("=" * 72)
print("PROBE F4: previous_snapshot_ref == snapshot_ref (самоссылка)")
print("=" * 72)
from apps.api.visual_artifacts import validate_passport_checkpoint  # noqa: E402

viol = validate_passport_checkpoint(checkpoint(previous_snapshot_ref="rs-" + "0" * 32))
print(f"violations: {[v.code for v in viol]}")
print("ИТОГ: " + ("самоссылка ПРИНЯТА" if not viol else "отвергнута"))

print()
print("=" * 72)
print("PROBE F5: pin-отказ после создания артефакта (freeze_visual_print_snapshot)")
print("=" * 72)

seed_run(RUN, SESS, context_id="ctx-p2cert-1", data_revision=7)
svc4 = PromotionService.create_default()
res_art = svc4.persist_visual_artifact(
    RUN, subject, kind="visual_result", payload=visual_result(result_ref="session:probe:v2"),
    producer_key="pgv.visual_result:probe:v2", session_id=SESS, context_id="ctx-p2cert-1", data_revision=7,
)
n_before = len(get_artifact_registry().list_artifacts(RUN))


class _Boom(Exception):
    pass


orig_pin = type(get_artifact_registry()).pin_ref


def boom(*a, **k):
    raise _Boom("pin storage down")


type(get_artifact_registry()).pin_ref = boom
try:
    freeze_visual_print_snapshot(
        RUN, subject,
        payload={**snap_payload,
                 "result": {**snap_payload["result"], "result_ref": "artifact:probe-f5",
                            "result_digest": "c" * 64}},
        session_id=SESS, result_artifact_id=res_art.artifact_id,
    )
    print("ИТОГ: исключения не было")
except _Boom:
    n_after = len(get_artifact_registry().list_artifacts(RUN))
    print(f"_Boom пойман; артефактов {n_before} -> {n_after} "
          f"(артефакт остался зарегистрированным, пин зависимости НЕ поставлен)")
finally:
    type(get_artifact_registry()).pin_ref = orig_pin

print()
print("=" * 72)
print("PROBE F6: Memory print-реестр не обеспечивает UNIQUE(document_id, version_no)")
print("=" * 72)
from apps.api.document_jobs import (  # noqa: E402
    DocumentPrintRevisionRecord,
    new_print_revision_id,
)

reg = get_document_registry()
rec1 = DocumentPrintRevisionRecord(
    print_revision_id=new_print_revision_id(), document_id=doc.document_id, run_id=RUN,
    print_kind="P01", basis_kind="passport", version_no=1,
)
rec2 = DocumentPrintRevisionRecord(
    print_revision_id=new_print_revision_id(), document_id=doc.document_id, run_id=RUN,
    print_kind="P01", basis_kind="passport", version_no=1,  # тот же version_no
)
reg.register_print_revision(rec1)
reg.register_print_revision(rec2)
lst = reg.list_print_revisions(doc.document_id)
print(f"version_no=1 зарегистрирован дважды: {[r.print_revision_id for r in lst]}")
print("ИТОГ: " + ("Memory маскирует UNIQUE-ограничение DDL (класс F-D2C1)" if len(lst) == 2 else "конфликт пойман"))

print()
print("PROBE F7: контекст чекпоинта -- data_revision пустая строка/0")
viol7a = validate_passport_checkpoint(checkpoint(context={"run_id": RUN, "context_id": "ctx-p2cert-1", "data_revision": "", "target_column": "value", "entity_id": None}))
viol7b = validate_passport_checkpoint(checkpoint(context={"run_id": RUN, "context_id": "ctx-p2cert-1", "data_revision": 0, "target_column": "value", "entity_id": None}))
print(f"data_revision='': {[v.code for v in viol7a]}")
print(f"data_revision=0:  {[v.code for v in viol7b]}")
