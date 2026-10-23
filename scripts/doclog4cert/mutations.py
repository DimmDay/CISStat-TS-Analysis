# scripts/doclog4cert/mutations.py
# DOCLOG-4-CERT: мутационная кампания («мутанты на своих мутантах»).
# Боевые мутанты -- точечные правки кода DOCLOG-4; каждый прогоняется
# через ДВА канала: REPO (tests/api/test_doclog4_document_delivery.py)
# и ORACLE (корпус сертификатора БЕЗ RED-блока -- чистые GREEN-оракулы).
# Классификация: DUAL-KILLED / REPO-ONLY / ORACLE-ONLY / SURVIVED.
# Контрольные no-op-мутанты обязаны оставаться ALIVE в обоих каналах
# (проверка того, что каналы убивают семантику, а не любой дифф).
# После каждого мутанта -- байт-в-байт восстановление (RESTORE-FAIL=0).
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
PROTO_DIR = Path(__file__).resolve().parent / "protocols"

RENDITIONS = REPO / "apps" / "api" / "document_renditions.py"
JOBS = REPO / "apps" / "api" / "document_jobs.py"
ROUTER = REPO / "apps" / "api" / "routers" / "documentation.py"

# ── Боевые мутанты (файл, old, new, описание) ────────────────────────

BATTLE = [
    (
        "M01", RENDITIONS,
        '    escaped = _html.escape(str(value), quote=True)\n    return _HTML_SCHEME_RE.sub(r"\\1&#58;", escaped)',
        '    return str(value)',
        "HTML: снято экранирование + нейтрализация схем (AC16)",
    ),
    (
        "M02", RENDITIONS,
        '    escaped = _html.escape(str(value), quote=True)\n    return _HTML_SCHEME_RE.sub(r"\\1&#58;", escaped)',
        '    return _html.escape(str(value), quote=True)',
        "HTML: снята только нейтрализация javascript:/data: схем",
    ),
    (
        "M03", RENDITIONS,
        "    if text.startswith(_CSV_FORMULA_PREFIXES):\n        return \"'\" + text\n    return text",
        "    return text",
        "CSV: снята spreadsheet-safe нейтрализация префиксов =,+,-,@",
    ),
    (
        "M04", RENDITIONS,
        "                event_count if isinstance(event_count, int) else \"\",\n                last_sequence if isinstance(last_sequence, int) else \"\",",
        "                _csv_text(event_count),\n                _csv_text(last_sequence),",
        "CSV: числа прогнаны через текстовый safe-профиль (минусы -> текст)",
    ),
    (
        "M05", RENDITIONS,
        '            envelope = {\n                "schema_version": JSONL_SCHEMA_VERSION,',
        '            envelope = {\n                "schema_version": "dropped",',
        "JSONL: envelope теряет schema_version снимка (подмена)",
    ),
    (
        "M06", RENDITIONS,
        '    for section in snapshot.sections:\n        for claim in section.get("claims", []):\n            envelope = {',
        '    for section in reversed(snapshot.sections):\n        for claim in section.get("claims", []):\n            envelope = {',
        "JSONL: порядок секций инвертирован (§7 порядок frozen корпуса)",
    ),
    (
        "M07", RENDITIONS,
        '    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(revision_id)) or "unknown"',
        '    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", str(revision_id)) or "unknown"',
        "filename: разрешена точка (path-traversal '..' проходит)",
    ),
    (
        "M08", JOBS,
        "        if (\n            existing is not None\n            and existing.state == RENDITION_READY\n            and existing.job_id\n            and self.registry.get_job(existing.job_id) is not None\n        ):",
        "        if False:",
        "Jobs: снята идемпотентность выдачи (каждый клик -- новый job)",
    ),
    (
        "M09", JOBS,
        "        if artifact_content_sha256(content) != rendition.content_sha256:\n            raise DocumentIntegrityError(",
        "        if False:\n            raise DocumentIntegrityError(",
        "Jobs: снят integrity-гвард content_sha256 (T8-дух)",
    ),
    (
        "M10", JOBS,
        '        if job.state in (JOB_QUEUED, JOB_RENDERING):\n            job = self.registry.update_job(\n                replace_dataclass(job, state=JOB_CANCELLED)\n            )\n        return job',
        "        job = self.registry.update_job(\n            replace_dataclass(job, state=JOB_CANCELLED)\n        )\n        return job",
        "Jobs: cancel переписывает терминальные состояния (ready -> cancelled)",
    ),
    (
        "M11", JOBS,
        "    result = func(snapshot)\n    if isinstance(result, bytes):\n        return result\n    return str(result).encode(\"utf-8\")",
        "    result = func(snapshot)\n    if isinstance(result, bytes):\n        return b\"\"\n    return str(result).encode(\"utf-8\")",
        "Jobs: байтовый рендер обнуляется (пустой ready-файл)",
    ),
    (
        "M12", JOBS,
        "        decision = authorize_run_access(\n            run, subject, session_id=session_id, action=action\n        )\n        if not decision.allowed:\n            raise DocumentAccessDenied(\"Запуск недоступен\")\n        return run",
        "        decision = authorize_run_access(\n            run, subject, session_id=session_id, action=action\n        )\n        if False:\n            raise DocumentAccessDenied(\"Запуск недоступен\")\n        return run",
        "Jobs: сервисная авторизация отключена (R09 сквозной канал)",
    ),
    (
        "M13", ROUTER,
        "    if isinstance(exc, DocumentAccessDenied):\n        return HTTPException(status_code=404, detail=_DOCUMENT_NOT_FOUND_DETAIL)",
        "    if isinstance(exc, DocumentAccessDenied):\n        return HTTPException(status_code=403, detail=_DOCUMENT_NOT_FOUND_DETAIL)",
        "Router: uniform-404 -> 403 (дисклоужается существование, AC06)",
    ),
    (
        "M14", ROUTER,
        "    # 3. response_stream_finished (завершение отдачи).\n    record_standard(\n        ACTION_RESPONSE_STREAM_FINISHED,",
        "    # 3. response_stream_finished (завершение отдачи).\n    if False:\n        record_standard(\n            ACTION_RESPONSE_STREAM_FINISHED,",
        "Router: тройка аудита теряет finished (§14.1 различимость)",
    ),
    (
        "M15", ROUTER,
        '    record_standard(\n        ACTION_PROTECTED_DOCUMENT_VIEWED,',
        '    if False:\n        record_standard(\n            ACTION_PROTECTED_DOCUMENT_VIEWED,',
        "Router: preview без protected_document_viewed (§14.1)",
    ),
    (
        "M16", ROUTER,
        '    return {"run_id": run_id, "documents": documents}',
        '    documents.append({"run_id": run_id, "leaked": True, "snapshot": {"dependencies": ["d4c-leak"]}})\n    return {"run_id": run_id, "documents": documents}',
        "Router: N3-гейт -- dependency-манифест утекает в список",
    ),
]

# ── Контрольные no-op-мутанты (обязаны быть ALIVE) ───────────────────

CONTROLS = [
    (
        "C01", RENDITIONS,
        "# ── Каталог форматов P0 (§7) ─────────────────────────────────────────\n",
        "# ── Каталог форматов P0 (§7) ─────────────────────────────────────────\n# d4c-control: no-op комментарий сертификатора\n",
        "Контроль: комментарий (семантики нет)",
    ),
    (
        "C02", JOBS,
        "def _now_iso() -> str:\n    return datetime.now(timezone.utc).isoformat()",
        "def _now_iso() -> str:\n    return (datetime.now(timezone.utc).isoformat())",
        "Контроль: скобочная группировка (AST-эквивалент)",
    ),
    (
        "C03", ROUTER,
        "def peek_snapshot_record(snapshot_id: str) -> Any:\n    from apps.api.report_snapshot import peek_snapshot_registry",
        "def peek_snapshot_record(snapshot_id: str) -> Any:\n    # d4c-control-3: реимпорт без эффекта\n    from apps.api.report_snapshot import peek_snapshot_registry",
        "Контроль: комментарий-2 (семантики нет)",
    ),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _apply(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def _run_channel(name: str, args: list[str]) -> tuple[bool, str, float]:
    started = time.time()
    proc = subprocess.run(
        [PY, "-m", "pytest", *args, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    return proc.returncode == 0, " | ".join(tail), time.time() - started


def main() -> int:
    PROTO_DIR.mkdir(exist_ok=True)
    repo_args = ["tests/api/test_doclog4_document_delivery.py"]
    oracle_args = ["scripts/doclog4cert/", "--deselect",
                   "scripts/doclog4cert/test_doclog4cert_oracle_api.py::TestOrcRedDefectProofs"]

    results = []
    restore_failures = 0
    baseline_hashes = {_sha(p): str(p) for p in {RENDITIONS, JOBS, ROUTER}}

    for family, entries in (("BATTLE", BATTLE), ("CONTROL", CONTROLS)):
        for mid, path, old, new, desc in entries:
            original = _sha(path)
            if not _apply(path, old, new):
                results.append({
                    "id": mid, "family": family, "status": "APPLY-FAIL",
                    "description": desc,
                })
                print(f"[{mid}] APPLY-FAIL -- маркер не найден", flush=True)
                continue
            try:
                repo_ok, repo_tail, repo_t = _run_channel(mid, repo_args)
                oracle_ok, oracle_tail, oracle_t = _run_channel(mid, oracle_args)
            finally:
                # Восстановление из git (байт-в-байт) и проверка.
                subprocess.run(
                    ["git", "checkout", "--", str(path.relative_to(REPO))],
                    cwd=REPO, capture_output=True, text=True,
                )
                if _sha(path) != original:
                    restore_failures += 1

            repo_killed = not repo_ok
            oracle_killed = not oracle_ok
            if family == "CONTROL":
                status = "ALIVE" if (repo_killed is False and oracle_killed is False) else "FALSELY-KILLED"
            else:
                if repo_killed and oracle_killed:
                    status = "DUAL-KILLED"
                elif repo_killed:
                    status = "REPO-ONLY"
                elif oracle_killed:
                    status = "ORACLE-ONLY"
                else:
                    status = "SURVIVED"
            results.append({
                "id": mid, "family": family, "status": status,
                "description": desc,
                "repo_killed": repo_killed, "oracle_killed": oracle_killed,
                "repo_tail": repo_tail, "oracle_tail": oracle_tail,
                "repo_seconds": round(repo_t, 1), "oracle_seconds": round(oracle_t, 1),
            })
            print(f"[{mid}] {status} -- {desc}", flush=True)

    summary = {
        "task": "DOCLOG-4-CERT",
        "channels": {"repo": repo_args, "oracle": oracle_args},
        "battle": [r for r in results if r["family"] == "BATTLE"],
        "controls": [r for r in results if r["family"] == "CONTROL"],
        "restore_failures": restore_failures,
        "baseline_hashes": baseline_hashes,
    }
    (PROTO_DIR / "mutations_protocol.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    killed = sum(1 for r in summary["battle"] if "KILLED" in r["status"])
    alive_controls = sum(1 for r in summary["controls"] if r["status"] == "ALIVE")
    print(
        f"\nИТОГ: battle {killed}/{len(summary['battle'])} KILLED "
        f"(SURVIVED={sum(1 for r in summary['battle'] if r['status']=='SURVIVED')}), "
        f"controls ALIVE {alive_controls}/{len(summary['controls'])}, "
        f"RESTORE-FAIL={restore_failures}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
