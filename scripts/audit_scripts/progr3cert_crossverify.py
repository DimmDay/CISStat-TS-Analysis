# scripts/progr3cert_crossverify.py
# Task PROGR-3-CERT -- независимая кросс-верификация фактов PROGR-3
# по живым исходникам. Ожидания читаются из ЖИВЫХ роутеров/схем/спеки
# (regex по исходному тексту), а не из trace_hook.py.
"""Кросс-верификация хука трассы (аудит PROGR-3).
Запуск: python3 /home/z/my-project/scripts/progr3cert_crossverify.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps/api/session_store.py").exists():
            return parent
    return Path("/home/z/my-project/CISStat-TS-Analysis")


ROOT = _find_root()
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


# ── 1. Живые маршруты роутеров: (method, full_path, response_model) ──

ROUTER_FILES = {
    "public.py": "/v1/public",
    "internal.py": "/v1/internal",
    "session.py": "/v1/session",
    "modeling_session.py": "/v1/session/modeling",
    "forecasting_session.py": "/v1/session/forecasting",
    "tasks_session.py": "/v1/tasks",
    "diagnostics.py": "/v1/models",
    "diagnostics_internal.py": "/v1/models",
    "models.py": "/v1/models",
}

DECOR_RE = re.compile(r'@router\.(get|post|put|delete|patch)\(([^)]*)\)', re.S)
PATH_RE = re.compile(r'"([^"]+)"')
MODEL_RE = re.compile(r'response_model=([A-Za-z_0-9]+)')


def live_routes() -> list[tuple[str, str, str | None, str]]:
    """(method, full_path, response_model|None, router_file) из живых файлов.

    Префикс берётся из include_router в main.py (файлы объявляют APIRouter()
    без префикса) -- фактическая конфигурация приложения.
    """
    main_src = (ROOT / "apps/api/main.py").read_text(encoding="utf-8")
    prefixes: dict[str, str] = {}
    for m in re.finditer(
        r'include_router\((\w+)\.router[^)]*prefix="([^"]+)"', main_src
    ):
        prefixes[m.group(1)] = m.group(2)
    out: list[tuple[str, str, str | None, str]] = []
    for fname in ROUTER_FILES:
        module = fname[:-3]
        src = (ROOT / "apps/api/routers" / fname).read_text(encoding="utf-8")
        real_prefix = prefixes.get(module, "")
        for dec in DECOR_RE.finditer(src):
            method, body = dec.group(1).upper(), dec.group(2)
            pm = PATH_RE.search(body)
            if not pm:
                continue
            mm = MODEL_RE.search(body)
            model = mm.group(1) if mm else None
            out.append((method, real_prefix + pm.group(1), model, fname))
    return out


LIVE = live_routes()


def template_matches(template: str, path: str) -> bool:
    ts, ps = template.split("/"), path.split("/")
    if len(ts) != len(ps):
        return False
    for t, p in zip(ts, ps):
        if t.startswith("{") and t.endswith("}"):
            continue
        if t != p:
            return False
    return True


# ── 2. Таблица хука из живого модуля ──

from apps.api.trace_hook import TRACE_ROUTES, ENV_THROTTLE_SECONDS, DEFAULT_THROTTLE_SECONDS  # noqa: E402
from apps.api.trace_events import STAGE_EVENT_TYPES, RUN_LEVEL_EVENT_TYPES, KNOWN_STAGES  # noqa: E402
from app.core.pipeline_graph import STAGES as GRAPH_STAGES, is_known_node  # noqa: E402
from apps.api import session_store as SS  # noqa: E402


def main() -> int:
    # X1: размер таблицы -- 40 (заявление исполнителя)
    check("X1: TRACE_ROUTES == 40 записей", len(TRACE_ROUTES) == 40, f"{len(TRACE_ROUTES)}")

    # X2: каждая строка таблицы матчится ровно в один живой маршрут с тем же методом
    bad: list[str] = []
    for spec in TRACE_ROUTES:
        hits = [
            (m, p) for (m, p, _, _) in LIVE
            if m == spec.method and template_matches(spec.path_template, p)
        ]
        if len(hits) != 1:
            bad.append(f"{spec.method} {spec.path_template} -> {hits}")
    check("X2: все 40 шаблонов разрешаются в живые роуты (метод+путь)", not bad, "; ".join(bad[:3]))

    # X3: пары (stage, event_type/preview_type) валидны по живому реестру PROGR-1
    bad = []
    for spec in TRACE_ROUTES:
        for et in (spec.event_type, spec.preview_type):
            if et is None:
                continue
            if et not in STAGE_EVENT_TYPES[spec.stage] and et not in RUN_LEVEL_EVENT_TYPES:
                bad.append(f"{spec.stage}/{et}")
    check("X3: все пары (stage, event_type) валидны по STAGE_EVENT_TYPES", not bad, "; ".join(bad))

    # X4: node_id известны графу; стадия -- из STAGES графа; свёртка реестров цела
    bad = []
    for spec in TRACE_ROUTES:
        if spec.stage not in GRAPH_STAGES:
            bad.append(f"stage {spec.stage}")
        if spec.node_id is not None and not is_known_node(spec.stage, spec.node_id):
            bad.append(f"{spec.stage}/{spec.node_id}")
    check("X4: стадии/узлы таблицы известны живому графу pipeline_graph", not bad, "; ".join(bad))

    # X5: forecasting отсутствует в таблице (дублирование ForecastRun.trace)
    check("X5: forecasting-маршрутов в таблице нет",
          all(spec.stage != "forecasting" for spec in TRACE_ROUTES))

    # X6: троттлируемые строки -- только profile_viewed, и это все GET-строки;
    # env/дефолт -- канон §4.2
    check("X6a: throttled только у profile_viewed",
          all((not spec.throttled) or spec.event_type == "profile_viewed" for spec in TRACE_ROUTES))
    check("X6b: все GET-строки таблицы троттлируются",
          all(spec.throttled for spec in TRACE_ROUTES if spec.method == "GET"))
    check("X6c: env-имя и дефолт §4.2 (300 c)",
          ENV_THROTTLE_SECONDS == "PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS"
          and DEFAULT_THROTTLE_SECONDS == 300)

    # X7: заявление исполнителя «все 20 correction-эндпоинтов возвращают
    # applied: bool, проверено по схемам» -- верифицируется по ЖИВЫМ схемам;
    # плюс отчёт о «мёртвых» ключах общего кортежа _CORRECTION_PAYLOAD_KEYS
    from apps.api import schemas as SCH  # noqa: E402
    corr = [s for s in TRACE_ROUTES if s.preview_type is not None]
    no_applied = []
    for spec in corr:
        hits = [(m, p, mdl) for (m, p, mdl, _) in LIVE
                if m == spec.method and template_matches(spec.path_template, p)]
        if len(hits) != 1 or not hits[0][2]:
            no_applied.append(f"{spec.method} {spec.path_template}: схема не разрешена")
            continue
        model = getattr(SCH, hits[0][2], None)
        fields = set(getattr(model, "model_fields", {}).keys()) if model else set()
        if "applied" not in fields:
            no_applied.append(f"{spec.method} {spec.path_template}: нет applied в {hits[0][2]}")
    check(f"X7: applied: bool есть во всех {len(corr)} preview/apply-схемах",
          not no_applied, "; ".join(no_applied[:4]))

    dead: dict[str, list[str]] = {}
    for spec in corr:
        hits = [(m, p, mdl) for (m, p, mdl, _) in LIVE
                if m == spec.method and template_matches(spec.path_template, p)]
        if len(hits) != 1 or not hits[0][2]:
            continue
        model = getattr(SCH, hits[0][2], None)
        fields = set(getattr(model, "model_fields", {}).keys()) if model else set()
        missing = [k for k in spec.payload_keys if k not in fields]
        if missing:
            dead[f"{spec.method} {spec.path_template}"] = missing
    check("X7b: 'мёртвые' ключи общего кортежа payload (опускаются рантаймом, "
          "не дефект -- INFO)", True,
          f"{len(dead)}/{len(corr)} строк с мёртвыми ключами (см. акт)")

    # X8: полнота покрытия (классификация аудитора). Каждый изменяющий
    # (POST/PUT/DELETE) эндпоинт:
    #   (a) forecasting-контур -- исключён по дизайну (PROGR-1, ForecastRun.trace);
    #   (b) stateless-поверхности (public/internal/models/diagnostics*) --
    #       вне контура сессии: хуку не к чему писать (нет SessionStore);
    #   (c) сессионный, но без канонического event_type в таблице §4.1 --
    #       не трассируется по букве спеки (расширение реестра -- отдельное
    #       решение); фиксируется списком в акте;
    #   (d) сессионный и mappable §4.1 -- ОБЯЗАН быть в таблице (иначе FAIL).
    traced_keys = {(s.method, s.path_template) for s in TRACE_ROUTES}
    sess_mod = [
        (m, p, mdl) for (m, p, mdl, fname) in LIVE
        if m in ("POST", "PUT", "DELETE")
        and fname in ("session.py", "modeling_session.py")
        and not p.startswith("/v1/session/forecasting")
    ]
    # ручная классификация аудитора по живому коду роутеров (см. акт §Полнота)
    NO_41_TYPE = {
        ("POST", "/v1/session/date-column"),
        ("PUT", "/v1/session/dataset/validation-rules"),
        ("PUT", "/v1/session/dataset/type-schema"),
        ("POST", "/v1/session/stage/{stage}"),
        ("PUT", "/v1/session/modeling/feature-regressors"),
        ("POST", "/v1/session/modeling/candidates"),
        ("POST", "/v1/session/modeling/baselines"),
        ("POST", "/v1/session/modeling/backtest/exclude"),
        ("POST", "/v1/session/modeling/tuning/skip"),
        ("POST", "/v1/session/modeling/tuning/skip-pending"),
        ("POST", "/v1/session/modeling/jobs/start"),
        ("POST", "/v1/session/modeling/jobs/{job_id}/cancel"),
        ("POST", "/v1/session/modeling/jobs/{job_id}/step"),
        ("POST", "/v1/session/modeling/tuning/start"),
        ("POST", "/v1/session/modeling/tuning/step"),
        ("POST", "/v1/session/modeling/diagnostics"),
        ("POST", "/v1/session/modeling/diagnostics/ensure"),
        ("POST", "/v1/session/modeling/compare"),
        ("POST", "/v1/session/modeling/selection/evaluate"),
    }
    unresolved = [
        (m, p) for (m, p, _) in sess_mod
        if (m, p) not in traced_keys and (m, p) not in NO_41_TYPE
    ]
    check("X8: все сессионные изменяющие эндпоинты -- в таблице или "
          "классифицированы (без §4.1-типа)", not unresolved,
          f"неразрешённые: {sorted(unresolved)[:8]}")
    # прогнозный контур исключён по дизайну:
    fc = [(m, p) for (m, p, _, f) in LIVE if f == "forecasting_session.py"
          and m in ("POST", "PUT", "DELETE")]
    check("X8b: forecasting-контур вне таблицы (дизайн-решение, PROGR-1/5)",
          all((m, p) not in traced_keys for (m, p) in fc), f"{len(fc)} шт.")

    # X9: §3.1 -- хук не трогает session.stages (ни вызова set_stage/статусов)
    hook_src = (ROOT / "apps/api/trace_hook.py").read_text(encoding="utf-8")
    check("X9: trace_hook не пишет session.stages (§3.1)",
          ".set_stage" not in hook_src and 'stages[' not in hook_src)

    # X10: роутеры не правились в 38f1cb9 (§4.2 -- единая точка интеграции)
    import subprocess
    stat = subprocess.run(
        ["git", "show", "--stat", "--format=", "38f1cb9"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    touched_routers = [ln for ln in stat.splitlines()
                       if "apps/api/routers/" in ln or "main.py" in ln and " routers" in ln]
    check("X10: ни один роутер не изменён коммитом PROGR-3",
          not touched_routers, str(touched_routers[:3]))

    # X11: границы констант слоя 1 (заявления записи PROGR-3)
    check("X11a: SESSION_SCHEMA_VERSION == 2", SS.SESSION_SCHEMA_VERSION == 2)
    check("X11b: MAX_PIPELINE_TRACE_EVENTS == 1000", SS.MAX_PIPELINE_TRACE_EVENTS == 1000)
    check("X11c: STAGES хранилища == STAGES графа == KNOWN_STAGES трассы",
          tuple(SS.STAGES) == tuple(GRAPH_STAGES) == tuple(KNOWN_STAGES))

    # X12: middleware зарегистрирован ДО CORS (CORS -- внешний слой)
    main_src = (ROOT / "apps/api/main.py").read_text(encoding="utf-8")
    ih, cors = main_src.find("TraceHookMiddleware)"), main_src.find("CORSMiddleware,")
    check("X12: add_middleware(TraceHookMiddleware) стоит до CORS в main.py",
          0 < ih < cors)

    # X13: set_dataset сбрасывает run_id и pipeline_trace (новое исследование)
    ss_src = (ROOT / "apps/api/session_store.py").read_text(encoding="utf-8")
    setds = ss_src[ss_src.find("def set_dataset"):ss_src.find("def set_target_column")]
    check("X13: set_dataset содержит сброс run_id и pipeline_trace",
          "self.run_id = \"\"" in setds and "self.pipeline_trace = []" in setds)

    # X14: чтение слоя 1 -- нормализующая граница; сериализация хранит stored-форму
    check("X14a: to_document пишет run_id и deepcopy(pipeline_trace)",
          '"run_id": session.run_id' in ss_src and "deepcopy(session.pipeline_trace)" in ss_src)
    check("X14b: from_document читает run_id с дефолтом и фильтрует не-словари",
          'd.get("run_id", "")' in ss_src and "isinstance(item, dict)" in ss_src)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"CROSSVERIFY: {len(RESULTS) - len(failed)}/{len(RESULTS)} PASSED")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
