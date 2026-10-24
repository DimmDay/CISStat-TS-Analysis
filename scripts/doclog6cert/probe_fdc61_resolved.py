#!/usr/bin/env python3
"""DOCLOG-6-CERT-FIX: зонд разрешения находки F-D6C1.

ИСТОРИЯ: зонд probe_findings.py (акт DOCLOG-6-CERT, protocols/
probe_findings.json) зафиксировал F-D6C1 -- направление diff-полей
противоположно подписям UI: diff(v2, against=v1) возвращал NEW-claim
в removed, панель doclog6-diff подписывала added -> «Добавлено
утверждений» (см. находку, low/UI-семантика).

ФИКС (DOCLOG-6-CERT-FIX): семантика diff_revisions приведена к
естественному чтению -- diff(rev, against=prev) = изменения ОТ
against К rev: claims.added = появившиеся в rev, claims.removed =
существовавшие в against; metadata/validity_changed from = значение
against, to = значение rev. Подписи панели doclog6-diff не менялись
(они уже выражали естественное чтение); оракул a35 эволюционировал
честной заменой пина; пин направления добавлен в repo-сюиту
(test_diff_direction_natural_semantics).

Этот зонд воспроизводит СЦЕНАРИЙ исходного зонда (v1 = {A}, v2 =
{A, NEW}) и проверяет РАЗРЕШЕНИЕ: NEW обязан попадать в added
(не в removed), metadata from = значение v1, to = значение v2.
Диагностическая фиксация факта разрешения; протокол пишется в
protocols/probe_fdc61_resolved.json.

Запуск: python scripts/doclog6cert/probe_fdc61_resolved.py
Код возврата: 0 -- находка разрешена; 1 -- направление всё ещё
инвертировано (регресс фикса).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

PROTOCOLS = REPO / "scripts" / "doclog6cert" / "protocols"


def main() -> int:
    os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp(prefix="d6cfix-probe-")
    for name in (
        "DATABASE_URL", "CISSTAT_RUNS_BACKEND", "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS", "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND", "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND", "CISSTAT_DOCLOG_APPROVAL_POLICY",
        "CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS",
    ):
        os.environ.pop(name, None)

    from scripts.doclog6cert import conftest as cf

    cf._reset_all()
    cf.seed_cert_run()
    from apps.api.document_lifecycle import DocumentLifecycleService

    snapshot_v1 = cf.build_own_snapshot(
        snapshot_key="probe-fix-v1",
        kinds=["D02"],
        sections=[
            {
                "code": "D01",
                "title": "Зонд разрешения F-D6C1",
                "kind": "summary",
                "methodology_stage": "S1",
                "claims": [
                    {"text": "Утверждение A (есть в обеих ревизиях)", "validity": "current"},
                ],
            }
        ],
    )
    document, revision_v1 = cf.ensure_own_revision(snapshot_v1, "D02")
    snapshot_v2 = cf.build_own_snapshot(
        snapshot_key="probe-fix-v2",
        kinds=["D02"],
        sections=[
            {
                "code": "D01",
                "title": "Зонд разрешения F-D6C1",
                "kind": "summary",
                "methodology_stage": "S1",
                "claims": [
                    {"text": "Утверждение A (есть в обеих ревизиях)", "validity": "current"},
                    {"text": "НОВОЕ утверждение v2 (появилось в v2)", "validity": "current"},
                ],
            }
        ],
        context_id="ctx-d6cert-2",
    )
    _document, revision_v2 = cf.ensure_own_revision(snapshot_v2, "D02")

    service = DocumentLifecycleService.create_default()
    subject = cf.cert_subject()
    report = service.diff_revisions(
        revision_v2.revision_id,
        subject,
        session_id=cf.CERT_SESSION,
        against_revision_id=revision_v1.revision_id,
    )
    added_texts = [claim["text"] for claim in report["claims"]["added"]]
    removed_texts = [claim["text"] for claim in report["claims"]["removed"]]

    new_in_added = any("НОВОЕ утверждение v2" in text for text in added_texts)
    new_in_removed = any("НОВОЕ утверждение v2" in text for text in removed_texts)
    # Разрешение F-D6C1: NEW в added (естественное чтение), не в removed.
    finding_resolved = new_in_added and not new_in_removed
    metadata = report["metadata"]
    metadata_natural = (
        metadata["context_id"]["from"] == "ctx-d6cert-1"
        and metadata["context_id"]["to"] == "ctx-d6cert-2"
    )
    resolved = finding_resolved and metadata_natural

    payload = {
        "finding": "F-D6C1",
        "probe": "DOCLOG-6-CERT-FIX: проверка разрешения (сценарий "
                 "probe_findings.json: v1={A}, v2={A, NEW})",
        "diff_call": f"diff({revision_v2.revision_id[:24]}..., against={revision_v1.revision_id[:24]}...)",
        "claims_added": added_texts,
        "claims_removed": removed_texts,
        "new_claim_lands_in": "added" if new_in_added else ("removed" if new_in_removed else "neither"),
        "ui_label_added": "Добавлено утверждений: {diff.claims.added.length}",
        "ui_label_removed": "Убрано утверждений: {diff.claims.removed.length}",
        "ui_now_shows": {
            "Добавлено": len(added_texts),
            "Убрано": len(removed_texts),
        },
        "natural_reading": {
            "Добавлено": 1,
            "Убрано": 0,
        },
        "metadata_from_to": metadata.get("context_id"),
        "direction_inverted_vs_ui_labels": not finding_resolved,
        "finding_resolved": resolved,
        "fix": "DOCLOG-6-CERT-FIX: семантика added/removed/metadata "
               "from-to в diff_revisions приведена к естественному "
               "чтению (diff(rev, against=prev) = изменения от prev к "
               "rev); подписи панели doclog6-diff не менялись; пин "
               "направления: repo "
               "test_diff_direction_natural_semantics + эволюция "
               "оракула a35.",
    }
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    (PROTOCOLS / "probe_fdc61_resolved.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if resolved else 1


if __name__ == "__main__":
    sys.exit(main())
