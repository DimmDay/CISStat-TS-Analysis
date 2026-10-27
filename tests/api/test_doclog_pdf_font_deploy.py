# tests/api/test_doclog_pdf_font_deploy.py
"""DOCLOG-PDF-FONT-DEPLOY-1 (2026-10-27): регресс-тесты инцидента
«Собрать формат: PDF» -> «Ошибка (failed) (попытка 2)» в деплое
(Render, docker).

Root cause (воспроизведён scripts/doclog_pdf_repro/reproduce_pdf_failure.py):
PDF/PNG-рендер требует TTF-шрифт из allowlist (_PDF_FONT_CANDIDATES:
DejaVu/Liberation, AC16 -- чтение ФС рендером ограничено этим списком;
кириллица §7 требует встроенного TTF). Деплой-образ собирается из
python:3.12-slim (apps/api/Dockerfile), а slim-образы Debian НЕ содержат
системных шрифтов -> _resolve_font() честно падает
RenderDependencyError("font_unavailable") -> worker classify
render_dependency_unavailable (детерминированная, терминальная --
§18 очередь не крутится) -> «Ошибка (failed)»; повторный клик
пользователя создаёт НОВЫЙ job (attempt = len(prior_jobs)+1) --
наблюдаемое «(попытка 2)».

Слои защиты (философия DEPLOY-1: зависимость среды обязана падать НА
СБОРКЕ образа, а не в runtime у аналитика):

1. В образ устанавливается fonts-dejavu-core -- пакет Debian,
   предоставляющий ровно те пути, что стоят первыми в allowlist
   (/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf[.ttf bold]).
2. Сборка образа проверяет доступность allowlist-шрифта ВРЕМЕНЕМ СБОРКИ
   (python -c ... _resolve_font) -- без шрифта образ НЕ собирается.

Сюит НЕ требует docker: Dockerfile проверяется парсингом текста
(паттерн tests/api/test_docker_image_layout.py, DEPLOY-1).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


class TestDockerImageProvidesAllowlistFonts:
    """Образ деплоя обязан содержать шрифт allowlist (root cause)."""

    def test_dockerfile_installs_dejavu_fonts(self):
        """fonts-dejavu-core установлен apt-get'ом в образ деплоя.

        Пакет предоставляет /usr/share/fonts/truetype/dejavu/
        DejaVuSans.ttf + DejaVuSans-Bold.ttf -- первичные кандидаты
        allowlist; без него PDF/PNG-рендер в деплое терминально failed
        (render_dependency_unavailable), P0-форматы при этом работают --
        отказ выглядит как «только PDF сломан»."""
        text = _dockerfile_text()
        # apt-слой с fonts-dejavu-core (no-install-recommends -- стиль
        # файла: минимальные образы).
        apt_fonts = re.search(
            r"apt-get install[^\n]*\n(?:[^\n]*\\\n)*[^\n]*fonts-dejavu-core",
            text,
        )
        assert (
            apt_fonts is not None
        ), "apps/api/Dockerfile: нет apt-get установки fonts-dejavu-core -- \
PDF/PNG-рендер в деплое падает render_dependency_unavailable \
(font_unavailable: slim-образ без шрифтов); см. DOCLOG-PDF-FONT-DEPLOY-1"

    def test_dockerfile_build_time_font_guard(self):
        """Сборка образа проверяет allowlist-шрифт ВРЕМЕНЕМ СБОРКИ
        (python -c ... _resolve_font) -- DEPLOY-1 философия: без шрифта
        образ не собирается, а не молча выдаёт failed у аналитика."""
        text = _dockerfile_text()
        guard = re.search(
            r"python -c [\"']from apps\.api\.document_renditions import "
            r"_resolve_font",
            text,
        )
        assert (
            guard is not None
        ), "apps/api/Dockerfile: нет build-time проверки allowlist-шрифта \
(_resolve_font) -- зависимость среды всплывает только в runtime \
(нарушение философии DEPLOY-1 fail-closed); см. DOCLOG-PDF-FONT-DEPLOY-1"

    def test_font_allowlist_primary_matches_dejavu_package(self):
        """Контракт сопряжения код<->образ: первичный кандидат allowlist
        -- ровно те пути, что предоставляет fonts-dejavu-core. Смена
        пакета или allowlist без синхронизации ломает этот пин."""
        from apps.api.document_renditions import _PDF_FONT_CANDIDATES

        primary = _PDF_FONT_CANDIDATES[0]
        regular, name, bold = primary
        assert name == "DejaVuSans"
        assert regular == "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        assert bold == "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        # Порядок allowlist: DejaVu раньше Liberation (пакет образа
        # обязан закрывать первичного кандидата).
        assert _PDF_FONT_CANDIDATES[1][1] == "LiberationSans"

    def test_dockerfile_references_doclog_pdf_font_deploy_task(self):
        """Слой шрифтов и guard снабжены комментарием задачи -- при
        будущей переработке Dockerfile зависимость не выкинут молча
        (паттерн UPLOAD-DB-7/DEPLOY-1 комментариев в этом файле)."""
        text = _dockerfile_text()
        assert (
            "DOCLOG-PDF-FONT-DEPLOY-1" in text
        ), "apps/api/Dockerfile: слой fonts-dejavu-core без маркера задачи \
DOCLOG-PDF-FONT-DEPLOY-1 -- регламент файла требует комментировать \
нестандартные зависимости (см. UPLOAD-DB-7, DEPLOY-1)"
