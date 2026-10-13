# tests/api/test_progress_audit_8.py
"""
PROGR-AUDIT-8: raw restore и checkpoint metadata
(plan_progress_audit.md §14; spec_progress_audit.md F03/P05, H05;
контракт docs/progress_audit_contract.md I4 + аддендум v1.2-8A §22).

Задача на фундаменте AUDIT-1a → AUDIT-3 → AUDIT-5B (план §5: AUDIT-1/3/5B
предшественники закрыты). Состав карточки §14:

  1. Ответ restore ЯВНО сообщает mode=raw и новый data/context revision
     (до задачи: raw-восстановление -- загрузка ИСХОДНОГО файла,
     промежуточные DataFrame не восстанавливаются -- неотличимо от
     полного восстановления; потребитель не видит ни режима, ни новой
     ревизии, ни нового контекста).
  2. Старая current-validity НЕ используется для raw входа (P05/H05:
     после restore прежний data_types=done оставался «current» против
     СТАРОГО контекста run-метаданных, хотя вычислительный вход --
     raw). Исторические done видны (stale/historical), новый
     применимый расчёт появляется только с новым результатом.
  3. Восстановленная цель проверяется по raw данным и effective-target
     истории (AUDIT-1a); restore НЕ создаёт нового выбора.
  4. Чекпоинт связывает снимок с РЕАЛЬНЫМ current контекстом и
     watermark'ом ЕГО СОЗДАНИЯ: ссылка на произвольное старое event_id
     не означает «DataFrame в момент того события» (RED-карточка:
     чекпоинт с ранним event_id после поздней коррекции).
  5. DTO/UI показывают: есть ли снимок, к какому контексту он
     относится; raw restore снимок НЕ применяет (full snapshot replay
     -- отдельный контракт, сознательно НЕ реализован).
  6. Исходный raw файл не меняется; исторические факты не удаляются
     (append-only ledger).

RED-сценарии карточки §14: P05; исправленная цель/clear перед restore;
checkpoint с ранним event_id после поздней коррекции; отсутствующий
raw/файл; snapshot absent; cap>1000; restore на новую cookie без
нового choice.

Границы (план §14): full snapshot replay НЕ реализуется; применение
снимков чекпоинтов -- отдельный контракт; история run продолжается,
cookie меняется (§5.3); легаси-чекпоинты без метаданных читаются с
честным отсутствием (§3.7, N-3).
"""
from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from app.core.pipeline_graph import STAGE_NODES
from apps.api import research_runs
from apps.api.main import app
from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
    SESSION_COOKIE_NAME,
)


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Изоляция КАЖДОГО теста: свои каталоги данных (файловый слой --
    restore перечитывает исходный файл; чекпоинты пишут снимки),
    чистые синглтоны, Memory-бэкенд (паттерн test_progress_audit_1a)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


client = TestClient(app)


# ── Harness (паттерн test_progress_audit_1a) ─────────────────────────

CSV_ONE_NUMERIC = (
    "date,rain\n"
    "2023-01-01,10.5\n"
    "2023-01-02,20.1\n"
    "2023-01-03,30.2\n"
    "2023-01-04,15.8\n"
)


def _upload_csv(csv: str = CSV_ONE_NUMERIC, name: str = "single.csv") -> dict:
    file = io.BytesIO(csv.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (name, file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _convert_to_string(column: str = "rain", apply: bool = True, http=None):
    poster = http or client
    return poster.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": column, "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": apply,
        },
    )


def _run_id() -> str:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    run_id = resp.json().get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе слоя 1"
    return run_id


def _run_meta(run_id: str) -> research_runs.ResearchRun:
    run = research_runs.get_research_run_store().get_run(run_id)
    assert run is not None, "запуск не найден в слое 2"
    return run


def _restore(run_id: str) -> dict:
    fresh = TestClient(app)
    resp = fresh.get(f"/v1/progress/runs/{run_id}/restore")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    data["_session_id"] = fresh.cookies.get(SESSION_COOKIE_NAME)
    return data


def _trace_with_cookie(session_id: str) -> dict:
    resp = client.get(
        "/v1/progress/trace", cookies={SESSION_COOKIE_NAME: session_id}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _node(trace: dict, stage: str, node_id: str) -> dict:
    nodes = [
        n for n in trace.get("nodes", [])
        if n.get("stage") == stage and n.get("node_id") == node_id
    ]
    assert nodes, f"узел {stage}/{node_id} отсутствует в проекции"
    return nodes[0]


def _checkpoint_post(run_id: str, event_id: str, *, http=None) -> dict:
    poster = http or client
    resp = poster.post(
        f"/v1/progress/runs/{run_id}/checkpoints",
        json={"event_id": event_id, "label": "точка аудита"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["checkpoint"]


def _first_event_id(run_id: str) -> str:
    store = research_runs.get_research_run_store()
    events = store.list_events(run_id)
    assert events, "ledger пуст"
    return events[0].event_id


def _cookie_client(session_id: str) -> TestClient:
    """Клиент с cookie указанной сессии (восстановленной и т.п.)."""
    fresh = TestClient(app)
    fresh.cookies.set(SESSION_COOKIE_NAME, session_id)
    return fresh


def _report_validation_map(
    run_id: str,
    context_id: str,
    report_id: str,
    *,
    http=None,
    fill: str = "done",
) -> dict:
    """Полная v2-карта Валидации (честный производитель фактов узлов
    стадии, паттерн AUDIT-2A): data_types=done сеется КЛИЕНТСКИМ
    наблюдением, не конвертацией (AUDIT-4: исход unknown статус
    convert-types не утверждает)."""
    poster = http or client
    checks = {node: fill for node in STAGE_NODES["validation"]}
    resp = poster.post(
        "/v1/progress/validation-checks",
        json={
            "checks": checks,
            "schema_version": 2,
            "run_id": run_id,
            "context_id": context_id,
            "report_id": report_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 1. Restore: mode=raw и новые ревизии (план §14 п.1) ──────────────


class TestRestoreRawSemantics:
    def test_restore_reports_mode_raw_and_new_revisions(self):
        """RED-карточка: ответ restore явно сообщает mode=raw, новую
        data_revision (raw -- 0) и новый context_id; context_changed
        честен (коррекция до restore сдвинула контекст)."""
        _upload_csv()
        run_id = _run_id()
        _convert_to_string("rain")
        old_context = _run_meta(run_id).context_id
        assert old_context, "до restore run-метаданные несут контекст"

        data = _restore(run_id)
        assert data["mode"] == "raw"
        assert data["data_revision"] == 0
        session = get_session_store().get(data["_session_id"])
        assert data["context_id"] == session.current_context_id()
        assert data["context_changed"] is True
        # Новый контекст не равен прежнему (raw -- другой вычислительный
        # вход, спека §8.2).
        assert data["context_id"] != old_context

    def test_restore_unmutated_run_continues_same_context(self):
        """Restore запуска БЕЗ мутаций: компоненты контекста совпадают
        (детерминизм uuid5, I3) -- context_changed=False, тот же
        context_id; история продолжается, а не «новое исследование»."""
        _upload_csv()
        run_id = _run_id()
        old_context = _run_meta(run_id).context_id

        data = _restore(run_id)
        assert data["mode"] == "raw"
        assert data["context_changed"] is False
        assert data["context_id"] == old_context

    def test_run_metadata_follows_restored_context(self):
        """Run-метаданные после restore несут НОВЫЙ контекст/ревизию
        (raw): иначе проекция против старого context_id считает старые
        факты current (дефект H05)."""
        _upload_csv()
        run_id = _run_id()
        _convert_to_string("rain")
        old = _run_meta(run_id)
        assert old.data_revision == 1  # конвертация -- мутация контента

        data = _restore(run_id)
        session = get_session_store().get(data["_session_id"])
        run = _run_meta(run_id)
        assert run.context_id == session.current_context_id()
        assert run.context_id != old.context_id
        assert run.data_revision == 0  # raw
        assert run.data_digest == session.data_digest

    def test_p05_old_done_stale_new_input_current(self):
        """P05/H05 по исправленному ожиданию: data_types=done (карта
        Валидации, контекст A), мутация данных (string, ревизия 1),
        restore -- raw вход (новая ревизия/контекст); прежний done --
        validity=stale (историческое достижение видно, не «current»);
        новый применимый расчёт появляется с новым фактом НОВОГО
        контекста (карта от восстановленной сессии)."""
        _upload_csv()
        run_id = _run_id()
        old_context = _run_meta(run_id).context_id
        assert old_context
        report = _report_validation_map(run_id, old_context, "rep-audit8-a")
        assert report.get("mode") != "legacy"

        convert = _convert_to_string("rain")
        assert convert.status_code == 200, convert.text

        data = _restore(run_id)
        trace = _trace_with_cookie(data["_session_id"])
        node = _node(trace, "validation", "data_types")
        # Историческое достижение видно, но не «current» (I4).
        assert node["status"] == "done"
        assert node["validity"] == "stale"

        # Новый расчёт на новом входе -- новый текущий факт: карта
        # Валидации от восстановленной сессии (контекст C, гейт 2A
        # против обновлённых run-метаданных проходит).
        new_context = data["context_id"]
        assert new_context
        _report_validation_map(
            run_id, new_context, "rep-audit8-b",
            http=_cookie_client(data["_session_id"]),
        )
        trace_after = _trace_with_cookie(data["_session_id"])
        node_after = _node(trace_after, "validation", "data_types")
        assert node_after["validity"] == "current"

    def test_cleared_target_before_restore_context_honest(self):
        """RED-карточка «исправленная цель/clear перед restore»: сброс
        цели до restore не воскресает из метаданных (AUDIT-1a) и
        контекст восстановления честно отражает отсутствие цели."""
        _upload_csv()
        run_id = _run_id()
        _convert_to_string("rain")  # конвертация строки сбрасывает цель
        assert _run_meta(run_id).target_column is None

        data = _restore(run_id)
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        session = get_session_store().get(data["_session_id"])
        components = session.current_context_components()
        assert components is not None
        assert components["target"] == ""

    def test_manual_choice_before_restore_reflected_in_context(self):
        """Ручной выбор до restore восстанавливается парой (AUDIT-1a) и
        отражается в контексте восстановления (вселенная «датасет +
        цель», AUDIT-3)."""
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200
        run_id = _run_id()
        choose = client.post("/v1/session/target-column", json={"column": "sales"})
        assert choose.status_code == 200

        data = _restore(run_id)
        assert data["target_column"] == "sales"
        assert data["target_column_source"] == "user"
        session = get_session_store().get(data["_session_id"])
        components = session.current_context_components()
        assert components is not None
        assert components["target"] == "sales"

    def test_restore_new_cookie_no_new_choice(self):
        """RED-карточка «restore на новую cookie без нового choice»:
        restore сеет только run_resumed; событий выбора/сброса нет."""
        _upload_csv()
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        types_before = [e.event_type for e in store.list_events(run_id)]

        data = _restore(run_id)
        types_after = [e.event_type for e in store.list_events(run_id)]
        # Append-only: ровно один новый факт -- run_resumed.
        assert types_after == types_before + ["run_resumed"]
        assert "target_column_changed" not in types_after[len(types_before):]
        assert "target_column_cleared" not in types_after[len(types_before):]

    def test_missing_raw_file_409(self):
        """RED-карточка «отсутствующий raw/файл»: файлового слоя нет --
        честный 409 (повторная загрузка), не 500 и не тихая деградация."""
        _upload_csv()
        run_id = _run_id()
        file_store = research_runs.get_dataset_file_store()
        for path in file_store.uploads_dir.glob("*"):
            path.unlink()
        fresh = TestClient(app)
        resp = fresh.get(f"/v1/progress/runs/{run_id}/restore")
        assert resp.status_code == 409

    def test_raw_file_bytes_unchanged_after_restore(self):
        """План §14 п.6: исходный raw файл НЕ меняется при restore."""
        _upload_csv()
        run_id = _run_id()
        file_store = research_runs.get_dataset_file_store()
        fingerprint = _run_meta(run_id).dataset_fingerprint
        before = hashlib.sha256(file_store.load(fingerprint).data).hexdigest()

        _restore(run_id)

        after = hashlib.sha256(file_store.load(fingerprint).data).hexdigest()
        assert after == before

    def test_restore_history_preserved_append_only(self):
        """План §14 п.6: исторические факты НЕ удаляются (ledger
        append-only; засев слоя 1 -- копия, не перемещение)."""
        _upload_csv()
        run_id = _run_id()
        _convert_to_string("rain")
        store = research_runs.get_research_run_store()
        before_ids = [e.event_id for e in store.list_events(run_id)]

        _restore(run_id)

        after_ids = [e.event_id for e in store.list_events(run_id)]
        assert after_ids[: len(before_ids)] == before_ids
        assert len(after_ids) == len(before_ids) + 1


# ── 2. Чекпоинт: metadata создания (план §14 п.4–5) ──────────────────


class TestCheckpointMetadata:
    def test_checkpoint_records_creation_context_and_watermark(self):
        """Чекпоинт связывает снимок с реальным current контекстом и
        watermark'ом создания (позиция durable-истории ДО факта
        checkpoint_saved)."""
        _upload_csv()
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        ledger_before = len(store.list_events(run_id))
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        expected_context = session.current_context_id()

        checkpoint = _checkpoint_post(run_id, _first_event_id(run_id))
        assert checkpoint["has_snapshot"] is True
        assert checkpoint["context_id"] == expected_context
        assert checkpoint["data_revision"] == 0  # raw-загрузка без мутаций
        assert checkpoint["watermark"] == ledger_before

    def test_checkpoint_early_event_after_late_correction(self):
        """RED-карточка: чекпоинт с РАННИМ event_id после ПОЗДНЕЙ
        коррекции. Снимок -- текущий DataFrame (после коррекции):
        metadata обязаны связывать его с ТЕКУЩИМ контекстом и текущей
        позицией истории, а не с моментом раннего события."""
        _upload_csv()
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        early_event_id = _first_event_id(run_id)
        early_context = _run_meta(run_id).context_id

        _convert_to_string("rain")  # поздняя коррекция: ревизия 1
        session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
        current_context = session.current_context_id()
        assert current_context != early_context

        # Позиция durable-истории ДО факта checkpoint_saved.
        ledger_before_checkpoint = len(store.list_events(run_id))

        checkpoint = _checkpoint_post(run_id, early_event_id)
        assert checkpoint["event_id"] == early_event_id  # ссылка сохранена
        # Но снимок -- момент СОЗДАНИЯ, не момент раннего события:
        assert checkpoint["context_id"] == current_context
        assert checkpoint["data_revision"] == 1
        assert checkpoint["watermark"] == ledger_before_checkpoint

    def test_checkpoint_foreign_session_snapshot_absent_honest(self):
        """RED-карточка «snapshot absent»: чужая сессия создаёт ссылку
        БЕЗ снимка (has_snapshot=False) и без контекстных метаданных
        (честное отсутствие); watermark durable-истории записывается --
        позиция не зависит от сессии."""
        _upload_csv()
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        ledger_before = len(store.list_events(run_id))

        foreign = TestClient(app)  # без cookie исследования
        checkpoint = _checkpoint_post(run_id, _first_event_id(run_id), http=foreign)
        assert checkpoint["has_snapshot"] is False
        assert checkpoint["context_id"] is None
        assert checkpoint["data_revision"] is None
        assert checkpoint["watermark"] == ledger_before

    def test_run_detail_includes_checkpoint_metadata(self):
        """DTO чтения (GET /runs/{run_id}) несёт metadata чекпоинта --
        потребитель видит, к какому контексту относится снимок."""
        _upload_csv()
        run_id = _run_id()
        _checkpoint_post(run_id, _first_event_id(run_id))

        resp = client.get(f"/v1/progress/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        checkpoints = resp.json()["checkpoints"]
        assert len(checkpoints) == 1
        assert checkpoints[0]["context_id"] is not None
        assert checkpoints[0]["watermark"] is not None

    def test_checkpoint_watermark_is_full_history_after_cap_restore(self):
        """RED-карточка «cap>1000»: restore сеет в слой 1 только хвост
        (cap 1000), но watermark чекпоинта, созданного ПОСЛЕ restore, --
        позиция ПОЛНОЙ durable-истории, а не усечённого хвоста."""
        _upload_csv()
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        # 1001 синтетический факт поверх загрузки (паттерн P11/H11 --
        # нагрузочный корпус; ledger/проекция не ограничены капом).
        from apps.api.trace_events import make_trace_event

        for i in range(1001):
            store.append_event(
                run_id,
                make_trace_event(
                    "mode_changed", stage="validation", node_id=None,
                    run_id=run_id, actor="system", modes={"k": str(i)},
                ),
            )

        expected_total = len(store.list_events(run_id))
        assert expected_total > 1000, "корпус обязан превысить cap слоя 1"

        data = _restore(run_id)
        assert data["events_total"] == expected_total
        assert data["events_restored"] == 1000  # cap слоя 1

        # +1 -- run_resumed, сеянный самим restore (append-only).
        ledger_total = len(store.list_events(run_id))
        assert ledger_total == expected_total + 1

        fresh_client = _cookie_client(data["_session_id"])
        resp = fresh_client.post(
            f"/v1/progress/runs/{run_id}/checkpoints",
            json={"event_id": _first_event_id(run_id)},
        )
        assert resp.status_code == 201, resp.text
        checkpoint = resp.json()["checkpoint"]
        # Watermark -- полная durable-история (не cap 1000).
        assert checkpoint["watermark"] == ledger_total
