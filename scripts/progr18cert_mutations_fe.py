#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-18-CERT: мутационное тестирование фронтенда СВОИМИ мутантами.

Протокол: правка TsAnalysisEDA.tsx -> jest TsAnalysisEDA.test.tsx ->
git checkout. KILLED -- хотя бы один тест упал; SURVIVED -- все зелёные.
Список НЕ копирует M-4..M-6 тимлида (URL через sessionApiUrl, снятие
seed-якоря, ослабление критерия до «открыл») и FM-P..FM-W cert17 --
независимый набор под контур eda-checks (snapshot-инверсия, seed-фильтр,
сброс при !ok, сброс вселенной при смене датасета, дедуп против якоря,
credentials-контракт, activeDataset-гейт).

Запуск: python3 scripts/progr18cert_mutations_fe.py
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
COMPONENT = "packages/ui/components/TsAnalysisEDA.tsx"
TEST_SPEC = "TsAnalysisEDA.test.tsx"

MUTANTS = [
    ("FM-A", "снапшот инвертирован: !viewed.has -> viewed-done <-> pending "
     "поменяны местами (в журнал уходит ANTISNAPSHOT)",
     '''      Object.fromEntries(
        CHECKS.map((check) => [check.id, viewed.has(check.id) ? "done" : "pending"]),
      ),''',
     '''      Object.fromEntries(
        CHECKS.map((check) => [check.id, !viewed.has(check.id) ? "done" : "pending"]),
      ),'''),

    ("FM-B", "критерий просмотра ослаблен до «любой непустой статус» "
     "(running/error/skipped считают просмотренными)",
     '''    if (activeStatus !== "done" && activeStatus !== "warning") return;''',
     '''    if (!activeStatus) return;'''),

    ("FM-C", "seed-фильтр ослаблен: в просмотренные засеивается всё, кроме "
     "pending (warning/error узлы /trace стали бы «просмотренными»)",
     '''              if (status === "done" && knownIds.has(nodeId)) seedViewed.add(nodeId);''',
     '''              if (status !== "pending" && knownIds.has(nodeId)) seedViewed.add(nodeId);'''),

    ("FM-D", "сброс маркера при !ok снят (гипотеза: ВыЖИВАЕТ -- повтор в "
     "существующем тесте происходит по ИЗМЕНЕНИЮ снапшота, не по сбросу)",
     '''      .then((res) => {
        if (!res.ok) lastReportedEdaChecksRef.current = "";
      })''',
     '''      .then((res) => {
        void res;
      })'''),

    ("FM-E", "сброс вселенной при смене датасета удалён (старые просмотры "
     "протекают в новую вселенную фактов; seed сливается с чужим множеством)",
     '''  useEffect(() => {
    edaSeedReadyRef.current = false;
    setEdaViewedIds(new Set());
    setEdaSeedReady(false);
    lastReportedEdaChecksRef.current = "";
  }, [datasetKey]);''',
     '''  useEffect(() => {
  }, [datasetKey]);'''),

    ("FM-F", "дедупликация против seed-якоря снята (после перемонтирования "
     "без новых просмотров отчёт Уходит повторно -- seed-снапшот != пустой "
     "маркер)",
     '''    if (!edaChecksReportSnapshot) return;
    if (edaChecksReportSnapshot === lastReportedEdaChecksRef.current) return;
    lastReportedEdaChecksRef.current = edaChecksReportSnapshot;''',
     '''    if (!edaChecksReportSnapshot) return;
    lastReportedEdaChecksRef.current = edaChecksReportSnapshot;'''),

    ("FM-G", "credentials: \"include\" удалён из POST (контракт сессии)",
     '''      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ checks: reported }),''',
     '''      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ checks: reported }),'''),

    ("FM-H", "activeDataset-гейт снят из снапшота (гипотеза: ВыЖИВАЕТ -- "
     "size>0 вторично страхует пустую вселенную)",
     '''  const edaChecksReportSnapshot: string | null =
    activeDataset && edaSeedReady && edaViewedIds.size > 0
      ? buildEdaChecksSnapshot(edaViewedIds)
      : null;''',
     '''  const edaChecksReportSnapshot: string | null =
    edaSeedReady && edaViewedIds.size > 0
      ? buildEdaChecksSnapshot(edaViewedIds)
      : null;'''),
]


def run_jest() -> tuple[int, str]:
    cmd = ["npx", "jest", TEST_SPEC]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout + proc.stderr


def apply_mutant(fragment_old: str, fragment_new: str) -> bool:
    path = REPO / COMPONENT
    text = path.read_text(encoding="utf-8")
    if fragment_old not in text:
        return False
    path.write_text(text.replace(fragment_old, fragment_new, 1), encoding="utf-8")
    return True


def restore() -> None:
    subprocess.run(["git", "checkout", "--", COMPONENT], cwd=REPO, check=True)


def main() -> int:
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        allowed = {
            "scripts/progr18cert_oracles.py",
            "scripts/progr18cert_mutations.py",
            "scripts/progr18cert_mutations_fe.py",
            "scripts/progr18cert_mutation_results.txt",
        }
        unexpected = [
            line for line in dirty.splitlines()
            if line.split()[-1] not in allowed
        ]
        assert not unexpected, f"рабочее дерево грязное: {unexpected}"

    results = []
    for mid, desc, old, new in MUTANTS:
        ok = apply_mutant(old, new)
        if not ok:
            results.append((mid, desc, "APPLY-FAIL", ""))
            print(f"[{mid}] APPLY-FAIL: якорь не найден")
            continue
        try:
            code, out = run_jest()
            verdict = "KILLED" if code != 0 else "SURVIVED"
            tail = [line for line in out.splitlines() if line.strip()][-6:]
            reason = " | ".join(t.strip() for t in tail)[:300]
        finally:
            restore()
        results.append((mid, desc, verdict, reason))
        print(f"[{mid}] {verdict} -- {desc}")

    killed = sum(1 for _, _, v, _ in results if v == "KILLED")
    survived = [m for m, _, v, _ in results if v == "SURVIVED"]
    lines = []
    lines.append("PROGR-18-CERT: протокол мутационного тестирования фронтенда (свои мутанты)")
    lines.append(f"Компонент: {COMPONENT}; канал: jest {TEST_SPEC}")
    lines.append("")
    for mid, desc, verdict, reason in results:
        lines.append(f"[{mid}] {verdict} -- {desc}")
        if reason and verdict == "KILLED":
            lines.append(f"    {reason}")
    lines.append("")
    lines.append(f"===== СВОДКА: всего {len(results)} | KILLED {killed} | SURVIVED {len(survived)} {survived} =====")
    out_path = REPO / "scripts" / "progr18cert_fe_mutation_results.txt"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nпротокол: {out_path}")
    print(lines[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
