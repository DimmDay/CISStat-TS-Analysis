# tests/api/test_doclog_pdf_render_env_classification.py
"""DOCLOG-PDF-RENDER-DEPLOY-2 (2026-10-27): честная классификация
отсутствующих зависимостей рендера (§18: детерминированная
отсутствующая зависимость -- render_dependency_unavailable, а не общий
render_failed с пустыми ретраями).

Эталон класса -- parquet-рендер: отсутствие движка -> честный
RenderDependencyError (document_renditions.py, §7 «отсутствие движка --
честный RenderDependencyError, не тихая подмена»). Тот же контракт
распространяется на:

  render_snapshot_png  -- `from PIL import ...` (Pillow);
  _pdfa_postprocess    -- `import pypdf` (PDF/A-1b маркеры).

До фикса raw ImportError классифицировался worker'ом как render_failed
(TRANSIENT_ERROR_CODES: render_failed -- ПЕРЕЗАПУСКАЕМЫЙ код): absent
пакет нельзя «поправить» ретраем -- очередь крутилась бы впустую.
Модель отсутствующего пакета: sys.modules[name] = None (import
поднимает ImportError; monkeypatch восстанавливает состояние).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from apps.api.report_snapshot import ReportSnapshot


def _minimal_snapshot() -> ReportSnapshot:
    return ReportSnapshot(
        snapshot_id="renv-guard-snap",
        research_run_id="RUN-RENV00001",
    )


class TestMissingDependencyClassification:
    def test_png_without_pillow_raises_render_dependency_error(
        self, monkeypatch
    ):
        """PNG без Pillow: RenderDependencyError('pil_unavailable: ...')
        вместо raw ImportError -> worker классифицирует
        render_dependency_unavailable (терминальная, без пустых
        ретраев)."""
        from apps.api.document_renditions import (
            RenderDependencyError,
            render_snapshot_png,
        )

        monkeypatch.setitem(sys.modules, "PIL", None)
        with pytest.raises(RenderDependencyError) as exc_info:
            render_snapshot_png(_minimal_snapshot())
        assert "pil_unavailable" in str(exc_info.value)
        assert "Pillow" in str(exc_info.value)

    def test_pdfa_without_pypdf_raises_render_dependency_error(
        self, monkeypatch
    ):
        """PDF/A без pypdf: RenderDependencyError('pypdf_unavailable:
        ...') вместо raw ImportError (та же честная граница
        зависимости, что parquet-движок)."""
        from apps.api.document_renditions import (
            RenderDependencyError,
            _pdfa_postprocess,
        )

        monkeypatch.setitem(sys.modules, "pypdf", None)
        profile = SimpleNamespace(
            title_prefix="", footer_text="", organization=""
        )
        with pytest.raises(RenderDependencyError) as exc_info:
            _pdfa_postprocess(
                b"%PDF-1.4\n%%EOF\n", _minimal_snapshot(), profile
            )
        assert "pypdf_unavailable" in str(exc_info.value)

    def test_parquet_missing_engine_is_the_reference_contract(self):
        """Пин эталона: parquet без движка -- RenderDependencyError
        (контракт §7); классификация png/pdfa обязана совпадать с ним,
        не с общим render_failed."""
        from apps.api.document_renditions import (
            RenderDependencyError,
            render_snapshot_parquet,
        )

        monkey_freeze = sys.modules.get("pyarrow", object())
        try:
            sys.modules["pyarrow"] = None  # модель отсутствия движка
            with pytest.raises(RenderDependencyError):
                render_snapshot_parquet(_minimal_snapshot())
        finally:
            if "pyarrow" in sys.modules:
                sys.modules["pyarrow"] = monkey_freeze
