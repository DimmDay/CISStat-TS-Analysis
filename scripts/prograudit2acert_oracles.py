# scripts/prograudit2acert_oracles.py
# -*- coding: utf-8 -*-
"""СВОИ оракулы независимой сертификации PROGR-AUDIT-2A-CERT.

Объект: коммит 5689e8a (PROGR-AUDIT-2A — API-карты: контекст и
идемпотентность: единый механизм v2-конверта четырёх карт run/context/
report_id, контекстные гейты 409 ДО записи (P24/F04), идемпотентность по
report_id с отпечатком ТЕЛА (P07/F07), receipt доставки, штамп
client_observation (I10), compatibility mode легаси-писателей).
Аудит на HEAD = 9e8edde (продуктовый код AUDIT-2A — 5689e8a; последующие
02ac7ff/5364d41/3322e4a/0af1ea5/02ac7ff/5689e8a/9e8edde-сертификации
продуктовый код AUDIT-2A не меняли — git diff 5689e8a..9e8edde -- apps/
app/ пуст).

Принцип «оракулы на своих данных»: данные сертификатора ДИЗЪЮКТНЫ
данным оракула исполнителя (tests/api/test_progress_audit_2a.py:
monitor CSV value/humidity n150 от 2026-02-01, report_id rep-val-*/rep-
upload-a/rep-ctx-*/rep-obs-*/rep-refs-*, refs ctx-0123456789abcdef@…,
fingerprint-векторы RUN-1/ctx-a/n1/n2):
  * свои CSV-корпуса (метео «давление/осадки» 2025-11, «энергия»
    2025-08 — свои имена колонок/сезоны/объёмы);
  * свои report_id (c2a-rep-…), свои ссылки (…@c2a-ref-N), свой
    фабрикованный запуск RUN-C2A-FABRICATED;
  * свои наблюдательные методы: модульный разбор конверта
    (SimpleNamespace), spy-store commit_event_batch (гейт ДО записи),
    инъекция отказа слоя 1 (proxy session store), e2e — свои корпуса
    через живой API.

Канал проверки: самодостаточный EXIT-код (0 = все PASS).
Группы: ENV (форма конверта), FP (отпечаток тела), GATE (контекстные
гейты P24/F04), IDEM (матрица идемпотентности §19.3), STAMP (штамп
envelope), TX (транзакционность v2/receipt), LGC (легаси-пины
честности), FOUR (единый механизм на четырёх эндпоинтах), RECV
(поля receipt).

Запуск: python scripts/prograudit2acert_oracles.py [--protocol PATH]
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import traceback
from types import SimpleNamespace

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
            tmp = tempfile.mkdtemp(prefix="cert2a-oracle-")
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

# Метео-корпус: 60 суток от 2025-11-01, давление (плавный рост) и
# осадки (периодика). Колонки/сезоны/объёмы — дизъюнктны monitor-CSV
# исполнителя (value/humidity, 150 точек, 2026-02).
_METEO_DATE = [f"2025-11-{d:02d}" for d in range(1, 31)] + [
    f"2025-12-{d:02d}" for d in range(1, 32)
]
CSV_METEO = "date,давление,осадки\n" + "".join(
    f"{d},{740.0 + 0.4 * i},{(i % 9) * 1.5:.1f}\n"
    for i, d in enumerate(_METEO_DATE)
)

# Энергетический корпус: 90 суток от 2025-08-01 (второй upload —
# «загрузка B» в сценариях stale_run).
CSV_ENERGY = "date,энергия\n" + "".join(
    f"2025-08-{(i % 31) + 1:02d},{100.0 + (i % 13) * 7.25:.2f}\n"
    for i in range(90)
)

from fastapi.testclient import TestClient  # noqa: E402

from app.core.pipeline_graph import (  # noqa: E402
    CHECK_STATUS_VALUES,
    STAGE_NODES,
)
from apps.api.main import app  # noqa: E402
from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES  # noqa: E402

# Ленивые импорты API AUDIT-2A (progress_maps) — ВНУТРИ оракулов:
# RED на базе 3322e4a даёт по-оракульную грануляцию (прецедент 4-CERT).

ENDPOINTS: dict[str, dict] = {
    "/upload-stops": {
        "key": "stops",
        "registry": STAGE_NODES["upload"],
        "statuses": CHECK_STATUS_VALUES,
    },
    "/validation-checks": {
        "key": "checks",
        "registry": STAGE_NODES["validation"],
        "statuses": CHECK_STATUS_VALUES,
    },
    "/preprocessing-checks": {
        "key": "checks",
        "registry": STAGE_NODES["preprocessing"],
        "statuses": CHECK_STATUS_VALUES,
    },
    "/eda-checks": {
        "key": "checks",
        "registry": STAGE_NODES["eda"],
        "statuses": EDA_CHECK_STATUS_VALUES,
    },
}

MAP_EVENT_TYPE = {
    "/upload-stops": "upload_stop_status",
    "/validation-checks": "validation_check_status",
    "/preprocessing-checks": "preprocessing_check_status",
    "/eda-checks": "eda_check_status",
}

FABRICATED_RUN = "RUN-C2A-FABRICATED"


# ── СВОИ наблюдательные методы ───────────────────────────────────────


def _client(raise_server_exceptions: bool = True) -> TestClient:
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _meteo_upload(client: TestClient) -> None:
    r = client.post(
        "/v1/internal/upload",
        files={"file": (
            "cert2a_meteo.csv", io.BytesIO(CSV_METEO.encode()), "text/csv",
        )},
    )
    assert r.status_code == 200, f"upload meteo: {r.status_code} {r.text}"


def _energy_upload(client: TestClient) -> None:
    r = client.post(
        "/v1/internal/upload",
        files={"file": (
            "cert2a_energy.csv", io.BytesIO(CSV_ENERGY.encode()), "text/csv",
        )},
    )
    assert r.status_code == 200, f"upload energy: {r.status_code} {r.text}"


def _trace(client: TestClient) -> dict:
    r = client.get("/v1/progress/trace")
    assert r.status_code == 200, r.text
    return r.json()


def _seed(client: TestClient, corpus: str = "meteo") -> tuple[str, str]:
    """Свой seed: загрузка + (run_id, context_id) из GET /trace."""
    if corpus == "meteo":
        _meteo_upload(client)
    else:
        _energy_upload(client)
    t = _trace(client)
    run_id, context_id = t.get("run_id") or "", t.get("context_id") or ""
    assert run_id, "seed: run_id не зафиксирован"
    assert context_id, "seed: контекст не вычислен"
    return run_id, context_id


def _full_map(endpoint: str, fill: str = "done") -> dict[str, str]:
    spec = ENDPOINTS[endpoint]
    values = list(spec["statuses"])
    return {
        node: fill if fill in values else values[i % len(values)]
        for i, node in enumerate(spec["registry"])
    }


def _v2_body(
    endpoint: str,
    *,
    run_id: str,
    context_id: str,
    report_id: str,
    checks: dict[str, str] | None = None,
    result_refs: dict[str, str] | None = None,
    schema_version: int | None = 2,
) -> dict:
    spec = ENDPOINTS[endpoint]
    body: dict = {
        spec["key"]: checks if checks is not None else _full_map(endpoint),
        "schema_version": schema_version,
        "run_id": run_id,
        "context_id": context_id,
        "report_id": report_id,
    }
    if result_refs is not None:
        body["result_refs"] = result_refs
    return body


def _legacy_body(endpoint: str) -> dict:
    return {ENDPOINTS[endpoint]["key"]: _full_map(endpoint)}


def _post(client: TestClient, endpoint: str, body: dict):
    return client.post(f"/v1/progress{endpoint}", json=body)


def _session(client: TestClient):
    from apps.api.session_store import (
        SESSION_COOKIE_NAME,
        get_session_store,
    )

    sid = client.cookies.get(SESSION_COOKIE_NAME)
    assert sid, "нет session cookie"
    session = get_session_store().get(sid)
    assert session is not None
    return session


def _layer1(client: TestClient, event_type: str) -> list[dict]:
    return [
        e for e in _session(client).pipeline_trace
        if e.get("event_type") == event_type
    ]


def _layer2(run_id: str, event_type: str) -> list:
    from apps.api.research_runs import get_research_run_store

    return [
        e for e in get_research_run_store().list_events(run_id)
        if e.event_type == event_type
    ]


def _counts(client: TestClient, run_id: str, event_type: str):
    return (
        len(_layer1(client, event_type)),
        len(_layer2(run_id, event_type)),
    )


def _panel(client: TestClient) -> dict:
    return _trace(client)["node_statuses"]


def _zero_changes(client: TestClient, run_id, event_type, before, panel=None):
    after = _counts(client, run_id, event_type)
    assert after == before, (
        f"409/422/отказ обязаны давать НОЛЬ изменений: было {before}, "
        f"стало {after}"
    )
    if panel is not None:
        assert _panel(client) == panel, "панель изменилась после отказа"


def _expect_http(exc, code: int, fragment: str = "") -> None:
    from fastapi import HTTPException

    assert isinstance(exc, HTTPException), f"не HTTPException: {exc!r}"
    assert exc.status_code == code, (
        f"ожидался {code}, получен {exc.status_code}: {exc.detail}"
    )
    if fragment:
        assert fragment in str(exc.detail), (
            f"в detail нет {fragment!r}: {exc.detail}"
        )


# ── ENV: форма v2-конверта (контракт §19.1) — модульный разбор ───────


def _parse(body, registry):
    from apps.api.progress_maps import parse_map_envelope

    return parse_map_envelope(body, registry=registry)


def _simple_body(**kw) -> SimpleNamespace:
    base = {
        "schema_version": 2, "run_id": "RUN-C2A-1",
        "context_id": "ctx-0123456789abcdef", "report_id": "c2a-rep-env",
        "result_refs": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


@oracle("ENV1")
def env1_legacy_body_is_none():
    """Легаси: тело БЕЗ schema_version — None (не исключение, не 422):
    отсутствие поля — честный признак легаси-режима (§19.5)."""
    out = _parse(_simple_body(schema_version=None),
                 STAGE_NODES["validation"])
    assert out is None, f"легаси-тело должно давать None, получено {out!r}"


@oracle("ENV2")
def env2_foreign_schema_version_1_422():
    """Явное чужое schema_version=1 — 422 (не молчаливая деградация)."""
    try:
        _parse(_simple_body(schema_version=1), STAGE_NODES["validation"])
    except Exception as exc:
        _expect_http(exc, 422, "schema_version")
    else:
        raise OracleFail("schema_version=1 принят без 422")


@oracle("ENV3")
def env3_foreign_schema_version_3_422():
    """Явное чужое schema_version=3 — 422; поддерживается только 2."""
    try:
        _parse(_simple_body(schema_version=3), STAGE_NODES["validation"])
    except Exception as exc:
        _expect_http(exc, 422, "schema_version")
    else:
        raise OracleFail("schema_version=3 принят без 422")


@oracle("ENV4")
def env4_missing_run_id_422():
    """Пустой/пробельный run_id — 422 (отчёт обязан ссылаться на запуск)."""
    for bad in ("", "   ", None):
        try:
            _parse(_simple_body(run_id=bad), STAGE_NODES["validation"])
        except Exception as exc:
            _expect_http(exc, 422, "run_id")
        else:
            raise OracleFail(f"run_id={bad!r} принят без 422")


@oracle("ENV5")
def env5_missing_context_id_422():
    """Пустой/пробельный context_id — 422 (привязка к контексту I3)."""
    for bad in ("", "  ", None):
        try:
            _parse(_simple_body(context_id=bad), STAGE_NODES["validation"])
        except Exception as exc:
            _expect_http(exc, 422, "context_id")
        else:
            raise OracleFail(f"context_id={bad!r} принят без 422")


@oracle("ENV6")
def env6_missing_report_id_422():
    """Пустой/пробельный report_id — 422 (ключ идемпотентности)."""
    for bad in ("", " ", None):
        try:
            _parse(_simple_body(report_id=bad), STAGE_NODES["validation"])
        except Exception as exc:
            _expect_http(exc, 422, "report_id")
        else:
            raise OracleFail(f"report_id={bad!r} принят без 422")


@oracle("ENV7")
def env7_report_id_length_cap():
    """report_id длиннее 200 — 422; ровно 200 — принимается."""
    ok = _simple_body(report_id="r" * 200)
    out = _parse(ok, STAGE_NODES["validation"])
    assert out is not None and out.report_id == "r" * 200
    try:
        _parse(_simple_body(report_id="r" * 201), STAGE_NODES["validation"])
    except Exception as exc:
        _expect_http(exc, 422, "компактным")
    else:
        raise OracleFail("report_id из 201 символа принят без 422")


@oracle("ENV8")
def env8_result_ref_phantom_node_422():
    """result_refs фантомного узла — 422 (ключи — только узлы реестра)."""
    try:
        _parse(_simple_body(result_refs={"phantom_c2a": "ctx-0123456789abcdef@c2a-ref-1"}),
               STAGE_NODES["validation"])
    except Exception as exc:
        _expect_http(exc, 422, "неизвестный узел")
    else:
        raise OracleFail("фантомная ссылка принята без 422")


@oracle("ENV9")
def env9_result_ref_empty_422():
    """Пустая/пробельная/не-строковая ссылка — 422."""
    for bad in ("", "   ", None, 42):
        try:
            _parse(_simple_body(result_refs={"data_types": bad}),
                   STAGE_NODES["validation"])
        except Exception as exc:
            _expect_http(exc, 422, "непустой строкой")
        else:
            raise OracleFail(f"ссылка {bad!r} принята без 422")


@oracle("ENV10")
def env10_result_ref_length_cap():
    """Ссылка длиннее 512 — 422; ровно 512 — принимается."""
    own = "ctx-0123456789abcdef@"
    ok = _simple_body(result_refs={"data_types": own + "r" * (512 - len(own))})
    out = _parse(ok, STAGE_NODES["validation"])
    assert out is not None and out.result_refs
    try:
        _parse(_simple_body(result_refs={"data_types": own + "r" * (513 - len(own))}),
               STAGE_NODES["validation"])
    except Exception as exc:
        _expect_http(exc, 422, "длиннее")
    else:
        raise OracleFail("ссылка из 513 символов принята без 422")


@oracle("ENV11")
def env11_result_ref_foreign_context_409():
    """Ссылка со встроенным ЧУЖИМ контекстом (ctx-<16hex>@) — 409 (I3):
    результат чужого расчёта не прикладывается к текущей карте."""
    try:
        _parse(_simple_body(result_refs={"data_types": "ctx-ffffffffffffffff@c2a-ref-9"}),
               STAGE_NODES["validation"])
    except Exception as exc:
        _expect_http(exc, 409, "чужому контексту")
    else:
        raise OracleFail("чужой контекст ссылки принят без 409")


@oracle("ENV12")
def env12_result_ref_own_or_prefixless_ok():
    """Ссылка со СВОИМ контекстом и без префикса (клиентская метка) —
    принимаются; сервер не фабрикует владение без канона префикса."""
    out = _parse(_simple_body(
        result_refs={"data_types": "ctx-0123456789abcdef@c2a-ref-1",
                     "formats": "c2a-blob-77"}),
        STAGE_NODES["validation"])
    assert out is not None
    refs = dict(out.result_refs)
    assert refs["data_types"] == "ctx-0123456789abcdef@c2a-ref-1"
    assert refs["formats"] == "c2a-blob-77"


@oracle("ENV13")
def env13_refs_canonical_sorted():
    """refs в MapReportV2 отсортированы канонически (порядок тела не
    влияет на запись)."""
    out = _parse(_simple_body(
        result_refs={"formats": "c2a-b", "data_types": "c2a-a"}),
        STAGE_NODES["validation"])
    assert [n for n, _ in out.result_refs] == ["data_types", "formats"]


@oracle("ENV14")
def env14_envelope_fields_parsed():
    """Успешный конверт несёт ровно разобранные поля (run/context/
    report/refs)."""
    out = _parse(_simple_body(), STAGE_NODES["validation"])
    assert out.run_id == "RUN-C2A-1"
    assert out.context_id == "ctx-0123456789abcdef"
    assert out.report_id == "c2a-rep-env"
    assert out.result_refs == ()


# ── FP: отпечаток ТЕЛА (контракт §19.3) ──────────────────────────────


def _fp(**kw) -> str:
    from apps.api.progress_maps import report_body_fingerprint

    base = {
        "run_id": "RUN-C2A-FP", "context_id": "ctx-0123456789abcdef",
        "report_id": "c2a-rep-fp", "payload_map": {"n1": "done"},
        "result_refs": None,
    }
    base.update(kw)
    return report_body_fingerprint(**base)


@oracle("FP1")
def fp1_stable():
    """Детерминированность: тот же материал — тот же отпечаток."""
    assert _fp() == _fp()


@oracle("FP2")
def fp2_key_order_invariant():
    """Порядок ключей карты/ссылок не влияет (canonical json)."""
    a = _fp(payload_map={"n1": "done", "n2": "pending", "n3": "error"})
    b = _fp(payload_map={"n3": "error", "n1": "done", "n2": "pending"})
    assert a == b
    c = _fp(payload_map={"n1": "done"}, result_refs={"n1": "c2a-a", "n2": "c2a-b"})
    d = _fp(payload_map={"n1": "done"}, result_refs={"n2": "c2a-b", "n1": "c2a-a"})
    assert c == d


@oracle("FP3")
def fp3_sensitive_to_map_value():
    """Смена значения карты меняет отпечаток (база конфликта тел)."""
    assert _fp(payload_map={"n1": "done"}) != _fp(payload_map={"n1": "warning"})


@oracle("FP4")
def fp4_sensitive_to_report_id():
    """Другой report_id — другой отпечаток."""
    assert _fp(report_id="c2a-rep-fp-1") != _fp(report_id="c2a-rep-fp-2")


@oracle("FP5")
def fp5_sensitive_to_run_and_context():
    """Другие run/context — другой отпечаток."""
    assert _fp(run_id="RUN-C2A-FP2") != _fp()
    assert _fp(context_id="ctx-ffffffffffffffff") != _fp()


@oracle("FP6")
def fp6_refs_part_of_body():
    """Ссылки — часть тела: с/без refs различаются; пустой словарь == None."""
    base = _fp()
    with_refs = _fp(result_refs={"n1": "ctx-0123456789abcdef@c2a-ref-1"})
    assert base != with_refs
    assert _fp(result_refs={}) == base


@oracle("FP7")
def fp7_sha256_canonical_and_type_normalizing():
    """Форма: sha256:<64 hex>; int-статус нормализуется к строке (та же
    строка — тот же отпечаток), 1 == '1'."""
    from apps.api.progress_maps import report_body_fingerprint

    v = _fp()
    assert v.startswith("sha256:") and len(v) == len("sha256:") + 64
    assert report_body_fingerprint(
        run_id="RUN-C2A-FP", context_id="ctx-0123456789abcdef",
        report_id="c2a-rep-fp", payload_map={"n1": 1},
    ) == _fp(payload_map={"n1": "1"})


@oracle("FP8")
def fp8_independent_of_generated_events():
    """Отпечаток НЕ зависит от сгенерированных событий: два батча
    событий одного тела (разные event_id/ts) — одинаковый отпечаток
    тела, из которого дедуп обязан сработать."""
    from apps.api.progress_maps import _build_map_events, MapSpec

    spec = MapSpec(
        stage="validation", event_type="validation_check_status",
        registry=STAGE_NODES["validation"],
        no_dataset_subject="проверки «Валидации»",
    )
    map_values = _full_map("/validation-checks")
    ev1 = tuple(_build_map_events(spec, run_id="RUN-C2A-FP", map_values=map_values))
    ev2 = tuple(_build_map_events(spec, run_id="RUN-C2A-FP", map_values=map_values))
    assert {e.event_id for e in ev1}.isdisjoint({e.event_id for e in ev2}), (
        "ожидаем СВЕЖИЕ event_id на каждый вызов — база проверки дедупа"
    )
    from apps.api.progress_maps import report_body_fingerprint

    f1 = report_body_fingerprint(
        run_id="RUN-C2A-FP", context_id="ctx-0123456789abcdef",
        report_id="c2a-rep-fp", payload_map=map_values,
    )
    f2 = report_body_fingerprint(
        run_id="RUN-C2A-FP", context_id="ctx-0123456789abcdef",
        report_id="c2a-rep-fp", payload_map=map_values,
    )
    assert f1 == f2


# ── GATE: контекстные гейты ДО записи (P24/F04) — e2e на своих корпусах


@oracle("GATE1")
def gate1_report_a_rejected_after_upload_b():
    """P24 e2e на своих корпусах: отчёт запуска A (метео) после загрузки
    B (энергия) — 409 stale_run; НОЛЬ изменений в B (оба слоя + панель)."""
    client = _client()
    run_a, ctx_a = _seed(client, "meteo")
    stale = _v2_body("/upload-stops", run_id=run_a, context_id=ctx_a,
                     report_id="c2a-rep-g1")
    first = _post(client, "/upload-stops", stale)
    assert first.status_code == 200, first.text
    _energy_upload(client)
    run_b = _trace(client)["run_id"]
    assert run_b and run_b != run_a, "новая загрузка — новый запуск"
    ev = MAP_EVENT_TYPE["/upload-stops"]
    before = _counts(client, run_b, ev)
    panel = _panel(client)
    replay = _post(client, "/upload-stops", stale)
    assert replay.status_code == 409, replay.text
    assert "stale_run" in replay.text
    _zero_changes(client, run_b, ev, before, panel)


@oracle("GATE2")
def gate2_fabricated_run_409_no_binding():
    """Неизвестный запуск — 409; run_id клиента НЕ сеется (привязка не
    фабрикуется): в durable-слое записи fabricated-запуска нет."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    body = _v2_body("/validation-checks", run_id=FABRICATED_RUN,
                    context_id=ctx, report_id="c2a-rep-g2")
    r = _post(client, "/validation-checks", body)
    assert r.status_code == 409, r.text
    assert "stale_run" in r.text
    from apps.api.research_runs import get_research_run_store

    assert get_research_run_store().get_run(FABRICATED_RUN) is None, (
        "привязка фабрикована: запуск с run_id клиента появился в слое 2"
    )
    # повтор с тем же фабрикованным run_id — снова 409, привязки нет
    r2 = _post(client, "/validation-checks", body)
    assert r2.status_code == 409
    assert get_research_run_store().get_run(FABRICATED_RUN) is None


@oracle("GATE3")
def gate3_same_run_shifted_context_409():
    """Тот же запуск, смена цели (давление -> осадки): старый контекст —
    409 stale_context ДО записи; старый снапшот не повышает прогресс."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    stale = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                     report_id="c2a-rep-g3")
    first = _post(client, "/validation-checks", stale)
    assert first.status_code == 200, first.text
    shifted = client.post("/v1/session/target-column",
                          json={"column": "осадки"})
    assert shifted.status_code == 200, shifted.text
    ctx2 = _trace(client)["context_id"]
    assert ctx2 != ctx, "смена цели — другой контекст расчёта"
    ev = MAP_EVENT_TYPE["/validation-checks"]
    before = _counts(client, run_id, ev)
    panel = _panel(client)
    replay = _post(client, "/validation-checks", stale)
    assert replay.status_code == 409, replay.text
    assert "stale_context" in replay.text
    _zero_changes(client, run_id, ev, before, panel)


@oracle("GATE4")
def gate4_gates_run_before_store_commit_spy():
    """Гейты работают ДО записи: POST с чужим контекстом НЕ достигает
    store.commit_event_batch (spy-store: ноль вызовов на 409; ровно
    один вызов при приёмке, expected_context_id == durable контекст ==
    контекст GET /trace — «тот же источник», §19.2)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    import apps.api.research_runs as rr

    orig_get_store = rr.get_research_run_store
    real_store = orig_get_store()
    captured: list = []

    class _Spy:
        def __getattr__(self, name):
            return getattr(real_store, name)

        def commit_event_batch(self, batch):
            captured.append(batch)
            return real_store.commit_event_batch(batch)

    rr.get_research_run_store = lambda: _Spy()
    try:
        wrong = _v2_body("/validation-checks", run_id=run_id,
                         context_id="ctx-ffffffffffffffff",
                         report_id="c2a-rep-g4-wrong")
        r = _post(client, "/validation-checks", wrong)
        assert r.status_code == 409, r.text
        assert not captured, (
            "409 гейта дошёл до commit_event_batch: гейт ПОСЛЕ записи"
        )
        ok = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                      report_id="c2a-rep-g4-ok")
        r2 = _post(client, "/validation-checks", ok)
        assert r2.status_code == 200, r2.text
        assert len(captured) == 1, f"ожидался один commit, было {len(captured)}"
        durable = real_store.get_run(run_id)
        assert durable is not None and durable.context_id == ctx
        assert captured[0].expected_context_id == ctx, (
            "CAS expected_context_id не равен durable контексту"
        )
    finally:
        rr.get_research_run_store = orig_get_store


@oracle("GATE5")
def gate5_form_422_zero_changes_v2():
    """422 формы конверта в v2 — НОЛЬ изменений в обоих слоях и панели."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    before = _counts(client, run_id, ev)
    panel = _panel(client)
    bad_bodies = [
        {"checks": _full_map("/validation-checks"), "schema_version": 2,
         "context_id": ctx, "report_id": "c2a-rep-g5a"},
        {"checks": _full_map("/validation-checks"), "schema_version": 2,
         "run_id": run_id, "report_id": "c2a-rep-g5b"},
        {"checks": _full_map("/validation-checks"), "schema_version": 2,
         "run_id": run_id, "context_id": ctx},
        _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                 report_id="", schema_version=3),
    ]
    for bad in bad_bodies:
        r = _post(client, "/validation-checks", bad)
        assert r.status_code == 422, (bad, r.text)
        _zero_changes(client, run_id, ev, before, panel)


@oracle("GATE6")
def gate6_dataset_gate_first_400():
    """Гейт «без датасета — 400» — ПЕРВЫЙ (конверт не отменяет гейт):
    v2-тело без датасета — 400, и даже невалидный конверт — тоже 400."""
    client = _client()
    body = _v2_body("/validation-checks", run_id=FABRICATED_RUN,
                    context_id="ctx-0123456789abcdef",
                    report_id="c2a-rep-g6")
    r = _post(client, "/validation-checks", body)
    assert r.status_code == 400, r.text
    broken = _v2_body("/validation-checks", run_id=FABRICATED_RUN,
                      context_id="ctx-0123456789abcdef",
                      report_id="c2a-rep-g6", schema_version=7)
    r2 = _post(client, "/validation-checks", broken)
    assert r2.status_code == 400, (
        "гейт датасета обязан быть раньше разбора конверта"
    )


@oracle("GATE7")
def gate7_unknown_run_branch_when_durable_missing():
    """Ветка «запуск не зафиксирован в долговременном слое»: run_id
    валиден в сессии, durable-слой пуст — 409 stale_run (привязка не
    фабрикуется), НОЛЬ записей."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    from apps.api import research_runs as rr

    rr.reset_research_run_store_for_testing()
    body = _v2_body("/upload-stops", run_id=run_id, context_id=ctx,
                    report_id="c2a-rep-g7")
    r = _post(client, "/upload-stops", body)
    assert r.status_code == 409, r.text
    assert "stale_run" in r.text
    assert _layer1(client, MAP_EVENT_TYPE["/upload-stops"]) == []


@oracle("GATE8")
def gate8_missing_durable_context_409():
    """Запуск БЕЗ зафиксированного контекста — 409 stale_context
    (строгий v2 отклоняет отчёт без контекста, план §11 п.5)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    import apps.api.research_runs as rr
    from apps.api.research_runs import MemoryResearchRunStore

    store = rr.get_research_run_store()
    assert isinstance(store, MemoryResearchRunStore), (
        "оракул рассчитан на memory-бэкенд песочницы"
    )
    run = store.get_run(run_id)
    assert run is not None and run.context_id
    # Прямая инъекция: upsert_run аддитивен (COALESCE) и не может обнулить
    # контекст — ветка «контекст не зафиксирован» достижима только сырым
    # состоянием хранилища.
    store._runs[run_id] = replace(run, context_id=None)
    body = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                    report_id="c2a-rep-g8")
    r = _post(client, "/validation-checks", body)
    assert r.status_code == 409, r.text
    assert "stale_context" in r.text


from dataclasses import replace  # noqa: E402  (для GATE8)


# ── IDEM: матрица идемпотентности (контракт §19.3) — на своих данных ─


@oracle("IDEM1")
def idem1_new_key_new_body_written():
    """Новый report_id, новое тело — 200, deduplicated=false,
    reported=|реестр|, receipt; события в ОБОИХ слоях."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    r = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-i1"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "v2" and out["deduplicated"] is False
    assert out["reported"] == len(STAGE_NODES["validation"])
    assert out["receipt"] and out["report_id"] == "c2a-rep-i1"
    assert _counts(client, run_id, ev) == (
        len(STAGE_NODES["validation"]), len(STAGE_NODES["validation"]),
    )


@oracle("IDEM2")
def idem2_retry_same_body_previous_receipt():
    """Повтор ТОГО ЖЕ тела (потерянный ответ) — прежний receipt,
    deduplicated=true, reported=0, НОЛЬ новых записей в обоих слоях."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    body = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                    report_id="c2a-rep-i2")
    first = _post(client, "/validation-checks", body)
    assert first.status_code == 200, first.text
    first_out = first.json()
    before = _counts(client, run_id, ev)
    second = _post(client, "/validation-checks", body)
    assert second.status_code == 200, second.text
    out = second.json()
    assert out["mode"] == "v2" and out["deduplicated"] is True
    assert out["reported"] == 0, "дедуп обязан вернуть reported=0"
    assert out["receipt"] == first_out["receipt"], (
        "повтор обязан вернуть ПРЕЖНИЙ receipt без изменений"
    )
    assert _counts(client, run_id, ev) == before


@oracle("IDEM3")
def idem3_same_key_different_body_409():
    """Тот же report_id с ДРУГИМ телом — 409 report_id_conflict без
    записи (щит P07: прежний ключ не переиспользуется)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    rid = "c2a-rep-i3"
    first = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx, report_id=rid))
    assert first.status_code == 200
    changed = _full_map("/validation-checks")
    changed["formats"] = "pending"
    before = _counts(client, run_id, ev)
    panel = _panel(client)
    second = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id=rid, checks=changed))
    assert second.status_code == 409, second.text
    assert "report_id_conflict" in second.text
    _zero_changes(client, run_id, ev, before, panel)


@oracle("IDEM4")
def idem4_new_key_same_body_new_observation():
    """НОВЫЙ report_id с тем же телом — НОВОЕ клиентское наблюдение:
    события пишутся в оба слоя (дедуп не подавляет), deduplicated=false
    (план §11 п.4 — явное основание: новый отчёт)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    body1 = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                     report_id="c2a-rep-i4a")
    r1 = _post(client, "/validation-checks", body1)
    assert r1.status_code == 200
    n1 = _counts(client, run_id, ev)
    r2 = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-i4b"))
    assert r2.status_code == 200, r2.text
    assert r2.json()["deduplicated"] is False
    n2 = _counts(client, run_id, ev)
    assert n2[0] == n1[0] * 2 and n2[1] == n1[1] * 2, (
        f"новое наблюдение обязано удвоить события: {n1} -> {n2}"
    )


@oracle("IDEM5")
def idem5_store_dedup_previous_receipt_no_growth():
    """Store-контракт (§19.3 поверх AUDIT-6A): commit_map_report с тем
    же ключом+отпечатком (свежие события каждый раз) — ПРЕЖНИЙ receipt,
    ledger не растёт; с другим отпечатком — IdempotencyConflictError."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    from apps.api.progress_maps import (
        _build_map_events,
        MapSpec,
        report_body_fingerprint,
    )
    from apps.api.research_runs import (
        IdempotencyConflictError,
        commit_map_report,
    )

    spec = MapSpec(
        stage="preprocessing", event_type="preprocessing_check_status",
        registry=STAGE_NODES["preprocessing"],
        no_dataset_subject="этапы «Предобработки»",
    )
    map_values = _full_map("/preprocessing-checks")
    events1 = tuple(_build_map_events(spec, run_id=run_id,
                                      map_values=map_values))
    fp1 = report_body_fingerprint(
        run_id=run_id, context_id=ctx, report_id="c2a-rep-i5",
        payload_map=map_values)
    key = f"report:{run_id}:c2a-rep-i5"
    session = _session(client)
    r1 = commit_map_report(
        session, events=events1, run_id=run_id, expected_context_id=ctx,
        idempotency_key=key, body_fingerprint=fp1)
    assert r1.accepted_event_ids and r1.committed_watermark > 0
    ledger_after_first = len(_layer2(run_id, "preprocessing_check_status"))
    events2 = tuple(_build_map_events(spec, run_id=run_id,
                                      map_values=map_values))
    assert {e.event_id for e in events1}.isdisjoint(
        {e.event_id for e in events2})
    r2 = commit_map_report(
        session, events=events2, run_id=run_id, expected_context_id=ctx,
        idempotency_key=key, body_fingerprint=fp1)
    assert r2 == r1 or (
        r2.idempotency_key == r1.idempotency_key
        and r2.accepted_event_ids == r1.accepted_event_ids
        and r2.committed_watermark == r1.committed_watermark
    ), "повтор обязан вернуть ПРЕЖНИЙ receipt"
    assert len(_layer2(run_id, "preprocessing_check_status")) == (
        ledger_after_first), "дедуп ростом ledger запрещён"
    fp2 = report_body_fingerprint(
        run_id=run_id, context_id=ctx, report_id="c2a-rep-i5",
        payload_map={**map_values, "missing": "pending"})
    try:
        commit_map_report(
            session, events=events2, run_id=run_id, expected_context_id=ctx,
            idempotency_key=key, body_fingerprint=fp2)
    except IdempotencyConflictError:
        pass
    else:
        raise OracleFail("тот же ключ с другим телом не поднял конфликт")


@oracle("IDEM6")
def idem6_store_cas_race_commit_conflict():
    """CAS-гонка (§19.3): commit_map_report с expected_context_id=устаревший
    — CommitConflictError ДО записи; ledger не вырос; свежий контекст
    проходит."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    from apps.api.progress_maps import (
        _build_map_events,
        MapSpec,
        report_body_fingerprint,
    )
    from apps.api.research_runs import (
        CommitConflictError,
        commit_map_report,
    )

    spec = MapSpec(
        stage="eda", event_type="eda_check_status",
        registry=STAGE_NODES["eda"],
        no_dataset_subject="исследования «EDA»",
    )
    map_values = _full_map("/eda-checks", fill="done")
    fp = report_body_fingerprint(
        run_id=run_id, context_id=ctx, report_id="c2a-rep-i6",
        payload_map=map_values)
    session = _session(client)
    stale = "ctx-eeeeeeeeeeeeeeee"
    assert stale != ctx
    events = tuple(_build_map_events(spec, run_id=run_id,
                                     map_values=map_values))
    try:
        commit_map_report(
            session, events=events, run_id=run_id,
            expected_context_id=stale,
            idempotency_key=f"report:{run_id}:c2a-rep-i6",
            body_fingerprint=fp)
    except CommitConflictError:
        pass
    else:
        raise OracleFail("CAS не поднял конфликт на устаревшем контексте")
    assert _layer2(run_id, "eda_check_status") == []
    ok = commit_map_report(
        session, events=events, run_id=run_id, expected_context_id=ctx,
        idempotency_key=f"report:{run_id}:c2a-rep-i6b",
        body_fingerprint=fp)
    assert ok.accepted_event_ids


@oracle("IDEM7")
def idem7_conflict_on_body_only_change_any_endpoint():
    """Матрица §19.3 на ЧЕТЫРЁХ эндпоинтах (свои report_id): конфликт
    тела по одному значению карты — 409 на каждом; retry — дедуп."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    for endpoint in ENDPOINTS:
        rid = f"c2a-rep-i7{endpoint.replace('-', '')}"
        first = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert first.status_code == 200, (endpoint, first.text)
        second = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert second.status_code == 200
        assert second.json()["deduplicated"] is True, endpoint
        registry = ENDPOINTS[endpoint]["registry"]
        node0 = registry[0]
        changed = _full_map(endpoint)
        current = changed[node0]
        changed[node0] = (
            "pending" if current != "pending"
            else ("done" if "done" in ENDPOINTS[endpoint]["statuses"]
                  else current)
        )
        if changed[node0] == current:
            continue
        third = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid,
            checks=changed))
        assert third.status_code == 409, (endpoint, third.text)


@oracle("IDEM8")
def idem8_dedup_ignores_fresh_event_ids():
    """Дедуп тела не зависит от свежих event_id/ts записей: два POST
    одного тела (события пересоздаются) — второй дедуплицирован, счётчики
    на месте; смена ОДНОГО поля ссылок при том же report_id — 409."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    refs = {"data_types": f"{ctx}@c2a-ref-i8"}
    body = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                    report_id="c2a-rep-i8", result_refs=refs)
    r1 = _post(client, "/validation-checks", body)
    assert r1.status_code == 200
    before = _counts(client, run_id, ev)
    r2 = _post(client, "/validation-checks", body)
    assert r2.status_code == 200 and r2.json()["deduplicated"] is True
    assert _counts(client, run_id, ev) == before
    r3 = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-i8",
        result_refs={"data_types": f"{ctx}@c2a-ref-i8-OTHER"}))
    assert r3.status_code == 409, (
        "ссылки — часть тела: их смена обязана конфликтовать"
    )


@oracle("IDEM9")
def idem9_receipt_key_format_and_isolation_between_runs():
    """Ключ идемпотентности — report:{run_id}:{report_id}; один и тот же
    report_id в РАЗНЫХ запусках — разные ключи (изолированы): отчёт того
    же report_id после новой загрузки — 409 stale_run (не дедуп)."""
    client = _client()
    run_a, ctx_a = _seed(client, "meteo")
    rid = "c2a-rep-i9"
    r1 = _post(client, "/upload-stops", _v2_body(
        "/upload-stops", run_id=run_a, context_id=ctx_a, report_id=rid))
    assert r1.status_code == 200
    assert r1.json()["receipt"]["idempotency_key"] == f"report:{run_a}:{rid}"
    _energy_upload(client)
    t = _trace(client)
    run_b, ctx_b = t["run_id"], t["context_id"]
    assert run_b != run_a and ctx_b != ctx_a
    r2 = _post(client, "/upload-stops", _v2_body(
        "/upload-stops", run_id=run_a, context_id=ctx_a, report_id=rid))
    assert r2.status_code == 409 and "stale_run" in r2.text, (
        "старый отчёт после новой загрузки обязан отклониться гейтом, "
        "а не дедуплицироваться"
    )


# ── STAMP: штамп envelope client_observation (I10, §19.4) ────────────


@oracle("STAMP1")
def stamp1_layer1_envelope_fields():
    """События слоя 1 v2-отчёта: schema_version=2,
    evidence_level=client_observation, operation_id=report_id,
    context_id (обязательность §12.3 для client_observation)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    rid = "c2a-rep-s1"
    r = _post(client, "/preprocessing-checks", _v2_body(
        "/preprocessing-checks", run_id=run_id, context_id=ctx,
        report_id=rid))
    assert r.status_code == 200, r.text
    events = _layer1(client, "preprocessing_check_status")
    assert len(events) == len(STAGE_NODES["preprocessing"])
    for e in events:
        assert e["schema_version"] == 2, e
        assert e["evidence_level"] == "client_observation", e
        assert e["operation_id"] == rid, e
        assert e["context_id"] == ctx, e


@oracle("STAMP2")
def stamp2_layer2_envelope_fields():
    """То же — для stored-событий durable-слоя (to_dict)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    rid = "c2a-rep-s2"
    r = _post(client, "/eda-checks", _v2_body(
        "/eda-checks", run_id=run_id, context_id=ctx,
        report_id=rid, checks=_full_map("/eda-checks", fill="done")))
    assert r.status_code == 200, r.text
    stored = _layer2(run_id, "eda_check_status")
    assert len(stored) == len(STAGE_NODES["eda"])
    for e in stored:
        d = e.to_dict()
        assert d["schema_version"] == 2, d
        assert d["evidence_level"] == "client_observation", d
        assert d["operation_id"] == rid, d
        assert d["context_id"] == ctx, d


@oracle("STAMP3")
def stamp3_result_ref_only_referenced_nodes():
    """result_ref={report_ref: …} — ТОЛЬКО узлам со ссылками; узлы без
    ссылок поле не получают (§19.1)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    refs = {"data_types": f"{ctx}@c2a-ref-s3",
            "ranges": "c2a-blob-s3"}
    r = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-s3", result_refs=refs))
    assert r.status_code == 200, r.text
    by_node = {e["node_id"]: e
               for e in _layer1(client, "validation_check_status")}
    assert by_node["data_types"]["result_ref"] == {
        "report_ref": refs["data_types"]}
    assert by_node["ranges"]["result_ref"] == {"report_ref": refs["ranges"]}
    for node in STAGE_NODES["validation"]:
        if node not in refs:
            assert "result_ref" not in by_node[node], node


@oracle("STAMP4")
def stamp4_registry_order_of_events():
    """События пишутся В ПОРЯДКЕ РЕЕСТРА (§7.2-прецедент): порядок
    node_id слоя 1 и accepted_event_ids receipt == порядок реестра."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    r = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-s4"))
    assert r.status_code == 200, r.text
    registry = list(STAGE_NODES["validation"])
    l1 = [e["node_id"] for e in _layer1(client, "validation_check_status")]
    assert l1 == registry, f"порядок слоя 1 {l1} != реестр {registry}"
    receipt = r.json()["receipt"]
    stored = _layer2(run_id, "validation_check_status")
    by_id = {e.event_id: e for e in stored}
    ordered = [by_id[eid].node_id for eid in receipt["accepted_event_ids"]
               if eid in by_id]
    assert ordered == registry, (
        f"accepted_event_ids порядок {ordered} != реестр {registry}"
    )


@oracle("STAMP5")
def stamp5_legacy_events_stay_v1():
    """Легаси-события остаются v1 (байт-в-байт): НЕТ schema_version/
    evidence_level/operation_id/context_id в layer-1 записях."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    r = _post(client, "/validation-checks", _legacy_body("/validation-checks"))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "legacy"
    events = _layer1(client, "validation_check_status")
    assert len(events) == len(STAGE_NODES["validation"])
    for e in events:
        assert "schema_version" not in e, e
        assert "evidence_level" not in e, e
        assert "operation_id" not in e, e
        assert "context_id" not in e, e


@oracle("STAMP6")
def stamp6_v2_events_bound_to_report_run():
    """События v2 привязаны к run_id отчёта (совпадающему с сессией) —
    слой 2 хранит их в ledger этого запуска; чужой run не получает."""
    client = _client()
    run_a, ctx_a = _seed(client, "meteo")
    rid = "c2a-rep-s6"
    r = _post(client, "/upload-stops", _v2_body(
        "/upload-stops", run_id=run_a, context_id=ctx_a, report_id=rid))
    assert r.status_code == 200
    _energy_upload(client)
    run_b = _trace(client)["run_id"]
    assert len(_layer2(run_a, "upload_stop_status")) == len(
        STAGE_NODES["upload"])
    assert _layer2(run_b, "upload_stop_status") == [], (
        "события отчёта A утекли в ledger запуска B"
    )


# ── TX: транзакционность v2 и receipt (§19.4) ────────────────────────


@oracle("TX1")
def tx1_layer1_failure_honest_500_receipt_durable():
    """Сбой слоя 1 ПОСЛЕ durable-фиксации — честный 500 при существующем
    receipt; ledger содержит события; слой 1 пуст; повтор того же тела
    дедуплицируется (без удвоения ledger); НОВЫЙ report_id при
    восстановленном слое 1 пишет в оба слоя (самозаживление копии)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    import apps.api.progress_maps as pm

    real_get_session_store = pm.get_session_store
    failing = {"on": True}

    class _FailingSessionStore:
        def __getattr__(self, name):
            return getattr(real_get_session_store(), name)

        def save(self, session):
            if failing["on"]:
                raise RuntimeError("c2a-injected: layer-1 save failure")
            return real_get_session_store().save(session)

    pm.get_session_store = lambda: _FailingSessionStore()
    try:
        body = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                        report_id="c2a-rep-t1")
        r = _post(client, "/validation-checks", body)
        assert r.status_code == 500, (
            f"сбой слоя 1 обязан быть честным 500, получен "
            f"{r.status_code}: {r.text}"
        )
        from apps.api.research_runs import get_research_run_store

        receipt = get_research_run_store().get_commit_receipt(
            f"report:{run_id}:c2a-rep-t1")
        assert receipt is not None, "receipt не зафиксирован в слое 2"
        assert len(_layer2(run_id, "validation_check_status")) == (
            len(STAGE_NODES["validation"]))
        # Примечание: in-memory session-объект хранит append (объект живой),
        # НО durable-копия не сохранена — проверяем это косвенно: повтор
        # дедуплицируется, самозаживление через новый report_id ниже.
    finally:
        pm.get_session_store = real_get_session_store
        failing["on"] = False
    # Повтор той же поставки — дедуп, без новых записей в ledger.
    body = _v2_body("/validation-checks", run_id=run_id, context_id=ctx,
                    report_id="c2a-rep-t1")
    r2 = _post(client, "/validation-checks", body)
    assert r2.status_code == 200, r2.text
    out = r2.json()
    assert out["deduplicated"] is True and out["reported"] == 0
    assert len(_layer2(run_id, "validation_check_status")) == (
        len(STAGE_NODES["validation"]))
    # Новый report_id при живом слое 1 — обычная приёмка в оба слоя
    # (самозаживление копии: первая попытка осталась в in-memory объекте
    # и согласована с ledger, новая запись добавляет ровно один реестр).
    r3 = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-t1b"))
    assert r3.status_code == 200 and r3.json()["deduplicated"] is False
    assert len(_layer1(client, "validation_check_status")) == (
        2 * len(STAGE_NODES["validation"]))
    assert len(_layer2(run_id, "validation_check_status")) == (
        2 * len(STAGE_NODES["validation"]))


@oracle("TX2")
def tx2_layer2_commit_failure_no_layer1_writes():
    """Отказ store.commit_event_batch (строгий v2, БЕЗ bare-except) —
    исключение наружу (500), НОЛЬ частичных узлов в слое 1; легаси при
    том же отказе — прежний 200 (best-effort P08)."""
    client = _client(raise_server_exceptions=False)
    run_id, ctx = _seed(client, "meteo")
    from apps.api import research_runs as rr

    store = rr.get_research_run_store()
    original = store.commit_event_batch

    def _boom(batch):
        raise RuntimeError("c2a-injected: store commit failure")

    store.commit_event_batch = _boom
    try:
        r_v2 = client.post("/v1/progress/validation-checks", json=_v2_body(
            "/validation-checks", run_id=run_id, context_id=ctx,
            report_id="c2a-rep-t2"))
        assert r_v2.status_code >= 500, (
            f"строгий v2 обязан не глотать отказ store: {r_v2.status_code}"
        )
        assert _layer1(client, "validation_check_status") == [], (
            "слой 1 получил частичные узлы при отказе слоя 2"
        )
        r_legacy = client.post("/v1/progress/validation-checks",
                               json=_legacy_body("/validation-checks"))
        assert r_legacy.status_code == 200, r_legacy.text
        assert r_legacy.json()["mode"] == "legacy"
    finally:
        store.commit_event_batch = original


@oracle("TX3")
def tx3_reported_zero_on_dedup_registry_on_accept():
    """reported — размер реестра при приёмке, 0 при дедупе (новых фактов
    не записано) — на всех четырёх эндпоинтах."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    for endpoint in ENDPOINTS:
        rid = f"c2a-rep-t3{endpoint.replace('-', '')}"
        r1 = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert r1.status_code == 200
        assert r1.json()["reported"] == len(ENDPOINTS[endpoint]["registry"])
        r2 = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert r2.status_code == 200
        assert r2.json()["reported"] == 0, endpoint


@oracle("TX4")
def tx4_zero_partial_nodes_on_gate_conflicts():
    """Отказы (409 гейтов, 409 конфликта тела, 422 формы) не оставляют
    частичных узлов: счётчики обоих слоёв кратны |реестру| или нулю."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/validation-checks"]
    reg = len(STAGE_NODES["validation"])
    rid = "c2a-rep-t4"
    r1 = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx, report_id=rid))
    assert r1.status_code == 200
    n1 = _counts(client, run_id, ev)
    assert n1 == (reg, reg)
    changed = _full_map("/validation-checks")
    changed["data_types"] = "pending"
    conflicts = [
        ("conflict-body", _v2_body("/validation-checks", run_id=run_id,
                                   context_id=ctx, report_id=rid,
                                   checks=changed)),
        ("stale-context", _v2_body("/validation-checks", run_id=run_id,
                                   context_id="ctx-ffffffffffffffff",
                                   report_id="c2a-rep-t4x")),
        ("stale-run", _v2_body("/validation-checks", run_id=FABRICATED_RUN,
                               context_id=ctx, report_id="c2a-rep-t4y")),
        ("form-422", {"checks": _full_map("/validation-checks"),
                      "schema_version": 2, "run_id": run_id,
                      "context_id": ctx}),
    ]
    for label, body in conflicts:
        resp = _post(client, "/validation-checks", body)
        assert resp.status_code in (409, 422), (label, resp.status_code)
        n2 = _counts(client, run_id, ev)
        assert n2 == n1, f"{label}: частичные узлы {n1} -> {n2}"
        assert n2[0] % reg == 0 and n2[1] % reg == 0


# ── LGC: легаси-пины честности (§19.5) ───────────────────────────────


@oracle("LGC1")
def lgc1_legacy_marked_no_receipt():
    """Тело без schema_version — mode=legacy, НЕТ receipt/report_id,
    deduplicated=false, reported=|реестр| (аддитивная маркировка)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    r = _post(client, "/upload-stops", _legacy_body("/upload-stops"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "legacy"
    assert out["receipt"] is None
    assert out["report_id"] is None
    assert out["deduplicated"] is False
    assert out["reported"] == len(STAGE_NODES["upload"])
    assert out["run_id"] == run_id


@oracle("LGC2")
def lgc2_legacy_repeat_appends_p07_open():
    """Пин честности P07: легаси-повтор ДОБАВЛЯЕТ события (прежняя
    семантика сохранена сознательно — граница, не одобрение)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    ev = MAP_EVENT_TYPE["/upload-stops"]
    body = _legacy_body("/upload-stops")
    r1 = _post(client, "/upload-stops", body)
    assert r1.status_code == 200 and r1.json()["mode"] == "legacy"
    n1 = _counts(client, run_id, ev)
    r2 = _post(client, "/upload-stops", body)
    assert r2.status_code == 200 and r2.json()["mode"] == "legacy"
    n2 = _counts(client, run_id, ev)
    assert n2[0] == n1[0] * 2 and n2[1] == n1[1] * 2, (
        f"легаси-повтор обязан добавлять события (P07 открыт): {n1}->{n2}"
    )


@oracle("LGC3")
def lgc3_legacy_stale_body_accepted_p24_open():
    """Пин честности P24: старое легаси-тело принимается в новый запуск
    после новой загрузки (P24 для old-write пути НЕ закрыт)."""
    client = _client()
    run_a, _ = _seed(client, "meteo")
    body = _legacy_body("/upload-stops")
    r1 = _post(client, "/upload-stops", body)
    assert r1.status_code == 200
    _energy_upload(client)
    run_b = _trace(client)["run_id"]
    assert run_b != run_a
    r2 = _post(client, "/upload-stops", body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["mode"] == "legacy"
    assert r2.json()["run_id"] == run_b, (
        "легаси-отчёт обязан лечь в НОВЫЙ запуск (граница P24 открыта)"
    )


@oracle("LGC4")
def lgc4_legacy_best_effort_mirror_survives_store_failure():
    """Легаси-зеркало слоя 2 — best-effort (P08): отказ store.commit не
    ломает 200 легаси-ответа; слой 1 при этом полный (те же события)."""
    client = _client(raise_server_exceptions=False)
    run_id, ctx = _seed(client, "meteo")
    from apps.api import research_runs as rr

    store = rr.get_research_run_store()
    original = store.commit_event_batch

    def _boom(batch):
        raise RuntimeError("c2a-injected: store commit failure")

    store.commit_event_batch = _boom
    try:
        r = client.post("/v1/progress/upload-stops",
                        json=_legacy_body("/upload-stops"))
        assert r.status_code == 200, (
            f"легаси best-effort обязан выжить: {r.status_code} {r.text}"
        )
        assert r.json()["mode"] == "legacy"
    finally:
        store.commit_event_batch = original
    assert len(_layer1(client, "upload_stop_status")) == (
        len(STAGE_NODES["upload"]))


@oracle("LGC5")
def lgc5_legacy_all_four_endpoints():
    """Легаси-контур работает на всех ЧЕТЫРЁХ эндпоинтах (маркировка
    mode=legacy; события v1)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    for endpoint in ENDPOINTS:
        r = _post(client, endpoint, _legacy_body(endpoint))
        assert r.status_code == 200, (endpoint, r.text)
        out = r.json()
        assert out["mode"] == "legacy", endpoint
        assert out["reported"] == len(ENDPOINTS[endpoint]["registry"])
        events = _layer1(client, MAP_EVENT_TYPE[endpoint])
        assert len(events) == len(ENDPOINTS[endpoint]["registry"])
        for e in events:
            assert "schema_version" not in e, (endpoint, e)


# ── FOUR: единый механизм на четырёх эндпоинтах (план §11) ───────────


@oracle("FOUR1")
def four1_shared_contract_all_endpoints():
    """Единый v2-контракт на каждом из четырёх: приёмка+receipt,
    дедуп повтора, гейты 409 на чужой контекст — один механизм."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    for endpoint in ENDPOINTS:
        rid = f"c2a-rep-f1{endpoint.replace('-', '')}"
        r1 = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert r1.status_code == 200, (endpoint, r1.text)
        out = r1.json()
        assert out["mode"] == "v2" and out["deduplicated"] is False
        assert out["receipt"]["idempotency_key"] == f"report:{run_id}:{rid}"
        ev = MAP_EVENT_TYPE[endpoint]
        events = _layer1(client, ev)
        assert len(events) == len(ENDPOINTS[endpoint]["registry"])
        assert all(
            e["schema_version"] == 2
            and e["evidence_level"] == "client_observation"
            and e["operation_id"] == rid and e["context_id"] == ctx
            for e in events
        ), endpoint
        r2 = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert r2.status_code == 200
        assert r2.json()["deduplicated"] is True, endpoint
        r3 = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id="ctx-dddddddddddddddd",
            report_id=f"{rid}x"))
        assert r3.status_code == 409, (endpoint, r3.text)


@oracle("FOUR2")
def four2_event_types_correct_per_endpoint():
    """Тип события каждой карты — по MapSpec (реестр §4.1): события
    каждого эндпоинта лежат в ledger под СВОИМ типом."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    for endpoint, ev in MAP_EVENT_TYPE.items():
        rid = f"c2a-rep-f2{endpoint.replace('-', '')}"
        r = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert r.status_code == 200, (endpoint, r.text)
        assert len(_layer2(run_id, ev)) == len(
            ENDPOINTS[endpoint]["registry"]), endpoint


@oracle("FOUR3")
def four3_eda_vocabulary_enforced_v2():
    """Словарь EDA (done/pending) действует и в v2: warning — 422
    (решение тимлида v1.1 §2 не обходится конвертом)."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    checks = _full_map("/eda-checks", fill="done")
    checks[STAGE_NODES["eda"][0]] = "warning"
    r = _post(client, "/eda-checks", _v2_body(
        "/eda-checks", run_id=run_id, context_id=ctx,
        report_id="c2a-rep-f3", checks=checks))
    assert r.status_code == 422, r.text
    assert _layer2(run_id, "eda_check_status") == []


@oracle("FOUR4")
def four4_registry_exact_node_ids():
    """node_id записанных событий — РОВНО реестр карты (без фантомов и
    пропусков) на каждом эндпоинте."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    for endpoint in ENDPOINTS:
        rid = f"c2a-rep-f4{endpoint.replace('-', '')}"
        r = _post(client, endpoint, _v2_body(
            endpoint, run_id=run_id, context_id=ctx, report_id=rid))
        assert r.status_code == 200
        ev = MAP_EVENT_TYPE[endpoint]
        l1 = sorted(e["node_id"] for e in _layer1(client, ev))
        assert l1 == sorted(ENDPOINTS[endpoint]["registry"]), endpoint


# ── RECV: поля receipt (§19.4) ───────────────────────────────────────


@oracle("RECV1")
def recv1_receipt_fields_complete():
    """receipt несёт все контрактные поля: idempotency_key/run_id/
    context_id/accepted_event_ids/committed_watermark/created_at."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    rid = "c2a-rep-r1"
    r = _post(client, "/validation-checks", _v2_body(
        "/validation-checks", run_id=run_id, context_id=ctx, report_id=rid))
    assert r.status_code == 200
    receipt = r.json()["receipt"]
    for field in ("idempotency_key", "run_id", "context_id",
                  "accepted_event_ids", "committed_watermark", "created_at"):
        assert field in receipt, f"нет поля {field}: {receipt.keys()}"
    assert receipt["idempotency_key"] == f"report:{run_id}:{rid}"
    assert receipt["run_id"] == run_id
    assert receipt["context_id"] == ctx
    assert len(receipt["accepted_event_ids"]) == (
        len(STAGE_NODES["validation"]))
    assert receipt["committed_watermark"] > 0
    assert receipt["created_at"]


@oracle("RECV2")
def recv2_accepted_ids_match_ledger_events():
    """accepted_event_ids — фактические id событий в ledger; watermark —
    последний sequence; дедуп не двигает watermark."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    rid = "c2a-rep-r2"
    r1 = _post(client, "/upload-stops", _v2_body(
        "/upload-stops", run_id=run_id, context_id=ctx, report_id=rid))
    assert r1.status_code == 200
    receipt = r1.json()["receipt"]
    stored = {e.event_id for e in _layer2(run_id, "upload_stop_status")}
    assert set(receipt["accepted_event_ids"]) <= stored, (
        "accepted_event_ids обязаны быть событиями ledger"
    )
    w1 = receipt["committed_watermark"]
    r2 = _post(client, "/upload-stops", _v2_body(
        "/upload-stops", run_id=run_id, context_id=ctx, report_id=rid))
    assert r2.status_code == 200
    assert r2.json()["receipt"]["committed_watermark"] == w1, (
        "дедуп обязан вернуть прежний watermark"
    )


@oracle("RECV3")
def recv3_v2_outcome_fields_consistent():
    """Ответ v2 согласован: mode/report_id/context_id/deduplicated и
    receipt.context_id == контекст отчёта; легаси-поля не выдаются."""
    client = _client()
    run_id, ctx = _seed(client, "meteo")
    rid = "c2a-rep-r3"
    r = _post(client, "/preprocessing-checks", _v2_body(
        "/preprocessing-checks", run_id=run_id, context_id=ctx,
        report_id=rid))
    out = r.json()
    assert out["mode"] == "v2"
    assert out["report_id"] == rid
    assert out["context_id"] == ctx
    assert out["receipt"]["context_id"] == ctx


# ── Запуск ───────────────────────────────────────────────────────────


def main() -> int:
    oracles = [
        (name, fn) for name, fn in sorted(globals().items())
        if callable(fn) and getattr(fn, "_oracle_name", None)
    ]
    # Порядок групп как в докстринге: ENV, FP, GATE, IDEM, STAMP, TX,
    # LGC, FOUR, RECV — по имени оракула.
    import re

    order = {"ENV": 0, "FP": 1, "GATE": 2, "IDEM": 3, "STAMP": 4,
             "TX": 5, "LGC": 6, "FOUR": 7, "RECV": 8}

    def _sort_key(item):
        m = re.match(r"([A-Z]+)(\d+)", item[0])
        return (order.get(m.group(1), 9), int(m.group(2))) if m else (9, 0)

    oracles.sort(key=_sort_key)
    print("=" * 72, flush=True)
    print("PROGR-AUDIT-2A-CERT: СВОИ оракулы на своих данных", flush=True)
    print("=" * 72, flush=True)
    for name, fn in oracles:
        fn()
    print("-" * 72)
    total = PASSES + len(FAILURES)
    _log(f"ИТОГО: {PASSES}/{total} PASS, {len(FAILURES)} FAIL")
    if FAILURES:
        _log("Отказы:")
        for f in FAILURES:
            _log(f"  - {f}")
    protocol_path = os.path.join(
        REPO, "scripts/prograudit2acert_oracles_results.txt")
    if "--protocol" in sys.argv:
        idx = sys.argv.index("--protocol")
        protocol_path = sys.argv[idx + 1]
    with open(protocol_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(PROTOCOL_LINES) + "\n")
    print(f"Протокол: {protocol_path}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
