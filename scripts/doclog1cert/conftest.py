# scripts/doclog1cert/conftest.py
"""DOCLOG-1-CERT: изоляция оракульного корпуса сертификатора.

Оракулы на СВОИХ данных: идентификаторы RUN-D1C* (дизъюнктны
repo-корпусу RUN-D1A*), сессии d1cert-*, отпечатки c1f*/e7b*.
Каждый тест -- свой tmp_path/CISSTAT_DATA_DIR и сброс singleton-фабрик
(паритет паттерна repo-корпуса, но независимая реализация сертификатора).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.api import research_runs

RUN_PREFIX = "RUN-D1C"
SESSION_PREFIX = "d1cert"


@pytest.fixture(autouse=True)
def _cert_isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Полная изоляция среды каждого оракула: свой data-root, без
    внешних backend'ов; сброс всех singleton-фабрик до и после."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "certdata"))
    for env_var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_STORAGE_MODE",
    ):
        monkeypatch.delenv(env_var, raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()

    def _reset_artifact_factories() -> None:
        """Сброс фабрик DOCLOG-1 (на родителе fb26f6f модулей нет --
        сбрасывать нечего; это НЕ ослабляет RED: он приходит из
        самих оракулов)."""
        try:
            from apps.api import artifact_store
        except ImportError:  # родительская база: контур отсутствует
            return
        artifact_store.reset_artifact_registry_for_testing()
        artifact_store.reset_artifact_object_store_for_testing()

    from apps.api.session_store import reset_session_store_for_testing

    _reset_artifact_factories()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    _reset_artifact_factories()
    reset_session_store_for_testing()


@pytest.fixture()
def cert_client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client
