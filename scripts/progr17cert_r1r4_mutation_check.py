#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-17-CERT-R1R4: верификация закрытия находок R1-R4 мутационными
пробами. Повторяет протокол сертификации (правка -> прогон -> откат),
но на ОБОГАЩЁННОМ сьюте (тесты R1-R3 в TsAnalysisPreprocessing.test.tsx,
тест R4 в test_progress_progr17.py).

Ожидания:
  FM-P/FM-Q/FM-R  -- остаются KILLED (были убиты и до R1-R4);
  FM-S            -- остаётся SURVIVED (маскировка pending-гейтом,
                     вне объёма R1-R4, задокументировано в акте);
  FM-T/FM-U/FM-W/FM-V -- становятся KILLED (закрытие R1/R2/R3);
  BM-H            -- становится KILLED (закрытие R4, тест на fakeredis).

Запуск: python3 /home/z/my-project/scripts/progr17cert_r1r4_mutation_check.py
"""
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
COMPONENT = REPO / "packages/ui/components/TsAnalysisPreprocessing.tsx"
PROGRESS_ROUTER = REPO / "apps/api/routers/progress.py"

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

FE_MUTANTS = [
    ("FM-P", "progressApiUrl -> sessionApiUrl",
     'fetch(progressApiUrl("/preprocessing-checks"), {',
     'fetch(sessionApiUrl("/preprocessing-checks"), {'),
    ("FM-Q", "pending-гейт снят",
     '''      && !checks.some((check) => check.status === "pending")
      ? JSON.stringify(''',
     '''      ? JSON.stringify('''),
    ("FM-R", "running-гейт снят",
     '''      && !checks.some((check) => check.status === "running")
      && !checks.some((check) => check.status === "pending")
      ? JSON.stringify(''',
     '''      && !checks.some((check) => check.status === "pending")
      ? JSON.stringify('''),
    ("FM-S", "activeDataset-гейт снят (вне объёма R1-R4: маскировка)",
     '''  const checksReportSnapshot: string | null =
    activeDataset
      && !checks.some((check) => check.status === "running")''',
     '''  const checksReportSnapshot: string | null =
    true
      && !checks.some((check) => check.status === "running")'''),
    ("FM-T", "res.ok-проверка снята (R1)",
     '''      .then((res) => {
        if (!res.ok) lastReportedChecksRef.current = "";
      })''',
     '''      .then((res) => {
        void res;
      })'''),
    ("FM-U", "дедупликация снята (R2)",
     '''    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    lastReportedChecksRef.current = checksReportSnapshot;''',
     '''    lastReportedChecksRef.current = checksReportSnapshot;'''),
    # FM-V обрабатывается специальной сплайс-мутацией (apply_fm_v):
    # эффекты в компоненте НЕ смежные, конкатенация не применяется.
    ("FM-V", "порядок эффектов инвертирован (R3)", None, None),
    ("FM-W", "маркер не фиксируется до отправки (R2)",
     '''    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    lastReportedChecksRef.current = checksReportSnapshot;
    postChecks(''',
     '''    if (checksReportSnapshot === lastReportedChecksRef.current) return;
    postChecks('''),
]

BM_H = (
    "BM-H", "store.save удалён (R4)",
    '''        record_run_event(session, event)
    store.save(session)
    return PreprocessingChecksReportResponse(''',
    '''        record_run_event(session, event)
    return PreprocessingChecksReportResponse(''',
)


def _restore(path: Path) -> None:
    subprocess.run(["git", "checkout", "--", str(path)], cwd=REPO, check=True)


def run_jest() -> tuple[int, str]:
    proc = subprocess.run(
        ["npx", "jest", "packages/ui/components/TsAnalysisPreprocessing.test.tsx"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests/api/test_progress_progr17.py", "-x", "-q"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    return proc.returncode, proc.stdout + proc.stderr


def apply_and_run(path: Path, old: str, new: str, runner) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return "APPLY-FAIL", []
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    try:
        code, out = runner()
        verdict = "KILLED" if code != 0 else "SURVIVED"
    finally:
        _restore(path)
    failed = [line.strip() for line in out.splitlines() if "✕" in line or "FAILED" in line]
    return verdict, failed[:4]


def apply_fm_v(text: str) -> str:
    """FM-V (R3): порядок эффектов инвертирован (сброс ПОСЛЕ отчёта).

    В компоненте сброс и отчёт НЕ смежные (между ними postChecks и
    checksReportSnapshot), поэтому splice-замена RESET+REPORT не
    применяется (в исходном прогоне сертификации проба уходила в
    APPLY-FAIL). Честная инверсия: сброс вырезается из своей позиции и
    вставляется ПОСЛЕ эффекта отчёта, промежуточный код сохраняется.
    """
    if RESET_EFFECT not in text or REPORT_EFFECT not in text:
        return text  # APPLY-FAIL распознаётся по неизменённому тексту
    reset_at = text.index(RESET_EFFECT)
    report_at = text.index(REPORT_EFFECT)
    if reset_at > report_at:
        return text  # уже инвертировано -- не мутируем повторно
    middle = text[reset_at + len(RESET_EFFECT):report_at]
    old = RESET_EFFECT + middle + REPORT_EFFECT
    # Инверсия ТОЛЬКО порядка двух эффектов: объявления postChecks и
    # checksReportSnapshot (middle) остаются ПЕРЕД обоими эффектами,
    # иначе отчёт-эффект ссылается на переменные до объявления
    # (TS2448/TDZ) -- мутант был бы невалидным (ложный KILLED).
    new = middle + REPORT_EFFECT + RESET_EFFECT
    if old not in text:
        return text
    return text.replace(old, new, 1)


def main() -> int:
    results: list[tuple[str, str, str, list[str]]] = []

    for mid, desc, old, new in FE_MUTANTS:
        if mid == "FM-V":
            # Специальная сплайс-мутация (эффекты не смежные).
            text = COMPONENT.read_text(encoding="utf-8")
            mutated = apply_fm_v(text)
            if mutated == text:
                results.append((mid, desc, "APPLY-FAIL", []))
                print(f"[{mid}] APPLY-FAIL -- {desc}")
                continue
            assert mutated != text
            COMPONENT.write_text(mutated, encoding="utf-8")
            try:
                code, out = run_jest()
                verdict = "KILLED" if code != 0 else "SURVIVED"
            finally:
                _restore(COMPONENT)
            failed = [line.strip() for line in out.splitlines() if "✕" in line]
            results.append((mid, desc, verdict, failed[:4]))
            print(f"[{mid}] {verdict} -- {desc}")
            for line in failed[:4]:
                print(f"      {line}")
            continue
        assert old is not None and new is not None, mid
        verdict, failed = apply_and_run(COMPONENT, old, new, run_jest)
        results.append((mid, desc, verdict, failed))
        print(f"[{mid}] {verdict} -- {desc}")
        for line in failed:
            print(f"      {line}")

    verdict, failed = apply_and_run(PROGRESS_ROUTER, BM_H[2], BM_H[3], run_pytest)
    results.append((BM_H[0], BM_H[1], verdict, failed))
    print(f"[{BM_H[0]}] {verdict} -- {BM_H[1]}")
    for line in failed:
        print(f"      {line}")

    expected = {
        "FM-P": "KILLED", "FM-Q": "KILLED", "FM-R": "KILLED",
        # FM-S: бонус закрытия R3 -- в гонке «профили осели / сессия не
        # гидратирована» activeDataset-гейт становится наблюдаемым
        # (R3-фаза «отчёта нет»), маскировка pending-гейтом снята.
        "FM-S": "KILLED",
        "FM-T": "KILLED", "FM-U": "KILLED", "FM-W": "KILLED",
        "FM-V": "KILLED", "BM-H": "KILLED",
    }
    print("\n===== СВОДКА =====")
    ok = True
    missing = set(expected) - {mid for mid, _, _, _ in results}
    if missing:
        print(f"ПРОПУЩЕНЫ МУТАНТЫ: {sorted(missing)}")
        ok = False
    for mid, desc, verdict, _ in results:
        mark = "OK" if expected.get(mid) == verdict else "ОЖИДАНИЕ НАРУШЕНО"
        if expected.get(mid) != verdict:
            ok = False
        print(f"[{mid}] {verdict} (ожидалось {expected.get(mid)}) {mark} -- {desc}")
    print("\nИТОГ:", "ВСЕ ОЖИДАНИЯ СХОДЯТСЯ" if ok else "ЕСТЬ РАСХОЖДЕНИЯ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
