# scripts/pgv03cert/conftest.py
"""Корпус независимой сертификации PGV-03 «Producer adapters».

ПРИНЦИПЫ (метод DOCLOG-7/8/9-CERT, PGV-00/01/02-CERT без послаблений):
  * оракулы на СВОИХ данных -- namespace дизъюнктен repo и другим
    сертификаторам (RUN-P3C*, p3cert-*, ctx-p3cert-*, subj-p3c*);
  * изоляция КАЖДОГО теста: tmp CISSTAT_DATA_DIR + полный сброс
    singleton-фабрик (research_runs, artifact registry/object store,
    document registry, session store, visual response cache)
    + Memory-бекенды;
  * средовые переменные сессии снимаются (известный класс psycopg-DSN).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Средовые переменные, способные подменить бекенды (psycopg-DSN класс).
_ENV_VARS_TO_CLEAR = (
    "DATABASE_URL",
    "CISSTAT_RUNS_BACKEND",
    "CISSTAT_IDENTITY_MODE",
    "CISSTAT_API_KEYS",
    "CISSTAT_ARTIFACTS_BACKEND",
)


@pytest.fixture(autouse=True)
def _p3cert_isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for var in _ENV_VARS_TO_CLEAR:
        monkeypatch.delenv(var, raising=False)

    from apps.api import research_runs
    from apps.api.artifact_store import (
        reset_artifact_object_store_for_testing,
        reset_artifact_registry_for_testing,
    )
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.visual_producers import (
        reset_visual_response_cache_for_testing,
    )

    def _reset_all() -> None:
        research_runs.reset_research_run_store_for_testing()
        reset_artifact_registry_for_testing()
        reset_artifact_object_store_for_testing()
        reset_document_registry_for_testing()
        reset_session_store_for_testing()
        reset_visual_response_cache_for_testing()

    _reset_all()
    # Единый сброс кэшей print-слоя (твины могут читаться из repo root).
    from apps.api.print_schema import reset_caches

    reset_caches()
    yield
    _reset_all()
    reset_caches()
