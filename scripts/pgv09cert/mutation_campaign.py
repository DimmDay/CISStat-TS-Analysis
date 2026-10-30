#!/usr/bin/env python3
# scripts/p9cert/mutation_campaign.py
"""PGV-09-CERT: кампания мутантов «на своих мутантах».

Каждый мутант -- точечная правка кода поставки PGV-09 (09c79aa);
оракул -- авторский корпус tests/api/test_pgv09_jobs_renderer_integration.py
(38 тестов). Мутант KILLED, если корпус падает; ALIVE -- пробел покрытия.
После каждого мутанта файл восстанавливается побайтно из git (git checkout --).

Без commit/push (AGENTS.md). Запуск из корня репозитория:
    python3 /home/z/my-project/scripts/p9cert/mutation_campaign.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
SUITE = ["tests/api/test_pgv09_jobs_renderer_integration.py", "-q", "--no-header", "-x"]

# (id, file, old, new, ожидаемый класс)
MUTANTS = [
    (
        "M1-client-png-gate-removed",
        "apps/api/png_renderer_client.py",
        "        if not data.startswith(PNG_SIGNATURE):\n            raise RendererBadOutput(\n                \"renderer_bad_output: ответ контейнера не PNG (протокольное \"\n                \"нарушение; байты не stage'ятся)\"\n            )\n        return data",
        "        return data",
        "client-gate",
    ),
    (
        "M2-dependency-becomes-transient",
        "apps/api/document_render_worker.py",
        "TRANSIENT_ERROR_CODES = frozenset(\n    {\"render_failed\", \"render_timeout\", \"renderer_busy\", \"renderer_unavailable\"}\n)",
        "TRANSIENT_ERROR_CODES = frozenset(\n    {\"render_failed\", \"render_timeout\", \"renderer_busy\", \"renderer_unavailable\", \"render_dependency_unavailable\"}\n)",
        "taxonomy",
    ),
    (
        "M3-requeue-no-attempt-increment",
        "apps/api/document_render_worker.py",
        "                    state=JOB_QUEUED,\n                    error_code=error_code,\n                    attempt=job.attempt + 1,",
        "                    state=JOB_QUEUED,\n                    error_code=error_code,\n                    attempt=job.attempt,",
        "retry",
    ),
    (
        "M4-print-quota-check-removed",
        "apps/api/document_jobs.py",
        "        open_jobs = self.registry.list_open_jobs()\n        tenant_open = [\n            job for job in open_jobs if (job.tenant_id or None) == tenant_id\n        ]\n        if len(tenant_open) >= MAX_OPEN_JOBS_PER_TENANT:\n            raise DocumentQuotaExceeded(\n                \"quota_exceeded: очередь открытых заданий tenant \"\n                f\"{tenant_id or 'default'} переполнена \"\n                f\"({len(tenant_open)}/{MAX_OPEN_JOBS_PER_TENANT}); \"\n                \"повторите позднее\"\n            )\n        attempt = len(prior_jobs) + 1\n        job = self.registry.register_job(\n            DocumentJobRecord(\n                job_id=new_job_id(),\n                run_id=revision.run_id,",
        "        attempt = len(prior_jobs) + 1\n        job = self.registry.register_job(\n            DocumentJobRecord(\n                job_id=new_job_id(),\n                run_id=revision.run_id,",
        "quota",
    ),
    (
        "M5-print-format-catalog-removed",
        "apps/api/document_jobs.py",
        "        if format not in PRINT_RENDITION_FORMATS:\n            raise UnsupportedFormatError(\n                f\"Формат {format!r} не входит в каталог печатных renditions \"\n                f\"{sorted(PRINT_RENDITION_FORMATS)} (§1 PNG-only; PGV-09)\"\n            )\n        spec = RENDITION_FORMATS.get(format)",
        "        spec = RENDITION_FORMATS.get(format)",
        "catalog",
    ),
    (
        "M6-nan-cell-stringified",
        "apps/api/print_render_payload.py",
        "    if isinstance(value, float):\n        if value != value or value in (float(\"inf\"), float(\"-inf\")):\n            return \"\"\n        return repr(value)",
        "    if isinstance(value, float):\n        return repr(value)",
        "canon",
    ),
    (
        "M7-schema-version-check-removed",
        "apps/api/print_render_payload.py",
        "    schema_version = snapshot_payload.get(\"schema_version\")\n    if schema_version != \"pgv.visual_print_snapshot/1\":\n        raise PrintRenderPayloadInvalid(\n            \"invalid_payload: ожидается pgv.visual_print_snapshot/1, \"\n            f\"получено {schema_version!r}\"\n        )",
        "",
        "preflight",
    ),
    (
        "M8-error-code-parse-blinded",
        "apps/api/png_renderer_client.py",
        "    try:\n        parsed = json.loads(body.decode(\"utf-8\"))\n        code = parsed.get(\"error\", {}).get(\"code\")\n        return code if isinstance(code, str) else \"\"\n    except Exception:  # noqa: BLE001 -- контракт мягкого парсинга\n        return \"\"",
        "    return \"\"",
        "taxonomy",
    ),
    (
        "M9-worker-png-gate-removed",
        "apps/api/document_render_worker.py",
        "        if not content.startswith(PNG_SIGNATURE):\n            return self._fail_or_requeue(claimed, \"renderer_bad_output\")",
        "",
        "worker-gate",
    ),
    (
        "M10-busy-mapped-unavailable",
        "apps/api/png_renderer_client.py",
        "            if exc.code == 429 or code == \"renderer_busy\":\n                raise RendererBusy(\n                    \"renderer_busy: конкурентный предел контейнера (429)\"\n                ) from None",
        "            if exc.code == 429 or code == \"renderer_busy\":\n                raise RendererUnavailable(\n                    \"renderer_busy mis-mapped\"\n                ) from None",
        "taxonomy",
    ),
    (
        "M11-print-idempotency-removed",
        "apps/api/document_jobs.py",
        "        if (\n            existing is not None\n            and existing.state == RENDITION_READY\n            and existing.job_id\n            and self.registry.get_job(existing.job_id) is not None\n        ):\n            job = self.registry.get_job(existing.job_id)\n            return job, existing\n        prior_jobs = [",
        "        prior_jobs = [",
        "idempotency",
    ),
    (
        "M12-payload-contract-emptied",
        "apps/api/document_render_worker.py",
        "def _build_print_payload(basis: dict[str, Any], job: DocumentJobRecord) -> dict[str, Any]:\n    \"\"\"Сборка pgv.render_payload/1 из durable basis (preflight §7;\n    request_id -- от job'а: трассировка рендера связана с job, §13.1).\"\"\"\n    from apps.api.print_render_payload import build_print_render_payload_from_basis\n\n    return build_print_render_payload_from_basis(\n        basis, request_id=f\"pgv:{job.job_id}\"\n    )",
        "def _build_print_payload(basis: dict[str, Any], job: DocumentJobRecord) -> dict[str, Any]:\n    return {\"schema_version\": \"pgv.render_payload/1\", \"request_id\": f\"pgv:{job.job_id}\", \"snapshot\": {}, \"sections\": []}",
        "contract",
    ),
]


def run_suite() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *SUITE],
        cwd=str(REPO), capture_output=True, text=True, timeout=900,
    )
    killed = proc.returncode != 0
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-3:])
    return killed, tail


def main() -> int:
    results = []
    for mid, rel, old, new, klass in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append({"id": mid, "error": "anchor-not-found"})
            continue
        mutated = original.replace(old, new, 1)
        if mutated == original:
            results.append({"id": mid, "error": "no-op"})
            continue
        path.write_text(mutated, encoding="utf-8")
        try:
            killed, tail = run_suite()
        finally:
            subprocess.run(
                ["git", "checkout", "--", rel], cwd=str(REPO), check=True
            )
        restored = path.read_text(encoding="utf-8") == original
        results.append(
            {
                "id": mid,
                "class": klass,
                "file": rel,
                "status": "KILLED" if killed else "ALIVE",
                "restored": restored,
                "pytest_tail": tail,
            }
        )
        print(f"{mid}: {'KILLED' if killed else 'ALIVE'} (restored={restored})")
    alive = [r["id"] for r in results if r.get("status") == "ALIVE"]
    summary = {
        "task": "PGV-09-CERT mutation campaign",
        "base": "09c79aa",
        "oracle": "tests/api/test_pgv09_jobs_renderer_integration.py (38)",
        "total": len(results),
        "killed": sum(1 for r in results if r.get("status") == "KILLED"),
        "alive": alive,
        "results": results,
    }
    out = Path(__file__).resolve().parent / "protocols" / "mutation_campaign.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": summary["total"], "killed": summary["killed"], "alive": alive}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
