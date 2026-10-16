#!/usr/bin/env bash
# RED-воспроизведение сертификации DATASET-VIEW-EDITOR-1-CERT.
# Откат продовых файлов задачи к базам c6823e3 (до задачи 1) и 1c9eb29
# (до задачи 2 -- дефект-репорт), прогон СВОИХ оракулов -- ожидаем RED.
# Восстановление побайтовое, md5-контроль (урок PROGR-19).
#
# Примечание: шаг 2 выполняется вручную (см. протокол) -- файл
# DatasetViewEditor.tsx в c6823e3 отсутствует (новый в задаче 1),
# git show по нему невозможен; корректный откат = удаление файла.
set -u
cd "$(dirname "$0")/.."

FILES_T2="apps/api/schemas.py apps/api/column_origin.py apps/api/routers/session.py packages/ui/components/DatasetViewEditor.tsx"
FILES_T1="apps/api/schemas.py apps/api/column_origin.py apps/api/routers/session.py packages/ui/components/DatasetViewEditor.tsx packages/ui/components/TsAnalysisPreprocessing.tsx packages/ui/components/TsAnalysisValidation.tsx"
OUT="scripts/dvecert_red_repro.txt"

md5() { md5sum "$1" | cut -d' ' -f1; }

declare -A BACKUP
for f in $FILES_T1; do BACKUP[$f]=$(md5 "$f"); done

restore() {
  local ok=0
  for f in $FILES_T1; do
    git show "68fd65d:$f" > "$f"
    if [ "$(md5 "$f")" != "${BACKUP[$f]}" ]; then echo "RESTORE MISMATCH: $f"; ok=1; fi
  done
  [ $ok -eq 0 ] && echo "Восстановление 68fd65d побайтовое (md5 сошёлся)"
  return $ok
}
trap restore EXIT

{
echo "RED-воспроизведение DATASET-VIEW-EDITOR-1-CERT (свои оракулы на коде ДО задач)"
echo "=================================================================="
echo
echo "── Шаг 1: откат к 1c9eb29 (до дефект-репорта: нет POST /delete и кнопки «Сохранить»)"
for f in $FILES_T2; do git show "1c9eb29:$f" > "$f"; done
echo "[бэкенд-оракулы]"
/home/z/.venv/bin/python scripts/dvecert_backend_oracles.py 2>/dev/null | grep -E "^\[|ИТОГО" | sed 's/^/  /'
echo "[фронт-оракулы]"
npx jest --silent packages/ui/components/dvecert_DatasetViewEditor.test.tsx packages/ui/components/dvecert_toggle_oracles.test.tsx 2>&1 | grep -E "Tests:" | sed 's/^/  /'
echo
echo "── Шаг 2: откат к c6823e3 выполняется вручную (DatasetViewEditor.tsx -- НОВЫЙ файл задачи 1;"
echo "   в c6823e3 отсутствует -- корректный откат = удаление файла; см. протокол dvecert_red_repro.txt)"
} > "$OUT" 2>&1

cat "$OUT"
