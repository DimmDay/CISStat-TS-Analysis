"""Supplemental socket-free actual PostgreSQL WASM SQL/HTTP proof.

Not native PostgreSQL locking/restart certification; native CI is mandatory.
"""

import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class Result:
    def __init__(self, value):
        self.rows = value.get("rows", [])
        self.rowcount = value.get("affectedRows", len(self.rows))
        fields = {v["name"]: v["dataTypeID"] for v in value.get("fields", [])}
        for row in self.rows:
            for k, v in row.items():
                if v is None:
                    continue
                if fields.get(k) == 2950:
                    row[k] = UUID(v)
                elif fields.get(k) == 1184:
                    row[k] = datetime.fromisoformat(v.replace("Z", "+00:00"))
                elif fields.get(k) in (20, 21, 23):
                    row[k] = int(v)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, modules):
        self.child = subprocess.Popen(
            ["node", str(ROOT / "scripts/auth15/wasm_engine.mjs"), modules],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        self.depth = 0

    def execute(self, sql, params=None, **kw):
        if params:
            for i in range(len(params)):
                sql = sql.replace("%s", "$" + str(i + 1), 1)
        self.child.stdin.write(
            json.dumps({"sql": sql, "params": params or []}, default=str) + "\n"
        )
        self.child.stdin.flush()
        line = self.child.stdout.readline()
        if not line:
            raise RuntimeError("WASM process exited")
        value = json.loads(line)
        if "error" in value:
            import psycopg

            code = value["error"].get("code") or ""
            cls = psycopg.errors.lookup(code) if len(code) == 5 else RuntimeError
            raise cls(value["error"]["message"])
        return Result(value["result"])

    @contextmanager
    def transaction(self):
        level = self.depth
        self.execute("BEGIN" if level == 0 else f"SAVEPOINT nested{level}")
        self.depth += 1
        try:
            yield self
            self.execute("COMMIT" if level == 0 else f"RELEASE SAVEPOINT nested{level}")
        except BaseException:
            self.execute(
                "ROLLBACK" if level == 0 else f"ROLLBACK TO SAVEPOINT nested{level}"
            )
            raise
        finally:
            self.depth -= 1

    def close(self):
        self.child.stdin.close()
        self.child.wait(timeout=10)


class WasmStore:
    def __init__(self, modules):
        self.c = Connection(modules)
        self._dsn = "WASM-supplemental-only"
        self.schema = "public"

    @contextmanager
    def transaction(self, readonly=False):
        from apps.api.authentication.storage import AccessTransaction

        with self.c.transaction():
            yield AccessTransaction(self.c)

    def close(self):
        self.c.close()


def main():
    import unittest

    if not os.environ.get("CISSTAT_AUTH15_WASM"):
        print("Set CISSTAT_AUTH15_WASM to @electric-sql/pglite module directory")
        return 2
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests/integration"), pattern="test_auth15*.py"
    )
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        "Supplemental WASM SQL/HTTP proof only. Native concurrency/restart NOT certified."
    )
    return 0 if r.wasSuccessful() and r.testsRun > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
