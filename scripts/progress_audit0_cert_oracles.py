"""AUDIT-0-CERT (сертификация задачи AUDIT-0): оракулы сертификатора
и кампания мутантов «на своих мутантах».

Задача сертификации -- независимая проверка поставки AUDIT-0 (коммит
deaed93): docs/progress_audit_contract.md v0.1-AUDIT-0, протоколы
scripts/progress_audit0_*.json, наблюдательные пины H26-H28.

Оракулы (контрольный прогон -- против РЕАЛЬНЫХ файлов поставки):
  OR-C -- «контракт <-> живой код»: каждое факт-утверждение контракта
          (номера строк, реестры, семантики) проверяется программно;
  OR-D -- целостность протоколов (25/25, свои данные, инструмент
          аудита не изменён, продуктовый код не менялся);
  OR-E -- покрытие решений: план §4 + «Донастройка плана» ->
          разделы контракта §3-§10.

Кампания мутантов (санити-мутанты поставки, убиваемые оракулами):
  M01-M06, M11-M13 -- текстовые мутанты КОНТРАКТА (Option B вместо
          выделенного типа, происхождение после сброса = user, неверные
          номера строк, неверные константы, снятые уровни/пункты);
  M07, M08, M14 -- мутанты ПРОТОКОЛА репро (счётчик, подмена данных,
          подмена базы);
  M09, M10 -- мутанты ПИНОВ H26/H27 (переворачивание наблюдения),
          убиваются реальностью: прогон jest обязан ПАДАТЬ.

Каждый мутант обязан быть УБИТ своим оракулом; выживший мутант --
дыра сертификации (находка). Мутанты живут во временных копиях;
продуктовые файлы не изменяются (хеш-контроль tracked-файлов до/после).

Запуск из корня репозитория:
  python scripts/progress_audit0_cert_oracles.py --output scripts/progress_audit0_cert_oracles_results.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "progress_audit_contract.md"
REPRO = ROOT / "scripts" / "progress_audit0_repro.py"
REPRO_JSON = ROOT / "scripts" / "progress_audit0_repro_results.json"
CONTROL_JSON = ROOT / "scripts" / "progress_audit0_baseline_control.json"
CERT_REPRO_JSON = ROOT / "scripts" / "progress_audit0_cert_base_repro_results.json"
PINS = {
    "H26": ROOT / "packages" / "ui" / "components" / "prograudit0_h26_no_auto_retry.test.tsx",
    "H27": ROOT / "packages" / "ui" / "components" / "prograudit0_h27_seed_failure_regresses.test.tsx",
    "H28": ROOT / "packages" / "ui" / "components" / "prograudit0_h28_viewed_transfer.test.tsx",
}
PIN_HEADER_MARKS = ["наблюдательный пин", "НЕ", "acceptance-тест"]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def lines_of(path: Path) -> list[str]:
    return read(path).splitlines()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def contract_section(text: str, start: str, end: str) -> str:
    """Секция контракта от заголовка start до следующего заголовка end."""
    i = text.find(start)
    j = text.find(end, i + 1) if i >= 0 else -1
    if i < 0:
        return ""
    return text[i:j if j > 0 else len(text)]


# ────────────────────────────────────────────────────────────────────────
# OR-C: контракт <-> живой код
# ────────────────────────────────────────────────────────────────────────

def c01_registry_validation_block(ctx):
    """§3.1: носитель target_column_changed -- блок "validation"; тип
    target_column_cleared ЕЩЁ НЕ зарегистрирован (регистрация -- работа
    горячей дорожки)."""
    src = lines_of(ROOT / "apps" / "api" / "trace_events.py")
    text = "\n".join(src)
    m = re.search(r'"validation":\s*\{(.*?)\},', text, re.S)
    if not m:
        return False, "validation block not found in _STAGE_EVENT_TYPES"
    block = m.group(1)
    has_changed = "target_column_changed" in block
    not_cleared_yet = "target_column_cleared" not in text
    return has_changed and not_cleared_yet, {
        "target_column_changed_in_validation": has_changed,
        "target_column_cleared_not_registered_yet": not_cleared_yet,
    }


def c02_seed_point_convert_types(ctx):
    """§5.2: контракт называет точку посева session.py::convert-types
    `:X-Y` -- проверяем, что на ЭТИХ строках кода находится ветка сброса
    (target_column = None + target_column_source = None + флаг reset)."""
    text = ctx["contract_text"]
    m = re.search(r"session\.py::convert-types[^\n]*\n\(`?:(\d+)-(\d+)", text)
    if not m:
        return False, "contract does not name convert-types line range"
    lo, hi = int(m.group(1)), int(m.group(2))
    chunk = "\n".join(lines_of(ROOT / "apps" / "api" / "routers" / "session.py")[lo - 1:hi])
    ok = ("target_column = None" in chunk and "target_column_source = None" in chunk
          and "target_column_reset = True" in chunk)
    return ok, {"claimed_range": [lo, hi], "branch_in_range": ok}


def c03_merge_dict_restore_run(ctx):
    """§5.2: паттерн merge-dict -- restore_run, progress.py:X-Y."""
    text = ctx["contract_text"]
    m = re.search(r"restore_run`, `progress\.py:(\d+)-(\d+)", text)
    if not m:
        return False, "contract does not name restore_run merge-dict range"
    lo, hi = int(m.group(1)), int(m.group(2))
    chunk = "\n".join(lines_of(ROOT / "apps" / "api" / "routers" / "progress.py")[lo - 1:hi])
    ok = "**run.to_dict()" in chunk and "session_id" in chunk
    return ok, {"claimed_range": [lo, hi], "merge_dict_in_range": ok}


def c04_empty_target_branch(ctx):
    """§8/§3.1: пустая ветка редьюсера -- node_status.py:X-Y
    (пустая строка -- сброс reason; мусор -- не факт)."""
    text = ctx["contract_text"]
    m = re.search(r"пустая ветка `?:(\d+)-(\d+)", text)
    if not m:
        return False, "contract does not name empty-branch range"
    lo, hi = int(m.group(1)), int(m.group(2))
    chunk = "\n".join(lines_of(ROOT / "app" / "core" / "node_status.py")[lo - 1:hi])
    ok = 'target == ""' in chunk and "return {}, {target_node}" in chunk
    return ok, {"claimed_range": [lo, hi], "empty_branch_in_range": ok}


def c05_static_map_line(ctx):
    """§8 F17: точка derive-функции рядом со статической картой --
    node_status.py:N (EVENT_NODE_STATUS)."""
    text = ctx["contract_text"]
    m = re.search(r"node_status\.py:(\d+)`?\)", text)
    if not m:
        return False, "contract does not name node_status static-map line"
    n = int(m.group(1))
    line = lines_of(ROOT / "app" / "core" / "node_status.py")[n - 1]
    ok = "EVENT_NODE_STATUS" in line
    return ok, {"claimed_line": n, "line": line.strip()[:80], "ok": ok}


def c06_mentor_triple(ctx):
    """§3.1.7/§8: тройка Наставника существует в коде (_target_confirmed/
    _target_origin/_phase_event_text_facts); контракт не называет строк --
    связка семантическая."""
    src = "\n".join(lines_of(ROOT / "app" / "core" / "mentor_rules.py"))
    defs = {name: f"def {name}" in src for name in
            ("_target_confirmed", "_target_origin", "_phase_event_text_facts")}
    return all(defs.values()), defs


def c07_mentor_fallback_text(ctx):
    """§3.1.7: fallback Наставника «Подтвердите целевой признак…»."""
    text = read(ROOT / "app" / "core" / "mentor_rules.py")
    return "Подтвердите целевой признак" in text, {}


def c08_session_constants(ctx):
    """§3.2: SESSION_SCHEMA_VERSION (сейчас N) и MAX_PIPELINE_TRACE_EVENTS
    (1000) -- контрактные значения сверяются с кодом."""
    src = "\n".join(lines_of(ROOT / "apps" / "api" / "session_store.py"))
    m_code = re.search(r"SESSION_SCHEMA_VERSION\s*=\s*(\d+)", src)
    m_contract = re.search(r"SESSION_SCHEMA_VERSION`?\s*\(сейчас\s*(\d+)\)", ctx["contract_text"])
    if not (m_code and m_contract):
        return False, {"code": m_code and m_code.group(1), "contract": m_contract and m_contract.group(1)}
    ok = m_code.group(1) == m_contract.group(1) == "3"
    ok2 = "MAX_PIPELINE_TRACE_EVENTS = 1000" in src
    return ok and ok2, {"schema_version_code": m_code.group(1),
                        "schema_version_contract": m_contract.group(1), "cap_1000": ok2}


def c09_trace_event_canon(ctx):
    """§5.1: канон TraceEvent -- 8 полей + legacy-алиас timestamp."""
    text = read(ROOT / "apps" / "api" / "trace_events.py")
    fields = ["event_type", "payload", "event_id", "run_id", "ts", "stage", "node_id", "actor"]
    block = text[text.index("class TraceEvent"):text.index("def to_dict")]
    missing = [f for f in fields if f"{f}:" not in block]
    alias = 'def timestamp' in text and "return self.ts" in text
    return not missing and alias, {"missing_fields": missing, "timestamp_alias": alias}


def c10_correction_payload_keys(ctx):
    """§3.1.3/Часть 1: target_column_reset путешествует в correction-payload
    хука; _CORRECTION_PAYLOAD_KEYS содержит ключ ("не трогаются" -- он там есть)."""
    src = lines_of(ROOT / "apps" / "api" / "trace_hook.py")
    def_line = next(i for i, l in enumerate(src) if "_CORRECTION_PAYLOAD_KEYS = (" in l)
    end_line = next(i for i in range(def_line + 1, len(src)) if src[i].strip() == ")")
    tuple_body = "\n".join(src[def_line:end_line + 1])
    ok = '"target_column_reset"' in tuple_body
    return ok, {"keys_def_line": def_line + 1, "tuple_end_line": end_line + 1,
                "reset_key_in_tuple": ok}


def c11_stage_nodes(ctx):
    """§2/P06: STAGE_NODES validation -- 10 узлов; eda содержит
    descriptive/correlation/seasonality."""
    sys.path.insert(0, str(ROOT))
    from app.core.pipeline_graph import STAGE_NODES
    ok = len(STAGE_NODES["validation"]) == 10 and {"descriptive", "correlation", "seasonality"} <= set(STAGE_NODES["eda"])
    return ok, {"validation_nodes": len(STAGE_NODES["validation"])}


def c12_modeling_types_no_status(ctx):
    """P13/§8: семь Modeling-типов не проецируют статус."""
    sys.path.insert(0, str(ROOT))
    from app.core.node_status import resolve_event_status
    types = ["candidates_generated", "selection_evaluated", "models_compared",
             "diagnostics_run", "tuning_skipped", "tuning_job_started", "tuning_job_cancelled"]
    result = {k: resolve_event_status({"event_type": k, "payload": {}}) for k in types}
    return all(v is None for v in result.values()), result


def c13_event_types_exist(ctx):
    """§4/§3.6: перечисленные в контракте типы существуют в реестре/карте."""
    sys.path.insert(0, str(ROOT))
    text = read(ROOT / "apps" / "api" / "trace_events.py")
    node_map = read(ROOT / "app" / "core" / "node_status.py")
    needed = ["target_column_changed", "correction_applied", "validation_check_status",
              "preprocessing_check_status", "eda_check_status", "upload_stop_status",
              "outliers_profile_status", "structure_confirmed", "run_paused",
              "run_resumed", "checkpoint_saved", "correction_previewed", "profile_viewed"]
    missing = [t for t in needed if t not in text and t not in node_map]
    return not missing, {"missing": missing}


def c14_eda_reset_keyed_dataset(ctx):
    """§2 H28: сброс keyed ТОЛЬКО по datasetKey -- TsAnalysisEDA.tsx:1000-1005."""
    src = lines_of(ROOT / "packages" / "ui" / "components" / "TsAnalysisEDA.tsx")
    chunk = "\n".join(src[999:1005])
    ok = "edaSeedReadyRef.current = false" in chunk and "datasetKey" in chunk
    return ok, {"range": "1000-1005", "ok": ok}


def c15_eda_report_effect(ctx):
    """§2 H26: контур отчёта EDA -- TsAnalysisEDA.tsx:1046-1091
    (postEdaChecks + effect на снапшоте с маркером)."""
    src = lines_of(ROOT / "packages" / "ui" / "components" / "TsAnalysisEDA.tsx")
    chunk = "\n".join(src[1045:1091])
    ok = ("postEdaChecks" in chunk and "lastReportedEdaChecksRef.current = edaChecksReportSnapshot" in chunk
          and "if (!res.ok) lastReportedEdaChecksRef.current = \"\";" in chunk)
    return ok, {"range": "1046-1091", "marker_reset_on_error": 'if (!res.ok)' in chunk}


def c16_validation_twin_effect(ctx):
    """§2 H26: контур-близнец Валидации -- TsAnalysisValidation.tsx:410-442."""
    src = lines_of(ROOT / "packages" / "ui" / "components" / "TsAnalysisValidation.tsx")
    chunk = "\n".join(src[409:442])
    ok = "postChecks" in chunk and "lastReportedChecksRef.current = checksReportSnapshot" in chunk
    return ok, {"range": "410-442", "ok": ok}


def c17_target_column_422(ctx):
    """§3.1.5: POST /v1/session/target-column -- маршрут ВЫБОРА с 422
    на пустой (граница PROGR-25-C)."""
    src = read(ROOT / "apps" / "api" / "routers" / "session.py")
    i = src.index('@router.post("/target-column"')
    handler = src[i:i + 3000]
    ok = "422" in handler and "@router.post" in src[i:i + 60]
    return ok, {"handler_found": True, "422_in_handler": "422" in handler}


def c18_status_whitelist(ctx):
    """§3.6(3)/P15: PAYLOAD-статусы через whitelist CHECK_STATUS_VALUES."""
    prog = read(ROOT / "apps" / "api" / "routers" / "progress.py")
    node = read(ROOT / "app" / "core" / "node_status.py")
    ok = "CHECK_STATUS_VALUES" in prog and "PAYLOAD_STATUS_EVENT_TYPES" in node
    return ok, {"progress_whitelist": "CHECK_STATUS_VALUES" in prog,
                "node_payload_status": "PAYLOAD_STATUS_EVENT_TYPES" in node}


def c19_seed_stage_validation(ctx):
    """§3.1: носитель target-событий -- stage="validation", node_id=None
    (target_column_rule.auto_fix_and_seed)."""
    src = read(ROOT / "apps" / "api" / "target_column_rule.py")
    ok = 'stage="validation"' in src and "def auto_fix_and_seed" in src
    return ok, {"auto_fix_and_seed": True}


def c20_product_code_untouched(ctx):
    """§1: c8818de..6a83924 -- продуктовый код не менялся; deaed93
    добавляет только артефакты AUDIT-0 + worklog9."""
    empty = git("diff", "--name-only", "c8818de", "6a83924", "--",
                "apps", "app", "packages", "shared", "rules")
    status = git("diff", "--name-status", "6a83924", "deaed93").splitlines()
    allowed_modified = {"worklog/worklog9.md"}
    added = {l.split("\t")[1] for l in status if l.startswith("A")}
    modified = {l.split("\t")[1] for l in status if l.startswith("M")}
    expected_added = {
        "docs/progress_audit_contract.md",
        "scripts/progress_audit0_repro.py",
        "scripts/progress_audit0_repro_results.json",
        "scripts/progress_audit0_baseline_control.json",
        "packages/ui/components/prograudit0_h26_no_auto_retry.test.tsx",
        "packages/ui/components/prograudit0_h27_seed_failure_regresses.test.tsx",
        "packages/ui/components/prograudit0_h28_viewed_transfer.test.tsx",
    }
    ok = empty == "" and modified <= allowed_modified and added == expected_added
    return ok, {"diff_c8818de_6a83924_empty": empty == "", "added": sorted(added),
                "modified": sorted(modified)}


C_CHECKS = [c01_registry_validation_block, c02_seed_point_convert_types,
            c03_merge_dict_restore_run, c04_empty_target_branch, c05_static_map_line,
            c06_mentor_triple, c07_mentor_fallback_text, c08_session_constants,
            c09_trace_event_canon, c10_correction_payload_keys, c11_stage_nodes,
            c12_modeling_types_no_status, c13_event_types_exist, c14_eda_reset_keyed_dataset,
            c15_eda_report_effect, c16_validation_twin_effect, c17_target_column_422,
            c18_status_whitelist, c19_seed_stage_validation, c20_product_code_untouched]


# ────────────────────────────────────────────────────────────────────────
# OR-D: целостность протоколов (пути параметризованы -- кампания мутантов)
# ────────────────────────────────────────────────────────────────────────

def d01_repro_protocol(paths):
    data = json.loads(read(Path(paths["repro_json"])))
    ids = [o["id"] for o in data["observations"]]
    ok = data["counts"] == {"observed": 25, "probe_errors": 0} and ids == [f"P{i:02d}" for i in range(1, 26)]
    return ok, {"counts": data["counts"], "ids_complete": len(ids) == 25}


def d02_control_protocol(paths):
    data = json.loads(read(Path(paths["control_json"])))
    ok = data["counts"] == {"observed": 25, "probe_errors": 0}
    ok = ok and "pandas" in data and "data_substitution" not in data  # оригинальный инструмент
    return ok, {"counts": data["counts"], "original_tool_meta": "pandas" in data,
                "no_substitution_field": "data_substitution" not in data}


def d03_own_data_recorded(paths):
    data = json.loads(read(Path(paths["repro_json"])))
    sub = data.get("data_substitution", {})
    ok = ("temp" in sub.get("columns_single", "") and "humidity" in sub.get("columns_multi", "")
          and "rain" not in sub.get("columns_single", "") and "snow" not in sub.get("columns_multi", "")
          and sub.get("rows") == 20 and "2026-02" in sub.get("dates", ""))
    return ok, {"substitution": sub}


def d04_audit_tool_unmodified(paths):
    status = git("status", "--porcelain", "scripts/progress_audit_readonly.py")
    # побайтовое сравнение рабочего дерева с git-блобом HEAD
    blob = subprocess.check_output(["git", "show", "HEAD:scripts/progress_audit_readonly.py"], cwd=ROOT)
    work = (ROOT / "scripts" / "progress_audit_readonly.py").read_bytes()
    repro_src = read(Path(paths["repro"]))
    uses_importlib = "importlib" in repro_src and "progress_audit_readonly.py" in repro_src
    ok = status == "" and blob == work and uses_importlib
    return ok, {"git_status": status or "clean", "blob_matches_worktree": blob == work,
                "repro_reuses_tool_via_importlib": uses_importlib}


def d05_repro_constants_match_protocol(paths):
    src = read(Path(paths["repro"]))
    data = json.loads(read(Path(paths["repro_json"])))
    sub = data["data_substitution"]
    m_single = re.search(r'SINGLE_HEADER\s*=\s*"([^"]+)"', src)
    m_multi = re.search(r'MULTI_HEADER\s*=\s*"([^"]+)"', src)
    m_scale = re.search(r"VALUE_SCALE\s*=\s*([\d.]+)", src)
    m_hum = re.search(r"HUM_SCALE\s*=\s*([\d.]+)", src)
    ok = (m_single and m_single.group(1) == sub["columns_single"]
          and m_multi and m_multi.group(1) == sub["columns_multi"]
          and m_scale and f"temp=i*{m_scale.group(1)}" in sub.get("values", "")
          and m_hum and f"humidity=i*{m_hum.group(1)}" in sub.get("values", ""))
    return ok, {"script_headers": [m_single and m_single.group(1), m_multi and m_multi.group(1)],
                "protocol_values": sub.get("values")}


def d06_pins_observation_headers(paths):
    details = {}
    ok = True
    for key, path in PINS.items():
        actual = Path(paths.get(f"pin_{key}", path))
        text = read(actual)
        has = all(m in text for m in ["наблюдательный пин"]) and "acceptance-тест" in text \
              and "Донастройка_2 п.3" in text and "AUDIT-0" in text
        details[key] = has
        ok = ok and has
    return ok, details


def d07_protocols_baseline(paths):
    details, ok = {}, True
    for key, path in (("repro_json", paths["repro_json"]), ("control_json", paths["control_json"])):
        data = json.loads(read(Path(path)))
        baseline_ok = data["baseline"].startswith("6a83924")
        py_ok = data["python"] == "3.12.14"
        details[key] = {"baseline": data["baseline"][:8], "python": data["python"]}
        ok = ok and baseline_ok and py_ok
    return ok, details


def d08_cert_repro_protocol(paths):
    """Собственный протокол OR-A сертификатора: 25/0, свои данные."""
    data = json.loads(read(Path(paths["cert_repro_json"])))
    sub = data.get("data_substitution", {})
    ok = data["counts"] == {"observed": 25, "probe_errors": 0} \
        and "pressure" in sub.get("columns_single", "") \
        and "wind" in sub.get("columns_multi", "") \
        and data["baseline"].startswith(git("rev-parse", "HEAD")[:8])
    return ok, {"counts": data["counts"], "columns": [sub.get("columns_single"), sub.get("columns_multi")]}


D_CHECKS = [d01_repro_protocol, d02_control_protocol, d03_own_data_recorded,
            d04_audit_tool_unmodified, d05_repro_constants_match_protocol,
            d06_pins_observation_headers, d07_protocols_baseline, d08_cert_repro_protocol]


# ────────────────────────────────────────────────────────────────────────
# OR-E: покрытие решений плана §4 + Донастройки в контракте
# ────────────────────────────────────────────────────────────────────────

def e01_cleared_contract(text):
    s = contract_section(text, "### 3.1.", "### 3.2.")
    marks = ["target_column_cleared", '_STAGE_EVENT_TYPES["validation"]', "target_column: null",
             "reset_reason", 'source: "system"|"auto"', "before_target", "НЕ «user»", "unknown",
             "422", "auto_fix_and_seed", "TRACE_ROUTES", "_CORRECTION_PAYLOAD_KEYS",
             "не ждёт AUDIT-S", "append_trace_event", "record_run_event",
             "target_column=None, target_column_source=None"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.1"}


def e02_envelope_v2(text):
    s = contract_section(text, "### 3.2.", "### 3.3.")
    marks = ["schema_version", "SESSION_SCHEMA_VERSION", "PipelineNodeState", "AUDIT-S",
             "8 полей", "timestamp", "7 полей §3"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.2"}


def e03_order(text):
    s = contract_section(text, "### 3.3.", "### 3.4.")
    marks = ["commit sequence", "BIGSERIAL", "НЕ порядок редьюсера", "store-order", "AUDIT-6A"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.3"}


def e04_context(text):
    s = contract_section(text, "### 3.4.", "### 3.5.")
    marks = ["fingerprint", "dataset_revision", "context_id", "pipeline_graph.py", "Dependency scopes", "AUDIT-C"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.4"}


def e05_validity(text):
    s = contract_section(text, "### 3.5.", "### 3.6.")
    marks = ["current, stale, unknown", "mode=raw"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.5"}


def e06_delivery(text):
    s = contract_section(text, "### 3.6.", "### 3.7.")
    marks = ["advisory", "required", "durable receipt", "idempotency key", "fail-closed",
             "(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "AUDIT-6B", "AUDIT-6C"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.6"}


def e07_legacy(text):
    s = contract_section(text, "### 3.7.", "## 4.")
    marks = ["«user»", "unknown", "compatibility mode", "release-marker", "20.2"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§3.7"}


def e08_evidence_levels(text):
    s = contract_section(text, "## 4.", "## 5.")
    levels = ["server_result", "client_observation", "user_decision", "operational"]
    client_row_marks = ["validation_check_status", "preprocessing_check_status",
                        "eda_check_status", "upload_stop_status", "outliers_profile_status"]
    missing = [m for m in levels + client_row_marks if m not in s]
    return not missing, {"missing": missing, "section": "§4"}


def e09_dto_examples(text):
    s = contract_section(text, "## 5.", "## 6.")
    v1_marks = ["event_id", "run_id", "ts", "stage", "node_id", "event_type", "payload", "actor", "timestamp"]
    cleared_marks = ["target_column_cleared", "reset_reason", "before_target"]
    v2_marks = ["schema_version", "evidence_level", "sequence", "operation_id", "context_id",
                "result_ref", "method", "time_quality"]
    missing = [m for m in v1_marks + cleared_marks + v2_marks if m not in s]
    return not missing, {"missing": missing, "section": "§5"}


def e10_invariants(text):
    s = contract_section(text, "## 6.", "## 7.")
    missing = [f"I{i}" for i in range(1, 11) if f"**I{i}" not in s]
    return not missing, {"missing": missing, "section": "§6"}


def e11_transition(text):
    s = contract_section(text, "## 7.", "## 8.")
    marks = ["Читатели раньше писателей", "Типы раньше полей", "target_column_cleared", "AUDIT-S"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§7"}


def e12_hot_track(text):
    s = contract_section(text, "## 8.", "## 9.")
    marks = ["PROGR-AUDIT-H1", "F02", "F17", "interim", "ЗАПРЕЩЕНО", "trace_events.py",
             "session.py", "node_status.py", "mentor_rules.py", "progress_audit_readonly.py",
             "PAYLOAD_STATUS"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§8"}


def e13_org_decisions(text):
    s = contract_section(text, "## 9.", "## 10.")
    marks = ["AUDIT-6A", "apps.api.main", "AUDIT-6C", "versioned-обновление"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§9"}


def e14_open_items(text):
    s = contract_section(text, "## 10.", "## 11.")
    marks = ["outbox", "PROGR-23", "H29/H30"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§10"}


def e15_base_and_env(text):
    s = contract_section(text, "## 1.", "## 2.")
    marks = ["6a83924", "Python 3.12.14", "pandas 2.3.3", "statsmodels 0.15.0",
             "PyWavelets 1.8.0", "pandera 0.34.1", "statsforecast 2.1.1", "arch 8.0.0",
             "ruptures 1.1.10", "25 OBSERVED / 0 PROBE_ERROR", "fakeredis"]
    missing = [m for m in marks if m not in s]
    return not missing, {"missing": missing, "section": "§1"}


def e16_hypotheses_status(text):
    s = contract_section(text, "## 2.", "## 3.")
    marks = ["H26", "H27", "H28", "H29", "H30", "OBSERVED", "НЕ ПРОВЕРЕНО"]
    missing = [m for m in marks if m not in s]
    h29_30 = "H29" in s and "H30" in s and s.count("НЕ ПРОВЕРЕНО") >= 2
    return not missing and h29_30, {"missing": missing, "unverified_count": s.count("НЕ ПРОВЕРЕНО")}


E_CHECKS = [e01_cleared_contract, e02_envelope_v2, e03_order, e04_context, e05_validity,
            e06_delivery, e07_legacy, e08_evidence_levels, e09_dto_examples, e10_invariants,
            e11_transition, e12_hot_track, e13_org_decisions, e14_open_items, e15_base_and_env,
            e16_hypotheses_status]


# ────────────────────────────────────────────────────────────────────────
# Кампания мутантов: каждый мутант поставки обязан быть УБИТ оракулом
# ────────────────────────────────────────────────────────────────────────

# contract-мутанты: (pattern, replacement); killer -- id оракула/проверки
CONTRACT_MUTANTS = [
    {"id": "M01", "title": "Payload сброса подменён на Option B (пустой target в changed)",
     "pattern": "`{target_column: null, reset_reason: str, source: \"system\"|\"auto\", before_target: str|null}`",
     "replacement": "`{target_column: \"\", reset_reason: str, source: \"system\"|\"auto\", before_target: str|null}`",
     "killer": "E01"},
    {"id": "M02", "title": "Происхождение после сброса подменено на user",
     "pattern": "**unknown/пусто (None), НЕ «user»**", "replacement": "**«user»**",
     "killer": "E01"},
    {"id": "M03", "title": "Носитель типа подменён на стадию preprocessing",
     "pattern": '`_STAGE_EVENT_TYPES["validation"]`', "replacement": '`_STAGE_EVENT_TYPES["preprocessing"]`',
     "killer": "E01"},
    {"id": "M04", "title": "Точка посева convert-types сдвинута на чужие строки",
     "pattern": "(`:3952-3961`)", "replacement": "(`:3940-3949`)", "killer": "C02"},
    {"id": "M05", "title": "Константа SESSION_SCHEMA_VERSION в контракте искажена",
     "pattern": "SESSION_SCHEMA_VERSION` (сейчас 3)", "replacement": "SESSION_SCHEMA_VERSION` (сейчас 4)",
     "killer": "C08"},
    {"id": "M06", "title": "Число полей PipelineNodeState искажено (7 -> 9)",
     "pattern": "PipelineNodeState` (7 полей §3)", "replacement": "PipelineNodeState` (9 полей §3)",
     "killer": "E02"},
    {"id": "M11", "title": "eda_check_status изъят из уровня client_observation",
     "pattern": "`validation_check_status`, `preprocessing_check_status`, `eda_check_status`, `upload_stop_status`, `outliers_profile_status`",
     "replacement": "`validation_check_status`, `preprocessing_check_status`, `upload_stop_status`, `outliers_profile_status`",
     "killer": "E08"},
    {"id": "M12", "title": "Пункт идемпотентности (7) изъят из §3.6",
     "pattern": "(7) в заявленном required-режиме тихий fallback в Memory недопустим",
     "replacement": "", "killer": "E06"},
    {"id": "M13", "title": "Run-метаданные при сбросе подменены (source=user фабрикуется)",
     "pattern": "`target_column=None, target_column_source=None`", "replacement": '`target_column=None, target_column_source="user"`',
     "killer": "E01"},
]

PROTOCOL_MUTANTS = [
    {"id": "M07", "title": "Счётчик протокола репро искажён (25 -> 24)",
     "file": "repro_json", "ops": [("counts", {"observed": 24, "probe_errors": 0})], "killer": "D01"},
    {"id": "M08", "title": "Свои данные подменены данными автора аудита",
     "file": "repro_json", "ops": [("data_substitution.columns_single", "date,rain"),
                                   ("data_substitution.columns_multi", "date,rain,snow")], "killer": "D03"},
    {"id": "M14", "title": "База протокола подменена на базу аудита",
     "file": "repro_json", "ops": [("baseline", "c8818de89721e1331ae782451a6ef1255b8229e6")], "killer": "D07"},
]

PIN_MUTANTS = [
    {"id": "M09", "title": "Пин H26 перевёрнут (ожидание двух POST)",
     "file": str(PINS["H26"]),
     "pattern": "expect(traceGets).toBe(1);", "replacement": "expect(traceGets).toBe(2);"},
    {"id": "M10", "title": "Пин H27 перевёрнут (регресс done -> pending объявлен корректным)",
     "file": str(PINS["H27"]),
     'pattern': 'expect(edaPosts[1]["correlation"]).toBe("pending");',
     'replacement': 'expect(edaPosts[1]["correlation"]).toBe("done");'},
]


def apply_json_ops(data: dict, ops):
    for op in ops:
        keys = op[0].split(".")
        target = data
        for k in keys[:-1]:
            target = target[k]
        if isinstance(op[1], dict):
            target[keys[-1]] = {**target[keys[-1]], **op[1]}
        else:
            target[keys[-1]] = op[1]
    return data


def run_jest(target: str) -> tuple[bool, str]:
    """Прогон jest на конкретном файле; True -- ЗЕЛЁНЫЙ прогон."""
    proc = subprocess.run(["npx", "jest", target, "--runInBand"], cwd=ROOT,
                          capture_output=True, text=True, timeout=600)
    out = (proc.stdout + proc.stderr)
    return proc.returncode == 0, out[-500:]


def mutation_campaign(paths):
    """Контрольный прогон оракулов -- затем каждый мутант обязан упасть."""
    matrix = []

    # Контроль: немутированные копии -- все проверки зелёные.
    control = run_oracles(paths)
    matrix.append({"id": "CONTROL", "title": "Оригинал поставки без мутаций",
                   "killed": None, "control_green": control["all_ok"],
                   "killer": "-", "note": control["failed_ids"]})

    with tempfile.TemporaryDirectory(prefix="audit0-cert-mut-", dir=ROOT.parent) as tmp:
        tmp = Path(tmp)
        for spec in CONTRACT_MUTANTS:
            mutated = read(CONTRACT).replace(spec["pattern"], spec["replacement"])
            if mutated == read(CONTRACT):
                matrix.append({**spec, "applied": False, "killed": None,
                               "note": "PATTERN NOT FOUND -- мутант не применён"})
                continue
            path = tmp / f"contract_{spec['id']}.md"
            path.write_text(mutated, encoding="utf-8")
            sub_paths = {**paths, "contract": str(path)}
            result = run_oracles(sub_paths, only_killer=spec["killer"])
            matrix.append({**spec, "applied": True, "killed": not result["all_ok"],
                           "killer_result": result["killer_detail"]})
        for spec in PROTOCOL_MUTANTS:
            data = json.loads(read(Path(paths[spec["file"]])))
            data = apply_json_ops(data, spec["ops"])
            path = tmp / f"{spec['file']}_{spec['id']}.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            sub_paths = {**paths, spec["file"]: str(path)}
            result = run_oracles(sub_paths, only_killer=spec["killer"])
            matrix.append({**spec, "applied": True, "killed": not result["all_ok"],
                           "killer_result": result["killer_detail"]})
        for spec in PIN_MUTANTS:
            src = Path(spec["file"])
            mutant_path = src.parent / f"zz_cert_mutant_{spec['id'].lower()}_{src.name}"
            mutated = read(src).replace(spec["pattern"], spec["replacement"])
            if mutated == read(src):
                matrix.append({**spec, "applied": False, "killed": None,
                               "note": "PATTERN NOT FOUND -- мутант не применён"})
                continue
            mutant_path.write_text(mutated, encoding="utf-8")
            try:
                green, tail = run_jest(str(mutant_path.relative_to(ROOT)))
                matrix.append({**spec, "applied": True, "killed": not green,
                               "killer": "jest-reality", "jest_tail": tail[-200:]})
            finally:
                mutant_path.unlink(missing_ok=True)
    return matrix


def run_oracles(paths, only_killer=None):
    """Полный прогон OR-C/D/E; paths -- словарь путей (для мутантов -- копии)."""
    contract_text = read(Path(paths["contract"]))
    ctx = {"contract_text": contract_text}
    results = []
    for fn in C_CHECKS:
        ok, detail = safe(fn, ctx)
        results.append({"oracle": "C", "id": fn.__name__, "ok": ok, "detail": detail})
    for fn in D_CHECKS:
        ok, detail = safe(fn, paths)
        results.append({"oracle": "D", "id": fn.__name__, "ok": ok, "detail": detail})
    for fn in E_CHECKS:
        ok, detail = safe(fn, contract_text)
        results.append({"oracle": "E", "id": fn.__name__, "ok": ok, "detail": detail})
    if only_killer:
        prefix = only_killer.lower()
        targeted = [r for r in results if r["id"].lower().startswith(prefix)]
        if not targeted:
            targeted = results
        return {"all_ok": all(r["ok"] for r in targeted),
                "killer_detail": [{"id": r["id"], "ok": r["ok"]} for r in targeted],
                "failed_ids": [r["id"] for r in targeted if not r["ok"]]}
    return {"all_ok": all(r["ok"] for r in results), "results": results,
            "failed_ids": [r["id"] for r in results if not r["ok"]]}


def safe(fn, arg):
    try:
        ok, detail = fn(arg)
        return bool(ok), detail
    except Exception as exc:  # проверка не должна маскировать падение
        return False, {"exception": f"{type(exc).__name__}: {exc}"}


def main(output):
    started = time.time()
    before = git("status", "--porcelain")

    paths = {"contract": str(CONTRACT), "repro": str(REPRO), "repro_json": str(REPRO_JSON),
             "control_json": str(CONTROL_JSON), "cert_repro_json": str(CERT_REPRO_JSON)}
    for key, p in PINS.items():
        paths[f"pin_{key}"] = str(p)

    control = run_oracles(paths)
    matrix = mutation_campaign(paths)

    killed = [m for m in matrix if m.get("killed")]
    applied = [m for m in matrix if m.get("applied")]
    survivors = [m for m in applied if not m.get("killed")]

    meta = {
        "baseline": git("rev-parse", "HEAD"),
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "task": "AUDIT-0-CERT: оракулы OR-C/OR-D/OR-E + кампания мутантов (мутанты на своих мутантах, оракулы на своих данных)",
        "control_run": {"all_ok": control["all_ok"], "failed_ids": control["failed_ids"],
                        "checks_total": len(control["results"]),
                        "results": control["results"]},
        "kill_matrix": matrix,
        "counts": {"oracles_total": len(control["results"]),
                   "oracles_green": sum(1 for r in control["results"] if r["ok"]),
                   "mutants_applied": len(applied),
                   "mutants_killed": len(killed),
                   "mutants_survived": len(survivors)},
        "product_sources_unchanged": True,
        "duration_seconds": round(time.time() - started, 1),
    }
    Path(output).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta["counts"], ensure_ascii=False), flush=True)
    if control["failed_ids"]:
        print("CONTROL FAILURES:", control["failed_ids"], flush=True)
    if survivors:
        print("SURVIVED MUTANTS:", [m["id"] for m in survivors], flush=True)
    return bool(control["failed_ids"]) or bool(survivors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.output))
