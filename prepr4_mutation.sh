#!/bin/bash
# Мутационная кампания PREPR-4: инъекция дефекта → прогон целевых тестов → восстановление из бэкапа.
# Использование: bash /home/z/my-project/scripts/prepr4_mutation.sh <id>
set -e
cd /home/z/my-project/CISStat-TS-Analysis
MUTANT="$1"
BK=/home/z/my-project/scripts/prepr4_backup

restore() {
  cp "$BK/TsAnalysisPreprocessing.tsx" packages/ui/components/
  cp "$BK/PreprocessingMissingOverview.tsx" packages/ui/components/
  cp "$BK/TasksHub.tsx" packages/ui/components/
  cp "$BK/TsAnalysisValidation.tsx" packages/ui/components/
}
trap restore EXIT

case "$MUTANT" in
  M1) # Убрать datasetVersion из deps родительского эффекта декомпозиции
    python3 - <<'EOF'
p="packages/ui/components/TsAnalysisPreprocessing.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("}, [activeFeature, decompositionRefreshKey, datasetVersion]);","}, [activeFeature, decompositionRefreshKey]);",1)
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TsAnalysisPreprocessing.test.tsx -t "the blocked decomposition stop refreshes" 2>&1 | tail -4 ;;
  M2a) # Заморозить Обзор пропусков (убрать datasetVersion из суммы)
    python3 - <<'EOF'
p="packages/ui/components/TsAnalysisPreprocessing.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("refreshKey={missingRefreshKey + datasetVersion}","refreshKey={missingRefreshKey}",1)
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TsAnalysisPreprocessing.test.tsx -t "no frozen keys" 2>&1 | tail -4 ;;
  M2b) # Заместить ключ константой 0
    python3 - <<'EOF'
p="packages/ui/components/TsAnalysisPreprocessing.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("refreshKey={missingRefreshKey + datasetVersion}","refreshKey={0}",1)
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TsAnalysisPreprocessing.test.tsx -t "no frozen keys" 2>&1 | tail -4 ;;
  M3) # Удалить refreshKey из deps эффекта MissingOverview
    python3 - <<'EOF'
p="packages/ui/components/PreprocessingMissingOverview.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("  }, [refreshKey]);","  }, []);",1)
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TsAnalysisPreprocessing.test.tsx -t "component contract" 2>&1 | tail -4 ;;
  M4) # Убрать пересинхронизацию из TasksHub
    python3 - <<'EOF'
p="packages/ui/components/TasksHub.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("""  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);
""","")
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TasksHubSessionSync.test.tsx 2>&1 | tail -4 ;;
  M5) # Убрать бамп validationVersion
    python3 - <<'EOF'
p="packages/ui/components/TsAnalysisValidation.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("setValidationVersion((current) => current + 1);","// mutant: bump removed",1)
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TsAnalysisValidation.test.tsx -t "invalidation source" 2>&1 | tail -4 ;;
  M6) # Убрать onRulesApplied={runValidation}
    python3 - <<'EOF'
p="packages/ui/components/TsAnalysisValidation.tsx"; s=open(p,encoding="utf-8").read()
s=s.replace("<RulesManagementPanel onRulesApplied={runValidation} />","<RulesManagementPanel />",1)
open(p,"w",encoding="utf-8").write(s)
EOF
    npx jest packages/ui/components/TsAnalysisValidation.test.tsx -t "onRulesApplied" 2>&1 | tail -4 ;;
  *) echo "Unknown mutant"; exit 1 ;;
esac
restore
echo "=== RESTORED ==="
