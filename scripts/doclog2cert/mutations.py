#!/usr/bin/env python3
# scripts/doclog2cert/mutations.py
# DOCLOG-2-CERT: мутационная кампания сертификатора -- СВОИ мутанты на
# 4 целях поставки DOCLOG-2 (288fdde). Двухканальная схема:
#   REPO   = tests/api/test_doclog2_snapshots.py (68, корпус исполнителя)
#   ORACLE = scripts/doclog2cert/ (78 оракулов; 3 F-D2C1-RED исключаются
#            из канала -- они красны на ЛЮБОМ мутанте из-за блокера)
# Точечные байтовые замены; контроль ровно 1 вхождения; восстановление
# из памяти с md5-паспортом; RESTORE-FAIL должен быть 0.
#
# Запуск: python3 scripts/doclog2cert/mutations.py [M01 M02 ... | all]
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROTO_DIR = Path(__file__).resolve().parent / "protocols"

RS = "apps/api/report_snapshot.py"
SB = "apps/api/snapshot_builder.py"
RR = "apps/api/research_runs.py"
SD = "apps/api/storage_diagnostics.py"

# (id, file, old, new, zone)
MUTANTS = [
    # ── report_snapshot.py: контракт и cutoff ──
    ("M01", RS,
     'return bool(isinstance(value, str) and SNAPSHOT_ID_PATTERN.match(value))',
     'return bool(isinstance(value, str) and value.startswith("rs-"))',
     "is_valid_snapshot_id ослаблен"),
    ("M02", RS,
     'return "rs-" + uuid.uuid4().hex',
     'return "rs-" + uuid.uuid4().hex[:31]',
     "new_snapshot_id: 31 hex вместо 32"),
    ("M03", RS,
     'if code not in resolved:\n            resolved.append(code)',
     'resolved.append(code)',
     "resolve_kinds: дедупе снят"),
    ("M04", RS,
     '        if code not in resolved:\n            resolved.append(code)\n    return resolved',
     '        if code not in resolved:\n            resolved.append(code)\n    return sorted(resolved)',
     "resolve_kinds: порядок запроса -> sorted"),
    ("M05", RS,
     'if not isinstance(requested, (list, tuple)) or not requested:',
     'if not isinstance(requested, (list, tuple)):',
     "resolve_kinds: пустой список допустим"),
    ("M06", RS,
     'return "sha256:" + hashlib.sha256(content).hexdigest()',
     'return "sha256:" + ("0" * 64)',
     "knowledge_registry_version: константа"),
    ("M07", RS,
     '''        return SourceCutoff(
            last_sequence=(max(sequences) if sequences else 0),
            event_count=len(ordered),
            ordering_quality="canonical",
            event_id_manifest=None,
        )''',
     '''        return SourceCutoff(
            last_sequence=(max(sequences) if sequences else 0),
            event_count=len(ordered),
            ordering_quality="canonical",
            event_id_manifest=[str(e.get("event_id") or "") for e in ordered],
        )''',
     "canonical корпус несёт manifest (бережливость §18 снята)"),
    ("M08", RS,
     '''        return SourceCutoff(
            last_sequence=(max(sequences) if sequences else 0),
            event_count=len(ordered),
            ordering_quality="canonical",''',
     '''        return SourceCutoff(
            last_sequence=len(sequences),
            event_count=len(ordered),
            ordering_quality="canonical",''',
     "last_sequence = число событий (не max) в canonical"),
    ("M09", RS,
     'ordering_quality="legacy",',
     'ordering_quality="canonical",',
     "legacy корпус помечен canonical"),
    # ── report_snapshot.py: validity / модель ──
    ("M10", RS,
     'if ctx == target_context and rev == target_revision:',
     'if ctx == target_context or rev == target_revision:',
     "validity: and -> or"),
    ("M11", RS,
     '''if ctx is None and rev is None:
        return VALIDITY_UNKNOWN''',
     '''if ctx is None and rev is None:
        return VALIDITY_STALE''',
     "validity: отсутствие metadata -> stale"),
    ("M12", RS,
     '"approval": self.approval,\n        }',
     '"approval": self.approval,\n            "payload_sha256": self.payload_sha256,\n        }',
     "to_dict: registry-поле в канонических байтах"),
    ("M13", RS,
     '"claims": [dict(claim) for claim in section.get("claims", [])],',
     '"claims": list(section.get("claims", [])),',
     "copy(): неглубокие sections"),
    # ── report_snapshot.py: Memory-реестр ──
    ("M14", RS,
     '''existing = self._snapshots[existing_id]
                if existing.request_fingerprint != snapshot.request_fingerprint:
                    raise SnapshotIdempotencyConflictError(
                        "Тот же idempotency_key с другим телом запроса -- "
                        "конфликт без записи (AC09)"
                    )
                return existing.copy(), False''',
     '''existing = self._snapshots[existing_id]
                return existing.copy(), False''',
     "Memory register: fingerprint-конфликт снят"),
    ("M15", RS,
     '''def get_snapshot_record(self, snapshot_id: str) -> Optional[ReportSnapshot]:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
        return snapshot.copy() if snapshot is not None else None''',
     '''def get_snapshot_record(self, snapshot_id: str) -> Optional[ReportSnapshot]:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
        return snapshot if snapshot is not None else None''',
     "Memory get: живой объект вместо копии"),
    ("M16", RS,
     'records.sort(key=lambda item: (item.captured_at, item.snapshot_id))',
     'records = records[:]',
     "Memory list_records: сортировка снята"),
    # ── snapshot_builder.py: авторизация и согласованное чтение ──
    ("M17", SB,
     '''if not decision.allowed:
            raise SnapshotAccessDenied("Снимок недоступен")
        return run''',
     '''if decision.allowed:
            raise SnapshotAccessDenied("Снимок недоступен")
        return run''',
     "решающая таблица инвертирована"),
    ("M18", SB,
     '''run = get_research_run_store().get_run(run_id)
        if run is None:
            # Единый отказ без дисклоужения существования (uniform-404).
            raise SnapshotAccessDenied("Снимок недоступен")
        effective_subject = subject if subject is not None else SubjectRef.anonymous()
        decision = authorize_run_access(
            run, effective_subject, session_id=session_id, action=action
        )
        if not decision.allowed:
            raise SnapshotAccessDenied("Снимок недоступен")
        return run''',
     '''return get_research_run_store().get_run(run_id)''',
     "авторизация снята полностью (R09/T7)"),
    ("M19", SB,
     '''return (
            getattr(run, "context_id", None),
            getattr(run, "data_revision", None),
            getattr(run, "data_digest", None),
            getattr(run, "target_column", None),
        )''',
     '''return (
            getattr(run, "context_id", None),
            getattr(run, "data_digest", None),
            getattr(run, "target_column", None),
        )''',
     "_mirror_key: data_revision выпала из зеркала"),
    ("M20", SB,
     '''if existing.request_fingerprint != fingerprint:
                raise SnapshotIdempotencyConflictError(
                    "Тот же idempotency_key с другим телом запроса -- "
                    "конфликт без записи (AC09)"
                )
            return existing, False''',
     '''return existing, False''',
     "идемпотентный replay: конфликт тел снят"),
    ("M21", SB,
     '''effective_key = idempotency_key or (
            f"auto:{fingerprint[:16]}:{cutoff1.last_sequence}:"
            f"{cutoff1.event_count}:{cutoff1.ordering_quality}"
        )''',
     '''effective_key = idempotency_key or (f"auto:{fingerprint[:16]}")''',
     "авто-ключ без cutoff (новая заморозка не рождается)"),
    ("M22", SB,
     '''run2 = self._read_run(run_id)
        cutoff2 = build_source_cutoff(self._read_events(run_id))
        if self._mirror_key(run1) != self._mirror_key(run2) or (
            cutoff1.stability_key() != cutoff2.stability_key()
        ):
            raise SnapshotConflictError(
                "Состояние запуска изменилось между чтениями -- 409/"
                "retry, смешанный документ не собирается"
            )''',
     '''run2 = self._read_run(run_id)''',
     "второе чтение/сверка сняты (AC02/T13)"),
    # ── snapshot_builder.py: reproducibility / pins / целостность / D08 ──
    ("M23", SB,
     '''if data_ref is None:
            reasons.append("missing_data_artifact")''',
     '''if data_ref is None and False:
            reasons.append("missing_data_artifact")''',
     "reproducibility: missing_data_artifact снят"),
    ("M24", SB,
     'if dep["ref_kind"] in (REF_KIND_ARTIFACT, REF_KIND_CHECKPOINT)',
     'if dep["ref_kind"] in (REF_KIND_ARTIFACT,)',
     "pins: checkpoint-зависимости не пинятся"),
    ("M25", SB,
     '''if record.payload_sha256:
            actual = hashlib.sha256(data).hexdigest()
            if actual != record.payload_sha256:''',
     '''if False:
            actual = hashlib.sha256(data).hexdigest()
            if actual != record.payload_sha256:''',
     "_load_content: payload_sha256-гейт снят (T16)"),
    ("M26", SB,
     'if isinstance(horizon, int) and not isinstance(horizon, bool):',
     'if isinstance(horizon, int):',
     "D08: bool-горизонт проходит как int"),
    # ── storage_diagnostics.py / research_runs.py ──
    ("M27", SD,
     'registry = peek_snapshot_registry()\n    backend = "not_initialized" if registry is None else',
     'registry = peek_snapshot_registry()\n    backend = "memory" if registry is None else',
     "health: not_initialized фабрикуется"),
    ("M28", RR,
     '''        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (run_id, idempotency_key)
    )
    """,''',
     '''        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    )
    """,''',
     "каталог 0008: UNIQUE(run_id, idempotency_key) снят"),
    # ── no-op контролы (должны остаться ALIVE) ──
    ("CTL1", RS,
     "# ── Ошибки контура ───────────────────────────────────────────────────",
     "# ── Ошибки контура (ctl) ─────────────────────────────────────────────",
     "no-op: комментарий"),
    ("CTL2", SB,
     '"""Фасад сборки снимков: авторизация + согласованное чтение +',
     '"""Фасад сборки снимков: авторизация + согласованное  чтение +',
     "no-op: пробел в docstring"),
    ("CTL3", SB,
     'horizon = payload.get("horizon")',
     'horizon = payload.get("horizon", None)',
     "no-op: .get с дефолтом None"),
]

REPO_SUITE = ["tests/api/test_doclog2_snapshots.py"]
ORACLE_DIR = "scripts/doclog2cert"
ORACLE_DESELECT = [
    "scripts/doclog2cert/test_doclog2cert_oracle_unit.py::TestOrcPostgresMirror::test_register_then_get_roundtrip",
    "scripts/doclog2cert/test_doclog2cert_oracle_unit.py::TestOrcPostgresMirror::test_find_idempotent_returns_existing_with_same_fingerprint",
    "scripts/doclog2cert/test_doclog2cert_oracle_unit.py::TestOrcPostgresMirror::test_conflict_replay_path_raises_409_semantics",
]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run(cmd: list[str]) -> tuple[int, str]:
    env = dict(os.environ)
    for var in ("DATABASE_URL", "CISSTAT_API_KEYS",
                "CISSTAT_SNAPSHOTS_BACKEND", "CISSTAT_ARTIFACTS_BACKEND",
                "CISSTAT_RUNS_BACKEND", "CISSTAT_STORAGE_MODE"):
        env.pop(var, None)
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          env=env, timeout=600)
    return proc.returncode, proc.stdout[-3000:] + proc.stderr[-1500:]


def pytest_exit_code(output: str) -> int:
    for line in output.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            if line.strip().startswith("="):
                return 0 if (" failed" not in line and " error" not in line) else 1
    return 1 if "FAILED" in output or "ERROR" in output else 0


def main() -> int:
    selected = sys.argv[1:] or ["all"]
    ids = [m[0] for m in MUTANTS] if selected == ["all"] else selected
    unknown = [i for i in ids if i not in {m[0] for m in MUTANTS}]
    if unknown:
        print(json.dumps({"error": f"unknown mutants: {unknown}"}))
        return 2

    targets = {m[1] for m in MUTANTS if m[0] in ids}
    passports_before = {t: md5(REPO / t) for t in targets}
    backups = {t: (REPO / t).read_bytes() for t in targets}

    # baseline каналов на чистом дереве
    rc_repo, out_repo = run(
        [sys.executable, "-m", "pytest", *REPO_SUITE, "-q", "-p", "no:cacheprovider"])
    rc_orc, out_orc = run(
        [sys.executable, "-m", "pytest", ORACLE_DIR, "-q", "-p", "no:cacheprovider"]
        + sum([["--deselect", d] for d in ORACLE_DESELECT], []))
    baseline = {"repo_green": rc_repo == 0, "oracle_green": rc_orc == 0,
                "repo_tail": out_repo.strip().splitlines()[-1:] ,
                "oracle_tail": out_orc.strip().splitlines()[-1:]}
    if not (baseline["repo_green"] and baseline["oracle_green"]):
        print(json.dumps({"error": "baseline not green", **baseline},
                         ensure_ascii=False))
        return 2

    results = []
    for mut_id, rel, old, new, zone in MUTANTS:
        if mut_id not in ids:
            continue
        path = REPO / rel
        src = path.read_text("utf-8")
        count = src.count(old)
        if count != 1:
            results.append({"id": mut_id, "status": "HARNESS-FAIL",
                            "detail": f"occurrences={count}"})
            path.write_bytes(backups[rel])
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        rc1, _ = run([sys.executable, "-m", "pytest", *REPO_SUITE, "-q",
                      "-p", "no:cacheprovider"])
        rc2, _ = run([sys.executable, "-m", "pytest", ORACLE_DIR, "-q",
                      "-p", "no:cacheprovider"]
                     + sum([["--deselect", d] for d in ORACLE_DESELECT], []))
        # восстановление + паспорт
        path.write_bytes(backups[rel])
        restored = md5(path) == passports_before[rel]
        is_control = mut_id.startswith("CTL")
        if is_control:
            status = "CONTROL-ALIVE" if (rc1 == 0 and rc2 == 0) else "CONTROL-DIED"
        else:
            repo_killed = rc1 != 0
            oracle_killed = rc2 != 0
            if repo_killed and oracle_killed:
                status = "DUAL-KILLED"
            elif repo_killed:
                status = "REPO-ONLY"
            elif oracle_killed:
                status = "ORACLE-ONLY"
            else:
                status = "SURVIVED"
        results.append({
            "id": mut_id, "file": rel, "zone": zone,
            "status": status, "restored": restored,
            "repo_rc": rc1, "oracle_rc": rc2,
        })
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    # финальный паспорт дерева
    final_md5 = {t: md5(REPO / t) for t in targets}
    tree_ok = final_md5 == passports_before
    git_diff = run(["git", "diff", "--stat", "--", *targets])[1].strip()
    protocol = {
        "baseline": baseline,
        "results": results,
        "tree_restored": tree_ok,
        "git_diff_empty": git_diff == "",
        "summary": {
            "total": len(results),
            "killed": sum(1 for r in results
                          if r["status"].endswith("KILLED")),
            "survived": sum(1 for r in results if r["status"] == "SURVIVED"),
            "controls_alive": sum(1 for r in results
                                  if r["status"] == "CONTROL-ALIVE"),
            "restore_fail": sum(1 for r in results if not r.get("restored", True)),
        },
    }
    PROTO_DIR.mkdir(exist_ok=True)
    (PROTO_DIR / "mutations_protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(protocol["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
