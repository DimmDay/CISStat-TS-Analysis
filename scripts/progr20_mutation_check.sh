#!/usr/bin/env bash
# ── PROGR-20: протокол мутационных проб ─────────────────────────────
# Урок PROGR-19 (worklog8.md): реализация НЕ закоммичена (AGENTS.md
# запрещает commit/push), git checkout как restore СТИРАЕТ незакоммичен-
# ную реализацию. Единственный корректный restore -- backup-копия с
# контролем побайтовой идентичности после восстановления.
#
# Мутанты (6):
#   M-1  путь candidates переименован          -> строки таблицы + e2e
#   M-2  узел candidates -> "selection"        -> явный ассерт теста
#        (оба узла известны графу -- import-гейт НЕ ловит, только тест)
#   M-3  опечатка event_type в таблице         -> ImportError валидатора
#   M-4  снят dotted-ключ payload candidates   -> payload-тест
#   M-5  снят тип tuning_skipped из реестра    -> ImportError валидатора
#   M-6  добавлен запрещённый step-маршрут     -> тест исключений + счётчик
set -u
cd "$(dirname "$0")/.."

HOOK="apps/api/trace_hook.py"
REGISTRY="apps/api/trace_events.py"
TMPDIR_LOCAL="scripts/progr20_mutation_tmp"
RESULTS="scripts/progr20_mutation_results.txt"

: > "$RESULTS"

backup() {
  rm -rf "$TMPDIR_LOCAL"
  mkdir -p "$TMPDIR_LOCAL"
  cp "$HOOK" "$TMPDIR_LOCAL/trace_hook.py"
  cp "$REGISTRY" "$TMPDIR_LOCAL/trace_events.py"
}

restore() {
  cp "$TMPDIR_LOCAL/trace_hook.py" "$HOOK"
  cp "$TMPDIR_LOCAL/trace_events.py" "$REGISTRY"
}

verify_clean() {
  cmp -s "$HOOK" "$TMPDIR_LOCAL/trace_hook.py" || { echo "FATAL: $HOOK != backup"; exit 2; }
  cmp -s "$REGISTRY" "$TMPDIR_LOCAL/trace_events.py" || { echo "FATAL: $REGISTRY != backup"; exit 2; }
}

expect_killed() {
  label="$1"; shift
  if python -m pytest tests/api/test_progress_trace_hook.py tests/api/test_trace_events.py -q \
      > "$TMPDIR_LOCAL/out.txt" 2>&1; then
    echo "$label: SURVIVED (тесты зелёные -- мутант НЕ убит)" | tee -a "$RESULTS"
    restore; verify_clean
    return 1
  else
    killed=$(grep -cE "^(FAILED|ERROR)" "$TMPDIR_LOCAL/out.txt" || true)
    echo "$label: KILLED (падений: ${killed})" | tee -a "$RESULTS"
    restore; verify_clean
    return 0
  fi
}

backup

# ── M-1: путь candidates переименован (строка перестаёт матчить) ──
perl -pi -e 's#"POST", "/v1/session/modeling/candidates", "modeling",#"POST", "/v1/session/modeling/candidat", "modeling",#' "$HOOK"
expect_killed "M-1 path-rename candidates" || true

# ── M-2: узел candidates -> "selection" (известный узел, ловит только тест) ──
perl -0pi -e 's#"POST", "/v1/session/modeling/candidates", "modeling",\n        "candidate_generation",#"POST", "/v1/session/modeling/candidates", "modeling",\n        "selection",#' "$HOOK"
expect_killed "M-2 node-swap candidates->selection" || true

# ── M-3: опечатка event_type в таблице (реестр такого не знает) ──
perl -pi -e 's#"candidate_generation", "candidates_generated",#"candidate_generation", "candidates_generatedd",#' "$HOOK"
expect_killed "M-3 typo event_type (ImportError)" || true

# ── M-4: снят dotted-ключ payload candidates ──
python - <<'PY'
import re
p = "apps/api/trace_hook.py"
s = open(p, encoding="utf-8").read()
s = s.replace('            "statistics.runnable_candidates",\n', '', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-4 payload dotted-key removed" || true

# ── M-5: снят тип tuning_skipped из реестра STAGE_EVENT_TYPES ──
python - <<'PY'
p = "apps/api/trace_events.py"
s = open(p, encoding="utf-8").read()
s = s.replace('"diagnostics_run", "tuning_skipped",\n', '"diagnostics_run",\n', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-5 registry type removed (ImportError)" || true

# ── M-6: добавлен запрещённый step-маршрут (исключение снято) ──
python - <<'PY'
p = "apps/api/trace_hook.py"
s = open(p, encoding="utf-8").read()
injected = '''    TraceRouteSpec(
        "POST", "/v1/session/modeling/jobs/{job_id}/step", "modeling",
        "tuning", "tuning_job_started", payload_keys=("model_id",),
    ),
'''
anchor = '    TraceRouteSpec(\n        "POST", "/v1/session/modeling/jobs/{job_id}/cancel"'
assert anchor in s, "anchor not found"
s = s.replace(anchor, injected + anchor, 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-6 forbidden step route added" || true

restore
verify_clean
echo "" | tee -a "$RESULTS"
echo "Финальный контроль: диффы пусты, рабочее дерево соответствует реализационной версии." | tee -a "$RESULTS"
python -m pytest tests/api/test_progress_trace_hook.py tests/api/test_trace_events.py -q 2>&1 | tail -1 | tee -a "$RESULTS"
