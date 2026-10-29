#!/usr/bin/env bash
# scripts/pgv06fix/delta0.sh -- дельта-0 полного tests/api (прецедент
# scripts/pgv04fix/delta0.sh и акта PGV-06-CERT): родитель 3d04f88
# (git stash) vs родитель+фикс (текущее дерево). Одна среда, кэш
# pytest отключён (урок DOCLOG-8). Критерий PGV-06-FIX:
#   fix-only FAILED    = пусто (фикс не ломает ничего);
#   parent-only FAILED = ровно {B1 F-P6C1} (RED-свидетельство,
#                        ставшее GREEN после фикса).
set -u
cd "$(dirname "$0")/../.." || exit 1
OUT=scripts/pgv06fix/protocols
mkdir -p "$OUT"

extract_failed() {
  rg -o 'FAILED \S+::\S+' -r '$0' "$1" | sort > "$2"
}

echo "[1/4] Полный прогон: РОДИТЕЛЬ+ФИКС (текущее дерево)"
date -u +"start_fix: %Y-%m-%dT%H:%M:%SZ"
python3 -m pytest tests/api -q --tb=no -p no:cacheprovider > "$OUT/full_fix.txt" 2>&1
tail -1 "$OUT/full_fix.txt"
extract_failed "$OUT/full_fix.txt" "$OUT/failed_fix.txt"
date -u +"end_fix: %Y-%m-%dT%H:%M:%SZ"

echo "[2/4] Прогон: РОДИТЕЛЬ (3d04f88, git stash)"
git stash push -m "pgv06fix-delta0" >/dev/null || { echo "stash failed"; exit 1; }
STASHED=1
date -u +"start_parent: %Y-%m-%dT%H:%M:%SZ"
python3 -m pytest tests/api -q --tb=no -p no:cacheprovider > "$OUT/full_parent.txt" 2>&1
tail -1 "$OUT/full_parent.txt"
extract_failed "$OUT/full_parent.txt" "$OUT/failed_parent.txt"
date -u +"end_parent: %Y-%m-%dT%H:%M:%SZ"
git stash pop >/dev/null && STASHED=0
echo "[3/4] stash восстановлен: $((1-STASHED))"

echo "[4/4] Сравнение FAILED-ID"
comm -23 "$OUT/failed_fix.txt" "$OUT/failed_parent.txt" > "$OUT/diff_fix_only.txt"
comm -13 "$OUT/failed_fix.txt" "$OUT/failed_parent.txt" > "$OUT/diff_parent_only.txt"
echo "-- fix-only (новые FAILED на стороне фикса): $(wc -l < "$OUT/diff_fix_only.txt")"
cat "$OUT/diff_fix_only.txt"
echo "-- parent-only (исчезли на стороне фикса): $(wc -l < "$OUT/diff_parent_only.txt")"
cat "$OUT/diff_parent_only.txt"
