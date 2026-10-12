# scripts/prograudit1acert_oracles.py
# -*- coding: utf-8 -*-
"""СВОИ оракулы независимой сертификации PROGR-AUDIT-1A-CERT.

Объект: коммит 5364d41 (PROGR-AUDIT-1A — единый effective-target reducer,
пара target/source в run-метаданных, restore согласованную пару без
повторного авто-выбора, миграция 0003).

Принцип «оракулы на своих данных»: данные сертификатора ДИЗЪЮКТНЫ
данным оракула исполнителя (tests/api/test_progress_audit_1a.py):
  * свои CSV-корпуса (agro_nov/двухканальный/кириллический/строковый);
  * свои run_id (RUN-C1A-…), свои session_id, свои payload-значения
    (в т.ч. кириллические колонки);
  * свои события с пиннутыми event_id;
  * живой pgserver с чистой схемой на каждый PG-оракул.

Каналы проверки: самодостаточный EXIT-код (0 = все PASS).
Группы: NRM (нормализация origin), RED (редьюсер), MEN (Наставник),
RUN (run-метаданные Memory), RST (restore API), CLR (сброс-согласованность
P03), PG (паритет/миграция 0003 на живом PG), CYC (полный цикл),
NRK (reason-марка "(авто)").

Запуск: python scripts/prograudit1acert_oracles.py [--protocol PATH]
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
            tmp = tempfile.mkdtemp(prefix="cert1a-oracle-")
            os.environ["CISSTAT_DATA_DIR"] = tmp
            # Свежие синглтоны обоих хранилищ на каждый оракул.
            from apps.api import research_runs as rr
            from apps.api.session_store import reset_session_store_for_testing

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

CSV_A = (
    "date,soy\n"
    "2024-03-01,12.4\n"
    "2024-03-02,13.1\n"
    "2024-03-03,11.9\n"
    "2024-03-04,14.6\n"
    "2024-03-05,15.0\n"
    "2024-03-06,13.8\n"
)  # одна числовая soy -> честный авто-выбор soy

CSV_B = (
    "date,soy,maize\n"
    "2024-03-01,12.4,1.2\n"
    "2024-03-02,13.1,1.9\n"
    "2024-03-03,11.9,1.1\n"
    "2024-03-04,14.6,2.3\n"
    "2024-03-05,15.0,2.0\n"
    "2024-03-06,13.8,1.7\n"
)  # две числовых -> честная неоднозначность

CSV_C = (
    "date,продажи\n"
    "2024-03-01,100\n"
    "2024-03-02,150\n"
    "2024-03-03,130\n"
    "2024-03-04,170\n"
)  # кириллическая числовая колонка (чувствительность к содержимому)

CSV_D = (
    "date,city,soy\n"
    "2024-03-01,Москва,12.4\n"
    "2024-03-02,Казань,13.1\n"
    "2024-03-03,Тула,11.9\n"
    "2024-03-04,Уфа,14.6\n"
)  # строковая city ПРИСУТСТВУЕТ в raw (применимость цели к raw-данным)

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402

CLIENT = TestClient(app)


def _upload(csv: str, name: str) -> dict:
    resp = CLIENT.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(csv.encode("utf-8")), "text/csv")},
    )
    if resp.status_code != 200:
        raise OracleFail(f"upload {name}: HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _convert(column: str, apply: bool = True):
    return CLIENT.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": column, "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": apply,
        },
    )


def _choose(column: str):
    return CLIENT.post("/v1/session/target-column", json={"column": column})


def _state() -> dict:
    resp = CLIENT.get("/v1/session/target-column")
    if resp.status_code != 200:
        raise OracleFail(f"GET target-column: HTTP {resp.status_code}")
    return resp.json()


def _trace() -> dict:
    resp = CLIENT.get("/v1/progress/trace")
    if resp.status_code != 200:
        raise OracleFail(f"GET trace: HTTP {resp.status_code}")
    return resp.json()


def _run_id() -> str:
    rid = _trace().get("run_id") or ""
    if not rid:
        raise OracleFail("run_id не зафиксирован в трассе слоя 1")
    return rid


def _run_meta(run_id: str):
    from apps.api import research_runs as rr

    run = rr.get_research_run_store().get_run(run_id)
    if run is None:
        raise OracleFail(f"запуск {run_id} не найден в слое 2")
    return run


def _restore(run_id: str) -> dict:
    fresh = TestClient(app)
    resp = fresh.get(f"/v1/progress/runs/{run_id}/restore")
    if resp.status_code != 200:
        raise OracleFail(
            f"restore {run_id}: HTTP {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    from apps.api.session_store import SESSION_COOKIE_NAME

    data["_session_id"] = fresh.cookies.get(SESSION_COOKIE_NAME)
    return data


def _cleared(trace: dict) -> list[dict]:
    return [
        e for e in trace.get("events", [])
        if e.get("event_type") == "target_column_cleared"
    ]


def _choices(trace: dict) -> list[dict]:
    return [
        e for e in trace.get("events", [])
        if e.get("event_type") == "target_column_changed"
    ]


def _mentor_text() -> str:
    """Метод наблюдения P03/H1: текст фазы «Загрузка» по событиям слоя 2."""
    from app.core.mentor_rules import phase_text
    from app.core.node_status import derive_node_statuses
    from apps.api import research_runs as rr

    layer2 = rr.get_research_run_store().list_events(_run_id())
    return phase_text(
        "upload", statuses=derive_node_statuses(layer2), events=layer2,
    )


def _reason_of(stage: str, node_id: str) -> str:
    nodes = [
        n for n in _trace().get("nodes", [])
        if n.get("stage") == stage and n.get("node_id") == node_id
    ]
    if not nodes:
        raise OracleFail(f"узел {stage}/{node_id} отсутствует")
    return nodes[0].get("status_reason") or ""


# ── Группа NRM: normalize_target_origin (канон происхождения) ────────


def _make_event(**payload_extra):
    from apps.api.trace_events import make_trace_event

    kwargs = dict(
        stage="validation", node_id=None, run_id="RUN-C1A-NRM",
        actor="system",
    )
    kwargs.update(payload_extra)
    return make_trace_event(**kwargs)


@oracle("NRM1 normalize auto->auto")
def nrm1():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin("auto") != "auto":
        raise OracleFail('normalize("auto") != "auto"')


@oracle("NRM2 normalize user->user")
def nrm2():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin("user") != "user":
        raise OracleFail('normalize("user") != "user"')


@oracle("NRM3 normalize None->user (legacy-контракт PROGR-25-A)")
def nrm3():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin(None) != "user":
        raise OracleFail("normalize(None) != user — legacy-отсутствие сломано")


@oracle("NRM4 normalize ''->user (эквивалент отсутствия)")
def nrm4():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin("") != "user":
        raise OracleFail("normalize('') != user")


@oracle("NRM5 normalize мусор 'bot'->None (unknown, не фабрика user)")
def nrm5():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin("bot") is not None:
        raise OracleFail("повреждённое происхождение фабрикует user (спека §8.2)")


@oracle("NRM6 normalize мусор 123->None")
def nrm6():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin(123) is not None:
        raise OracleFail("нестроковый source фабрикует происхождение")


@oracle("NRM7 normalize 'AUTO' (регистр) ->None (канон чувствителен)")
def nrm7():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin("AUTO") is not None:
        raise OracleFail("регистр канона не чувствителен — фабрика из шума")


@oracle("NRM8 normalize ' user' (пробел) ->None")
def nrm8():
    from app.core.effective_target import normalize_target_origin

    if normalize_target_origin(" user") is not None:
        raise OracleFail("непарсированный мусор читается как user")


# ── Группа RED: единый effective-target reducer (свои корпуса) ───────


@oracle("RED1 выбор непустым строковым target (своё значение 'soy')")
def red1():
    from app.core.effective_target import effective_target

    ev = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    st = effective_target([ev])
    if st.target != "soy" or st.origin != "auto" or st.resolved is not True:
        raise OracleFail(f"пара не выбрана: {st}")


@oracle("RED2 выбор без source -> user (своё 'maize')")
def red2():
    from app.core.effective_target import effective_target

    ev = _make_event(
        event_type="target_column_changed", target_column="maize", actor="user",
    )
    st = effective_target([ev])
    if st.target != "maize" or st.origin != "user":
        raise OracleFail(f"legacy-выбор читается неверно: {st}")


@oracle("RED3 мусорный source -> origin None, target сохранён (I10-стиль)")
def red3():
    from app.core.effective_target import effective_target

    ev = _make_event(
        event_type="target_column_changed", target_column="soy", source="cron",
    )
    st = effective_target([ev])
    if st.target != "soy" or st.origin is not None:
        raise OracleFail(f"повреждённое происхождение не unknown: {st}")


@oracle("RED4 cleared сбрасывает ПАРУ (target+origin) на своих payload")
def red4():
    from app.core.effective_target import effective_target

    choice = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    cleared = _make_event(
        event_type="target_column_cleared", target_column=None,
        reset_reason="type_conversion", source="system", before_target="soy",
    )
    st = effective_target([choice, cleared])
    if st.target is not None or st.origin is not None or st.resolved is not True:
        raise OracleFail(f"cleared не сбросил пару: {st}")
    if st.source_event_id != cleared.event_id:
        raise OracleFail("source_event_id не последний факт (cleared)")


@oracle("RED5 пустая строка target = legacy-сброс (канон PROGR-15-B)")
def red5():
    from app.core.effective_target import effective_target

    choice = _make_event(
        event_type="target_column_changed", target_column="maize", actor="user",
    )
    legacy = _make_event(
        event_type="target_column_changed", target_column="", actor="user",
    )
    st = effective_target([choice, legacy])
    if st.target is not None or st.origin is not None or st.resolved is not True:
        raise OracleFail(f"пустая строка не сброс: {st}")


@oracle("RED6 мусорный target 123 после выбора — состояние не тронул")
def red6():
    from app.core.effective_target import effective_target

    choice = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    garbage = _make_event(
        event_type="target_column_changed", target_column=123, actor="user",
    )
    st = effective_target([choice, garbage])
    if st.target != "soy" or st.origin != "auto":
        raise OracleFail(f"мусор фабрикует/стирает цель: {st}")


@oracle("RED7 пустой корпус — unresolved (не «сброс»)")
def red7():
    from app.core.effective_target import effective_target

    st = effective_target([])
    if st.resolved is not False or st.target is not None or st.origin is not None:
        raise OracleFail(f"пустой корпус не unresolved: {st}")


@oracle("RED8 шум (чужие типы) не сбрасывает состояние")
def red8():
    from app.core.effective_target import effective_target

    choice = _make_event(
        event_type="target_column_changed", target_column="продажи", source="auto",
    )
    noise = _make_event(
        event_type="upload_completed", stage="upload", node_id="overview",
        name="agro.csv",
    )
    st = effective_target([choice, noise])
    if st.target != "продажи" or st.origin != "auto":
        raise OracleFail(f"шум стёр цель: {st}")


@oracle("RED9 last-wins по ДАННОМУ порядку (свои значения, оба порядка)")
def red9():
    from app.core.effective_target import effective_target

    auto = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    manual = _make_event(
        event_type="target_column_changed", target_column="maize", actor="user",
    )
    if effective_target([auto, manual]).target != "maize":
        raise OracleFail("last-wins нарушен в порядке [auto, manual]")
    if effective_target([manual, auto]).target != "soy":
        raise OracleFail("last-wins нарушен в порядке [manual, auto]")


@oracle("RED10 TraceEvent и dict формы дают одно состояние")
def red10():
    from app.core.effective_target import effective_target

    ev = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    a = effective_target([ev])
    b = effective_target([ev.to_dict()])
    if (a.target, a.origin) != (b.target, b.origin):
        raise OracleFail(f"формы расходятся: {a} vs {b}")


@oracle("RED11 мусорный корпус деградирует честно (не 500)")
def red11():
    from app.core.effective_target import effective_target

    st = effective_target(["мусор", None, 42, {"payload": "не событие"}])
    if st.resolved is not False:
        raise OracleFail("мусорный корпус не unresolved")


@oracle("RED12 source_event_id = последний ФАКТ (выбор после шума)")
def red12():
    from app.core.effective_target import effective_target

    noise = _make_event(
        event_type="upload_completed", stage="upload", node_id="overview",
        name="agro.csv",
    )
    choice = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    st = effective_target([noise, choice])
    if st.source_event_id != choice.event_id:
        raise OracleFail("source_event_id не событие выбора")


@oracle("RED13 cleared затем пустая строка — оба сбросы, last = строка")
def red13():
    from app.core.effective_target import effective_target

    cleared = _make_event(event_type="target_column_cleared")
    legacy = _make_event(
        event_type="target_column_changed", target_column="", actor="user",
    )
    st = effective_target([cleared, legacy])
    if st.target is not None or st.resolved is not True:
        raise OracleFail(f"последний факт не сброс: {st}")
    if st.source_event_id != legacy.event_id:
        raise OracleFail("source_event_id не legacy-сброс")


@oracle("RED14 кириллический target — полноценный факт (чувствительность)")
def red14():
    from app.core.effective_target import effective_target

    ev = _make_event(
        event_type="target_column_changed", target_column="продажи",
        source="auto",
    )
    st = effective_target([ev])
    if st.target != "продажи" or st.origin != "auto":
        raise OracleFail(f"кириллический выбор читается неверно: {st}")


# ── Группа MEN: Наставник — потребитель единого редьюсера ────────────


def _mixed_corpus():
    """СВОЙ смешанный корпус (не корпус исполнителя)."""
    auto = _make_event(
        event_type="target_column_changed", target_column="soy", source="auto",
    )
    noise = _make_event(
        event_type="correction_applied", node_id="data_types", applied=True,
    )
    cleared = _make_event(
        event_type="target_column_cleared", target_column=None,
        reset_reason="type_conversion", source="system", before_target="soy",
    )
    manual = _make_event(
        event_type="target_column_changed", target_column="maize", actor="user",
    )
    return [auto, noise, cleared, manual]


@oracle("MEN1 _target_confirmed совпадает с редьюсером (свой корпус)")
def men1():
    from app.core.effective_target import effective_target
    from app.core.mentor_rules import _target_confirmed

    events = _mixed_corpus()
    expected = effective_target(events).target is not None
    if _target_confirmed(events) is not expected:
        raise OracleFail("расхождение _target_confirmed с редьюсером")


@oracle("MEN2 _target_origin совпадает с редьюсером (свой корпус)")
def men2():
    from app.core.effective_target import effective_target
    from app.core.mentor_rules import _target_origin

    events = _mixed_corpus()
    if _target_origin(events) != effective_target(events).origin:
        raise OracleFail("расхождение _target_origin с редьюсером")


@oracle("MEN3 _phase_event_text_facts совпадает с редьюсером")
def men3():
    from app.core.effective_target import effective_target
    from app.core.mentor_rules import _phase_event_text_facts

    events = tuple(_mixed_corpus())
    expected = effective_target(list(events)).target or ""
    want = {"target_column": expected} if expected else {}
    if _phase_event_text_facts(events) != want:
        raise OracleFail("расхождение фаз-фактов с редьюсером")


@oracle("MEN4 мусорный source: _target_origin=None (различитель unknown)")
def men4():
    from app.core.mentor_rules import _target_origin

    ev = _make_event(
        event_type="target_column_changed", target_column="soy", source="bot",
    )
    if _target_origin([ev]) is not None:
        raise OracleFail("мусорный source читается Наставником как известный")


@oracle("MEN5 мусорный source: факт колонки сохранён в тексте")
def men5():
    from app.core.mentor_rules import _phase_event_text_facts

    ev = _make_event(
        event_type="target_column_changed", target_column="soy", source="bot",
    )
    facts = _phase_event_text_facts((ev,))
    if facts != {"target_column": "soy"}:
        raise OracleFail(f"выбор с unknown-origin потерял факт колонки: {facts}")


# ── Группа RUN: run-метаданные (Memory) — пара target/source ─────────


def _record_pair(events):
    from apps.api import research_runs as rr
    from apps.api.session_store import AnalysisSession

    session = AnalysisSession(session_id="sess-c1a")
    session.run_id = "RUN-C1A-RUN"
    for ev in events:
        rr.record_run_event(session, ev)
    return rr.get_research_run_store().get_run("RUN-C1A-RUN")


@oracle("RUN1 changed auto -> пара (soy, auto)")
def run1():
    from apps.api.trace_events import make_trace_event

    ev = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="system", target_column="soy", source="auto",
    )
    run = _record_pair([ev])
    if run.target_column != "soy" or run.target_column_source != "auto":
        raise OracleFail(f"пара не зеркалирована: {run.target_column}/{run.target_column_source}")


@oracle("RUN2 manual без source -> (maize, user)")
def run2():
    from apps.api.trace_events import make_trace_event

    ev = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="user", target_column="maize",
    )
    run = _record_pair([ev])
    if run.target_column != "maize" or run.target_column_source != "user":
        raise OracleFail(f"legacy-пара не user: {run.target_column_source}")


@oracle("RUN3 cleared -> (None, None) — парная очистка")
def run3():
    from apps.api.trace_events import make_trace_event

    choice = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="system", target_column="soy", source="auto",
    )
    cleared = make_trace_event(
        "target_column_cleared", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="system", target_column=None,
        reset_reason="type_conversion", source="system", before_target="soy",
    )
    run = _record_pair([choice, cleared])
    if run.target_column is not None or run.target_column_source is not None:
        raise OracleFail("cleared не очистил пару run-метаданных")


@oracle("RUN4 мусор после выбора — метаданные не тронуты (не «123»)")
def run4():
    from apps.api.trace_events import make_trace_event

    choice = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="system", target_column="soy", source="auto",
    )
    garbage = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="user", target_column=123,
    )
    run = _record_pair([choice, garbage])
    if run.target_column != "soy" or run.target_column_source != "auto":
        raise OracleFail(f"мусор изменил метаданные: {run.target_column}")


@oracle("RUN5 пустая строка — сброс пары (паритет run-метаданных)")
def run5():
    from apps.api.trace_events import make_trace_event

    choice = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="user", target_column="maize",
    )
    legacy = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-C1A-RUN", actor="user", target_column="",
    )
    run = _record_pair([choice, legacy])
    if run.target_column is not None or run.target_column_source is not None:
        raise OracleFail("legacy-сброс не парный в run-метаданных")


@oracle("RUN6 round-trip to_dict/from_dict: auto/user/None")
def run6():
    from apps.api import research_runs as rr

    for col, src in (("soy", "auto"), ("maize", "user"), (None, None)):
        run = rr.ResearchRun(
            run_id="RUN-C1A-RT", target_column=col, target_column_source=src,
        )
        restored = rr.ResearchRun.from_dict(run.to_dict())
        if restored.target_column != col or restored.target_column_source != src:
            raise OracleFail(f"round-trip {col}/{src} повреждён")


@oracle("RUN7 from_dict мусор -> None (щит, не фабрика str)")
def run7():
    from apps.api import research_runs as rr

    restored = rr.ResearchRun.from_dict(
        {"run_id": "RUN-C1A-MS", "target_column_source": 123}
    )
    if restored.target_column_source is not None:
        raise OracleFail("мусорный origin фабрикует строку")


@oracle("RUN8 to_dict всегда несёт ключ пары (форма контракта §17.2)")
def run8():
    from apps.api import research_runs as rr

    raw = rr.ResearchRun(run_id="RUN-C1A-FORM").to_dict()
    if "target_column_source" not in raw:
        raise OracleFail("целевая пара отсутствует в словаре (None-сброс неотличим)")


# ── Группа RST: restore — согласованная пара через API (P04) ─────────


@oracle("RST1 auto-restore: пара во всех точках, второго выбора нет")
def rst1():
    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    before = len([
        e for e in __import__("apps.api.research_runs", fromlist=["x"])
        .get_research_run_store().list_events(run_id)
        if e.event_type == "target_column_changed"
    ])
    if before != 1:
        raise OracleFail(f"выборов до restore {before} != 1")
    data = _restore(run_id)
    if data["target_column"] != "soy" or data["target_column_source"] != "auto":
        raise OracleFail(f"пара restore потеряна: {data.get('target_column')}/{data.get('target_column_source')}")
    from apps.api.session_store import get_session_store

    session = get_session_store().get(data["_session_id"])
    if session.target_column != "soy" or session.target_column_source != "auto":
        raise OracleFail("сессия restore без пары")
    sel = CLIENT.get(
        "/v1/session/target-column",
        cookies={__import__("apps.api.session_store", fromlist=["x"]).SESSION_COOKIE_NAME: data["_session_id"]},
    ).json()
    if sel["target_column"] != "soy" or sel["target_column_source"] != "auto":
        raise OracleFail("селектор восстановленной сессии без пары")
    ledger = __import__("apps.api.research_runs", fromlist=["x"]).get_research_run_store().list_events(run_id)
    if len([e for e in ledger if e.event_type == "target_column_changed"]) != 1:
        raise OracleFail("restore породил второе событие выбора")


@oracle("RST2 reset->restore: без воскрешения и без авто-пере-выбора")
def rst2():
    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    _convert("soy")
    if _run_meta(run_id).target_column is not None:
        raise OracleFail("сброс не дошёл до run-метаданных")
    data = _restore(run_id)
    if data["target_column"] is not None or data["target_column_source"] is not None:
        raise OracleFail("сброшенная цель воскресла (F03-остаток)")
    from apps.api.session_store import get_session_store

    session = get_session_store().get(data["_session_id"])
    if session.target_column is not None:
        raise OracleFail("raw-пере-выбор выполнился вместо честного отсутствия")


@oracle("RST3 demo->manual->restore: origin=user восстанавливается")
def rst3():
    resp = CLIENT.post("/v1/session/demo")
    if resp.status_code != 200:
        raise OracleFail(f"demo: HTTP {resp.status_code}")
    run_id = _run_id()
    if _choose("sales").status_code != 200:
        raise OracleFail("ручной выбор sales не принят")
    data = _restore(run_id)
    if data["target_column"] != "sales" or data["target_column_source"] != "user":
        raise OracleFail(f"manual-пара потеряна: {data.get('target_column_source')}")


@oracle("RST4 ledger авторитетен: stale-метаданные не воскрешают сброс")
def rst4():
    from dataclasses import replace as dc_replace

    from apps.api import research_runs as rr

    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    _convert("soy")
    stale = rr.get_research_run_store().get_run(run_id)
    rr.get_research_run_store().upsert_run(dc_replace(stale, target_column="soy"))
    data = _restore(run_id)
    if data["target_column"] is not None or data["target_column_source"] is not None:
        raise OracleFail("устаревшие метаданные воскрешают сброшенную цель")


@oracle("RST5 legacy-корпус без фактов цели: fallback метаданных, origin=None")
def rst5():
    import csv as _csv

    from apps.api import research_runs as rr

    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["soy"])
    w.writerow([1.5])
    fp = rr.get_dataset_file_store().save_upload(
        buf.getvalue().encode("utf-8"), "legacy_agro.csv",
        rows=1, columns=1, size_label="1 B",
    )
    rr.get_research_run_store().upsert_run(
        rr.ResearchRun(
            run_id="RUN-C1A-LEG", session_id="s0",
            dataset_fingerprint=fp, dataset_name="legacy_agro.csv",
            target_column="soy",
        )
    )
    fresh = TestClient(app)
    resp = fresh.get("/v1/progress/runs/RUN-C1A-LEG/restore")
    if resp.status_code != 200:
        raise OracleFail(f"legacy restore: HTTP {resp.status_code}")
    data = resp.json()
    if data["target_column"] != "soy" or data["target_column_source"] is not None:
        raise OracleFail("legacy-fallback: происхождение сфабриковано")


@oracle("RST6 ghost-цель (отсутствует в raw) — пара пуста")
def rst6():
    from apps.api import research_runs as rr
    from apps.api.trace_events import make_trace_event

    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    ghost = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id=run_id, actor="user", target_column="нефть",
    )
    rr.get_research_run_store().append_event(run_id, ghost)
    data = _restore(run_id)
    if data["target_column"] is not None or data["target_column_source"] is not None:
        raise OracleFail("неприменимая цель восстановлена")


@oracle("RST7 НЕчисловая ПРИСУТСТВУЮЩАЯ цель (строковая city) — пара пуста")
def rst7():
    """Различитель применимости: у исполнителя только ghost (отсутствует);
    строковая колонка В raw требует числовой проверки numeric_columns."""
    from apps.api import research_runs as rr
    from apps.api.trace_events import make_trace_event

    _upload(CSV_D, "texty.csv")
    run_id = _run_id()
    ev = make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id=run_id, actor="user", target_column="city",
    )
    rr.get_research_run_store().append_event(run_id, ev)
    data = _restore(run_id)
    if data["target_column"] is not None or data["target_column_source"] is not None:
        raise OracleFail(
            f"нечисловая цель восстановлена: {data.get('target_column')}"
        )


@oracle("RST8 два числовых — честная неоднозначность после restore")
def rst8():
    _upload(CSV_B, "two_channels.csv")
    run_id = _run_id()
    data = _restore(run_id)
    if data["target_column"] is not None or data["target_column_source"] is not None:
        raise OracleFail("restore угадывает при неоднозначности")


@oracle("RST9 шапка /trace восстановленной сессии — та же пара")
def rst9():
    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    data = _restore(run_id)
    resp = CLIENT.get(
        "/v1/progress/trace",
        cookies={
            __import__("apps.api.session_store", fromlist=["x"])
            .SESSION_COOKIE_NAME: data["_session_id"]
        },
    ).json()
    if resp["target_column"] != "soy" or resp["target_column_source"] != "auto":
        raise OracleFail("шапка трассы расходится с парой restore")


# ── Группа CLR: сброс-согласованность всех потребителей (P03) ────────


@oracle("CLR1 полный сброс: сессия+run+ровно один cleared+payload")
def clr1():
    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    resp = _convert("soy")
    if resp.status_code != 200 or resp.json().get("target_column_reset") is not True:
        raise OracleFail("конвертация не сообщила сброс")
    if _state()["target_column"] is not None or _state()["target_column_source"] is not None:
        raise OracleFail("сессия не очистила пару")
    run = _run_meta(run_id)
    if run.target_column is not None or run.target_column_source is not None:
        raise OracleFail("run не очистил пару")
    trace = _trace()
    if len(_cleared(trace)) != 1:
        raise OracleFail(f"cleared != 1 ({len(_cleared(trace))}) — двойной посев?")
    payload = _cleared(trace)[0]["payload"]
    if payload.get("reset_reason") != "type_conversion" or payload.get("before_target") != "soy":
        raise OracleFail(f"payload сброса не честен: {payload}")


@oracle("CLR2 после сброса Наставник НЕ утверждает выбор и просит подтвердить")
def clr2():
    # Свой метод наблюдения (без привязки к конкретному шаблону): текст
    # фазы «Загрузка» НЕ утверждает факт цели и содержит просьбу
    # подтвердить целевой признак (честный fallback P03).
    _upload(CSV_A, "agro_nov.csv")
    _convert("soy")
    text = _mentor_text()
    low = text.lower()
    if "целевой признак выбран" in low or "выбран автоматически" in low:
        raise OracleFail(f"Наставник утверждает выбор после сброса: {text[:160]}")
    if "подтвердите" not in low or "целевой признак" not in low:
        raise OracleFail(f"Наставник не просит подтвердить цель: {text[:160]}")


@oracle("CLR3 reason своего класса снят (пустая строка)")
def clr3():
    _upload(CSV_A, "agro_nov.csv")
    _convert("soy")
    if _reason_of("validation", "sufficiency") != "":
        raise OracleFail("reason узла не снят после сброса")


@oracle("CLR4 preview (apply=False) не сбрасывает")
def clr4():
    _upload(CSV_A, "agro_nov.csv")
    resp = _convert("soy", apply=False)
    if resp.status_code != 200 or resp.json().get("target_column_reset") is not False:
        raise OracleFail("preview сообщил сброс")
    if _state()["target_column"] != "soy":
        raise OracleFail("preview стёр цель")
    if len(_cleared(_trace())) != 0:
        raise OracleFail("preview посеял cleared")


@oracle("CLR5 пустой POST /target-column — 422, сброс через выбор невозможен")
def clr5():
    _upload(CSV_A, "agro_nov.csv")
    resp = CLIENT.post("/v1/session/target-column", json={"column": None})
    if resp.status_code != 422:
        raise OracleFail(f"граница PROGR-25-C нарушена: HTTP {resp.status_code}")
    if len(_cleared(_trace())) != 0:
        raise OracleFail("422-отказ посеял cleared")


@oracle("CLR6 заголовок отчёта после сброса не называет цель")
def clr6():
    from app.core.run_report import build_report_model
    from apps.api import research_runs as rr

    _upload(CSV_A, "agro_nov.csv")
    run_id = _run_id()
    _convert("soy")
    run = _run_meta(run_id)
    model = build_report_model(
        run.to_dict(),
        [e.to_dict() for e in rr.get_research_run_store().list_events(run_id)],
    )
    if model.target_column is not None:
        raise OracleFail("документ утверждает цель после сброса")


# ── Группа NRK: reason-марка «(авто)» через normalize_target_origin ──


@oracle("NRK1 auto-выбор: reason несёт марку «(авто)»")
def nrk1():
    _upload(CSV_A, "agro_nov.csv")
    reason = _reason_of("validation", "sufficiency")
    if "(авто)" not in reason:
        raise OracleFail(f"auto-марка потеряна: {reason!r}")


@oracle("NRK2 manual-выбор: марки нет")
def nrk2():
    _upload(CSV_B, "two_channels.csv")
    if _choose("maize").status_code != 200:
        raise OracleFail("manual выбор не принят")
    reason = _reason_of("validation", "sufficiency")
    if "(авто)" in reason:
        raise OracleFail(f"manual выбор маркирован auto: {reason!r}")


# ── Группа CYC: полный цикл на своих данных ──────────────────────────


@oracle("CYC1 auto->reset->manual (свой двухканальный корпус)")
def cyc1():
    _upload(CSV_B, "two_channels.csv")
    run_id = _run_id()
    if _state()["target_column"] is not None:
        raise OracleFail("два числовых — не должна быть цель")
    _convert("soy")
    if _run_meta(run_id).target_column_source is not None:
        raise OracleFail("сброс не очистил origin")
    if _choose("maize").status_code != 200:
        raise OracleFail("manual после сброса не принят")
    st = _state()
    if st["target_column"] != "maize" or st["target_column_source"] != "user":
        raise OracleFail("выбор после сброса не восстановил пару")
    run = _run_meta(run_id)
    if run.target_column != "maize" or run.target_column_source != "user":
        raise OracleFail("run-пара после цикла расходится с сессией")


@oracle("CYC2 manual->reset: пара очищена, выбор сохранён исторически")
def cyc2():
    _upload(CSV_B, "two_channels.csv")
    _choose("maize")
    _convert("maize")
    st = _state()
    if st["target_column"] is not None or st["target_column_source"] is not None:
        raise OracleFail("manual-сброс не парный")
    trace = _trace()
    if len(_cleared(trace)) != 1 or len(_choices(trace)) != 1:
        raise OracleFail(
            f"хронология сброса нечестна: choices={len(_choices(trace))}, cleared={len(_cleared(trace))}"
        )
    if _cleared(trace)[0]["payload"].get("before_target") != "maize":
        raise OracleFail("before_target не честен")


@oracle("CYC3 кириллический корпус: полный сброс пары честен")
def cyc3():
    _upload(CSV_C, "кириллица.csv")
    run_id = _run_id()
    if _state()["target_column"] != "продажи":
        raise OracleFail("авто-выбор кириллической колонки не состоялся")
    _convert("продажи")
    run = _run_meta(run_id)
    if run.target_column is not None or run.target_column_source is not None:
        raise OracleFail("кириллический сброс не парный")
    if _state()["target_column_source"] is not None:
        raise OracleFail("сессия кириллического сброса не парная")


# ── Группа PG: паритет Memory/Postgres + миграция 0003 (живой PG) ────

import pgserver  # noqa: E402
import psycopg  # noqa: E402

_PG_SERVER = None
_PG_URI = ""


def _pg_fresh_dsn() -> str:
    """Живой pgserver с ЧИСТОЙ схемой на каждый PG-оракул."""
    global _PG_SERVER, _PG_URI
    import apps.api.research_runs as rr

    if _PG_SERVER is None:
        pgdir = tempfile.mkdtemp(prefix="cert1a-pg-")
        _PG_SERVER = pgserver.get_server(pgdir, cleanup_mode="delete")
        _PG_URI = _PG_SERVER.get_uri()
    # Чистая схема = чистый корпус (тест-гигиена F-6A2).
    with psycopg.connect(_PG_URI) as conn:
        cur = conn.cursor()
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.commit()
    conn = psycopg.connect(_PG_URI)
    rr.run_migrations(conn)
    conn.close()
    return _PG_URI


@oracle("PG1 паритет record_run_event: пара durable (auto)")
def pg1():
    from apps.api import research_runs as rr
    from apps.api.session_store import AnalysisSession
    from apps.api.trace_events import make_trace_event

    dsn = _pg_fresh_dsn()
    store = rr.PostgresResearchRunStore(dsn)
    # record_run_event пишет в СИНГЛТОН — переключаю его на живой PG
    # (паттерн test_research_runs_postgres).
    old_backend = os.environ.get("CISSTAT_RUNS_BACKEND")
    os.environ["DATABASE_URL"] = dsn
    os.environ.pop("CISSTAT_RUNS_BACKEND", None)
    rr.reset_research_run_store_for_testing()
    try:
        session = AnalysisSession(session_id="sess-pg")
        session.run_id = "RUN-C1A-PG1"
        ev = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="RUN-C1A-PG1", actor="system", target_column="soy", source="auto",
        )
        rr.record_run_event(session, ev)
    finally:
        os.environ.pop("DATABASE_URL", None)
        if old_backend is not None:
            os.environ["CISSTAT_RUNS_BACKEND"] = old_backend
        rr.reset_research_run_store_for_testing()
    run = store.get_run("RUN-C1A-PG1")
    if run is None:
        raise OracleFail("run не создан в PG")
    if run.target_column != "soy" or run.target_column_source != "auto":
        raise OracleFail(
            f"PG-пара потеряна: {run.target_column}/{run.target_column_source}"
        )


@oracle("PG2 прямая запись пары: None стирает прежний auto (НЕ COALESCE)")
def pg2():
    from dataclasses import replace as dc_replace

    from apps.api import research_runs as rr

    dsn = _pg_fresh_dsn()
    store = rr.PostgresResearchRunStore(dsn)
    base = rr.ResearchRun(
        run_id="RUN-C1A-PG2", target_column="soy", target_column_source="auto",
    )
    store.upsert_run(base)
    if store.get_run("RUN-C1A-PG2").target_column_source != "auto":
        raise OracleFail("PG не сохранил auto")
    store.upsert_run(dc_replace(base, target_column=None, target_column_source=None))
    reset = store.get_run("RUN-C1A-PG2")
    if reset.target_column is not None or reset.target_column_source is not None:
        raise OracleFail(
            "сброс пары не прошёл прямую запись (COALESCE-фабрика вернула auto)"
        )


@oracle("PG3 legacy-строка (NULL source) читается честным отсутствием")
def pg3():
    from apps.api import research_runs as rr

    dsn = _pg_fresh_dsn()
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO research_runs (run_id, session_id, created_at,"
            " last_active_at, status) VALUES (%s, %s, now(), now(), 'active')",
            ("RUN-C1A-PG3", "s0"),
        )
        conn.commit()
    store = rr.PostgresResearchRunStore(dsn)
    run = store.get_run("RUN-C1A-PG3")
    if run is None or run.target_column_source is not None:
        raise OracleFail("legacy NULL не честное отсутствие")


@oracle("PG4 файл 0003 == MIGRATION_STATEMENTS_0003 (нормализующий разбор)")
def pg4():
    import re

    from apps.api import research_runs as rr

    sql_text = (REPO / "apps/api/migrations/0003_audit1a_target_source.sql").read_text(
        encoding="utf-8"
    )
    # Снимаем комментарии -- до конца строки, схлопываем пробелы, режем по ;
    stmts = []
    for raw in sql_text.splitlines():
        line = raw.split("--", 1)[0]
        if line.strip():
            stmts.append(line.strip())
    joined = " ".join(stmts)
    file_stmts = [re.sub(r"\s+", " ", s).strip() for s in joined.split(";") if s.strip()]
    py_stmts = [
        re.sub(r"\s+", " ", s).strip() for s in rr.MIGRATION_STATEMENTS_0003
    ]
    if file_stmts != py_stmts:
        raise OracleFail(f"DDL-эквивалентность нарушена: {file_stmts} != {py_stmts}")


@oracle("PG5 каталог MIGRATION_FILES: 0001+0002+0003")
def pg5():
    from apps.api import research_runs as rr

    names = [name for name, _ in rr.MIGRATION_FILES]
    if names != ["0001_research_runs.sql", "0002_audit6a_atomic_ledger.sql",
                 "0003_audit1a_target_source.sql"]:
        raise OracleFail(f"каталог миграций нечестен: {names}")


@oracle("PG6 legacy-корпус (0001+0002) + файл 0003 -> колонка NULL, читаем")
def pg6():
    from apps.api import research_runs as rr

    global _PG_SERVER, _PG_URI
    pgdir = tempfile.mkdtemp(prefix="cert1a-pg-legacy-")
    server = pgserver.get_server(pgdir, cleanup_mode="delete")
    uri = server.get_uri()
    with psycopg.connect(uri) as conn:
        cur = conn.cursor()
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.commit()
    conn = psycopg.connect(uri)
    for st in rr.MIGRATION_STATEMENTS_0001 + rr.MIGRATION_STATEMENTS_0002:
        conn.cursor().execute(st)
    conn.commit()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO research_runs (run_id, session_id, created_at,"
        " last_active_at, status, target_column)"
        " VALUES (%s, %s, now(), now(), 'active', %s)",
        ("RUN-C1A-LEG6", "s0", "soy"),
    )
    conn.commit()
    conn.close()
    # Применение ФАЙЛА 0003 (ops-контур).
    sql_text = (REPO / "apps/api/migrations/0003_audit1a_target_source.sql").read_text(
        encoding="utf-8"
    )
    stmts = [
        line.split("--", 1)[0].strip()
        for line in sql_text.splitlines()
        if line.split("--", 1)[0].strip()
    ]
    conn = psycopg.connect(uri)
    for st in stmts:
        conn.cursor().execute(st.rstrip(";"))
    conn.commit()
    conn.close()
    store = rr.PostgresResearchRunStore(uri)
    run = store.get_run("RUN-C1A-LEG6")
    if run is None or run.target_column != "soy" or run.target_column_source is not None:
        raise OracleFail("применение файла 0003 к legacy-корпусу нечестно")


@oracle("PG7 повторное применение файла 0003 — no-op (идемпотентность)")
def pg7():
    global _PG_SERVER, _PG_URI
    dsn = _pg_fresh_dsn()
    sql_text = (REPO / "apps/api/migrations/0003_audit1a_target_source.sql").read_text(
        encoding="utf-8"
    )
    stmts = [
        line.split("--", 1)[0].strip()
        for line in sql_text.splitlines()
        if line.split("--", 1)[0].strip()
    ]
    for _ in range(2):
        conn = psycopg.connect(dsn)
        for st in stmts:
            conn.cursor().execute(st.rstrip(";"))
        conn.commit()
        conn.close()
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name='research_runs' AND column_name='target_column_source'"
        )
        if cur.fetchone()[0] != 1:
            raise OracleFail("повторное применение задвоило колонку")


@oracle("PG8 Memory/PG паритет полного mirror-потока (choice+cleared)")
def pg8():
    from apps.api import research_runs as rr
    from apps.api.session_store import AnalysisSession
    from apps.api.trace_events import make_trace_event

    dsn = _pg_fresh_dsn()
    pg_store = rr.PostgresResearchRunStore(dsn)

    def _flow(store_kind, run_id):
        # store_kind: "memory" | "postgres" — направление СИНГЛТОНА.
        if store_kind == "postgres":
            os.environ["DATABASE_URL"] = dsn
            os.environ.pop("CISSTAT_RUNS_BACKEND", None)
            rr.reset_research_run_store_for_testing()
        else:
            os.environ.pop("DATABASE_URL", None)
            os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
            rr.reset_research_run_store_for_testing()
        session = AnalysisSession(session_id="sess-x")
        session.run_id = run_id
        e1 = make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id=run_id, actor="system", target_column="soy", source="auto",
        )
        e2 = make_trace_event(
            "target_column_cleared", stage="validation", node_id=None,
            run_id=run_id, actor="system", target_column=None,
            reset_reason="type_conversion", source="system", before_target="soy",
        )
        for ev in (e1, e2):
            rr.record_run_event(session, ev)
        result = rr.get_research_run_store().get_run(run_id)
        # Возврат к Memory-изолированной норме оракула.
        os.environ.pop("DATABASE_URL", None)
        os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
        rr.reset_research_run_store_for_testing()
        return result

    mem = _flow("memory", "RUN-C1A-PM")
    pg = _flow("postgres", "RUN-C1A-PG8")
    if mem is None or pg is None:
        raise OracleFail("одна из сторон потока не создала run")
    if (mem.target_column, mem.target_column_source) != (
        pg.target_column, pg.target_column_source
    ):
        raise OracleFail(
            f"паритет нарушен: Memory {mem.target_column}/{mem.target_column_source}"
            f" vs PG {pg.target_column}/{pg.target_column_source}"
        )
    if (mem.target_column, mem.target_column_source) != (None, None):
        raise OracleFail("mirror-поток не привёл к честному сбросу")


# ── Запуск ───────────────────────────────────────────────────────────


def main() -> int:
    _log("=" * 72)
    _log("PROGR-AUDIT-1A-CERT: СВОИ оракулы на СВОИХ данных")
    _log("=" * 72)
    oracles = [
        v for k, v in sorted(globals().items())
        if k.startswith(("nrm", "red", "men", "run", "rst", "clr", "nrk", "cyc", "pg"))
        and callable(v) and getattr(v, "_oracle_name", None)
    ]
    for fn in oracles:
        fn()
    _log("-" * 72)
    _log(f"ИТОГО: {PASSES} PASS / {len(FAILURES)} FAIL (всего {PASSES + len(FAILURES)})")
    if FAILURES:
        for f in FAILURES:
            _log(f"  FAIL: {f}")
    proto = REPO / "scripts/prograudit1acert_oracles_results.txt"
    proto.write_text("\n".join(PROTOCOL_LINES) + "\n", encoding="utf-8")
    _log(f"Протокол: {proto}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
