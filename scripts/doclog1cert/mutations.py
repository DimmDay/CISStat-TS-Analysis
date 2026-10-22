# scripts/doclog1cert/mutations.py
"""DOCLOG-1-CERT: мутационная кампания на СВОИХ мутантах.

Двухканальная схема (паттерн CERT-серии платформы):
  ORACLE-канал -- scripts/doclog1cert/ (62 оракула сертификатора);
  REPO-канал    -- tests/api/test_doclog1_artifacts.py +
                   tests/api/test_research_runs.py +
                   tests/api/test_session_store.py.

27 боевых мутантов (цели: artifact_store.py, artifact_promotion.py,
research_runs.py, routers/progress.py, storage_diagnostics.py)
+ 3 no-op-контроля. Применение -- точечная байтовая замена (контроль:
ровно 1 вхождение), восстановление побайтовое с md5-паспортом
до/после; финальный контроль -- git diff пуст.

Классификация: DUAL-KILLED (оба канала), ORACLE-ONLY, REPO-ONLY,
DUAL-SURVIVOR (оба живы -- кандидат в равносильные/находку),
контроли -- ALIVE(OK).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

REPO_CMD = [
    PYTHON, "-m", "pytest",
    "tests/api/test_doclog1_artifacts.py",
    "tests/api/test_research_runs.py",
    "tests/api/test_session_store.py",
    "-x", "-q", "--no-header", "-p", "no:cacheprovider",
]
ORACLE_CMD = [
    PYTHON, "-m", "pytest",
    "scripts/doclog1cert",
    "-x", "-q", "--no-header", "-p", "no:cacheprovider",
]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _run(cmd: list[str]) -> tuple[int, str]:
    env = dict(os.environ)
    env["DATABASE_URL"] = ""  # песочница-DSN psycopg вне сертификации
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                          timeout=1200, env=env)
    return proc.returncode, (proc.stdout + proc.stderr)


class Mutant:
    def __init__(self, mid: str, rel_path: str, old: str, new: str, note: str = ""):
        self.mid, self.rel_path, self.old, self.new, self.note = (
            mid, rel_path, old, new, note
        )

    def apply(self) -> bool:
        path = REPO_ROOT / self.rel_path
        text = path.read_text(encoding="utf-8")
        if text.count(self.old) != 1:
            return False
        path.write_text(text.replace(self.old, self.new, 1), encoding="utf-8")
        return True

    def restore(self) -> None:
        raise NotImplementedError


class ByteMutant(Mutant):
    """Байтовая замена с точным восстановлением исходного текста."""

    def __init__(self, mid, rel_path, old, new, note=""):
        super().__init__(mid, rel_path, old, new, note)
        self._original: bytes | None = None

    def apply(self) -> bool:
        path = REPO_ROOT / self.rel_path
        self._original = path.read_bytes()
        return super().apply()

    def restore(self) -> None:
        path = REPO_ROOT / self.rel_path
        if self._original is not None:
            path.write_bytes(self._original)
            self._original = None


def build_mutants() -> list[ByteMutant]:
    store = "apps/api/artifact_store.py"
    promo = "apps/api/artifact_promotion.py"
    runs = "apps/api/research_runs.py"
    progress = "apps/api/routers/progress.py"
    diag = "apps/api/storage_diagnostics.py"
    return [
        # ── artifact_store.py ────────────────────────────────────────
        ByteMutant("M01", store, "allow_nan=False,", "allow_nan=True,",
                   "T12: маскировка NaN в канонизации"),
        ByteMutant("M02", store,
                   "hashlib.sha256(data).hexdigest() != staged.sha256",
                   "hashlib.sha256(data).hexdigest() == staged.sha256",
                   "verify staging инвертирован (AC08 fail-closed снят)"),
        ByteMutant("M03", store,
                   "if hashlib.sha256(data).hexdigest() != expected:",
                   "if False:",
                   "T8: проверка целостности при чтении снята"),
        ByteMutant("M04", store,
                   'DATA_DIGEST_ALGORITHM = "cisstat-data-v1"',
                   'DATA_DIGEST_ALGORITHM = "cisstat-data-v2"',
                   "algorithm/version data_digest искажён"),
        ByteMutant("M05", store, "if item.run_id == artifact.run_id",
                   "if item.run_id != artifact.run_id",
                   "AC09: идемпотентность/конфликт Memory сняты"),
        ByteMutant("M06", store,
                   "for pin in self.list_pins(run_id, ref_kind=REF_KIND_CHECKPOINT)",
                   "for pin in self.list_pins(run_id)",
                   "pinned_checkpoint_ids игнорирует ref_kind"),
        ByteMutant("M07", store, "existing = self._pins.get(key)",
                   "existing = None",
                   "идемпотентность pin_ref снята"),
        ByteMutant("M08", store, "if age >= grace_seconds:", "if False:",
                   "sweep перестаёт удалять orphan staging"),
        ByteMutant("M09", store, "{staged.sha256[:2]}/{staged.sha256}",
                   "{staged.sha256[:1]}/{staged.sha256}",
                   "схема content-addressed ключа изменена"),
        ByteMutant("M10", store, 'return "art-" + uuid.uuid4().hex',
                   'return "art_" + uuid.uuid4().hex',
                   "схема artifact_id искажена"),
        ByteMutant("M11", store, 'if not probe.get("ok"):', "if False:",
                   "P21/F14: required fail-closed снят"),
        ByteMutant("M12", store,
                   "staged.path.unlink(missing_ok=True)\n        return key",
                   "pass\n        return key",
                   "staging не убирается после коммита"),
        ByteMutant("M13", store, "return artifact.copy() if artifact else None",
                   "return artifact if artifact else None",
                   "R1: копии записей реестра сняты"),
        # ── artifact_promotion.py ────────────────────────────────────
        ByteMutant("M14", promo, "if run is None:", "if False:",
                   "uniform-отказ отсутствующего run снят"),
        ByteMutant("M15", promo, 'if action == "write":', "if False:",
                   "R09: классификация write-отказа снята"),
        ByteMutant("M16", promo, "snapshot = session.latest_panel_passport()",
                   'snapshot = session.latest_passport("modeling_entry")',
                   "R4/AC13: изоляция panel-вселенной снята"),
        ByteMutant("M17", promo, "                raise PromotionUnavailable(",
                   "                raise",
                   "AC12-дух: честный отказ NaN подменён сырым исключением"),
        ByteMutant("M18", promo, "if artifact.producer_key == producer_key:",
                   "if False:",
                   "предварительный поиск producer_key снят (гарантия остаётся в реестре)"),
        ByteMutant("M19", promo, "for checkpoint_id in auto_pin_checkpoints or []:",
                   "for checkpoint_id in []:",
                   "AC04: авто-pin зависимостей снят"),
        ByteMutant("M20", promo, "dependencies=[checkpoint_id] if checkpoint_id else [],",
                   "dependencies=[],",
                   "зависимость model_card от checkpoint снята"),
        ByteMutant("M21", promo, 'if is_valid_source_ref(source_bytes_sha256 or "")',
                   "if True",
                   "невалидный source-ref фабкуется"),
        # ── research_runs.py ─────────────────────────────────────────
        ByteMutant("M22", runs,
                   "if not path.exists():\n            return None\n        try:\n            return path.read_bytes()",
                   "if False:\n            return None\n        try:\n            return path.read_bytes()",
                   "честное отсутствие снимка чекпоинта снято"),
        ByteMutant("M23", runs,
                   "+ MIGRATION_STATEMENTS_0005 + MIGRATION_STATEMENTS_0006\n    + MIGRATION_STATEMENTS_0007",
                   "+ MIGRATION_STATEMENTS_0005 + MIGRATION_STATEMENTS_0006",
                   "миграция 0007 выведена из каталога"),
        # ── progress.py ──────────────────────────────────────────────
        ByteMutant("M24", progress, "pinned = None", "pinned = set()",
                   "T11: fail-closed prune при сбое lookup снят"),
        ByteMutant("M25", progress, "dict.fromkeys(list(keep) + sorted(pinned))",
                   "dict.fromkeys(list(keep))",
                   "AC04: объединение keep-списка с пинами снято"),
        # ── storage_diagnostics.py ───────────────────────────────────
        ByteMutant("M26", diag, '"artifacts": build_artifacts_health(),', "",
                   "T6: artifacts-блок /health/ops удалён"),
        ByteMutant("M27", diag,
                   'bool(\n            (os.environ.get("CISSTAT_DATA_DIR") or "").strip()\n        )',
                   'os.environ.get("CISSTAT_DATA_DIR") or ""',
                   "T10: раскрытие пути в health"),
        # ── no-op контроли ───────────────────────────────────────────
        ByteMutant("CTL-01", store, 'OBJECTS_DIR = "objects"',
                   'OBJECTS_DIR = "objects"  # cert-noop',
                   "no-op: комментарий"),
        ByteMutant("CTL-02", promo, "logger = logging.getLogger(__name__)",
                   "logger = logging.getLogger(__name__)  # cert-noop",
                   "no-op: комментарий"),
        ByteMutant("CTL-03", progress, "def create_checkpoint(",
                   "def create_checkpoint(  # cert-noop",
                   "no-op: комментарий"),
    ]


def main() -> int:
    mutants = build_mutants()
    target_files = sorted({m.rel_path for m in mutants})
    # аварийное восстановление после возможного падения прошлой сессии
    subprocess.run(
        ["git", "checkout", "--"] + target_files,
        cwd=REPO_ROOT, capture_output=True,
    )
    passports_before = {rel: _md5(REPO_ROOT / rel) for rel in target_files}
    log: list[str] = []
    for mutant in mutants:
        path = REPO_ROOT / mutant.rel_path
        if not mutant.apply():
            line = f"{mutant.mid} | APPLY-FAIL (якорь не уникален) | {mutant.note}"
            log.append(line)
            print(line)
            continue
        try:
            oracle_rc, _ = _run(ORACLE_CMD)
            repo_rc, _ = _run(REPO_CMD)
        finally:
            mutant.restore()
        oracle_kill = oracle_rc != 0
        repo_kill = repo_rc != 0
        if oracle_kill and repo_kill:
            verdict = "DUAL-KILLED"
        elif oracle_kill:
            verdict = "ORACLE-ONLY"
        elif repo_kill:
            verdict = "REPO-ONLY"
        else:
            verdict = "DUAL-SURVIVOR"
        if mutant.mid.startswith("CTL"):
            verdict = "ALIVE(OK)" if not (oracle_kill or repo_kill) else "CTL-KILLED(BAD)"
        line = (f"{mutant.mid} | {mutant.rel_path.split('/')[-1]} | {verdict} | "
                f"oracle_kill={oracle_kill} repo_kill={repo_kill} | {mutant.note}")
        log.append(line)
        print(line, flush=True)
    passports_after = {rel: _md5(REPO_ROOT / rel) for rel in target_files}
    restore_ok = passports_before == passports_after
    git_diff = subprocess.run(
        ["git", "diff", "--stat"] + target_files,
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    clean = git_diff.stdout.strip() == ""
    report = "\n".join(log) + (
        f"\n\nmd5-паспорта восстановлены: {restore_ok}; git diff чист: {clean}\n"
    )
    out = Path(__file__).resolve().parent / "mutations_protocol.txt"
    out.write_text(report, encoding="utf-8")
    print(report.splitlines()[-2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
