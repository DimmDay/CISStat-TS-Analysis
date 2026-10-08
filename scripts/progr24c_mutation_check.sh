#!/usr/bin/env bash
# ── PROGR-24-ORIGIN-C: протокол мутационных проб ────────────────────
# Урок PROGR-19 (worklog8.md): реализация НЕ закоммичена (AGENTS.md
# запрещает commit/push), git checkout как restore СТИРАЕТ незакоммичен-
# ную реализацию. Единственный корректный restore -- backup-копия с
# контролем побайтовой идентичности после восстановления.
#
# Мутанты (6):
#   M-1 путь (а) искажён: STL убран из шаблона   -> пин обоих путей спеки
#   M-2 severity info -> warning                  -> юнит severity + e2e
#   M-3 условие total <= 0 -> total < 0 (ноль
#       срабатывает)                              -> юнит тишины на нуле
#   M-4 слияние совета в ответ next-step снято    -> e2e next-step
#   M-5 факты по ПОЛНОМУ кадру вместо
#       производной области                       -> скоуп-тест facts
#   M-6 context total_outliers захардкожен в 0    -> юнит рендера + e2e
set -u
cd "$(dirname "$0")/.."

ENGINE="app/core/mentor_rules.py"
ROUTER="apps/api/routers/progress.py"
TMPDIR_LOCAL="scripts/progr24c_mutation_tmp"
RESULTS="scripts/progr24c_mutation_results.txt"

: > "$RESULTS"

backup() {
  rm -rf "$TMPDIR_LOCAL"
  mkdir -p "$TMPDIR_LOCAL"
  cp "$ENGINE" "$TMPDIR_LOCAL/mentor_rules.py"
  cp "$ROUTER" "$TMPDIR_LOCAL/progress.py"
}

restore() {
  cp "$TMPDIR_LOCAL/mentor_rules.py" "$ENGINE"
  cp "$TMPDIR_LOCAL/progress.py" "$ROUTER"
}

verify_clean() {
  cmp -s "$ENGINE" "$TMPDIR_LOCAL/mentor_rules.py" || { echo "FATAL: $ENGINE != backup"; exit 2; }
  cmp -s "$ROUTER" "$TMPDIR_LOCAL/progress.py" || { echo "FATAL: $ROUTER != backup"; exit 2; }
}

expect_killed() {
  label="$1"; shift
  if python3 -m pytest tests/api/test_mentor_rules.py -q \
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

# ── M-1: путь (а) спеки искажён -- STL убран из шаблона ──
python3 - <<'PY'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
target = "обнаружение на остатке STL-декомпозиции доступно в "
assert target in s, "M-1 anchor not found"
s = s.replace(target, "обнаружение на остатке декомпозиции доступно в ", 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-1 path-A text distorted (STL removed)" || true

# ── M-2: severity info -> warning (совет превратился в тревогу) ──
python3 - <<'PY'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
target = '    return MentorRuleFact(\n        context={"total_outliers": total},\n        severity=SEVERITY_INFO,'
assert target in s, "M-2 anchor not found"
s = s.replace(target, '    return MentorRuleFact(\n        context={"total_outliers": total},\n        severity=SEVERITY_WARNING,', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-2 severity info->warning" || true

# ── M-3: ноль срабатывает (total <= 0 -> total < 0) ──
python3 - <<'PY'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
target = "or not isinstance(total, int) or total <= 0:"
assert target in s, "M-3 anchor not found"
s = s.replace(target, "or not isinstance(total, int) or total < 0:", 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-3 fires on zero (<=0 -> <0)" || true

# ── M-4: слияние совета в ответ next-step снято (роутер) ──
python3 - <<'PY'
p = "apps/api/routers/progress.py"
s = open(p, encoding="utf-8").read()
target = "        *evaluate_session_advice(_derived_spikes_facts(run)),\n"
assert target in s, "M-4 anchor not found"
s = s.replace(target, "", 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-4 router merge removed" || true

# ── M-5: факты по ПОЛНОМУ кадру вместо производной области (скоуп) ──
python3 - <<'PY'
p = "apps/api/routers/progress.py"
s = open(p, encoding="utf-8").read()
target = 'scope_frame(session.dataframe, derived_names), method="iqr", param=None'
assert target in s, "M-5 anchor not found"
s = s.replace(target, 'session.dataframe, method="iqr", param=None', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-5 facts over full frame (scope lost)" || true

# ── M-6: context total_outliers захардкожен в 0 (совет врёт в числе) ──
python3 - <<'PY'
p = "app/core/mentor_rules.py"
s = open(p, encoding="utf-8").read()
target = 'context={"total_outliers": total},'
assert target in s, "M-6 anchor not found"
s = s.replace(target, 'context={"total_outliers": 0},', 1)
open(p, "w", encoding="utf-8").write(s)
PY
expect_killed "M-6 context count hardcoded 0" || true

restore
verify_clean
echo "" | tee -a "$RESULTS"
echo "Финальный контроль: диффы пусты, рабочее дерево соответствует реализационной версии." | tee -a "$RESULTS"
python3 -m pytest tests/api/test_mentor_rules.py -q 2>&1 | tail -1 | tee -a "$RESULTS"
