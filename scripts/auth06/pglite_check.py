#!/usr/bin/env python3
"""Optional two-database PostgreSQL WASM proof; native CI remains mandatory.

Separate auth/audit engines avoid PGlite's transaction multiplexer deadlock
when the existing audit consumer commits while the auth outbox is locked.
"""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="auth06-wasm-", dir=ROOT.parent) as tmp:
        directory = Path(tmp)
        servers = []
        logs = []
        dsns = []
        try:
            for name in ("auth", "audit"):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                dsn = f"postgresql://postgres@127.0.0.1:{port}/postgres?sslmode=disable"
                dsns.append(dsn)
                log = (directory / (name + ".txt")).open("w", encoding="utf-8")
                logs.append(log)
                server = subprocess.Popen(
                    [
                        "node",
                        str(ROOT / "scripts/auth02/pglite_server.mjs"),
                        str(args.modules.resolve()),
                        str(directory / name),
                        str(port),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                servers.append(server)
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("WASM startup failed")
                    try:
                        with psycopg.connect(dsn, connect_timeout=1) as conn:
                            print(
                                name,
                                conn.execute("SELECT version()").fetchone()[0],
                                flush=True,
                            )
                        break
                    except psycopg.OperationalError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("WASM readiness timeout")
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/auth06/verify_postgres.py")],
                cwd=ROOT,
                env={
                    **os.environ,
                    "CISSTAT_AUTH_TEST_DSN": dsns[0],
                    "CISSTAT_AUTH_AUDIT_TEST_DSN": dsns[1],
                },
                check=True,
                timeout=180,
            )
        finally:
            for server in servers:
                server.terminate()
            for server in servers:
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            for log in logs:
                log.close()
    print(
        "AUTH-06 SQL/HTTP proof PASS; native PostgreSQL locking/restart NOT certified"
    )


if __name__ == "__main__":
    main()
