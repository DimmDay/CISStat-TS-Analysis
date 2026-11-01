#!/usr/bin/env python3
"""Two independent HTTPS hosts -> shared handler -> real auth API -> PostgreSQL.

This is a transport proof, not a Next/browser or native PostgreSQL certificate.
"""

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.api.authentication.mfa import MfaService
from apps.api.authentication.mfa_crypto import totp
from apps.api.authentication.mfa_migrations import apply_migration
from apps.api.authentication.storage import PostgresAccessStore


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    dsn = os.environ["CISSTAT_AUTH_TEST_DSN"]
    schema = "auth06wire_" + uuid4().hex
    api_port, a, b = free_port(), free_port(), free_port()
    origins = [f"https://localhost:{a}", f"https://127.0.0.1:{b}"]
    api = f"https://127.0.0.1:{api_port}"
    password = "AUTH06 test-only named admin passphrase!"
    now = datetime.now(UTC)
    processes = []
    with tempfile.TemporaryDirectory(
        prefix="auth06-recovery-wire-", dir=ROOT.parent
    ) as tmp:
        temp = Path(tmp)
        cert = temp / "cert.pem"
        key = temp / "key.pem"
        clock = temp / "clock.txt"
        clock.write_text(now.isoformat())
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )
        env = {
            **os.environ,
            "CISSTAT_AUTH_ALLOWED_ORIGINS": ",".join(origins),
            "CISSTAT_AUTH_CSRF_KEY": "wire-test-only-" + "a" * 40,
            "CISSTAT_AUTH_MFA_KEYS": json.dumps(
                {"wire": base64.b64encode(b"w" * 32).decode()}
            ),
            "CISSTAT_AUTH_MFA_ACTIVE_KEY": "wire",
            "CISSTAT_AUTH_WIRE_SCHEMA": schema,
            "CISSTAT_AUTH_WIRE_CLOCK": str(clock),
            "NODE_EXTRA_CA_CERTS": str(cert),
            "CISSTAT_IDENTITY_MODE": "scoped",
        }
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            store = PostgresAccessStore(dsn, schema=schema)
            with store.transaction() as tx:
                apply_migration(tx.connection)
            service = MfaService(store)
            admin = service.bootstrap(
                service.prepare_bootstrap(), "wire-admin", password
            )
            subprocess.run(
                [
                    "node",
                    "node_modules/typescript/bin/tsc",
                    "-p",
                    "scripts/auth06/tsconfig.wire.json",
                    "--outDir",
                    str(temp / "compiled"),
                ],
                cwd=ROOT,
                check=True,
            )
            config = temp / "proxy.json"
            config.write_text(
                json.dumps(
                    {"origins": origins, "api": api, "key": str(key), "cert": str(cert)}
                )
            )
            with (temp / "servers.log").open("w") as log:
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "scripts.auth06.wire_api:create_app",
                            "--factory",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(api_port),
                            "--ssl-keyfile",
                            str(key),
                            "--ssl-certfile",
                            str(cert),
                            "--log-level",
                            "warning",
                            "--no-access-log",
                        ],
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                processes.append(
                    subprocess.Popen(
                        [
                            "node",
                            "scripts/auth06/wire_proxy.cjs",
                            str(temp / "compiled/firstPartyProxy.js"),
                            str(config),
                        ],
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                for target in [api, *origins]:
                    for _ in range(150):
                        if any(p.poll() is not None for p in processes):
                            raise RuntimeError("wire startup failed")
                        try:
                            httpx.get(
                                target
                                + (
                                    "/v1/auth/me"
                                    if target == api
                                    else "/api/v1/auth/me"
                                ),
                                verify=str(cert),
                                timeout=1,
                                trust_env=False,
                            )
                            break
                        except httpx.TransportError:
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("wire readiness timeout")
                clients = [
                    httpx.Client(
                        base_url=o,
                        verify=str(cert),
                        trust_env=False,
                        headers={"Origin": o, "Sec-Fetch-Site": "same-origin"},
                    )
                    for o in origins
                ]

                def proof(c):
                    r = c.get("/api/v1/auth/csrf", headers={"X-CSRF-Request": "1"})
                    assert r.status_code == 200
                    return r.json()["csrf_token"]

                def post(c, path, payload):
                    return c.post(
                        "/api/v1/auth/" + path,
                        json=payload,
                        headers={"X-CSRF-Token": proof(c)},
                    )

                def otp(seed):
                    nonlocal now
                    now += timedelta(seconds=30)
                    clock.write_text(now.isoformat())
                    return totp(seed, int(now.timestamp()) // 30)

                x, y = clients
                try:
                    assert (
                        x.get(
                            "/api/v1/auth/me",
                            headers={
                                "X-Role": "admin",
                                "X-Subject-ID": admin["subject_id"],
                            },
                        ).status_code
                        == 401
                    )
                    assert (
                        x.post(
                            "/api/v1/auth/login",
                            json={"login": "wire-admin", "password": password},
                        ).headers["x-cisstat-csrf"]
                        == "required"
                    )
                    assert (
                        post(
                            x, "login", {"login": "wire-admin", "password": "wrong"}
                        ).status_code
                        == 401
                    )
                    r = post(x, "login", {"login": "wire-admin", "password": password})
                    assert (
                        r.status_code == 200 and r.json()["purpose"] == "enroll_start"
                    )
                    assert (
                        "__Host-cisstat_auth" not in x.cookies
                        and x.get("/api/v1/auth/me").status_code == 401
                    )
                    r = post(
                        x,
                        "mfa/enroll",
                        {"challenge_token": r.json()["challenge_token"]},
                    )
                    assert r.status_code == 200
                    seed = base64.b32decode(r.json()["secret"])
                    old = proof(x)
                    r = post(
                        x,
                        "mfa/verify",
                        {
                            "challenge_token": r.json()["challenge_token"],
                            "code": otp(seed),
                        },
                    )
                    assert (
                        r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
                    )
                    sid = x.cookies["__Host-cisstat_auth"]
                    assert sid.startswith("s1_") and sid not in r.text
                    assert any(
                        "__Host-cisstat_auth=" in v
                        and "HttpOnly" in v
                        and "Secure" in v
                        for v in r.headers.get_list("set-cookie")
                    )
                    assert (
                        x.get("/api/v1/auth/me").json()["mfa_verified_at"]
                        and y.get("/api/v1/auth/me").status_code == 401
                    )
                    r = post(y, "login", {"login": "wire-admin", "password": password})
                    assert r.json()["purpose"] == "login"
                    r = post(
                        y,
                        "mfa/verify",
                        {
                            "challenge_token": r.json()["challenge_token"],
                            "code": otp(seed),
                        },
                    )
                    assert (
                        r.status_code == 200 and y.cookies["__Host-cisstat_auth"] != sid
                    )
                    assert (
                        y.post(
                            "/api/v1/auth/logout",
                            json={},
                            headers={
                                "Origin": origins[0],
                                "X-CSRF-Token": proof(y),
                                "X-Forwarded-Host": "evil.example",
                            },
                        ).status_code
                        == 403
                    )
                    x.cookies.set(
                        "__Host-cisstat_csrf", old, domain="localhost.local", path="/"
                    )
                    denied = x.post(
                        "/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": old}
                    )
                    assert (
                        denied.status_code == 403
                        and "x-cisstat-csrf" not in denied.headers
                    )
                    assert x.get("/api/v1/auth/me").status_code == 200
                    with httpx.Client(
                        base_url=api, verify=str(cert), trust_env=False
                    ) as direct:
                        assert (
                            direct.post(
                                "/v1/auth/logout",
                                json={},
                                headers={
                                    "Origin": origins[0],
                                    "Cookie": "__Host-cisstat_auth=" + sid,
                                },
                            ).status_code
                            == 403
                        )
                        assert (
                            direct.get(
                                "/v1/auth/me",
                                headers={
                                    "Origin": "https://evil.vercel.app",
                                    "Cookie": "__Host-cisstat_auth=" + sid,
                                },
                            ).headers.get("access-control-allow-origin")
                            is None
                        )
                        assert (
                            direct.options(
                                "/v1/auth/me",
                                headers={
                                    "Origin": origins[0],
                                    "Access-Control-Request-Method": "GET",
                                },
                            ).headers["access-control-allow-origin"]
                            == origins[0]
                        )
                    assert post(x, "logout", {}).status_code == 204
                    assert (
                        x.get("/api/v1/auth/me").status_code == 401
                        and y.get("/api/v1/auth/me").status_code == 200
                        and "__Host-cisstat_auth" not in x.cookies
                    )
                finally:
                    for c in clients:
                        c.close()
        finally:
            if sys.exc_info()[0] is not None and (temp / "servers.log").exists():
                print((temp / "servers.log").read_text()[-5000:])
            for p in processes:
                p.terminate()
            for p in processes:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
            with psycopg.connect(dsn, autocommit=True) as c:
                c.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
    print(
        "AUTH-06 two-origin HTTPS -> shared handler -> actual auth API -> PostgreSQL PASS; not Next/browser certification"
    )


if __name__ == "__main__":
    main()
