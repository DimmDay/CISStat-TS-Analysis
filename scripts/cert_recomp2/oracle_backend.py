# scripts/cert_recomp2/oracle_backend.py
#
# UPLOAD-RECOMP-2-CERT (2026-10-20): ОРАКУЛЫ НА СВОИХ ДАННЫХ (канал oracle)
# независимой сертификации серии UPLOAD-RECOMP-2 (8db2d81) + FIX (8782abd)
# + DECOMP (39c001d) на базе main@0ee3ffe.
#
# Корпус СВОЙ, дизъюнктен repo-корпусам (tests/api/test_panel_transforms.py,
# tests/api/test_session_date_column.py) и корпусам прошлых сертификаций:
#   * «Волжские склады» -- панель 3 сущности (delta/epsilon/zeta) x 120
#     дневных дат (2023-01-01..2023-04-30), revenue с РУЧНОЙ арифметикой
#     (100+2d / 200+2d / 300+2d по датам d=0..119 -- mean/sum/min/max
#     проверяются точными значениями), нечисловая note (first-агрегация);
#     дневная сетка выбрана под гейт декомпозиции (2 полных периода);
#   * «Смешанный журнал» -- week_log: 24 даты DD.MM.YYYY + 16 "б/н"
#     (score 0.6 < 0.7 -- оракул снятия гейта ЯВНЫМ подтверждением;
#     "б/н" не схлопывается в NaN при CSV-круговороте, в отличие от
#     "n/a" -- первая версия корпуса ошибалась именно здесь);
#   * «Короткая сущность» -- сущность с 12 строками (< паспортного
#     минимума 30) -- честный отказ ДО apply;
#   * «Мусорная мемо» -- колонка без дат вообще (crash-guard: 422, не 500).
#
# Запуск: python3 scripts/cert_recomp2/oracle_backend.py
# Канал repo для мутационной кампании: tests/api/test_panel_transforms.py +
# tests/api/test_session_date_column.py (см. mutations.py).
from __future__ import annotations

import io
import os
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

# Слой 2 (research_runs) в песочнице сертификации -- in-memory: битый
# DSN DATABASE_URL свежей песочницы (задокументированный средовый класс
# падений тестов) не должен смешивать артефакты среды с контрактами.
os.environ["DATABASE_URL"] = ""

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import reset_session_store_for_testing  # noqa: E402

client = TestClient(app)

RESULTS: list[tuple[bool, str]] = []


def check(cond: bool, name: str) -> None:
    RESULTS.append((bool(cond), name))
    print(("PASS " if cond else "FAIL ") + name)


def _upload_df(df: pd.DataFrame, name: str = "cert_volga.csv") -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": (name, buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def _rows() -> list:
    resp = client.get("/v1/session/dataset/rows?offset=0&limit=1000")
    assert resp.status_code == 200, resp.text
    return resp.json()["rows"]


def _cols() -> list[str]:
    resp = client.get("/v1/session/dataset/rows?offset=0&limit=1")
    return resp.json()["columns"]


def _trace_node(node_id: str) -> dict | None:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # node_id в трассе -- БЕЗ префикса стадии (stage -- отдельное поле):
    # "upload/structure" -- это stage="upload" + node_id="structure".
    for state in data.get("nodes") or []:
        if f"{state.get('stage')}/{state.get('node_id')}" == node_id:
            return state
    return None


# ── СВОЙ корпус ──────────────────────────────────────────────────────────

DATES = pd.date_range("2023-01-01", periods=120, freq="D")


def volga_panel() -> pd.DataFrame:
    """3 сущности x 120 дат; revenue: delta=100+2d, epsilon=200+2d,
    zeta=300+2d (d -- индекс даты) -- mean=200+2d, sum=600+6d, min=100+2d,
    max=300+2d, median=200+2d; note = f"{e[0]}{d}" (first-агрегация)."""
    rows = []
    for d, day in enumerate(DATES):
        for e, base in (("delta", 100), ("epsilon", 200), ("zeta", 300)):
            rows.append({
                "week": day.strftime("%Y-%m-%d"),
                "company": e,
                "revenue": float(base + 2 * d),
                "note": f"{e[0]}{d}",
            })
    return pd.DataFrame(rows)


def mixed_journal() -> pd.DataFrame:
    """week_log: 24 даты DD.MM.YYYY + 16 'б/н' -- score 0.6 (<0.7),
    24 валидные даты (>= 2) -- колонка приводима, но низко-score."""
    good = pd.date_range("2023-01-01", periods=40, freq="D").strftime("%d.%m.%Y").tolist()
    return pd.DataFrame({"week_log": good[:24] + ["б/н"] * 16, "value": list(range(40))})


def short_entity_panel() -> pd.DataFrame:
    """zeta -- только 12 строк (последние 12 дат): фильтр по zeta --
    меньше паспортного минимума 30 -- честный 422."""
    full = volga_panel()
    zeta = full[full["company"] == "zeta"].tail(12)
    return pd.concat([full[full["company"] != "zeta"], zeta], ignore_index=True)


# ── O01–O05: entity-filter ───────────────────────────────────────────────

def o01_no_dataset_404() -> None:
    reset_session_store_for_testing()
    r = client.post("/v1/session/dataset/entity-filter", json={"entity_col": "company", "value": None, "apply": False})
    check(r.status_code == 404, "O01 entity-filter без датасета -- 404")
    r = client.post("/v1/session/dataset/panel-aggregate", json={"date_col": "week", "func": "mean", "apply": False})
    check(r.status_code == 404, "O01b panel-aggregate без датасета -- 404")


def o02_available_values() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/dataset/entity-filter", json={"entity_col": "company", "value": None, "apply": False})
    body = r.json()
    check(r.status_code == 200 and body["available_values"] == ["delta", "epsilon", "zeta"],
          "O02 доступные значения -- [delta, epsilon, zeta]")
    check(body["n_rows_before"] == 360 and body["n_rows_after"] is None,
          "O02b опрос без значения: 360 строк, статистики сведения не выдаются")


def o03_preview_no_mutation() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    before = _rows()
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "company", "date_col": "week", "value": "epsilon", "apply": False})
    body = r.json()
    check(r.status_code == 200 and body["applied"] is False, "O03 preview applied=false")
    check(body["n_rows_before"] == 360 and body["n_rows_after"] == 120, "O03b preview 360 -> 120 строк")
    check(body["n_dates"] == 120 and body["date_min"] == "2023-01-01" and body["date_max"] == "2023-04-30",
          "O03c preview сетка: 120 дат, 2023-01-01..2023-04-30")
    check(_rows() == before, "O03d preview НЕ мутирует сессию (побайтный паритет строк)")


def o04_apply_keeps_entity_exact_values() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "company", "value": "delta", "apply": True})
    body = r.json()
    check(r.status_code == 200 and body["applied"] is True and body["n_rows_after"] == 120,
          "O04 apply delta: 120 строк")
    cols = _cols()
    rows = _rows()
    companies = {row[cols.index("company")] for row in rows}
    check(companies == {"delta"}, "O04b в датасете только delta")
    revenue = [float(row[cols.index("revenue")]) for row in rows]
    check(all(abs(v - (100 + 2 * i)) < 1e-9 for i, v in enumerate(revenue)),
          "O04c значения revenue сохранены точно (100+2i)")
    dataset = client.get("/v1/session/dataset").json()
    check(dataset["rows"] == 120, "O04d apply сохранён в сессии")


def o05_fail_closed() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "company", "value": "omega", "apply": False})
    check(r.status_code == 422 and "omega" in r.json()["detail"], "O05 неизвестное значение -- 422")
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "no_such_col", "value": None, "apply": False})
    check(r.status_code == 422, "O05b неизвестная entity-колонка -- 422")
    # Короткая сущность (12 строк < 30) -- отказ ДО apply.
    reset_session_store_for_testing()
    _upload_df(short_entity_panel())
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "company", "value": "zeta", "apply": False})
    check(r.status_code == 422 and "30" in r.json()["detail"],
          "O05c сущность короче паспортного минимума 30 -- честный 422")
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "company", "value": "zeta", "apply": True})
    check(r.status_code == 422, "O05d apply короткой сущности тоже 422 (fail-closed)")


# ── O06–O09: panel-aggregate ─────────────────────────────────────────────

def _agg_revenue(cols: list[str], rows: list) -> list[float]:
    return [float(row[cols.index("revenue")]) for row in rows]


def o06_mean_exact_arithmetic() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    before = _rows()
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "week", "entity_col": "company", "func": "mean", "apply": False})
    body = r.json()
    check(r.status_code == 200 and body["applied"] is False and body["n_rows_after"] == 120,
          "O06 mean preview: 120 агрегатов")
    check(_rows() == before, "O06b mean preview НЕ мутирует")
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "week", "entity_col": "company", "func": "mean", "apply": True})
    body = r.json()
    check(r.status_code == 200 and body["applied"] is True, "O06c mean apply")
    check(body["n_rows_before"] == 360 and body["n_rows_after"] == 120 and body["n_dates"] == 120,
          "O06d summary 360 -> 120, 120 дат")
    check(body["n_dates_skipped"] == 0, "O06e без пропусков skipped=0")
    check("company" in body["dropped_columns"], "O06f entity-колонка удалена с пометкой")
    check("revenue" in body["numeric_columns"] and "note" in body["first_kept_columns"],
          "O06g числовая mean, нечисловая first")
    cols = _cols()
    check("company" not in cols, "O06h company отсутствует в результате")
    revenue = _agg_revenue(cols, _rows())
    check(all(abs(v - (200 + 2 * d)) < 1e-9 for d, v in enumerate(revenue)),
          "O06i mean-арифметика точна: (100+2d + 200+2d + 300+2d)/3 = 200+2d")


def o07_sum_min_max_median() -> None:
    cases = (
        ("sum", lambda d: 600 + 6 * d),
        ("min", lambda d: 100 + 2 * d),
        ("max", lambda d: 300 + 2 * d),
        ("median", lambda d: 200 + 2 * d),
    )
    for func, expect in cases:
        reset_session_store_for_testing()
        _upload_df(volga_panel())
        r = client.post("/v1/session/dataset/panel-aggregate",
                        json={"date_col": "week", "entity_col": "company", "func": func, "apply": True})
        cols = _cols()
        revenue = _agg_revenue(cols, _rows())
        d = 3  # контрольная 4-я дата
        check(r.status_code == 200 and abs(revenue[d] - expect(d)) < 1e-9,
              f"O07 {func}: revenue[3] == {expect(3)}")


def o08_nan_policy() -> None:
    reset_session_store_for_testing()
    df = volga_panel()
    mask = df["week"] == DATES[5].strftime("%Y-%m-%d")
    df.loc[mask, "revenue"] = None  # у ВСЕХ сущностей пропуск на этой дате
    _upload_df(df)
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "week", "entity_col": "company", "func": "mean", "apply": True})
    body = r.json()
    check(r.status_code == 200 and body["n_dates_skipped"] == 1 and body["n_dates"] == 119,
          "O08 дата без единого валидного значения отброшена со счётчиком (1, осталось 119)")


def o09_agg_fail_closed() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "nope", "entity_col": "company", "func": "mean", "apply": False})
    check(r.status_code == 404, "O09 неизвестная date-колонка -- 404")
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "week", "entity_col": "company", "func": "median_of_medians", "apply": False})
    check(r.status_code == 422, "O09b недопустимая функция -- 422")
    reset_session_store_for_testing()
    _upload_df(pd.DataFrame({
        "week": pd.date_range("2024-03-01", periods=8, freq="D").astype(str),
        "company": ["a", "b"] * 4,
        "label": ["x"] * 8,
    }))
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "week", "entity_col": "company", "func": "mean", "apply": False})
    check(r.status_code == 422 and "числов" in r.json()["detail"], "O09c нет числовых колонок -- 422")


# ── O10–O12: date-column confirmed ───────────────────────────────────────

def o10_confirmed_lifts_low_score_gate() -> None:
    reset_session_store_for_testing()
    _upload_df(mixed_journal(), "cert_journal.csv")
    # прежний контракт: без confirmed низко-score колонка отклоняется
    r = client.post("/v1/session/date-column", json={"column": "week_log", "confirmed": False})
    check(r.status_code == 422, "O10 score 0.6 без confirmed -- 422 (прежний контракт)")
    node = _trace_node("upload/structure")
    check(node is None or node.get("status") != "done", "O10b факт structure_confirmed не записан после отказа")
    # явное подтверждение снимает гейт
    r = client.post("/v1/session/date-column", json={"column": "week_log", "confirmed": True})
    check(r.status_code == 200, "O10c score 0.6 + confirmed=true -- 200 (гейт снят)")
    check(client.get("/v1/session/date-column").json()["date_column"] == "week_log",
          "O10d week_log сохранён как date_column")
    node = _trace_node("upload/structure")
    check(node is not None and node.get("status") == "done" and node.get("validity") == "current",
          "O10e трасса: узел upload/structure = done (structure_confirmed)")


def o11_marker_requires_confirmation() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/date-column", json={"column": "(не использовать)", "confirmed": False})
    check(r.status_code == 422, "O11 «(не использовать)» без confirmed -- 422")
    r = client.post("/v1/session/date-column", json={"column": "(не использовать)", "confirmed": True})
    check(r.status_code == 200 and client.get("/v1/session/date-column").json()["date_column"] is None,
          "O11b «(не использовать)» + confirmed -- 200, date_column=None")
    node = _trace_node("upload/structure")
    check(node is not None and node.get("status") == "done",
          "O11c «временной колонки нет» -- легитимное подтверждение, узел done")


def o12_content_requirements_and_crash_guard() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/date-column", json={"column": "revenue", "confirmed": True})
    check(r.status_code == 422, "O12 revenue не приводится к дате -- 422 даже при confirmed")
    r = client.post("/v1/session/date-column", json={"column": "no_such", "confirmed": True})
    check(r.status_code == 404, "O12b несуществующая колонка -- 404")
    # < 2 валидных дат
    df = volga_panel().copy()
    df["day_hint"] = ["07.03.2024"] + ["?"] * (len(df) - 1)
    reset_session_store_for_testing()
    _upload_df(df)
    r = client.post("/v1/session/date-column", json={"column": "day_hint", "confirmed": True})
    check(r.status_code == 422, "O12c одна валидная дата -- 422 даже при confirmed")
    # crash-guard: мусорная колонка -- честный 422, не 500
    df2 = volga_panel().copy()
    df2["memo"] = ["заметка " + str(i) for i in range(len(df2))]
    reset_session_store_for_testing()
    _upload_df(df2)
    r = client.post("/v1/session/date-column", json={"column": "memo", "confirmed": True})
    check(r.status_code == 422, "O12d мусорная колонка при confirmed -- честный 422 (crash-guard, не 500)")
    # crash-guard на ПУТИ ИСКЛЮЧЕНИЯ smart_to_datetime: год-only колонка с
    # нечисловым мусором (н/д) -- year_only-ветка astype('Int64') бросает;
    # снятие crash-guard-мутантом (MS-09) обязано ловиться этим оракулом.
    df3 = volga_panel().copy()
    df3["year_mark"] = ["2020", "2021", "2022", "2023", "2024"] + ["н/д"] * (len(df3) - 5)
    reset_session_store_for_testing()
    _upload_df(df3)
    r = client.post("/v1/session/date-column", json={"column": "year_mark", "confirmed": True})
    check(r.status_code == 422 and "не приводится" in r.json()["detail"],
          "O12e год-only колонка с «н/д» мусором -- 422 «не приводится» (крэш-путь smart_to_datetime)")


# ── O13: сценарий сертификации «панель -> микросервис -> декомпозиция» ───

def o13_panel_to_series_to_decomposition_entity_filter() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    # декомпозиция на ПАНЕЛИ -- честный отказ (дубликаты дат)
    r = client.get("/v1/session/dataset/decomposition?column=revenue&date_column=week")
    check(r.status_code == 200 and r.json()["applicable"] is False,
          "O13 панель до преобразования: декомпозиция applicable=false")
    # фильтр сущности -- панель становится однорядной
    r = client.post("/v1/session/dataset/entity-filter",
                    json={"entity_col": "company", "date_col": "week", "value": "zeta", "apply": True})
    check(r.status_code == 200, "O13b entity-filter apply zeta")
    # подтверждение структуры аналитиком (честный маршрут: после
    # преобразования аналитик подтверждает date-колонку)
    r = client.post("/v1/session/date-column", json={"column": "week", "confirmed": True})
    check(r.status_code == 200, "O13c подтверждение week после фильтра -- 200")
    r = client.get("/v1/session/dataset/decomposition?column=revenue&date_column=week")
    body = r.json()
    check(body["applicable"] is True, "O13d ПОСЛЕ преобразования декомпозиция applicable=true")
    r = client.get("/v1/session/dataset/decomposition-series?column=revenue&date_column=week")
    check(r.status_code == 200 and r.json().get("applicable") is True,
          "O13e ряды компонент (STL) отдаются")


def o13b_aggregate_path_decomposition() -> None:
    reset_session_store_for_testing()
    _upload_df(volga_panel())
    r = client.post("/v1/session/dataset/panel-aggregate",
                    json={"date_col": "week", "entity_col": "company", "func": "mean", "apply": True})
    check(r.status_code == 200, "O13-Aggregate apply mean")
    r = client.get("/v1/session/dataset/decomposition?column=revenue&date_column=week")
    check(r.status_code == 200 and r.json()["applicable"] is True,
          "O13b путь агрегации: декомпозиция applicable=true")


def main() -> int:
    o01_no_dataset_404()
    o02_available_values()
    o03_preview_no_mutation()
    o04_apply_keeps_entity_exact_values()
    o05_fail_closed()
    o06_mean_exact_arithmetic()
    o07_sum_min_max_median()
    o08_nan_policy()
    o09_agg_fail_closed()
    o10_confirmed_lifts_low_score_gate()
    o11_marker_requires_confirmation()
    o12_content_requirements_and_crash_guard()
    o13_panel_to_series_to_decomposition_entity_filter()
    o13b_aggregate_path_decomposition()
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\nORACLE BACKEND: {passed}/{total} PASS")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
