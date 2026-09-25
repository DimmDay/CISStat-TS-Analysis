# scripts/audit_scripts/progr4cert_crossverify.py
# Task PROGR-4-CERT (2026-09-25) -- кросс-верификация по живым исходникам.
# Ожидания читаются из ЖИВЫХ файлов (не из заявлений worklog): аддендум
# §4.1-4.2 (pill-кнопка), §4.2 (w-[40rem]), §6.1-6.2 spec_progress.md
# (механика панели, шапка, состав), §5 (namespace /v1/progress),
# §3 (словари статусов), §12 п.2/п.10 (общий JSON, свёртка).
# Запуск: python3 scripts/audit_scripts/progr4cert_crossverify.py
#   -> CROSSVERIFY: N/N PASSED (+ список находок)
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool]] = []
NOTES: list[str] = []


def check(name: str, ok: bool, note: str = "") -> None:
    RESULTS.append((name, ok))
    if note:
        NOTES.append(f"{'OK ' if ok else 'FAIL'} {name}: {note}")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── Живые исходники ──────────────────────────────────────────────────
nav = read("packages/ui/components/ModuleNav.tsx")
drawer = read("packages/ui/components/ProgressDrawer.tsx")
flow = read("packages/ui/components/ProgressStageFlow.tsx")
tracelog = read("packages/ui/components/ProgressTraceLog.tsx")
lib = read("packages/ui/lib/progress.ts")
ctx = read("packages/ui/context/AppShellContext.tsx")
idx = read("packages/ui/index.ts")
api_client = read("packages/ui/lib/apiClient.ts")
progress_router = read("apps/api/routers/progress.py")
main_py = read("apps/api/main.py")
panel_tests = read("tests/api/test_progress_panel.py")

def code_lines(src: str) -> str:
    """Только код: строки без // -- и без хвостовых комментариев после кода
    (строковые литералы с // в этих файлах отсутствуют)."""
    return "\n".join(
        ln.split("//")[0] if "//" in ln and '"' not in ln.split("//")[0] else ln
        for ln in src.splitlines()
    )


# ── Блок A: pill-кнопка -- аддендум §4.1 (построчно) ─────────────────
# Позиция: тот же слот, «Логи событий» заменены, не добавлены рядом.
nav_code = code_lines(nav)
check("A1 'Логи событий' отсутствуют в КОДЕ ModuleNav (не в комментарии)",
      "Логи событий" not in nav_code)
check("A2 кнопка «Прогресс» присутствует", ">Прогресс<" in nav or "Прогресс</span>" in nav)
check("A3 ScrollText заменён (в коде нет использования)", "ScrollText" not in nav_code)
check("A4 иконка Workflow в слоте (аддендум §4.1: опционально, тот же слот)", "Workflow" in nav)

# Форма: pill по паттерну бейджей (BADGE_BASE).
badge = re.search(r'const BADGE_BASE =\s*\n?\s*"([^"]+)"', nav)
check("A5 BADGE_BASE найден", badge is not None)
if badge:
    b = badge.group(1)
    check("A5a rounded-full", "rounded-full" in b)
    check("A5b h-9", "h-9" in b)
    check("A5c whitespace-nowrap", "whitespace-nowrap" in b)
    check("A5d адаптив px-3/text-[13px] -> lg:px-4/lg:text-sm",
          "px-3" in b and "text-[13px]" in b and "lg:px-4" in b and "lg:text-sm" in b)

trigger = re.search(r"const PROGRESS_TRIGGER_BASE = `([^`]+)`", nav)
check("A6 PROGRESS_TRIGGER_BASE построен на BADGE_BASE", trigger is not None and "${BADGE_BASE}" in (trigger.group(1) if trigger else ""))
check("A7 focus-visible ring (аддендум: доступность)", trigger is not None and "focus-visible:ring-2" in (trigger.group(1) if trigger else ""))

# Неактивное состояние: bg-white + ТОНКАЯ border-brand + text-brand.
check("A8 неактивная: bg-white + border border-brand + text-brand",
      re.search(r"bg-white border border-brand text-brand", nav) is not None)
check("A9 «тонкая» = не border-2", "border-2" not in nav)
# Активное: bg-brand + text-white + font-semibold (semibold ≠ font-medium).
active_cls = re.search(r"progressOpen\s*\n?\s*\?\s*`([^`]+)`", nav)
if active_cls is None:
    active_cls = re.search(r"\?\s*`\$\{PROGRESS_TRIGGER_BASE\} ([^`]+)`", nav)
check("A10 активная: bg-brand + text-white + font-semibold",
      active_cls is not None and "bg-brand" in active_cls.group(1)
      and "text-white" in active_cls.group(1) and "font-semibold" in active_cls.group(1))
check("A11 активная НЕ font-medium (осознанное отличие §4.1)",
      active_cls is not None and "font-medium" not in active_cls.group(1))

# Доступность и toggle-поведение.
check("A12 aria-expanded={progressOpen}", "aria-expanded={progressOpen}" in nav)
check("A13 aria-controls='progress-drawer'", 'aria-controls="progress-drawer"' in nav)
check("A14 toggle повторным кликом (setProgressOpen(prev => !prev))",
      "setProgressOpen((previous) => !previous)" in nav)

# ── Блок B: панель -- аддендум §4.2 + §6.1 ────────────────────────────
check("B1 ширина w-[40rem] (ровно 2×w-80)", "w-[40rem]" in drawer)
check("B2 fixed top-0 right-0 h-full", "fixed top-0 right-0 h-full" in drawer)
check("B3 translate-x транзишн", "translate-x-0" in drawer and "translate-x-full" in drawer
      and "transition-transform" in drawer)
check("B4 затемнение bg-black/20 закрывает кликом (§6.1 дословно)",
      "bg-black/20" in drawer and "onClick={handleBackdropClick}" in drawer)
check("B5 крестик закрывает (aria-label='Закрыть')", 'aria-label="Закрыть"' in drawer)
check("B6 aside id='progress-drawer' (цель aria-controls)", 'id="progress-drawer"' in drawer)
check("B7 шапка §6.1: датасет + признак + дата",
      "activeDataset?.name" in drawer and "targetColumn" in drawer
      and "toLocaleDateString" in drawer)
check("B8 шапка §6.1: run_id + «Начат N мин назад»",
      "trace.runId" in drawer and "Начат" in drawer and "мин назад" in drawer)
check("B9 run_id/started_at моноширинно/прочерк",
      "font-mono" in drawer and '"—"' in drawer)
check("B10 «Развернуть трассу» переключатель с aria-expanded",
      "Развернуть трассу" in drawer and "traceExpanded" in drawer)
check("B11 контент с первого открытия (hasOpened) -- закрытая панель не рендерит стадии",
      "hasOpened" in drawer)

# ── Блок C: чтение трассы -- роутер PROGR-4, §5 ───────────────────────
check("C1 ровно один GET-маршрут /trace",
      len(re.findall(r"@router\.(get|post|put|delete|patch)", progress_router)) == 1
      and '@router.get("/trace"' in progress_router)
check("C2 response-модель: run_id/started_at/events",
      all(f in progress_router for f in ("run_id", "started_at", "events")))
check("C3 started_at = ts ПЕРВОГО события (аналог created_at слоя 1)",
      "events[0].ts if events else None" in progress_router)
check("C4 run_id -- session.run_id или None (не session_id)",
      "session.run_id or None" in progress_router)
check("C5 чтение через read_pipeline_trace (нормализация legacy на границе)",
      "read_pipeline_trace()" in progress_router)
check("C6 регистрация в main.py с префиксом /v1/progress",
      'include_router(progress.router, prefix="/v1/progress"' in main_py)
check("C7 events -- канонический to_dict каждого события",
      "event.to_dict() for event in events" in progress_router)

from apps.api.trace_hook import resolve_trace_route  # noqa: E402
check("C8 /v1/progress/trace отсутствует в таблице хука (ридер не трассируется)",
      resolve_trace_route("GET", "/v1/progress/trace") is None)

# ── Блок D: шапка -- target_column «поле есть» (§6.1) ────────────────
sess = read("apps/api/routers/session.py")
check("D1 GET /current уже отдаёт target_column (бэкенд не менялся для этого)",
      "target_column=session.target_column" in sess and "@router.get(\"/current\"" in sess)
ctx_code = code_lines(ctx)
check("D2 AppShellContext: log/addLogEntry/clearLog удалены из кода",
      all(s not in ctx_code for s in ("addLogEntry", "clearLog", "LogEntry", "log:")))
check("D3 AppShellContext: добавлен targetColumn (optional для частичных моков)",
      "targetColumn?" in ctx and "target_column" in ctx)
check("D4 index.ts: экспорт EventsLogDrawer снят", "EventsLogDrawer" not in idx)
check("D5 index.ts: тройка Progress* экспортируется",
      "ProgressDrawer" in idx and "ProgressStageFlow" in idx and "ProgressTraceLog" in idx)
check("D6 index.ts: LogEntry больше не экспортируется", "LogEntry" not in idx)
check("D7 apiClient: progressApiUrl = getApiBase()/v1/progress (§5 namespace)",
      "`${getApiBase()}/v1/progress${path}`" in api_client)

# ── Блок E: реестр узлов фронтенда vs живой граф (§2, §12 п.2) ────────
from app.core.pipeline_graph import STAGES, STAGE_NODES  # noqa: E402

block = re.search(r"export const PROGRESS_STAGE_NODES[^=]*=\s*\{(.*?)\n\};", lib, re.DOTALL)
check("E1 PROGRESS_STAGE_NODES присутствует", block is not None)
if block:
    entries = dict(
        (k, tuple(re.findall(r'"([^"]+)"', raw)))
        for k, raw in re.findall(r'"([a-z_]+)":\s*\[([^\]]*)\]', block.group(1), re.DOTALL)
    )
    for stage in STAGES:
        if stage == "eda":
            continue
        check(f"E2 {stage}: узлы дословно с графом (порядок -- контракт §2)",
              entries.get(stage) == tuple(STAGE_NODES[stage]))
    check("E3 eda -- из общего JSON §12 п.2 (не вшитая копия)",
          "shared/pipeline_nodes/eda_checks.json" in lib
          and "edaChecksJson" in lib)
    eda_json = json.loads(read("shared/pipeline_nodes/eda_checks.json"))
    json_ids = tuple(n["id"] for n in eda_json["nodes"])
    check("E4 общий JSON действительно паритетен графу (eda)",
          json_ids == tuple(STAGE_NODES["eda"]))
    total = sum(len(v) for v in entries.values()) + len(json_ids)
    check("E5 суммарно 46 узлов (1+10+10+10+11+4)", total == 46,
          f"получено {total}")

# Метки узлов: у каждого не-EDA узла есть человекочитаемая метка.
labels = re.search(r"const NODE_LABELS: Record<string, Record<string, string>> = \{(.*?)\n\};", lib, re.DOTALL)
check("E6 NODE_LABELS присутствует", labels is not None)
if labels and block:
    missing = []
    for stage, ids in entries.items():
        for nid in ids:
            # Ключи в NODE_LABELS записаны без кавычек (identifier:).
            if not re.search(rf"\b{re.escape(nid)}\s*:", labels.group(1)):
                missing.append(f"{stage}/{nid}")
    check("E7 метка у каждого не-EDA узла", not missing, f"нет меток: {missing}")

# ── Блок F: свёртка §12 п.10 -- порт сверён с живым бэкендом ──────────
py_src = read("app/core/pipeline_graph.py")
check("F1 fold_status_values существует (источник порта)", "def fold_status_values" in py_src)
check("F2 TS: известные статусы = CheckStatus + in_progress (§3)",
      '"done", "warning", "pending", "skipped", "running", "error"' in lib
      and '"in_progress"' in lib)
check("F3 TS: STARTED_BEYOND_DONE = running/in_progress (как бэкенд)",
      '"running", "in_progress"' in lib)
check("F4 TS: неизвестный статус -- ошибка (fail-closed, §12 п.10)",
      "throw new Error" in lib and "Неизвестный статус узла" in lib)
check("F5 зеркальная таблица кейсов свёртки в progress.test.ts",
      "foldNodeStatuses" in read("packages/ui/lib/progress.test.ts"))

# ── Блок G: статусы узлов из фактов трассы (§4.1) ─────────────────────
mapping = re.search(r"const PROGRESS_EVENT_STATUS: Record<string, string> = \{(.*?)\};", lib, re.DOTALL)
check("G1 PROGRESS_EVENT_STATUS присутствует", mapping is not None)
if mapping:
    m = mapping.group(1)
    terminal = ["upload_completed", "correction_applied", "backtest_run",
                "tuning_trial_completed", "model_selected", "model_card_generated",
                "forecast_generated", "forecast_compared",
                "forecast_sensitivity_computed", "forecast_exported"]
    check("G2 терминальные -> done (все 10 типов)",
          all(re.search(rf'{t}:\s*"done"', m) for t in terminal))
    check("G3 correction_previewed -> warning (§6.2 «найдены проблемы»)",
          re.search(r'correction_previewed:\s*"warning"', m) is not None)
    check("G4 profile_viewed -> running", re.search(r'profile_viewed:\s*"running"', m) is not None)
    check("G5 stage-level события не в реестре узловых типов",
          "mode_changed" not in m and "target_column_changed" not in m
          and "passport_captured" not in m)

check("G6 deriveNodeStatuses: ключ 'stage/node_id' (регулярность/stационарность не путаются)",
      '`${event.stage}/${event.node_id}`' in lib)
check("G7 deriveNodeStatuses: фантомные узлы отсечены isKnownNode",
      "isKnownNode(event.stage, event.node_id)" in lib)
check("G8 collectForecastTraceEvents: node_id = event_type, stage = forecasting",
      'node_id: raw.event_type' in lib and 'stage: "forecasting"' in lib)
check("G9 collectForecastTraceEvents: чужие типы пропускаются (fail-safe)",
      "isKnownNode(\"forecasting\", raw.event_type)" in lib)

# ── Блок H: карточки стадий (§6.2, §12 п.10) ──────────────────────────
check("H1 bg-green-50/bg-amber-50/нейтральный -- семантика StatusIcon на фоне карточки",
      '"bg-green-50"' in flow and '"bg-amber-50"' in flow)
check("H2 StatusIcon переиспользуется как есть", "StatusIcon" in flow and "FOLD_ICON" in flow)
check("H3 подписи «найдены проблемы»/«в работе»/«пройдено»/«не начато»",
      "найдены проблемы" in lib and "в работе" in lib and "пройдено" in lib
      and "не начато" in lib)
check("H4 разворачивание стадии -- узлы списком, deep-link ссылкой (§6.2)",
      "<Link" in flow and "PROGRESS_STAGE_NODES[key]" in flow)
check("H5 стадии из STAGE_DEFS (единый источник с меню)",
      "STAGE_DEFS.map" in flow)
check("H6 трасса: фильтры по стадии/узлу (§6.2)",
      "stageFilter" in tracelog and "nodeFilter" in tracelog)
check("H7 трасса: события уровня стадии -- строка без узла",
      "event.node_id &&" in tracelog)
check("H8 трасса: смена стадии сбрасывает узел (узлы другой стадии)",
      "setNodeFilter(\"\")" in tracelog)
check("H9 трасса: битый ts -- как есть (честный рендер)",
      "Number.isNaN(date.getTime())" in tracelog)

# ── Блок I: атомарность замены слота (риск-таблица плана) ─────────────
upload = read("packages/ui/components/TsAnalysisUpload.tsx")
forecasting = read("packages/ui/components/TsAnalysisForecasting.tsx")
check("I1 TsAnalysisUpload: addLogEntry не вызывается в коде",
      "addLogEntry(" not in code_lines(upload))
check("I2 TsAnalysisForecasting: addLogEntry не вызывается в коде",
      "addLogEntry(" not in code_lines(forecasting))

# ── Блок J: находка F-1 -- EventsLogDrawer НЕ удалён ──────────────────
orphan = ROOT / "packages/ui/components/EventsLogDrawer.tsx"
check("J1 EventsLogDrawer.tsx удалён из репозитория (§6.1, DELETIONS.txt, план)",
      not orphan.exists(),
      "ФАЙЛ СУЩЕСТВУЕТ -- заявление об удалении (DELETIONS.txt/worklog8/план) "
      "не подтверждается коммитом 8a20ba3")
deletions = read("DELETIONS.txt")
check("J2 DELETIONS.txt согласован с деревом", "удалён" in deletions and not orphan.exists())

# ── Блок K: тест-контур исполнителя декларирует заявленное ────────────
check("K1 тест-сьют панели существует и покрывает оба контура",
      "TestProgressTraceEndpoint" in panel_tests
      and "TestFrontendNodeRegistrySync" in panel_tests)
check("K2 sync-тест: regex-парсер живого .ts (не транскрипиляция)",
      "_parse_ts_stage_nodes" in panel_tests)

# ── Итог ──────────────────────────────────────────────────────────────
passed = sum(1 for _, ok in RESULTS if ok)
total = len(RESULTS)
print(f"CROSSVERIFY: {passed}/{total} PASSED")
for name, ok in RESULTS:
    if not ok:
        print(f"  FAIL: {name}")
for n in NOTES:
    print(f"  note: {n}")
sys.exit(0 if passed == total else 1)
