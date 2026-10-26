# scripts/doclogrecheckfixcert/mutations.py
"""
Каталог мутантов сертификации DOCLOG-E2E-RECHECK-1-FIX (аудит 9401fa5).

Каждый мутант -- одно целевое поведенческое изменение РЕАЛИЗАЦИИ FIX
(«свои мутанты»): 1-й порядок -- одиночные, 2-й порядок («мутанты на
своих мутантах») -- КОМПОЗИЦИИ пар из разных функций; оракулы -- repo-
корпус tests/api/test_doclog_recheck_fix.py + собственные оракулы
сертификатора scripts/doclogrecheckcert/* (свои данные/пробы).

Ожидания классифицированы заранее (двусторонне):
  KILL-CORPUS  -- убивает repo-корпус fix-задачи;
  KILL-CERT    -- убивает ТОЛЬКО собственным оракулом сертификатора
                  (ORACLE-ONLY: атрибуция одного файла-оракула);
  SURVIVED     -- предсказанно выживает (дублирующий слой
                  defense-in-depth); классифицируется честно, не
                  натягивается килл.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Mutant:
    mid: str
    file: str
    old: str
    new: str
    expectation: str  # KILL-CORPUS | KILL-CERT | SURVIVED (redundant)
    note: str = ""
    extra: list[tuple[str, str]] = field(default_factory=list)


# ── 1-й порядок: apps/api/promotion_integration.py ────────────────────
MUTANTS = [
    Mutant(
        mid="M01",
        file="apps/api/promotion_integration.py",
        old="""    try:
        artifact = _service().promote_passport(
            run_id,
            subject,
            session,
            session_id=session_id,
            stage=stage,
        )
        return artifact""",
        new="""    try:
        return None  # MUTANT M01: промоушен паспорта пропущен
        artifact = _service().promote_passport(
            run_id,
            subject,
            session,
            session_id=session_id,
            stage=stage,
        )
        return artifact""",
        expectation="KILL-CORPUS",
        note="C03: capture-промоушен паспорта отключён",
    ),
    Mutant(
        mid="M02",
        file="apps/api/promotion_integration.py",
        old="""    try:
        return _service().promote_validation_result(
            run_id,
            subject,
            session,
            session_id=session_id,
            result_payload=result_payload,
        )""",
        new="""    try:
        return None  # MUTANT M02: промоушен результата валидации пропущен
        return _service().promote_validation_result(
            run_id,
            subject,
            session,
            session_id=session_id,
            result_payload=result_payload,
        )""",
        expectation="KILL-CORPUS",
        note="C03: check-промоушен отключён",
    ),
    Mutant(
        mid="M03",
        file="apps/api/promotion_integration.py",
        old="""        return _service().promote_data_version(
            run_id,
            subject,
            session,
            session_id=session_id,
            dataframe_csv_bytes=csv_bytes,
            reason=reason,
        )""",
        new="""        return None  # MUTANT M03: первичная версия данных не продвигается
        return _service().promote_data_version(
            run_id,
            subject,
            session,
            session_id=session_id,
            dataframe_csv_bytes=csv_bytes,
            reason=reason,
        )""",
        expectation="KILL-CORPUS",
        note="C03: upload-версия данных отключена",
    ),
    Mutant(
        mid="M04",
        file="apps/api/promotion_integration.py",
        old="""        recipe_artifact = service.promote_correction_recipe(
            run_id,
            subject,
            session,
            session_id=session_id,
            node_id=node_id,
            operation=operation,
            recipe=recipe,
            data_version_artifact_id=getattr(
                data_artifact, "artifact_id", None
            ),
        )
        return recipe_artifact""",
        new="""        recipe_artifact = service.promote_correction_recipe(
            run_id,
            subject,
            session,
            session_id=session_id,
            node_id=node_id,
            operation=operation,
            recipe=recipe,
            data_version_artifact_id=None,  # MUTANT M04: связь разорвана
        )
        return recipe_artifact""",
        expectation="KILL-CORPUS",
        note="C03/§16: рецепт теряет зависимость от версии данных",
    ),
    Mutant(
        mid="M05",
        file="apps/api/promotion_integration.py",
        old="""        service = _service()
        data_artifact = service.promote_data_version(
            run_id,
            subject,
            session,
            session_id=session_id,
            dataframe_csv_bytes=csv_bytes,
            reason=reason or operation,
        )""",
        new="""        service = _service()
        data_artifact = None  # MUTANT M05: версия данных apply не пишется""",
        expectation="KILL-CORPUS",
        note="C03: apply-версия данных отключена (рецепт без данных)",
    ),
    Mutant(
        mid="M06",
        file="apps/api/promotion_integration.py",
        old="""    try:
        from apps.api.security_audit import record_standard

        record_standard(
            "artifact_promotion_failed",""",
        new="""    try:
        from apps.api.security_audit import record_standard

        return  # MUTANT M06: durable-receipt сбоя не записывается
        record_standard(
            "artifact_promotion_failed",""",
        expectation="KILL-CORPUS",
        note="C03: честный receipt сбоя отключён",
    ),
    Mutant(
        mid="M07",
        file="apps/api/promotion_integration.py",
        old="""                producer_key = f"{key_prefix}:{entry_id}"
                if service.find_by_producer(run_id, producer_key) is not None:
                    continue  # идемпотентность: уже продвинут""",
        new="""                producer_key = f"{key_prefix}:{entry_id}"
                if False:  # MUTANT M07: идемпотентный пропуск отключён
                    continue""",
        expectation="KILL-CERT",
        note="C03: счётчики повторного sweep врут (не нули)",
    ),
    Mutant(
        mid="M08",
        file="apps/api/promotion_integration.py",
        old="""    counts = {"oof_backtest": 0, "model_card": 0, "forecast": 0}
    artifacts = getattr(session, "modeling_artifacts", None) or {}""",
        new="""    counts = {"oof_backtest": 0, "model_card": 0, "forecast": 0}
    return counts  # MUTANT M08: sweep-промоушен отключён целиком
    artifacts = getattr(session, "modeling_artifacts", None) or {}""",
        expectation="KILL-CERT",
        note="C03: backtest/card/forecast не продвигаются",
    ),
    # ── 1-й порядок: apps/api/snapshot_builder.py ────────────────────
    Mutant(
        mid="M09",
        file="apps/api/snapshot_builder.py",
        old="""        validity = _event_context_validity(
            event.get("context_id"), ctx.target_ctx
        )""",
        new="""        validity = VALIDITY_CURRENT  # MUTANT M09: всегда current (регресс C04)""",
        expectation="KILL-CORPUS",
        note="C04: исторические события снова current",
    ),
    Mutant(
        mid="M10",
        file="apps/api/snapshot_builder.py",
        old="""        validity = _event_context_validity(
            event.get("context_id"), ctx.target_ctx
        )""",
        new="""        validity = VALIDITY_UNKNOWN  # MUTANT M10: всегда unknown""",
        expectation="KILL-CORPUS",
        note="C04/I4: факт текущего контекста теряет current",
    ),
    Mutant(
        mid="M11",
        file="apps/api/snapshot_builder.py",
        old="""            if not has_current_passport:
                # Паспорт другого контекста -- исторический факт (stale,
                # C04), но источником ТЕКУЩЕЙ версии данных он не является.
                ctx.add_mandatory_gap("missing_source_passport_artifact")""",
        new="""            if False:  # MUTANT M11: gap паспорта не выставляется
                ctx.add_mandatory_gap("missing_source_passport_artifact")""",
        expectation="KILL-CORPUS",
        note="C05: D02 без current-паспорта снова complete",
    ),
    Mutant(
        mid="M12",
        file="apps/api/snapshot_builder.py",
        old="""            if data_ref is None:
                ctx.add_mandatory_gap("missing_data_artifact")""",
        new="""            if False:  # MUTANT M12: gap data_ref не выставляется
                ctx.add_mandatory_gap("missing_data_artifact")""",
        expectation="KILL-CERT",
        note="C05: ось data_ref выпадает из каталога gaps",
    ),
    Mutant(
        mid="M13",
        file="apps/api/snapshot_builder.py",
        old="""        completeness_status = (
            "complete"
            if not ctx.missing_refs and not ctx.missing_mandatory
            else "partial"
        )""",
        new="""        completeness_status = (
            "complete"  # MUTANT M13: missing_mandatory игнорируется
            if not ctx.missing_refs
            else "partial"
        )""",
        expectation="KILL-CORPUS",
        note="C05: complete снова означает только отсутствие битых ссылок",
    ),
    Mutant(
        mid="M14",
        file="apps/api/snapshot_builder.py",
        old="""        strategy = payload.get("strategy")
        if strategy:
            parts.append(f"стратегия {strategy}")
        method = payload.get("method")
        if method:""",
        new="""        strategy = None  # MUTANT M14: стратегия/метод выкинуты из рецепта
        payload = dict(payload)
        payload.pop("method", None)
        if strategy:
            parts.append(f"стратегия {strategy}")
        method = payload.get("method")
        if method:""",
        expectation="KILL-CORPUS",
        note="C06: D04 теряет фактически выбранную стратегию/метод",
    ),
    Mutant(
        mid="M15",
        file="apps/api/snapshot_builder.py",
        old="""        for artifact in ctx.index.get("validation_result", []):
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)""",
        new="""        for artifact in ([] if True else ctx.index.get("validation_result", [])):  # MUTANT M15
            payload = self._read_payload(artifact)
            if payload is None:
                ctx.integrity_failures.append(artifact.artifact_id)""",
        expectation="KILL-CORPUS",
        note="C06: D03 теряет научный протокол валидации",
    ),
    # ── 1-й порядок: apps/api/doc_profiles.py ────────────────────────
    Mutant(
        mid="M16",
        file="apps/api/doc_profiles.py",
        old="""        self._audit(
            "org_profile_created",
            subject=subject,
            profile=profile,
            details={"name": profile.name, "version_no": profile.version_no,
                     "format": profile.format},
        )
        return self.registry.create_profile(profile)""",
        new="""        created = self.registry.create_profile(profile)  # MUTANT M16: порядок восстановлен НЕверно (write до аудита)
        self._audit(
            "org_profile_created",
            subject=subject,
            profile=profile,
            details={"name": profile.name, "version_no": profile.version_no,
                     "format": profile.format},
        )
        return created""",
        expectation="KILL-CORPUS",
        note="C08: protected write снова до mandatory-аудита",
    ),
    Mutant(
        mid="M17",
        file="apps/api/doc_profiles.py",
        old="""        self._audit(
            "org_profile_retired",
            subject=subject,
            profile=profile,
            details={"name": profile.name, "version_no": profile.version_no},
        )
        updated = self.registry.update_status(
            profile_id, PROFILE_RETIRED, getattr(subject, "subject_id", None)
        )
        assert updated is not None
        return updated""",
        new="""        updated = self.registry.update_status(
            profile_id, PROFILE_RETIRED, getattr(subject, "subject_id", None)
        )  # MUTANT M17: write до аудита
        assert updated is not None
        self._audit(
            "org_profile_retired",
            subject=subject,
            profile=profile,
            details={"name": profile.name, "version_no": profile.version_no},
        )
        return updated""",
        expectation="KILL-CORPUS",
        note="C08: retire снова пишет до аудита",
    ),
    # ── 1-й порядок: apps/api/document_jobs.py (F-D5C1 CAS) ──────────
    Mutant(
        mid="M18",
        file="apps/api/document_jobs.py",
        old="""        fresh = self.registry.get_job(job.job_id)
        if fresh is not None and fresh.state != job.state:
            job = fresh
        if job.state == JOB_CANCELLED:
            return job, None""",
        new="""        # MUTANT M18: гейт #1 удалён (остаётся только гейт #2)""",
        expectation="SURVIVED",
        note="F-D5C1: дубль-слой -- гейт #2 маскирует удаление гейта #1",
    ),
    Mutant(
        mid="M19",
        file="apps/api/document_jobs.py",
        old="""        fresh_before_commit = self.registry.get_job(job.job_id)
        if (
            fresh_before_commit is not None
            and fresh_before_commit.state == JOB_CANCELLED
        ):""",
        new="""        fresh_before_commit = self.registry.get_job(job.job_id)
        if (
            fresh_before_commit is not None
            and fresh_before_commit.state != JOB_CANCELLED  # MUTANT M19: инверсия
        ):""",
        expectation="KILL-CORPUS",
        note="F-D5C1: отмена перезаписывается готовностью",
    ),
    Mutant(
        mid="M20",
        file="apps/api/document_jobs.py",
        old="""            self.registry.update_rendition(
                replace_dataclass(
                    rendition, state=RENDITION_FAILED, job_id=job.job_id
                )
            )
            return fresh_before_commit, None""",
        new="""            return fresh_before_commit, None  # MUTANT M20: rendition не помечен failed""",
        expectation="KILL-CERT",
        note="F-D5C1: staged rendition «висит в очереди» при отмене",
    ),
    # ── 1-й порядок: packages/ui (C01/C02/C07/C09) ───────────────────
    Mutant(
        mid="UM01",
        file="packages/ui/components/DocumentationWorkspace.tsx",
        old="""            disabled={
              creating ||
              (listPhase !== "ready" && listPhase !== "empty")
            }""",
        new="""            disabled={creating || listPhase !== "ready"} // MUTANT UM01: empty снова блокирует первый документ""",
        expectation="KILL-CORPUS",
        note="C02: первый документ снова невозможно создать",
    ),
    Mutant(
        mid="UM02",
        file="packages/ui/components/DocumentationWorkspace.tsx",
        old="""      if (next.length === 0) {
        return current; // пустой реестр: выбор вида сохраняется
      }
      return next[0].kind_code;""",
        new="""      return next.length > 0 ? next[0].kind_code : null; // MUTANT UM02: пустой список сбрасывает вид""",
        expectation="KILL-CORPUS",
        note="C02: deep-link initialKind сбрасывается пустым списком",
    ),
    Mutant(
        mid="UM03",
        file="packages/ui/components/DocumentationWorkspace.tsx",
        old="""    // C07 (DOCLOG-E2E-RECHECK-1-FIX): отказ создания показывается
    // аналитику (§12.3/AC17); повтор не теряет выбранный вид.
    setCreateError(createErrorText(result.status));""",
        new="""    // MUTANT UM03: отказ создания не показывается
    if (false) setCreateError(createErrorText(result.status));""",
        expectation="KILL-CORPUS",
        note="C07: ошибка создания невидима",
    ),
    Mutant(
        mid="UM04",
        file="packages/ui/components/DocumentationWorkspace.tsx",
        old="""  { format: "pdf", label: "PDF", heavy: true },
  { format: "xlsx", label: "XLSX", heavy: true },
  { format: "parquet", label: "Parquet", heavy: true },
  { format: "zip", label: "ZIP", heavy: true },
];""",
        new="""  // MUTANT UM04: тяжёлые форматы убраны из селектора
];""",
        expectation="KILL-CORPUS",
        note="C09: PDF/XLSX/Parquet/ZIP снова недоступны в меню",
    ),
    Mutant(
        mid="UM05",
        file="packages/ui/components/DocumentationWorkspace.tsx",
        old="""    if (!runId) {
      // C01 (DOCLOG-E2E-RECHECK-1-FIX): отсутствие run -- отдельное
      setListPhase("no-run");
      return;
    }""",
        new="""    if (!runId) {
      setListPhase("empty"); // MUTANT UM05: no-run маскируется пустым реестром
      return;
    }""",
        expectation="KILL-CORPUS",
        note="C01: отсутствие run снова «документов нет»",
    ),
    Mutant(
        mid="UM06",
        file="packages/ui/lib/documentation.ts",
        old="""    result.ok
      ? {
          ok: true,
          status: result.status,
          data: { run_id: result.data?.run_id || null },
        }
      : { ok: false, status: result.status },""",
        new="""    result.ok
      ? {
          ok: true,
          status: result.status,
          data: { run_id: null }, // MUTANT UM06: run всегда теряется
        }
      : { ok: false, status: result.status },""",
        expectation="KILL-CERT",
        note="C01: резолв текущего run сломан (единый источник слоя 1)",
    ),
]

# ── 2-й порядок: «мутанты на своих мутантах» (пары из разных функций) ──
SECOND_ORDER = [
    ("S1", ["M01", "M09"]),
    ("S2", ["M04", "M14"]),
    ("S3", ["M13", "M16"]),
    ("S4", ["M19", "M02"]),
    ("S5", ["UM01", "UM04"]),
    ("S6", ["M17", "M06"]),
    ("S7", ["M10", "M11"]),
]


def by_id(mid: str) -> Mutant:
    for m in MUTANTS:
        if m.mid == mid:
            return m
    raise KeyError(mid)
