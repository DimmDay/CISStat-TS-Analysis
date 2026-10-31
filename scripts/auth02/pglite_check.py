#!/usr/bin/env python3
"""Optional SQL rehearsal on PostgreSQL WASM, NOT a native multi-backend certificate.

Isolated npm tooling: npm install --prefix SOME_DIRECTORY --legacy-peer-deps
  @electric-sql/pglite@0.5.14 @electric-sql/pglite-socket@0.2.17
Run: python scripts/auth02/pglite_check.py --modules SOME_DIRECTORY
Native PostgreSQL remains mandatory in CI (verify_postgres + actual service restart).
"""

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", type=Path, required=True)
    args = parser.parse_args()
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node required for optional WASM rehearsal")
    with tempfile.TemporaryDirectory(
        prefix="auth02-wasm-", dir=ROOT.parent
    ) as directory:
        temp = Path(directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        dsn = f"postgresql://postgres@127.0.0.1:{port}/postgres?sslmode=disable"
        env = {**os.environ, "CISSTAT_AUTH_TEST_DSN": dsn}
        log = (temp / "server.txt").open("w", encoding="utf-8")

        def start():
            server = subprocess.Popen(
                [
                    node,
                    str(ROOT / "scripts/auth02/pglite_server.mjs"),
                    str(args.modules.resolve()),
                    str(temp / "data"),
                    str(port),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            for _ in range(50):
                if server.poll() is not None:
                    raise RuntimeError("WASM server startup failed")
                try:
                    with psycopg.connect(dsn, connect_timeout=1) as conn:
                        print(
                            conn.execute("SELECT version()").fetchone()[0], flush=True
                        )
                    return server
                except psycopg.OperationalError:
                    time.sleep(0.1)
            server.terminate()
            server.wait(timeout=15)
            raise RuntimeError("WASM server not reachable")

        def stop(server):
            server.terminate()
            try:
                code = server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
                raise RuntimeError("WASM graceful shutdown failed")
            if code != 0:
                raise RuntimeError("WASM shutdown failed")

        def run(*command):
            subprocess.run(
                [sys.executable, *command], cwd=ROOT, env=env, check=True, timeout=120
            )

        server = None
        try:
            print(
                "WASM SQL rehearsal; transaction multiplexer is NOT native PostgreSQL lock scheduling",
                flush=True,
            )
            server = start()
            run("scripts/auth02/verify_postgres.py")
            run("scripts/auth02/mutation_rehearsal.py")
            run(
                "scripts/auth02/restart_probe.py",
                "seed",
                "--state",
                str(temp / "state.json"),
            )
            stop(server)
            server = None
            server = start()
            run(
                "scripts/auth02/restart_probe.py",
                "verify",
                "--state",
                str(temp / "state.json"),
            )
            print("WASM SQL + database process restart rehearsal PASS", flush=True)
        finally:
            if server is not None:
                stop(server)
            log.close()
            print((temp / "server.txt").read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
