# scripts/doclog0cert/mutations.py
"""DOCLOG-0-CERT: мутационная кампания на СВОИХ мутантах.

Двухканальная схема (паттерн CERT-серии платформы):
  ORACLE-канал  -- scripts/doclog0cert/ (53 оракула сертификатора);
  REPO-канал    -- tests/api/test_doclog0_identity.py (42) +
                   tests/api/test_session_store.py + tests/api/test_research_runs.py.

26 боевых мутантов (цели: identity.py, auth.py, routers/progress.py,
research_runs.py, session_store.py) + 3 no-op-контроля. Применение --
точечная байтовая замена (контроль: ровно 1 вхождение), восстановление
побайтовое с md5-паспортом до/после; финальный контроль -- git diff пуст.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

REPO_CMD = [
    PYTHON, "-m", "pytest",
    "tests/api/test_doclog0_identity.py",
    "tests/api/test_session_store.py",
    "tests/api/test_research_runs.py",
    "-x", "-q", "--no-header", "-p", "no:cacheprovider",
]
ORACLE_CMD = [
    PYTHON, "-m", "pytest",
    "scripts/doclog0cert",
    "-x", "-q", "--no-header", "-p", "no:cacheprovider",
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _run(cmd: list[str]) -> tuple[int, str]:
    import os

    env = dict(os.environ)
    env["DATABASE_URL"] = ""  # песочница-DSN psycopg вне сертификации
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                          timeout=1200, env=env)
    return proc.returncode, (proc.stdout + proc.stderr)


def _count(text: str, needle: str) -> int:
    return text.count(needle)


class Mutant:
    def __init__(self, mid: str, rel_path: str, old: str, new: str, note: str = ""):
        self.mid, self.rel_path, self.old, self.new, self.note = (
            mid, rel_path, old, new, note
        )

    def apply(self) -> None:
        path = REPO_ROOT / self.rel_path
        text = path.read_text(encoding="utf-8")
        n = _count(text, self.old)
        if n != 1:
            raise RuntimeError(
                f"{self.mid}: вхождений {n} (ожидается 1) в {self.rel_path}: {self.old[:70]!r}"
            )
        path.write_text(text.replace(self.old, self.new, 1), encoding="utf-8")


MUTANTS: list[Mutant] = [
    # ── identity.py: решающая таблица (R09) ──
    Mutant("M01", "apps/api/identity.py",
           'return _finish(False, "anonymous", log_warning=True)',
           'return _finish(True, "anonymous", log_warning=True)',
           "анониму разрешён доступ (T1 снят)"),
    Mutant("M02", "apps/api/identity.py",
           'if (subject.role or "") == "admin":',
           'if (subject.role or "") == "dca-sudo":',
           "ADMIN-грант мёртв"),
    Mutant("M03", "apps/api/identity.py",
           "if get_identity_mode() == MODE_DEV_SINGLE_USER:",
           "if get_identity_mode() == MODE_SESSION_SCOPED:",
           "dev_single_user-режим мёртв"),
    Mutant("M04", "apps/api/identity.py",
           'subject.subject_id == getattr(run, "owner_subject", None)\n'
           "            and subject.tenant_id == run_tenant\n        ):",
           'subject.subject_id == getattr(run, "owner_subject", None)\n        ):',
           "tenant-граница снята в owner-строке (T5)"),
    Mutant("M05", "apps/api/identity.py",
           "# для чужих).\n        if (",
           "# для чужих).\n        if False and (",
           "bound creator-continuity мёртв"),
    Mutant("M06", "apps/api/identity.py",
           'return _finish(False, "foreign_session", log_warning=True)',
           'return _finish(True, "foreign_session", log_warning=True)',
           "чужой bound-запуск разрешён (T1)"),
    Mutant("M07", "apps/api/identity.py",
           'return _finish(False, "unresolved_foreign", log_warning=True)',
           'return _finish(True, "unresolved_foreign", log_warning=True)',
           "чужой legacy-запуск разрешён (T1)"),
    Mutant("M08", "apps/api/identity.py",
           '    if getattr(run, "ownership", None) == OWNERSHIP_BOUND and getattr(',
           "    if False and getattr(run, \"ownership\", None) == OWNERSHIP_BOUND and getattr(",
           "effective_ownership всегда unresolved"),
    # ── identity.py: псевдонимизация/validity/режимы (T4/T6) ──
    Mutant("M09", "apps/api/identity.py",
           "    return SUBJECT_PREFIX + digest",
           "    return SUBJECT_PREFIX + material[:16]",
           "материал субъекта всплывает в псевдониме (T4)"),
    Mutant("M10", "apps/api/identity.py",
           "        else (os.environ.get(IDENTITY_SALT_ENV) or _DEV_SALT)",
           "        else _DEV_SALT",
           "env-соль игнорируется (ротация мертва)"),
    Mutant("M11", "apps/api/identity.py",
           "        return bool(SUBJECT_ID_PATTERN.match(value))",
           "        return True",
           "подделка формы subj-* принимается"),
    Mutant("M12", "apps/api/identity.py",
           "            raw, MODE_SESSION_SCOPED,\n        )\n        return MODE_SESSION_SCOPED",
           "            raw, MODE_SESSION_SCOPED,\n        )\n        return raw",
           "незнакомый режим возвращается как есть (fail-closed снят)"),
    Mutant("M13", "apps/api/identity.py",
           '    return bool(os.environ.get("CISSTAT_API_KEYS", "").strip())',
           '    return os.environ.get("CISSTAT_API_KEYS", "").strip()',
           "ops-флаг реестра -- строка, не bool (T6)"),
    # ── auth.py: реестр ключей (T4) ──
    Mutant("M14", "apps/api/auth.py",
           "        if subject_id is not None and subject_id == key:\n            continue",
           "        if False and subject_id is not None and subject_id == key:\n            continue",
           "subject==key принят (T4 снят)"),
    Mutant("M15", "apps/api/auth.py",
           "            subject_id=subject_id if subject_id is not None else subject_pseudonym(key),",
           "            subject_id=subject_id if subject_id is not None else key,",
           "идентичность по умолчанию -- значение ключа (T4)"),
    Mutant("M16", "apps/api/auth.py",
           '            s.strip() for s in scopes_raw.split("+") if s.strip()',
           '            s.strip() for s in scopes_raw.split(",") if s.strip()',
           "разделитель scopes сломан"),
    Mutant("M17", "apps/api/auth.py",
           "    return _parse_key_registry().get(key)",
           "    return _parse_key_registry()[key]",
           "неизвестный ключ -- исключение вместо None"),
    # ── progress.py: гейт маршрутов (R09/F08) ──
    Mutant("M18", "apps/api/routers/progress.py",
           "    if not decision.allowed:\n        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND_DETAIL)",
           "    if False and not decision.allowed:\n        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND_DETAIL)",
           "объектная авторизация run-маршрутов снята (F08 возвращён)"),
    Mutant("M19", "apps/api/routers/progress.py",
           "        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND_DETAIL)",
           '        raise HTTPException(status_code=404, detail=f"Запуск {run_id} не найден")',
           "uniform-404 дисклоужает run_id"),
    Mutant("M20", "apps/api/routers/progress.py",
           '    if run.owner_subject:\n        session.owner_subject = run.owner_subject\n        session.tenant_id = run.tenant_id or "tenant-default"',
           "    if False and run.owner_subject:",
           "restore-наследование владельца снято (T3)"),
    Mutant("M21", "apps/api/routers/progress.py",
           '    run = _authorized_run(request, response, run_id, action="write")\n    if run.status == "completed":',
           '    run = _authorized_run(request, response, run_id, action="read")\n    if run.status == "completed":',
           "restore проходит как read (audit-факт действия искажён)"),
    # ── research_runs.py: привязка/гвард зеркала/COALESCE ──
    Mutant("M22", "apps/api/research_runs.py",
           "                if session_owner != existing_run.owner_subject and not same_creator:",
           "                if False and session_owner != existing_run.owner_subject and not same_creator:",
           "гвард зеркала слоя 2 снят (T2)"),
    Mutant("M23", "apps/api/research_runs.py",
           "            owner_subject=owner_subject,\n            tenant_id=tenant_id,\n            ownership=\"bound\",",
           "            owner_subject=None,\n            tenant_id=None,\n            ownership=None,",
           "создание run без привязки владельца (T3)"),
    Mutant("M24", "apps/api/research_runs.py",
           "            else existing.owner_subject",
           "            else None",
           "COALESCE инвертирован: батч без owner стирает привязку"),
    # ── session_store.py: first-write-wins / сериализация (F1-класс) ──
    Mutant("M25", "apps/api/session_store.py",
           "        if self.owner_subject is None:\n            self.owner_subject = subject_pseudonym(self.session_id)",
           "        if True:\n            self.owner_subject = subject_pseudonym(self.session_id)",
           "first-write-wins снят (restore-наследование переписывается)"),
    Mutant("M26", "apps/api/session_store.py",
           '        "owner_subject": session.owner_subject,\n        "tenant_id": session.tenant_id,',
           '        "tenant_id": session.tenant_id,',
           "owner_subject выпадает из сериализации (класс F1/PROGR-25)"),
]

CONTROLS: list[Mutant] = [
    Mutant("CTL-01", "apps/api/identity.py",
           "from apps.api.plans import Role",
           "from apps.api.plans import Role  # DOCLOG-0-CERT no-op CTL-01",
           "no-op: комментарий"),
    Mutant("CTL-02", "apps/api/routers/progress.py",
           "from apps.api.identity import authorize_run_access, resolve_request_subject",
           "from apps.api.identity import authorize_run_access, resolve_request_subject  # CTL-02",
           "no-op: комментарий"),
    Mutant("CTL-03", "apps/api/research_runs.py",
           "def _mirror_run_base(",
           "# DOCLOG-0-CERT no-op CTL-03\ndef _mirror_run_base(",
           "no-op: комментарий"),
]


def main() -> int:
    import os

    only = [s for s in (os.environ.get("MUT_ONLY") or "").split(",") if s]
    selected = MUTANTS + CONTROLS if not only else [
        m for m in MUTANTS + CONTROLS if m.mid in only
    ]
    targets: dict[str, Path] = {}
    passports: dict[str, str] = {}
    for m in MUTANTS + CONTROLS:
        path = REPO_ROOT / m.rel_path
        if m.rel_path not in targets:
            targets[m.rel_path] = path
            passports[m.rel_path] = _md5(path)

    rows: list[str] = []
    dual_only = oracle_only = repo_only = survivors = 0
    controls_alive = 0

    try:
        for m in selected:
            is_control = m in CONTROLS
            path = REPO_ROOT / m.rel_path
            m.apply()
            try:
                rc_o, _ = _run(ORACLE_CMD)
                rc_r, _ = _run(REPO_CMD)
            finally:
                _restore(path, passports)
            oracle_killed = rc_o != 0
            repo_killed = rc_r != 0
            if is_control:
                state = "ALIVE(OK)" if not oracle_killed and not repo_killed else "FALSE-KILL!!"
                if not oracle_killed and not repo_killed:
                    controls_alive += 1
            elif oracle_killed and repo_killed:
                state = "DUAL-KILLED"
                dual_only += 1
            elif oracle_killed:
                state = "ORACLE-ONLY"
                oracle_only += 1
            elif repo_killed:
                state = "REPO-ONLY"
                repo_only += 1
            else:
                state = "SURVIVED"
                survivors += 1
            rows.append(f"{m.mid} | {m.rel_path.split('/')[-1]} | {state} | oracle_kill={oracle_killed} repo_kill={repo_killed} | {m.note}")
            print(rows[-1], flush=True)
    finally:
        # Гарантированное восстановление всех целей.
        for rel, path in targets.items():
            _restore(path, passports)

    print("\n== md5-паспорт после кампании ==")
    ok_restore = all(_md5(p) == passports[r] for r, p in targets.items())
    for rel, path in targets.items():
        status = "OK" if _md5(path) == passports[rel] else "MISMATCH!!"
        print(f"{rel}: {status}")
    git_diff = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--quiet"], capture_output=True
    )
    tree_clean = git_diff.returncode == 0
    print(f"git diff пуст: {tree_clean}")

    print(
        f"\nИТОГО: боевых {len(MUTANTS)} -- DUAL {dual_only}, "
        f"ORACLE-ONLY {oracle_only}, REPO-ONLY {repo_only}, SURVIVED {survivors}; "
        f"контролей ALIVE {controls_alive}/3; restore {'OK' if ok_restore else 'FAIL'}"
    )
    with open(Path(__file__).parent / "mutations_protocol.txt", "w") as fh:
        fh.write("\n".join(rows) + "\n")
    return 0 if (survivors == 0 and controls_alive == 3 and ok_restore) else 1


def _restore(path: Path, passports: dict[str, str]) -> None:
    """Побайтовое восстановление из git (сертификатор не хранит копий --
    источник истины git, файл на HEAD == паспорт)."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    content = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel}"],
        capture_output=True, check=True,
    ).stdout
    path.write_bytes(content)
    assert _md5(path) == passports[path.relative_to(REPO_ROOT).as_posix()], (
        f"RESTORE-FAIL: {rel}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
