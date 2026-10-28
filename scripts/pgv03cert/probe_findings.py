#!/usr/bin/env python3
"""PGV-03-CERT: динамические пробы кандидатов-находок (до корпуса).

Каждая проба -- проверяемый факт о поведении поставки; результаты
идут в protocols/probe_findings.txt и в акт.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Memory-бекенды (класс psycopg-DSN снимается; паттерн conftest pgv02cert).
os.environ.pop("DATABASE_URL", None)
os.environ.pop("CISSTAT_RUNS_BACKEND", None)
os.environ.pop("CISSTAT_IDENTITY_MODE", None)
os.environ.pop("CISSTAT_API_KEYS", None)
os.environ.pop("CISSTAT_ARTIFACTS_BACKEND", None)
os.environ.setdefault("CISSTAT_DATA_DIR", str(REPO / ".p3cert-probe-data"))

out: list[str] = []


def probe(name: str, ok: bool, detail: str) -> None:
    out.append(f"[{'CONFIRMED' if ok else 'refuted  '}] {name}: {detail}")


# ── P1: selection_keys адаптеров ⊆ view_params реестра ──────────────
from apps.api.print_schema import load_visual_registry  # noqa: E402
from apps.api.visual_producers import ADAPTER_SPECS  # noqa: E402

reg = {s["view_id"]: s for s in load_visual_registry()["sites"]}
violations = []
for view_id, spec in ADAPTER_SPECS.items():
    site = reg.get(view_id)
    if site is None:
        violations.append(f"{view_id}: нет в реестре")
        continue
    vp = set(site.get("view_params") or [])
    extra = set(spec.selection_keys) - vp
    if extra:
        violations.append(f"{view_id}: {sorted(extra)} вне view_params {sorted(vp)}")
probe(
    "P1 selection_keys⊆view_params (48 wired)",
    not violations,
    "; ".join(violations) if violations else "все 48 адаптеров в allowlist реестра",
)

# ── P2: покрытие wired-видов wiring-точками роутеров ────────────────
import re as _re  # noqa: E402

wired = set(ADAPTER_SPECS)
router_text = ""
for rel in (
    "apps/api/routers/session.py",
    "apps/api/routers/tasks_session.py",
    "apps/api/routers/forecasting_session.py",
    "apps/api/routers/modeling_session.py",
):
    router_text += (REPO / rel).read_text(encoding="utf-8")
referenced = set(_re.findall(r'"([a-z_]+(?:\.[a-z_]+)+)"', router_text))
sweep_views = {"modeling.backtest.comparison", "modeling.backtest.oof"}
missing_wiring = sorted(wired - referenced - sweep_views)
probe(
    "P2 каждый wired view добирается wiring/sweep",
    not missing_wiring,
    f"без wiring: {missing_wiring}" if missing_wiring else "48 = wiring-точки + sweep(comparison/oof)",
)

# ── P3: unknown view -- честный отказ резолва ───────────────────────
from apps.api.visual_producers import resolve_producer_view  # noqa: E402

try:
    resolve_producer_view("upload.chart.typo_demo")
    probe("P3 unknown view rejection", False, "резолв не отказал?!")
except Exception as exc:  # noqa: BLE001
    probe(
        "P3 unknown view -> честный отказ",
        type(exc).__name__ == "UnknownVisualView",
        f"{type(exc).__name__}",
    )

# ── P4: CAS fail-open при expected_*=None ───────────────────────────
# freeze_saved_visual передаёт saved.context_id/saved.data_revision как
# ожидания; _check_context_cas пропускает сверку при None. Проба:
# контекст run сменился; freeze с expected_*=None проходит без конфликта.
from apps.api.artifact_store import (  # noqa: E402
    reset_artifact_object_store_for_testing,
)
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef  # noqa: E402
from apps.api.research_runs import (  # noqa: E402
    ResearchRun,
    get_research_run_store,
)
from apps.api.security_audit import reset_audit_for_testing  # noqa: E402
from apps.api.visual_artifacts import (  # noqa: E402
    freeze_visual_result,
    list_visual_results,
)

reset_artifact_object_store_for_testing()
reset_audit_for_testing()

RUN = "RUN-PROBE-P4"
subj = SubjectRef.from_session("probe-p4")
store = get_research_run_store()
run = ResearchRun(
    run_id=RUN,
    session_id="probe-p4",
    dataset_fingerprint="ab" * 16,
    dataset_name="probe",
    target_column="v",
    created_at=datetime.now(timezone.utc).isoformat(),
    last_active_at=datetime.now(timezone.utc).isoformat(),
    status="active",
    owner_subject=subj.subject_id,
    tenant_id=DEFAULT_TENANT_ID,
    ownership="bound",
    context_id="ctx-OLD",
    data_revision=3,
)
store.upsert_run(run)
payload = {
    "schema_version": "pgv.visual_result/1",
    "view_id": "upload.chart.series",
    "payload": {
        "kind": "recharts_svg",
        "series_cap": None,
        "digest": "c" * 64,
        "digest_reason": None,
        "data": {"series": [1, 2, 3]},
    },
    "parameters": {
        "origin": "producer_first_export",
        "method": "probe",
        "parameters": {},
    },
    "units": [{"value": None, "reason": "legacy_unknown"}],
    "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
    "warnings": [],
    "execution": {
        "execution_ref": "producer:pgv-03/x",
        "result_ref": "vr-probe-p4",
        "computed_at": None,
        "computed_at_reason": "producer_not_reported",
    },
}
# Данные сменились: run.context_id теперь ctx-NEW, revision 4
store.upsert_run(dc_replace(run, context_id="ctx-NEW", data_revision=4))
freeze_visual_result(
    RUN,
    subj,
    payload=payload,
    session_id="probe-p4",
    expected_context_id=None,  # saved.context_id == None (деградация контекста)
    expected_data_revision=None,
)
frozen = list_visual_results(RUN)
probe(
    "P4 CAS fail-open при expected_*=None (freeze_saved_visual с деградировавшим контекстом)",
    len(frozen) == 1,
    (
        f"context сменился ctx-OLD→ctx-NEW, rev 3→4; freeze прошёл без конфликта, "
        f"артефактов={len(frozen)}"
        if frozen
        else "конфликт сработал"
    ),
)

# ── P5: двойной _now_iso() в notify_visual_result ───────────────────
src = (REPO / "apps" / "api" / "promotion_integration.py").read_text(encoding="utf-8")
double_now = src.count("computed_at or _now_iso()")
probe(
    "P5 двойной _now_iso() в notify_visual_result",
    double_now == 2,
    f"сохранение и freeze берут независимые _now_iso() (вхождений: {double_now})",
)

# ── P6: поверхностный dict(response) в кэше ─────────────────────────
from apps.api.visual_producers import (  # noqa: E402
    get_saved_visual_response,
    reset_visual_response_cache_for_testing,
    save_visual_response,
)

reset_visual_response_cache_for_testing()


class FakeSession:
    run_id = "RUN-SHALLOW"
    session_id = "probe-shallow"
    data_revision = 1
    dataset = object()

    def current_context_id(self):
        return "ctx-shallow"


resp = {"points": [1, 2, 3]}
ref = save_visual_response(FakeSession(), response=resp, params={})
resp["points"].append(999)  # мутация ответа ПОСЛЕ сохранения
saved = get_saved_visual_response("RUN-SHALLOW", ref)
leaked = saved is not None and 999 in (saved.response.get("points") or [])
probe(
    "P6 кэш хранит поверхностную копию ответа",
    leaked,
    "мутация вложенного списка ответа видна в кэше (общие ссылки)"
    if leaked
    else "кэш изолирован",
)

protocols = Path(__file__).resolve().parent / "protocols"
protocols.mkdir(parents=True, exist_ok=True)
(protocols / "probe_findings.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
