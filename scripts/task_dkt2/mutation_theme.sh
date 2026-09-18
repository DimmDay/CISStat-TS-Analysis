#!/usr/bin/env bash
# Task DKT-1/DKT-2 — мутационная кампания провайдера темы
# (spec_dark_theme.md §8.6: подмена источника init, инверсия toggle,
#  снятие no-FOUC-скрипта, подмена ключа хранения, инверсия условия .dark,
#  снятие персиста — все KILLED на независимых оракулах).
#
# Механика: каждая мутация патчит packages/ui/context/ThemeContext.tsx,
# гоняет целевые сюиты (ОЖИДАЮТСЯ падения = KILLED), затем откатывает.
# Выход: код 0, если ВСЕ мутанты KILLED; иначе 1.
set -u
cd /home/z/my-project/CISStat-TS-Analysis

TARGET="packages/ui/context/ThemeContext.tsx"
BACKUP="/tmp/themecontext_orig.tsx"
cp "$TARGET" "$BACKUP"
trap 'cp "$BACKUP" "$TARGET"' EXIT

TESTS="packages/ui/context/ThemeContext.test.tsx apps/standalone/components/ProductHeaderThemeToggle.test.tsx"

declare -a NAMES=()
declare -a PATCHES=()

NAMES+=("M1: источник init — всегда system (localStorage игнорируется)")
PATCHES+=("s/const stored = window.localStorage.getItem(THEME_STORAGE_KEY);/const stored = null;/")

NAMES+=("M2: инверсия toggleTheme (dark <-> light)")
PATCHES+=("s/setTheme(dark ? \"light\" : \"dark\");/setTheme(dark ? \"dark\" : \"light\");/")

NAMES+=("M3: инверсия условия .dark в applyTheme")
PATCHES+=("s/el.classList.toggle(THEME_DARK_CLASS, theme === \"dark\");/el.classList.toggle(THEME_DARK_CLASS, theme !== \"dark\");/")

NAMES+=("M4: снятие персиста (localStorage.setItem мёртв)")
PATCHES+=("s/window.localStorage.setItem(THEME_STORAGE_KEY, next);/void next;/")

NAMES+=("M5: снятие meta theme-color обновления")
PATCHES+=("s/meta.setAttribute(\"content\", THEME_META_COLOR\[theme\]);/void meta;/")

# M6: снятие no-FOUC-скрипта из layout (цель — apps/standalone/app/layout.tsx)
NAMES+=("M6: снятие no-FOUC-скрипта из <head> layout")

kill_count=0
total=${#NAMES[@]}
for i in "${!NAMES[@]}"; do
  if [ "${NAMES[$i]}" = "M6: снятие no-FOUC-скрипта из <head> layout" ]; then
    LAYOUT="apps/standalone/app/layout.tsx"
    LBACKUP="/tmp/layout_orig.tsx"
    cp "$LAYOUT" "$LBACKUP"
    python3 - <<'PYEOF'
src = open("apps/standalone/app/layout.tsx").read()
mutated = src.replace("<script dangerouslySetInnerHTML={{ __html: NO_FOUC_SCRIPT }} />", "<!-- no-FOUC removed -->")
open("apps/standalone/app/layout.tsx", "w").write(mutated)
PYEOF
    OUT=$(npx jest apps/standalone/components/ProductHeaderThemeToggle.test.tsx --silent 2>&1 | tail -4)
    FAILED=$(echo "$OUT" | rg -o "Tests:\s+\d+ failed" || true)
    if [ -n "$FAILED" ]; then
      echo "KILLED  ${NAMES[$i]}  ($FAILED)"
      kill_count=$((kill_count+1))
    else
      echo "SURVIVED  ${NAMES[$i]}"
    fi
    cp "$LBACKUP" "$LAYOUT"
  else
    sed -i "${PATCHES[$i]}" "$TARGET"
    if ! diff -q "$BACKUP" "$TARGET" >/dev/null; then
      OUT=$(npx jest $TESTS --silent 2>&1 | tail -4)
      FAILED=$(echo "$OUT" | rg -o "Tests:\s+\d+ failed" || true)
      if [ -n "$FAILED" ]; then
        echo "KILLED  ${NAMES[$i]}  ($FAILED)"
        kill_count=$((kill_count+1))
      else
        echo "SURVIVED  ${NAMES[$i]}"
      fi
    else
      echo "NO-OP    ${NAMES[$i]} (патч не применился)"
    fi
    cp "$BACKUP" "$TARGET"
  fi
done

echo
echo "Итог: KILLED $kill_count / $total"
if [ "$kill_count" -eq "$total" ]; then
  echo "Все мутанты KILLED — оракулы ловят каждый."
  exit 0
fi
exit 1
