#!/usr/bin/env python3
"""Optional PostgreSQL WASM SQL proof; native PostgreSQL CI is separate.

Reuse AUTH-02 wire transport. No production fallback; does not prove native locks.
"""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    import psycopg

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--modules", type=Path, required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="auth03-wasm-", dir=ROOT.parent) as tmp:
        directory = Path(tmp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        dsn = f"postgresql://postgres@127.0.0.1:{port}/postgres?sslmode=disable"
        with (directory / "server.txt").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [
                    "node",
                    str(ROOT / "scripts/auth02/pglite_server.mjs"),
                    str(args.modules.resolve()),
                    str(directory / "data"),
                    str(port),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("WASM transport startup failed")
                    try:
                        with psycopg.connect(dsn, connect_timeout=1) as conn:
                            print(
                                conn.execute("SELECT version()").fetchone()[0],
                                flush=True,
                            )
                        break
                    except psycopg.OperationalError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("WASM transport readiness timeout")
                subprocess.run(
                    [sys.executable, str(ROOT / "scripts/auth03/verify_postgres.py")],
                    cwd=ROOT,
                    env={**os.environ, "CISSTAT_AUTH_TEST_DSN": dsn},
                    check=True,
                    timeout=120,
                )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            if server.returncode:
                raise RuntimeError("WASM transport shutdown failed")
    print("AUTH-03 SQL rehearsal PASS; native PostgreSQL scheduling/CI NOT tested")


if __name__ == "__main__":
    main()
