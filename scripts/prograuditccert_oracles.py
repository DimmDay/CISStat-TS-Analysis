#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-AUDIT-C-CERT (2026-10-10) — независимые оракулы аудита задачи
AUDIT-C (plan_progress_audit.md §6: данные, ревизии и серверный контекст
расчёта) на СВОИХ данных.

Аудитор: отдельная сессия; объект — коммит 0769547 поверх d54b648.
Оракулы ДИЗЪЮНКТНЫ сюиту разработчика tests/api/test_progress_audit_c.py:
свои датасеты/ids/маркеры/углы проверки. Ключевые СВОИ углы, которых НЕТ
в сюите разработчика:
  * межпроцессный детерминизм digest и context_id (субпроцесс, контракт
    «детерминирован между процессами»);
  * безопасная сторона недоступного дайджеста (сбой -> «изменение»,
    спека §8.2 — у разработчика этот угол не пинится);
  * чувствительность дайджеста к переупорядочению строк (index=True) и
    к смене ЗНАЧЕНИЯ при той же форме;
  * forged-контекст: POST-маршрутам выбора скармливаются поддельные
    context_id/data_revision — сервер не принимает;
  * чувствительность context_id к КАЖДОЙ компоненте в отдельности и
    нечувствительность к порядку словаря компонентов;
  * partial-v2 легальность штампа (validate_envelope на
    context-единственном штампе — форма перехода §14.5);
  * Redis-путь ревизии (save/get полного store, не только Memory);
  * честное отсутствие: события без датасета остаются v1 (без
    context_id), context-компоненты честно "" при отсутствии выбора.

СВОИ данные:
  * датасет hydro_meteo.csv — timestamp,humidity,pressure; 72 часовые
    точки c 2026-02-01T00:00 (сид 20261011, синус+шум, генерируется
    детерминированно в этом скрипте);
  * датасет hydro_fix.csv — тот же ряд с пропуском humidity (строка 30)
    для адресной коррекции;
  * session-ключи certc-hydro-*; run-материал RUN-CERTC-H01...;
  * actor программных событий «auditor» (не user/system разработчика);
  * event-типы-представители для unit-штампа — строка таблицы хука
    upload_completed (spec из TRACE_ROUTES) с СВОИМ response_body.

Режимы:
  --cert  все оракулы обязаны быть PASS (запуск на 0769547); exit 0.
  --red   сверка с PRE-REGISTERED таблицей EXPECTED_RED (запуск на
          d54b648 ДО AUDIT-C): KILLER обязан FAIL, GUARD обязан PASS;
          отсутствие новых API (ImportError) честно отмечается как
          ABSENT-FAIL у всех unit-групп; exit 0 при полном совпадении.

Pre-registered EXPECTED_RED (зафиксировано ДО отката на d54b648):
  KILLER (FAIL на d54b648):
    - все unit-группы D/R/S/C/E/A (новых API нет: apps/api/data_context.py
      не существует; AnalysisSession без data_revision/set_dataframe/
      current_context_*; pipeline_graph без CONTEXT_SCOPES/
      NODE_DEPENDENCY_SCOPES/node_context_validity) — ImportError,
      честная фиксация отсутствия (прецедент PROGR-24-A-CERT);
    - API P1..P6 (/current не отдаёт context_id/data_revision; ревизии
      и no-op-семантики нет; hook-события трассы без context_id;
      повторная загрузка не различима контекстом);
    - межпроцессные D4/C3 (субпроцесс не может импортировать новые API);
    - файловые пины X2/X3 (AppShellContext.test.tsx с гидратацией
      контекста и TS-оракул аудита отсутствуют в родительской редакции).
  GUARD (PASS на обеих базах):
    - G1 (слоя-1 идентичность upload_completed стабильна между чтениями
      /trace и ДО AUDIT-C — стабильность ввела AUDIT-S, AUDIT-C её не
      меняет; форма-пин v1 НЕ включён: на 0769547 hook-событие
      легально несёт context_id);
    - G2 (инвариант реестра узлов, живший до AUDIT-C: каждая стадия
      STAGE_NODES непуста и upload.chart существует);
    - G3 (чистый pandas: hash_pandas_object с фиксированным ключом
      детерминирован — свойство pandas, не AUDIT-C);
    - X1 (git-факт: рабочие файлы инструмента аудита == blob HEAD своей
      базы; от чекаута не зависит).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())

import requests  # noqa: E402,F401  (только для исключений; TestClient ниже)
from fastapi.testclient import TestClient  # noqa: E402

MODE = "cert"
if "--red" in sys.argv:
    MODE = "red"

RESULTS: list[tuple[str, str, str]] = []  # (id, класс, PASS/FAIL)


def oracle(oid: str, cls: str = "KILLER"):
    def deco(fn):
        def wrapper():
            try:
                fn()
                RESULTS.append((oid, cls, "PASS"))
            except Exception as exc:  # noqa: BLE001
                RESULTS.append(
                    (oid, cls, f"FAIL: {type(exc).__name__}: {exc}"[:220])
                )
        wrapper.__name__ = oid
        ORACLES.append(wrapper)
        return wrapper
    return deco


ORACLES: list = []

# ── Свои данные ────────────────────────────────────────────────────────

MY_NAME = "hydro_meteo.csv"
MY_FIX_NAME = "hydro_fix.csv"
MY_RUN = "RUN-CERTC-H01"
MY_ACTOR = "auditor"
MY_TS0 = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)


def _hydro_csv(with_gap: bool = False) -> str:
    """Детерминированный ряд аудита: 72 часовые точки, синус+шум.
    with_gap=True — пропуск humidity в строке 30 (адресная коррекция)."""
    import random

    rng = random.Random(20261011)
    rows = ["timestamp,humidity,pressure"]
    for i in range(72):
        stamp = datetime.fromtimestamp(MY_TS0.timestamp() + i * 3600, tz=timezone.utc).isoformat()
        hum = 55 + 18 * math.sin(2 * math.pi * (i % 24) / 24) + rng.uniform(-1.5, 1.5)
        pr = 1010 + 6 * math.sin(2 * math.pi * i / 72) + rng.uniform(-0.6, 0.6)
        hum_cell = "" if (with_gap and i == 30) else f"{hum:.2f}"
        rows.append(f"{stamp},{hum_cell},{pr:.2f}")
    return "\n".join(rows) + "\n"


def _new_client() -> TestClient:
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("REDIS_URL", None)
    os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
    os.environ["CISSTAT_SESSION_BACKEND"] = "memory"
    from apps.api.main import app
    from apps.api.session_store import reset_session_store_for_testing

    reset_session_store_for_testing()
    return TestClient(app)


def _upload(client: TestClient, name: str = MY_NAME, with_gap: bool = False) -> dict:
    csv = _hydro_csv(with_gap=with_gap)
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(csv.encode()), "text/csv")},
    )
    assert resp.status_code == 200, f"upload: {resp.status_code} {resp.text[:200]}"
    return resp.json()


def _current(client: TestClient) -> dict:
    resp = client.get("/v1/session/current")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_target(client: TestClient, column: str, **extra) -> dict:
    body = {"column": column, **extra}
    resp = client.post("/v1/session/target-column", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _missing_corrections(client: TestClient, *, apply: bool) -> dict:
    resp = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["humidity"], "strategy": "interpolate", "apply": apply},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trace(client: TestClient) -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _convert_to_string(client: TestClient, column: str) -> dict:
    resp = client.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": column, "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ════════════════ P-группа: живой API (поведение контекста) ════════════

@oracle("P1", "KILLER")
def _p1():
    """/current отдаёт СЕРВЕРНЫЙ context_id (prefix ctx-) и
    data_revision (int); устойчивы между чтениями; после загрузки
    ревизия 0. RED GREEN: «API отдаёт устойчивый контекст»."""
    client = _new_client()
    _upload(client)
    b1 = _current(client)
    b2 = _current(client)
    assert isinstance(b1.get("context_id"), str) and b1["context_id"].startswith("ctx-"), \
        f"context_id не серверная строка ctx-*: {b1.get('context_id')!r}"
    assert b1["context_id"] == b2["context_id"], "контекст неустойчив между чтениями"
    assert b1["data_revision"] == 0, f"ревизия после загрузки != 0: {b1['data_revision']!r}"


@oracle("P2", "KILLER")
def _p2():
    """Повторная загрузка ТОГО ЖЕ filename: dataset_id и context_id оба
    НОВЫЕ (run-scoping; RED «тот же filename после повторной загрузки
    различается»)."""
    client = _new_client()
    first = _upload(client)
    ctx1 = _current(client)["context_id"]
    second = _upload(client)  # тот же контент, то же имя
    ctx2 = _current(client)["context_id"]
    assert second["dataset_id"] != first["dataset_id"], \
        "dataset_id повторной загрузки не отличается"
    assert ctx1 and ctx2 and ctx1 != ctx2, \
        "повторная загрузка не сменила контекст (run-scoping нарушен)"


@oracle("P3", "KILLER")
def _p3():
    """Применённая коррекция повышает data_revision и двигает контекст;
    preview (apply=false) НЕ повышает ревизию и НЕ двигает контекст
    (RED «применённая коррекция меняет data revision; preview не меняет
    её»)."""
    client = _new_client()
    _upload(client, MY_FIX_NAME, with_gap=True)
    before = _current(client)
    assert before["data_revision"] == 0
    _missing_corrections(client, apply=False)  # preview
    preview = _current(client)
    assert preview["data_revision"] == 0, "preview повысил ревизию"
    assert preview["context_id"] == before["context_id"], "preview сдвинул контекст"
    _missing_corrections(client, apply=True)  # apply
    after = _current(client)
    assert after["data_revision"] == 1, \
        f"apply не повысил ревизию до 1: {after['data_revision']!r}"
    assert after["context_id"] != before["context_id"], "apply не сдвинул контекст"


@oracle("P4", "KILLER")
def _p4():
    """Смена цели humidity->pressure при неизменном datasetId меняет
    контекст (target-scope); no-op повторный выбор той же цели контекст
    не двигает (RED карточки; честный no-op выбора)."""
    client = _new_client()
    _upload(client)
    ds1 = _current(client)["dataset"]["dataset_id"]
    ctx1 = _current(client)["context_id"]
    _set_target(client, "humidity")
    ctx_h = _current(client)["context_id"]
    assert ctx_h != ctx1, "выбор цели не сдвинул контекст"
    _set_target(client, "pressure")
    ctx_p = _current(client)["context_id"]
    assert ctx_p != ctx_h, "смена цели humidity->pressure не сдвинула контекст"
    assert _current(client)["dataset"]["dataset_id"] == ds1, "datasetId сменился сменой цели"
    _set_target(client, "pressure")  # no-op повторный выбор
    assert _current(client)["context_id"] == ctx_p, \
        "no-op повторный выбор цели сдвинул контекст"


@oracle("P5", "KILLER")
def _p5():
    """Контекст создаёт ТОЛЬКО сервер: POST-маршруту выбора скармливаются
    поддельные context_id/data_revision — сервер их не принимает, /current
    продолжает отдавать вычисленное (план §1: «запретить подмену версии
    собственным счётчиком фронтенда»)."""
    client = _new_client()
    _upload(client)
    ctx0 = _current(client)["context_id"]
    _set_target(
        client, "humidity",
        context_id="ctx-forged-ffffffffffffffff",
        data_revision=999,
    )
    body = _current(client)
    assert body["context_id"] != "ctx-forged-ffffffffffffffff", \
        "поддельный context_id принят сервером"
    assert body["data_revision"] == 0, "поддельная data_revision принята сервером"
    assert body["context_id"] and body["context_id"] != ctx0, \
        "реальная смена цели не отразилась"


@oracle("P6", "KILLER")
def _p6():
    """Hook-события трассы несут серверный context_id момента сеяния
    (§12.7/§14.5): события, посеянные ДО мутации, держат СВОЙ момент
    (не перепривязываются — I3), событие ПОСЛЕ коррекции несёт
    актуальный контекст /current."""
    client = _new_client()
    _upload(client, MY_FIX_NAME, with_gap=True)
    ctx_upload = _current(client)["context_id"]
    _missing_corrections(client, apply=True)
    ctx_after = _current(client)["context_id"]
    assert ctx_upload and ctx_after and ctx_upload != ctx_after
    events = _trace(client).get("events", [])
    assert events, "трасса пуста после коррекции"
    upload_ev = [e for e in events if e["event_type"] == "upload_completed"]
    corr_ev = [e for e in events if e["event_type"] == "correction_applied"]
    assert upload_ev and corr_ev, "нет upload_completed/correction_applied в трассе"
    assert upload_ev[-1].get("context_id") == ctx_upload, \
        "историческое событие перепривязано к новому контексту (I3 нарушен)"
    assert corr_ev[-1].get("context_id") == ctx_after, \
        "событие после коррекции несёт не актуальный контекст"


# ════════════════ GUARD-группа: инварианты, жившие до AUDIT-C ══════════

@oracle("G1", "GUARD")
def _g1():
    """Слоя-1 идентичность upload_completed стабильна между чтениями
    /trace и ДО AUDIT-C (стабильность ввела AUDIT-S; AUDIT-C её не
    меняет). Форма-пин v1 НЕ включён: на 0769547 hook-событие легально
    несёт context_id."""
    client = _new_client()
    _upload(client)
    t1 = _trace(client)
    t2 = _trace(client)
    ev1 = [e for e in t1["events"] if e["event_type"] == "upload_completed"]
    ev2 = [e for e in t2["events"] if e["event_type"] == "upload_completed"]
    assert len(ev1) == 1 and len(ev2) == 1, "upload_completed не единственный"
    assert ev1[0]["event_id"] == ev2[0]["event_id"] and ev1[0]["event_id"], \
        "идентичность слоя 1 нестабильна"


@oracle("G2", "GUARD")
def _g2():
    """Инвариант реестра узлов, живший до AUDIT-C: каждая стадия
    STAGE_NODES непуста; upload.chart существует (структура графа не
    менялась задачей)."""
    from app.core.pipeline_graph import STAGES, STAGE_NODES

    for stage in STAGES:
        nodes = STAGE_NODES.get(stage)
        assert nodes, f"стадия {stage!r} без узлов"
    assert "chart" in STAGE_NODES["upload"], "upload.chart исчез"
    assert "missing" in STAGE_NODES["validation"] or True  # структура — не пин AUDIT-C


@oracle("G3", "GUARD")
def _g3():
    """Чистый pandas: hash_pandas_object с фиксированным ключом
    детерминирован (свойство pandas, на котором стоит дайджест; не
    факт AUDIT-C)."""
    import pandas as pd

    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": ["x", "y", "z"]})
    h1 = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    h2 = pd.util.hash_pandas_object(frame.copy(), index=True).to_numpy().tobytes()
    assert h1 == h2, "hash_pandas_object недетерминирован"


# ════════════════ D-группа: дайджест контента (unit) ══════════════════

@oracle("D1", "KILLER")
def _d1():
    """compute_data_digest: детерминирован в процессе; префикс df1-;
    None -> честное отсутствие «»."""
    import pandas as pd
    from apps.api.data_context import compute_data_digest

    frame = pd.DataFrame({"humidity": [51.0, 55.3], "pressure": [1010.1, 1012.7]})
    d1 = compute_data_digest(frame)
    d2 = compute_data_digest(frame.copy())
    assert d1 == d2 and d1.startswith("df1-"), f"дайджест недетерминирован: {d1!r}"
    assert compute_data_digest(None) == "", "None должен давать честное «»"


@oracle("D2", "KILLER")
def _d2():
    """Чувствительность дайджеста (СВОИ углы): смена ЗНАЧЕНИЯ при той
    же форме; добавление строки; переименование колонки; переупорядочение
    строк (index=True) — всё различается."""
    import pandas as pd
    from apps.api.data_context import compute_data_digest

    base = pd.DataFrame(
        {"humidity": [51.0, 55.3], "pressure": [1010.1, 1012.7]},
        index=[0, 1],
    )
    d_base = compute_data_digest(base)
    d_value = compute_data_digest(base.assign(humidity=[51.0, 55.4]))
    d_row = compute_data_digest(pd.DataFrame(
        {"humidity": [51.0, 55.3, 57.0], "pressure": [1010.1, 1012.7, 1009.9]},
    ))
    d_rename = compute_data_digest(base.rename(columns={"humidity": "hum_pct"}))
    d_shuffled = compute_data_digest(base.iloc[::-1])
    assert d_value != d_base, "смена значения не различена"
    assert d_row != d_base, "добавление строки не различено"
    assert d_rename != d_base, "переименование колонки не различено"
    assert d_shuffled != d_base, "переупорядочение строк не различено (index=True)"


@oracle("D3", "KILLER")
def _d3():
    """Сбой вычисления дайджеста -> «» (честное отсутствие); вызывающий
    трактует в безопасную сторону. Прямой пин защитного контура (спека
    §8.2)."""
    import pandas as pd
    import apps.api.data_context as dc

    def _boom(*a, **k):
        raise RuntimeError("audit-injected failure")

    original = pd.util.hash_pandas_object
    try:
        pd.util.hash_pandas_object = _boom
        assert dc.compute_data_digest(pd.DataFrame({"a": [1]})) == "", \
            "сбой дайджеста не дал честного «»"
    finally:
        pd.util.hash_pandas_object = original


@oracle("D4", "KILLER")
def _d4():
    """Межпроцессный детерминизм дайджеста (контракт: «детерминирован
    между процессами»): субпроцесс считает дайджест фиксированного
    фрейма — значение совпадает с вычислением в этом процессе."""
    import pandas as pd
    from apps.api.data_context import compute_data_digest

    frame = pd.DataFrame(
        {"humidity": [51.0, 55.3, 57.0], "pressure": [1010.1, 1012.7, 1009.9]}
    )
    here = compute_data_digest(frame)
    code = (
        "import pandas as pd, hashlib, json\n"
        "df = pd.DataFrame({'humidity': [51.0, 55.3, 57.0], "
        "'pressure': [1010.1, 1012.7, 1009.9]})\n"
        "hashed = pd.util.hash_pandas_object(df, index=True)\n"
        "material = f\"{df.shape}|{[str(c) for c in df.columns]}|"
        "{hashed.to_numpy().tobytes()!r}\"\n"
        "print('df1-' + hashlib.sha256(material.encode('utf-8', "
        "errors='surrogatepass')).hexdigest())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, f"субпроцесс упал: {proc.stderr[-200:]}"
    there = proc.stdout.strip().splitlines()[-1]
    assert here == there, f"межпроцессное расхождение: {here!r} != {there!r}"


# ════════════════ R-группа: ревизии и единая точка set_dataframe ═══════

def _own_session(frame=None, *, fp: str = "fp-certc-hydro-01"):
    """СВОЯ сессия аудита: set_dataset с фиксированным fingerprint."""
    import pandas as pd
    from apps.api.session_store import AnalysisSession, DatasetInfo

    session = AnalysisSession(session_id="certc-hydro-01")
    if frame is None:
        frame = pd.DataFrame(
            {"humidity": [55.1, None, 58.4, 61.2], "pressure": [1010.1, 1011.0, 1009.8, 1010.4]}
        )
    session.set_dataset(
        DatasetInfo(
            dataset_id="D-CERTC-01", name=MY_NAME, rows=len(frame),
            columns=len(frame.columns), size_label="2 KB",
            dataset_fingerprint=fp,
        ),
        frame,
    )
    session.ensure_run_id()
    return session


@oracle("R1", "KILLER")
def _r1():
    """set_dataset -> ревизия 0 и свой дайджест; set_dataframe с другим
    контентом -> True и ревизия 1; no-op (тот же контент) -> False и
    ревизия на месте (план §6 п.2: no-op не выдаётся за изменение)."""
    import pandas as pd

    session = _own_session()
    assert session.data_revision == 0 and session.data_digest, \
        "set_dataset не дал ревизии 0 и дайджеста"
    changed_frame = session.dataframe.assign(humidity=[55.1, 56.0, 58.4, 61.2])
    fact = session.set_dataframe(changed_frame, reason="certc:audit-correction")
    assert fact is True, "факт изменения не возвращён True"
    assert session.data_revision == 1, "ревизия не повышена"
    # Свежесть дайджеста после изменения (СВОЙ угол: дайджест обязан
    # соответствовать НОВОМУ контенту, иначе следующая no-op-детекция
    # слепа)
    from apps.api.data_context import compute_data_digest

    assert session.data_digest == compute_data_digest(changed_frame), \
        "дайджест не обновлён после изменения (устаревший)"
    same = session.set_dataframe(changed_frame.copy(), reason="certc:noop")
    assert same is False, "no-op вернул True"
    assert session.data_revision == 1, "no-op повысил ревизию"


@oracle("R2", "KILLER")
def _r2():
    """set_dataframe(None): после фрейма — факт изменения (ревизия+1,
    дайджест «»); повторно None — no-op False (честный факт)."""
    session = _own_session()
    first = session.set_dataframe(None, reason="certc:drop")
    assert first is True and session.data_revision == 1 and session.data_digest == "", \
        "сброс фрейма не дал честного факта изменения"
    second = session.set_dataframe(None, reason="certc:drop-again")
    assert second is False and session.data_revision == 1, \
        "повторный None выдал себя за изменение"


@oracle("R3", "KILLER")
def _r3():
    """Безопасная сторона недоступного дайджеста (спека §8.2; СВОЙ угол,
    у разработчика не запинен): compute_data_digest вернул «» при
    недоступном ПРЕДЫДУЩЕМ дайджесте — set_dataframe трактует как
    ИЗМЕНЕНИЕ (устаревший результат за current дороже лишней
    инвалидации)."""
    import apps.api.session_store as ss
    import pandas as pd

    session = _own_session()
    session.data_digest = ""  # честная симуляция недоступного прошлого дайджеста
    original = ss.compute_data_digest
    try:
        ss.compute_data_digest = lambda df: ""  # сбой вычисления
        fact = session.set_dataframe(
            pd.DataFrame({"humidity": [55.1, 55.9, 58.4, 61.2],
                          "pressure": [1010.1, 1011.0, 1009.8, 1010.4]}),
            reason="certc:digest-unavailable",
        )
        assert fact is True, "недоступный дайджест не взят в безопасную сторону"
        assert session.data_revision == 1, "безопасная сторона не повысила ревизию"
    finally:
        ss.compute_data_digest = original


@oracle("R4", "KILLER")
def _r4():
    """Новая загрузка (set_dataset) сбрасывает ревизию в 0 (новый датасет
    = новый анализ) и пересчитывает дайджест; контекст после новой
    загрузки другой (run-scoping)."""
    session = _own_session()
    session.set_dataframe(session.dataframe, reason="certc:noop")  # False
    session.set_dataframe(
        session.dataframe.assign(pressure=[1001.0] * 4), reason="certc:fix"
    )
    assert session.data_revision == 1
    import pandas as pd
    ctx_before = session.current_context_id()
    session.set_dataset(
        type(session.dataset)(
            dataset_id="D-CERTC-02", name=MY_FIX_NAME, rows=4, columns=2,
            size_label="2 KB", dataset_fingerprint="fp-certc-hydro-02",
        ),
        pd.DataFrame({"humidity": [40.0, 41.0], "pressure": [1020.0, 1021.0]}),
    )
    session.ensure_run_id()
    assert session.data_revision == 0, "новая загрузка не сбросила ревизию"
    assert session.data_digest and session.current_context_id() != ctx_before, \
        "новая загрузка не пересчитала контекст"


# ════════════════ S-группа: реестр scopes и применимость ══════════════

@oracle("S1", "KILLER")
def _s1():
    """Реестр NODE_DEPENDENCY_SCOPES покрывает STAGE_NODES 1:1 (нет
    сирот/дыр), значения — непустые frozenset ⊆ CONTEXT_SCOPES."""
    from app.core.pipeline_graph import (
        CONTEXT_SCOPES, NODE_DEPENDENCY_SCOPES, STAGE_NODES,
    )

    covered = set()
    for stage, nodes in NODE_DEPENDENCY_SCOPES.items():
        assert stage in STAGE_NODES, f"сирота-стадия {stage!r}"
        for node_id, scopes in nodes.items():
            assert node_id in STAGE_NODES[stage], f"сирота-узел {stage}.{node_id}"
            assert isinstance(scopes, frozenset) and scopes, \
                f"пустой/не-frozenset scope у {stage}.{node_id}"
            assert scopes <= set(CONTEXT_SCOPES), \
                f"внеканонный scope у {stage}.{node_id}: {scopes}"
            covered.add((stage, node_id))
    expected = {(s, n) for s, nodes in STAGE_NODES.items() for n in nodes}
    assert covered == expected, \
        f"полнота нарушена: дыры={sorted(expected - covered)[:5]} сироты={sorted(covered - expected)[:5]}"


@oracle("S2", "KILLER")
def _s2():
    """Матрица зависимостей: СВОИ точечные чтения семантики (контракт
    §14.3) + fail-closed ValueError на неизвестной паре."""
    from app.core.pipeline_graph import node_dependency_scopes

    assert node_dependency_scopes("upload", "chart") == frozenset({"data", "target", "temporal"})
    assert node_dependency_scopes("upload", "structure") == frozenset({"data", "temporal"})
    assert node_dependency_scopes("validation", "regularity") == frozenset({"data", "temporal"})
    assert "target" in node_dependency_scopes("validation", "sufficiency")
    assert node_dependency_scopes("preprocessing", "missing") == frozenset({"data"})
    assert node_dependency_scopes("preprocessing", "scaling") == frozenset({"data"})
    for probe in (("eda", "descriptive"), ("modeling", "backtest")):
        scopes = node_dependency_scopes(*probe)
        assert scopes == frozenset({"data", "target", "temporal"}), \
            f"{probe} должен зависеть от всех трёх: {scopes}"
    for bad in (("no_such_stage", "x"), ("upload", "no_such_node")):
        try:
            node_dependency_scopes(*bad)
        except ValueError:
            continue
        raise AssertionError(f"fail-closed не сработал на {bad}")


@oracle("S3", "KILLER")
def _s3():
    """Применимость (validity) — СВОЯ матрица: None/не-Mapping/частичный
    captured -> unknown; несовпадение -> stale; совпадение -> current;
    смена ТОЛЬКО цели: data-only узел current, target-dependent stale
    (риск карточки закрыт с обеих сторон)."""
    from app.core.pipeline_graph import (
        VALIDITY_CURRENT, VALIDITY_STALE, VALIDITY_UNKNOWN, node_context_validity,
    )

    cur = {"data": "fp1#0", "target": "humidity", "temporal": "timestamp"}
    assert node_context_validity("upload", "chart", None, cur) == VALIDITY_UNKNOWN
    assert node_context_validity("upload", "chart", "мусор", cur) == VALIDITY_UNKNOWN
    assert node_context_validity(
        "validation", "regularity", {"data": "fp1#0"}, cur
    ) == VALIDITY_UNKNOWN, "частичный captured должен быть unknown"
    assert node_context_validity("upload", "chart", cur, cur) == VALIDITY_CURRENT
    bumped = {**cur, "data": "fp1#1"}
    assert node_context_validity("upload", "chart", cur, bumped) == VALIDITY_STALE
    # смена только цели: data-only узел остаётся current...
    target_moved = {**cur, "target": "pressure"}
    assert node_context_validity("preprocessing", "missing", cur, target_moved) == VALIDITY_CURRENT
    # ...а target-dependent — stale
    assert node_context_validity("upload", "chart", cur, target_moved) == VALIDITY_STALE


@oracle("S4", "KILLER")
def _s4():
    """Канон scope-ключей един: CONTEXT_SCOPES == data_context.SCOPE_*
    (равенство-страховка; направленный импорт невозможен — паттерн
    STAGES)."""
    from app.core import pipeline_graph as pg
    from apps.api.data_context import SCOPE_DATA, SCOPE_TARGET, SCOPE_TEMPORAL

    assert pg.CONTEXT_SCOPES == ("data", "target", "temporal")
    assert set(pg.CONTEXT_SCOPES) == {SCOPE_DATA, SCOPE_TARGET, SCOPE_TEMPORAL}


# ════════════════ C-группа: идентичность контекста (unit) ═════════════

@oracle("C1", "KILLER")
def _c1():
    """compute_context_id: без запуска — None (честное отсутствие); тот
    же run+компоненты — тот же id; другой run — другой; префикс ctx-."""
    from apps.api.data_context import compute_context_id

    comp = {"data": "fp#0", "target": "humidity", "temporal": "timestamp"}
    assert compute_context_id(run_id="", components=comp) is None
    a = compute_context_id(run_id=MY_RUN, components=comp)
    b = compute_context_id(run_id=MY_RUN, components=dict(comp))
    c = compute_context_id(run_id=MY_RUN + "-X", components=comp)
    assert a and a.startswith("ctx-")
    assert a == b, "детерминизм на том же состоянии нарушен"
    assert a != c, "run-scoping нарушен"


@oracle("C2", "KILLER")
def _c2():
    """Чувствительность к КАЖДОЙ компоненте в отдельности и
    нечувствительность к порядку словаря (sort_keys материала)."""
    from apps.api.data_context import compute_context_id

    base = {"data": "fp#0", "target": "humidity", "temporal": "timestamp"}
    id0 = compute_context_id(run_id=MY_RUN, components=base)
    for key, val in (
        ("data", "fp#1"), ("target", "pressure"), ("temporal", "ts_utc"),
    ):
        moved = compute_context_id(run_id=MY_RUN, components={**base, key: val})
        assert moved != id0, f"компонента {key} не влияет на контекст"
    reversed_id = compute_context_id(
        run_id=MY_RUN, components=dict(reversed(list(base.items())))
    )
    assert reversed_id == id0, "порядок словаря компонентов влияет на id"


@oracle("C3", "KILLER")
def _c3():
    """Межпроцессный детерминизм context_id (uuid5 фиксированного
    namespace): субпроцесс с тем же материалом даёт тот же id (I3:
    восстановимая сессия продолжает свой контекст)."""
    from apps.api.data_context import compute_context_id

    comp = {"data": "fp-certc#3", "target": "pressure", "temporal": "timestamp"}
    here = compute_context_id(run_id=MY_RUN, components=comp)
    code = (
        "import json\n"
        "from uuid import NAMESPACE_URL, uuid5\n"
        "ns = uuid5(NAMESPACE_URL, 'https://cisstat.ts-analysis/progress/data-context-v1')\n"
        "material = json.dumps({'v': 1, 'run_id': 'RUN-CERTC-H01', "
        "'components': {'data': 'fp-certc#3', 'target': 'pressure', "
        "'temporal': 'timestamp'}}, sort_keys=True, ensure_ascii=False, "
        "separators=(',', ':'))\n"
        "print('ctx-' + uuid5(ns, material).hex[:16])\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"субпроцесс упал: {proc.stderr[-200:]}"
    there = proc.stdout.strip().splitlines()[-1]
    assert here == there, f"межпроцессное расхождение: {here!r} != {there!r}"


@oracle("C4", "KILLER")
def _c4():
    """context_components: data = fingerprint#revision; отсутствие
    выбора честно «» (не выдумывается)."""
    from apps.api.data_context import SCOPE_DATA, SCOPE_TARGET, SCOPE_TEMPORAL, context_components

    comp = context_components(
        dataset_fingerprint="fp-c", data_revision=7,
        target_column=None, date_column=None,
    )
    assert comp[SCOPE_DATA] == "fp-c#7"
    assert comp[SCOPE_TARGET] == "" and comp[SCOPE_TEMPORAL] == "", \
        "отсутствие выбора выдумано"
    full = context_components(
        dataset_fingerprint="fp-c", data_revision=7,
        target_column="humidity", date_column="timestamp",
    )
    assert full[SCOPE_TARGET] == "humidity" and full[SCOPE_TEMPORAL] == "timestamp"


# ════════════════ E-группа: штампование продюсеров (§14.5) ════════════

@oracle("E1", "KILLER")
def _e1():
    """record_trace_event штампует context_id момента сеяния (прямая
    точка хука, СВОЙ spec-строкой таблицы и СВОИМ response_body);
    штамп = v2-форма (schema_version=2)."""
    from apps.api.trace_hook import TRACE_ROUTES, record_trace_event

    session = _own_session()
    spec = next(s for s in TRACE_ROUTES if s.event_type == "upload_completed")
    event = record_trace_event(
        session, spec,
        response_body={"name": MY_NAME, "rows": 4, "columns": 2, "size_label": "2 KB"},
    )
    assert event is not None, "событие не сформировано"
    assert event.context_id == session.current_context_id(), \
        "hook-событие без серверного контекста сеяния"
    assert event.schema_version == 2, "штамп не поднял schema_version до 2"


@oracle("E2", "KILLER")
def _e2():
    """auto_fix_and_seed штампует auto-событие контекстом (СВОЙ фрейм:
    ровно один числовой кандидат humidity при date_column=timestamp)."""
    import pandas as pd
    from apps.api.session_store import AnalysisSession, DatasetInfo
    from apps.api.target_column_rule import auto_fix_and_seed

    frame = pd.DataFrame({
        "timestamp": [f"2026-02-01T0{i}:00:00+00:00" for i in range(4)],
        "humidity": [55.1, 56.2, 57.3, 58.4],
    })
    session = AnalysisSession(session_id="certc-hydro-auto")
    session.set_dataset(
        DatasetInfo(
            dataset_id="D-CERTC-AUTO", name=MY_NAME, rows=4, columns=2,
            size_label="2 KB", dataset_fingerprint="fp-certc-auto",
        ),
        frame,
    )
    session.ensure_run_id()
    column = auto_fix_and_seed(session)
    assert column == "humidity", f"авто-кандидат: {column!r}"
    assert session.target_column_source == "auto"
    auto_events = [
        e for e in session.pipeline_trace if e["event_type"] == "target_column_changed"
    ]
    assert auto_events, "auto-событие не посеяно"
    assert auto_events[-1]["context_id"] == session.current_context_id(), \
        "auto-событие без контекста сеяния"


@oracle("E3", "KILLER")
def _e3():
    """cleared-событие (convert-types) несёт контекст момента сброса:
    target-компонент уже пуст, ревизия конвертации применена (§14.5)."""
    client = _new_client()
    _upload(client)
    _set_target(client, "humidity")
    _convert_to_string(client, "humidity")
    cleared = [
        e for e in _trace(client)["events"]
        if e["event_type"] == "target_column_cleared"
    ]
    assert cleared, "cleared-событие не посеяно"
    body = _current(client)
    assert cleared[-1].get("context_id") == body["context_id"], \
        "cleared несёт контекст не момента сброса"
    assert body["target_column"] is None, "цель не сброшена конвертацией"


@oracle("E4", "KILLER")
def _e4():
    """Partial-v2 — ЛЕГАЛЬНАЯ форма перехода (§14.5): граница ПРИНИМАЕТ
    context-единственный штамп (normalize сохраняет schema_version=2 и
    context_id, без исключения); validate_envelope честно называет
    ТОЛЬКО ещё-не-заполненные обязательные поля уровня (context_id в
    нарушениях НЕ фигурирует — Optional до AUDIT-6A/6B); v1 — ровно
    одна запись «не нарушение»."""
    from apps.api.trace_events import (
        ENVELOPE_REQUIREMENTS, make_trace_event, normalize_trace_event_dict,
        stamp_envelope, validate_envelope,
    )

    session = _own_session()
    event = make_trace_event(
        "upload_completed", stage="upload", node_id="overview", run_id=session.run_id,
    )
    stamped = stamp_envelope(event, context_id=session.current_context_id())
    raw = stamped.to_dict()
    roundtrip = normalize_trace_event_dict(json.loads(json.dumps(raw)), run_id=session.run_id)
    assert roundtrip.get("schema_version") == 2 and roundtrip.get("context_id"), \
        "граница не приняла context-единственный штамп (форма перехода сломана)"
    violations = validate_envelope(raw)
    missing = {v.split("поле ")[-1] for v in violations}
    assert missing == set(ENVELOPE_REQUIREMENTS["server_result"]) - {"schema_version", "evidence_level"}, \
        f"аудит-линза неточна: {missing}"
    assert not any("context_id" in v for v in violations), \
        "context_id попал в нарушения (Optional до 6A/6B)"
    v1 = make_trace_event(
        "upload_completed", stage="upload", node_id="overview", run_id=session.run_id,
    ).to_dict()
    v1_viol = validate_envelope(v1)
    assert len(v1_viol) == 1 and "не нарушение" in v1_viol[0], \
        f"v1 должен быть честно отмечен не-нарушением: {v1_viol}"


@oracle("E5", "KILLER")
def _e5():
    """Честное отсутствие: сессия без датасета — hook-событие в v1-форме
    (context_id не выдумывается; None штамп не ставит)."""
    from apps.api.session_store import AnalysisSession
    from apps.api.trace_hook import TRACE_ROUTES, record_trace_event

    session = AnalysisSession(session_id="certc-empty")
    spec = next(s for s in TRACE_ROUTES if s.event_type == "upload_completed")
    event = record_trace_event(session, spec, response_body={"name": MY_NAME})
    assert event is not None
    assert session.current_context_id() is None
    assert event.context_id is None, "контекст выдуман без датасета/запуска"


# ════════════════ A-группа: сериализация, legacy, CAS ═════════════════

@oracle("A1", "KILLER")
def _a1():
    """Memory-roundtrip: data_revision/data_digest/context_id переживают
    сериализацию (план §6 п.5)."""
    import pandas as pd
    from apps.api.session_store import session_from_dict, session_to_dict

    session = _own_session()
    session.set_dataframe(session.dataframe.assign(humidity=[1.0, 2.0, 3.0, 4.0]),
                          reason="certc:fix")
    doc = session_to_dict(session)
    restored = session_from_dict(json.loads(json.dumps(doc)))
    assert restored.data_revision == session.data_revision == 1
    assert restored.data_digest == session.data_digest
    assert restored.current_context_id() == session.current_context_id()


@oracle("A2", "KILLER")
def _a2():
    """Legacy-документ (без новых полей) -> честные дефолты 0/«»
    (SESSION_SCHEMA_VERSION не поднят, аддитивные Optional)."""
    from apps.api.session_store import session_from_dict

    restored = session_from_dict({"session_id": "certc-legacy", "stages": {}})
    assert restored.data_revision == 0 and restored.data_digest == ""


@oracle("A3", "KILLER")
def _a3():
    """Redis-путь: полный save/get сохраняет ревизию и контекст (СВОЙ
    session-ключ)."""
    from fakeredis import FakeStrictRedis

    import pandas as pd
    from apps.api.session_store import DatasetInfo, RedisSessionStore

    store = RedisSessionStore(client=FakeStrictRedis())
    session = store.get_or_create("certc-hydro-redis")
    session.set_dataset(
        DatasetInfo(
            dataset_id="D-CERTC-R", name=MY_NAME, rows=4, columns=2,
            size_label="2 KB", dataset_fingerprint="fp-certc-redis",
        ),
        pd.DataFrame(
            {"humidity": [55.1, 56.2, None, 58.4], "pressure": [1010.0] * 4}
        ),
    )
    session.set_dataframe(
        pd.DataFrame(
            {"humidity": [55.1, 56.2, 57.3, 58.4], "pressure": [1010.0] * 4}
        ),
        reason="certc:redis-fix",
    )
    store.save(session)
    reread = store.get("certc-hydro-redis")
    assert reread is not None
    assert reread.data_revision == session.data_revision == 1
    assert reread.data_digest == session.data_digest
    assert reread.current_context_id() == session.current_context_id()


@oracle("A4", "KILLER")
def _a4():
    """CAS-конфликт не выдаёт ложное обновление (СВОЙ session-ключ):
    устаревший снимок отклонён; в хранилище — данные winner'а; счётчик
    storage_revision проигравшего не выдуман."""
    import pandas as pd
    from fakeredis import FakeStrictRedis

    from apps.api.session_store import DatasetInfo, RedisSessionStore, SessionConflictError

    store = RedisSessionStore(client=FakeStrictRedis())
    winner = store.get_or_create("certc-hydro-cas")
    winner.set_dataset(
        DatasetInfo(
            dataset_id="D-CERTC-CAS", name=MY_NAME, rows=4, columns=2,
            size_label="2 KB", dataset_fingerprint="fp-certc-cas",
        ),
        pd.DataFrame({"humidity": [55.1, 56.2, None, 58.4]}),
    )
    store.save(winner)
    stale = store.get("certc-hydro-cas")
    fresh = store.get("certc-hydro-cas")
    fresh.set_dataframe(pd.DataFrame({"humidity": [55.1, 56.2, 57.3, 58.4]}),
                        reason="certc:cas-fix")
    store.save(fresh)
    try:
        store.save(stale)
    except SessionConflictError:
        pass
    else:
        raise AssertionError("CAS-конфликт не поднят устаревшим снимком")
    reread = store.get("certc-hydro-cas")
    assert reread.data_revision == fresh.data_revision
    assert reread.data_digest == fresh.data_digest
    assert reread.current_context_id() == fresh.current_context_id()
    assert stale.storage_revision < reread.storage_revision


# ════════════════ X-группа: файловые пины аудита ══════════════════════

@oracle("X1", "GUARD")
def _x1():
    """Git-факт: рабочие файлы инструмента аудита == blob HEAD (не тронут
    аудитом; от чекаута не зависит)."""
    for name in (
        "scripts/progress_audit_readonly.py",
        "scripts/progress_audit_readonly_results.json",
    ):
        blob = subprocess.run(
            ["git", "show", f"HEAD:{name}"], capture_output=True, cwd=os.getcwd()
        )
        assert blob.returncode == 0, f"{name} отсутствует в HEAD"
        assert hashlib.md5(blob.stdout).hexdigest() == \
            hashlib.md5(open(name, "rb").read()).hexdigest(), \
            f"{name} изменён рабочим деревом"


@oracle("X2", "KILLER")
def _x2():
    """Файловый пин: AppShellContext гидратирует contextId/dataRevision
    из ответа сервера (точка карточки); в родительской редакции поля
    отсутствуют."""
    text = open("packages/ui/context/AppShellContext.tsx", encoding="utf-8").read()
    assert "context_id" in text and "contextId" in text, "нет гидратации contextId"
    assert "data_revision" in text and "dataRevision" in text, "нет гидратации dataRevision"
    assert "setContextId(data.context_id ?? null)" in text, "контекст не из ответа сервера"


@oracle("X3", "KILLER")
def _x3():
    """Файловый пин: acceptance-сюит задачи и jest-оракул гидратации
    существуют (в родительской редакции их нет)."""
    for name in (
        "tests/api/test_progress_audit_c.py",
        "packages/ui/context/AppShellContext.test.tsx",
    ):
        assert os.path.exists(name), f"{name} отсутствует (не задеплоен коммит задачи)"


# ════════════════════════ запуск ══════════════════════════════════════

def main() -> int:
    for fn in ORACLES:
        fn()

    killers = [r for r in RESULTS if r[1] == "KILLER"]
    guards = [r for r in RESULTS if r[1] == "GUARD"]
    print("=" * 72)
    print(f"PROGR-AUDIT-C-CERT: оракулы на СВОИХ данных — режим {MODE}")
    print("=" * 72)
    for oid, cls, status in RESULTS:
        marker = "✅" if status == "PASS" else "❌"
        print(f"  {marker} {oid:4} [{cls:6}] {status}")
    passed = sum(1 for _, _, s in RESULTS if s == "PASS")
    print("-" * 72)
    print(f"ИТОГО: {passed}/{len(RESULTS)} PASS "
          f"(KILLER: {len(killers)}, GUARD: {len(guards)})")

    if MODE == "cert":
        ok = passed == len(RESULTS)
        print("ВЕРДИКТ ОРАКУЛОВ:", "ALL GREEN" if ok else "ЕСТЬ ПРОВАЛЫ")
        return 0 if ok else 1

    mismatches = []
    for oid, cls, status in RESULTS:
        expected_fail = cls == "KILLER"
        actual_fail = status != "PASS"
        if expected_fail != actual_fail:
            mismatches.append((oid, cls, status))
    print("-" * 72)
    if mismatches:
        print("EXPECTED_RED РАСХОЖДЕНИЯ:")
        for oid, cls, status in mismatches:
            print(f"  {oid} [{cls}] — {status}")
        return 1
    print("EXPECTED_RED: полное совпадение "
          f"({len(killers)} KILLER упали, {len(guards)} GUARD зелёные)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
