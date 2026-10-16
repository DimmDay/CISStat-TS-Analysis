#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""НЕЗАВИСИМЫЕ бэкенд-оракулы сертификации DATASET-VIEW-EDITOR-1-CERT
(2026-10-16): свои данные сертификатора («порт-звонки» port_calls_2023),
корпус дизъюнктен repo-тестам задачи (g345/meteo). Прецедент PROGR-25-B-CERT.

Контур проверок (B01..B16):
  B01/B02 (guard) -- 404 без датасета (GET реестра / POST удаления);
  B03 (guard)     -- свежая загрузка -- честно пустой реестр;
  B04     -- стратегия 1: flag по ДВУМ колонкам сразу (calls, cargo_kt)
             -- 2 записи, stage/source по паттерну, порядок created_at;
  B05     -- вторая остановка (outlier-flag) -- 3 записи, 2 стадии,
             created_at монотонны;
  B06     -- GET read-only ГЛУБЖЕ repo-пина: data_revision И updated_at
             не меняются, снапшот кадра/реестра байт-совпадает;
  B07     -- смешанный запрос (производная + каноническая month) -- 422
             ЦЕЛИКОМ, offending-имена в detail, кадр/реестр/ревизия целы;
  B08     -- каноническая колонка -- 422, ревизия без изменений, состав
             кадра байт-равен (главная гарантия безопасности источника);
  B09     -- ЯДРО СЦЕНАРИЯ дефекта: delete 1 из 3 добавленных -- 200,
             deleted, remaining_total == факту GET, строки без колонки,
             каскад реестра, канонические целы;
  B10     -- ревизия ровно +1 за удаление (и ровно ещё +1 за второе);
  B11     -- дубли имени схлопнуты (единожды), порядок сохранён;
  B12     -- удаление всех добавленных -- реестр пуст; re-add заново
             регистрирует (нет скрытых долгов);
  B13     -- ПЕРСИСТЕНЦИЯ НА РЕАЛЬНОМ Redis-бэкенде (fakeredis):
             save→get roundtrip production-пути -- перечитанная сессия
             без удалённой колонки, каскад реестра сохранён; RAW JSON
             документа Redis несёт состав после удаления;
  B14     -- контракт ответа delete: deleted list[str],
             remaining_total int == GET total; строк в ответе нет
             (пин «источник строк -- /dataset/rows»);
  B15     -- устаревшая запись реестра (колонка удалена мимо реестра):
             GET её не отдаёт, POST по ней -- 422;
  B16 (guard) -- пустой список columns -- 422.

Запуск: DATABASE_URL=sqlite:////tmp/... python scripts/dvecert_backend_oracles.py
Протокол: scripts/dvecert_backend_oracles.txt (exit 0 = все PASSED).
Правила AGENTS.md: артефакт сертификации; commit/push НЕ выполняются.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "sqlite:////tmp/dvecert_oracles.db")

import fakeredis  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import apps.api.session_store as session_store_module  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    RedisSessionStore,
    reset_session_store_for_testing,
)

client = TestClient(app)

URL = "/v1/session/dataset/derived-columns"
DELETE_URL = "/v1/session/dataset/derived-columns/delete"

_RESULTS: list[tuple[str, bool, str]] = []


def check(oracle_id: str, condition: bool, detail: str = "") -> None:
    _RESULTS.append((oracle_id, bool(condition), detail))
    status = "PASSED" if condition else "FAILED"
    print(f"[{status}] {oracle_id}" + (f" -- {detail}" if detail and not condition else ""), flush=True)


# ── СВОИ данные: «порт-звонки» (24 месячных точки, дизъюнктны repo) ──
def _port_calls_frame() -> pd.DataFrame:
    t = np.arange(24, dtype=float)
    frame = pd.DataFrame(
        {
            "month": pd.date_range("2023-01-01", periods=24, freq="MS").strftime("%Y-%m-%d"),
            "calls": np.round(42 + 3.1 * t + 6 * np.sin(t / 2.0), 0),
            "cargo_kt": np.round(120 + 0.9 * t + 10 * np.cos(t / 3.0), 2),
        }
    )
    frame.loc[[4, 15], "calls"] = np.nan      # пропуски звонков
    frame.loc[[7], "cargo_kt"] = np.nan       # пропуск грузооборота
    frame.loc[[20], "cargo_kt"] += 500        # детерминированный выброс (иначе IQR-flag не добавит колонку)
    return frame


def _upload(frame: pd.DataFrame, name: str = "port_calls_2023.csv") -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _session():
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    return session_store_module.get_session_store().get(session_id)


def _data_revision() -> int:
    return int(_session().data_revision)


def _frame_columns() -> list[str]:
    return [str(c) for c in _session().dataframe.columns]


def main() -> int:
    reset_session_store_for_testing()

    # ── Guards: пустая сессия ─────────────────────────────────────────
    check("B01 guard: GET derived-columns без датасета -- 404", client.get(URL).status_code == 404)
    check("B02 guard: POST delete без датасета -- 404", client.post(DELETE_URL, json={"columns": ["x"]}).status_code == 404)

    # ── Свежая загрузка: честно пустой реестр ────────────────────────
    _upload(_port_calls_frame())
    body = client.get(URL).json()
    check("B03 guard: свежая загрузка -- columns [], total 0", body["columns"] == [] and body["total"] == 0, json.dumps(body, ensure_ascii=False)[:200])

    # ── Стратегия 1: flag по ДВУМ колонкам ───────────────────────────
    r = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["calls", "cargo_kt"], "strategy": "flag", "apply": True},
    )
    ok = r.status_code == 200 and r.json()["added_columns"] == ["calls_missing_flag", "cargo_kt_missing_flag"]
    check("B04a: стратегия 1 (flag на 2 колонках) -- добавлены обе", ok, r.text[:200])
    body = client.get(URL).json()
    names = [e["column"] for e in body["columns"]]
    stages = [e["stage"] for e in body["columns"]]
    sources = [e["source"] for e in body["columns"]]
    check(
        "B04b: реестр -- 2 записи, stage=missing, source по паттерну, порядок created_at",
        body["total"] == 2
        and names == ["calls_missing_flag", "cargo_kt_missing_flag"]
        and stages == ["missing", "missing"]
        and all(s.startswith("missing_correction:flag:") for s in sources)
        and "calls" in sources[0] and "cargo_kt" in sources[0]
        and [e["created_at"] for e in body["columns"]] == sorted(e["created_at"] for e in body["columns"]),
        json.dumps(body, ensure_ascii=False)[:300],
    )

    # ── Вторая остановка: outlier-flag ───────────────────────────────
    r = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["cargo_kt"], "strategy": "flag", "method": "iqr", "param": 1.5, "apply": True},
    )
    ok = r.status_code == 200 and r.json()["added_columns"] == ["cargo_kt_outlier_flag"]
    body = client.get(URL).json()
    stages = [e["stage"] for e in body["columns"]]
    check(
        "B05: вторая остановка -- 3 записи, стадии missing/missing/outliers, created_at монотонны",
        ok and body["total"] == 3 and stages == ["missing", "missing", "outliers"]
        and [e["created_at"] for e in body["columns"]] == sorted(e["created_at"] for e in body["columns"]),
        json.dumps(body, ensure_ascii=False)[:300],
    )

    # ── GET read-only глубже repo-пина ────────────────────────────────
    session = _session()
    rev_before = _data_revision()
    upd_before = session.updated_at
    snapshot_df = session.dataframe.copy(deep=True)
    snapshot_reg = dict(session.derived_columns or {})
    ok1 = client.get(URL).status_code == 200
    ok2 = client.get(URL).status_code == 200
    same = (
        _data_revision() == rev_before
        and session.updated_at == upd_before
        and session.dataframe.equals(snapshot_df)
        and dict(session.derived_columns or {}) == snapshot_reg
    )
    check("B06: GET ×2 read-only -- ревизия/updated_at/кадр/реестр нетронуты", ok1 and ok2 and same)

    # ── Смешанный запрос -- 422 ЦЕЛИКОМ ──────────────────────────────
    cols_before = _frame_columns()
    rev_before = _data_revision()
    r = client.post(DELETE_URL, json={"columns": ["calls_missing_flag", "month"]})
    offending = r.json().get("detail", "") if r.status_code == 422 else ""
    check(
        "B07: смешанный [производная, month] -- 422 целиком, offending в detail, кадр/ревизия целы",
        r.status_code == 422 and "month" in offending
        and _frame_columns() == cols_before and _data_revision() == rev_before,
        f"status={r.status_code} detail={offending[:120]}",
    )

    # ── Каноническая колонка -- 422 ──────────────────────────────────
    r = client.post(DELETE_URL, json={"columns": ["calls"]})
    check(
        "B08: каноническая calls -- 422, ревизия без изменений, состав кадра байт-равен",
        r.status_code == 422 and _data_revision() == rev_before and _frame_columns() == cols_before,
        f"status={r.status_code}",
    )

    # ── Ядро сценария: delete 1 из 3 ─────────────────────────────────
    r = client.post(DELETE_URL, json={"columns": ["cargo_kt_missing_flag"]})
    body = r.json() if r.status_code == 200 else {}
    registry = client.get(URL).json()
    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 5}).json()
    row_cols = set(rows["columns"])
    check(
        "B09: ЯДРО -- удаление 1 из 3: 200, deleted, remaining_total==GET, строки без колонки, канонические целы, каскад реестра, счётчик dataset.columns -1",
        r.status_code == 200
        and body.get("deleted") == ["cargo_kt_missing_flag"]
        and body.get("remaining_total") == 2
        and registry["total"] == 2
        and "cargo_kt_missing_flag" not in row_cols
        and {"month", "calls", "cargo_kt", "calls_missing_flag", "cargo_kt_outlier_flag"} == row_cols
        and set(_session().derived_columns or {}) == {"calls_missing_flag", "cargo_kt_outlier_flag"}
        and int(_session().dataset.columns) == 5,
        f"status={r.status_code} body={json.dumps(body, ensure_ascii=False)[:150]}",
    )

    # ── Ревизия ровно +1 за удаление ─────────────────────────────────
    rev_after_first = _data_revision()
    check("B10a: ревизия выросла ровно на 1", rev_after_first == rev_before + 1, f"{rev_before} -> {rev_after_first}")
    r = client.post(DELETE_URL, json={"columns": ["calls_missing_flag"]})
    check("B10b: второе удаление -- ещё ровно +1", r.status_code == 200 and _data_revision() == rev_after_first + 1)

    # ── Дубли схлопнуты ──────────────────────────────────────────────
    r = client.post(DELETE_URL, json={"columns": ["cargo_kt_outlier_flag", "cargo_kt_outlier_flag"]})
    body = r.json() if r.status_code == 200 else {}
    check(
        "B11: дубли имени -- 200, deleted единожды, реестр пуст",
        r.status_code == 200 and body.get("deleted") == ["cargo_kt_outlier_flag"] and client.get(URL).json()["total"] == 0,
        json.dumps(body, ensure_ascii=False)[:150],
    )

    # ── Re-add: никаких скрытых долгов ───────────────────────────────
    r = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["calls"], "strategy": "flag", "apply": True},
    )
    body = client.get(URL).json()
    check(
        "B12: re-add заново регистрирует (нет скрытых долгов)",
        r.status_code == 200 and r.json()["added_columns"] == ["calls_missing_flag"]
        and body["total"] == 1 and body["columns"][0]["column"] == "calls_missing_flag",
        json.dumps(body, ensure_ascii=False)[:200],
    )

    # ── B14: контракт ответа + отсутствие строк ──────────────────────
    r = client.post(DELETE_URL, json={"columns": ["calls_missing_flag"]})
    body = r.json()
    got = client.get(URL).json()["total"]
    check(
        "B14: контракт delete -- deleted list[str], remaining_total int == GET total, строк в ответе нет",
        r.status_code == 200
        and isinstance(body["deleted"], list) and all(isinstance(x, str) for x in body["deleted"])
        and isinstance(body["remaining_total"], int) and body["remaining_total"] == got
        and set(body.keys()) == {"deleted", "remaining_total"},
        json.dumps(body, ensure_ascii=False)[:150],
    )

    # ── B15: устаревшая запись реестра (удаление мимо реестра) ───────
    r = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["cargo_kt"], "strategy": "flag", "apply": True},
    )
    assert r.status_code == 200 and r.json()["added_columns"] == ["cargo_kt_missing_flag"], r.text
    _session().dataframe = _session().dataframe.drop(columns=["cargo_kt_missing_flag"])  # мимо реестра
    body = client.get(URL).json()
    names = [e["column"] for e in body["columns"]]
    r = client.post(DELETE_URL, json={"columns": ["cargo_kt_missing_flag"]})
    check(
        "B15 guard: запись без колонки в кадре -- GET не отдаёт (append-only ∩ кадр), POST -- 422",
        "cargo_kt_missing_flag" not in names and r.status_code == 422,
        f"names={names} status={r.status_code}",
    )

    # ── B16 guard: пустой список ─────────────────────────────────────
    r = client.post(DELETE_URL, json={"columns": []})
    check("B16 guard: пустой список columns -- 422", r.status_code == 422, f"status={r.status_code}")

    # ── B13: персистенция на РЕАЛЬНОМ Redis-бэкенде (fakeredis) ──────
    # Полный production-путь: upload → 3 флага → delete 1 → save → get
    # из RAW-хранилища (Memory-бэкенд хранит ссылку и маскирует потерю).
    reset_session_store_for_testing()
    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeStrictRedis(server=fake_server)
    session_store_module._store = RedisSessionStore(client=fake_client, ttl_seconds=3600)
    try:
        client.cookies.clear()
        _upload(_port_calls_frame(), name="port_calls_redis.csv")
        r = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["calls", "cargo_kt"], "strategy": "flag", "apply": True},
        )
        assert r.status_code == 200 and len(r.json()["added_columns"]) == 2, r.text
        r = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["cargo_kt"], "strategy": "flag", "method": "iqr", "param": 1.5, "apply": True},
        )
        assert r.status_code == 200, r.text
        r = client.post(DELETE_URL, json={"columns": ["cargo_kt_missing_flag"]})
        assert r.status_code == 200, r.text

        sid = client.cookies.get(SESSION_COOKIE_NAME)
        reloaded = session_store_module.get_session_store().get(sid)
        cols = [str(c) for c in reloaded.dataframe.columns]
        registry = set(reloaded.derived_columns or {})
        ok_roundtrip = (
            "cargo_kt_missing_flag" not in cols
            and registry == {"calls_missing_flag", "cargo_kt_outlier_flag"}
        )
        # RAW-документ Redis (production JSON) несёт состав после удаления.
        raw_keys = list(fake_client.keys("*"))
        raw_ok = False
        for key in raw_keys:
            try:
                doc = json.loads(fake_client.get(key))
            except Exception:
                continue
            if isinstance(doc, dict) and "derived_columns" in doc:
                raw_ok = raw_ok or (
                    "cargo_kt_missing_flag" not in (doc.get("derived_columns") or {})
                    and set((doc.get("derived_columns") or {})) == {"calls_missing_flag", "cargo_kt_outlier_flag"}
                )
        check(
            "B13: Redis-персистенция (fakeredis): save→get roundtrip -- кадр и каскад реестра пережили хранилище; RAW JSON согласован",
            ok_roundtrip and raw_ok,
            f"cols={cols} registry={sorted(registry)} raw_ok={raw_ok}",
        )
    finally:
        fake_client.flushall()
        session_store_module._store = None
        reset_session_store_for_testing()

    # ── Итог ──────────────────────────────────────────────────────────
    failed = [r for r in _RESULTS if not r[1]]
    print("", flush=True)
    print(f"ИТОГО: {len(_RESULTS) - len(failed)}/{len(_RESULTS)} PASSED", flush=True)
    out = Path(__file__).with_name("dvecert_backend_oracles.txt")
    with out.open("w", encoding="utf-8") as fh:
        fh.write("Оракулы сертификации DATASET-VIEW-EDITOR-1-CERT -- бэкенд (свои данные, «порт-звонки»)\n")
        fh.write("=" * 78 + "\n")
        for oid, ok, detail in _RESULTS:
            fh.write(f"[{'PASSED' if ok else 'FAILED'}] {oid}" + (f" -- {detail}" if detail and not ok else "") + "\n")
        fh.write(f"\nИТОГО: {len(_RESULTS) - len(failed)}/{len(_RESULTS)} PASSED\n")
    print(f"Протокол: {out}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
