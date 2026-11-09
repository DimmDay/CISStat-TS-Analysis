"""Bounded expired-workspace cleanup; usage/audit survive and uncertain work holds."""

import re
from datetime import timedelta

from apps.api.billing.coordinator import audit

from .demo_lifecycle import LifecycleService, check_schema
from .sessions import boundary


class DemoCleanup(LifecycleService):
    @boundary
    def sweep(self, limit=25):
        from .demo import CampaignPolicy

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("bounded batch required")
        report = {"expired": 0, "cleaned": 0, "held": 0, "running": 0}
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            now = self._now(c)
            grants = c.execute(
                """SELECT g.* FROM auth_demo_grants g JOIN auth_demo_campaigns p USING(campaign_id) LEFT JOIN auth_demo_cleanup x USING(grant_id) LEFT JOIN auth_demo_sweep_attempts a USING(grant_id)
                WHERE x.grant_id IS NULL AND (g.expires_at<=%s OR g.status='revoked' OR p.status='revoked') ORDER BY a.attempted_at NULLS FIRST,g.expires_at,g.grant_id LIMIT %s""",
                (now, limit),
            ).fetchall()
        for hint in grants:
            with self._tx() as tx:
                c = tx.connection
                now = self._now(c)
                # Serialize with enter/policy and deny post-cleanup issuance.
                campaign = c.execute(
                    "SELECT * FROM auth_demo_campaigns WHERE campaign_id=%s FOR UPDATE",
                    (hint["campaign_id"],),
                ).fetchone()
                g = c.execute(
                    "SELECT * FROM auth_demo_grants WHERE grant_id=%s FOR UPDATE",
                    (hint["grant_id"],),
                ).fetchone()
                if c.execute(
                    "SELECT 1 FROM auth_demo_cleanup WHERE grant_id=%s",
                    (g["grant_id"],),
                ).fetchone():
                    continue
                c.execute(
                    "INSERT INTO auth_demo_sweep_attempts(grant_id,attempted_at) VALUES (%s,%s) ON CONFLICT(grant_id) DO UPDATE SET attempted_at=EXCLUDED.attempted_at",
                    (g["grant_id"], now),
                )
                if g["status"] != "revoked":
                    c.execute(
                        "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s",
                        (g["grant_id"],),
                    )
                    c.execute(
                        "UPDATE auth_budget_scopes SET status='closed',version=version+1 WHERE scope_id=%s AND status<>'closed'",
                        (g["grant_id"],),
                    )
                    c.execute(
                        "UPDATE auth_sessions SET revoked_at=%s WHERE demo_grant_id=%s AND revoked_at IS NULL",
                        (now, g["grant_id"]),
                    )
                    audit(
                        c,
                        "auth_demo_changed",
                        g["grant_id"],
                        details={"command": "expired"},
                    )
                    report["expired"] += 1
                p = CampaignPolicy.model_validate(campaign["policy"])
                if now < g["expires_at"] + timedelta(hours=p.retention_hours):
                    continue
                if (
                    c.execute(
                        "SELECT 1 FROM auth_worker_jobs WHERE account_id=%s AND state IN ('queued','running','uncertain') LIMIT 1",
                        (g["account_id"],),
                    ).fetchone()
                    or c.execute(
                        "SELECT 1 FROM auth_demo_calls WHERE grant_id=%s AND state='running' LIMIT 1",
                        (g["grant_id"],),
                    ).fetchone()
                ):
                    report["running"] += 1
                    continue
                runs = c.execute(
                    "SELECT * FROM research_runs WHERE owner_account_id=%s FOR UPDATE",
                    (g["account_id"],),
                ).fetchall()
                held = False
                for run in runs:
                    rid = run["run_id"]
                    if (
                        c.execute(
                            "SELECT 1 FROM run_ownership_migrations WHERE run_id=%s LIMIT 1",
                            (rid,),
                        ).fetchone()
                        or c.execute(
                            "SELECT 1 FROM document_retention WHERE run_id=%s AND hold LIMIT 1",
                            (rid,),
                        ).fetchone()
                        or c.execute(
                            "SELECT 1 FROM document_lifecycle WHERE run_id=%s AND event IN ('published','approved') LIMIT 1",
                            (rid,),
                        ).fetchone()
                        or c.execute(
                            "SELECT 1 FROM research_artifact_pins WHERE run_id=%s LIMIT 1",
                            (rid,),
                        ).fetchone()
                    ):
                        held = True
                        break
                if held:
                    report["held"] += 1
                    continue
                for run in runs:
                    rid = run["run_id"]
                    for table in (
                        "research_artifacts",
                        "report_snapshots",
                        "document_renditions",
                    ):
                        for key in c.execute(
                            "SELECT storage_key FROM "
                            + table
                            + " WHERE run_id=%s AND storage_key<>''",
                            (rid,),
                        ).fetchall():
                            self._queue(c, "object", key["storage_key"])
                    if re.fullmatch("[a-f0-9]{64}", run["dataset_fingerprint"]):
                        self._queue(c, "upload", run["dataset_fingerprint"])
                    self._queue(c, "checkpoint", rid)
                    c.execute("DELETE FROM research_runs WHERE run_id=%s", (rid,))
                for worker in c.execute(
                    "SELECT worker_id,stop_proof FROM auth_worker_jobs WHERE account_id=%s",
                    (g["account_id"],),
                ).fetchall():
                    cache = (worker["stop_proof"] or {}).get("compute_cache") or {}
                    if cache.get("storage_key"):
                        self._queue(c, "cache", cache["storage_key"])
                    self._queue(c, "proof", str(worker["worker_id"]))
                c.execute(
                    "DELETE FROM analysis_sessions WHERE payload->>'owner_account_id'=%s",
                    (str(g["account_id"]),),
                )
                c.execute(
                    "DELETE FROM auth_demo_calls WHERE grant_id=%s", (g["grant_id"],)
                )
                c.execute(
                    "INSERT INTO auth_demo_cleanup(grant_id,cleaned_at,runs_deleted) VALUES (%s,%s,%s)",
                    (g["grant_id"], now, len(runs)),
                )
                audit(
                    c,
                    "auth_demo_changed",
                    g["grant_id"],
                    details={"command": "workspace_cleaned", "runs": len(runs)},
                )
                report["cleaned"] += 1
        return report

    @boundary
    def abandon_calls(self, *, quiesced=False):
        if not quiesced:
            raise ValueError("all publishers must be stopped")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            rows = c.execute(
                "UPDATE auth_demo_calls SET state='failed',response=NULL WHERE state='running' RETURNING call_id"
            ).fetchall()
            audit(
                c,
                "auth_demo_changed",
                "demo-http",
                details={"command": "quiesced_abandon_calls", "count": len(rows)},
            )
            return {"abandoned": len(rows)}

    @staticmethod
    def _queue(c, kind, key):
        c.execute(
            "INSERT INTO auth_demo_gc(kind,file_key) VALUES (%s,%s) ON CONFLICT(kind,file_key) DO UPDATE SET state='pending'",
            (kind, key),
        )

    @boundary
    def collect_files(self, *, quiesced=False, limit=100):
        if not quiesced or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("all publishers must be stopped; finite batch required")
        from apps.api.artifact_store import get_artifact_object_store
        from apps.api.billing.compute_cache import objects
        from apps.api.research_runs import DatasetFileStore
        from apps.api.workers.spool import root as proof_root

        count = 0
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            rows = c.execute(
                "SELECT * FROM auth_demo_gc WHERE state='pending' ORDER BY created_at,kind,file_key LIMIT %s FOR UPDATE SKIP LOCKED",
                (limit,),
            ).fetchall()
            for row in rows:
                kind, key = row["kind"], row["file_key"]
                paths = []
                if kind == "object":
                    if not re.fullmatch("[a-f0-9]{2}/[a-f0-9]{64}", key):
                        raise ValueError("invalid content key")
                    referenced = any(
                        c.execute(
                            "SELECT 1 FROM " + t + " WHERE storage_key=%s LIMIT 1",
                            (key,),
                        ).fetchone()
                        for t in (
                            "research_artifacts",
                            "report_snapshots",
                            "document_renditions",
                        )
                    )
                    if referenced:
                        continue
                    paths = [get_artifact_object_store().path_for_key(key)]
                elif kind == "upload":
                    if not re.fullmatch("[a-f0-9]{64}", key):
                        raise ValueError("invalid upload digest")
                    if c.execute(
                        "SELECT 1 FROM research_runs WHERE dataset_fingerprint=%s LIMIT 1",
                        (key,),
                    ).fetchone():
                        continue
                    root = DatasetFileStore.default_root() / "uploads"
                    paths = [
                        root / (key + ext)
                        for ext in (
                            ".csv",
                            ".xlsx",
                            ".xls",
                            ".tsv",
                            ".json",
                            ".meta.json",
                        )
                    ]
                elif kind == "checkpoint":
                    if not re.fullmatch("RUN-[A-Za-z0-9-]+", key):
                        raise ValueError("invalid run")
                    if c.execute(
                        "SELECT 1 FROM research_runs WHERE run_id=%s", (key,)
                    ).fetchone():
                        continue
                    root = DatasetFileStore.default_root() / "checkpoints" / key
                    paths = list(root.glob("*.csv")) if not root.is_symlink() else []
                elif kind == "cache":
                    if not re.fullmatch("[a-f0-9]{2}/[a-f0-9]{64}", key):
                        raise ValueError("invalid cache key")
                    if c.execute(
                        "SELECT 1 FROM auth_worker_jobs w LEFT JOIN auth_demo_grants g ON g.account_id=w.account_id LEFT JOIN auth_demo_cleanup x ON x.grant_id=g.grant_id WHERE w.stop_proof#>>'{compute_cache,storage_key}'=%s AND x.grant_id IS NULL LIMIT 1",
                        (key,),
                    ).fetchone():
                        continue
                    paths = [objects().path_for_key(key)]
                else:
                    from uuid import UUID

                    UUID(key)
                    paths = list(proof_root().glob(key + "-*.json")) + list(
                        proof_root().glob(key + "-*.tmp")
                    )
                # Publishers are stopped; validate every parent against symlink escapes.
                for path in paths:
                    if path.is_symlink() or any(
                        parent.is_symlink() for parent in path.parents
                    ):
                        raise ValueError("symlink GC refused")
                # Commit the mandatory intent before irreversible unlink. A crash
                # after unlink leaves a pending idempotent obligation, never lost audit.
                with self.store.transaction() as intent_tx:
                    audit(
                        intent_tx.connection,
                        "auth_demo_changed",
                        key,
                        details={"command": "file_gc_intent", "kind": kind},
                    )
                for path in paths:
                    path.unlink(missing_ok=True)
                c.execute(
                    "UPDATE auth_demo_gc SET state='done' WHERE kind=%s AND file_key=%s",
                    (kind, key),
                )
                count += 1
        return {"collected": count}
