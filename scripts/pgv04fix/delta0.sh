#!/usr/bin/env bash
# scripts/pgv04fix/delta0.sh -- дельта-0 полного tests/api (прецедент
# акта PGV-04-CERT §9): родитель ad597cb (без фикса, git stash) vs
# родитель+фикс (текущее дерево). Одна среда, кэш pytest отключён
# (урок DOCLOG-8). Сравнение -- по строкам FAILED ID.
set -u
cd "$(dirname "$0")/../.." || exit 1
OUT=scripts/pgv04fix/protocols
mkdir -p "$OUT"

extract_failed() {
  # FAILED ID: "FAILED tests/api/...::Class::test" (без хвоста - ...)
  rg -o 'FAILED \S+::\S+' -r '$0' "$1" | sort > "$2"
  rg -o '^==== \d+ failed.*$' "$1" | tail -1 >> "$2.summary" || true
}

echo "[1/4] Полный прогон: РОДИТЕЛЬ+ФИКС (текущее дерево)"
python3 -m pytest tests/api -q --tb=no -p no:cacheprovider > "$OUT/full_fix.txt" 2>&1
tail -1 "$OUT/full_fix.txt"
extract_failed "$OUT/full_fix.txt" "$OUT/failed_fix.txt"

echo "[2/4] Прогон: РОДИТЕЛЬ (ad597cb, git stash)"
git stash push -m "pgv04fix-delta0" >/dev/null || { echo "stash failed"; exit 1; }
STASHED=1
python3 -m pytest tests/api -q --tb=no -p no:cacheprovider > "$OUT/full_parent.txt" 2>&1
tail -1 "$OUT/full_parent.txt"
extract_failed "$OUT/full_parent.txt" "$OUT/failed_parent.txt"
git stash pop >/dev/null && STASHED=0
echo "[3/4] stash восстановлен: $((1-STASHED))"

echo "[4/4] Сравнение FAILED-ID"
diff_target_only=$(comm -23 "$OUT/failed_fix.txt" "$OUT/failed_parent.txt" | wc -l)
diff_parent_only=$(comm -13 "$OUT/failed_fix.txt" "$OUT/failed_parent.txt" | wc -l)
echo "diff_target_only (новые FAILED на стороне фикса): $diff_target_only"
[ "$diff_target_only" -gt 0 ] && comm -23 "$OUT/failed_fix.txt" "$OUT/failed_parent.txt"
echo "diff_parent_only (потери родительской стороны): $diff_parent_only"
[ "$diff_parent_only" -gt 0 ] && comm -13 "$OUT/failed_fix.txt" "$OUT/failed_parent.txt"
if [ "$diff_target_only" -eq 0 ] && [ "$diff_parent_only" -eq 0 ]; then
  echo "DELTA-0 OK: FAILED-ID идентичны на обеих сторонах"
  exit 0
fi
exit 1
