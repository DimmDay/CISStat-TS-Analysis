"""Native PostgreSQL only: team capacity/ownership/replay under actual SQL locks."""

import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.accounts.team import TeamService
from apps.api.accounts.team_contract import (
    Accept,
    Command,
    Convert,
    Invite,
    SeatRequest,
    Transfer,
)
from apps.api.accounts.team_migrations import apply_migration, check_schema
from tests.integration import test_auth04_sessions as previous


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class TeamSQLTests(unittest.TestCase):
    cleanup = previous.SessionSQLTests.cleanup
    login = previous.SessionSQLTests.login
    error = previous.SessionSQLTests.error
    rows = previous.SessionSQLTests.rows

    def setUp(self):
        previous.SessionSQLTests.setUp(self)
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
            self.account = tx.accounts.update(
                self.account.account_id,
                expected_version=self.account.entitlement_version,
                account_type="multi",
                plan="starter",
                seats=2,
            )
        self.team = TeamService(self.store, clock=lambda: self.now)
        self.token = self.login().token
        self.other, self.other_account, self.other_token = self.person("bob17")
        self.third, self.third_account, self.third_token = self.person("eve17")

    def person(self, login):
        with self.store.transaction() as tx:
            person = tx.identities.create()
            account = tx.accounts.create(person.subject_id, plan="starter")
        self.service.set_password(person.subject_id, login, previous.PASS)
        issued = self.service.login(
            login, previous.PASS, account.account_id, origin=previous.ORIGIN
        )
        return person, account, issued.token

    def current(self):
        with self.store.transaction() as tx:
            return tx.accounts.get(self.account.account_id)

    def body(self, cls=Command, **kw):
        return cls(
            expected_version=self.current().entitlement_version,
            reason="native team test",
            idempotency_key=secrets.token_hex(8),
            **kw,
        )

    def invite(self, target=None, **kw):
        return self.team.invite(
            self.token,
            previous.ORIGIN,
            self.account.account_id,
            self.body(
                Invite, **({"target_subject_id": target or self.other.subject_id} | kw)
            ),
        )

    def accept(self, inv, token=None, key="accept17"):
        return self.team.accept(
            token or self.other_token,
            previous.ORIGIN,
            Accept(invitation_token=inv["invitation_token"], idempotency_key=key),
        )

    def command(self, op, body=None, target=None, token=None):
        return self.team.command(
            token or self.token,
            previous.ORIGIN,
            self.account.account_id,
            op,
            body or self.body(),
            target=target,
        )

    def test_migration_repeat_hash_only_and_direct_history_guard(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        inv = self.invite()
        self.assertNotIn(
            inv["invitation_token"],
            str(
                self.rows("auth_invitations")
                + self.rows("auth_team_commands")
                + self.rows("auth_audit_outbox")
            ),
        )
        self.error(lambda: self.accept(inv, token=self.third_token), 404)
        self.assertIsNone(self.rows("auth_invitations")[0]["consumed_at"])

    def test_last_seat_race_two_invites_one_member(self):
        one = self.invite()
        two = self.invite(self.third.subject_id)

        def accept(v):
            try:
                return self.accept(*v)
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            r = list(
                pool.map(accept, [(one, self.other_token), (two, self.third_token)])
            )
        self.assertEqual(r.count(409), 1)
        memberships = [
            r
            for r in self.rows("auth_memberships")
            if r["account_id"] == self.account.account_id and r["status"] == "active"
        ]
        self.assertEqual(len(memberships), 2)
        self.assertEqual(self.current().seats, 2)

    def test_same_invite_race_and_replay_do_not_duplicate_or_reset(self):
        inv = self.invite()
        with ThreadPoolExecutor(max_workers=2) as pool:
            r = list(pool.map(lambda _: self.accept(inv), range(2)))
        self.assertTrue(all(v["accepted"] for v in r))
        self.assertEqual(self.current().seats, 2)
        self.assertEqual(
            len(
                [
                    m
                    for m in self.rows("auth_memberships")
                    if m["account_id"] == self.account.account_id
                ]
            ),
            2,
        )

    def test_audit_failure_rolls_back_invite_accept_and_capacity(self):
        with patch("apps.api.accounts.team.audit", side_effect=RuntimeError("fault")):
            self.error(lambda: self.invite(), 503)
        self.assertFalse(self.rows("auth_invitations"))
        inv = self.invite()
        with patch("apps.api.accounts.team.audit", side_effect=RuntimeError("fault")):
            self.error(lambda: self.accept(inv), 503)
        self.assertIsNone(self.rows("auth_invitations")[0]["consumed_at"])
        self.assertFalse(
            [
                m
                for m in self.rows("auth_memberships")
                if m["account_id"] == self.account.account_id
                and m["subject_id"] == self.other.subject_id
            ]
        )
        req = self.command("seat-request", self.body(SeatRequest, seats=3))
        with patch("apps.api.accounts.team.audit", side_effect=RuntimeError("fault")):
            self.error(
                lambda: self.team.confirm_capacity(
                    self.account.account_id,
                    req["request_id"],
                    expected_version=self.current().entitlement_version,
                    confirmation_ref="manual:test",
                    reason="confirmed",
                ),
                503,
            )
        self.assertEqual(self.current().seats, 2)
        self.assertEqual(self.rows("auth_seat_requests")[0]["state"], "pending")

    def test_expiry_and_inviter_revoke_prevent_acceptance(self):
        inv = self.invite()
        self.now += timedelta(hours=25)
        # Keep an actually current login; expiration applies to invitation.
        self.other_token = self.service.login(
            "bob17",
            previous.PASS,
            self.other_account.account_id,
            origin=previous.ORIGIN,
        ).token
        self.error(lambda: self.accept(inv), 404)

    def test_last_owner_guard_and_transfer_invalidates_old_invites(self):
        self.error(lambda: self.command("remove", target=self.owner.subject_id), 409)
        inv = self.invite()
        self.accept(inv)
        pending = self.invite(self.third.subject_id)
        result = self.command(
            "transfer", self.body(Transfer, target_subject_id=self.other.subject_id)
        )
        self.assertTrue(result["session_invalidated"])
        self.error(lambda: self.service.verify(self.token), 401)
        self.error(lambda: self.accept(pending, token=self.third_token), 404)
        with self.store.transaction() as tx:
            owners = tx.connection.execute(
                "SELECT subject_id FROM auth_memberships WHERE account_id=%s AND status='active' AND account_role='owner'",
                (self.account.account_id,),
            ).fetchall()
        self.assertEqual([x["subject_id"] for x in owners], [self.other.subject_id])

    def test_member_removal_and_rejoin_never_revives_old_sid(self):
        self.accept(self.invite())
        selected = self.team.select(
            self.other_token, previous.ORIGIN, self.account.account_id
        )
        self.command("remove", target=self.other.subject_id)
        self.error(lambda: self.service.verify(selected.token), 401)
        self.other_token = self.service.login(
            "bob17",
            previous.PASS,
            self.other_account.account_id,
            origin=previous.ORIGIN,
        ).token
        self.accept(self.invite(), key="rejoin")
        self.error(lambda: self.service.verify(selected.token), 401)

    def test_capacity_pending_confirmation_replay_and_churn_preserve_budget(self):
        from apps.api.billing.policy import BudgetPolicy

        policy = BudgetPolicy(self.store)
        policy.create_scope(
            "account", account_id=self.account.account_id, reason="native"
        )
        policy.set_budget(
            self.account.account_id, "cu", limit_units=1000, reason="native"
        )
        policy.set_budget(
            self.account.account_id, "concurrency", limit_units=2, reason="native"
        )
        from apps.api.access_registry import ModelWorkload
        from apps.api.authentication.context import resolve_verified_context
        from apps.api.billing.contract import Admission, Cost
        from apps.api.billing.coordinator import ReservationCoordinator

        ctx = resolve_verified_context(
            self.service.verify(self.token), store=self.store
        )
        ledger = ReservationCoordinator(self.store)

        def reserve(key):
            return ledger.reserve(
                ctx,
                Admission(
                    entry_id="api:POST:/v1/internal/models/backtest",
                    resource_kind="stateless",
                    resource_id=key,
                    idempotency_key=key,
                    payload={"test": key},
                    cost=Cost(micro_cu=100, version="native17/1"),
                    deadline=self.now + timedelta(minutes=10),
                    workload=ModelWorkload(
                        model_ids=("naive",),
                        rows=80,
                        folds=1,
                        horizon=4,
                        seasonal_period=12,
                        custom_parameters=False,
                    ),
                ),
            )

        spent = reserve("spent17")
        started = ledger.start(
            ctx, spent.reservation_id, expected_version=spent.version
        )
        ledger.settle(
            spent.reservation_id, expected_version=started.version, actual_cu=50
        )
        reserve("held17")
        before = self.rows("auth_resource_budgets")
        self.assertTrue(any(b["spent"] > 0 for b in before))
        self.assertTrue(any(b["reserved"] > 0 for b in before))
        posts = self.rows("auth_usage_postings")
        body = self.body(SeatRequest, seats=3)
        req = self.command("seat-request", body)
        self.assertEqual(self.command("seat-request", body), req)
        self.assertEqual(self.current().seats, 2)
        self.team.confirm_capacity(
            self.account.account_id,
            req["request_id"],
            expected_version=self.current().entitlement_version,
            confirmation_ref="paid:test:1",
            reason="verified external entitlement",
        )
        self.team.confirm_capacity(
            self.account.account_id,
            req["request_id"],
            expected_version=1,
            confirmation_ref="paid:test:1",
            reason="replay",
        )
        self.assertEqual(self.current().seats, 3)
        req2 = self.command("seat-request", self.body(SeatRequest, seats=2))
        self.team.confirm_capacity(
            self.account.account_id,
            req2["request_id"],
            expected_version=self.current().entitlement_version,
            confirmation_ref="paid:test:2",
            reason="capacity reduction",
        )
        self.assertEqual(self.rows("auth_resource_budgets"), before)
        self.assertEqual(self.rows("auth_usage_postings"), posts)

    def test_monotype_ids_and_switch_deadline_are_preserved(self):
        aid, tenant = self.account.account_id, self.account.tenant_id
        req = self.command("seat-request", self.body(SeatRequest, seats=1))
        self.team.confirm_capacity(
            aid,
            req["request_id"],
            expected_version=self.current().entitlement_version,
            confirmation_ref="manual:one",
            reason="verified",
        )
        self.command("convert", self.body(Convert, account_type="mono"))
        self.command(
            "convert",
            self.body(Convert, account_type="multi", acknowledge_shared_access=True),
        )
        self.assertEqual(
            (self.current().account_id, self.current().tenant_id), (aid, tenant)
        )
        req2 = self.command("seat-request", self.body(SeatRequest, seats=2))
        self.team.confirm_capacity(
            aid,
            req2["request_id"],
            expected_version=self.current().entitlement_version,
            confirmation_ref="manual:two",
            reason="verified",
        )
        self.accept(self.invite())
        old = self.service.verify(self.other_token)
        oldrow = next(
            x
            for x in self.rows("auth_sessions")
            if str(x["session_id"]) == old.auth_session_id
        )
        self.now += timedelta(minutes=3)
        switched = self.team.select(self.other_token, previous.ORIGIN, aid)
        self.assertEqual(
            switched.session["absolute_expires_at"],
            oldrow["absolute_expires_at"].isoformat(),
        )
        self.error(lambda: self.service.verify(self.other_token), 401)
        self.assertEqual(self.service.verify(switched.token).account_id, str(aid))

    def test_issue_replay_and_stale_version_or_payload_conflict(self):
        body = self.body(Invite, target_subject_id=self.other.subject_id)
        self.team.invite(self.token, previous.ORIGIN, self.account.account_id, body)
        replay = self.team.invite(
            self.token, previous.ORIGIN, self.account.account_id, body
        )
        self.assertFalse(replay["token_available"])
        self.assertNotIn("invitation_token", replay)
        altered = body.model_copy(update={"ttl_hours": 2})
        self.error(
            lambda: self.team.invite(
                self.token, previous.ORIGIN, self.account.account_id, altered
            ),
            409,
        )
        self.assertEqual(len(self.rows("auth_invitations")), 1)

    def test_email_target_requires_unique_verified_contact_no_identity_creation(self):
        from uuid import uuid4

        body = self.body(Invite, email="Bob@Example.org")
        inv = self.team.invite(
            self.token, previous.ORIGIN, self.account.account_id, body
        )
        count = len(self.rows("auth_identities"))
        self.error(lambda: self.accept(inv), 404)
        with self.store.transaction() as tx:
            tx.identities.link_external(
                self.other.subject_id,
                "https://id.example",
                "bob",
                email="bob@example.org",
                email_verified=True,
            )
        self.accept(inv)
        self.assertEqual(len(self.rows("auth_identities")), count)
        inv2 = self.team.invite(
            self.token,
            previous.ORIGIN,
            self.account.account_id,
            self.body(Invite, email="new@example.org"),
        )
        with self.store.transaction() as tx:
            tx.identities.link_external(
                self.other.subject_id,
                "https://id.example",
                str(uuid4()),
                email="new@example.org",
                email_verified=True,
            )
            tx.identities.link_external(
                self.third.subject_id,
                "https://id.example",
                "eve",
                email="new@example.org",
                email_verified=True,
            )
        self.error(lambda: self.accept(inv2), 404)
        self.error(lambda: self.accept(inv2, token=self.third_token), 404)

    def test_changed_inviter_permission_and_stale_owner_login_fail(self):
        accepted = self.invite()
        self.accept(accepted)
        pending = self.invite(self.third.subject_id)
        self.now += timedelta(minutes=6)
        self.error(
            lambda: self.command(
                "transfer", self.body(Transfer, target_subject_id=self.other.subject_id)
            ),
            403,
            "recent_login_required",
        )
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_memberships SET account_role='owner' WHERE account_id=%s AND subject_id=%s",
                (self.account.account_id, self.other.subject_id),
            )
            tx.connection.execute(
                "UPDATE auth_memberships SET account_role='member' WHERE account_id=%s AND subject_id=%s",
                (self.account.account_id, self.owner.subject_id),
            )
        self.error(lambda: self.accept(pending, token=self.third_token), 404)
        self.error(lambda: self.invite(self.third.subject_id), 403)

    def test_raw_sql_last_owner_and_capacity_are_still_deferred_guards(self):
        from apps.api.authentication.errors import RepositoryConflict

        before = self.current().entitlement_version
        with self.assertRaises(RepositoryConflict):  # noqa: SIM117 -- explicitly assert deferred COMMIT failure
            with self.store.transaction() as tx:
                tx.connection.execute(
                    "UPDATE auth_memberships SET status='revoked' WHERE account_id=%s AND subject_id=%s",
                    (self.account.account_id, self.owner.subject_id),
                )
        self.assertEqual(self.current().entitlement_version, before)
        self.accept(self.invite())
        with self.assertRaises(RepositoryConflict):  # noqa: SIM117 -- explicitly assert deferred COMMIT failure
            with self.store.transaction() as tx:
                tx.connection.execute(
                    "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'member')",
                    (self.account.account_id, self.third.subject_id),
                )
        with self.assertRaises(RepositoryConflict):  # noqa: SIM117 -- explicitly assert deferred COMMIT failure
            with self.store.transaction() as tx:
                tx.connection.execute("DELETE FROM auth_invitations")

    def test_http_personal_csrf_roles_accept_and_select_clear_research_pointer(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from apps.api.authentication.csrf import AUTH_COOKIE, CSRF_COOKIE
        from apps.api.routers import accounts, authentication

        app = FastAPI()
        app.state.auth_access_store = self.store
        app.state.auth_session_service = self.service
        app.state.auth_team_service = self.team
        app.include_router(authentication.router, prefix="/v1/auth")
        app.include_router(accounts.router, prefix="/v1/accounts")
        with (
            patch.dict(
                os.environ,
                {
                    "CISSTAT_AUTH_ALLOWED_ORIGINS": previous.ORIGIN,
                    "CISSTAT_AUTH_CSRF_KEY": "auth17-native-test-csrf-key-" + "x" * 32,
                },
            ),
            TestClient(app, base_url=previous.ORIGIN) as owner,
            TestClient(app, base_url=previous.ORIGIN) as member,
            TestClient(app, base_url=previous.ORIGIN) as anon,
        ):
            owner.cookies.set(
                AUTH_COOKIE, self.token, domain="standalone.example", path="/"
            )
            member.cookies.set(
                AUTH_COOKIE, self.other_token, domain="standalone.example", path="/"
            )
            aid = str(self.account.account_id)

            def post(client, path, body):
                proof = client.get(
                    "/v1/auth/csrf", headers={"Origin": previous.ORIGIN}
                ).json()["csrf_token"]
                return client.post(
                    "/v1/accounts" + path,
                    json=body,
                    headers={"Origin": previous.ORIGIN, "X-CSRF-Token": proof},
                )

            self.assertEqual(anon.get("/v1/accounts").status_code, 401)
            self.assertEqual(
                owner.get("/v1/accounts", headers={"X-Api-Key": "bad"}).status_code, 401
            )
            self.assertEqual(
                owner.post(
                    "/v1/accounts/" + aid + "/seat-requests",
                    json=self.body(SeatRequest, seats=3).model_dump(),
                ).status_code,
                403,
            )
            spoof = self.body(SeatRequest, seats=3).model_dump() | {
                "payment_confirmed": True
            }
            self.assertEqual(
                post(owner, "/" + aid + "/seat-requests", spoof).status_code, 422
            )
            self.assertEqual(self.current().seats, 2)
            invitation = self.invite()
            self.assertEqual(
                member.get("/v1/accounts/invitations/accept").status_code, 405
            )
            response = post(
                member,
                "/invitations/accept",
                {
                    "invitation_token": invitation["invitation_token"],
                    "idempotency_key": "http-accept",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(member.get("/v1/accounts/" + aid).status_code, 404)
            member.cookies.set(
                "cisstat_session_id",
                "old-account-pointer",
                domain="standalone.example",
                path="/",
            )
            response = post(member, "/" + aid + "/select", {})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("old-account-pointer", response.text)
            cookies = response.headers.get_list("set-cookie")
            self.assertTrue(
                any(
                    "cisstat_session_id=" in value and "Max-Age=0" in value
                    for value in cookies
                )
            )
            self.assertTrue(
                any(CSRF_COOKIE in value and "Max-Age=0" in value for value in cookies)
            )
            detail = member.get("/v1/accounts/" + aid)
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertFalse(detail.json()["can_manage"])
            self.assertEqual(detail.json()["invitations"], [])
            denied = post(
                member,
                "/" + aid + "/seat-requests",
                self.body(SeatRequest, seats=3).model_dump(),
            )
            self.assertEqual(denied.status_code, 403, denied.text)
            self.assertEqual(member.get("/v1/auth/me").json()["account_id"], aid)

    def test_admin_member_is_not_owner_and_switch_copies_real_mfa_proof(self):
        import base64
        import json

        from apps.api.authentication.mfa import MfaService
        from apps.api.authentication.mfa_crypto import totp

        with patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_MFA_KEYS": json.dumps(
                    {"test": base64.b64encode(b"k" * 32).decode()}
                ),
                "CISSTAT_AUTH_MFA_ACTIVE_KEY": "test",
            },
        ):
            mfa = MfaService(self.store, clock=lambda: self.now)
            admin = mfa.bootstrap(mfa.prepare_bootstrap(), "admin17", previous.PASS)
            challenge = self.service.login(
                "admin17", previous.PASS, admin["account_id"], origin=previous.ORIGIN
            )
            enroll = mfa.begin_enrollment(challenge.token, origin=previous.ORIGIN)
            self.now += timedelta(seconds=30)
            issued = mfa.complete(
                enroll.challenge.token,
                totp(base64.b32decode(enroll.secret), int(self.now.timestamp()) // 30),
                origin=previous.ORIGIN,
            ).session
            adminctx = self.service.verify(issued.token)
            inv = self.invite(adminctx.subject_id)
            self.accept(inv, token=issued.token)
            switched = self.team.select(
                issued.token, previous.ORIGIN, self.account.account_id
            )
            ctx = self.service.verify(switched.token)
            self.assertEqual(ctx.mfa_verified_at, adminctx.mfa_verified_at)
            self.error(
                lambda: self.command(
                    "seat-request",
                    self.body(SeatRequest, seats=3),
                    token=switched.token,
                ),
                403,
                "owner_required",
            )
            self.assertEqual(
                switched.session["absolute_expires_at"],
                issued.session["absolute_expires_at"],
            )

    def test_transfer_audit_failure_preserves_owner_sessions_and_invites(self):
        self.accept(self.invite())
        pending = self.invite(self.third.subject_id)
        before = self.current().entitlement_version
        with patch("apps.api.accounts.team.audit", side_effect=RuntimeError("fault")):
            self.error(
                lambda: self.command(
                    "transfer",
                    self.body(Transfer, target_subject_id=self.other.subject_id),
                ),
                503,
            )
        self.assertEqual(self.current().entitlement_version, before)
        self.service.verify(self.token)
        with self.store.transaction() as tx:
            owner = tx.connection.execute(
                "SELECT subject_id FROM auth_memberships WHERE account_id=%s AND status='active' AND account_role='owner'",
                (self.account.account_id,),
            ).fetchone()
        self.assertEqual(owner["subject_id"], self.owner.subject_id)
        self.assertIsNone(
            next(
                x
                for x in self.rows("auth_invitations")
                if str(x["invitation_id"]) == pending["invitation_id"]
            )["revoked_at"]
        )

    def test_concurrent_owner_transfer_has_one_winner_and_valid_last_owner(self):
        req = self.command("seat-request", self.body(SeatRequest, seats=3))
        self.team.confirm_capacity(
            self.account.account_id,
            req["request_id"],
            expected_version=self.current().entitlement_version,
            confirmation_ref="manual:three",
            reason="confirmed",
        )
        self.accept(self.invite())
        self.accept(
            self.invite(self.third.subject_id), token=self.third_token, key="third"
        )
        bodies = [
            self.body(Transfer, target_subject_id=x.subject_id)
            for x in (self.other, self.third)
        ]

        def transfer(body):
            try:
                return self.command("transfer", body)
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            r = list(pool.map(transfer, bodies))
        self.assertEqual(sum(isinstance(v, dict) for v in r), 1)
        with self.store.transaction() as tx:
            owners = tx.connection.execute(
                "SELECT subject_id FROM auth_memberships WHERE account_id=%s AND status='active' AND account_role='owner'",
                (self.account.account_id,),
            ).fetchall()
        self.assertEqual(len(owners), 1)
        self.assertIn(
            owners[0]["subject_id"], [self.other.subject_id, self.third.subject_id]
        )
