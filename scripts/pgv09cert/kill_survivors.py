#!/usr/bin/env python3
# scripts/p9cert/kill_survivors.py
"""PGV-09-CERT: добивание выживших мутантов оракулами сертификатора.

Для каждого мутанта, ВЫЖИВШЕГО в авторском корпусе (38 тестов), прогон
МОЕГО корпуса tests/api/test_p9cert_oracles.py (14 оракулов на своих
данных). Ожидание: KILLED -- пробелы покрытия автора закрываются
независимым корпусом; дефекты поставки при этом не обнаруживаются
(оракулы GREEN на чистом дереве).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
SUITE = ["tests/api/test_p9cert_oracles.py", "-q", "--no-header"]

MUTANTS = [
    (
        "M4-print-quota-check-removed",
        "apps/api/document_jobs.py",
        "        open_jobs = self.registry.list_open_jobs()\n        tenant_open = [\n            job for job in open_jobs if (job.tenant_id or None) == tenant_id\n        ]\n        if len(tenant_open) >= MAX_OPEN_JOBS_PER_TENANT:\n            raise DocumentQuotaExceeded(\n                \"quota_exceeded: очередь открытых заданий tenant \"\n                f\"{tenant_id or 'default'} переполнена \"\n                f\"({len(tenant_open)}/{MAX_OPEN_JOBS_PER_TENANT}); \"\n                \"повторите позднее\"\n            )\n        attempt = len(prior_jobs) + 1\n        job = self.registry.register_job(\n            DocumentJobRecord(\n                job_id=new_job_id(),\n                run_id=revision.run_id,",
        "        attempt = len(prior_jobs) + 1\n        job = self.registry.register_job(\n            DocumentJobRecord(\n                job_id=new_job_id(),\n                run_id=revision.run_id,",
    ),
    (
        "M6-nan-cell-stringified",
        "apps/api/print_render_payload.py",
        "    if isinstance(value, float):\n        if value != value or value in (float(\"inf\"), float(\"-inf\")):\n            return \"\"\n        return repr(value)",
        "    if isinstance(value, float):\n        return repr(value)",
    ),
    (
        "M7-schema-version-check-removed",
        "apps/api/print_render_payload.py",
        "    schema_version = snapshot_payload.get(\"schema_version\")\n    if schema_version != \"pgv.visual_print_snapshot/1\":\n        raise PrintRenderPayloadInvalid(\n            \"invalid_payload: ожидается pgv.visual_print_snapshot/1, \"\n            f\"получено {schema_version!r}\"\n        )",
        "",
    ),
    (
        "M11-print-idempotency-removed",
        "apps/api/document_jobs.py",
        "        if (\n            existing is not None\n            and existing.state == RENDITION_READY\n            and existing.job_id\n            and self.registry.get_job(existing.job_id) is not None\n        ):\n            job = self.registry.get_job(existing.job_id)\n            return job, existing\n        prior_jobs = [",
        "        prior_jobs = [",
    ),
    (
        "M12-payload-contract-emptied",
        "apps/api/document_render_worker.py",
        "def _build_print_payload(basis: dict[str, Any], job: DocumentJobRecord) -> dict[str, Any]:\n    \"\"\"Сборка pgv.render_payload/1 из durable basis (preflight §7;\n    request_id -- от job'а: трассировка рендера связана с job, §13.1).\"\"\"\n    from apps.api.print_render_payload import build_print_render_payload_from_basis\n\n    return build_print_render_payload_from_basis(\n        basis, request_id=f\"pgv:{job.job_id}\"\n    )",
        "def _build_print_payload(basis: dict[str, Any], job: DocumentJobRecord) -> dict[str, Any]:\n    return {\"schema_version\": \"pgv.render_payload/1\", \"request_id\": f\"pgv:{job.job_id}\", \"snapshot\": {}, \"sections\": []}",
    ),
]


def main() -> int:
    results = []
    for mid, rel, old, new in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append({"id": mid, "error": "anchor-not-found"})
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", *SUITE],
                cwd=str(REPO), capture_output=True, text=True, timeout=900,
            )
            killed = proc.returncode != 0
            tail = "\n".join((proc.stdout or "").strip().splitlines()[-2:])
        finally:
            subprocess.run(["git", "checkout", "--", rel], cwd=str(REPO), check=True)
        restored = path.read_text(encoding="utf-8") == original
        results.append(
            {
                "id": mid,
                "status": "KILLED" if killed else "ALIVE",
                "restored": restored,
                "oracle_tail": tail,
            }
        )
        print(f"{mid}: {'KILLED' if killed else 'ALIVE'} (restored={restored})")
    alive = [r["id"] for r in results if r.get("status") == "ALIVE"]
    summary = {
        "task": "PGV-09-CERT survivor kill-out",
        "oracle": "tests/api/test_p9cert_oracles.py (14)",
        "total": len(results),
        "killed": sum(1 for r in results if r.get("status") == "KILLED"),
        "alive": alive,
        "results": results,
    }
    out = Path(__file__).resolve().parent / "protocols" / "survivor_killout.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": summary["total"], "killed": summary["killed"], "alive": alive}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
