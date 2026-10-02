# scripts/progr13cert_mutations.py
# Task PROGR-13-CERT -- мутационное тестирование на СВОИХ мутантах
# (сертификация PROGR-13-A и PROGR-13-B, база main@f607ccc).
#
# Каждая мутация -- точечная правка РАБОЧЕГО КОДА в ключевой точке
# решения задач A/B (с бэкапом и гарантированным восстановлением файла).
# Мутант KILLED, если хотя бы один тест целевого набора падает
# (тестовая сеть ловит поведение); SURVIVED -- дыра тестов.
# Контрольный мутант M-CTRL (правка докстринга) обязан SURVIVE --
# проверка самой сети: убивать текст докстринга тесты не должны.
#
# Запуск: python3 scripts/progr13cert_mutations.py
# (exit 0 = все содержательные мутанты KILLED, контроль SURVIVED).
"""Мутационный прогон PROGR-13-A/B.

Мутанты фокусируются на контрактах задач:
  B-группа (PROGR-13-B): нормализация legacy node_id, фаза Наставника
  по узловым фактам, литеральные паспортные точки.
  A-группа (PROGR-13-A): payload-статусы с whitelist, разведение
  upload_completed/structure_confirmed, fail-closed POST /upload-stops,
  зеркало слоя 2, общий реестр 5 остановок, метки отчёта §5.4.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Целевые наборы тестов по зоне мутанта (быстрый релевантный срез;
# полный suite по каждому мутанту избыточен -- сертификат фиксирует срез).
CORE = [
    "tests/api/test_progress_progr13a.py",
    "tests/api/test_progress_progr13b.py",
    "tests/api/test_progress_defects_progr13.py",
]
ENGINE = CORE + ["tests/api/test_node_status_engine.py",
                 "tests/api/test_progress_panel.py"]
HOOK = CORE + ["tests/api/test_progress_trace_hook.py"]
GRAPH = CORE + ["tests/api/test_pipeline_graph.py"]
REPORT = CORE + ["tests/api/test_run_report.py"]

NODE_STATUS = "app/core/node_status.py"
PROGRESS_ROUTER = "apps/api/routers/progress.py"
TRACE_HOOK = "apps/api/trace_hook.py"
PIPELINE_GRAPH = "app/core/pipeline_graph.py"
RUN_REPORT = "app/core/run_report.py"

MUTATIONS = [
    dict(
        id="M-CTRL",
        zone="контроль сети (докстринг)",
        file=NODE_STATUS,
        old="""    legacy-значение своей стадии -> канонический id; канонический
    проходит насквозь (идемпотентность -- корпус уже нормализованный
    легитимен); неизвестное -- как есть (дальнейший is_known_node-гейт
    движка решает, фантомов не возникает); None -- None; чужая стадия --
    маппинга нет, значение не переписывается.""",
        new="""    MUTANT-DOC: legacy-значение своей стадии -> канонический id;
    канонический проходит насквозь; неизвестное -- как есть;
    None -- None; чужая стадия -- маппинга нет.""",
        tests=ENGINE,
        expect="SURVIVED",
        note="контроль сети: убивать докстринг тесты не должны",
    ),
    # ── PROGR-13-B: нормализация legacy node_id (B3) ─────────────────
    dict(
        id="M-B3-1",
        zone="B3 нормализация",
        file=NODE_STATUS,
        old="""    if node_id is None:
        return None
    mapping = LEGACY_NODE_IDS.get(stage)
    canonical = mapping.get(str(node_id)) if mapping else None
    return canonical if canonical else str(node_id)""",
        new="""    if node_id is None:
        return None
    return str(node_id)""",
        tests=ENGINE,
        expect="KILLED",
        note="рецидив дефекта: legacy-строки корпуса отбрасываются гейтом",
    ),
    dict(
        id="M-B3-2",
        zone="B3 нормализация",
        file=NODE_STATUS,
        old="    mapping = LEGACY_NODE_IDS.get(stage)",
        new='    mapping = LEGACY_NODE_IDS.get("upload")',
        tests=ENGINE,
        expect="KILLED",
        note="маппинг чужой стадии -- cross-stage перезапись",
    ),
    dict(
        id="M-B3-3",
        zone="B3 нормализация",
        file=NODE_STATUS,
        old="""    if not node_id:
        return None
    return normalize_legacy_node_id(stage, str(node_id))""",
        new="""    if not node_id:
        return None
    return str(node_id)""",
        tests=ENGINE,
        expect="KILLED",
        note="вызов-сайт resolve_node_id перестал нормализовать (независимо от M-B3-1)",
    ),
    # ── PROGR-13-B: фаза Наставника (B1) ─────────────────────────────
    dict(
        id="M-B1-1",
        zone="B1 фаза Наставника",
        file=NODE_STATUS,
        old="""        if resolve_event_status(data) is None:
            continue
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)
        if not node_id or not is_known_node(stage, node_id):
            continue
        last_stage = stage
    return last_stage if last_stage is not None else default""",
        new="""        return str(data.get("stage") or default)
        last_stage = stage  # noqa
    return last_stage if last_stage is not None else default""",
        tests=ENGINE,
        expect="KILLED",
        note="рецидив дефекта 2: фаза по хвосту трассы (events[-1].stage)",
    ),
    dict(
        id="M-B1-2",
        zone="B1 фаза Наставника",
        file=NODE_STATUS,
        old="""        if resolve_event_status(data) is None:
            continue
        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)""",
        new="""        stage = str(data.get("stage") or "")
        node_id = resolve_node_id(data)""",
        tests=ENGINE,
        expect="KILLED",
        note="фазу двигают любые узловые события, не только факты решения",
    ),
    # ── PROGR-13-B: паспортные точки (B2) ────────────────────────────
    dict(
        id="M-B2-1",
        zone="B2 паспортные точки",
        file=TRACE_HOOK,
        old="""    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/validation", "validation", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),""",
        new="""    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/validation", "eda", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),""",
        tests=HOOK,
        expect="KILLED",
        note="рецидив мисаттрибуции: validation-паспорт снова -> eda",
    ),
    dict(
        id="M-B2-2",
        zone="B2 паспортные точки",
        file=TRACE_HOOK,
        old="""    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/start", "upload", None,
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),""",
        new="""    TraceRouteSpec(
        "POST", "/v1/session/dataset/passport/start", "upload", "overview",
        "passport_captured", payload_keys=("stage", "snapshot_id", "fingerprint"),
    ),""",
        tests=HOOK,
        expect="KILLED",
        note="паспортная точка -- уровень стадии, node_id обязателен None",
    ),
    # ── PROGR-13-A: payload-статусы (A4) ─────────────────────────────
    dict(
        id="M-A4-1",
        zone="A4 payload-статусы",
        file=NODE_STATUS,
        old="""    if event_type in PAYLOAD_STATUS_EVENT_TYPES:
        payload = data.get("payload")
        raw = payload.get("status") if isinstance(payload, Mapping) else None
        if isinstance(raw, str) and raw in CHECK_STATUS_VALUES:
            return raw
        return None""",
        new="""    if event_type in PAYLOAD_STATUS_EVENT_TYPES:
        payload = data.get("payload")
        raw = payload.get("status") if isinstance(payload, Mapping) else None
        if isinstance(raw, str):
            return raw
        return None""",
        tests=ENGINE,
        expect="KILLED",
        note="снят whitelist CHECK_STATUS_VALUES -- мусор становится статусом",
    ),
    dict(
        id="M-A4-2",
        zone="A4 payload-статусы",
        file=NODE_STATUS,
        old='    if event_type in PAYLOAD_STATUS_EVENT_TYPES:',
        new='    if event_type in frozenset():',
        tests=ENGINE,
        expect="KILLED",
        note="payload-типы выпали из движка -- отчёт модуля не виден панели",
    ),
    dict(
        id="M-A3-1",
        zone="A3 разведение фактов",
        file=NODE_STATUS,
        old='    "structure_confirmed": "done",',
        new='    # "structure_confirmed": "done",',
        tests=ENGINE,
        expect="KILLED",
        note="structure_confirmed выпал из карты -- решение аналитика не считается",
    ),
    dict(
        id="M-A3-2",
        zone="A3 разведение фактов",
        file=NODE_STATUS,
        old='    "upload_completed": "Датасет загружен, превью доступно",',
        new='    "upload_completed": "Датасет загружен, структура подтверждена",',
        tests=ENGINE,
        expect="KILLED",
        note="рецидив лжи дефекта 1б в человекочитаемой причине",
    ),
    # ── PROGR-13-A: POST /upload-stops (A4) ──────────────────────────
    dict(
        id="M-A4-3",
        zone="A4 POST /upload-stops",
        file=PROGRESS_ROUTER,
        old="""    missing = [node_id for node_id in known_ids if node_id not in stops]
    if missing:""",
        new="""    missing: list[str] = []
    if False:
        pass
    if missing:""",
        tests=CORE,
        expect="KILLED",
        note="снят fail-closed неполной карты -- чёрные дыры в фактах",
    ),
    dict(
        id="M-A4-4",
        zone="A4 POST /upload-stops",
        file=PROGRESS_ROUTER,
        old="""    unknown = sorted(set(stops) - set(known_ids))
    if unknown:""",
        new="""    unknown: list[str] = []
    if unknown:""",
        tests=CORE,
        expect="KILLED",
        note="снят отказ на неизвестных узлах -- фантомные остановки",
    ),
    dict(
        id="M-A4-5",
        zone="A4 POST /upload-stops",
        file=PROGRESS_ROUTER,
        old="""    invalid = sorted(
        node_id
        for node_id, status in stops.items()
        if status not in CHECK_STATUS_VALUES
    )
    if invalid:""",
        new="""    invalid: list[str] = []
    if invalid:""",
        tests=CORE,
        expect="KILLED",
        note="снят отказ на недопустимом статусе",
    ),
    dict(
        id="M-A4-6",
        zone="A4 POST /upload-stops",
        file=PROGRESS_ROUTER,
        old="""        session.append_trace_event(event)
        # §5 слой 2: зеркало фактов остановок в research_runs -- тот же
        # best-effort механизм, что у хука (record_run_event).
        record_run_event(session, event)""",
        new="""        session.append_trace_event(event)
        if False:
            record_run_event(session, event)""",
        tests=CORE,
        expect="KILLED",
        note="зеркало слоя 2 отключено -- admin/Наставник теряют факты",
    ),
    dict(
        id="M-A4-7",
        zone="A4 POST /upload-stops",
        file=PROGRESS_ROUTER,
        old="    session.ensure_run_id()\n    for node_id in known_ids:",
        new="    for node_id in known_ids:",
        tests=CORE,
        expect="KILLED",
        note="run_id не фиксируется первым отчётом",
    ),
    dict(
        id="M-A4-8",
        zone="A4 POST /upload-stops",
        file=PROGRESS_ROUTER,
        old="""    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if session.dataset is None:
        raise HTTPException(
            status_code=400,""",
        new="""    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    session = store.get_or_create(session_id)
    if False:
        raise HTTPException(
            status_code=400,""",
        tests=CORE,
        expect="KILLED",
        note="снят 400 без датасета",
    ),
    # ── PROGR-13-A: таблица хука /date-column (A3) ───────────────────
    dict(
        id="M-A3-3",
        zone="A3 /date-column",
        file=TRACE_HOOK,
        old="""    TraceRouteSpec(
        "POST", "/v1/session/date-column", "upload", "structure",
        "structure_confirmed", payload_keys=("date_column",),
    ),""",
        new="""    TraceRouteSpec(
        "POST", "/v1/session/date-column", "upload", "overview",
        "structure_confirmed", payload_keys=("date_column",),
    ),""",
        tests=HOOK,
        expect="KILLED",
        note="структурный факт уходит на overview -- узел structure не красится",
    ),
    # ── PROGR-13-A: общий реестр (A1) ────────────────────────────────
    dict(
        id="M-A1-1",
        zone="A1 общий реестр",
        file=PIPELINE_GRAPH,
        old="""UPLOAD_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in UPLOAD_STOP_DEFS)""",
        new="""UPLOAD_STAGE_IDS: tuple[str, ...] = tuple(d["id"] for d in UPLOAD_STOP_DEFS[:1])""",
        tests=GRAPH,
        expect="KILLED",
        note="рецидив дефекта 1а: Загрузка из одной остановки",
    ),
    dict(
        id="M-A1-2",
        zone="A1 общий реестр",
        file=PIPELINE_GRAPH,
        old="""        if node_id in seen:
            raise ImportError(
                f"Дубликат id узла {registry_name} в реестре: {node_id!r}"
            )
        seen.add(node_id)""",
        new="""        if False:
            raise ImportError(
                f"Дубликат id узла {registry_name} в реестре: {node_id!r}"
            )
        seen.add(node_id)""",
        tests=GRAPH,
        expect="KILLED",
        note="снят fail-closed дубликатов id реестра",
    ),
    # ── PROGR-13-A: отчёт §5.4 (A5) ──────────────────────────────────
    dict(
        id="M-A5-1",
        zone="A5 отчёт §5.4",
        file=RUN_REPORT,
        old='    stop_label = node_label("upload", node_id) if node_id else node_id',
        new='    stop_label = node_id',
        tests=REPORT,
        expect="KILLED",
        note="метки остановок не из реестра -- сырые id в отчёте",
    ),
    dict(
        id="M-A5-2",
        zone="A5 отчёт §5.4",
        file=RUN_REPORT,
        old="""    column = payload.get("date_column")
    if column:
        return f"Подтверждена временная колонка «{column}»."
    return "Подтверждена структура данных (временная колонка).\"""",
        new="""    column = payload.get("date_column") or "unknown_column"
    return f"Подтверждена временная колонка «{column}».\"""",
        tests=REPORT,
        expect="KILLED",
        note="выдуманный факт при отсутствующей колонке",
    ),
]


def run_mutation(m: dict) -> str:
    path = REPO / m["file"]
    backup = path.with_suffix(path.suffix + ".mutbak")
    shutil.copy2(path, backup)
    try:
        src = path.read_text(encoding="utf-8")
        if m["old"] not in src:
            return "SPEC-ERROR (old_str не найден)"
        mutated = src.replace(m["old"], m["new"], 1)
        path.write_text(mutated, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-x",
             *m["tests"]],
            cwd=REPO, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            return "KILLED"
        return "SURVIVED"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    finally:
        shutil.copy2(backup, path)
        backup.unlink(missing_ok=True)


def main() -> int:
    killed = survived = spec_errors = 0
    mismatch: list[str] = []
    print(f"Мутационный прогон PROGR-13-CERT: {len(MUTATIONS)} мутантов\n")
    for m in MUTATIONS:
        status = run_mutation(m)
        if status == "KILLED":
            killed += 1
        elif status == "SURVIVED":
            survived += 1
        else:
            spec_errors += 1
        flag = "" if status == m["expect"] else "  <-- НЕ ОЖИДАННО"
        print(f"{m['id']:8} [{m['zone']}] {status} (ожидание {m['expect']}) "
              f"-- {m['note']}{flag}")
        if flag:
            mismatch.append(m["id"])
    print(f"\nИтог: KILLED={killed}, SURVIVED={survived}, "
          f"SPEC/ERROR={spec_errors}, расхождений с ожиданием={len(mismatch)}")
    if mismatch:
        print("Расхождения:", ", ".join(mismatch))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
