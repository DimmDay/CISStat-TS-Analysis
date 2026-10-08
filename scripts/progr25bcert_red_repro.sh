#!/usr/bin/env bash
# RED-воспроизведение сертификации PROGR-25-B-CERT.
#
# Продовые файлы задачи B откатываются к состоянию ДО задачи (13c693c --
# коммит PROGR-25-A), прогоняются ТОЛЬКО свои оракулы аудитора
# (progr25bcert*). Ожидание: поведенческие падения по контрактам B --
# доказательство, что оракулы ловят отсутствие задачи B. Затем
# восстановление d703407 побайтово (md5-контроль, урок PROGR-19).
#
# Бэкапы -- /home/z/my-project/scripts/certb_backup (вне репозитория).
set -u
cd "$(dirname "$0")/.."
OUT="scripts/progr25bcert_red_repro.txt"
BK=/home/z/my-project/scripts/certb_backup
mkdir -p "$BK"

FILES="packages/ui/hooks/useTargetColumn.ts packages/ui/components/ProgressDrawer.tsx packages/ui/lib/modeling.ts packages/ui/components/TsAnalysisUpload.tsx"

md5all() { md5sum $FILES | md5sum; }
BASE=$(md5all)
echo "База md5 (4 продовых файла): $BASE" | tee "$OUT"

echo "" | tee -a "$OUT"
echo "=== Шаг 1. Бэкап d703407 ===" | tee -a "$OUT"
for f in $FILES; do
  cp "$f" "$BK/$(basename "$f")"
done
md5sum $FILES | tee -a "$OUT"

echo "" | tee -a "$OUT"
echo "=== Шаг 2. Откат к 13c693c (до задачи B) ===" | tee -a "$OUT"
git checkout 13c693c -- $FILES
md5sum $FILES | tee -a "$OUT"

echo "" | tee -a "$OUT"
echo "=== Шаг 3. Прогон СВОИХ оракулов на дo-B коде (ожидание: RED) ===" | tee -a "$OUT"
npx jest progr25bcert --verbose 2>&1 | rg "✓|✕|Tests:|Test Suites:" | tee -a "$OUT"

echo "" | tee -a "$OUT"
echo "=== Шаг 4. Восстановление d703407 ===" | tee -a "$OUT"
for f in $FILES; do
  cp "$BK/$(basename "$f")" "$f"
done
RESTORED=$(md5all)
echo "md5 после восстановления: $RESTORED" | tee -a "$OUT"
if [ "$BASE" == "$RESTORED" ]; then
  echo "RESTORE OK: побайтовое совпадение" | tee -a "$OUT"
else
  echo "RESTORE MISMATCH -- КРИТИЧНО" | tee -a "$OUT"
  exit 1
fi
rm -rf "$BK"

echo "" | tee -a "$OUT"
echo "=== Шаг 5. Контроль: свои оракулы на d703407 (ожидание: GREEN 25/25) ===" | tee -a "$OUT"
npx jest progr25bcert 2>&1 | rg "Tests:|Test Suites:" | tee -a "$OUT"
