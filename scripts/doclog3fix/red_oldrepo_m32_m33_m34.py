# scripts/doclog3fix/red_oldrepo_m32_m33_m34.py
"""DOCLOG-3-FIX: RED-доказательство на СТАРОМ репо-канале.

На чистом 52315ac (worktree, tests/api/test_doclog3_telemetry_audit.py
= 96, БЕЗ гварда N1/N4) мутанты M32/M33/M34 должны ВЫЖИВАТЬ (это и
есть репо-гэп находок N1/N4). На новом канале (111) они убиты
(см. mutations_fix_protocol.json).

Дисциплина: точечная замена (контроль 1 вхождения), восстановление
байт-в-байт с md5-паспортом.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKTREE = Path("/home/z/my-project/wt-52315ac")
PYTHON = REPO_ROOT / "venv" / "bin" / "python"

MUTANTS = [
    ("M32", "apps/api/main.py",
     'app.add_middleware(TelemetryContextMiddleware)\n\n'
     'app.add_middleware(\n'
     '    CORSMiddleware,\n'
     '    allow_origins=_default_dev_origins + _env_origins,\n'
     '    allow_origin_regex=r"https://.*\\.vercel\\.app",\n'
     '    allow_credentials=True,\n'
     '    allow_methods=["*"],\n'
     '    allow_headers=["*"],\n'
     ')',
     'app.add_middleware(\n'
     '    CORSMiddleware,\n'
     '    allow_origins=_default_dev_origins + _env_origins,\n'
     '    allow_origin_regex=r"https://.*\\.vercel\\.app",\n'
     '    allow_credentials=True,\n'
     '    allow_methods=["*"],\n'
     '    allow_headers=["*"],\n'
     ')\n'
     'app.add_middleware(TelemetryContextMiddleware)'),
    ("M33", "apps/api/telemetry.py",
     ' occurred_at, observed_at, severity_text, severity_number,"',
     ' occurred_at, observed_at, severity_number, severity_text,"'),
    ("M34", "apps/api/security_audit.py",
     ' occurred_at, actor_subject, actor_via, tenant_id, action, decision,"',
     ' occurred_at, actor_subject, tenant_id, actor_via, action, decision,"'),
]

REPO_CMD = [
    str(PYTHON), "-m", "pytest",
    "tests/api/test_doclog3_telemetry_audit.py",
    "-q", "--no-header", "-p", "no:cacheprovider", "--tb=no",
]


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def main() -> int:
    lines: list[str] = []
    ok_all = True
    for mid, rel, old, new in MUTANTS:
        path = WORKTREE / rel
        backup = path.read_bytes()
        before_md5 = _md5(path)
        src = path.read_text(encoding="utf-8")
        if src.count(old) != 1:
            print(f"[{mid}] NOT-APPLIED (вхождений {src.count(old)})")
            ok_all = False
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        proc = subprocess.run(
            REPO_CMD, cwd=WORKTREE, capture_output=True, text=True,
            timeout=600,
        )
        survived = proc.returncode == 0
        path.write_bytes(backup)
        restored = _md5(path) == before_md5
        verdict = "SURVIVED (RED на старом канале)" if survived \
            else "KILLED (неожиданно!)"
        if survived and restored:
            pass
        else:
            ok_all = False
        print(f"[{mid}] {verdict} | restore_md5={restored} | "
              f"{proc.stdout.strip().splitlines()[-1] if proc.stdout else ''}")
        lines.append(f"{mid}: {'SURVIVED' if survived else 'KILLED'} "
                     f"restore_md5={restored}")
    (REPO_ROOT / "scripts" / "doclog3fix" / "protocols"
     / "red_oldrepo_m32_m33_m34.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print("ВЕРДИКТ:", "RED 3/3 подтверждён" if ok_all else "СБОЙ")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
