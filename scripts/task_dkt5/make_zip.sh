#!/usr/bin/env bash
# Task DKT-5 — сборка ZIP в download (только файлы текущей задачи).
set -euo pipefail
REPO=/home/z/my-project/CISStat-TS-Analysis
OUT=/home/z/my-project/download/task_dkt5_footer_10_decisions_prod_smoke.zip
STAGE=$(mktemp -d)

cd "$REPO"
FILES=(
  packages/ui/globals.css
  packages/ui/components/HomeFooter.tsx
  packages/ui/components/HomeFooter.test.tsx
  packages/ui/index.ts
  packages/ui/dark-catalog-contrast.test.ts
  packages/ui/tailwind-preset.test.ts
  packages/ui/dkt5-footer-dark.test.tsx
  packages/ui/dkt5-open-questions.test.ts
  apps/standalone/app/page.tsx
  apps/standalone/app/page.test.tsx
  apps/standalone/app/navigator/page.tsx
  apps/standalone/app/navigator/page.test.tsx
  spec_dark_theme.md
  scripts/task_dkt5/footer_bundle_smoke.mjs
  docs/task_dkt5_prod_dark_home.png
  worklog/worklog7.md
)

for f in "${FILES[@]}"; do
  mkdir -p "$STAGE/$(dirname "$f")"
  cp "$f" "$STAGE/$f"
done

mkdir -p /home/z/my-project/download
rm -f "$OUT"
( cd "$STAGE" && zip -q -r "$OUT" . )
rm -rf "$STAGE"
echo "ZIP: $OUT"
unzip -l "$OUT"
