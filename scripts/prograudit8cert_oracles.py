# scripts/prograudit8cert_oracles.py
# -*- coding: utf-8 -*-
"""СВОИ оракулы независимой сертификации PROGR-AUDIT-8-CERT.

Объект: коммит 2353e65 (PROGR-AUDIT-8 -- raw restore и checkpoint
metadata: ответ restore честно сообщает mode=raw и новые data/context
revision; run-метаданные следуют raw-входу P05/H05; чекпоинт связывает
снимок с реальным current контекстом и watermark'ом СОЗДАНИЯ; DTO/UI
показывают снимок/контекст/позицию и honest-пометку; неразрушительность).
Аудит на HEAD = 2353e65 (продуктовый код AUDIT-8 вошёл в сам 2353e65;
предыдущие сертификации 2A-CERT/2B-CERT продуктовый код restore/checkpoint
не меняли).

Принцип «оракулы на своих данных»: данные сертификатора ДИЗЪЮКТНЫ данным
оракула исполнителя (tests/api/test_progress_audit_8.py: CSV date/rain
4 строки 2023-01, report_id rep-audit8-*, метки «точка аудита»):
  * свои CSV-корпуса: сенсорный «day,sensor_a,sensor_b» 14 суток
    2024-03 (два числовых столбца, выброс 900 для cap-коррекции) и
    нагрузочный «ts,load» 9 суток 2024-07 (один числовой -- авто-цель);
  * своя вторая мутация контента: outlier-cap (класс коррекции
    отличный от convert-types исполнителя) + convert-types на ДРУГОЙ
    колонке/типе;
  * свои report_id (c8-rep-*), свои метки чекпоинтов (cert8-*),
    свой объём cap-корпуса (1002 факта против 1001);
  * свои наблюдательные методы: инъекция ЛЕГАСИ-строки чекпоинта в
    store (Memory) с последующим чтением через живой API; двойной
    restore с SHA-256 контролами; rename uploads_dir как способ
    изъятия raw-файла; сверка roundtrip POST/GET.

Канал проверки: самодостаточный EXIT-код (0 = все PASS).
Группы: ENV (свои корпуса), RAW (честность restore §22.1), CTX
(run-метаданные/P05/гейты §22.2), CHK (metadata создания §22.3),
DTO (§22.4), ND (неразрушительность §22.5).

Запуск: python scripts/prograudit8cert_oracles.py [--protocol PATH]
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Чистая изоляция окружения ДО импортов продукта.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

PROTOCOL_LINES: list[str] = []
FAILURES: list[str] = []
PASSES: int = 0


def _log(msg: str) -> None:
    print(msg)
    PROTOCOL_LINES.append(msg)


class OracleFail(AssertionError):
    """Честный отказ оракула (различим от неожиданного исключения)."""


def oracle(name: str):
    """Декоратор-харнесс: полная изоляция окружения на каждый оракул."""

    def wrap(fn):
        def run():
            global PASSES
            tmp = tempfile.mkdtemp(prefix="cert8-oracle-")
            os.environ["CISSTAT_DATA_DIR"] = tmp
            from apps.api import research_runs as rr
            from apps.api.session_store import (
                reset_session_store_for_testing,
            )

            rr.reset_research_run_store_for_testing()
            rr.reset_dataset_file_store_for_testing()
            reset_session_store_for_testing()
            try:
                fn()
            except OracleFail as exc:
                FAILURES.append(f"{name}: {exc}")
                _log(f"  FAIL {name}: {exc}")
            except Exception as exc:  # неожиданное исключение = FAIL
                FAILURES.append(f"{name}: UNEXPECTED {exc!r}")
                _log(f"  FAIL {name}: UNEXPECTED {exc!r}")
                traceback.print_exc()
            else:
                PASSES += 1
                _log(f"  ok   {name}")
            finally:
                rr.reset_research_run_store_for_testing()
                rr.reset_dataset_file_store_for_testing()
                reset_session_store_for_testing()

        run.__name__ = fn.__name__
        run._oracle_name = name
        return run

    return wrap


# ── СВОИ данные сертификатора ────────────────────────────────────────

# Сенсорный корпус: 14 суток 2024-03, два числовых столбца (авто-цель
# НЕ выбирается), в sensor_a -- выброс 900 для cap-коррекции.
_SENSOR_DAYS = [f"2024-03-{d:02d}" for d in range(1, 15)]
_SENSOR_A = [10.0 + i for i in range(14)]
_SENSOR_A[6] = 900.0  # выброс -- материал для outlier-cap коррекции
_SENSOR_B = [5.5 + (i % 4) * 1.25 for i in range(14)]
CSV_SENSOR = "day,sensor_a,sensor_b\n" + "".join(
    f"{d},{a},{b}\n" for d, a, b in zip(_SENSOR_DAYS, _SENSOR_A, _SENSOR_B)
)

# Нагрузочный корпус: 9 суток 2024-07, один числовой столбец
# (auto-цель load после загрузки).
CSV_LOAD = "ts,load\n" + "".join(
    f"2024-07-{d:02d},{100.0 + 3.7 * i:.2f}\n" for i, d in enumerate(range(1, 10))
)

from fastapi.testclient import TestClient  # noqa: E402

from app.core.pipeline_graph import STAGE_NODES  # noqa: E402
from apps.api import research_runs  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
)


# ── СВОИ наблюдательные методы ───────────────────────────────────────


def _client() -> TestClient:
    return TestClient(app)


def _upload(client: TestClient, csv: str, name: str) -> dict:
    r = client.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(csv.encode("utf-8")), "text/csv")},
    )
    assert r.status_code == 200, f"upload {name}: {r.status_code} {r.text}"
    return r.json()


def _run_id(client: TestClient) -> str:
    r = client.get("/v1/progress/trace")
    assert r.status_code == 200, r.text
    run_id = r.json().get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе слоя 1"
    return run_id


def _run_meta(run_id: str) -> research_runs.ResearchRun:
    run = research_runs.get_research_run_store().get_run(run_id)
    assert run is not None, f"запуск {run_id} не найден в слое 2"
    return run


def _outlier_cap(client: TestClient, column: str) -> dict:
    """Своя вторая мутация контента (класс коррекции выбросов):
    cap по IQR на своей колонке с выбросом."""
    r = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": [column], "strategy": "cap", "method": "iqr", "apply": True},
    )
    assert r.status_code == 200, f"outlier cap: {r.status_code} {r.text}"
    return r.json()


def _convert_string(client: TestClient, column: str) -> dict:
    """Мутация конвертации типа (на своей колонке, отличной от
    исполнителя)."""
    r = client.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": column, "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": True,
        },
    )
    assert r.status_code == 200, f"convert: {r.status_code} {r.text}"
    return r.json()


def _choose_target(client: TestClient, column: str) -> None:
    r = client.post("/v1/session/target-column", json={"column": column})
    assert r.status_code == 200, f"manual target: {r.status_code} {r.text}"


def _restore(run_id: str) -> dict:
    """Restore свежим клиентом (новая cookie) -- паттерн живого API."""
    fresh = TestClient(app)
    r = fresh.get(f"/v1/progress/runs/{run_id}/restore")
    assert r.status_code == 200, f"restore: {r.status_code} {r.text}"
    data = r.json()
    data["_session_id"] = fresh.cookies.get(SESSION_COOKIE_NAME)
    data["_client"] = fresh
    return data


def _raw_sha256(run_id: str) -> str:
    """SHA-256 исходного raw-файла из файлового слоя (свой контроль
    неразрушительности)."""
    fingerprint = _run_meta(run_id).dataset_fingerprint
    assert fingerprint, "у запуска нет fingerprint"
    blob = research_runs.get_dataset_file_store().load(fingerprint)
    return hashlib.sha256(blob.data).hexdigest()


def _ledger_ids(run_id: str) -> list[str]:
    return [
        e.event_id
        for e in research_runs.get_research_run_store().list_events(run_id)
    ]


def _ledger_len(run_id: str) -> int:
    return len(research_runs.get_research_run_store().list_events(run_id))


def _checkpoint_post(
    run_id: str, event_id: str, *, http: TestClient | None = None, label: str = ""
) -> dict:
    poster = http or TestClient(app)
    r = poster.post(
        f"/v1/progress/runs/{run_id}/checkpoints",
        json={"event_id": event_id, "label": label or "cert8-точка"},
    )
    assert r.status_code == 201, f"checkpoint POST: {r.status_code} {r.text}"
    return r.json()["checkpoint"]


def _report_validation_map(
    run_id: str, context_id: str, report_id: str, *, http: TestClient | None = None
) -> dict:
    """Полная v2-карта Валидации на СВОИХ report_id."""
    poster = http or TestClient(app)
    checks = {node: "done" for node in STAGE_NODES["validation"]}
    r = poster.post(
        "/v1/progress/validation-checks",
        json={
            "checks": checks,
            "schema_version": 2,
            "run_id": run_id,
            "context_id": context_id,
            "report_id": report_id,
        },
    )
    assert r.status_code == 200, f"validation map: {r.status_code} {r.text}"
    return r.json()


def _trace(client: TestClient) -> dict:
    r = client.get("/v1/progress/trace")
    assert r.status_code == 200, r.text
    return r.json()


def _node(trace: dict, stage: str, node_id: str) -> dict:
    nodes = [
        n for n in trace.get("nodes", [])
        if n.get("stage") == stage and n.get("node_id") == node_id
    ]
    assert nodes, f"узел {stage}/{node_id} отсутствует в проекции"
    return nodes[0]


# ── ENV: свои корпуса живы (контроль вселенной сертификатора) ────────


@oracle("ENV-1 свои корпуса, авто-цель, контекст существует")
def env1_oracle():
    c = _client()
    up = _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    assert up.get("name") == "cert8_sensor.csv", up
    run_id = _run_id(c)
    meta = _run_meta(run_id)
    assert meta.context_id, "контекст не вычислен для сенсорного корпуса"
    # Два числовых столбца -- авто-цель НЕ угадывается (F01, singleton).
    assert meta.target_column is None, meta.target_column

    c2 = _client()
    _upload(c2, CSV_LOAD, "cert8_load.csv")
    meta2 = _run_meta(_run_id(c2))
    # Один числовой столбец -- auto-выбор согласован (своя вселенная).
    assert meta2.target_column == "load", meta2.target_column
    assert meta2.target_column_source == "auto", meta2.target_column_source


# ── RAW: честность ответа restore (контракт §22.1) ───────────────────


@oracle("RAW-1 mode=raw, ревизия 0 и новый контекст после ДВУХ мутаций")
def raw1_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _choose_target(c, "sensor_b")          # ручной выбор (не мутация)
    _outlier_cap(c, "sensor_a")            # мутация 1: cap выброса
    _convert_string(c, "sensor_b")         # мутация 2: цель уходит в строку
    assert _run_meta(run_id).data_revision == 2, _run_meta(run_id).data_revision

    data = _restore(run_id)
    assert data["mode"] == "raw", data["mode"]
    assert data["data_revision"] == 0, data["data_revision"]
    session = get_session_store().get(data["_session_id"])
    assert data["context_id"] == session.current_context_id(), "context_id не от восстановленной сессии"
    assert data["context_changed"] is True, data["context_changed"]
    # Форма raw-датасета в ответе: 14 строк, 3 столбца (мутации контента
    # не имели права менять форму, restore вернул исходник).
    assert data["dataset"]["rows"] == 14, data["dataset"]
    assert data["dataset"]["columns"] == 3, data["dataset"]


@oracle("RAW-2 двойной restore немутированного запуска: I3 + append-only")
def raw2_oracle():
    c = _client()
    _upload(c, CSV_LOAD, "cert8_load.csv")
    run_id = _run_id(c)
    ctx_before = _run_meta(run_id).context_id

    types_before = [
        e.event_type
        for e in research_runs.get_research_run_store().list_events(run_id)
    ]

    first = _restore(run_id)
    assert first["mode"] == "raw" and first["context_changed"] is False, first
    assert first["context_id"] == ctx_before, "I3: контекст обязан продолжаться"

    second = _restore(run_id)
    assert second["mode"] == "raw", second["mode"]
    assert second["context_id"] == ctx_before, second["context_id"]
    assert second["context_changed"] is False, second["context_changed"]
    # Append-only: ровно +2 run_resumed, порядок сохранён.
    types_after = [
        e.event_type
        for e in research_runs.get_research_run_store().list_events(run_id)
    ]
    assert len(types_after) == len(types_before) + 2, types_after
    assert types_after[len(types_before):] == ["run_resumed", "run_resumed"], (
        types_after[len(types_before):]
    )
    # Cookie ротируется при каждом restore (разные сессии).
    assert first["_session_id"] != second["_session_id"], "cookie не ротируется"


@oracle("RAW-3 привязка run к новой сессии и восстановленная пара цели")
def raw3_oracle():
    c = _client()
    _upload(c, CSV_LOAD, "cert8_load.csv")
    run_id = _run_id(c)
    old_session = c.cookies.get(SESSION_COOKIE_NAME)

    data = _restore(run_id)
    meta = _run_meta(run_id)
    assert meta.status == "active", meta.status
    assert meta.session_id == data["_session_id"], meta.session_id
    assert data["_session_id"] != old_session, "cookie не сменился"
    # Историческая пара (auto, load) восстановлена редьюсером, а не
    # новым авто-выбором (v0.7-1A): источник -- auto из истории.
    assert data["target_column"] == "load", data["target_column"]
    assert data["target_column_source"] == "auto", data["target_column_source"]


# ── CTX: run-метаданные следуют raw-входу (контракт §22.2, P05/H05) ──


@oracle("CTX-1 run-метаданные = контекст/ревизия/дайджест raw-входа")
def ctx1_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _outlier_cap(c, "sensor_a")            # мутация до restore
    ctx_old = _run_meta(run_id).context_id

    data = _restore(run_id)
    session = get_session_store().get(data["_session_id"])
    meta = _run_meta(run_id)
    assert meta.context_id == session.current_context_id(), meta.context_id
    assert meta.context_id != ctx_old, "контекст не сместился после мутации"
    assert meta.data_revision == 0, meta.data_revision
    assert meta.data_digest == session.data_digest, "дайджест не от raw-входа"


@oracle("CTX-2 P05 на своих данных: сброс цели -- старый done stale, новый current")
def ctx2_oracle():
    # Своя вселенная P05: авто-цель load, карта в контексте A
    # (ревизия 0, target load), конвертация ЦЕЛИ в строку (сброс цели,
    # ревизия 1), restore -- raw (ревизия 0, цель НЕ воскресает).
    # Контекст восстановления (target="") != контекст карты A
    # (target="load") -- применимость старого done обязана быть stale.
    c = _client()
    _upload(c, CSV_LOAD, "cert8_load.csv")
    run_id = _run_id(c)
    ctx_a = _run_meta(run_id).context_id
    _report_validation_map(run_id, ctx_a, "c8-rep-p05a", http=c)

    _convert_string(c, "load")             # мутация цели: сброс, ревизия 1
    assert _run_meta(run_id).target_column is None, "сброс цели не зафиксирован"
    data = _restore(run_id)
    assert data["target_column"] is None, data["target_column"]
    assert data["context_changed"] is True, data["context_changed"]

    trace = _trace(data["_client"])
    node = _node(trace, "validation", "data_types")
    assert node["status"] == "done", node["status"]
    assert node["validity"] == "stale", node["validity"]

    _report_validation_map(
        run_id, data["context_id"], "c8-rep-p05b", http=data["_client"]
    )
    node_after = _node(_trace(data["_client"]), "validation", "data_types")
    assert node_after["validity"] == "current", node_after["validity"]


@oracle("CTX-2b пер-выбор цели: restore продолжает контекст, старая карта stale")
def ctx2b_oracle():
    # Своя форма: НИКАКИХ мутаций контента -- только смена пары цели
    # (sensor_b -> sensor_a). Контекст смещается сменой компоненты
    # target; restore продолжает контекст (context_changed=False,
    # I3), но старая карта из прежней вселенной обязана остаться stale.
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _choose_target(c, "sensor_b")
    ctx_a = _run_meta(run_id).context_id
    _report_validation_map(run_id, ctx_a, "c8-rep-rechoice-a", http=c)

    _choose_target(c, "sensor_a")          # смена цели: новая вселенная
    ctx_b = _run_meta(run_id).context_id
    assert ctx_b != ctx_a, "пер-выбор не сместил контекст"

    data = _restore(run_id)
    assert data["target_column"] == "sensor_a", data["target_column"]
    assert data["target_column_source"] == "user", data["target_column_source"]
    # Контекст продолжается: пара та же, мутаций не было (I3).
    assert data["context_id"] == ctx_b, data["context_id"]
    assert data["context_changed"] is False, data["context_changed"]

    node = _node(_trace(data["_client"]), "validation", "data_types")
    assert node["status"] == "done", node["status"]
    assert node["validity"] == "stale", node["validity"]

    _report_validation_map(
        run_id, data["context_id"], "c8-rep-rechoice-b", http=data["_client"]
    )
    node_after = _node(_trace(data["_client"]), "validation", "data_types")
    assert node_after["validity"] == "current", node_after["validity"]


@oracle("CTX-3 гейты карт после сдвига контекста: старый 409, новый 200")
def ctx3_oracle():
    c = _client()
    _upload(c, CSV_LOAD, "cert8_load.csv")
    run_id = _run_id(c)
    ctx_a = _run_meta(run_id).context_id
    _convert_string(c, "load")             # сброс цели: контекст сместился
    data = _restore(run_id)

    # Старый контекст отклонён ДО записи (P24/F04 -- гейт 2A против
    # ОБНОВЛЁННЫХ run-метаданных).
    checks = {node: "done" for node in STAGE_NODES["validation"]}
    stale = data["_client"].post(
        "/v1/progress/validation-checks",
        json={
            "checks": checks, "schema_version": 2,
            "run_id": run_id, "context_id": ctx_a,
            "report_id": "c8-rep-stale",
        },
    )
    assert stale.status_code == 409, stale.status_code

    fresh_ok = _report_validation_map(
        run_id, data["context_id"], "c8-rep-fresh", http=data["_client"]
    )
    assert fresh_ok.get("mode") != "legacy", fresh_ok


# ── CHK: metadata создания снимка (контракт §22.3) ───────────────────


@oracle("CHK-1 watermark = позиция ledger ДО факта checkpoint_saved")
def chk1_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    expected_wm = _ledger_len(run_id)
    session = get_session_store().get(c.cookies.get(SESSION_COOKIE_NAME))
    expected_ctx = session.current_context_id()
    first_event = research_runs.get_research_run_store().list_events(run_id)[0]

    cp = _checkpoint_post(run_id, first_event.event_id, http=c)
    assert cp["has_snapshot"] is True, cp
    assert cp["watermark"] == expected_wm, (cp["watermark"], expected_wm)
    assert cp["context_id"] == expected_ctx, cp["context_id"]
    assert cp["data_revision"] == 0, cp["data_revision"]
    # Позиция -- ДО факта: после POST в ledger появился checkpoint_saved,
    # и повторный подсчёт на 1 больше записанного watermark.
    assert _ledger_len(run_id) == expected_wm + 1, "checkpoint_saved не в ledger"


@oracle("CHK-2 ранний якорь после поздней коррекции: metadata СОЗДАНИЯ")
def chk2_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _choose_target(c, "sensor_b")
    early = research_runs.get_research_run_store().list_events(run_id)[0]

    _outlier_cap(c, "sensor_a")            # поздняя коррекция: ревизия 1
    session = get_session_store().get(c.cookies.get(SESSION_COOKIE_NAME))
    ctx_now = session.current_context_id()
    wm_now = _ledger_len(run_id)

    cp = _checkpoint_post(run_id, early.event_id, http=c)
    assert cp["event_id"] == early.event_id, "якорь потерян"
    # Снимок -- момент СОЗДАНИЯ, не момент раннего события:
    assert cp["context_id"] == ctx_now, (cp["context_id"], ctx_now)
    assert cp["data_revision"] == 1, cp["data_revision"]
    assert cp["watermark"] == wm_now, (cp["watermark"], wm_now)


@oracle("CHK-3 чужая сессия: ссылка без снимка и без контекста, позиция есть")
def chk3_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    expected_wm = _ledger_len(run_id)

    foreign = _client()  # без cookie исследования
    cp = _checkpoint_post(run_id, _ledger_ids(run_id)[0], http=foreign)
    assert cp["has_snapshot"] is False, cp
    assert cp["context_id"] is None, cp["context_id"]
    assert cp["data_revision"] is None, cp["data_revision"]
    assert cp["watermark"] == expected_wm, cp["watermark"]


@oracle("CHK-4 монотонность позиций: два чекпоинта подряд")
def chk4_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    events = research_runs.get_research_run_store().list_events(run_id)

    cp1 = _checkpoint_post(run_id, events[0].event_id, http=c, label="cert8-first")
    cp2 = _checkpoint_post(run_id, events[-1].event_id, http=c, label="cert8-second")
    assert cp2["watermark"] == cp1["watermark"] + 1, (
        cp1["watermark"], cp2["watermark"]
    )
    # Оба -- metadata своей сессии; контексты совпадают (мутаций между
    # ними не было), снимки у обоих.
    assert cp1["has_snapshot"] and cp2["has_snapshot"], (cp1, cp2)
    assert cp1["context_id"] == cp2["context_id"], "контекст поплыл без мутаций"
    assert cp1["checkpoint_id"] != cp2["checkpoint_id"], "id не различаются"


@oracle("CHK-5 cap: после restore watermark = ПОЛНАЯ позиция ledger")
def chk5_oracle():
    c = _client()
    _upload(c, CSV_LOAD, "cert8_load.csv")
    run_id = _run_id(c)
    from apps.api.trace_events import make_trace_event

    for i in range(1002):  # свой объём (у исполнителя 1001)
        research_runs.get_research_run_store().append_event(
            run_id,
            make_trace_event(
                "mode_changed", stage="validation", node_id=None,
                run_id=run_id, actor="system",
                modes={"step": f"c8-{i}"},
            ),
        )
    total_before = _ledger_len(run_id)
    assert total_before > 1000, "корпус обязан превысить cap слоя 1"

    data = _restore(run_id)
    assert data["events_restored"] == 1000, data["events_restored"]
    assert data["events_total"] == total_before, data["events_total"]

    # Чекпоинт от ВОССТАНОВЛЕННОЙ сессии: снимок есть, контекст raw,
    # позиция -- полная durable-история (total_before + run_resumed).
    cp = _checkpoint_post(
        run_id, _ledger_ids(run_id)[0], http=data["_client"]
    )
    assert cp["has_snapshot"] is True, cp
    assert cp["context_id"] == data["context_id"], cp["context_id"]
    assert cp["data_revision"] == 0, cp["data_revision"]
    assert cp["watermark"] == total_before + 1, (
        cp["watermark"], total_before
    )
    assert cp["watermark"] > 1000, "watermark привязан к cap слоя 1"


@oracle("CHK-7 сессия ЧУЖОГО запуска со своим датасетом: ссылка без снимка")
def chk7_oracle():
    # Эволюция кампании (CM-7): чужая сессия с cookieless-клиентом не
    # достигает пути снимка (dataframe пуст). Достижимая форма -- сессия
    # ДРУГОГО запуска со СВОИМ активным датасетом: её снимок/контекст не
    # имеют права атрибутироваться чужому запуску (§22.3: «только из
    # сессии ЭТОГО запуска»).
    a = _client()
    _upload(a, CSV_SENSOR, "cert8_sensor.csv")
    run_a = _run_id(a)

    b = _client()
    _upload(b, CSV_LOAD, "cert8_load.csv")
    run_b = _run_id(b)
    ctx_b = _run_meta(run_b).context_id
    assert ctx_b, "у сессии B есть свой контекст"

    anchor_a = _ledger_ids(run_a)[0]
    expected_wm = _ledger_len(run_a)  # ДО факта checkpoint_saved
    cp = _checkpoint_post(run_a, anchor_a, http=b, label="cert8-foreign-run")
    # Ссылка валидна (якорь существует в запуске A), но снимок и
    # контекстные метаданные сессии B НЕ атрибутируются запуску A.
    assert cp["has_snapshot"] is False, cp
    assert cp["context_id"] is None, cp["context_id"]
    assert cp["data_revision"] is None, cp["data_revision"]
    # Позиция durable-истории запуска A записана (от сессии не зависит).
    assert cp["watermark"] == expected_wm, (cp["watermark"], expected_wm)


@oracle("CHK-8 щит сериализации: bool не ревизия/позиция, None не фабрикуется")
def chk8_oracle():
    # Эволюция кампании (CM-11): unit-контракт from_dict/to_dict (§3.7,
    # щит C-CERT) -- пути Redis/JSON-чтения легаси-корпуса.
    from apps.api.research_runs import ResearchCheckpoint

    base = {
        "checkpoint_id": "cp-c8-shield",
        "run_id": "RUN-C8-SHIELD",
        "event_id": "e-c8-shield",
        "label": "cert8-shield",
        "has_snapshot": True,
        "created_at": "2026-10-13T12:00:00+00:00",
        "context_id": "ctx-8cert-a1b2c3d4",
        "data_revision": 3,
        "watermark": 41,
    }
    # Валидный корпус: metadata сохраняются (roundtrip).
    cp = ResearchCheckpoint.from_dict(dict(base))
    assert cp.context_id == "ctx-8cert-a1b2c3d4", cp.context_id
    assert cp.data_revision == 3 and cp.watermark == 41, (cp.data_revision, cp.watermark)
    assert ResearchCheckpoint.from_dict(base).to_dict()["watermark"] == 41
    # Мусорные типы -> честное отсутствие (bool -- subclass int, но НЕ
    # ревизия; строка -- не позиция).
    dirty = dict(base, data_revision=True, watermark=False, context_id="")
    cp_dirty = ResearchCheckpoint.from_dict(dirty)
    assert cp_dirty.data_revision is None, cp_dirty.data_revision
    assert cp_dirty.watermark is None, cp_dirty.watermark
    assert cp_dirty.context_id is None, cp_dirty.context_id
    # Незаполняемое поле отсутствует (легаси-строка не фабрикует ключи).
    legacy = ResearchCheckpoint.from_dict(
        {k: v for k, v in base.items()
         if k not in ("context_id", "data_revision", "watermark")}
    )
    assert legacy.to_dict().keys().isdisjoint(
        {"context_id", "data_revision", "watermark"}
    ), legacy.to_dict()


@oracle("CHK-6 легаси-строка чекпоинта: честное отсутствие, не фабрикация")
def chk6_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _checkpoint_post(run_id, _ledger_ids(run_id)[0], label="cert8-fresh")

    # Свой наблюдательный метод: инъекция ЛЕГАСИ-строки (без metadata)
    # напрямую в store -- корпус до миграции 0004.
    from apps.api.research_runs import ResearchCheckpoint

    research_runs.get_research_run_store().add_checkpoint(
        run_id,
        ResearchCheckpoint(
            checkpoint_id="cp-c8-legacy-row",
            run_id=run_id,
            event_id=_ledger_ids(run_id)[0],
            label="cert8-legacy",
            has_snapshot=True,
        ),
    )

    r = c.get(f"/v1/progress/runs/{run_id}")
    assert r.status_code == 200, r.text
    rows = {cp["checkpoint_id"]: cp for cp in r.json()["checkpoints"]}
    legacy = rows["cp-c8-legacy-row"]
    assert legacy["has_snapshot"] is True, legacy
    assert legacy["context_id"] is None, legacy["context_id"]
    assert legacy["data_revision"] is None, legacy["data_revision"]
    assert legacy["watermark"] is None, legacy["watermark"]
    fresh = rows[[k for k in rows if k != "cp-c8-legacy-row"][0]]
    assert fresh["watermark"] is not None, "свежий чекпоинт потерял metadata"


# ── DTO: чтение/создание несут одно и то же (контракт §22.4) ─────────


@oracle("DTO-1 roundtrip POST/GET: metadata совпадают байт-в-байт")
def dto1_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _outlier_cap(c, "sensor_a")

    posted = _checkpoint_post(run_id, _ledger_ids(run_id)[0], label="cert8-dto")
    r = c.get(f"/v1/progress/runs/{run_id}")
    assert r.status_code == 200, r.text
    rows = {cp["checkpoint_id"]: cp for cp in r.json()["checkpoints"]}
    read = rows[posted["checkpoint_id"]]
    for field in ("context_id", "data_revision", "watermark", "has_snapshot"):
        assert read[field] == posted[field], (field, read[field], posted[field])


# ── ND: неразрушительность восстановления (контракт §22.5) ───────────


@oracle("ND-1 SHA-256 raw-файла неизменен после двух restores")
def nd1_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    sha_before = _raw_sha256(run_id)

    _restore(run_id)
    _restore(run_id)

    assert _raw_sha256(run_id) == sha_before, "raw-файл изменён restore"


@oracle("ND-2 ledger append-only: префикс сохранён, ровно +1 run_resumed")
def nd2_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _outlier_cap(c, "sensor_a")
    types_before = [
        e.event_type
        for e in research_runs.get_research_run_store().list_events(run_id)
    ]
    ids_before = _ledger_ids(run_id)

    _restore(run_id)

    ids_after = _ledger_ids(run_id)
    types_after = [
        e.event_type
        for e in research_runs.get_research_run_store().list_events(run_id)
    ]
    assert ids_after[: len(ids_before)] == ids_before, "история переписана"
    assert len(ids_after) == len(ids_before) + 1, ids_after
    tail = types_after[len(types_before):]
    assert tail == ["run_resumed"], tail
    assert "target_column_changed" not in tail, "restore сеет выбор"
    assert "target_column_cleared" not in tail, "restore сеет сброс"


@oracle("ND-3 restore не выполняет новый авто-выбор (v0.7-1A сохранён)")
def nd3_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    _choose_target(c, "sensor_b")
    _outlier_cap(c, "sensor_a")

    data = _restore(run_id)
    # Пара восстановлена из ИСТОРИИ (choice факт остался тем же -- id
    # события выбора в ledger не появился заново).
    assert data["target_column"] == "sensor_b", data["target_column"]
    assert data["target_column_source"] == "user", data["target_column_source"]
    choice_events = [
        e.event_type
        for e in research_runs.get_research_run_store().list_events(run_id)
        if e.event_type in ("target_column_changed", "target_column_cleared")
    ]
    assert len(choice_events) == 1, choice_events  # исторический факт один


@oracle("ND-4 отсутствующий raw -- честный 409 (изъятие файлового слоя)")
def nd4_oracle():
    c = _client()
    _upload(c, CSV_SENSOR, "cert8_sensor.csv")
    run_id = _run_id(c)
    uploads_dir = research_runs.get_dataset_file_store().uploads_dir
    hidden = Path(str(uploads_dir) + ".c8-hidden")
    uploads_dir.rename(hidden)
    try:
        fresh = TestClient(app)
        r = fresh.get(f"/v1/progress/runs/{run_id}/restore")
        assert r.status_code == 409, r.status_code
    finally:
        hidden.rename(uploads_dir)


# ── Прогон ───────────────────────────────────────────────────────────

ORACLES = [
    (_name, _fn)
    for _name, _fn in sorted(globals().items())
    if callable(_fn) and hasattr(_fn, "_oracle_name")
]


def main() -> int:
    _log("=" * 72)
    _log("PROGR-AUDIT-8-CERT: СВОИ оракулы на СВОИХ данных (HEAD 2353e65)")
    _log("=" * 72)
    for _name, _fn in ORACLES:
        _fn()
    _log("-" * 72)
    _log(f"ИТОГО: {PASSES} PASS / {len(FAILURES)} FAIL из {len(ORACLES)}")
    for failure in FAILURES:
        _log(f"  FAILED: {failure}")
    if "--protocol" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--protocol") + 1])
        path.write_text("\n".join(PROTOCOL_LINES) + "\n", encoding="utf-8")
        print(f"protocol -> {path}", file=sys.stderr)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
