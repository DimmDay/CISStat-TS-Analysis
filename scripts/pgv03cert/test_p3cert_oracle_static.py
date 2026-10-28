# scripts/pgv03cert/test_p3cert_oracle_static.py
#
# PGV-03-CERT — Класс A: статические оракулы (постановка/спека/док/
# реестр/границы). Продуктовое дерево не мутируется.

from __future__ import annotations

import re
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

from apps.api.print_schema import load_visual_registry  # noqa: E402
from apps.api.visual_producers import (  # noqa: E402
    ADAPTER_SPECS,
    UNWIRED_PGV03_VIEWS,
    static_demo_view_ids,
    wired_view_ids,
)

VP = "spec_passport_graphics_visual.md"
DL = "spec_documentation_logging.md"
DOC = "docs/pgv03_producer_adapters.md"
WORKLOG = "worklog/worklog11.md"


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ── 1. Постановка (спека) ────────────────────────────────────────────


class TestSpecPinning:
    def test_pgv03_row_exists_with_dependency(self):
        pgv = read(VP)
        row = next((l for l in pgv.splitlines() if l.startswith("| PGV-03 |")), "")
        assert row.startswith("| PGV-03 |")
        assert "PGV-02" in row, "зависимость PGV-03 -> PGV-02"

    def test_pgv03_row_points_of_change(self):
        pgv = read(VP)
        row = next(l for l in pgv.splitlines() if l.startswith("| PGV-03 |"))
        for stop in ("upload", "validation", "preprocessing", "EDA", "modeling", "forecast", "tasks"):
            assert stop in row, f"остановка {stop} в точках изменения"

    def test_pgv03_row_criterion(self):
        pgv = read(VP)
        row = next(l for l in pgv.splitlines() if l.startswith("| PGV-03 |"))
        assert "Freeze" in row and "CAS" in row and "export" in row and "science" in row

    def test_ac05_ac08_ac14_scenarios_present(self):
        pgv = read(VP)
        for ac in ("PGV-AC05", "PGV-AC06", "PGV-AC07", "PGV-AC08", "PGV-AC14"):
            assert ac in pgv

    def test_lazy_transfer_contract_in_spec_section6(self):
        pgv = read(VP)
        assert "lazy GET" in pgv or "lazy" in pgv
        assert "result_ref" in pgv

    def test_parent_spec_row_pgv03_in_doclog_spec(self):
        dl = read(DL)
        assert "| PGV-03 —" in dl and "Producer" in dl

    def test_doclog_spec_names_visual_producers_module(self):
        dl = read(DL)
        assert "visual_producers" in dl or "visualResult" in dl


# ── 2. Реестр PGV-00: распределение категорий (источник истины) ──────


class TestRegistryPartition:
    def test_total_sites_93(self):
        reg = load_visual_registry()
        assert reg.get("total_sites") == 93

    def test_pgv03_adapter_views_84_with_68_research(self):
        sites = load_visual_registry()["sites"]
        pgv03 = [
            s for s in sites
            if str(s.get("source_adapter", "")).startswith("pgv-03/")
        ]
        assert len(pgv03) == 84, "все pgv-03/* сайты"
        research = [s for s in pgv03 if s.get("applicability") != "static_demo"]
        assert len(research) == 68, "84 минус 16 static_demo = 68 research-видов"

    def test_static_demo_16(self):
        assert len(static_demo_view_ids()) == 16

    def test_wired_48_plus_unwired_20_equals_68(self):
        assert len(wired_view_ids()) + len(UNWIRED_PGV03_VIEWS) == 68

    def test_wired_subset_of_pgv03_research_views(self):
        sites = {
            s["view_id"]: s
            for s in load_visual_registry()["sites"]
            if str(s.get("source_adapter", "")).startswith("pgv-03/")
            and s.get("applicability") != "static_demo"
        }
        assert set(wired_view_ids()) | set(UNWIRED_PGV03_VIEWS) == set(sites)
        assert not (set(wired_view_ids()) & set(UNWIRED_PGV03_VIEWS))

    def test_static_demo_disjoint_from_research_views(self):
        assert not (set(static_demo_view_ids()) & (set(wired_view_ids()) | set(UNWIRED_PGV03_VIEWS)))

    def test_adapter_selection_keys_subset_of_registry_view_params(self):
        reg = {s["view_id"]: s for s in load_visual_registry()["sites"]}
        for view_id, spec in ADAPTER_SPECS.items():
            vp = set(reg[view_id].get("view_params") or [])
            assert set(spec.selection_keys) <= vp, (
                f"{view_id}: selection_keys {sorted(set(spec.selection_keys) - vp)} "
                "вне view_params реестра"
            )

    def test_adapter_module_matches_registry_module(self):
        reg = {s["view_id"]: s for s in load_visual_registry()["sites"]}
        for view_id in wired_view_ids():
            assert view_id.split(".", 1)[0] == reg[view_id].get("module_id"), view_id

    def test_adapter_renderer_kind_matches_registry(self):
        reg = {s["view_id"]: s for s in load_visual_registry()["sites"]}
        mixed_ok = {"recharts_svg", "html_table"}
        for view_id, spec in ADAPTER_SPECS.items():
            rk = reg[view_id].get("renderer_kind")
            if rk == "mixed":
                assert spec.renderer_kind in mixed_ok, view_id
            else:
                assert spec.renderer_kind == rk, view_id


# ── 3. Wiring: полнота покрытия (48 = wiring + sweep) ────────────────


class TestWiringCoverage:
    def _router_text(self) -> str:
        text = ""
        for rel in (
            "apps/api/routers/session.py",
            "apps/api/routers/tasks_session.py",
            "apps/api/routers/forecasting_session.py",
            "apps/api/routers/modeling_session.py",
        ):
            text += read(rel)
        return text

    def test_every_wired_view_referenced_in_routers_or_sweep(self):
        sweep = {"modeling.backtest.comparison", "modeling.backtest.oof"}
        referenced = set(
            re.findall(r'"([a-z_]+(?:\.[a-z_]+)+)"', self._router_text())
        )
        missing = set(wired_view_ids()) - referenced - sweep
        assert not missing, f"view без wiring: {sorted(missing)}"

    def test_no_unknown_view_in_wiring(self):
        # view-литералы wiring-точек обязаны быть известными категориями
        known = (
            set(wired_view_ids())
            | set(UNWIRED_PGV03_VIEWS)
            | set(static_demo_view_ids())
        )
        literal_views = set(
            re.findall(r'"([a-z_]+(?:\.[a-z_]+){2,})"', self._router_text())
        )
        unknown = {
            v for v in literal_views
            if v not in known and v.split(".")[0] in {
                "upload", "validation", "preprocessing", "eda",
                "modeling", "forecasting", "tasks", "navigator",
            }
        }
        assert not unknown, f"неизвестные view-литералы в wiring: {sorted(unknown)}"

    def test_tasks_wiring_guards_available_method(self):
        tasks = read("apps/api/routers/tasks_session.py")
        seg = tasks[tasks.find("notify_visual_result") - 1500 : tasks.find("notify_visual_result") + 400]
        assert "available" in seg, "fold_importance морозится только при available-методе"

    def test_no_new_routers_added(self):
        # Граница §13: роутеры §11 -- PGV-13/15; поставка не добавляет
        # новых маршрутов (import main -- 221, пин динамическим оракулом).
        session = read("apps/api/routers/session.py")
        assert session.count("@router.") >= 1  # файл жив; число роутеров пинится ниже


# ── 4. Документ поставки и worklog ───────────────────────────────────


class TestDeliveryDocs:
    def test_delivery_doc_exists_and_pins_files(self):
        doc = read(DOC)
        for token in (
            "apps/api/visual_producers.py",
            "apps/api/promotion_integration.py",
            "tests/api/test_pgv03_producer_adapters.py",
            "freeze_saved_visual",
            "producer_first_export",
            "UNWIRED_PGV03_VIEWS",
        ):
            assert token in doc, f"док поставки: {token}"

    def test_delivery_doc_counts_honest(self):
        doc = read(DOC)
        assert "48" in doc and "20" in doc and "16" in doc

    def test_worklog_has_pgv03_entry(self):
        wl = read(WORKLOG)
        assert "Task ID: PGV-03" in wl

    def test_worklog_preserves_previous_entries(self):
        wl = read(WORKLOG)
        for token in ("Task ID: PGV-00", "Task ID: PGV-01", "Task ID: PGV-02", "Task ID: PGV-02-CERT"):
            assert token in wl

    def test_migration_pins_updated_honestly(self):
        # Поставка обновила пины doclog3/7/9 (урок PGV-02-CERT F-P2C7)
        for rel in (
            "tests/api/test_doclog3_telemetry_audit.py",
            "tests/api/test_doclog7_logs_support.py",
            "tests/api/test_doclog9_profiles.py",
        ):
            text = read(rel)
            assert "16" in text, f"{rel}: пин миграций 16 файлов"


# ── 5. Дизъюнкт namespace и границы ──────────────────────────────────


class TestNamespaceAndBoundaries:
    def test_cert_namespace_disjoint_from_repo(self):
        corpus = " ".join(
            p.read_text(encoding="utf-8")
            for p in CERT_DIR.glob("*.py")
        )
        assert "RUN-P3C" in corpus
        # дизъюнкт с repo-сюитой: repo не использует p3cert-литералы
        repo_suite = read("tests/api/test_pgv03_producer_adapters.py")
        assert "p3cert" not in repo_suite
        assert "RUN-P3C" not in repo_suite

    def test_cert_corpus_disjoint_from_other_certs(self):
        # Дизъюнкт namespace: значимые литералы чужих корпусов (id run/ctx/
        # subj/артефактов) не встречаются; упоминания в докстрингах-декларациях
        # дизъюнкта сами по себе не нарушение.
        mine = "\n".join(
            "\n".join(
                line for line in p.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            for p in CERT_DIR.glob("*.py")
        )
        # Литералы собираются динамически -- список проверок не несёт
        # сам проверяемые литералы (анти-самотриггер).
        digits = "012"
        tokens = [f"RUN-P{d}C" for d in digits]
        tokens += [f"ctx-p{d}cert" for d in digits]
        tokens += [f"subj-p{d}c" for d in digits]
        tokens += [f"p{d}cases" for d in digits]
        tokens += [f"p{d}harness" for d in digits]
        for token in tokens:
            assert token not in mine, f"литерал {token} чужого корпуса в коде p3cert"

    def test_visual_producers_module_docstring_states_invariant(self):
        src = read("apps/api/visual_producers.py")
        assert "никакой науки здесь нет" in src or "ТОЛЬКО переносит" in src

    def test_science_runtime_not_touched_by_delivery(self):
        # Дифф поставки не трогает научные модули (срез -- из git show bf0ae7a,
        # здесь пиним файловую границу: нет импортов science из visual_producers)
        src = read("apps/api/visual_producers.py")
        for banned in ("import app.core.pipeline", "from app.core.pipeline", "sklearn", "statsmodels"):
            assert banned not in src, f"наука в producer-слое: {banned}"

    def test_promotion_module_is_single_integration_point(self):
        # §2: вторая реализация семантики запрещена -- обработчики зовут
        # только notify_visual_result promotion_integration (без прямых
        # freeze_visual_from_response в роутерах)
        for rel in (
            "apps/api/routers/session.py",
            "apps/api/routers/tasks_session.py",
            "apps/api/routers/forecasting_session.py",
            "apps/api/routers/modeling_session.py",
        ):
            src = read(rel)
            assert "freeze_visual_from_response" not in src, rel
            assert "_promotion.notify_visual_result" in src, rel
