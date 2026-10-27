# scripts/pgv00cert/test_p0cert_findings_evidence.py
#
# PGV-00-CERT — RED-свидетельства находок (Класс B).
# Намеренно ПАДАЮЩИЕ на сертифицируемом дереве 2ef6947 оракулы, кодирующие
# ТРЕБОВАНИЯ спеки, по которым сертификатор нашёл дефекты поставки.
# Это не xfail/skip: каждый тест — воспроизводимое доказательство находки
# F-P0C1…F-P0C4 акта docs/cert_pgv00_2026-10-28.md. После PGV-00-FIX
# корпус должен стать GREEN без правки смысла оракулов.

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p0scan as S

REPO = S.REPO


# ── F-P0C1: счётчик проверок guard'а в документе инвентаря ───────────


def test_f_p0c1_inventory_doc_states_actual_check_count():
    """Фактический прогон scripts/pgv00/check_documents.py даёт 353 проверки
    (совпадает с коммит-сообщением); документ инвентаря §7 заявляет 335."""
    r = __import__("subprocess").run(
        [sys.executable, "scripts/pgv00/check_documents.py"], cwd=REPO,
        capture_output=True, text=True, timeout=120,
    )
    m = re.search(r"(\d+)/(\d+)", r.stdout)
    assert m, r.stdout
    actual = int(m.group(2))
    inv = (REPO / "docs" / "pgv00_render_site_inventory.md").read_text(encoding="utf-8")
    assert str(actual) in inv, (
        f"документ инвентаря не содержит фактический счётчик {actual} (F-P0C1)"
    )


# ── F-P0C2: navigator.upload.distribution.kde отсутствует ────────────


def test_f_p0c2_navigator_kde_registered():
    """NavigatorDistributionPreview монтирует 3 recharts-графика
    (scatter/histogram/KDE — <KdeDistributionChart> в JSX); spec §5
    требует «scatter, histogram, KDE» в обязательном охвате реальных
    preview Навигатора. Реестр регистрирует только scatter и histogram."""
    src = (REPO / "packages" / "ui" / "components" / "NavigatorDistributionPreview.tsx").read_text(encoding="utf-8")
    assert "<KdeDistributionChart" in src, "претест: KDE-график исчез из компонента"
    reg = S.load_registry()
    kde = [s for s in reg["sites"] if s["view_id"] == "navigator.upload.distribution.kde"]
    assert kde, "F-P0C2: navigator.upload.distribution.kde не зарегистрирован"


def test_f_p0c2_navigator_distribution_records_have_renderer_component():
    """Связанные данные F-P0C2: upload.distribution.* несут renderer_component
    (DistributionCharts.tsx#…), navigator-записи того же reusable-рендерера —
    нет (recharts живёт в дочернем компоненте, file-level scan это скрывает)."""
    reg = S.load_registry()
    for vid in ("navigator.upload.distribution.scatter", "navigator.upload.distribution.histogram"):
        s = next(x for x in reg["sites"] if x["view_id"] == vid)
        assert s.get("renderer_component"), f"F-P0C2: {vid} без renderer_component"


# ── F-P0C3: forecasting comparison/sensitivity ветки без записей ─────


def test_f_p0c3_forecast_comparison_view_registered():
    """TsAnalysisForecasting рендерит блок «Наложение прогнозов»
    (data-testid="comparison-view", чипы реальных scientific runs
    model_name·horizon); spec §5 включает comparisons в обязательный
    охват Прогнозирования. Записи в реестре нет."""
    src = (REPO / "packages" / "ui" / "components" / "TsAnalysisForecasting.tsx").read_text(encoding="utf-8")
    assert 'data-testid="comparison-view"' in src, "претест: comparison-view исчез"
    reg = S.load_registry()
    assert any(s["view_id"] == "forecasting.forecast.comparison" for s in reg["sites"]), (
        "F-P0C3: forecasting.forecast.comparison не зарегистрирован"
    )


def test_f_p0c3_forecast_sensitivity_view_registered():
    """Блок «Веер чувствительности» (data-testid="sensitivity-view", чипы
    комбинаций param_space с точками) — научное представление артефакта
    FORECAST-1; записи в реестре нет."""
    src = (REPO / "packages" / "ui" / "components" / "TsAnalysisForecasting.tsx").read_text(encoding="utf-8")
    assert 'data-testid="sensitivity-view"' in src, "претест: sensitivity-view исчез"
    reg = S.load_registry()
    assert any(s["view_id"] == "forecasting.forecast.sensitivity" for s in reg["sites"]), (
        "F-P0C3: forecasting.forecast.sensitivity не зарегистрирован"
    )


# ── F-P0C4: остановка Навигатора «preview» классифицирована неверно ──


def test_f_p0c4_navigator_preview_stop_registered_consistently():
    """Остановка Навигатора «Автопревью и типы колонок» (navigator-stops.ts
    id=preview) рендерит UploadAutoPreviewPipeline — статичную информационную
    схему научного пайплайна (ближайший родственник StructuralClassSchema,
    который зарегистрирован как upload.structure.schema). Однако файл попал
    под glob-исключение *Pipeline.tsx (класс controls, «мастера коррекций»),
    и ни stop upload.preview в каталоге, ни записи в реестре нет."""
    nav = S.parse_navigator_stops()
    assert "preview" in nav.get("upload", []), "претест: пункт preview исчез из navigator-stops"
    mapping = dict((f"{st}.{it}", comp) for st, it, comp in S.parse_navigator_item_mapping())
    assert mapping.get("upload.preview") == "UploadAutoPreviewPipeline", mapping.get("upload.preview")
    reg = S.load_registry()
    sites = S.load_registry()["sites"]
    catalog_stops = [s["stop_id"] for s in sites if s["module_id"] == "navigator"]
    assert "upload.preview" in catalog_stops, (
        "F-P0C4: остановка navigator upload.preview не представлена в реестре "
        "(UploadAutoPreviewPipeline под неверным glob-исключением controls)"
    )
