"""Subprocess-only executable mutants; no production source files are edited."""
import copy
import os
from uuid import uuid4


def pytest_configure(config):
    from apps.api import passport_documents as P
    mode = os.environ.get("PGV13_CERT_MUTANT", "control")
    if mode in {"drop_group", "wrong_source_hash"}:
        original = P.build_passport_print_snapshot

        def changed(*args, **kwargs):
            payload = copy.deepcopy(original(*args, **kwargs))
            for section in payload["display"]["sections"]:
                record = section["record"]
                if mode == "drop_group" and record.get("passport"):
                    record["passport"].pop(next(reversed(record["passport"])))
                if mode == "wrong_source_hash":
                    record["source_hash"] = "f" * 64
            return payload

        P.build_passport_print_snapshot = changed
    elif mode == "wrong_job_id":
        original = P._job_json

        def changed(job):
            return {**original(job), "job_id": "job-" + uuid4().hex}

        P._job_json = changed
    elif mode != "control":
        raise ValueError("Unknown cert mutant")
