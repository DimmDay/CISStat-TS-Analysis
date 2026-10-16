# scripts/db4cert_mutations.py
"""
Независимая сертификация UPLOAD-DB-4 — мутационный прогон на СВОИХ
мутантах. Двухканальная схема: (repo) repo-сюита задач
tests/api/test_upload_db.py + VERSIONED test_progress_trace_hook.py;
(oracle) свой корпус оракулов scripts/db4cert_oracles.py.
MB-00 — no-op-контроль достоверности харнесса (обязан пережить ОБА
канала). Восстановление файлов побайтовое с md5-контролем каждого шага.

Запуск: DATABASE_URL="" python scripts/db4cert_mutations.py
Протокол: scripts/db4cert_mutations.txt
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UPLOAD_DB = ROOT / "apps/api/routers/upload_db.py"
UPLOAD_COMMON = ROOT / "apps/api/upload_common.py"
TRACE_HOOK = ROOT / "apps/api/trace_hook.py"
SCHEMAS = ROOT / "apps/api/schemas.py"

PYTHON = sys.executable

# (id, файл, старая строка, новая строка, ожидаемое число вхождений)
MUTANTS: list[tuple[str, Path, str, str, int]] = [
    (
        "MB-00 no-op-контроль (харнесс достоверен, если переживает оба канала)",
        UPLOAD_DB,
        "logger = logging.getLogger(__name__)",
        "logger = logging.getLogger(__name__)  # db4cert no-op",
        1,
    ),
    (
        "MB-01 /test: probe лжёт ok=True при транспортном сбое",
        UPLOAD_DB,
        "ok=False, db_type=db_type, error=mask_secrets(str(exc), password)",
        "ok=True, db_type=db_type, error=mask_secrets(str(exc), password)",
        1,
    ),
    (
        "MB-02 /test: снято маскирование причины отказа (D4)",
        UPLOAD_DB,
        "ok=False, db_type=db_type, error=mask_secrets(str(exc), password)",
        "ok=False, db_type=db_type, error=str(exc)",
        1,
    ),
    (
        "MB-03 /test: ValueError (вкл. whitelist/расширение) -> 400 вместо 422",
        UPLOAD_DB,
        "raise HTTPException(status_code=422, detail=mask_secrets(str(exc), password))\n        latency_ms",
        "raise HTTPException(status_code=400, detail=mask_secrets(str(exc), password))\n        latency_ms",
        1,
    ),
    (
        "MB-04 /load: DbQueryRejected (read-only guard) -> 400 вместо 422",
        UPLOAD_DB,
        "raise HTTPException(status_code=422, detail=str(exc))",
        "raise HTTPException(status_code=400, detail=str(exc))",
        1,
    ),
    (
        "MB-05 /load: init-сбой -> 422 вместо 400 (карта ошибок перевёрнута)",
        UPLOAD_DB,
        'raise HTTPException(status_code=400, detail=mask_secrets(str(exc), password))\n\n        try:\n            result = load_db_dataframe(',
        'raise HTTPException(status_code=422, detail=mask_secrets(str(exc), password))\n\n        try:\n            result = load_db_dataframe(',
        1,
    ),
    (
        "MB-06 /load: честная пометка усечения снята (truncated игнорируется)",
        UPLOAD_DB,
        "if result.truncated:",
        "if False:",
        1,
    ),
    (
        "MB-07 /load: имя серверного источника без label реестра",
        UPLOAD_DB,
        'return f"{spec.label}: {connection.database}"',
        'return f"{connection.database}"',
        1,
    ),
    (
        "MB-08 /load: имя embedded-источника — полный путь вместо basename",
        UPLOAD_DB,
        "return os.path.basename(os.path.expanduser(str(connection.path).strip()))",
        "return str(connection.path).strip()",
        1,
    ),
    (
        "MB-09 /load: size_label — константа (нечестная размерность)",
        UPLOAD_DB,
        "size_label = format_size_label(int(df.memory_usage(deep=True).sum()))",
        'size_label = "0 B"',
        1,
    ),
    (
        "MB-10 register_uploaded_dataframe: потеря store.save (класс PROGR-25-F1; Memory-алиасинг маскирует)",
        UPLOAD_COMMON,
        "    store.save(session)\n",
        "",
        1,
    ),
    (
        "MB-11 register_uploaded_dataframe: авто-фиксация цели снята (PROGR-25-A)",
        UPLOAD_COMMON,
        "    auto_fix_and_seed(session)\n",
        "",
        1,
    ),
    (
        "MB-12 preview.head без строки заголовка колонок",
        UPLOAD_COMMON,
        "head = [[str(col) for col in df.columns.tolist()]] + head",
        "pass  # db4cert mutant: заголовок снят",
        1,
    ),
    (
        "MB-13 TRACE_ROUTES: путь internal db/load разъехался (событие не пишется)",
        TRACE_HOOK,
        '"POST", "/v1/internal/upload/db/load", "upload", "overview",',
        '"POST", "/v1/internal/upload/db/loadx", "upload", "overview",',
        1,
    ),
    (
        "MB-14 TRACE_ROUTES: payload internal db/load обеднен (size_label потерян)",
        TRACE_HOOK,
        '"POST", "/v1/internal/upload/db/load", "upload", "overview",\n        "upload_completed", payload_keys=("name", "rows", "columns", "size_label"),',
        '"POST", "/v1/internal/upload/db/load", "upload", "overview",\n        "upload_completed", payload_keys=("name",),',
        1,
    ),
    (
        "MB-15 schemas: safe-дефолт ssl=False перевёрнут в True (D3)",
        SCHEMAS,
        "ssl: bool = Field(\n        False,",
        "ssl: bool = Field(\n        True,",
        1,
    ),
    (
        "MB-16 schemas: extra=forbid снят (смешение профилей принимается молча)",
        SCHEMAS,
        'model_config = ConfigDict(extra="forbid")',
        'model_config = ConfigDict(extra="ignore")',
        2,
    ),
    (
        "MB-17 public-семейство: API-ключ снят (require_api_key)",
        UPLOAD_DB,
        "public_router = APIRouter(dependencies=[Depends(require_api_key)])",
        "public_router = APIRouter()",
        1,
    ),
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env={
            **__import__("os").environ, "DATABASE_URL": "", "PYTHONDONTWRITEBYTECODE": "1"
        },
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    passport = {p: md5(p) for p in {m[1] for m in MUTANTS}}
    lines: list[str] = [
        "db4cert мутационный прогон UPLOAD-DB-4 (свои мутанты, двухканальная схема repo+oracle)",
        f"md5-паспорт до прогона: { {p.name: h for p, h in passport.items()} }",
        "",
    ]
    survivors = 0
    for mid, path, old, new, expected in MUTANTS:
        text = path.read_text()
        count = text.count(old)
        if count != expected:
            lines.append(f"{mid}: ОШИБКА ХАРНЕССА — вхождений {count}, ожидалось {expected}")
            print(lines[-1])
            return 2
        mutated = text.replace(old, new)
        path.write_text(mutated)
        try:
            rc_repo, out_repo = run([
                PYTHON, "-m", "pytest", "tests/api/test_upload_db.py",
                "tests/api/test_progress_trace_hook.py", "-q", "--tb=no",
                "-p", "no:cacheprovider",
            ])
            rc_oracle, out_oracle = run([
                PYTHON, "-m", "pytest", "scripts/db4cert_oracles.py",
                "-q", "--tb=line", "-x", "-p", "no:cacheprovider",
            ])
        finally:
            path.write_text(text)  # побайтовое восстановление (read_text/roundtrip)
        repo_state = "SURVIVED" if rc_repo == 0 else "KILLED"
        oracle_state = "SURVIVED" if rc_oracle == 0 else "KILLED"
        if repo_state == "SURVIVED" and oracle_state == "SURVIVED":
            survivors += 1
            verdict = "DUAL-SURVIVOR"
        else:
            verdict = "ok"
        repo_tail = [
            l for l in out_repo.splitlines() if l.startswith(("FAILED", "ERROR"))
        ][:3]
        oracle_tail = [
            l for l in out_oracle.splitlines() if l.startswith(("FAILED", "ERROR"))
        ][:3]
        detail = (
            f"{mid}\n"
            f"    repo: {repo_state} ({_summary(out_repo)})\n"
            f"    oracle: {oracle_state} ({_summary(out_oracle)})\n"
            + (f"    repo-убийцы: {repo_tail}\n" if repo_tail else "")
            + (f"    oracle-убийцы: {oracle_tail}\n" if oracle_tail else "")
            + f"    вердикт: {verdict}"
        )
        lines.append(detail)
        print(f"{mid.split(' (')[0]} -> repo {repo_state} / oracle {oracle_state}")
    md5_after = {p: md5(p) for p in {m[1] for m in MUTANTS}}
    restored = all(passport[p] == md5_after[p] for p in passport)
    import subprocess as sp
    diff_empty = sp.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0
    lines += [
        "",
        f"md5-паспорт после прогона: СХОДИТСЯ = {restored}",
        f"git diff пуст (дерево чистое): {diff_empty}",
        f"DUAL-SURVIVORS (без MB-00): {survivors - 1}",
    ]
    report = "\n".join(lines)
    (ROOT / "scripts/db4cert_mutations.txt").write_text(report + "\n")
    print(report.splitlines()[-3:])
    return 0 if restored and diff_empty else 3


def _summary(out: str) -> str:
    for line in out.splitlines():
        if " passed" in line or " failed" in line or "error" in line.lower():
            return line.strip().split("==")[-1].strip() if "==" in line else line.strip()[:90]
    return out.strip().splitlines()[-1][:90] if out.strip() else "нет вывода"


if __name__ == "__main__":
    sys.exit(main())
