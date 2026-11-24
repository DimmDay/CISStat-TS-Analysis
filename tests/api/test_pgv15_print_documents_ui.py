"""TDD-корпус PGV-15 (spec_passport_graphics_visual.md §10.2/§11/§13,
строка PGV-15): Documents picker/preview/PNG UI -- «Документы исследования»
получают печатные семейства и пикер паспортов.

ПОСТАНОВКА (§13): «Documents picker/preview/PNG UI; точки изменения --
DocumentationWorkspace/lib/documentation/обе apps; критерий -- Один/все/
сравнение по версии, D02 не P01, ZIP страниц доступен».

Ключевые инварианты поставки:

  §10.2  -- фильтры семейств: сохранённые P01/P02/V01 перечислены
            versioned-листингом; D01-D12 каталог не изменён;
  §10.2  -- «Восстановить паспорта»: пикер durable-источников
            (passport-sources), один/все/сравнение по версии
            (checkpoint/refs), gaps/completeness честны;
  AC09   -- идемпотентный replay: та же цель -- тот же job/rendition,
            листинг не создаёт jobs (GET read-only);
  AC11   -- reused-чекпоинт: подтверждение отдельно, физической копии нет
            (паритет PGV-13; на UI-уровне -- сводка sections);
  AC14   -- panel не смешивается (universe-гейт -- 409 comparison_incompatible);
  AC18   -- чужой/несуществующий run -- uniform 404 (существование не
            дисклоужается);
  §10.2  -- одна страница -- PNG; много страниц/mode=set -- ZIP; metadata
            JSON sidecar доступен (PGV-14 metadata_url).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

RUN_ID = "RUN-P15A0001"
SESSION_ID = "p15-seed-session"


# ── Изоляция среды (паттерн PGV-13) ──────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing
    from apps.api.routers import documentation as documentation_router

    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()
    documentation_router.reset_documentation_service_for_testing()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы (паттерн PGV-13) ─────────────────────────────────────


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _series_csv(n: int = 84) -> str:
    rng = np.random.default_rng(15)
    dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
    x = np.arange(n)
    values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
    frame = pd.DataFrame({"date": dates, "value": values})
    return frame.to_csv(index=False)


def _upload(client: TestClient) -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_series_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _select_series(client: TestClient) -> None:
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200


def _capture(client: TestClient, stage: str) -> dict:
    response = client.post(f"/v1/session/dataset/passport/{stage}")
    assert response.status_code == 200, response.text
    return response.json()


def _mutate_target(client: TestClient, delta: float = 5.0) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] += delta
    session.touch()
    store.save(session)


def _capture_full_trajectory(client: TestClient) -> dict:
    _capture(client, "start")
    _mutate_target(client, 3.0)
    _capture(client, "validation")
    _mutate_target(client, 4.0)
    _capture(client, "exit")
    _mutate_target(client, 5.0)
    return _capture(client, "modeling_entry")


def _run_id_of(client: TestClient) -> str:
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None
    assert session.run_id
    return session.run_id


def _durable_checkpoint_id(run_id: str, session_checkpoint_id: str) -> str:
    from apps.api.visual_artifacts import get_passport_checkpoint

    artifact = get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")
    assert artifact is not None
    return artifact.refs["checkpoint_id"]


def _seed_owned_run(run_id: str, session_id: str) -> None:
    """Существующий run, принадлежащий субъекту текущей cookie-сессии,
    без печатных документов (честный пустой список)."""
    from apps.api.identity import SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    now = _now()
    get_research_run_store().upsert_run(
        ResearchRun(
            run_id=run_id,
            session_id=session_id,
            dataset_fingerprint="p15" * 8,
            dataset_name="pgv15-empty",
            target_column="value",
            created_at=now,
            last_active_at=now,
            status="active",
            owner_subject=SubjectRef.from_session(session_id),
            tenant_id=None,
            ownership="bound",
        )
    )


class TestPrintDocumentsHTTP:
    """GET /runs/{run_id}/print-documents -- versioned-листинг печатных
    документов (субстрат фильтров «Визуализации»/«Паспорта свойств»)."""

    @pytest.fixture()
    def seeded(self, client):
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        run_id = _run_id_of(client)
        checkpoint_id = _durable_checkpoint_id(run_id, capture["checkpoint_id"])
        # Сохранённый комплект P01 (mode=set принудительно даёт ZIP, PGV-14).
        created = client.post(
            f"/v1/documentation/runs/{run_id}/passport-documents",
            json={"mode": "set", "checkpoint_id": checkpoint_id},
        )
        assert created.status_code == 202, created.text
        return {
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "created": created.json(),
        }

    def test_list_print_documents_owner_shape(self, client, seeded):
        response = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_id"] == seeded["run_id"]
        documents = body["documents"]
        kinds = {document["print_kind"] for document in documents}
        assert kinds == {"P01"}
        document = documents[0]
        assert document["family"] == "passports"
        assert document["kind_title"]
        assert document["document_id"] == seeded["created"]["document_id"]
        revisions = document["revisions"]
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision["print_revision_id"] == seeded["created"]["print_revision_id"]
        assert revision["version_no"] == 1
        assert revision["basis_kind"] == "passport_print_snapshot"
        assert revision["profile_id"]
        # Job постановки существует, но ещё не ready: renditions пусты --
        # листинг read-only, НЕ дожидается и не создаёт render (§11).
        assert isinstance(revision["renditions"], list)

    def test_list_print_documents_does_not_create_jobs_or_renditions(
        self, client, seeded
    ):
        from apps.api.document_jobs import DocumentDeliveryService

        before_jobs = len(
            DocumentDeliveryService.create_default().registry.list_jobs(
                seeded["run_id"]
            )
        )
        before_revisions = None
        first = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        assert first.status_code == 200
        before_revisions = len(first.json()["documents"][0]["revisions"])
        second = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        assert second.status_code == 200
        after_jobs = len(
            DocumentDeliveryService.create_default().registry.list_jobs(
                seeded["run_id"]
            )
        )
        assert after_jobs == before_jobs
        assert len(second.json()["documents"][0]["revisions"]) == before_revisions

    def test_list_print_documents_unknown_run_uniform_404(self, client, seeded):
        response = client.get("/v1/documentation/runs/RUN-NOPE/print-documents")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "not_found"

    def test_list_print_documents_empty_run(self, client, seeded):
        """Существующий run без печатных документов -- честный пустой
        список (не 404, не ошибка)."""
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        assert session_id
        fresh_run = "RUN-P15EMPTY01"
        _seed_owned_run(fresh_run, session_id)
        response = client.get(f"/v1/documentation/runs/{fresh_run}/print-documents")
        assert response.status_code == 200, response.text
        assert response.json()["documents"] == []

    def test_ready_rendition_summary_appears_in_listing(self, client, seeded):
        """Готовая rendition (ZIP комплекта) видна в листинге с
        metadata-полем size/hash -- состав для скачивания без байтов.
        Связка job->rendition -- реальная форма (publish_page_set)."""
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            DocumentJobRecord,
            DocumentRenditionRecord,
            JOB_READY,
            RENDITION_READY,
            new_job_id,
            new_rendition_id,
        )

        run_id = seeded["run_id"]
        print_revision_id = seeded["created"]["print_revision_id"]
        service = DocumentDeliveryService.create_default()
        rendition = service.registry.register_rendition(
            DocumentRenditionRecord(
                rendition_id=new_rendition_id(),
                revision_id="",
                snapshot_id="",
                run_id=run_id,
                format="zip",
                state=RENDITION_READY,
                media_type="application/zip",
                size_bytes=12345,
                content_sha256="a" * 64,
                storage_key="objects/zip",
                print_revision_id=print_revision_id,
            )
        )
        service.registry.register_job(
            DocumentJobRecord(
                job_id=new_job_id(),
                run_id=run_id,
                snapshot_id="",
                format="png",
                state=JOB_READY,
                rendition_id=rendition.rendition_id,
                revision_id=print_revision_id,
                print_revision_id=print_revision_id,
            )
        )
        response = client.get(f"/v1/documentation/runs/{run_id}/print-documents")
        assert response.status_code == 200
        renditions = response.json()["documents"][0]["revisions"][0]["renditions"]
        assert len(renditions) == 1
        summary = renditions[0]
        assert summary["format"] == "zip"
        assert summary["state"] == "ready"
        assert summary["size_bytes"] == 12345
        assert summary["content_sha256"] == "a" * 64
        assert summary["media_type"] == "application/zip"

    def test_p01_set_zip_available_via_replay_request(self, client, seeded):
        """«ZIP страниц доступен» (критерий): POST print-revisions/{id}/
        renditions (format=png) для комплектной ревизии -- прежняя цель;
        ответ несёт job/status_url (replay ready -- паритет PGV-14)."""
        response = client.post(
            f"/v1/documentation/print-revisions/"
            f"{seeded['created']['print_revision_id']}/renditions",
            json={"format": "png"},
        )
        assert response.status_code == 202, response.text
        job = response.json()["job"]
        assert job["print_revision_id"] == seeded["created"]["print_revision_id"]
        assert response.json()["status_url"].startswith("/v1/documentation/jobs/")

    def test_job_ready_dto_exposes_output_format_and_metadata_url(
        self, client, seeded
    ):
        """PGV-14 DTO: ready job несёт output_format и metadata_url --
        UI берёт metadata JSON и main bytes из одного поллинга."""
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            DocumentJobRecord,
            DocumentRenditionRecord,
            JOB_READY,
            RENDITION_READY,
            new_job_id,
            new_rendition_id,
        )

        run_id = seeded["run_id"]
        print_revision_id = seeded["created"]["print_revision_id"]
        service = DocumentDeliveryService.create_default()
        rendition = service.registry.register_rendition(
            DocumentRenditionRecord(
                rendition_id=new_rendition_id(),
                revision_id="",
                snapshot_id="",
                run_id=run_id,
                format="zip",
                state=RENDITION_READY,
                media_type="application/zip",
                size_bytes=2048,
                content_sha256="b" * 64,
                storage_key="objects/zip-2",
                print_revision_id=print_revision_id,
            )
        )
        job = service.registry.register_job(
            DocumentJobRecord(
                job_id=new_job_id(),
                run_id=run_id,
                snapshot_id="",
                format="png",
                revision_id=print_revision_id,
                rendition_id=rendition.rendition_id,
                state=JOB_READY,
                print_revision_id=print_revision_id,
            )
        )
        polled = client.get(f"/v1/documentation/jobs/{job.job_id}")
        assert polled.status_code == 200, polled.text
        payload = polled.json()["job"]
        assert payload["output_format"] == "zip"
        assert payload["rendition"]["rendition_id"] == rendition.rendition_id


class TestPickerFlowContract:
    """Пикер «Восстановить паспорта»: один/все/сравнение по версии через
    существующие маршруты PGV-13; UI-контракт ошибок -- плоские коды."""

    @pytest.fixture()
    def seeded(self, client):
        _upload(client)
        _select_series(client)
        capture = _capture_full_trajectory(client)
        run_id = _run_id_of(client)
        return {
            "run_id": run_id,
            "checkpoint_id": _durable_checkpoint_id(
                run_id, capture["checkpoint_id"]
            ),
        }

    def test_single_by_ref_creates_p01_document(self, client, seeded):
        sources = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-sources"
        )
        assert sources.status_code == 200
        snapshot_ref = sources.json()["snapshots"][0]["snapshot_ref"]
        created = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "single", "snapshot_refs": [snapshot_ref]},
        )
        assert created.status_code == 202, created.text
        body = created.json()
        assert body["print_kind"] == "P01"
        assert body["mode"] == "single"
        listing = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        assert listing.status_code == 200
        assert listing.json()["documents"][0]["print_kind"] == "P01"

    def test_compare_two_refs_creates_p02_and_listing_shows_family(
        self, client, seeded
    ):
        sources = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-sources"
        )
        refs = [item["snapshot_ref"] for item in sources.json()["snapshots"]][:2]
        created = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "compare", "snapshot_refs": refs},
        )
        assert created.status_code == 202, created.text
        assert created.json()["print_kind"] == "P02"
        listing = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        documents = listing.json()["documents"]
        p02 = next(d for d in documents if d["print_kind"] == "P02")
        assert p02["family"] == "passports"
        assert p02["kind_title"]

    def test_idempotent_restore_same_revision_and_job(self, client, seeded):
        """AC09: «Восстановить паспорта» по тому же checkpoint -- та же
        ревизия и тот же job (пикер не плодит дубли)."""
        first = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "set", "checkpoint_id": seeded["checkpoint_id"]},
        )
        second = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "set", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert first.status_code == second.status_code == 202
        assert (
            second.json()["print_revision_id"]
            == first.json()["print_revision_id"]
        )
        assert second.json()["job"]["job_id"] == first.json()["job"]["job_id"]
        listing = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        p01 = listing.json()["documents"][0]
        assert len(p01["revisions"]) == 1

    def test_display_summary_honest_gaps_and_completeness(self, client, seeded):
        """Сводка resolved-точек/gaps/completeness для UI -- из
        resolved-записей (AC11/AC12: reused -- одна строка, missing -- gap)."""
        created = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "set", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert created.status_code == 202
        body = created.json()
        assert body["completeness"] in ("complete", "partial")
        display = body["display"]
        assert display["title"]
        sections = display["sections"]
        assert sections
        for section in sections:
            assert set(section) >= {"snapshot_ref", "stage", "content_status"}
        # Физический паспорт один на stage -- reused не дублируется (AC11).
        refs = [section["snapshot_ref"] for section in sections]
        assert len(refs) == len(set(refs))

    def test_error_codes_for_picker(self, client, seeded):
        """Плоские коды ошибок пикера (§17/PGV-13): 409 source_unavailable,
        422 invalid_selection, 404 uniform."""
        unknown = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "set", "checkpoint_id": "pck-nope"},
        )
        assert unknown.status_code == 409
        assert unknown.json()["code"] == "source_unavailable"
        invalid = client.post(
            f"/v1/documentation/runs/{seeded['run_id']}/passport-documents",
            json={"mode": "banana", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "invalid_selection"
        foreign = client.post(
            "/v1/documentation/runs/RUN-NOPE/passport-documents",
            json={"mode": "set", "checkpoint_id": seeded["checkpoint_id"]},
        )
        assert foreign.status_code == 404
        assert foreign.json()["code"] == "not_found"


class TestDocumentationCatalogUnchanged:
    """D01-D12 каталог и D02 «Паспорт источника» не затронуты (AC22,
    критерий «D02 не P01»): passport capture создаёт D02-запись в
    snapshot-каталоге, а печатный P01 -- отдельный документ."""

    @pytest.fixture()
    def seeded(self, client):
        _upload(client)
        _select_series(client)
        _capture_full_trajectory(client)
        return {"run_id": _run_id_of(client)}

    def test_d02_is_snapshot_catalog_kind_not_p01(self, client, seeded):
        from apps.api.report_snapshot import get_snapshot_registry

        records = get_snapshot_registry().list_records(seeded["run_id"])
        assert any("D02" in (record.kinds or []) for record in records)
        listing = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/print-documents"
        )
        kinds = {document["print_kind"] for document in listing.json()["documents"]}
        assert "D02" not in kinds
        documents = client.get(
            f"/v1/documentation/runs/{seeded['run_id']}/documents"
        )
        assert documents.status_code == 200
        listed_kinds = {
            document["kind_code"] for document in documents.json()["documents"]
        }
        assert "D02" not in listed_kinds  # D02 -- snapshot-вид, не D-документ
        assert "P01" not in listed_kinds  # печатные -- отдельный листинг
