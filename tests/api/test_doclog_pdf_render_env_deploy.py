# tests/api/test_doclog_pdf_render_env_deploy.py
"""DOCLOG-PDF-RENDER-DEPLOY-2 (2026-10-27): полная паритет-сетка
«зависимости рендера ↔ деплой-образ» поверх DOCLOG-PDF-FONT-DEPLOY-1.

Постановка тимлида: сценарий «Загрузка» -> «План исследования» -> PDF
не работает -- render_dependency_unavailable. Статус: фикс шрифта
(DEPLOY-1) в дереве, но отказ у тимлида сохраняется => работающий
контейнер собран ДО фикса (stale-образ), а аудит класса отказа нашёл
латентные разрывы ТОГО ЖЕ класса, которые сработают следующими:

  pdf     -- TTF allowlist (fonts-dejavu-core, DEPLOY-1) + reportlab;
  png     -- Pillow (PIL) НЕ объявлен в apps/api/requirements.txt;
  pdfa    -- Pillow/ImageCms (littlecms, OutputIntent) и pypdf
             (PDF/A-1b маркеры) НЕ объявлены;
  parquet -- pyarrow объявлен (эталон формулировки F14).

Урок F14 («не полагаться на недоказанную установку») распространяется
на ВСЕ зависимости тяжёлых рендеров, тремя слоями:

1. requirements.txt объявляет pillow/pypdf явно (сейчас -- недоказанная
   установка: в песочнице пакеты есть, в slim-образе -- НЕТ);
2. сборка образа исполняет НАСТОЯЩИЙ render_snapshot_pdf (executable
   guard -- расширение font-guard'а DEPLOY-1: без рабочего PDF-рендера
   образ не собирается);
3. /health/ops несёт facts-only блок render_dependencies (peek-семантика)
   -- операционная видимость: тимлид видит на ЖИВОМ контейнере, какие
   зависимости рендера отсутствуют, БЕЗ shell-доступа; stale-образ с
   отсутствующим шрифтом диагностируется до первого клика аналитика.

Сюит НЕ требует docker: Dockerfile/requirements проверяются парсингом
текста (паттерн test_docker_image_layout.py / DEPLOY-1 /
DOCLOG-PDF-FONT-DEPLOY-1).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"
REQUIREMENTS = REPO_ROOT / "apps" / "api" / "requirements.txt"

TASK_MARKER = "DOCLOG-PDF-RENDER-DEPLOY-2"


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _requirements_text() -> str:
    return REQUIREMENTS.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════
# Слой 1: requirements.txt объявляет ВСЕ зависимости тяжёлых рендеров
# ═════════════════════════════════════════════════════════════════════


class TestRequirementsDeclareRenderDependencies:
    """Урок F14: зависимость, не объявленная в requirements, в образе
    НЕ существует независимо от песочницы разработчика."""

    @pytest.mark.parametrize(
        ("package", "consumer"),
        [
            ("Pillow", "render_snapshot_png"),
            ("Pillow", "ImageCms"),
            ("pypdf", "_pdfa_postprocess"),
        ],
    )
    def test_requirements_declare_package(self, package: str, consumer: str):
        """Pillow и pypdf объявлены в apps/api/requirements.txt с
        комментарием потребителя (стиль файла: каждая строка несёт
        обоснование -- см. reportlab/pyarrow DOCLOG-5)."""
        text = _requirements_text()
        declaration = re.search(
            rf"^{re.escape(package)}>=\S+[^\n]*{re.escape(consumer)}",
            text,
            re.MULTILINE,
        )
        assert (
            declaration is not None
        ), f"apps/api/requirements.txt: {package} (нужен {consumer}) не объявлен \
-- slim-образ собирается БЕЗ НЕГО, а песочница разработчика маскирует \
отсутствие (урок F14); см. {TASK_MARKER}"

    def test_requirements_comment_marks_task(self):
        """Блок зависимостей рендера снабжён маркером задачи (регламент
        файла: нестандартные/уточнённые зависимости комментируются)."""
        assert (
            TASK_MARKER in _requirements_text()
        ), f"apps/api/requirements.txt: нет маркера {TASK_MARKER} -- \
регламент файла требует комментировать блок (см. DOCLOG-5, UPLOAD-DB-4)"


# ═════════════════════════════════════════════════════════════════════
# Слой 2: executable guard -- сборка образа исполняет настоящий PDF
# ═════════════════════════════════════════════════════════════════════


class TestDockerfileExecutableRenderGuard:
    """DEPLOY-1 философия, расширение font-guard'а DEPLOY-1: образ
    обязан ДОКАЗАТЬ способность собрать PDF временем сборки."""

    def test_dockerfile_renders_real_pdf_at_build(self):
        """RUN python -c исполняет render_snapshot_pdf на минимальном
        снимке и проверяет %PDF- подпись -- font-guard проверял только
        ФС (файл шрифта), но НЕ способность образа собрать PDF
        (reportlab/регистрация TTF/сам рендер оставались
        недоказанными)."""
        text = _dockerfile_text()
        guard = re.search(
            r"python -c [\"'].*?render_snapshot_pdf.*?%PDF-",
            text,
            re.DOTALL,
        )
        assert (
            guard is not None
        ), f"apps/api/Dockerfile: нет build-time executable-guard'а \
render_snapshot_pdf -- образ может собраться без рабочего PDF-рендера \
(font-guard DEPLOY-1 проверял только наличие файла шрифта); см. {TASK_MARKER}"

    def test_dockerfile_import_checks_pillow_pypdf(self):
        """Слой pip-проверок образа содержит явный import PIL/pypdf
        (тот же стиль, что redis/psycopg/db-track проверки) -- без него
        недостающий пакет всплывает только в runtime."""
        text = _dockerfile_text()
        check = re.search(
            r"python -c [\"']import PIL, pypdf[;\"']",
            text,
        )
        assert (
            check is not None
        ), f"apps/api/Dockerfile: нет build-time проверки импорта \
PIL/pypdf -- png/pdfa-рендеры в образе недоказаны (стиль файла: redis/\
psycopg/db-track проверяются явным import); см. {TASK_MARKER}"

    def test_dockerfile_references_task_marker(self):
        """Guard'ы снабжены комментарием задачи (регламент файла)."""
        assert (
            TASK_MARKER in _dockerfile_text()
        ), f"apps/api/Dockerfile: нет маркера {TASK_MARKER}"


# ═════════════════════════════════════════════════════════════════════
# Слой 3: runtime-видимость -- render_dependencies_status + /health/ops
# ═════════════════════════════════════════════════════════════════════


def _expected_module_ok(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class TestRenderDependenciesStatus:
    """render_dependencies_status(): facts-only статус зависимостей
    тяжёлых рендеров (peek-семантика: только ФС allowlist и импорты)."""

    def test_status_keys_and_self_consistency(self):
        from apps.api.document_renditions import (
            _PDF_FONT_CANDIDATES,
            render_dependencies_status,
        )

        status = render_dependencies_status()
        assert set(status) == {
            "pdf_font",
            "reportlab",
            "pillow",
            "pypdf",
            "pyarrow",
        }
        # pdf_font: самосогласованность с allowlist-резолвером.
        font = status["pdf_font"]
        try:
            _path, name = None, None
            for path, candidate_name, _bold in _PDF_FONT_CANDIDATES:
                import os

                if os.path.isfile(path):
                    _path, name = path, candidate_name
                    break
        except Exception:  # pragma: no cover -- allowlist читается всегда
            name = None
        if name is not None:
            assert font["ok"] is True and font["name"] == name
        else:  # pragma: no cover -- песочница без шрифтов
            assert font["ok"] is False
        # python-зависимости: ok == реальная импортируемость (оракул
        # работает в ЛЮБОЙ среде: песочница, CI, slim-образ).
        for key, module in (
            ("reportlab", "reportlab"),
            ("pillow", "PIL"),
            ("pypdf", "pypdf"),
            ("pyarrow", "pyarrow"),
        ):
            assert status[key]["ok"] is _expected_module_ok(module), (
                f"render_dependencies[{key}].ok не согласован с "
                f"импортируемостью {module}"
            )

    def test_status_font_missing_env_model(self, monkeypatch):
        """Модель slim-образа без шрифтов: ok=False, кандидаты честно
        перечислены (диагностика указывает, ЧЕГО нет)."""
        from apps.api import document_renditions

        monkeypatch.setattr(document_renditions, "_PDF_FONT_CANDIDATES", ())
        status = document_renditions.render_dependencies_status()
        assert status["pdf_font"]["ok"] is False
        assert status["pdf_font"]["candidates"] == []
        assert status["pdf_font"]["name"] is None


@pytest.fixture()
def ops_client(monkeypatch, tmp_path):
    """Минимальный TestClient для /health/ops (паттерн корпуса DOCLOG):
    memory-бекенды, worker'ы выключены, изоляция каталога данных."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "render-env-data"))
    monkeypatch.setenv("CISSTAT_STORAGE_MODE", "advisory")
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SNAPSHOTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_ENABLED", "0")
    monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", "0")
    for name in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    from apps.api import artifact_store, document_jobs, research_runs
    from apps.api import report_snapshot, security_audit, session_store
    from apps.api.main import app

    session_store.reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    security_audit.reset_audit_for_testing()

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


class TestHealthOpsRenderDependencies:
    """/health/ops несёт render_dependencies (операционная видимость
    на ЖИВОМ контейнере -- у тимлида на Render нет shell-доступа)."""

    def test_health_ops_exposes_render_dependencies(self, ops_client):
        response = ops_client.get("/health/ops")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert "render_dependencies" in snapshot, (
            "/health/ops: нет блока render_dependencies -- отсутствие "
            "зависимостей рендера на живом контейнере невидимо "
            f"операционно; см. {TASK_MARKER}"
        )
        deps = snapshot["render_dependencies"]
        assert set(deps) >= {"pdf_font", "reportlab", "pillow", "pypdf", "pyarrow"}

    def test_health_ops_font_state_matches_filesystem(self, ops_client):
        """pdf_font в /health/ops согласован с ФС песочницы (шрифты
        установлены -> ok=True; stale-образ без шрифтов даёт ok=False
        и это ВИДНО операционно)."""
        snapshot = ops_client.get("/health/ops").json()
        font = snapshot["render_dependencies"]["pdf_font"]
        import os

        from apps.api.document_renditions import _PDF_FONT_CANDIDATES

        any_candidate = any(
            os.path.isfile(path) for path, _n, _b in _PDF_FONT_CANDIDATES
        )
        assert font["ok"] is any_candidate

    def test_health_ops_survives_font_missing(self, ops_client, monkeypatch):
        """Диагностика не роняет /health/ops (контракт: диагностика не
        роняет health): без шрифтов -- ok=False, 200 OK."""
        from apps.api import document_renditions

        monkeypatch.setattr(document_renditions, "_PDF_FONT_CANDIDATES", ())
        response = ops_client.get("/health/ops")
        assert response.status_code == 200
        assert response.json()["render_dependencies"]["pdf_font"]["ok"] is False
