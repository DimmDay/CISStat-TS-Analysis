"""Personal team authority; state + receipt + mandatory audit share one commit."""

import hashlib
import json
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from apps.api.accounts.entitlements import account_is_active
from apps.api.accounts.lifecycle import AccountLifecycle
from apps.api.authentication.context import auth_error
from apps.api.authentication.mfa import session_mfa
from apps.api.authentication.sessions import SessionService, boundary, token_digest
from apps.api.authentication.storage import PostgresAccessStore

from .team_contract import (
    Accept,
    Command,
    Convert,
    Invite,
    SeatRequest,
    Transfer,
    invitation_digest,
)
from .team_migrations import check_schema


def audit(c, actor, aid, operation, reason, *, via="auth_session", **details):
    from apps.api.security_audit import build_audit_record

    record = build_audit_record(
        "auth_membership_changed",
        "allowed",
        actor_subject=str(actor),
        actor_via=via,
        resource_kind="account_membership",
        resource_id=str(aid),
        policy_basis="AUTH-17 atomic team command",
        details={"command": operation, "reason": reason, **details},
    )
    c.execute(
        "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
        (record["audit_id"], json.dumps(record)),
    )


class TeamService(SessionService):
    def __init__(self, store=None, clock=None):
        super().__init__(store or PostgresAccessStore.from_env(), clock)

    def _personal(self, c, token, origin, extra=()):
        check_schema(c)
        digest = token_digest(token)
        hint = c.execute(
            "SELECT subject_id FROM auth_sessions WHERE token_hash=%s", (digest,)
        ).fetchone()
        if not hint:
            auth_error(401, "invalid_credential")
        for sid in sorted(
            {hint["subject_id"], *(UUID(str(x)) for x in extra if x)}, key=str
        ):
            self._identity(c, sid)
        row = self._load(c, digest, touch=True)
        if origin is not None and row["origin"] != origin:
            auth_error(401, "invalid_credential")
        if (
            row.get("demo_grant_id")
            or c.execute(
                "SELECT kind FROM auth_identities WHERE subject_id=%s",
                (row["subject_id"],),
            ).fetchone()["kind"]
            != "person"
        ):
            auth_error(403, "team_unavailable")
        return row

    def _account(self, c, aid, actor, *, current=True):
        row = c.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE", (aid,)
        ).fetchone()
        if not row or (current and row["account_id"] != actor["account_id"]):
            auth_error(404, "account_not_found")
        if not account_is_active(row, now=self._now(c)):
            auth_error(403, "account_expired")
        if c.execute(
            "SELECT 1 FROM auth_demo_grants WHERE account_id=%s", (aid,)
        ).fetchone():
            auth_error(403, "team_unavailable")
        return row

    @staticmethod
    def _member(c, aid, sid):
        return c.execute(
            "SELECT * FROM auth_memberships WHERE account_id=%s AND subject_id=%s AND status='active'",
            (aid, sid),
        ).fetchone()

    def _owner(self, c, a, actor):
        m = self._member(c, a["account_id"], actor["subject_id"])
        if not m or m["account_role"] != "owner":
            auth_error(403, "owner_required")
        if a["plan"] == "demo":
            auth_error(403, "team_unavailable")

    def _fresh(self, c, actor):
        now = self._now(c)
        stamp = session_mfa(c, actor)
        factor = c.execute(
            "SELECT 1 FROM auth_mfa_factors WHERE subject_id=%s AND revoked_at IS NULL",
            (actor["subject_id"],),
        ).fetchone()
        if now - actor["auth_time"] > timedelta(minutes=5) or (
            factor and (stamp is None or now - stamp > timedelta(minutes=5))
        ):
            auth_error(403, "recent_login_required")

    @staticmethod
    def _version(a, version):
        if a["entitlement_version"] != version:
            auth_error(409, "account_version_conflict")

    @staticmethod
    def _digest(body):
        return hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()

    def _replay(self, c, a, actor, op, body):
        kh = self._digest(body.idempotency_key)
        payload = body.model_dump(mode="json")
        if isinstance(body, Accept):
            payload["invitation_token_hash"] = invitation_digest(
                body.invitation_token.get_secret_value()
            )
            payload.pop("invitation_token")
        bh = self._digest(payload)
        row = c.execute(
            "SELECT body_hash,response FROM auth_team_commands WHERE account_id=%s AND subject_id=%s AND operation=%s AND key_hash=%s",
            (a["account_id"], actor["subject_id"], op, kh),
        ).fetchone()
        if row and row["body_hash"] != bh:
            auth_error(409, "idempotency_conflict")
        return (row["response"] if row else None), kh, bh

    def _record(self, c, a, actor, op, body, hashes, result):
        c.execute(
            "INSERT INTO auth_team_commands(command_id,account_id,subject_id,operation,key_hash,body_hash,response,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (
                uuid4(),
                a["account_id"],
                actor["subject_id"],
                op,
                *hashes,
                json.dumps(result, default=str),
                self._now(c),
            ),
        )
        audit(
            c,
            actor["subject_id"],
            a["account_id"],
            op,
            body.reason,
            before_version=a["entitlement_version"],
        )
        return result

    def _cancel_pending(self, c, aid):
        now = self._now(c)
        c.execute(
            "UPDATE auth_invitations SET revoked_at=%s WHERE account_id=%s AND consumed_at IS NULL AND revoked_at IS NULL",
            (now, aid),
        )
        c.execute(
            "UPDATE auth_seat_requests SET state='rejected',completed_at=%s WHERE account_id=%s AND state='pending'",
            (now, aid),
        )

    def _summary(self, c, a, actor):
        members = c.execute(
            "SELECT m.subject_id,m.account_role,m.status,m.joined_at,COALESCE(p.login,m.subject_id::text) AS label FROM auth_memberships m LEFT JOIN auth_password_credentials p USING(subject_id) WHERE account_id=%s ORDER BY (m.status='active') DESC,m.joined_at,m.subject_id LIMIT 1001",
            (a["account_id"],),
        ).fetchall()
        active = c.execute(
            "SELECT count(*) AS n FROM auth_memberships WHERE account_id=%s AND status='active'",
            (a["account_id"],),
        ).fetchone()["n"]
        mine = self._member(c, a["account_id"], actor["subject_id"])
        owner = bool(mine and mine["account_role"] == "owner")
        return {
            **{
                k: a[k]
                for k in (
                    "account_id",
                    "tenant_id",
                    "account_type",
                    "plan",
                    "seats",
                    "entitlement_version",
                    "plan_expires_at",
                )
            },
            "occupied": active,
            "free_seats": max(0, a["seats"] - active),
            "can_manage": owner and a["plan"] != "demo",
            "members": members
            if owner
            else [m for m in members if m["subject_id"] == actor["subject_id"]],
            "invitations": c.execute(
                "SELECT invitation_id,target_subject_id,email,created_at,expires_at,consumed_at,revoked_at FROM auth_invitations WHERE account_id=%s ORDER BY created_at DESC LIMIT 100",
                (a["account_id"],),
            ).fetchall()
            if owner
            else [],
            "seat_requests": c.execute(
                "SELECT request_id,seats,state,created_at,expires_at FROM auth_seat_requests WHERE account_id=%s ORDER BY created_at DESC LIMIT 100",
                (a["account_id"],),
            ).fetchall()
            if owner
            else [],
        }

    @boundary
    def list_accounts(self, token, origin=None):
        with self._tx() as tx:
            c = tx.connection
            actor = self._personal(c, token, origin)
            rows = c.execute(
                "SELECT a.account_id,a.account_type,a.plan,a.status,a.seats,a.entitlement_version,m.account_role FROM auth_accounts a JOIN auth_memberships m USING(account_id) WHERE m.subject_id=%s AND m.status='active' AND a.status='active' AND (a.plan_expires_at IS NULL OR a.plan_expires_at>%s) AND NOT EXISTS(SELECT 1 FROM auth_demo_grants g WHERE g.account_id=a.account_id) ORDER BY a.created_at,a.account_id LIMIT 100",
                (actor["subject_id"], self._now(c)),
            ).fetchall()
            return {
                "accounts": rows,
                "current_account_id": actor["account_id"],
                "subject_id": actor["subject_id"],
            }

    @boundary
    def show(self, token, origin, aid):
        with self._tx() as tx:
            c = tx.connection
            actor = self._personal(c, token, origin)
            a = self._account(c, aid, actor)
            if not self._member(c, aid, actor["subject_id"]):
                auth_error(404, "account_not_found")
            return self._summary(c, a, actor)

    @boundary
    def invite(self, token, origin, aid, body: Invite):
        body = Invite.model_validate(body.model_dump())
        with self._tx() as tx:
            c = tx.connection
            actor = self._personal(c, token, origin)
            a = self._account(c, aid, actor)
            self._owner(c, a, actor)
            prior, kh, bh = self._replay(c, a, actor, "invite", body)
            if prior:
                return prior
            self._version(a, body.expected_version)
            if a["account_type"] != "multi":
                auth_error(409, "multi_required")
            pending = c.execute(
                "SELECT count(*) AS n FROM auth_invitations WHERE account_id=%s AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>%s",
                (aid, self._now(c)),
            ).fetchone()["n"]
            if pending >= 100:
                auth_error(429, "invitation_limit")
            target = body.target_subject_id
            if target:
                if not c.execute(
                    "SELECT 1 FROM auth_identities u WHERE subject_id=%s AND kind='person' AND status='active' AND NOT EXISTS(SELECT 1 FROM auth_demo_grants g WHERE g.subject_id=u.subject_id)",
                    (target,),
                ).fetchone():
                    auth_error(404, "invitation_unavailable")
                if self._member(c, aid, target):
                    auth_error(409, "already_member")
            else:
                hits = c.execute(
                    "SELECT DISTINCT subject_id FROM auth_external_identities WHERE lower(email)=%s AND email_verified",
                    (body.email,),
                ).fetchall()
                if len(hits) == 1:
                    target = hits[0]["subject_id"]
            raw = "i17_" + secrets.token_urlsafe(32)
            iid = uuid4()
            now = self._now(c)
            c.execute(
                "INSERT INTO auth_invitations(invitation_id,account_id,inviter_id,target_subject_id,email,token_hash,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    iid,
                    aid,
                    actor["subject_id"],
                    target,
                    body.email,
                    invitation_digest(raw),
                    now,
                    now + timedelta(hours=body.ttl_hours),
                ),
            )
            result = {"invitation_id": str(iid), "token_available": False}
            self._record(c, a, actor, "invite", body, (kh, bh), result)
            return {**result, "invitation_token": raw, "token_available": True}

    @boundary
    def accept(self, token, origin, body: Accept):
        body = Accept.model_validate(body.model_dump())
        digest = invitation_digest(body.invitation_token.get_secret_value())
        with self._tx() as tx:
            c = tx.connection
            hint = c.execute(
                "SELECT * FROM auth_invitations WHERE token_hash=%s", (digest,)
            ).fetchone()
            actor = self._personal(
                c, token, origin, extra=(hint["inviter_id"],) if hint else ()
            )
            if not hint:
                auth_error(404, "invitation_unavailable")
            a = self._account(c, hint["account_id"], actor, current=False)
            inv = c.execute(
                "SELECT * FROM auth_invitations WHERE invitation_id=%s FOR UPDATE",
                (hint["invitation_id"],),
            ).fetchone()
            if (
                inv["target_subject_id"]
                and inv["target_subject_id"] != actor["subject_id"]
            ):
                auth_error(404, "invitation_unavailable")
            if inv["email"]:
                verified = c.execute(
                    "SELECT DISTINCT subject_id FROM auth_external_identities WHERE lower(email)=%s AND email_verified",
                    (inv["email"],),
                ).fetchall()
                if (
                    len(verified) != 1
                    or verified[0]["subject_id"] != actor["subject_id"]
                ):
                    auth_error(404, "invitation_unavailable")
            prior, kh, bh = self._replay(c, a, actor, "accept", body)
            if inv["consumed_at"] is not None:
                if inv["consumed_by"] != actor["subject_id"] or not self._member(
                    c, a["account_id"], actor["subject_id"]
                ):
                    auth_error(409, "invitation_consumed")
                return {"accepted": True, "account_id": str(a["account_id"])}
            inviter = self._member(c, a["account_id"], inv["inviter_id"])
            identity = c.execute(
                "SELECT status FROM auth_identities WHERE subject_id=%s",
                (inv["inviter_id"],),
            ).fetchone()
            if (
                inv["revoked_at"] is not None
                or self._now(c) >= inv["expires_at"]
                or not inviter
                or inviter["account_role"] != "owner"
                or not identity
                or identity["status"] != "active"
            ):
                auth_error(404, "invitation_unavailable")
            if a["account_type"] != "multi" or a["plan"] == "demo":
                auth_error(403, "team_unavailable")
            if prior:
                return prior
            member = self._member(c, a["account_id"], actor["subject_id"])
            if not member:
                used = c.execute(
                    "SELECT count(*) AS n FROM auth_memberships WHERE account_id=%s AND status='active'",
                    (a["account_id"],),
                ).fetchone()["n"]
                if used >= a["seats"]:
                    auth_error(409, "seat_capacity_exhausted")
                old = c.execute(
                    "SELECT status FROM auth_memberships WHERE account_id=%s AND subject_id=%s",
                    (a["account_id"], actor["subject_id"]),
                ).fetchone()
                if old:
                    c.execute(
                        "UPDATE auth_memberships SET status='active',account_role='member' WHERE account_id=%s AND subject_id=%s",
                        (a["account_id"], actor["subject_id"]),
                    )
                else:
                    c.execute(
                        "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'member')",
                        (a["account_id"], actor["subject_id"]),
                    )
                AccountLifecycle._invalidate(
                    c, a["account_id"], self._now(c), actor["subject_id"]
                )
            c.execute(
                "UPDATE auth_invitations SET consumed_at=%s,consumed_by=%s WHERE invitation_id=%s",
                (self._now(c), actor["subject_id"], inv["invitation_id"]),
            )
            result = {"accepted": True, "account_id": str(a["account_id"])}
            return self._record(c, a, actor, "accept", body, (kh, bh), result)

    @boundary
    def command(self, token, origin, aid, op, body, *, target=None):
        cls = {
            "convert": Convert,
            "transfer": Transfer,
            "seat-request": SeatRequest,
            "remove": Command,
            "revoke-invite": Command,
            "cancel-seat-request": Command,
        }.get(op)
        if cls is None:
            auth_error(422, "invalid_request")
        body = cls.model_validate(body.model_dump())
        target = (
            UUID(str(target)) if target else getattr(body, "target_subject_id", None)
        )
        with self._tx() as tx:
            c = tx.connection
            actor = self._personal(
                c,
                token,
                origin,
                extra=(target,) if op in ("remove", "transfer") else (),
            )
            a = self._account(c, aid, actor)
            mine = self._member(c, aid, actor["subject_id"])
            if not mine:
                auth_error(404, "account_not_found")
            canonical = op + (":" + str(target) if target else "")
            prior, kh, bh = self._replay(c, a, actor, canonical, body)
            if prior:
                return prior
            if op != "remove" or target != actor["subject_id"]:
                self._owner(c, a, actor)
            self._version(a, body.expected_version)
            now = self._now(c)
            result = {"ok": True}
            if op == "convert":
                if body.account_type != a["account_type"]:
                    if body.account_type == "mono":
                        members = c.execute(
                            "SELECT count(*) AS n FROM auth_memberships WHERE account_id=%s AND status='active'",
                            (aid,),
                        ).fetchone()["n"]
                        obligations = c.execute(
                            "SELECT 1 FROM auth_reservations WHERE account_id=%s AND state IN ('pending','running') LIMIT 1",
                            (aid,),
                        ).fetchone()
                        workers = c.execute(
                            "SELECT 1 FROM auth_worker_jobs WHERE account_id=%s AND state IN ('queued','running','uncertain') LIMIT 1",
                            (aid,),
                        ).fetchone()
                        if a["seats"] != 1 or members != 1 or obligations or workers:
                            auth_error(409, "account_obligations")
                    c.execute(
                        "UPDATE auth_accounts SET account_type=%s,entitlement_version=entitlement_version+1,updated_at=%s WHERE account_id=%s",
                        (body.account_type, now, aid),
                    )
                    self._cancel_pending(c, aid)
            elif op == "transfer":
                self._fresh(c, actor)
                person = c.execute(
                    "SELECT kind,status FROM auth_identities WHERE subject_id=%s",
                    (target,),
                ).fetchone()
                if (
                    not person
                    or person["kind"] != "person"
                    or person["status"] != "active"
                    or c.execute(
                        "SELECT 1 FROM auth_demo_grants WHERE subject_id=%s", (target,)
                    ).fetchone()
                ):
                    auth_error(409, "owner_transfer_required")
                if target == actor["subject_id"] or not self._member(c, aid, target):
                    auth_error(409, "owner_transfer_required")
                c.execute(
                    "UPDATE auth_memberships SET account_role='owner' WHERE account_id=%s AND subject_id=%s",
                    (aid, target),
                )
                c.execute(
                    "UPDATE auth_memberships SET account_role='member' WHERE account_id=%s AND subject_id=%s",
                    (aid, actor["subject_id"]),
                )
                self._cancel_pending(c, aid)
                for sid in (actor["subject_id"], target):
                    AccountLifecycle._invalidate(c, aid, now, sid)
                result["session_invalidated"] = True
            elif op == "remove":
                m = self._member(c, aid, target)
                if not m:
                    auth_error(404, "member_not_found")
                owners = c.execute(
                    "SELECT count(*) AS n FROM auth_memberships WHERE account_id=%s AND status='active' AND account_role='owner'",
                    (aid,),
                ).fetchone()["n"]
                if m["account_role"] == "owner" and owners <= 1:
                    auth_error(409, "owner_transfer_required")
                c.execute(
                    "UPDATE auth_memberships SET status='revoked' WHERE account_id=%s AND subject_id=%s",
                    (aid, target),
                )
                AccountLifecycle._invalidate(c, aid, now, target)
                self._cancel_pending(c, aid)
                result["session_invalidated"] = target == actor["subject_id"]
            elif op == "revoke-invite":
                row = c.execute(
                    "SELECT * FROM auth_invitations WHERE account_id=%s AND invitation_id=%s",
                    (aid, target),
                ).fetchone()
                if not row:
                    auth_error(404, "invitation_unavailable")
                if not row["consumed_at"] and not row["revoked_at"]:
                    c.execute(
                        "UPDATE auth_invitations SET revoked_at=%s WHERE invitation_id=%s",
                        (now, target),
                    )
            elif op == "seat-request":
                if a["account_type"] != "multi":
                    auth_error(409, "multi_required")
                c.execute(
                    "UPDATE auth_seat_requests SET state='rejected',completed_at=%s WHERE account_id=%s AND state='pending' AND expires_at<=%s",
                    (now, aid, now),
                )
                if c.execute(
                    "SELECT 1 FROM auth_seat_requests WHERE account_id=%s AND state='pending'",
                    (aid,),
                ).fetchone():
                    auth_error(409, "seat_request_pending")
                rid = uuid4()
                c.execute(
                    "INSERT INTO auth_seat_requests(request_id,account_id,requested_by,seats,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        rid,
                        aid,
                        actor["subject_id"],
                        body.seats,
                        now,
                        now + timedelta(days=7),
                    ),
                )
                result = {
                    "request_id": str(rid),
                    "state": "pending",
                    "capacity_changed": False,
                }
            elif op == "cancel-seat-request":
                row = c.execute(
                    "SELECT * FROM auth_seat_requests WHERE request_id=%s AND account_id=%s",
                    (target, aid),
                ).fetchone()
                if not row:
                    auth_error(404, "seat_request_not_found")
                if row["state"] == "pending":
                    c.execute(
                        "UPDATE auth_seat_requests SET state='rejected',completed_at=%s WHERE request_id=%s",
                        (now, target),
                    )
            result["entitlement_version"] = c.execute(
                "SELECT entitlement_version FROM auth_accounts WHERE account_id=%s",
                (aid,),
            ).fetchone()["entitlement_version"]
            return self._record(c, a, actor, canonical, body, (kh, bh), result)

    @boundary
    def confirm_capacity(self, aid, rid, *, expected_version, confirmation_ref, reason):
        """Trusted AUTH-18 handoff/operator only; never a browser payment flag."""
        if (
            not isinstance(confirmation_ref, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}", confirmation_ref)
            or type(expected_version) is not int
            or expected_version < 1
            or not reason
            or not reason.strip()
        ):
            auth_error(422, "invalid_request")
        aid = UUID(str(aid))
        rid = UUID(str(rid))
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            a = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE", (aid,)
            ).fetchone()
            if not a:
                auth_error(404, "account_not_found")
            row = c.execute(
                "SELECT * FROM auth_seat_requests WHERE request_id=%s AND account_id=%s FOR UPDATE",
                (rid, aid),
            ).fetchone()
            if not row:
                auth_error(404, "seat_request_not_found")
            if row["state"] == "applied":
                if row["confirmation_ref"] != confirmation_ref:
                    auth_error(409, "idempotency_conflict")
                return {"applied": True, "request_id": str(rid)}
            self._version(a, expected_version)
            owner = self._member(c, aid, row["requested_by"])
            person = c.execute(
                "SELECT kind,status FROM auth_identities WHERE subject_id=%s",
                (row["requested_by"],),
            ).fetchone()
            if not person or person["kind"] != "person" or person["status"] != "active":
                auth_error(409, "seat_request_unavailable")
            if (
                row["state"] != "pending"
                or self._now(c) >= row["expires_at"]
                or not owner
                or owner["account_role"] != "owner"
                or not account_is_active(a, now=self._now(c))
                or a["account_type"] != "multi"
                or a["plan"] == "demo"
            ):
                auth_error(409, "seat_request_unavailable")
            if c.execute(
                "SELECT 1 FROM auth_demo_grants WHERE account_id=%s", (aid,)
            ).fetchone():
                auth_error(403, "team_unavailable")
            if c.execute(
                "SELECT 1 FROM auth_seat_requests WHERE confirmation_ref=%s",
                (confirmation_ref,),
            ).fetchone():
                auth_error(409, "idempotency_conflict")
            active = c.execute(
                "SELECT count(*) AS n FROM auth_memberships WHERE account_id=%s AND status='active'",
                (aid,),
            ).fetchone()["n"]
            if row["seats"] < active:
                auth_error(409, "seat_capacity_exhausted")
            c.execute(
                "UPDATE auth_accounts SET seats=%s,entitlement_version=entitlement_version+1,updated_at=%s WHERE account_id=%s",
                (row["seats"], self._now(c), aid),
            )
            c.execute(
                "UPDATE auth_seat_requests SET state='applied',confirmation_ref=%s,completed_at=%s WHERE request_id=%s",
                (confirmation_ref, self._now(c), rid),
            )
            audit(
                c,
                "operator:local",
                aid,
                "confirmed_capacity",
                reason,
                via="operator_cli",
                request_id=str(rid),
                seats=row["seats"],
            )
            return {"applied": True, "request_id": str(rid)}

    @boundary
    def select(self, token, origin, aid):
        with self._tx() as tx:
            c = tx.connection
            actor = self._personal(c, token, origin)
            self._account(c, aid, actor, current=False)
            if not self._member(c, aid, actor["subject_id"]):
                auth_error(404, "account_not_found")
            u = self._identity(c, actor["subject_id"])
            cred = c.execute(
                "SELECT * FROM auth_password_credentials WHERE credential_id=%s",
                (actor["credential_id"],),
            ).fetchone()
            issued = self._issue(
                c,
                u,
                cred,
                aid,
                actor["origin"],
                self._now(c),
                self._epoch(c, actor["subject_id"]),
                auth_time=actor["auth_time"],
                absolute_expires_at=actor["absolute_expires_at"],
                family_id=actor["family_id"],
            )
            proof = c.execute(
                "SELECT factor_id,verified_at FROM auth_session_mfa WHERE session_id=%s",
                (actor["session_id"],),
            ).fetchone()
            if proof:
                c.execute(
                    "INSERT INTO auth_session_mfa(session_id,factor_id,verified_at) VALUES (%s,%s,%s)",
                    (
                        UUID(issued.session["session_id"]),
                        proof["factor_id"],
                        proof["verified_at"],
                    ),
                )
            c.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE session_id=%s",
                (self._now(c), actor["session_id"]),
            )
            audit(
                c,
                actor["subject_id"],
                aid,
                "account_selected",
                "personal account selection",
            )
            return issued
