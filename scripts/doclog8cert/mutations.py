# scripts/doclog8cert/mutations.py
"""DOCLOG-8-CERT: мутационная кампания «мутанты на своих мутантах».

Двухканальная схема (прецедент DOCLOG-7-CERT):
- REPO-канал: tests/api/test_doclog8_monitoring.py + test_doclog2_snapshots.py
  + test_doclog6_approvals_archive.py (185 тестов -- поверхность DOCLOG-8
  и фундаментальные пины каталогов/publish-политики);
- ORACLE-канал: scripts/doclog8cert (77 оракулов на своих данных).

Классификация: DUAL-KILLED / ORACLE-ONLY / REPO-ONLY / SURVIVED.
Мета-валидация: MV1 (сухой прогон якорей), MV2 (self-test классификатора),
MV3 (md5-восстановление после каждого мутанта), MV4 (контроли ALIVE),
MV5 (скан хвостов киллов на посторонние файлы).

Запуск:  /home/z/.venv/bin/python -m scripts.doclog8cert.mutations dry
         /home/z/.venv/bin/python -m scripts.doclog8cert.mutations run
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MONITORING = "apps/api/monitoring.py"
ROUTER = "apps/api/routers/monitoring.py"
SNAPSHOT = "apps/api/snapshot_builder.py"

REPO_TARGETS = [
    "tests/api/test_doclog8_monitoring.py",
    "tests/api/test_doclog2_snapshots.py",
    "tests/api/test_doclog6_approvals_archive.py",
]
ORACLE_TARGETS = ["scripts/doclog8cert"]

PY = sys.executable

# ── Боевые мутанты и контроли ────────────────────────────────────────
# (id, файл, якорь, замена, описание)

MUTANTS: list[dict] = [
    # -- Единицы (AC15) --
    dict(id="M01", file=MONITORING,
         find='''        elif forecast_units_text == batch.units:
            units_check = "as_is"''',
         replace='''        elif True:
            units_check = "as_is"''',
         desc="units mismatch молча принимается как as_is (AC15 off)"),
    dict(id="M02", file=MONITORING,
         find="actual_value = actual_by_period[date] * float(units_factor)",
         replace="actual_value = actual_by_period[date]",
         desc="фактор конверсии единиц игнорируется"),
    dict(id="M26", file=MONITORING,
         find='''        if forecast_units_text is None:
            units_check = "unknown"''',
         replace='''        if forecast_units_text is None:
            units_check = "as_is"''',
         desc="честное unknown единиц фабрикуется как as_is"),
    dict(id="M29", file=MONITORING,
         find="if source_kind not in SOURCE_KINDS:",
         replace="if False:",
         desc="каталог source_kind открыт (fail-open)"),
    # -- Целостность прогноза (T8) и границы (T7/T15) --
    dict(id="M03", file=MONITORING,
         find="if artifact_content_sha256(raw) != artifact.payload_sha256:",
         replace="if False:",
         desc="T8-проверка sha256 байтов прогноза выключена"),
    dict(id="M04", file=MONITORING,
         find="if artifact.run_id != str(run_id):",
         replace="if False:",
         desc="чужой run-артефакт принимается (T7 off)"),
    dict(id="M05", file=MONITORING,
         find='if artifact.kind != "forecast":',
         replace="if False:",
         desc="kind-гейт прогноза выключен"),
    dict(id="M06", file=MONITORING,
         find="if batch is None or batch.run_id != str(run_id):",
         replace="if batch is None:",
         desc="run-граница партии факта выключена"),
    dict(id="M27", file=MONITORING,
         find="if not isinstance(points, list) or not points:",
         replace="if not isinstance(points, list):",
         desc="прогноз без точек принимается (пустая сверка)"),
    # -- Идемпотентность (§10.3/AC09) --
    dict(id="M07", file=MONITORING,
         find="""            existing = self.registry.find_comparison_idempotent(
                str(run_id), idempotency_key
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:""",
         replace="""            existing = self.registry.find_comparison_idempotent(
                str(run_id), idempotency_key
            )
            if existing is not None:
                if False:""",
         desc="конфликт идемпотентности сверок выключен (тихий дубль тела)"),
    dict(id="M08", file=MONITORING,
         find="""        if idempotency_key:
            existing = self.registry.find_actual_batch_idempotent(""",
         replace="""        if False:
            existing = self.registry.find_actual_batch_idempotent(""",
         desc="идемпотентный повтор партий отключён (дубли vintage)"),
    # -- Честные метрики (AC12) --
    dict(id="M09", file=MONITORING,
         find='''            mape = None
            mape_reason = "mape_undefined_actual_zero"''',
         replace='''            mape = 0.0
            mape_reason = None''',
         desc="MAPE фабрикуется в 0 при нулевом факте (AC12 off)"),
    dict(id="M10", file=MONITORING,
         find='''                "mae": None,
                "mae_reason": "no_matured_horizons",''',
         replace='''                "mae": 0.0,
                "mae_reason": None,''',
         desc="нет зрелых горизонтов -- 0 вместо null+reason (AC12 off)"),
    dict(id="M11", file=MONITORING,
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
    dict(id="M12", file=MONITORING,
         find='''        if mase_scale is None:
            mase: Optional[float] = None
            mase_reason: Optional[str] = "mase_scale_required"''',
         replace='''        if mase_scale is None:
            mase: Optional[float] = mae
            mase_reason: Optional[str] = None''',
         desc="MASE фабрикуется из MAE без явного scale"),
    dict(id="M13", file=MONITORING,
         find="if defined_hits == matured_count:",
         replace="if True:",
         desc="покрытие интервала считается при неполных границах"),
    dict(id="M25", file=MONITORING,
         find='        "out_of_horizon_labels": out_of_horizon_labels,',
         replace='        "out_of_horizon_labels": [],',
         desc="факты вне горизонта скрываются"),
    dict(id="M28", file=MONITORING,
         find="parsed = datetime.fromisoformat(text)",
         replace="parsed = datetime.now(timezone.utc)",
         desc="as_of fail-open: мусорная дата тихо заменяется на now"),
    # -- Порог и решения (§6.1) --
    dict(id="M14", file=MONITORING,
         find='                "status": "not_evaluable",',
         replace='                "status": "within",',
         desc="not_evaluable фабрикуется как within"),
    dict(id="M15", file=MONITORING,
         find='metric_aggregate >= float(threshold.get("value"))',
         replace='metric_aggregate > float(threshold.get("value"))',
         desc="оператор >= тихо сужен до >"),
    dict(id="M16", file=MONITORING,
         find='        "decision_action": None,',
         replace='''        "decision_action": (threshold_result or {}).get("status"),''',
         desc="§6.1 off: автопереобучение следует из статуса порога"),
    dict(id="M17", file=MONITORING,
         find="if action_text not in DECISION_ACTIONS:",
         replace="if False:",
         desc="каталог действий решений открыт (fail-open)"),
    dict(id="M18", file=MONITORING,
         find="        rationale_text = str(rationale or \"\").strip()\n"
              "        if not rationale_text:",
         replace="        rationale_text = str(rationale or \"\").strip()\n"
                 "        if False:",
         desc="основание решения перестаёт быть обязательным"),
    dict(id="M19", file=MONITORING,
         find="if record is None or record.run_id != str(run_id):\n"
              "            raise MonitoringNotFoundError(\n"
              '                f"Сверка {comparison_id!r} не найдена в границах run -- "\n'
              '                "решение не может ссылаться на чужую сверку"\n'
              "            )",
         replace="if record is None:\n"
                 "            raise MonitoringNotFoundError(\n"
                 '                f"Сверка {comparison_id!r} не найдена в границах run -- "\n'
                 '                "решение не может ссылаться на чужую сверку"\n'
                 "            )",
         desc="решение ссылается на чужую сверку (run-граница off)"),
    dict(id="M20", file=MONITORING,
         find="            if period in seen_periods:\n"
              "                raise MonitoringValidationError(",
         replace="            if False:\n"
                 "                raise MonitoringValidationError(",
         desc="дубликаты периодов внутри партии допускаются"),
    dict(id="M21", file=MONITORING,
         find="            if not _is_finite_number(raw_value):",
         replace="            if False:",
         desc="NaN/Infinity/bool в значениях факта допускаются"),
    # -- Аудит (§8) --
    dict(id="M22", file=MONITORING,
         find='            "monitoring_actual_registered",',
         replace='            "monitoring_actual_registered_v2",',
         desc="аудит-действие регистрации вне каталога AUDIT_ACTIONS"),
    dict(id="M23", file=MONITORING,
         find="        except Exception:\n"
              "            # Standard-класс: сбой аудита не ломает научную операцию\n"
              "            # (§8/AC11: mandatory -- только защищённая выдача).\n"
              "            pass",
         replace="        except Exception:\n"
                 "            raise",
         desc="standard-аудит превращён в ломучий (§8 off)"),
    dict(id="M24", file=MONITORING,
         find="payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),",
         replace='payload_sha256="",',
         desc="payload_sha256 сверке не вычисляется"),
    # -- Роутер (§17) --
    dict(id="M30", file=ROUTER,
         find="        return JSONResponse(\n"
              "            status_code=404,\n"
              "            content={\n"
              "                **_RUN_NOT_FOUND_DETAIL,",
         replace="        return JSONResponse(\n"
                 "            status_code=403,\n"
                 "            content={\n"
                 "                **_RUN_NOT_FOUND_DETAIL,",
         desc="uniform 404 заменён на 403 (дисклоужение существования)"),
    dict(id="M31", file=ROUTER,
         find='status, code = 409, "monitoring_idempotency_conflict"',
         replace='status, code = 422, "monitoring_idempotency_conflict"',
         desc="конфликт идемпотентности 409 -> 422"),
    dict(id="M32", file=ROUTER,
         find='status, code = 422, "monitoring_validation_error"',
         replace='status, code = 422, "monitoring_bad_request"',
         desc="код 422-каталога изменён вне контракта"),
    dict(id="M33", file=ROUTER,
         find='status, code = 422, "monitoring_units_mismatch"',
         replace='status, code = 422, "monitoring_validation_error"',
         desc="units mismatch теряет собственный код (AC15)"),
    dict(id="M34", file=ROUTER,
         find='    return {"created": created, "batch": _batch_json(record)}',
         replace='    return {"created": not created, "batch": _batch_json(record)}',
         desc="флаг created инвертирован"),
    dict(id="M35", file=ROUTER,
         find='@router.post("/runs/{run_id}/monitoring/actuals", status_code=201)',
         replace='@router.post("/runs/{run_id}/monitoring/actuals")',
         desc="201 создание тихо становится 200"),
    # -- Снимок D12 (честные claims) --
    dict(id="M36", file=SNAPSHOT,
         find='                "версии (§6 D12); выпуск прогноза не переписывается.",\n'
              "                validity=VALIDITY_UNKNOWN,",
         replace='                "версии (§6 D12); выпуск прогноза не переписывается.",\n'
                 "                validity=VALIDITY_CURRENT,",
         desc="пустая секция D12 фабрикует current вместо unknown"),
    dict(id="M37", file=SNAPSHOT,
         find='''            def _fmt(value: Any) -> str:
                if value is None:
                    return "—"''',
         replace='''            def _fmt(value: Any) -> str:
                if value is None:
                    return "0"''',
         desc="отсутствующие агрегаты/решение фабрикуются как 0"),
    # -- Контроли (no-op, обязаны остаться ALIVE) --
    dict(id="C1", file=MONITORING, control=True,
         find="# ── Ошибки контура (HTTP-маппинг -- routers/monitoring.py) ───────────",
         replace="# ── Ошибки контура (HTTP-маппинг -- routers/monitoring.py) ──────────",
         desc="контроль: комментарий без изменения семантики"),
    dict(id="C2", file=ROUTER, control=True,
         find='router = APIRouter()',
         replace='router = APIRouter()  # d8cert no-op control',
         desc="контроль: хвостовой комментарий"),
    dict(id="C3", file=SNAPSHOT, control=True,
         find='    def _section_d12(self, ctx: _BuildCtx) -> dict[str, Any]:',
         replace='    def _section_d12(self, ctx: _BuildCtx) -> dict[str, Any]:  # noqa: D8C',
         desc="контроль: хвостовой комментарий сигнатуры"),
]


def _apply(file_rel: str, find: str, replace: str) -> None:
    path = REPO_ROOT / file_rel
    source = path.read_text("utf-8")
    assert source.count(find) == 1, f"anchor not unique in {file_rel}"
    path.write_text(source.replace(find, replace, 1), "utf-8")


def _md5(file_rel: str) -> str:
    return hashlib.md5((REPO_ROOT / file_rel).read_bytes()).hexdigest()


def _run_channel(targets: list[str], timeout: int = 600) -> dict:
    cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]
    started = time.time()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=timeout)
    return {
        "cmd": " ".join(cmd),
        "exit": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "tail": "\n".join(proc.stdout.strip().splitlines()[-12:]),
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
        before = _md5(mutant["file"])
        try:
            _apply(mutant["file"], mutant["find"], mutant["replace"])
        except AssertionError as exc:
            entry.update(status="PATCH-FAIL", error=str(exc))
            summary.append(entry)
            print(f"[{mid}] PATCH-FAIL: {exc}")
            continue
        try:
            repo = _run_channel(REPO_TARGETS)
            oracle = _run_channel(ORACLE_TARGETS)
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
              f"{mutant['desc']}")
        (protocols_dir / f"mut_{mid}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), "utf-8"
        )

    # MV5: скан хвостов киллов на посторонние файлы (ложные киллы).
    channel_files = {
        "repo": {Path(p).name for p in REPO_TARGETS},
        "oracle": {Path(p).name for p in ORACLE_TARGETS}
        | {"conftest.py", "test_d8cert_oracle_unit.py",
           "test_d8cert_oracle_api.py", "test_d8cert_oracle_static.py"},
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
