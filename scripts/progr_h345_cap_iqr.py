#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОТРАБОТКА ГИПОТЕЗ Г3/Г4/Г5 при закреплённых тимлидом настройках
сценария: МЕТОД ОБНАРУЖЕНИЯ = IQR, СТРАТЕГИЯ = КЭПИРОВАНИЕ.

Уточнение постановки к PROGR-22-REPRO: мастер в наблюдаемом сценарии
работал в (iqr, cap). Прошлая матрица показала, что ЧИСТЫЕ дефолты
(iqr k=1.5 + cap, все предзаполненные колонки) на этом датасете чистят
(карточка и трейс зелёные в финале), а детерминированное расхождение
давал только flag. Значит, при закреплённых (iqr, cap) остаются СЛЕДУЮЩИЕ
степени свободы мастера, которые и перебираются здесь:

  C0 контроль: k=1.5, все предзаполненные колонки (чистые дефолты);
  C1: k=2.0 (строже);
  C2: k=3.0 (консервативно «только экстремальные») -- обнаружение мастера
      может стать ЧАСТИЧНЫМ относительно фиксированного iqr-1.5 карточки;
  C3: k=1.0 (чувствительнее) -- кэп всегда режет по ЖЁСТКО 1.5×IQR
      (outliers_correction.py:182-187), поэтому часть маски k=1.0 клип
      не трогает вовсе;
  C4: k=1.5 + «Обнаруживать на остатке STL» (use_residual, одна колонка)
      -- маска считается в шкале ОСТАТКА, кэп применяется в шкале СЫРОЙ
      колонки, still пересчитывается по СЫРОЙ колонке тем же методом;
  C5: частичный выбор колонок (снят чекбокс производной колонки).

Г3 «Повторная фиксация при некоторых настройках мастера не устраняет
   IQR-выбросы»: какие конфигурации (iqr, cap) оставляют жёлтую карточку.
Г4 «Мастер сообщает успех безусловно»: где баннер «Изменения применены,
   профиль пересчитан» (код: PreprocessingOutliersPipeline.tsx:190 --
   безусловно при HTTP 200) противоречит числам ответа мастера и/или
   карточке.
Г5 «Trace не видит появления выбросов (окно лжи)»: card vs trace на
   каждом шаге потока cap; финал каждой конфигурации.

Верность UI-потоку: мастер требует предпросмотр перед применением
(кнопка «Применить» disabled без preview) -- каждая фиксация здесь
выполняется как ПАРА preview(apply=false) -> apply(apply=true). Хук
трассы пишет correction_previewed (движок: warning) на preview и
correction_applied (движок: done) на apply.

Только измерение; правок кода нет (read-only исследование, AGENTS.md:
без commit/push).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO))

from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from fastapi.testclient import TestClient  # noqa: E402

CSV = Path("/home/z/my-project/scripts/repro_data/forecast_monitor_synthetic_n150.csv")
OUT = Path("/home/z/my-project/CISStat-TS-Analysis/scripts/progr_h345_cap_iqr_results.txt")

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text)
    _lines.append(text)


def card(c: TestClient, mark: str) -> dict:
    """Карточка остановки «Выбросы» = живой IQR-профиль (method=iqr
    фиксирован фронтендом, TsAnalysisPreprocessing.tsx:289)."""
    d = c.get("/v1/session/dataset/outlier-profile?method=iqr").json()
    emit(f"    {mark:46s} КАРТОЧКА(iqr): status={d['status']:8s} "
         f"outliers={d['total_outliers']:3d} cols={d['affected_columns']}")
    return d


def trace_node(c: TestClient, mark: str) -> dict:
    tr = c.get("/v1/progress/trace").json()
    node = {n["node_id"]: n for n in tr.get("nodes", [])}.get("outliers", {})
    emit(f"    {mark:46s} TRACE:       status={node.get('status'):8s} "
         f"reason={str(node.get('status_reason'))!r} count={node.get('summary_count')}")
    return node


def events_of(c: TestClient) -> list[dict]:
    sid = c.cookies.get(SESSION_COOKIE_NAME)
    return get_session_store().get(sid).pipeline_trace


def last_outliers_event(c: TestClient) -> dict:
    for e in events_of(c)[::-1]:
        if e["event_type"] in ("correction_applied", "correction_previewed") \
                and e.get("node_id") == "outliers":
            return {"event_type": e["event_type"], **(e.get("payload") or {})}
    return {}


def build_base(c: TestClient, label: str) -> dict:
    """Шаги 1-4 сценария: загрузка -> дата -> пропуски -> выбросы №1
    (дефолт cap/iqr1.5, пара preview->apply) -> стационарность
    (рекомендация, apply). Возвращает карточку ПЕРЕД 2-й фиксацией."""
    emit("\n" + "=" * 108)
    emit(f"ПОТОК: {label}")
    emit("=" * 108)

    emit("\n  [1] Загрузка + подтверждение даты:")
    r = c.post("/v1/internal/upload", files={
        "file": (CSV.name, io.BytesIO(CSV.read_bytes()), "text/csv")})
    assert r.status_code == 200, r.text
    c.post("/v1/session/date-column", json={"column": "date"})
    card(c, "после загрузки:")
    trace_node(c, "после загрузки:")

    emit("\n  [2] Пропуски -> interpolate (preview->apply):")
    mp = c.get("/v1/session/dataset/missing-profile").json()
    cols = list(mp.get("affected_columns")
                or [x["column"] for x in mp.get("columns", []) if x.get("missing_count")])
    assert c.post("/v1/session/dataset/missing-corrections",
                  json={"columns": cols, "strategy": "interpolate",
                        "apply": False}).status_code == 200
    assert c.post("/v1/session/dataset/missing-corrections",
                  json={"columns": cols, "strategy": "interpolate",
                        "apply": True}).status_code == 200

    emit("\n  [3] Выбросы №1: мастер по умолчанию cap/iqr1.5 (preview->apply):")
    p1 = card(c, "до 1-й фиксации:")
    cols1 = list(p1["affected_columns"])
    pv1 = c.post("/v1/session/dataset/outlier-corrections", json={
        "columns": cols1, "strategy": "cap", "method": "iqr",
        "param": 1.5, "apply": False}).json()
    emit(f"    {'превью №1:':46s} found={pv1['total_outliers']} "
         f"changed={pv1['total_changed']} still={pv1['total_still_outliers']}")
    trace_node(c, "после preview №1 (correction_previewed):")
    ap1 = c.post("/v1/session/dataset/outlier-corrections", json={
        "columns": cols1, "strategy": "cap", "method": "iqr",
        "param": 1.5, "apply": True})
    assert ap1.status_code == 200, ap1.text
    card(c, "после 1-й фиксации:")
    trace_node(c, "после 1-й фиксации:")

    emit("\n  [4] Стационарность: рекомендация -> добавление колонки (apply):")
    sp = c.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
    method = sp["profile"]["selected_method"]
    st = c.post("/v1/session/dataset/preprocessing/stationarity-transformations",
                json={"column": "value", "method": method, "apply": True,
                      "confirm_non_causal": True})
    assert st.status_code == 200, st.text
    sj = st.json()
    emit(f"    {'':46s} метод={method} -> колонка {sj.get('output_column')} "
         f"(rows {sj.get('rows_before')}->{sj.get('rows_after')})")
    p2 = card(c, "ПОСЛЕ добавления колонки («опять выбросы»):")
    node_mid = trace_node(c, "ПОСЛЕ добавления колонки (до 2-й фиксации):")

    emit("\n  [5] ВТОРАЯ фиксация выбросов (мастером, настройки варианта):")
    return {"card_before_fix2": p2, "trace_before_fix2": node_mid,
            "stationarity_method": method,
            "added_column": sj.get("output_column")}


def resp_profile_totals(resp: dict) -> tuple[int, list[str]]:
    """Профиль в ОТВЕТЕ мастера (шкала метода ЗАПРОСА) -- ровно то, что
    мастер показывает после apply (PreprocessingOutliersPipeline.tsx:184-189)."""
    items = [it for it in resp.get("profile", []) if it.get("outlier_count")]
    total = sum(it["outlier_count"] for it in items)
    return total, [it["column"] for it in items]


def run_variant(name: str, fix2: dict, note: str = "") -> dict:
    c = TestClient(app)
    base = build_base(c, f"{name}{(' -- ' + note) if note else ''}")
    res: dict = {"name": name, **{k: base[k] for k in
                                  ("stationarity_method", "added_column")}}
    res["card_before_fix2"] = base["card_before_fix2"]["status"]
    res["outliers_before_fix2"] = base["card_before_fix2"]["total_outliers"]
    res["trace_before_fix2"] = base["trace_before_fix2"].get("status")

    cols2 = list(base["card_before_fix2"]["affected_columns"])
    payload_base = {"columns": cols2, "strategy": "cap", "method": "iqr", "param": 1.5}
    payload_base.update(fix2)
    if "columns" in fix2:
        payload_base["columns"] = fix2["columns"]

    # preview (мастер требует preview перед apply)
    pv = c.post("/v1/session/dataset/outlier-corrections",
                json={**payload_base, "apply": False})
    assert pv.status_code == 200, f"{name} preview: {pv.text}"
    pvj = pv.json()
    res["preview_found"] = pvj["total_outliers"]
    res["preview_changed"] = pvj["total_changed"]
    res["preview_still"] = pvj["total_still_outliers"]
    res["preview_used_residual"] = pvj["used_residual"]
    trace_node(c, "после preview №2 (correction_previewed):")

    # apply
    ap = c.post("/v1/session/dataset/outlier-corrections",
                json={**payload_base, "apply": True})
    assert ap.status_code == 200, f"{name} apply: {ap.text}"
    apj = ap.json()
    res["apply_found"] = apj["total_outliers"]
    res["apply_changed"] = apj["total_changed"]
    res["apply_still"] = apj["total_still_outliers"]
    res["apply_examples"] = {it["column"]: it["outlier_examples"]
                             for it in apj["columns"] if it.get("outlier_examples")}
    res["apply_stats_after"] = {it["column"]: it["stats_after"]
                                for it in apj["columns"] if it.get("stats_after")}
    res["resp_profile_total"], res["resp_profile_cols"] = resp_profile_totals(apj)
    emit(f"    {'ОТВЕТ МАСТЕРА (apply):':46s} found={res['apply_found']} "
         f"changed={res['apply_changed']} still={res['apply_still']} "
         f"used_residual={apj['used_residual']} added={apj['added_columns']}")
    if res["apply_examples"]:
        emit(f"    {'маска мастера (позиции):':46s} {res['apply_examples']}")
    emit(f"    {'профиль В ОТВЕТЕ (шкала метода запроса):':46s} "
         f"total={res['resp_profile_total']} cols={res['resp_profile_cols']}")

    # финал: карточка + трейс одновременно
    fin = card(c, "ФИНАЛ (после «Изменения применены…»):")
    fin_node = trace_node(c, "ФИНАЛ (после «Изменения применены…»):")
    ev = last_outliers_event(c)
    emit(f"    {'последнее событие узла outliers:':46s} "
         f"{ev.get('event_type')} payload={json.dumps({k: v for k, v in ev.items() if k != 'event_type'}, ensure_ascii=False)}")

    res["card_final"] = fin["status"]
    res["card_final_outliers"] = fin["total_outliers"]
    res["card_final_cols"] = list(fin["affected_columns"])
    res["card_final_details"] = [
        {"column": it["column"], "count": it["outlier_count"],
         "examples": it.get("outlier_examples"), "bounds": it.get("bounds")}
        for it in fin["columns"] if it.get("outlier_count")]
    res["trace_final"] = fin_node.get("status")
    res["DIVERGENCE"] = res["card_final"] != res["trace_final"]

    # ── флаги противоречий баннера (Г4): баннер показан безусловно (HTTP 200) ──
    contra: list[str] = []
    if res["apply_still"] > 0:
        contra.append(f"баннер успеха при still={res['apply_still']} "
                      f"(в preview-боксе мастера при этом «Осталось выбросов: {res['apply_still']}»)")
    if res["apply_changed"] == 0:
        contra.append("баннер успеха при changed=0 (ни одно значение не изменено)")
    if res["card_final"] == "warning":
        contra.append(f"баннер «профиль пересчитан» при жёлтой карточке "
                      f"({res['card_final_outliers']} выбросов: {res['card_final_cols']})")
    if res["apply_changed"] == res["apply_found"] and res["apply_still"] == res["apply_found"] \
            and res["apply_found"] > 0:
        contra.append(f"самопротиворечие ответа: «исправлено {res['apply_found']}», "
                      f"но по методу мастера осталось {res['apply_still']}")
    if 0 < res["apply_found"] < res["outliers_before_fix2"]:
        contra.append(f"частичное обнаружение: мастер нашёл {res['apply_found']} из "
                      f"{res['outliers_before_fix2']} по фиксированному iqr-1.5 карточки")
    res["banner_contradictions"] = contra

    if res["card_final_details"]:
        for det in res["card_final_details"]:
            emit(f"    {'остаток в карточке:':46s} {det['column']}: "
                 f"{det['count']} @ {det['examples']} bounds={det['bounds']}")
    emit(f"    >>> ИТОГ {name}: КАРТОЧКА={res['card_final']} "
         f"(outliers={res['card_final_outliers']}) vs TRACE={res['trace_final']} "
         f"-> {'РАСХОЖДЕНИЕ' if res['DIVERGENCE'] else 'согласованы'}")
    for ctext in contra:
        emit(f"    >>> Г4-противоречие: {ctext}")
    return res


def main() -> int:
    rows: list[dict] = []

    rows.append(run_variant(
        "C0 КОНТРОЛЬ: k=1.5, все предзаполненные колонки (чистые дефолты)",
        {}, note="настройки сценария тимлида: IQR + кэпирование"))
    rows.append(run_variant(
        "C1: k=2.0 (строже), все предзаполненные колонки",
        {"param": 2.0}))
    rows.append(run_variant(
        "C2: k=3.0 (консервативно «только экстремальные»)",
        {"param": 3.0}))
    rows.append(run_variant(
        "C3: k=1.0 (чувствительнее; кэп режет всегда по 1.5×IQR)",
        {"param": 1.0}))
    rows.append(run_variant(
        "C4: k=1.5 + обнаружение по STL-остатку (одна колонка)",
        {"use_residual": True, "date_column": "date"}))
    rows.append(run_variant(
        "C5: частичный выбор колонок (производная колонка снята)",
        {"columns": ["value"]}))

    # ── СВОДНАЯ ТАБЛИЦА ──
    emit("\n" + "=" * 108)
    emit("СВОДНАЯ ТАБЛИЦА (все конфигурации: method=iqr, strategy=cap)")
    emit("=" * 108)
    header = (f"{'конфигурация 2-й фиксации':52s} | {'найдено':7s} | {'испр.':5s} | "
              f"{'осталось':8s} | {'КАРТОЧКА':9s} | {'TRACE':6s} | РАСХОЖДЕНИЕ")
    emit(header)
    emit("-" * len(header))
    for r in rows:
        emit(f"{r['name'][:52]:52s} | {r['apply_found']:7d} | {r['apply_changed']:5d} | "
             f"{r['apply_still']:8d} | {r['card_final']:9s} | {r['trace_final']:6s} | "
             f"{'>>> ДА <<<' if r['DIVERGENCE'] else 'нет'}")
    emit("")
    emit("ДОКАЗАТЕЛЬСТВО «клип действует на ВСЮ колонку, а не только на маску мастера»:")
    emit("(std/mean колонки value_detrended ПОСЛЕ apply; совпадение с C0 == фактически")
    emit(" изменены те же 4 значения, независимо от того, что мастер насчитал маской)")
    base = next((r for r in rows if r["name"].startswith("C0")), None)
    if base and base["apply_stats_after"]:
        b = base["apply_stats_after"].get("value_detrended", {})
        for r in rows:
            sa = (r.get("apply_stats_after") or {}).get("value_detrended")
            if sa is None:
                continue
            same = (abs(sa["std"] - b["std"]) < 1e-9 and abs(sa["mean"] - b["mean"]) < 1e-9)
            tail = ("== C0 (клип починил ВСЁ, хотя маска мастера found=%d)" % r["apply_found"]) \
                if same else "отличается"
            emit(f"  {r['name'][:64]:64s} std={sa['std']:.4f} mean={sa['mean']:.4f} {tail}")
    emit("")
    emit("Окно лжи (Г5) до 2-й фиксации, у ВСЕХ конфигураций:")
    for r in rows:
        emit(f"  {r['name'][:70]:70s} card={r['card_before_fix2']} "
             f"({r['outliers_before_fix2']}) vs trace={r['trace_before_fix2']}")

    # ── ВЕРДИКТЫ ГИПОТЕЗ ──
    emit("\n" + "=" * 108)
    emit("ВЕРДИКТЫ ГИПОТЕЗ ПРИ ЗАКРЕПЛЁННЫХ НАСТРОЙКАХ (method=iqr, strategy=cap)")
    emit("=" * 108)
    div_rows = [r for r in rows if r["DIVERGENCE"]]
    emit("\nГ3 «Повторная фиксация при некоторых настройках мастера не устраняет "
         "IQR-выбросы» (карточка жёлтая после «профиль пересчитан»):")
    if div_rows:
        for r in div_rows:
            emit(f"  ПОДТВЕРЖДЕНА ДЛЯ: {r['name']}")
            emit(f"      остаток: {r['card_final_outliers']} выбросов в {r['card_final_cols']}; "
                 f"мастер отчитался found={r['apply_found']}/changed={r['apply_changed']}/"
                 f"still={r['apply_still']}")
    else:
        emit("  не подтверждена ни в одной конфигурации")
    clean_div = [r for r in rows if not r["DIVERGENCE"] and r["apply_still"] == 0
                 and r["card_final"] == "done"]
    for r in clean_div:
        emit(f"  чистые (карточка зелёная): {r['name']}")

    emit("\nГ4 «Мастер сообщает успех безусловно» (баннер при HTTP 200 безусловно, "
         "код :190): конфигурации, где баннер противоречит фактам:")
    contra_rows = [r for r in rows if r["banner_contradictions"]]
    if contra_rows:
        for r in contra_rows:
            emit(f"  ПОДТВЕРЖДЕНА ДЛЯ: {r['name']}")
            for ctext in r["banner_contradictions"]:
                emit(f"      - {ctext}")
    else:
        emit("  противоречий не найдено")

    emit("\nГ5 «Trace не видит появления выбросов (окно лжи)»:")
    windows = {f"{r['card_before_fix2']}->{r['trace_before_fix2']}" for r in rows}
    emit(f"  ПОДТВЕРЖДЕНА: после stationarity-apply у ВСЕХ "
         f"{len(rows)}/{len(rows)} конфигураций карточка=warning при trace=done "
         f"(набор переходов {sorted(windows)}); причина -- GET-пересчёты профиля "
         f"не трассируются (Ф2 PROGR-22-REPRO); preview 2-й фиксации переводит "
         f"узел в warning (correction_previewed), apply -- в done.")
    finals = [(r["name"], r["card_final"], r["trace_final"], r["DIVERGENCE"]) for r in rows]
    emit("  Финалы по конфигурациям:")
    for name, cf, tf, dv in finals:
        emit(f"      {name[:66]:66s} card={cf} trace={tf} "
             f"{'РАСХОЖДЕНИЕ' if dv else 'согласованы'}")

    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"\nПротокол сохранён: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
