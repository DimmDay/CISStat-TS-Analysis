# scripts/doclogcert/mutations.py
"""DOCLOG-CERT: мутационная кампания «мутанты на своих мутантах».

Двухканальная схема (прецедент DOCLOG-3…8-CERT):
- REPO-канал: tests/api/test_doclog0..9 (полная doclog-поверхность);
- ORACLE-канал: scripts/doclogcert (сквозные оракулы на своих данных).

Классификация: DUAL-KILLED / ORACLE-ONLY / REPO-ONLY / SURVIVED.
Мета-валидация: MV1 (сухой прогон якорей), MV2 (self-test классификатора),
MV3 (md5-восстановление после каждого мутанта), MV4 (контроли ALIVE),
MV5 (скан хвостов киллов на посторонние файлы).

Запуск:  python -m scripts.doclogcert.mutations dry
         python -m scripts.doclogcert.mutations run [M01 M02 ...]
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Средовая гигиена: песочный DATABASE_URL (файл-СУБД песочницы) не
# должен включать durable-путь doclog-контура.
os.environ.pop("DATABASE_URL", None)

SNAPSHOT = "apps/api/snapshot_builder.py"
REG_SNAP = "apps/api/report_snapshot.py"
JOBS = "apps/api/document_jobs.py"
REND = "apps/api/document_renditions.py"
LIFE = "apps/api/document_lifecycle.py"
WORKER = "apps/api/document_render_worker.py"
TELEMETRY = "apps/api/telemetry.py"
AUDIT = "apps/api/security_audit.py"
MONITORING = "apps/api/monitoring.py"
ADMINLOGS = "apps/api/admin_logs.py"
PROFILES = "apps/api/doc_profiles.py"
IDENTITY = "apps/api/identity.py"
DOC_ROUTER = "apps/api/routers/documentation.py"
LOGS_ROUTER = "apps/api/routers/logs.py"

REPO_TARGETS = [
    "tests/api/test_doclog0_identity.py",
    "tests/api/test_doclog1_artifacts.py",
    "tests/api/test_doclog2_snapshots.py",
    "tests/api/test_doclog3_telemetry_audit.py",
    "tests/api/test_doclog4_document_delivery.py",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog6_approvals_archive.py",
    "tests/api/test_doclog7_logs_support.py",
    "tests/api/test_doclog8_monitoring.py",
    "tests/api/test_doclog9_profiles.py",
]
ORACLE_TARGETS = ["scripts/doclogcert"]

PY = sys.executable

# ── Боевые мутанты и контроли ────────────────────────────────────────
# (id, файл, якорь, замена, описание)

MUTANTS: list[dict] = [
    # -- Снимок (AC02/AC03/AC09) --
    dict(id="M01", file=REG_SNAP,
         find="""            if existing_id is not None:
                existing = self._snapshots[existing_id]
                if existing.request_fingerprint != snapshot.request_fingerprint:""",
         replace="""            if existing_id is not None:
                existing = self._snapshots[existing_id]
                if False:""",
         desc="конфликт идемпотентности снимка выключен (AC09 off)"),
    dict(id="M02", file=SNAPSHOT,
         find="knowledge_version=knowledge_registry_version(),",
         replace="knowledge_version=None,",
         desc="версия реестра знаний не пинится в снимок (AC03 off)"),
    # -- Выдача (AC09/AC16) --
    dict(id="M03", file=JOBS,
         find="""        if (
            existing is not None
            and existing.state == RENDITION_READY""",
         replace="""        if (
            False
            and existing.state == RENDITION_READY""",
         desc="повтор готовой цели плодит новый job (AC09 off)"),
    dict(id="M04", file=REND,
         find='_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")',
         replace='_CSV_FORMULA_PREFIXES = ()',
         desc="CSV formula-injection выключен (AC16 off)"),
    dict(id="M05", file=REND,
         find="    escaped = _html.escape(str(value), quote=True)",
         replace="    escaped = str(value)",
         desc="HTML-экранирование выключено (AC16 off)"),
    dict(id="M06", file=REND,
         find='        "data_included": False,',
         replace='        "data_included": True,',
         desc="evidence ZIP лжёт о включении данных (§7 off)"),
    # -- Согласование (AC07) --
    dict(id="M07", file=LIFE,
         find="if approval_policy() == POLICY_TWO_PERSON:",
         replace="if False:",
         desc="two_person policy выключена (самоутверждение разрешено)"),
    dict(id="M08", file=LIFE,
         find="""        if expected_snapshot_sha256 is not None and (
            expected_snapshot_sha256 != current_hash
        ):""",
         replace="""        if False:""",
         desc="bound-hash при approve выключен (AC07 off)"),
    dict(id="M09", file=LIFE,
         find="""        state = self.revision_state(revision_id)
        if state in (STATE_DRAFT, STATE_READY_FOR_REVIEW):
            raise PublishRequiresApprovalError(""",
         replace="""        state = self.revision_state(revision_id)
        if False:
            raise PublishRequiresApprovalError(""",
         desc="publish без согласования разрешён (AC07 off)"),
    dict(id="M10", file=LIFE,
         find="""        from apps.api.security_audit import record_mandatory

        record_mandatory(""",
         replace="""        from apps.api.security_audit import record_standard as record_mandatory

        record_mandatory(""",
         desc="mandatory audit заменён best-effort standard (AC11 off)"),
    dict(id="M27", file=LIFE,
         find="""        if current_hash != approval.snapshot_payload_sha256:
            raise ApprovalNotApplicableError(""",
         replace="""        if False:
            raise ApprovalNotApplicableError(""",
         desc="перепроверка bound-hash при publish выключена (AC07 off)"),
    # -- Worker (AC08) --
    dict(id="M11", file=WORKER,
         find="""            if expires is None or expires >= now:
                continue
            registry.update_job(""",
         replace="""            if False:
                continue
            registry.update_job(""",
         desc="реклейм трогает ЖИВЫЕ lease (AC09 off)"),
    # -- Telemetry/Audit (AC11) --
    dict(id="M12", file=TELEMETRY,
         find="""        self.inc("telemetry_sink_failures_total")
        if not raised:
            self.inc("telemetry_dropped_total")
            return""",
         replace="""        self.inc("telemetry_sink_failures_total")
        if not raised:
            return""",
         desc="потеря записи телеметрии невидима (AC11 off)"),
    dict(id="M13", file=AUDIT,
         find="""    if not delivered:
        _inc("audit_dropped_total")
        raise MandatoryAuditFailure(""",
         replace="""    if False:
        _inc("audit_dropped_total")
        raise MandatoryAuditFailure(""",
         desc="mandatory audit fail-open при отказе sink (AC11 off)"),
    # -- Мониторинг (AC12/AC15/§6.1) --
    dict(id="M14", file=MONITORING,
         find="""        else:
            # Незрелый горизонт: НЕ нулевая ошибка -- явное исключение.
            excluded_labels.append(date)""",
         replace="""        else:
            excluded_labels.append(date)
            pairs.append({"date": date, "forecast_value": forecast_value,
                          "actual_value": 0.0,
                          "signed_error": -forecast_value,
                          "absolute_error": abs(forecast_value),
                          "ape": None,
                          "ape_undefined_reason": "actual_zero",
                          "interval_hit": None})""",
         desc="§6.1 off: незрелый горизонт получает нулевую ошибку"),
    dict(id="M15", file=MONITORING,
         find='''            mape = None
            mape_reason = "mape_undefined_actual_zero"''',
         replace='''            mape = 0.0
            mape_reason = None''',
         desc="MAPE фабрикуется в 0 при нулевом факте (AC12 off)"),
    dict(id="M16", file=MONITORING,
         find='''        elif forecast_units_text == batch.units:
            units_check = "as_is"''',
         replace='''        elif True:
            units_check = "as_is"''',
         desc="units mismatch молча принимается как as_is (AC15 off)"),
    # -- Журналы/гранты (§15.1/AC06) --
    dict(id="M17", file=ADMINLOGS,
         find="""        unknown = [s for s in scopes if s not in GRANT_SCOPES]
        if unknown:""",
         replace="""        unknown = [s for s in scopes if s not in GRANT_SCOPES]
        if False:""",
         desc="whitelist scopes грантов открыт (fail-open)"),
    dict(id="M18", file=ADMINLOGS,
         find="if ttl <= 0 or ttl > GRANT_TTL_MAX_HOURS:",
         replace="if False:",
         desc="TTL-граница грантов выключена"),
    dict(id="M19", file=ADMINLOGS,
         find="""    if not access.export:
        raise LogsAccessDenied("logs.export отсутствует")""",
         replace="""    if False:
        raise LogsAccessDenied("logs.export отсутствует")""",
         desc="экспорт журналов без права (§15.1 off)"),
    dict(id="M24", file=LOGS_ROUTER,
         find="""    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",""",
         replace="""    record_standard(
        "audit_log_accessed_renamed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",""",
         desc="саможурналирование ломается (действие вне каталога)"),
    # -- Профили организации (DOCLOG-9) --
    dict(id="M20", file=PROFILES,
         find="""    if findings:
        return ValidationResult(PDFA_VALIDATOR, "failed", findings)""",
         replace="""    if False:
        return ValidationResult(PDFA_VALIDATOR, "failed", findings)""",
         desc="валидатор PDF/A всегда passed («по имени файла»)"),
    dict(id="M21", file=JOBS,
         find="""            if not org_profile_id:
                raise _dp.OrgProfileRequired(""",
         replace="""            if False:
                raise _dp.OrgProfileRequired(""",
         desc="безымянный выпуск PDF/A разрешён (§19 off)"),
    dict(id="M26", file=JOBS,
         find="""            if org_profile_id and existing.org_profile_id != org_profile_id:""",
         replace="""            if False:""",
         desc="mismatch профиля готовой цели тихо пропускается (§11 off)"),
    # -- Идентичность и роутеры (§15/AC06) --
    dict(id="M22", file=IDENTITY,
         find="""        if (
            subject.subject_id == getattr(run, "owner_subject", None)
            and subject.tenant_id == run_tenant
        ):""",
         replace="""        if True:""",
         desc="решающая таблица: чужой субъект получает owner-доступ"),
    dict(id="M23", file=DOC_ROUTER,
         find="""    if not decision.allowed:
        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND_DETAIL)""",
         replace="""    if not decision.allowed:
        raise HTTPException(status_code=403, detail=_RUN_NOT_FOUND_DETAIL)""",
         desc="uniform 404 -> 403 (дисклоужение существования)"),
    dict(id="M28", file=IDENTITY.replace("identity.py", "auth.py"),
         find="""        if subject_id is not None and subject_id == key:
            continue""",
         replace="""        if False:
            continue""",
         desc="T4 off: значение ключа принимается как идентичность"),
    # -- Контроли (no-op, обязаны остаться ALIVE) --
    dict(id="C1", file=MONITORING, control=True,
         find="# ── Ошибки контура (HTTP-маппинг -- routers/monitoring.py) ───────────",
         replace="# ── Ошибки контура (HTTP-маппинг -- routers/monitoring.py) ──────────",
         desc="контроль: комментарий без изменения семантики"),
    dict(id="C2", file=JOBS, control=True,
         find="def _new_id(prefix: str) -> str:",
         replace="def _new_id(prefix: str) -> str:  # noqa: E2C",
         desc="контроль: хвостовой комментарий"),
    dict(id="C3", file=REND, control=True,
         find="JSONL_SCHEMA_VERSION = \"doclog.rendition/1\"",
         replace="JSONL_SCHEMA_VERSION = \"doclog.rendition/1\"  # noqa: E2C",
         desc="контроль: хвостовой комментарий"),
]


def _apply(file_rel: str, find: str, replace: str) -> None:
    path = REPO_ROOT / file_rel
    source = path.read_text("utf-8")
    assert source.count(find) == 1, f"anchor not unique in {file_rel}"
    path.write_text(source.replace(find, replace, 1), "utf-8")


def _md5(file_rel: str) -> str:
    return hashlib.md5((REPO_ROOT / file_rel).read_bytes()).hexdigest()


def _failed_ids(stdout: str) -> list[str]:
    ids = []
    for line in stdout.splitlines():
        if (line.startswith("FAILED ") or line.startswith("ERROR ")) and "::" in line:
            ids.append(line.split()[1])
    return ids


# Известный средовый флак (класс N2 DOCLOG-6-CERT, повторён в
# DOCLOG-7/8-CERT): byte-determinism XLSX в комбинированном прогоне
# эпизодически расходится вне зависимости от мутанта. Протокол: если
# единственные FAILED-ID канала -- флак-класс, канал перезапускается
# ОДИН раз; классификация -- по повторному прогону.
KNOWN_FLAKEY = {
    "tests/api/test_doclog5_formats_worker.py::"
    "TestXlsxRender::test_xlsx_five_sheets_and_determinism",
}


def _run_channel_deflaked(targets: list[str], label: str,
                          timeout: int = 900) -> dict:
    first = _run_channel(targets, timeout=timeout)
    if first["exit"] == 0:
        return first
    failed = set(_failed_ids(first["stdout"]))
    if failed and failed <= KNOWN_FLAKEY:
        second = _run_channel(targets, timeout=timeout)
        second["deflake_rerun"] = True
        second["first_tail"] = first["tail"]
        print(f"    [{label}] де-флак: {sorted(failed)} -> "
              f"повторный прогон exit={second['exit']}", flush=True)
        return second
    return first


def _run_channel(targets: list[str], timeout: int = 900) -> dict:
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=timeout)
    return {
        "cmd": " ".join(cmd),
        "exit": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "tail": "\n".join(proc.stdout.strip().splitlines()[-14:]),
        "stdout": proc.stdout,
    }


def classify(repo: dict, oracle: dict) -> str:
    repo_killed = repo["exit"] != 0
    oracle_killed = oracle["exit"] != 0
    if repo_killed and oracle_killed:
        return "DUAL-KILLED"
    if oracle_killed:
        return "ORACLE-ONLY"
    if repo_killed:
        return "REPO-ONLY"
    return "SURVIVED"


def mv1_dry_run() -> list[str]:
    """MV1: каждый якорь встречается в своём файле РОВНО один раз."""
    problems: list[str] = []
    for mutant in MUTANTS:
        source = (REPO_ROOT / mutant["file"]).read_text("utf-8")
        count = source.count(mutant["find"])
        if count != 1:
            problems.append(
                f"{mutant['id']}: anchor count {count} in {mutant['file']}"
            )
    return problems


def self_test_classifier() -> bool:
    """MV2: классификатор сверен с синтетикой."""
    cases = [
        ({"exit": 1}, {"exit": 1}, "DUAL-KILLED"),
        ({"exit": 0}, {"exit": 1}, "ORACLE-ONLY"),
        ({"exit": 1}, {"exit": 0}, "REPO-ONLY"),
        ({"exit": 0}, {"exit": 0}, "SURVIVED"),
    ]
    for repo, oracle, expected in cases:
        if classify(repo, oracle) != expected:
            return False
    return True


def run_campaign(only: list[str] | None = None) -> dict:
    started = time.time()
    baseline_files = {m["file"] for m in MUTANTS}
    baseline_md5 = {f: _md5(f) for f in sorted(baseline_files)}
    summary: list[dict] = []
    protocols_dir = Path(__file__).resolve().parent / "protocols"
    protocols_dir.mkdir(exist_ok=True)

    for mutant in MUTANTS:
        mid = mutant["id"]
        if only and mid not in only:
            continue
        entry = {
            "id": mid,
            "file": mutant["file"],
            "desc": mutant["desc"],
            "control": bool(mutant.get("control")),
        }
        try:
            _apply(mutant["file"], mutant["find"], mutant["replace"])
        except AssertionError as exc:
            entry.update(status="PATCH-FAIL", error=str(exc))
            summary.append(entry)
            print(f"[{mid}] PATCH-FAIL: {exc}")
            continue
        try:
            repo = _run_channel_deflaked(REPO_TARGETS, mid)
            oracle = _run_channel_deflaked(ORACLE_TARGETS, mid)
        finally:
            # MV3: байт-в-байт восстановление из HEAD (git checkout --).
            subprocess.run(["git", "checkout", "--", mutant["file"]],
                           cwd=REPO_ROOT, capture_output=True, text=True)
            restored = _md5(mutant["file"])
            entry["restore_ok"] = restored == baseline_md5[mutant["file"]]
        entry["repo_exit"] = repo["exit"]
        entry["oracle_exit"] = oracle["exit"]
        entry["repo_seconds"] = repo["seconds"]
        entry["oracle_seconds"] = oracle["seconds"]
        entry["repo_tail"] = repo["tail"]
        entry["oracle_tail"] = oracle["tail"]
        if mutant.get("control"):
            entry["status"] = "ALIVE" if (repo["exit"] == 0
                                          and oracle["exit"] == 0) \
                else "CONTROL-KILLED"
        else:
            entry["status"] = classify(repo, oracle)
        summary.append(entry)
        print(f"[{mid}] {entry['status']} "
              f"(repo {repo['exit']}, oracle {oracle['exit']}) "
              f"{mutant['desc']}", flush=True)
        (protocols_dir / f"mut_{mid}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), "utf-8"
        )

    # Мердж с предыдущими порциями (среда обрывает долгие фоновые
    # процессы -- кампания идёт порциями с накоплением протокола).
    summary_path = protocols_dir / "mutations_summary.json"
    if summary_path.exists() and only:
        try:
            previous = json.loads(summary_path.read_text())
            known = {e["id"] for e in summary}
            summary = [
                e for e in previous.get("mutants", [])
                if e["id"] not in known
            ] + summary
        except Exception:
            pass
    summary.sort(key=lambda e: e["id"])

    # MV5: скан хвостов киллов на посторонние файлы (ложные киллы).
    channel_files = {
        "repo": {Path(p).name for p in REPO_TARGETS},
        "oracle": {Path(p).name for p in ORACLE_TARGETS}
        | {"conftest.py", "test_e2cert_oracle_unit.py",
           "test_e2cert_oracle_api.py", "test_e2cert_oracle_static.py"},
    }
    tail_scan = []
    for entry in summary:
        if entry.get("control") or entry["status"] in ("ALIVE",
                                                       "PATCH-FAIL"):
            continue
        for channel in ("repo", "oracle"):
            tail = entry.get(f"{channel}_tail", "")
            for line in tail.splitlines():
                if ((line.startswith("FAILED") or line.startswith("ERROR"))
                        and "::" in line):
                    path_part = line.split()[1].split("::")[0]
                    fname = Path(path_part).name
                    if fname not in channel_files[channel]:
                        tail_scan.append(
                            {"id": entry["id"], "channel": channel,
                             "foreign": fname}
                        )
    result = {
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.time() - started, 1),
        "mv2_classifier_self_test": self_test_classifier(),
        "mv3_all_restored": all(
            e.get("restore_ok", False) for e in summary
            if e.get("status") != "PATCH-FAIL"
        ),
        "mv5_foreign_tails": tail_scan,
        "mutants": summary,
    }
    (protocols_dir / "mutations_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), "utf-8"
    )
    return result


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry"
    if mode == "dry":
        problems = mv1_dry_run()
        print(f"MV1 anchors: {len(MUTANTS) - len(problems)}/"
              f"{len(MUTANTS)} OK")
        for problem in problems:
            print("  PROBLEM:", problem)
        print("MV2 classifier self-test:",
              "PASS" if self_test_classifier() else "FAIL")
        sys.exit(1 if problems else 0)
    elif mode == "run":
        only = sys.argv[2:] or None
        result = run_campaign(only)
        counts: dict[str, int] = {}
        for entry in result["mutants"]:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        print("MV3 all restored:", result["mv3_all_restored"])
        print("MV5 foreign tails:", result["mv5_foreign_tails"] or "none")
