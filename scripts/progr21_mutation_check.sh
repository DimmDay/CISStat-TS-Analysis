#!/usr/bin/env bash
# ── PROGR-21: протокол мутационных проб ─────────────────────────────
# Урок PROGR-19 (worklog8.md): реализация НЕ закоммичена (AGENTS.md
# запрещает commit/push), git checkout как restore СТИРАЕТ незакоммичен-
# ную реализацию. Единственный корректный restore -- backup-копия с
# контролем побайтовой идентичности после восстановления.
#
# Мутанты (6) -- цель app/core/node_status.py (единственная кодовая
# точка PROGR-21):
#   M-1  текст «включена вручную» искажён   -> точный текст примера v1.1
#   M-2  снятие auto-reason отключено       -> тест снятия + e2e
#   M-3  auto атрибутируется как reason     -> тест «авто-узлы без reason»
#        (шум полного карта-ответа -- канал обесценен)
#   M-4  носитель target-reason подменён    -> явный ассерт узла
#        (formats тоже известен графу -- import-гейт НЕ ловит)
#   M-5  mode_changed добавлен в EVENT_NODE_STATUS («не status» нарушено)
#                                            -> инвариант карты reason
#   M-6  внутренний тег утёк в выход §3     -> тест «ровно 7 полей»
set -u
cd "$(dirname "$0")/.."

ENGINE="app/core/node_status.py"
TMPDIR_LOCAL="scripts/progr21_mutation_tmp"
RESULTS="scripts/progr21_mutation_results.txt"

: > "$RESULTS"

backup() {
  rm -rf "$TMPDIR_LOCAL"
  mkdir -p "$TMPDIR_LOCAL"
  cp "$ENGINE" "$TMPDIR_LOCAL/node_status.py"
}

restore() {
  cp "$TMPDIR_LOCAL/node_status.py" "$ENGINE"
}

verify_clean() {
  cmp -s "$ENGINE" "$TMPDIR_LOCAL/node_status.py" || { echo "FATAL: $ENGINE != backup"; exit 2; }
}

expect_killed() {
  label="$1"; shift
  if python -m pytest tests/api/test_node_status_engine.py tests/api/test_progress_trace_hook.py -q \
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

# ── M-1: текст примера v1.1 искажён ──
python - <<'PY'
p = "app/core/node_status.py"
s = open(p, encoding="utf-8").read()
assert '"enabled": "включена вручную",' in s
s = s.replace('"enabled": "включена вручную",', '"enabled": "вручную",', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-1 mode reason text distorted" || true

# ── M-2: снятие устаревшего mode-reason отключено ──
python - <<'PY'
p = "app/core/node_status.py"
s = open(p, encoding="utf-8").read()
assert 'resets.add(node_id)' in s
s = s.replace('resets.add(node_id)', 'pass  # mutated: no reset', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-2 auto-reason clearing disabled" || true

# ── M-3: auto стало текстом (шум полного карта-ответа PUT) ──
python - <<'PY'
p = "app/core/node_status.py"
s = open(p, encoding="utf-8").read()
anchor = 'NODE_MODE_REASON_LABELS: dict[str, str] = {\n    "enabled": "включена вручную",'
assert anchor in s
s = s.replace(anchor, 'NODE_MODE_REASON_LABELS: dict[str, str] = {\n    "auto": "авто",\n    "enabled": "включена вручную",', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-3 auto attributed as reason (noise)" || true

# ── M-4: носитель target-reason подменён на другой известный узел ──
python - <<'PY'
p = "app/core/node_status.py"
s = open(p, encoding="utf-8").read()
assert 'TARGET_REASON_STAGE_NODE: tuple[str, str] = ("validation", "sufficiency")' in s
s = s.replace(
    'TARGET_REASON_STAGE_NODE: tuple[str, str] = ("validation", "sufficiency")',
    'TARGET_REASON_STAGE_NODE: tuple[str, str] = ("validation", "formats")', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-4 target carrier swapped to formats" || true

# ── M-5: mode_changed добавлен в карту статусов («не status» нарушено) ──
python - <<'PY'
p = "app/core/node_status.py"
s = open(p, encoding="utf-8").read()
anchor = '    "profile_viewed": "running",\n'
assert anchor in s
s = s.replace(anchor, anchor + '    "mode_changed": "done",\n', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-5 mode_changed colored status (invariant)" || true

# ── M-6: внутренний тег происхождения утёк в выход §3 ──
python - <<'PY'
p = "app/core/node_status.py"
s = open(p, encoding="utf-8").read()
anchor = '                    "summary_count": detail["summary_count"],\n                }\n            )'
assert anchor in s
s = s.replace(anchor, '                    "summary_count": detail["summary_count"],\n                    "_reason_tag": detail["_reason_tag"],\n                }\n            )', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-6 reason tag leaked to output" || true

restore
verify_clean
echo "" | tee -a "$RESULTS"
echo "Финальный контроль: диффы пусты, рабочее дерево соответствует реализационной версии." | tee -a "$RESULTS"
python -m pytest tests/api/test_node_status_engine.py tests/api/test_progress_trace_hook.py -q 2>&1 | tail -1 | tee -a "$RESULTS"
