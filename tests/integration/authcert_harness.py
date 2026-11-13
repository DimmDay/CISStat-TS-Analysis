"""AUTH-CERT deployment-like harness (design D2/D3/D6, docs/authcert/design.md).

One disposable PostgreSQL database = one production-like deployment: the full
migration chain 0019→0035 is applied by the real migrator, the real
``apps.api.main`` app is served through its own lifespan in required storage
mode, and every oracle drives the live HTTP surface (first-party cookies,
CSRF, Origin) of a real deployment. Preparation (identities, passwords, worker
service keys) uses the same trusted service layer the existing native suites
use; the acceptance assertions never bypass HTTP.
"""

import os
import secrets
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]

PASS = "A durable acceptance passphrase!"
STANDALONE = "https://datasetup.ru"
EMBEDDED = "https://embedded.datasetup.ru"
ORIGINS = f"{STANDALONE},{EMBEDDED}"

_server = None


def pg():
    """One shared disposable PostgreSQL 16.2 per process (unprivileged)."""
    global _server
    if _server is None:
        import pgserver

        _server = pgserver.get_server(
            tempfile.mkdtemp(prefix="authcert-pgserver-")
        )
    return _server


def suffix():
    return secrets.token_hex(5)


def mfa_env():
    import base64

    return {
        "CISSTAT_AUTH_MFA_KEYS": '{"certkey":"'
        + base64.b64encode(b"c" * 32).decode()
        + '"}',
        "CISSTAT_AUTH_MFA_ACTIVE_KEY": "certkey",
    }


class Deployment:
    """A fresh disposable database with the full 0019→0035 chain applied."""

    def __init__(self):
        base = pg().get_uri()
        assert "/postgres?" in base
        self.name = "authcert_" + uuid.uuid4().hex[:16]
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.name))
            )
        self.dsn = base.replace("/postgres?", f"/{self.name}?", 1)
        from apps.api.billing.refund_migrations import apply_migration

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            apply_migration(conn)
        # Production order: durable-store migrations BEFORE the api container
        # starts (required-mode startup probes expect migrated tables).
        from apps.api.research_runs import run_migrations
        from apps.api.session_store import PostgresSessionStore

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            run_migrations(conn)
        PostgresSessionStore(self.dsn).ensure_schema()
        from apps.api.authentication.storage import PostgresAccessStore

        self.store = PostgresAccessStore(self.dsn)
        self.tmp = tempfile.mkdtemp(prefix="authcert-data-")
        # Native suites prime the durable singletons exactly once per
        # deployment (see http()); parallel HTTP contexts must never race
        # their ensure_schema DDL against each other.
        self._primed = False
        from apps.api.workers.services import WorkerServices

        self.worker_key = WorkerServices(self.store).issue(
            kinds=["modeling", "delivery", "render"],
            reason="AUTH-CERT deployment",
        )
        self.now = datetime.now(timezone.utc)

    def stop(self):
        with psycopg.connect(pg().get_uri(), autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(self.name)
                )
            )

    # ------------------------------------------------------------- helpers

    def rows(self, table):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def personal_user(self, login, *, platform_role="external_user", plan=None):
        """Identity + password + MONO account owned by the identity."""
        from apps.api.authentication.sessions import SessionService

        with self.store.transaction() as tx:
            identity = tx.identities.create(platform_role=platform_role)
            if plan:
                account = tx.accounts.create(identity.subject_id, plan=plan)
            else:
                account = tx.accounts.create(identity.subject_id)
        SessionService(self.store).set_password(
            identity.subject_id, login, PASS
        )
        return identity, account

    def wallet(self, account_id):
        """Trusted wallet provisioning (AUTH-21 operator path, no HTTP).

        Idempotent: the paid account provisions its wallet once; repeated
        calls (issue_purchased after explicit provisioning) reuse it."""
        from apps.api.billing.wallet import WalletService

        wallet = WalletService(self.store)
        try:
            wallet.create_wallet(account_id, reason="AUTH-CERT provisioning")
        except ValueError as created:
            if "wallet already exists" not in str(created):
                raise
        return wallet

    def multi_user(self, login, *, plan="starter", seats=2):
        """Identity + password + MULTI account (native AUTH-17 order:
        create, then convert through the trusted accounts.update)."""
        identity, account = self.personal_user(login, plan=plan)
        with self.store.transaction() as tx:
            account = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                account_type="multi",
                plan=plan,
                seats=seats,
            )
        return identity, account

    def open_reservation(self, account_id, *, held_cu, reservation_id=None):
        """Fixture row in auth_reservations mirroring the coordinator
        contract (0025): wallet postings carry an FK to the reservation,
        so wallet-primitive oracles (hold/exactness/races) open the
        reservation first — the same restore-artifact fixture shape the
        native suites use for out-of-band durable rows. Returns the
        reservation id to pass to the wallet hooks."""
        import hashlib

        rid = reservation_id or uuid.uuid4()
        with self.store.transaction(readonly=True) as tx:
            account = tx.connection.execute(
                "SELECT tenant_id FROM auth_accounts WHERE account_id=%s",
                (account_id,),
            ).fetchone()
            subject = tx.connection.execute(
                "SELECT subject_id FROM auth_memberships WHERE account_id=%s"
                " AND status='active' LIMIT 1",
                (account_id,),
            ).fetchone()
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO auth_reservations(reservation_id,account_id,"
                "subject_id,tenant_id,canonical_operation,key_digest,"
                "payload_digest,admission,quote_version,held_cu,state,"
                "created_at,deadline) VALUES (%s,%s,%s,%s,"
                "'cert.wallet_fixture',%s,%s,'{}','cert-fixture',%s,"
                "'pending',%s,%s)",
                (
                    rid,
                    account_id,
                    subject["subject_id"],
                    account["tenant_id"],
                    hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                    hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                    held_cu,
                    self.now,
                    self.now + timedelta(days=1),
                ),
            )
        return rid

    def api_reservation_ctx(self, login, account, *, origin=STANDALONE):
        """Trusted coordinator context (native AUTH-21 order: session ->
        API key -> verify -> RequestContext) plus the account budgets the
        admission policy evaluates."""
        from apps.api.authentication.api_key_contract import IssueKeyBody
        from apps.api.authentication.api_keys import APIKeyService
        from apps.api.authentication.context import RequestContext
        from apps.api.authentication.sessions import SessionService
        from apps.api.billing.policy import BudgetPolicy

        session = SessionService(self.store).login(
            login, PASS, account.account_id, origin=origin
        )
        keys = APIKeyService(self.store)
        issued = keys.issue(
            session.token,
            IssueKeyBody(
                label="AUTH-CERT coordinator",
                scopes=["api.read", "api.compute", "api.write", "api.database"],
                expires_in_days=1,
            ),
            origin=origin,
        )
        event = keys.verify(issued.secret)
        with self.store.transaction(readonly=True) as tx:
            a = tx.accounts.get(event.account_id)
            u = tx.identities.get(event.subject_id)
        policy = BudgetPolicy(self.store)
        policy.create_scope(
            "account", account_id=account.account_id, reason="AUTH-CERT budgets"
        )
        policy.set_budget(
            account.account_id, "cu", limit_units=2**40, reason="AUTH-CERT budgets"
        )
        policy.set_budget(
            account.account_id,
            "concurrency",
            limit_units=4,
            reason="AUTH-CERT budgets",
        )
        return RequestContext(
            subject_id=event.subject_id,
            account_id=event.account_id,
            tenant_id=str(a.tenant_id),
            auth_method=event.auth_method,
            credential_id=event.credential_id,
            auth_session_id=event.auth_session_id,
            subject_version=u.subject_version,
            entitlement_version=a.entitlement_version,
            scopes=event.scopes,
            request_id="cert-coordinator",
        )

    def admission(self, *, cu, key=None):
        """Coordinator admission for the stateless rules entry (native
        AUTH-21 shape; cu work requires the concurrency slot)."""
        from apps.api.billing.contract import Admission, Cost

        return Admission(
            entry_id="api:GET:/v1/public/rules/templates",
            idempotency_key=key or ("cert-" + uuid.uuid4().hex[:12]),
            resource_kind="stateless",
            resource_id="cert-wallet-input",
            payload={"n": 80},
            cost=Cost(micro_cu=cu, version="test-only/1"),
            deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
            slots=1 if cu else 0,
        )

    def reserve_start(self, ctx, *, cu, key=None):
        """Trusted reserve→start through the real coordinator (the reserve
        itself pins the wallet — the native AUTH-12/21 race surface)."""
        from apps.api.billing.coordinator import ReservationCoordinator

        coordinator = ReservationCoordinator(self.store)
        receipt = coordinator.reserve(ctx, self.admission(cu=cu, key=key))
        coordinator.start(
            ctx, receipt.reservation_id, expected_version=receipt.version
        )
        return receipt

    def issue_purchased(self, account_id, units):
        wallet = self.wallet(account_id)
        lot = wallet.issue_purchased(
            account_id,
            units,
            origin_order="cert-" + uuid.uuid4().hex[:12],
            reason="AUTH-CERT purchased lot",
        )
        return wallet, lot

    # ------------------------------------------------------- HTTP surface

    @contextmanager
    def http(self):
        """Full apps.api.main through its real lifespan in required mode."""
        import apps.api.main as main_module
        from apps.api import research_runs, session_store
        from apps.api.artifact_store import ArtifactObjectStore
        from fastapi.testclient import TestClient

        env = {
            "DATABASE_URL": self.dsn,
            "CISSTAT_AUTH_DATABASE_URL": self.dsn,
            "CISSTAT_STORAGE_MODE": "required",
            "CISSTAT_SESSION_BACKEND": "postgres",
            "CISSTAT_IDENTITY_MODE": "session_scoped",
            "CISSTAT_DATA_DIR": self.tmp,
            "CISSTAT_WORKER_KEY": self.worker_key,
            "CISSTAT_WORKER_PROOF_DIR": os.path.join(self.tmp, "proof"),
            "CISSTAT_DELIVERY_WORKER_ENABLED": "0",
            "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED": "0",
            "CISSTAT_DEMO_SWEEPER_ENABLED": "0",
            "CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL": "0",
            "CISSTAT_AUTH_ALLOWED_ORIGINS": ORIGINS,
            "CISSTAT_TOPUP_REFUND_DAYS": "14",
        }
        env.update(mfa_env())
        env["CISSTAT_AUTH_CSRF_KEY"] = "cert-csrf-key-0123456789abcdef-0123456789"
        previous_state = getattr(main_module.app.state, "auth_access_store", None)
        resets = (
            session_store.reset_session_store_for_testing,
            research_runs.reset_research_run_store_for_testing,
            research_runs.reset_dataset_file_store_for_testing,
        )
        with mock.patch.dict(os.environ, env):
            if not self._primed:
                # Prime the audit sink BEFORE serving: its first connect
                # re-runs the durable DDL, and doing that lazily INSIDE the
                # first upload deadlocks against the same request's own
                # trace_events transaction (two-connection self-deadlock).
                # Production orders migration before the api container
                # starts; the harness replays exactly that order.
                from apps.api.security_audit import (
                    get_audit_sink,
                    set_audit_sink_for_testing,
                )

                set_audit_sink_for_testing(None)
                get_audit_sink()._connect().close()
                # Same order contract for the session/runs singletons: their
                # ensure_schema/ready probes run DDL, which must never race
                # an in-flight request transaction. The prime runs exactly
                # once per deployment: parallel HTTP contexts (AC12 race)
                # reuse the ready singleton instead of racing ensure_schema
                # DDL against each other (AccessExclusive/ShareLock
                # deadlock was reproduced on the CI native job).
                for reset in resets:
                    reset()
                session_store.get_session_store().readiness_probe()
                research_runs.get_research_run_store().readiness_probe()
                self._primed = True
            main_module.app.state.auth_access_store = self.store
            try:
                with TestClient(main_module.app, base_url=STANDALONE) as client:
                    yield client
            finally:
                main_module.app.state.auth_access_store = previous_state

    # ------------------------------------------------- HTTP step helpers

    @staticmethod
    def csrf(client, origin=STANDALONE):
        response = client.get(
            "/v1/auth/csrf",
            headers={"Origin": origin, "X-CSRF-Request": "1"},
        )
        assert response.status_code == 200, response.text
        return response.json()["csrf_token"]

    @staticmethod
    def post(client, path, *, origin=STANDALONE, json=None, csrf=True):
        """First-party mutation: CSRF proof + exact Origin."""
        headers = {"Origin": origin}
        if csrf:
            headers["X-CSRF-Token"] = Deployment.csrf(client, origin)
        return client.post(path, json=json, headers=headers)

    @staticmethod
    def login(client, login, password=PASS, origin=STANDALONE, **extra):
        """Personal password login over real CSRF/Origin transport."""
        response = Deployment.post(
            client,
            "/v1/auth/login",
            origin=origin,
            json={"login": login, "password": password, **extra},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] == "authenticated":
            return body
        assert body["status"] == "account_required", response.text
        return body

    def admin_client(self, client):
        """One-time MFA bootstrap admin + full HTTP MFA login. The bootstrap
        is single-use per deployment; re-login via ``admin_relogin``."""
        from apps.api.authentication.mfa import MfaService

        login = "cert-admin-" + suffix()
        mfa = MfaService(self.store, clock=lambda: datetime.now(timezone.utc))
        rec = mfa.bootstrap(mfa.prepare_bootstrap(), login, PASS)
        first = Deployment.post(
            client,
            "/v1/auth/login",
            json={"login": login, "password": PASS},
        ).json()
        assert first["status"] == "challenge_required", first
        enrollment = Deployment.post(
            client,
            "/v1/auth/mfa/enroll",
            json={"challenge_token": first["challenge_token"]},
        ).json()
        seed = enrollment["secret"]
        self.admin_verify(client, seed, enrollment["challenge_token"])
        return {"login": login}, {"seed": seed, "login": login}

    def admin_relogin(self, client, login, seed, origin=STANDALONE, password=PASS):
        """HTTP MFA login for an already-bootstrapped admin (stored seed)."""
        first = Deployment.post(
            client,
            "/v1/auth/login",
            json={"login": login, "password": password},
            origin=origin,
        ).json()
        assert first["status"] == "challenge_required", first
        return self.admin_verify(
            client, seed, first["challenge_token"], origin=origin
        )

    def admin_verify(self, client, seed, challenge_token, origin=STANDALONE):
        """Complete an MFA challenge with the stored seed (fresh step-up).
        TOTP codes are single-use: a retry waits for the next 30s window."""
        import base64
        import time as time_module

        from apps.api.authentication.mfa_crypto import totp

        seed_bytes = base64.b32decode(seed)
        for attempt in range(2):
            window = int(datetime.now(timezone.utc).timestamp()) // 30 + attempt
            verified = Deployment.post(
                client,
                "/v1/auth/mfa/verify",
                json={
                    "challenge_token": challenge_token,
                    "code": totp(seed_bytes, window),
                },
                origin=origin,
            )
            if verified.status_code == 200:
                return verified.json()
            if attempt == 0:
                time_module.sleep(31 - time_module.time() % 30)
        assert verified.status_code == 200, verified.text

    def campaign(self, client, *, alias=None, **policy):
        """Named-admin campaign create + activate over HTTP."""
        now = datetime.now(timezone.utc)
        body = {
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "grant_minutes": 120,
            "max_grants": 50,
            "campaign_cu": 4_000_000_000,
            "participant_cu": 200_000_000,
            "campaign_concurrency": 4,
            "participant_concurrency": 2,
            "campaign_analyses": 1000,
            "participant_analyses": 5,
            "max_rows": 5000,
            "allow_upload": True,
            "allowed_origins": [STANDALONE, EMBEDDED],
        }
        body.update(policy)
        created = Deployment.post(
            client,
            "/v1/admin/demo-campaigns",
            json={
                "alias": alias or ("cert-campaign-" + suffix()),
                "policy": body,
                "reason": "AUTH-CERT campaign",
            },
        )
        assert created.status_code == 200, created.text
        campaign = created.json()
        activated = Deployment.post(
            client,
            f"/v1/admin/demo-campaigns/{campaign['campaign_id']}/activate",
            json={
                "expected_version": campaign["policy_version"],
                "reason": "AUTH-CERT activate",
            },
        )
        assert activated.status_code == 200, activated.text
        campaign["policy_version"] = activated.json()["policy_version"]
        return campaign

    def admission_codes(self, client, campaign, count=1):
        from datetime import datetime, timedelta, timezone as tz

        issued = Deployment.post(
            client,
            f"/v1/admin/demo-campaigns/{campaign['campaign_id']}/admissions",
            json={
                "expected_version": campaign["policy_version"],
                "reason": "AUTH-CERT codes",
                "count": count,
                "expires_at": (
                    datetime.now(tz.utc) + timedelta(hours=1)
                ).isoformat(),
            },
        )
        assert issued.status_code == 200, issued.text
        return issued.json()["codes"]

    @staticmethod
    def enter(client, login, password=PASS, code=None, origin=STANDALONE):
        """Forum entry over real transport: resume cookie first, then enter."""
        prepared = Deployment.post(client, "/v1/auth/demo/prepare", origin=origin)
        assert prepared.status_code == 200, prepared.text
        body = {"login": login, "password": password}
        if code:
            body["admission_code"] = code
        response = Deployment.post(
            client, "/v1/auth/demo/enter", origin=origin, json=body
        )
        assert response.status_code == 200, response.text
        return response.json()

    @staticmethod
    def me(client, origin=STANDALONE):
        response = client.get("/v1/auth/me", headers={"Origin": origin})
        assert response.status_code == 200, response.text
        return response.json()

    @staticmethod
    def demo_me(client, origin=STANDALONE):
        response = client.get("/v1/auth/demo/me", headers={"Origin": origin})
        assert response.status_code == 200, response.text
        return response.json()

    @staticmethod
    def upload(client, rows=120, *, origin=STANDALONE, name="cert-monthly.csv"):
        """Bounded CSV upload for the §10 pipeline oracle. The certified
        fixture shape (native AUTH-16 pipeline): one row per date with an
        explicit 12-month seasonality — the shape the bounded modeling
        stage is certified on (the passport refuses duplicate dates)."""
        import io

        buffer = io.BytesIO()
        buffer.write(b"date,value\n")
        for i in range(rows):
            day = f"{2020 + i // 12}-{(i % 12) + 1:02d}-15"
            buffer.write(f"{day},{100 + i + ((i % 12) - 6) * 2}\n".encode())
        response = client.post(
            "/v1/internal/upload",
            files={"file": (name, buffer.getvalue(), "text/csv")},
            headers={
                "Origin": origin,
                "X-CSRF-Token": Deployment.csrf(client, origin),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()
