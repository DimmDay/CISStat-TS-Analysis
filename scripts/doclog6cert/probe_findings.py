#!/usr/bin/env python3
"""DOCLOG-6-CERT: зонд находки F-D6C1 (направление diff-полей vs
подписи UI).

ФАКТ: API diff_revisions(current, against=previous) возвращает
claims.added = утверждения, существующие в AGAINST-ревизии и
ОТСУТСТВУЮЩИЕ в текущей (т.е. «убранные» при движении old -> new), и
claims.removed = утверждения текущей, отсутствующие в against
(«добавленные» при движении old -> new).

UI (DocumentationWorkspace.tsx, панель doclog6-diff) вызывает
getRevisionDiff(текущая, предыдущая) и подписывает
  added   -> «Добавлено утверждений: N»
  removed -> «Убрано утверждений: N»
то есть числа added/removed меняются местами относительно естественного
чтения подписи «Добавлено» (= появилось в новой версии).

Зонд строит два собственных снимка: v1 = {A}, v2 = {A, NEW}; diff(v2,
against=v1) обязан (по честному чтению) вернуть NEW в added, но возвращает
NEW в removed. Диагностическая фиксация факта, не поломка: данные
честны и заморожены, ни один claim не теряется; репорт можно читать
обратно. Не блокирует согласование/архив (список metadata/validity не
зависит от направления).
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
    os.environ["CISSTAT_DATA_DIR"] = tempfile.mkdtemp(prefix="d6c-probe-")
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
        snapshot_key="probe-v1",
        kinds=["D02"],
        sections=[
            {
                "code": "D01",
                "title": "Зонд направления",
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
        snapshot_key="probe-v2",
        kinds=["D02"],
        sections=[
            {
                "code": "D01",
                "title": "Зонд направления",
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
    finding_confirmed = (not new_in_added) and new_in_removed

    payload = {
        "finding": "F-D6C1",
        "diff_call": f"diff({revision_v2.revision_id[:24]}..., against={revision_v1.revision_id[:24]}...)",
        "claims_added": added_texts,
        "claims_removed": removed_texts,
        "new_claim_lands_in": "removed" if new_in_removed else ("added" if new_in_added else "neither"),
        "ui_label_added": "Добавлено утверждений: {diff.claims.added.length}",
        "ui_label_removed": "Убрано утверждений: {diff.claims.removed.length}",
        "ui_would_show": {
            "Добавлено": len(added_texts),
            "Убрано": len(removed_texts),
        },
        "natural_reading": {
            "Добавлено": 1,
            "Убрано": 0,
        },
        "direction_inverted_vs_ui_labels": finding_confirmed,
        "severity": "low (UI-семантика; данные честны и заморожены, "
                    "recalculated=false; метаданные/validity не зависят "
                    "от направления)",
        "recommendation": "поменять местами семантику added/removed в "
                          "diff_revisions ЛИБО подписи панели "
                          "doclog6-diff; закрепить пин направления в "
                          "repo-сюите (a35 дизъюнктен repo)",
    }
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    (PROTOCOLS / "probe_findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if finding_confirmed else 1


if __name__ == "__main__":
    sys.exit(main())
