# scripts/progr2cert_crossverify.py
# Task PROGR-2-CERT -- независимая кросс-верификация фактов PROGR-2
# по живым модулям и по фронтенд-зеркалам. Ожидания читаются из ЖИВЫХ
# исходников (regex по исходному тексту), а не из pipeline_graph.
"""Кросс-верификация графа пайплайна (аудит PROGR-2).
Запуск: python3 /home/z/my-project/scripts/progr2cert_crossverify.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
FAILED: list[str] = []
PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} {detail}")


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


print("=== A. Живые Python-реестры (regex по исходникам, не через граф) ===")
rr = read("validation/rule_resolver.py")
m = re.search(r"CHECK_IDS\s*=\s*\(([^)]*)\)", rr, re.DOTALL)
live_validation = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))

sess = read("apps/api/routers/session.py")
m = re.search(r"PREPROCESSING_CHECK_IDS[^=]*=\s*\(([^)]*)\)", sess, re.DOTALL)
live_preproc = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))

mr = read("apps/api/model_readiness.py")
m = re.search(r"MODELING_STAGE_IDS[^=]*=\s*\(([^)]*)\)", mr, re.DOTALL)
live_modeling = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))

ss = read("apps/api/session_store.py")
m = re.search(r'^STAGES\s*=\s*[\[(]([^\])>]*)[\])]', ss, re.DOTALL | re.MULTILINE)
live_store_stages = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))
store_is_list = re.search(r'^STAGES\s*=\s*\[', ss, re.MULTILINE) is not None

te = read("apps/api/trace_events.py")
m = re.search(r"KNOWN_STAGES\s*=\s*\(([^)]*)\)", te, re.DOTALL)
live_known_stages = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))

sic = read("packages/ui/components/StatusIcon.tsx")
m = re.search(r'export type CheckStatus\s*=\s*([^;]+);', sic)
live_check_status = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))

st = read("packages/ui/lib/stages.ts")
m = re.search(r'export type StageStatus\s*=\s*([^;]+);', st)
live_stage_status = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))

print(f"  rule_resolver.CHECK_IDS = {live_validation}")
print(f"  session.PREPROCESSING_CHECK_IDS = {live_preproc}")
print(f"  model_readiness.MODELING_STAGE_IDS = {live_modeling}")
print(f"  session_store.STAGES = {live_store_stages} (list={store_is_list})")
print(f"  trace_events.KNOWN_STAGES = {live_known_stages}")
print(f"  StatusIcon.CheckStatus = {live_check_status}")
print(f"  stages.ts.StageStatus = {live_stage_status}")

sys.path.insert(0, str(REPO))
from app.core import pipeline_graph as pg  # noqa: E402

print("\n=== B. Сверка графа с живыми реестрами ===")
check("B1 STAGES == session_store.STAGES", pg.STAGES == live_store_stages)
check("B2 STAGES == trace_events.KNOWN_STAGES", pg.STAGES == live_known_stages)
check("B3 validation == живой CHECK_IDS", pg.STAGE_NODES["validation"] == live_validation)
check("B4 preprocessing == живой PREPROCESSING_CHECK_IDS", pg.STAGE_NODES["preprocessing"] == live_preproc)
check("B5 modeling == живой MODELING_STAGE_IDS", pg.STAGE_NODES["modeling"] == live_modeling)
check("B6 CHECK_STATUS_VALUES == StatusIcon.CheckStatus", pg.CHECK_STATUS_VALUES == live_check_status)
check("B7 PROCESS_STATUS_VALUES == stages.ts.StageStatus", pg.PROCESS_STATUS_VALUES == live_stage_status)

print("\n=== C. Идентичность объектов (is), §2 «не дублирует, а ссылается» ===")
import apps.api.model_readiness as mr_mod  # noqa: E402
import apps.api.routers.session as sess_mod  # noqa: E402
import validation.rule_resolver as rr_mod  # noqa: E402

check("C1 STAGE_NODES['validation'] is CHECK_IDS", pg.STAGE_NODES["validation"] is rr_mod.CHECK_IDS)
check("C2 STAGE_NODES['preprocessing'] is PREPROCESSING_CHECK_IDS", pg.STAGE_NODES["preprocessing"] is sess_mod.PREPROCESSING_CHECK_IDS)
check("C3 STAGE_NODES['modeling'] is MODELING_STAGE_IDS", pg.STAGE_NODES["modeling"] is mr_mod.MODELING_STAGE_IDS)

print("\n=== D. Направление зависимостей (риск-таблица плана) ===")
pg_src = read("app/core/pipeline_graph.py")
pg_imports = re.findall(r"^(?:from|import)\s+(\S+)", pg_src, re.MULTILINE)
check("D1 нет импорта session_store из pipeline_graph", not any("session_store" in i for i in pg_imports), str(pg_imports))
check("D2 нет импорта pipeline_graph из session_store", "pipeline_graph" not in read("apps/api/session_store.py"))

print("\n=== E. EDA JSON vs прежний литерал .tsx (byte-for-byte, git 0a4252b) ===")
old_tsx = subprocess.run(
    ["git", "show", "0a4252b:packages/ui/components/TsAnalysisEDA.tsx"],
    cwd=REPO, capture_output=True, text=True, check=True,
).stdout
ENTRY_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>[a-z_]+)",\s*'
    r'label:\s*"(?P<label>[^"]*)",\s*'
    r'status:\s*"pending",\s*count:\s*null,\s*'
    r'description:\s*"(?P<description>[^"]*)"\s*,?\s*\}',
    re.DOTALL,
)
old_entries = [
    {"id": mm["id"], "label": mm["label"], "description": mm["description"]}
    for mm in ENTRY_RE.finditer(old_tsx)
]
json_raw = json.loads(read("shared/pipeline_nodes/eda_checks.json"))
new_entries = [
    {"id": n["id"], "label": n["label"], "description": n["description"]}
    for n in json_raw["nodes"]
]
check("E1 старый литерал найден (10 записей)", len(old_entries) == 10, str(len(old_entries)))
check("E2 JSON-узлы дословно равны прежнему литералу .tsx", new_entries == old_entries)
if new_entries != old_entries:
    for i, (a, b) in enumerate(zip(new_entries, old_entries)):
        if a != b:
            print(f"    расхождение #{i}: new={a}  old={b}")

print("\n=== F. Новый .tsx: идемпотентность рантайм-маппинга ===")
new_tsx = read("packages/ui/components/TsAnalysisEDA.tsx")
check("F1 .tsx импортирует общий JSON", "shared/pipeline_nodes/eda_checks.json" in new_tsx)
check("F2 в .tsx нет вшитого литерала CHECKS", '{ id: "descriptive", label:' not in new_tsx)
check("F3 CHECKS строится map-ом с pending/null", 'status: "pending" as CheckStatus' in new_tsx and "count: null" in new_tsx)
for n in json_raw["nodes"]:
    check(f"F4 маппинг статуса для {n['id']} присутствует", f'check.id === "{n["id"]}"' in new_tsx)

print(f"\nИтог: {PASSED} PASS / {len(FAILED)} FAIL")
if FAILED:
    print("Упавшие:", ", ".join(FAILED))
    raise SystemExit(1)
print("КРОСС-ВЕРИФИКАЦИЯ ЗЕЛЁНАЯ")
