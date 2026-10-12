# scripts/prograudit4cert_oracles.py
# -*- coding: utf-8 -*-
"""СВОИ оракулы независимой сертификации PROGR-AUDIT-4-CERT.

Объект: коммит 0af1ea5 (PROGR-AUDIT-4 — outcome и детали коррекции:
единый вывод исхода changed/no_change/violations/clean/unknown, честные
статус/reason/бейдж, счётчик следует за reason-событием P16, невалидный
status — аномалия P15, параметры результата в dedupe P19). Аудит на
HEAD = 3322e4a (продуктовый код 0af1ea5; 1A-CERT добавил только
untracked-артефакты, затем закоммичен).

Принцип «оракулы на своих данных»: данные сертификатора ДИЗЪЮКТНЫ
данным оракула исполнителя (tests/api/test_progress_audit_4.py:
frame_with_missing a/b/c nan@(2,5,8)/(10,20), frame_clean a@20,
frame_spike seed=20261012 a[10]=40/b[30]=-35):
  * свои CSV-корпуса (гидрология/продажи/нагрузка/регулярность — свои
    имена колонок, свои seeds, свои позиции дефектов);
  * свои run_id (RUN-C4-…), свои event_id (c4-ev-…), свои контексты
    (c4-ctx-…);
  * свои наблюдательные методы (fold-доказательства, anomaly-счётчик,
    evidence-поля; e2e — через собственные корпуса).

Канал проверки: самодостаточный EXIT-код (0 = все PASS).
Группы: OUT (вывод исхода), RSN (reason-тексты), FLD (честная проекция
fold), EVD (evidence-outcome), PRJ (паритет редьюсера 5B-инвариантов
на коррекционных потоках), DQ (P19 dedupe параметров), PNL (панель e2e).

Запуск: python scripts/prograudit4cert_oracles.py [--protocol PATH]
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

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
    """Декоратор-харнесс: изоляция окружения на каждый оракул."""

    def wrap(fn):
        def run():
            global PASSES
            tmp = tempfile.mkdtemp(prefix="cert4-oracle-")
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

CSV_PURE = (
    "date,продажи\n"
    + "".join(f"2023-06-{d:02d},{120 + 3 * d}\n" for d in range(1, 17))
)  # чистый ряд «продажи»: 16 дней, без пропусков/выбросов

_HYDRO_LEVEL = [
    10.5 if i not in (1, 4, 7, 10) else None for i in range(40)
]
_HYDRO_FLOW = [2.2 if i != 3 else None for i in range(40)]
CSV_HYDRO = "date,уровень,расход,температура\n" + "".join(
    f"2023-07-{(i + 1):02d},{'' if v is None else v},{'' if f is None else f},{18 + (i % 5)}\n"
    for i, (v, f) in enumerate(zip(_HYDRO_LEVEL, _HYDRO_FLOW))
)  # гидрология: уровень 4 пропуска, расход 1, температура чистая

import numpy as np  # noqa: E402

_spike = np.random.default_rng(40407).normal(0.0, 1.0, 48)
_spike[20] = 60.0
CSV_SPIKE = "date,нагрузка\n" + "".join(
    f"2024-02-{(i % 28) + 1:02d}T{(i % 24):02d}:00,{v:.6f}\n"
    for i, v in enumerate(_spike)
)  # экстремальный выброс: iqr-1.5 и zscore-3.0 обязаны дать ОДНУ картину

CSV_REG = (
    "date,значение\n"
    "2024-03-02,5.0\n"
    "2024-03-01,1.0\n"
    "2024-03-02,7.0\n"
    "2024-03-03,3.0\n"
    "2024-03-01,2.0\n"
    "2024-03-04,4.0\n"
    "2024-03-03,9.0\n"
)  # неупорядоченные дубли дат: regularity sort -- пары до/после

from fastapi.testclient import TestClient  # noqa: E402

from app.core.node_status import (  # noqa: E402
    EVENT_NODE_REASON,
    NodeStateFold,
    CHECK_STATUS_VALUES,
    derive_node_statuses,
    derive_pipeline_node_states,
    derive_stage_states,
    event_to_dict,
    resolve_event_status,
)
# API AUDIT-4 (resolve_correction_outcome/correction_reason/
# DEDUPE_PARAM_KEYS/_event_params) импортируется ЛЕНИВО внутри
# оракулов: на базе 02ac7ff его нет -- тогда каждый оракул честно
# отказывает по-своему (RED-гранулярность), а не весь скрипт падает
# на module-level ImportError.

from apps.api.main import app  # noqa: E402

CLIENT = TestClient(app)

TS_A = "2026-10-12T09:15:00+00:00"
TS_B = "2026-10-12T09:16:00+00:00"
TS_C = "2026-10-12T09:17:00+00:00"
TS_D = "2026-10-12T09:18:00+00:00"


def _ev(
    event_id: str,
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str = TS_A,
    run_id: str = "RUN-C4-U1",
    context_id: str | None = None,
    actor: str = "user",
    **payload,
) -> dict:
    return {
        "event_id": event_id,
        "run_id": run_id,
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": payload,
        "actor": actor,
        "timestamp": ts,
        **({"context_id": context_id} if context_id else {}),
    }


def _fold_states(events: list) -> dict[tuple[str, str], dict]:
    return {
        (s["stage"], s["node_id"]): s
        for s in derive_pipeline_node_states(events)
    }


def _evidence_node(events: list, stage: str, node_id: str) -> dict:
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    return next(
        s
        for s in fold.node_states_with_evidence()
        if s["stage"] == stage and s["node_id"] == node_id
    )


def _evidence_fold(events: list) -> tuple[NodeStateFold, dict]:
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    idx = {
        (s["stage"], s["node_id"]): s
        for s in fold.node_states_with_evidence()
    }
    return fold, idx


def _upload(csv: str, name: str) -> dict:
    resp = CLIENT.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(csv.encode("utf-8")), "text/csv")},
    )
    if resp.status_code != 200:
        raise OracleFail(
            f"upload {name}: HTTP {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json()


def _trace_nodes() -> dict[tuple[str, str], dict]:
    data = CLIENT.get("/v1/progress/trace").json()
    return {(n["stage"], n["node_id"]): n for n in data["nodes"]}


def _trace_events(event_type: str, node_id: str) -> list[dict]:
    data = CLIENT.get("/v1/progress/trace").json()
    return [
        e
        for e in data["events"]
        if e.get("event_type") == event_type and e.get("node_id") == node_id
    ]


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise OracleFail(msg)


def _resolve_outcome(data):
    """Ленивый вызов API AUDIT-4 (на базе 02ac7ff -- ImportError = честный RED)."""
    from app.core.node_status import resolve_correction_outcome

    return resolve_correction_outcome(data)


def _correction_reason(event_type, outcome, remaining):
    from app.core.node_status import correction_reason

    return correction_reason(event_type, outcome, remaining)


# ── 1. OUT: единый вывод исхода коррекции (resolve_correction_outcome) ─


@oracle("OUT1")
def out1_preview_violations_positive():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o1", "preprocessing", "missing", "correction_previewed",
                total_missing=3, total_violations=3)
        )
        == "violations",
        "preview с нарушениями (>0) обязан быть violations",
    )


@oracle("OUT2")
def out2_preview_clean_zero():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o2", "preprocessing", "missing", "correction_previewed",
                total_missing=0)
        )
        == "clean",
        "preview с нулевой диагностикой -- clean (не violations)",
    )


@oracle("OUT3")
def out3_preview_no_facts_unknown():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o3", "preprocessing", "missing", "correction_previewed")
        )
        == "unknown",
        "preview без фактов -- unknown (легаси не фабрикует «Найдены "
        "нарушения», H14)",
    )


@oracle("OUT4")
def out4_preview_garbage_counts_unknown():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o4", "preprocessing", "missing", "correction_previewed",
                total_missing="3", total_outliers=True, total_invalid=-1,
                total_violations=2.5)
        )
        == "unknown",
        "строка/bool/отрицательное/дробь -- не факты (тот же щит, что "
        "_clean_summary_count): мусорные счётчики не дают исход",
    )


@oracle("OUT5")
def out5_apply_changed_positive():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o5", "preprocessing", "missing", "correction_applied",
                total_changed=4, total_still_missing=0)
        )
        == "changed",
        "apply с объёмом выполненного >0 -- changed",
    )


@oracle("OUT6")
def out6_apply_all_zero_no_change():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o6", "preprocessing", "missing", "correction_applied",
                total_changed=0, rows_removed=0, total_still_missing=0)
        )
        == "no_change",
        "apply со всеми нулевыми отчётами -- no_change (не done-фабрика)",
    )


@oracle("OUT7")
def out7_apply_fallback_pair():
    changed_ev = _ev("c4-ev-o7a", "validation", "regularity",
                     "correction_applied",
                     total_violations_before=5, total_violations_after=0)
    noop_ev = _ev("c4-ev-o7b", "validation", "regularity",
                  "correction_applied",
                  total_violations_before=5, total_violations_after=5)
    _expect(
        _resolve_outcome(changed_ev) == "changed",
        "fallback-пара до/после: remaining != before -- changed",
    )
    _expect(
        _resolve_outcome(noop_ev) == "no_change",
        "fallback-пара до/после: remaining == before -- no_change",
    )


@oracle("OUT8")
def out8_apply_half_pair_unknown():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o8", "validation", "data_types", "correction_applied",
                total_invalid=2)
        )
        == "unknown",
        "половина пары (только before -- convert-types total_invalid) -- "
        "честный unknown",
    )


@oracle("OUT9")
def out9_direct_facts_priority():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o9", "preprocessing", "missing", "correction_applied",
                total_changed=0, total_violations_before=4,
                total_violations_after=0)
        )
        == "no_change",
        "прямой отчёт объёма (total_changed=0) приоритетен fallback-паре: "
        "no_change, а не changed",
    )


@oracle("OUT10")
def out10_non_correction_type_unknown():
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o10", "upload", "overview", "upload_completed",
                rows=40, columns=4)
        )
        == "unknown",
        "не-коррекционный тип -- unknown (функция о качестве результата, "
        "не о классификации типа)",
    )


@oracle("OUT11")
def out11_first_valid_fact_by_key_order():
    # Документированная семантика «первый валидный счётчик из группы
    # по порядку ключей»: total_changed стоит в CORRECTION_CHANGED_KEYS
    # раньше rows_changed.
    _expect(
        _resolve_outcome(
            _ev("c4-ev-o11", "preprocessing", "missing", "correction_applied",
                rows_changed=2, total_changed=0)
        )
        == "no_change",
        "противоречивый синтетический payload: решает первый валидный "
        "факт по порядку ключей группы (total_changed=0) -- "
        "детерминизм documented-семантики",
    )


# ── 2. RSN: честные reason-тексты (correction_reason) ─────────────────


@oracle("RSN1")
def rsn1_canon_preview_violations():
    _expect(
        _correction_reason("correction_previewed", "violations", 3)
        == "Найдены нарушения: предпросмотр коррекции",
        "канонический текст violations-preview сохранён",
    )


@oracle("RSN2")
def rsn2_canon_apply_changed():
    _expect(
        _correction_reason("correction_applied", "changed", None)
        == "Коррекция применена",
        "канонический текст changed-apply сохранён",
    )
    _expect(
        _correction_reason("correction_applied", "changed", 0)
        == "Коррекция применена",
        "changed при remaining=0 -- тот же канонический текст",
    )


@oracle("RSN3")
def rsn3_partial_apply_text():
    _expect(
        _correction_reason("correction_applied", "changed", 2)
        == "Коррекция применена частично: нарушения остались",
        "changed при remaining>0 -- честный текст «применена частично»",
    )


@oracle("RSN4")
def rsn4_no_change_texts():
    _expect(
        _correction_reason("correction_applied", "no_change", None)
        == "Коррекция не изменила данные",
        "no_change без remaining -- «не изменила данные»",
    )
    _expect(
        _correction_reason("correction_applied", "no_change", 1)
        == "Коррекция не устранила нарушения",
        "no_change при remaining>0 -- «не устранила нарушения» "
        "(факт, не претензия)",
    )


@oracle("RSN5")
def rsn5_unknown_apply_no_claims():
    text = _correction_reason("correction_applied", "unknown", None)
    _expect(
        text == "Коррекция выполнена: исход не подтверждён",
        "unknown-apply: честная маркировка без утверждений о качестве",
    )
    for claim in ("применена", "устранила", "Найдены"):
        _expect(
            claim not in text,
            f"unknown-текст не утверждает качество ({claim!r} в тексте)",
        )


@oracle("RSN6")
def rsn6_clean_unknown_preview_texts():
    _expect(
        _correction_reason("correction_previewed", "clean", None)
        == "Нарушений не найдено: предпросмотр коррекции",
        "clean-preview -- честный текст «нарушений не найдено»",
    )
    _expect(
        _correction_reason("correction_previewed", "unknown", None)
        == "Предпросмотр коррекции выполнен",
        "unknown-preview -- только факт операции",
    )


@oracle("RSN7")
def rsn7_canon_dictionary_integrity():
    _expect(
        EVENT_NODE_REASON.get("correction_applied") == "Коррекция применена",
        "карта EVENT_NODE_REASON: канон apply не тронут (совместимость "
        "легаси-фолбэка resolve_event_status)",
    )
    _expect(
        EVENT_NODE_REASON.get("correction_previewed")
        == "Найдены нарушения: предпросмотр коррекции",
        "карта EVENT_NODE_REASON: канон preview не тронут",
    )


# ── 3. FLD: честная проекция fold (статус/reason/бейдж из исхода) ─────


@oracle("FLD1")
def fld1_clean_preview_does_not_color():
    state = _fold_states([
        _ev("c4-ev-f1", "preprocessing", "missing", "correction_previewed",
            TS_A, total_missing=0),
    ])
    node = state[("preprocessing", "missing")]
    _expect(
        node["status"] == "pending",
        "clean preview НЕ красит узел (статус не утверждается, P14)",
    )
    _expect(
        "Найдены нарушения" not in (node["status_reason"] or ""),
        "clean preview без причины «Найдены нарушения» (H14)",
    )
    _expect(
        node["status_reason"] == "Нарушений не найдено: предпросмотр коррекции",
        "reason честный: «нарушений не найдено»",
    )


@oracle("FLD2")
def fld2_violations_preview_warning_badge():
    state = _fold_states([
        _ev("c4-ev-f2", "preprocessing", "missing", "correction_previewed",
            TS_A, total_missing=4),
    ])
    node = state[("preprocessing", "missing")]
    _expect(node["status"] == "warning", "violations-preview -- warning")
    _expect(
        node["summary_count"] == 4,
        "бейдж preview -- найденные нарушения (диагностика до)",
    )


@oracle("FLD3")
def fld3_noop_apply_remaining_warning():
    state = _fold_states([
        _ev("c4-ev-f3", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=0, total_still_missing=3),
    ])
    node = state[("preprocessing", "missing")]
    _expect(
        node["status"] == "warning",
        "no-op apply при remaining>0 -- warning, не done (H14)",
    )
    _expect(
        node["summary_count"] == 3,
        "бейдж -- состояние ПОСЛЕ операции (remaining=3)",
    )


@oracle("FLD4")
def fld4_partial_apply_warning():
    state = _fold_states([
        _ev("c4-ev-f4", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=4, total_still_missing=1),
    ])
    node = state[("preprocessing", "missing")]
    _expect(
        node["status"] == "warning",
        "частичное устранение (changed при remaining>0) -- честный warning",
    )
    _expect(node["summary_count"] == 1, "бейдж -- remaining после операции")
    _expect(
        node["status_reason"]
        == "Коррекция применена частично: нарушения остались",
        "reason частичного устранения честен",
    )


@oracle("FLD5")
def fld5_full_apply_done_badge_after():
    state = _fold_states([
        _ev("c4-ev-f5", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=4, total_still_missing=0),
    ])
    node = state[("preprocessing", "missing")]
    _expect(node["status"] == "done", "полное устранение -- done")
    _expect(
        node["summary_count"] == 0,
        "бейдж -- remaining=0 (состояние после), НЕ диагностика до",
    )


@oracle("FLD6")
def fld6_unknown_apply_keeps_previous_status():
    state = _fold_states([
        _ev("c4-ev-f6a", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=4, total_still_missing=0),
        _ev("c4-ev-f6b", "preprocessing", "scaling", "correction_applied",
            TS_B),
    ])
    scaling = state[("preprocessing", "scaling")]
    _expect(
        scaling["status"] == "pending",
        "unknown-apply статус НЕ утверждает -- узел остаётся pending",
    )
    _expect(
        scaling["status_reason"] == "Коррекция выполнена: исход не подтверждён",
        "unknown-apply честная маркировка reason",
    )
    missing = state[("preprocessing", "missing")]
    _expect(
        missing["status"] == "done",
        "unknown-apply другого узла не трогает прежнее состояние missing",
    )


@oracle("FLD7")
def fld7_p16_badge_cleared_without_facts():
    state = _fold_states([
        _ev("c4-ev-f7a", "preprocessing", "missing", "correction_previewed",
            TS_A, total_missing=4),
        _ev("c4-ev-f7b", "preprocessing", "missing", "correction_applied",
            TS_B, target_column_reset=True),
    ])
    node = state[("preprocessing", "missing")]
    _expect(
        node["summary_count"] is None,
        "P16: новое решение без фактов счётчика НЕ наследует цифру "
        "прежней диагностики -- бейдж очищен",
    )
    _expect(
        node["status_reason"] == "Коррекция выполнена: исход не подтверждён",
        "reason нового решения -- его собственный (unknown-исход)",
    )


@oracle("FLD8")
def fld8_p16_count_source_follows_reason():
    _, idx = _evidence_fold([
        _ev("c4-ev-f8", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=2, total_still_missing=0),
    ])
    node = idx[("preprocessing", "missing")]
    _expect(
        node["count_source_event_id"] == node["reason_source_event_id"]
        == "c4-ev-f8",
        "P16-evidence: счётчик и reason -- одно событие-источник",
    )


@oracle("FLD9")
def fld9_p15_garbage_status_anomaly_details_intact():
    fold, idx = _evidence_fold([
        _ev("c4-ev-f9a", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=2, total_still_missing=0),
        _ev("c4-ev-f9b", "preprocessing", "missing", "correction_applied",
            TS_B, status="broken", total_changed=99),
    ])
    _expect(
        fold.anomaly_count == 1,
        "P15: невалидный status-факт -- диагностическая аномалия",
    )
    node = idx[("preprocessing", "missing")]
    _expect(
        node["status"] == "done",
        "аномальное событие статус не меняет",
    )
    _expect(
        node["status_reason"] == "Коррекция применена",
        "аномальное событие reason не меняет",
    )
    _expect(
        node["summary_count"] == 0
        and node["count_source_event_id"] == "c4-ev-f9a",
        "аномальное событие бейдж и его источник не трогает",
    )
    _expect(
        node["last_touched_at"] == TS_B,
        "касание -- факт журнала: last_touched_at остаётся",
    )


@oracle("FLD10")
def fld10_p15_nonstring_status_and_none_legacy():
    fold, _ = _evidence_fold([
        _ev("c4-ev-f10a", "preprocessing", "outliers",
            "correction_applied", TS_A, status=123, total_changed=1),
    ])
    _expect(
        fold.anomaly_count == 1,
        "P15: нестроковый status -- schema-нарушение (аномалия)",
    )
    # status: None -- легаси-ветка: НЕ аномалия; с фактами результата
    # исход changed даёт done (то же значение, что и прежний map-фолбэк).
    fold2, idx2 = _evidence_fold([
        _ev("c4-ev-f10b", "preprocessing", "outliers",
            "correction_applied", TS_A, status=None,
            total_changed=5, total_still_missing=0),
    ])
    _expect(
        fold2.anomaly_count == 0
        and idx2[("preprocessing", "outliers")]["status"] == "done",
        "status: None -- не аномалия; исход changed честно даёт done",
    )
    _expect(
        resolve_event_status({"event_type": "correction_applied",
                              "payload": {"status": "zebra"}})
        == "done",
        "resolve_event_status -- словарная проекция для гейтов фаз: "
        "мусорный status фолбэком на карту (пин PROGR-23), контракт "
        "не менялся",
    )


@oracle("FLD11")
def fld11_c5_card_scale_override_wins():
    state = _fold_states([
        _ev("c4-ev-f11a", "preprocessing", "outliers",
            "correction_applied", TS_A,
            status="warning", total_changed=5, total_outliers_after=2),
    ])
    node = state[("preprocessing", "outliers")]
    _expect(
        node["status"] == "warning",
        "C5: валидный payload.status карточной шкалы приоритетен исходу "
        "(частичная коррекция выбросов не унифицируется в done)",
    )
    state2 = _fold_states([
        _ev("c4-ev-f11b", "preprocessing", "outliers",
            "correction_applied", TS_A,
            status="done", total_changed=5, total_outliers_after=0),
    ])
    _expect(
        state2[("preprocessing", "outliers")]["status"] == "done",
        "C5: полный карточный done остаётся done",
    )


@oracle("FLD12")
def fld12_progr11_garbage_key_pin():
    state = _fold_states([
        _ev("c4-ev-f12", "preprocessing", "missing", "correction_applied",
            TS_A, total_outliers="garbage", rows_changed=3,
            total_still_missing=0),
    ])
    node = state[("preprocessing", "missing")]
    _expect(
        node["status"] == "done",
        "мусор в одном счётчике не мешает исходу по валидным фактам "
        "(пин PROGR-11)",
    )
    _expect(
        node["summary_count"] == 0,
        "бейдж -- remaining-факт (0), мусорный ключ пропущен",
    )


@oracle("FLD13")
def fld13_no_change_without_remaining_does_not_claim_done():
    """Контракт v0.8-4A §18.2 «no_change-прочее -- статус НЕ
    утверждается»: no-op apply (все сообщённые нули, remaining=0) на
    узле с прежним warning сохраняет warning -- no-op не удостоверяет
    устранение (H14). Добавлен ПОСЛЕ первой волны кампании: мутант
    CM-10 (no_change -> done) пережил и оракулы, и сюиту исполнителя
    -- гэп покрытия контракта закрыт этим пином (эволюция оракулов,
    открытая фиксация)."""
    state = _fold_states([
        _ev("c4-ev-f13a", "preprocessing", "missing",
            "correction_previewed", TS_A, total_missing=4),
        _ev("c4-ev-f13b", "preprocessing", "missing",
            "correction_applied", TS_B,
            total_changed=0, total_still_missing=0),
    ])
    node = state[("preprocessing", "missing")]
    _expect(
        node["status"] == "warning",
        "no_change-прочее (remaining=0) статус НЕ утверждает -- узел "
        "сохраняет прежний warning (не done)",
    )
    _expect(
        node["summary_count"] == 0,
        "бейдж -- состояние после (remaining=0) из фактов того же "
        "события (P16)",
    )
    _expect(
        node["status_reason"] == "Коррекция не изменила данные",
        "reason честен: no-op применён, устранение не заявлено",
    )


# ── 4. EVD: outcome в доказательствах (I10-стиль) ─────────────────────


@oracle("EVD1")
def evd1_evidence_outcome_additive_contract():
    events = [
        _ev("c4-ev-e1", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=4, total_still_missing=0),
    ]
    _, idx = _evidence_fold(events)
    evidence = idx[("preprocessing", "missing")]
    _expect(
        evidence["outcome"] == "changed",
        "evidence несёт outcome узла (I10-стиль)",
    )
    plain = _fold_states(events)[("preprocessing", "missing")]
    expected7 = {"stage", "node_id", "status", "status_reason", "mode",
                 "last_touched_at", "summary_count"}
    _expect(
        expected7.issubset(set(plain.keys())),
        "7-польный §3-контракт node_states не сужен",
    )


@oracle("EVD2")
def evd2_clean_preview_outcome_in_evidence():
    _, idx = _evidence_fold([
        _ev("c4-ev-e2", "preprocessing", "missing", "correction_previewed",
            TS_A, total_missing=0),
    ])
    _expect(
        idx[("preprocessing", "missing")]["outcome"] == "clean",
        "clean-preview фиксирует outcome=clean в доказательствах",
    )


@oracle("EVD3")
def evd3_outcome_none_without_corrections():
    _, idx = _evidence_fold([
        _ev("c4-ev-e3", "upload", "overview", "upload_completed", TS_A,
            rows=16, columns=2),
    ])
    _expect(
        idx[("upload", "overview")]["outcome"] is None,
        "без коррекций outcome честно None (аддитивность: None -- "
        "старый корпус)",
    )
    _, idx2 = _evidence_fold([
        _ev("c4-ev-e3b", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=1),
        _ev("c4-ev-e3c", "upload", "overview", "upload_completed", TS_B),
    ])
    _expect(
        idx2[("upload", "overview")]["outcome"] is None,
        "outcome -- свойство узла коррекции, чужие узлы не наследуют",
    )


# ── 5. PRJ: паритет редьюсера (5B-инварианты на коррекционных потоках) ─


@oracle("PRJ1")
def prj1_batch_equals_incremental_on_corrections():
    stream = [
        _ev("c4-ev-p1", "upload", "overview", "upload_completed", TS_A,
            rows=40, columns=4),
        _ev("c4-ev-p2", "preprocessing", "missing", "correction_previewed",
            TS_B, total_missing=5),
        _ev("c4-ev-p3", "preprocessing", "missing", "correction_applied",
            TS_C, total_changed=4, total_still_missing=1),
        _ev("c4-ev-p4", "preprocessing", "outliers", "correction_applied",
            TS_D, status="warning", total_changed=2, total_outliers_after=1),
    ]
    batch = _fold_states(stream)
    fold = NodeStateFold()
    for event in stream:
        fold.apply(event)
    inc = {
        (s["stage"], s["node_id"]): s for s in fold.node_states()
    }
    for key, base in batch.items():
        inc_node = inc[key]
        for field in ("status", "status_reason", "summary_count"):
            _expect(
                base[field] == inc_node[field],
                f"паритет батч/инкремент [{key}].{field}: "
                f"{base[field]!r} != {inc_node[field]!r}",
            )


@oracle("PRJ2")
def prj2_snapshot_tail_parity_with_outcome():
    """5B-инвариант replay == snapshot + tail сохранён на потоке с
    коррекциями; checkpoint-состояние несёт outcome/details."""
    stream = [
        _ev("c4-ev-p2a", "preprocessing", "missing", "correction_previewed",
            TS_A, total_missing=5),
        _ev("c4-ev-p2b", "validation", "formats", "correction_applied",
            TS_B, status="broken"),
        _ev("c4-ev-p2c", "preprocessing", "missing", "correction_applied",
            TS_C, total_changed=5, total_still_missing=0),
        _ev("c4-ev-p2d", "preprocessing", "missing", "correction_applied",
            TS_D, target_column_reset=True),
    ]
    prefix, tail = stream[:2], stream[2:]
    full = NodeStateFold()
    for event in stream:
        full.apply(event)
    snap = NodeStateFold()
    for event in prefix:
        snap.apply(event)
    resumed = NodeStateFold()
    resumed.restore_state(snap.export_state())
    for event in tail:
        resumed.apply(event)
    _expect(
        resumed.export_state()["anomalies"]
        == full.export_state()["anomalies"],
        "аномалии переживают snapshot+tail (P15 в checkpoint)",
    )
    for (stage, node_id), expect_state in _fold_states(stream).items():
        got = {
            (s["stage"], s["node_id"]): s
            for s in resumed.node_states()
        }[(stage, node_id)]
        for field in ("status", "status_reason", "summary_count"):
            _expect(
                got[field] == expect_state[field],
                f"replay==snapshot+tail [{stage}/{node_id}].{field}",
            )
    ev_idx = {
        (s["stage"], s["node_id"]): s
        for s in resumed.node_states_with_evidence()
    }
    _expect(
        ev_idx[("preprocessing", "missing")]["outcome"] == "unknown",
        "outcome последнего коррекционного факта восстановлен из "
        "checkpoint (unknown: apply без фактов)",
    )


# ── 6. DQ: P19 -- параметры результата в dedupe (свои данные) ─────────


@oracle("DQ1")
def dq1_method_change_same_picture_new_fact():
    _upload(CSV_SPIKE, "cert4_nagruzka.csv")
    first = CLIENT.get("/v1/session/dataset/outlier-profile?method=iqr")
    _expect(first.status_code == 200, f"iqr-профиль: {first.status_code}")
    second = CLIENT.get("/v1/session/dataset/outlier-profile?method=zscore")
    _expect(second.status_code == 200, f"zscore-профиль: {second.status_code}")
    _expect(
        second.json()["total_outliers"] == first.json()["total_outliers"]
        and second.json()["status"] == first.json()["status"],
        "предусловие: картина одинакова (мой корпус: выброс "
        "нагрузка[20]=60)",
    )
    events = _trace_events("outliers_profile_status", "outliers")
    methods = [e["payload"].get("method") for e in events]
    _expect(
        methods == ["iqr", "zscore"],
        f"P19: смена метода при равной картине -- два факта, получено "
        f"{methods}",
    )


@oracle("DQ2")
def dq2_refetch_same_method_deduped():
    _upload(CSV_SPIKE, "cert4_nagruzka.csv")
    for _ in range(3):
        resp = CLIENT.get("/v1/session/dataset/outlier-profile?method=iqr")
        _expect(resp.status_code == 200, "refetch iqr -- 200")
    events = _trace_events("outliers_profile_status", "outliers")
    _expect(
        len(events) == 1,
        f"focus-refetch того же результата -- один факт, получено "
        f"{len(events)}",
    )


@oracle("DQ3")
def dq3_picture_change_recorded():
    _upload(CSV_SPIKE, "cert4_nagruzka.csv")
    CLIENT.get("/v1/session/dataset/outlier-profile?method=iqr")
    modes = CLIENT.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"outliers": "disabled"}},
    )
    _expect(modes.status_code == 200, f"режим disabled: {modes.status_code}")
    card = CLIENT.get("/v1/session/dataset/outlier-profile?method=iqr")
    _expect(
        card.status_code == 200 and card.json()["status"] == "skipped",
        "предусловие: картина сменилась (disabled)",
    )
    events = _trace_events("outliers_profile_status", "outliers")
    _expect(
        len(events) == 2,
        "смена картины записывается независимо от параметров",
    )


@oracle("DQ4")
def dq4_event_params_honest_none():
    from apps.api.trace_hook import DEDUPE_PARAM_KEYS, _event_params

    _expect(
        DEDUPE_PARAM_KEYS == ("method", "mode"),
        "ключи параметров результата -- (method, mode) по контракту "
        "v0.8-4A §18.3",
    )
    _expect(
        _event_params({"payload": {"method": "iqr", "mode": 123}})
        == ("iqr", None),
        "нестроковое значение параметра честно None",
    )
    _expect(
        _event_params({"payload": "not-a-dict"}) is None,
        "несловарный payload -- сравнение параметров не выполняется "
        "(легаси-самозаживление)",
    )
    _expect(
        _event_params("garbage") is None,
        "событие не словарь -- None (не исключение)",
    )


@oracle("DQ5")
def dq5_mode_param_change_new_fact_unit():
    """mode-канал параметров (unit): смена mode при той же картине --
    другой результат."""
    from types import SimpleNamespace
    from apps.api.trace_hook import _node_picture_unchanged

    def _trace_item(payload: dict) -> dict:
        # Полная форма stored-события слоя 1 (как у живого хука):
        # неполная форма ломала бы before-картину fold-а.
        return {
            "event_id": "c4-ev-dq",
            "run_id": "RUN-C4-DQ",
            "ts": "2026-10-12T09:20:00+00:00",
            "stage": "preprocessing",
            "node_id": "outliers",
            "event_type": "outliers_profile_status",
            "payload": dict(payload),
            "actor": "user",
            "timestamp": "2026-10-12T09:20:00+00:00",
        }

    session_like = SimpleNamespace(
        pipeline_trace=[
            _trace_item({"status": "done", "total_outliers": 0,
                         "method": "iqr", "mode": "mask"}),
        ]
    )
    unchanged = _node_picture_unchanged(
        session_like, "preprocessing", "outliers",
        "outliers_profile_status",
        {"status": "done", "total_outliers": 0,
         "method": "iqr", "mode": "cap"},
    )
    _expect(
        unchanged is False,
        "смена mode при равной картине -- не dedupe (новый факт)",
    )
    unchanged2 = _node_picture_unchanged(
        session_like, "preprocessing", "outliers",
        "outliers_profile_status",
        {"status": "done", "total_outliers": 0,
         "method": "iqr", "mode": "mask"},
    )
    _expect(
        unchanged2 is True,
        "те же параметры и та же картина -- dedupe (refetch не шумит)",
    )


@oracle("DQ6")
def dq6_legacy_without_params_self_heals():
    """Легаси-событие без параметров: сравнение не даёт, первое новое
    событие с параметрами пишется (самозаживление, план §10 п.6)."""
    from types import SimpleNamespace
    from apps.api.trace_hook import _node_picture_unchanged

    def _trace_item(payload: dict) -> dict:
        return {
            "event_id": "c4-ev-dq",
            "run_id": "RUN-C4-DQ",
            "ts": "2026-10-12T09:20:00+00:00",
            "stage": "preprocessing",
            "node_id": "outliers",
            "event_type": "outliers_profile_status",
            "payload": dict(payload),
            "actor": "user",
            "timestamp": "2026-10-12T09:20:00+00:00",
        }

    session_like = SimpleNamespace(
        pipeline_trace=[
            _trace_item({"status": "done", "total_outliers": 0}),
        ]
    )
    unchanged = _node_picture_unchanged(
        session_like, "preprocessing", "outliers",
        "outliers_profile_status",
        {"status": "done", "total_outliers": 0, "method": "zscore"},
    )
    _expect(
        unchanged is False,
        "самозаживление: легаси-stored (параметры (None, None)) + новое "
        "событие С параметрами при той же картине -- параметры "
        "различимы -- первый факт ПИШЕТСЯ (сравнение не подавляет)",
    )
    session_like.pipeline_trace.append(
        _trace_item({"status": "done", "total_outliers": 0,
                     "method": "zscore"}),
    )
    unchanged2 = _node_picture_unchanged(
        session_like, "preprocessing", "outliers",
        "outliers_profile_status",
        {"status": "done", "total_outliers": 0, "method": "mad"},
    )
    _expect(
        unchanged2 is False,
        "после самозаживления смена метода снова различима",
    )


# ── 7. PNL: панель e2e на своих корпусах ──────────────────────────────


@oracle("PNL1")
def pnl1_clean_preview_e2e():
    _upload(CSV_PURE, "cert4_prodazhi.csv")
    resp = CLIENT.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["продажи"], "strategy": "interpolate",
              "apply": False},
    )
    _expect(resp.status_code == 200, f"clean preview: {resp.status_code}")
    _expect(resp.json()["applied"] is False, "preview -- applied=False")
    node = _trace_nodes()[("preprocessing", "missing")]
    _expect(
        node["status"] == "pending",
        "e2e: чистый preview не красит узел (P14)",
    )
    _expect(
        "Найдены нарушения" not in (node["status_reason"] or ""),
        "e2e: без «Найдены нарушения» (H14)",
    )


@oracle("PNL2")
def pnl2_flag_no_elimination_warning():
    _upload(CSV_HYDRO, "cert4_gidro.csv")
    resp = CLIENT.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["уровень"], "strategy": "flag", "apply": True},
    )
    _expect(resp.status_code == 200, f"flag apply: {resp.status_code}")
    body = resp.json()
    _expect(body["total_changed"] == 0, "предусловие: flag не меняет значений")
    _expect(body["total_still_missing"] > 0, "предусловие: пропуски остались")
    node = _trace_nodes()[("preprocessing", "missing")]
    _expect(
        node["status"] == "warning",
        "e2e: changed=0 при remaining>0 -- warning (не done)",
    )
    _expect(
        node["summary_count"] == body["total_still_missing"],
        "e2e: бейдж -- оставшиеся нарушения",
    )


@oracle("PNL3")
def pnl3_full_apply_done_badge_zero():
    _upload(CSV_HYDRO, "cert4_gidro.csv")
    resp = CLIENT.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["уровень", "расход"], "strategy": "mean_mode",
              "apply": True},
    )
    _expect(resp.status_code == 200, f"full apply: {resp.status_code}")
    body = resp.json()
    _expect(body["total_changed"] > 0, "предусловие: есть исправленные")
    _expect(
        body["total_still_missing"] == 0,
        "предусловие: обе колонки исправлены полностью",
    )
    node = _trace_nodes()[("preprocessing", "missing")]
    _expect(node["status"] == "done", "e2e: полное устранение -- done")
    _expect(
        node["status_reason"] == "Коррекция применена",
        "e2e: канонический reason сохранён",
    )
    _expect(
        node["summary_count"] == 0,
        "e2e: бейдж -- состояние после (0), не диагностика до (5)",
    )


@oracle("PNL4")
def pnl4_noop_reapply_honest_reason():
    _upload(CSV_HYDRO, "cert4_gidro.csv")
    first = CLIENT.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["уровень", "расход"], "strategy": "mean_mode",
              "apply": True},
    )
    _expect(first.status_code == 200, "первый apply -- 200")
    second = CLIENT.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["уровень", "расход"], "strategy": "mean_mode",
              "apply": True},
    )
    _expect(second.status_code == 200, "повторный apply -- 200")
    _expect(
        second.json()["total_changed"] == 0,
        "предусловие: повторный -- no-op",
    )
    node = _trace_nodes()[("preprocessing", "missing")]
    _expect(
        node["status"] == "done",
        "данные чисты с первого apply, узел остаётся решённым",
    )
    _expect(
        node["status_reason"] == "Коррекция не изменила данные",
        "e2e: повторный no-op не удостоверяет «применение» (H14)",
    )


@oracle("PNL5")
def pnl5_unknown_transform_pending():
    _upload(CSV_PURE, "cert4_prodazhi.csv")
    resp = CLIENT.post(
        "/v1/session/dataset/preprocessing/scaling-recipes",
        json={"target_column": "продажи", "columns": ["продажи"],
              "method": "standard", "apply": True},
    )
    _expect(resp.status_code == 200, f"scaling apply: {resp.status_code}")
    node = _trace_nodes()[("preprocessing", "scaling")]
    _expect(
        node["status"] == "pending",
        "e2e: transform без фактов результата -- статус не утверждается",
    )
    _expect(
        node["status_reason"] == "Коррекция выполнена: исход не подтверждён",
        "e2e: честная маркировка unknown",
    )


@oracle("PNL6")
def pnl6_regularity_fallback_pair_e2e():
    """e2e fallback-пары (regularity sort): строки не менялись, порядок
    устранён, дубли дат остаются -- remaining != before -- changed при
    remaining>0 -- честный warning с бейджем «после» (парная семантика
    плана §10 на живом маршруте)."""
    _upload(CSV_REG, "cert4_reg.csv")
    resp = CLIENT.post(
        "/v1/session/dataset/preprocessing/regularity-corrections",
        json={"strategy": "sort", "apply": True},
    )
    _expect(resp.status_code == 200, f"regularity sort: {resp.status_code}")
    body = resp.json()
    before = body["total_violations_before"]
    after = body["total_violations_after"]
    _expect(
        before > 0 and after > 0 and after != before,
        f"предусловие: пары до/после разные (sort устраняет порядок, "
        f"дубли остаются): {before} -> {after}",
    )
    node = _trace_nodes()[("preprocessing", "regularity")]
    _expect(
        node["status"] == "warning",
        f"e2e: remaining({after})>0 после коррекции -- честный warning "
        f"(не done)",
    )
    _expect(
        node["summary_count"] == after,
        "e2e: бейдж -- remaining (после), не before",
    )
    # Прямые факты приоритетны fallback-пары: маршрут regularity всегда
    # сообщает rows_added (0 при sort) -- исход no_change; remaining>0
    # даёт честный «не устранила» (находка F-4C1 акта).
    _expect(
        node["status_reason"] == "Коррекция не устранила нарушения",
        "e2e: remaining>0 при no_change -- «не устранила нарушения» "
        "(факт, без претензии на устранение)",
    )


@oracle("PNL7")
def pnl7_outlier_partial_card_interplay():
    """e2e C5-взаимодействие: частичная коррекция выбросов cap-стратегией
    -- статус карточной шкалы (warning), reason из исхода (changed +
    remaining>0 -> «применена частично»)."""
    _upload(CSV_SPIKE, "cert4_nagruzka.csv")
    profile = CLIENT.get("/v1/session/dataset/outlier-profile?method=iqr")
    _expect(
        profile.status_code == 200 and profile.json()["total_outliers"] == 1,
        "предусловие: ровно один выброс в моём корпусе",
    )
    resp = CLIENT.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["нагрузка"], "strategy": "cap", "method": "iqr",
              "apply": True},
    )
    _expect(resp.status_code == 200, f"outlier cap: {resp.status_code}")
    node = _trace_nodes()[("preprocessing", "outliers")]
    _expect(
        node["status"] == "done",
        "карточная шкала после полной коррекции cap -- done (C5)",
    )
    _expect(
        node["summary_count"] == 0,
        "бейдж -- remaining по карточной шкале (0)",
    )


@oracle("PNL8")
def pnl8_stage_card_reflects_correction():
    """Панельная надстройка derive_stage_states -- тот же редьюсер:
    warning узла делает карточку стадии жёлтой, done -- зелёной."""
    events = [
        _ev("c4-ev-s1", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=0, total_still_missing=2),
    ]
    states = {s["stage"]: s for s in derive_stage_states(
        derive_node_statuses(events)
    )}
    _expect(
        states["preprocessing"]["fold"] == "attention"
        and states["preprocessing"]["warning_nodes"] == 1,
        "честный warning узла виден в карточке стадии (attention, "
        "warning_nodes=1)",
    )
    events2 = [
        _ev("c4-ev-s2", "preprocessing", "missing", "correction_applied",
            TS_A, total_changed=5, total_still_missing=0),
    ]
    states2 = {s["stage"]: s for s in derive_stage_states(
        derive_node_statuses(events2)
    )}
    _expect(
        states2["preprocessing"]["done_count"] >= 1
        and states2["preprocessing"]["warning_nodes"] == 0,
        "честный done узла виден в карточке стадии (done_count>=1, "
        "без warning)",
    )


# ── прогон ────────────────────────────────────────────────────────────

ORACLES: list = []


def _collect() -> None:
    for name, value in list(globals().items()):
        if callable(value) and hasattr(value, "_oracle_name"):
            ORACLES.append((value._oracle_name, value))
    ORACLES.sort(key=lambda item: item[0])


def main() -> int:
    _collect()
    print("=" * 72)
    print(f"PROGR-AUDIT-4-CERT: СВОИ оракулы на СВОИХ данных ({len(ORACLES)})")
    print("=" * 72)
    for name, fn in ORACLES:
        fn()
    print("-" * 72)
    total = PASSES + len(FAILURES)
    print(f"ИТОГО: {PASSES}/{total} PASS, {len(FAILURES)} FAIL")
    if FAILURES:
        print("Отказы:")
        for fail in FAILURES:
            print(f"  - {fail}")
    protocol_path = REPO / "scripts/prograudit4cert_oracles_results.txt"
    if "--protocol" in sys.argv:
        idx = sys.argv.index("--protocol")
        protocol_path = Path(sys.argv[idx + 1])
    protocol_path.write_text(
        "\n".join(PROTOCOL_LINES) + "\n", encoding="utf-8"
    )
    print(f"Протокол: {protocol_path}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
