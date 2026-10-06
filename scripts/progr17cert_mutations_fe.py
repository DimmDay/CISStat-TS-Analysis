#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-17-CERT: мутационное тестирование фронтенда СВОИМИ мутантами.

Протокол: правка -> jest TsAnalysisPreprocessing.test.tsx -> git checkout.
KILLED -- хотя бы один тест упал; SURVIVED -- все зелёные.
Запуск: python3 /home/z/my-project/scripts/progr17_cert_mutations_fe.py
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
COMPONENT = "packages/ui/components/TsAnalysisPreprocessing.tsx"

RESET_EFFECT = """  useEffect(() => {
    lastReportedChecksRef.current = "";
  }, [activeDataset?.name]);
"""

REPORT_EFFECT = """  useEffect(() => {
    if (!checksReportSnapshot) return;
    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    lastReportedChecksRef.current = checksReportSnapshot;
    postChecks(JSON.parse(checksReportSnapshot) as Record<string, CheckStatus>);
  }, [checksReportSnapshot, postChecks]);
"""

MUTANTS = [
    ("FM-P", "progressApiUrl -> sessionApiUrl (двойной префикс)",
     'fetch(progressApiUrl("/preprocessing-checks"), {',
     'fetch(sessionApiUrl("/preprocessing-checks"), {'),

    ("FM-Q", "pending-гейт снят (ранний транзитный POST)",
     '''      && !checks.some((check) => check.status === "pending")
      ? JSON.stringify(''',
     '''      ? JSON.stringify('''),

    ("FM-R", "running-гейт снят (транзит авто-перезапросов)",
     '''      && !checks.some((check) => check.status === "running")
      && !checks.some((check) => check.status === "pending")
      ? JSON.stringify(''',
     '''      && !checks.some((check) => check.status === "pending")
      ? JSON.stringify('''),

    ("FM-S", "activeDataset-гейт снят (зеркало 400-гейта; гипотеза: НЕ ловится)",
     '''  const checksReportSnapshot: string | null =
    activeDataset
      && !checks.some((check) => check.status === "running")''',
     '''  const checksReportSnapshot: string | null =
    true
      && !checks.some((check) => check.status === "running")'''),

    ("FM-T", "res.ok-проверка снята (нет сброса маркера при !ok)",
     '''      .then((res) => {
        if (!res.ok) lastReportedChecksRef.current = "";
      })''',
     '''      .then((res) => {
        void res;
      })'''),

    ("FM-U", "дедупликация снята (повтор POST на каждом прогоне эффекта)",
     '''    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    lastReportedChecksRef.current = checksReportSnapshot;''',
     '''    lastReportedChecksRef.current = checksReportSnapshot;'''),

    ("FM-V", "порядок эффектов инвертирован (сброс ПОСЛЕ отчёта)",
     RESET_EFFECT + REPORT_EFFECT,
     REPORT_EFFECT + RESET_EFFECT),

    ("FM-W", "маркер не фиксируется до отправки (дедупликация слепа)",
     '''    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    lastReportedChecksRef.current = checksReportSnapshot;
    postChecks(''',
     '''    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    postChecks('''),
]


def run_jest() -> tuple[int, str]:
    proc = subprocess.run(
        ["npx", "jest", "packages/ui/components/TsAnalysisPreprocessing.test.tsx"],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    assert dirty == "", "рабочее дерево грязное -- нужна чистая база"

    path = REPO / COMPONENT
    results = []
    for mid, desc, old, new in MUTANTS:
        text = path.read_text(encoding="utf-8")
        if old not in text:
            results.append((mid, desc, "APPLY-FAIL"))
            print(f"[{mid}] APPLY-FAIL -- {desc}")
            continue
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            code, out = run_jest()
            verdict = "KILLED" if code != 0 else "SURVIVED"
        finally:
            subprocess.run(["git", "checkout", "--", COMPONENT], cwd=REPO, check=True)
        results.append((mid, desc, verdict))
        print(f"[{mid}] {verdict} -- {desc}")
        if verdict == "KILLED":
            for line in out.splitlines():
                if "✕" in line or "Tests:" in line:
                    print(f"      {line.strip()}")

    killed = sum(1 for _, _, v in results if v == "KILLED")
    surv = [m for m, _, v in results if v == "SURVIVED"]
    print("\n===== СВОДКА =====")
    print(f"Всего мутантов: {len(results)}  KILLED: {killed}  SURVIVED: {len(surv)}  {surv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
