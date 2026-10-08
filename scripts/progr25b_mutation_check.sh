#!/usr/bin/env bash
# Мутационные пробы PROGR-25-B (выборочные; полная матрица М1-М5 -- задача D
# по plan_progress_target_column.md §4). Каждый мутант обязан погибать своим
# оракулом. Restore -- backup-копиями с побайтовым cmp (урок PROGR-19).
set -u
cd "$(dirname "$0")/.."

HOOK="packages/ui/hooks/useTargetColumn.ts"
DRAWER="packages/ui/components/ProgressDrawer.tsx"
PY=/home/z/.venv/bin/python3

restore() {
  cp "$1.bak" "$1"
  cmp -s "$1.bak" "$1" || { echo "RESTORE MISMATCH: $1"; exit 1; }
  rm "$1.bak"
}

echo "=== МУТАНТ M-B1: возврат тихого авто-POST в хук (мутант R1) ==="
cp "$HOOK" "$HOOK.bak"
$PY - <<'EOF'
from pathlib import Path
p = Path("packages/ui/hooks/useTargetColumn.ts")
s = p.read_text(encoding="utf-8")
# Возврат авто-POST: после applyResponse при target null + suggested -- POST.
old = """      applyResponse(data);

      // Уведомление о сбросе теперь живёт в общем пути фетча (раньше --
      // в ветке авто-ПОСТА): "ранее непустой target стал null". newColumn
      // -- РЕКОМЕНДАЦИЯ (не фиксация!); потребитель строит честный текст.
      if (isReset && previousColumn) {
        setColumnResetNotice({ previousColumn, newColumn: data.suggested_column });
      }"""
new = """      applyResponse(data);
      if (data.target_column === null && data.suggested_column !== null) {
        const postRes = await fetch(sessionApiUrl("/target-column"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ column: data.suggested_column }),
        });
        if (postRes.ok) { applyResponse(await postRes.json()); return; }
      }
      if (isReset && previousColumn) {
        setColumnResetNotice({ previousColumn, newColumn: data.suggested_column });
      }"""
assert old in s, "hook pattern not found"
p.write_text(s.replace(old, new), encoding="utf-8")
EOF
npx jest packages/ui/hooks/useTargetColumn.test.tsx packages/ui/components/TsAnalysisUpload.test.tsx 2>&1 | tail -4 | head -2
restore "$HOOK"

echo ""
echo "=== МУТАНТ M-B2: шапка игнорирует /trace (всегда контекст) ==="
cp "$DRAWER" "$DRAWER.bak"
$PY - <<'EOF'
from pathlib import Path
p = Path("packages/ui/components/ProgressDrawer.tsx")
s = p.read_text(encoding="utf-8")
old = 'if (trace.targetColumn === undefined) {'
new = 'if (true) { // МУТАНТ: контекст всегда'
assert old in s, "drawer pattern not found"
p.write_text(s.replace(old, new, 1), encoding="utf-8")
EOF
npx jest packages/ui/components/ProgressDrawer.test.tsx 2>&1 | tail -4 | head -2
restore "$DRAWER"

echo ""
echo "=== Финальный контроль: чистое дерево ==="
md5sum "$HOOK" "$DRAWER"
cmp -s "$HOOK" "$HOOK" && echo "OK"
npx jest packages/ui/hooks/useTargetColumn.test.tsx packages/ui/components/ProgressDrawer.test.tsx packages/ui/components/TsAnalysisUpload.test.tsx 2>&1 | tail -4 | head -2
