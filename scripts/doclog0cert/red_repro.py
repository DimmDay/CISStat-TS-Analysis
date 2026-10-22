# scripts/doclog0cert/red_repro.py
"""DOCLOG-0-CERT: воспроизведение RED на родителе cc5c14e (git-worktree).

Композиция RED:
  (1) статические факты -- все артефакты задачи отсутствуют на родителе;
  (2) оракулы сертификатора на родителе: unit-сюит -- collection error
      (identity.py не существует), API-сюит -- F08 живьём (чужая сессия
      читает запуск по знанию run_id).

Дерево рабочей копии не трогается: worktree создаётся/удаляется
автоматически, cleanup подтверждается.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT = "cc5c14e"
WORKTREE = REPO_ROOT.parent / "cisstat-doclog0cert-red-wt"
PYTHON = sys.executable

FACTS: list[tuple[str, ...]] = []


def fact(name: str, ok: bool, detail: str = "") -> None:
    FACTS.append((name, "RED" if ok else "GREEN(неожиданно)", detail))
    print(f"[{'RED' if ok else '!!GREEN!!'}] {name} {detail}")


def show(path: str, revision: str = PARENT) -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{revision}:{path}"],
        capture_output=True, text=True,
    )
    return out.stdout if out.returncode == 0 else ""


def main() -> int:
    print(f"== RED на родителе {PARENT} (worktree {WORKTREE.name}) ==")
    rev = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=7", f"{PARENT}^{{commit}}"],
        capture_output=True, text=True,
    )
    assert PARENT.startswith(rev.stdout.strip()), rev.stdout
    print(f"родитель подтверждён: {rev.stdout.strip()}")

    # (1) Статические факты отсутствия артефактов задачи.
    fact("F1 identity.py отсутствует", not show("apps/api/identity.py"))
    fact(
        "F2 test_doclog0_identity.py отсутствует",
        not show("tests/api/test_doclog0_identity.py"),
    )
    fact(
        "F3 миграция 0006 отсутствует",
        not show("apps/api/migrations/0006_doclog0_run_ownership.sql"),
    )
    fact(
        "F4 контрактный документ отсутствует",
        not show("docs/doclog0_identity_contract.md"),
    )
    research_runs = show("apps/api/research_runs.py")
    fact(
        "F5 MIGRATION_STATEMENTS_0006 отсутствует",
        "MIGRATION_STATEMENTS_0006" not in research_runs,
    )
    fact(
        "F6 ResearchRun без owner_subject/tenant_id/ownership",
        "owner_subject: Optional[str] = None" not in research_runs
        and "ownership: Optional[str] = None" not in research_runs,
    )
    fact(
        "F7 _mirror_run_base не привязывает владельца",
        "session.ensure_owner_binding()" not in research_runs
        and 'ownership="bound"' not in research_runs,
    )
    fact(
        "F8 record_run_event без гварда субъекта",
        "эшелонированная защита слоя 2" not in research_runs,
    )
    progress = show("apps/api/routers/progress.py")
    fact(
        "F9 _authorized_run отсутствует (report без owner-проверки, F08)",
        "_authorized_run" not in progress
        and "def get_run_report" in progress,
    )
    fact(
        "F10 детальный 404 отчёта дисклоужал run_id (f-string)",
        'f"Запуск {run_id} не найден"' in progress,
    )
    session_store = show("apps/api/session_store.py")
    fact(
        "F11 AnalysisSession без owner_subject/ensure_owner_binding",
        "ensure_owner_binding" not in session_store
        and "owner_subject: Optional[str] = None" not in session_store,
    )
    fact(
        "F12 SESSION_SCHEMA_VERSION == 3 на родителе (4 на HEAD)",
        "SESSION_SCHEMA_VERSION = 3" in session_store,
    )
    auth = show("apps/api/auth.py")
    fact(
        "F13 реестр ключей без subject/tenant/scopes-сегментов",
        "subject_pseudonym" not in auth and "scopes_raw" not in auth,
    )
    fact(
        "F14 resolve_principal_for_key отсутствует",
        "def resolve_principal_for_key" not in auth,
    )
    diag = show("apps/api/storage_diagnostics.py")
    fact(
        "F15 /health/ops без identity-блока",
        "build_identity_health" not in diag and '"identity"' not in diag,
    )

    # (2) Оракулы на родителе -- worktree.
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "add", "--detach", str(WORKTREE), PARENT],
        check=True, capture_output=True,
    )
    try:
        # Копируем оракулы в worktree (их там нет -- они untracked артефакты
        # сертификации; корпус дизъюнктен и НЕ зависит от задачных файлов).
        import shutil

        dst = WORKTREE / "scripts" / "doclog0cert"
        dst.mkdir(parents=True, exist_ok=True)
        for name in (
            "oracle_corpus.py",
            "test_doclog0cert_oracle_unit.py",
            "test_doclog0cert_oracle_api.py",
        ):
            shutil.copy(Path(__file__).parent / name, dst / name)

        env_args = ["env", "DATABASE_URL=", "CISSTAT_DATA_DIR="]
        unit = subprocess.run(
            env_args + [PYTHON, "-m", "pytest",
                        "scripts/doclog0cert/test_doclog0cert_oracle_unit.py",
                        "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=WORKTREE, capture_output=True, text=True, timeout=600,
        )
        tail = unit.stdout.strip().splitlines()[-1] if unit.stdout.strip() else ""
        fact("F16 unit-оракулы RED (identity.py не существует -> collection error)",
             unit.returncode != 0, tail)

        api = subprocess.run(
            env_args + [PYTHON, "-m", "pytest",
                        "scripts/doclog0cert/test_doclog0cert_oracle_api.py",
                        "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=WORKTREE, capture_output=True, text=True, timeout=600,
        )
        api_out = api.stdout
        api_tail = api_out.strip().splitlines()[-1] if api_out.strip() else ""
        # Композиция: часть API-оракулов честно зелёная на родителе
        # (владелец читает своё -- тривиально и без гейта; mirror-легаси
        # и legacy-поведение не менялись) -- красными обязаны быть
        # привязка владельца, uniform-404, write-гейт, restore-наследование.
        fact("F17 API-оракулы RED (rc!=0 -- F08 живьём)", api.returncode != 0, api_tail)
        failed_lines = [
            line for line in api_out.splitlines() if line.startswith("FAILED")
        ]
        for marker in (
            "test_oc36_demo_upload_binds_owner",
            "test_oc39_foreign_denied_uniform_404_no_leak",
            "test_oc40_write_paths_denied_for_foreign",
            "test_oc45_restore_inherits_owner_and_fresh_session_reads",
        ):
            fact(
                f"F18 {marker} FAILED на родителе",
                any(marker in line for line in failed_lines),
            )
    finally:
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(WORKTREE)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "worktree", "prune"], capture_output=True
        )
        print("worktree удалён, cleanup подтверждён")

    red = sum(1 for _, state, _ in FACTS if state == "RED")
    print(f"\nИТОГО RED-репродукции: {red}/{len(FACTS)} фактов красные")
    return 0 if red == len(FACTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
