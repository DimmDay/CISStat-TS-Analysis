from uuid import uuid4
from .models import Account, Membership
from apps.api.authentication.errors import RecordNotFound, VersionConflict


class AccountRepository:
    def __init__(self, connection):
        self.connection = connection

    def create(
        self,
        owner_subject_id,
        *,
        account_type="mono",
        plan="demo",
        seats=1,
        plan_expires_at=None
    ):
        # Only server-generated IDs, no arbitrary tenant assignment parameter.
        account_id = uuid4()
        self.connection.execute(
            """INSERT INTO auth_accounts(account_id,tenant_id,account_type,plan,seats,plan_expires_at)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (account_id, uuid4(), account_type, plan, seats, plan_expires_at),
        )
        self.connection.execute(
            "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'owner')",
            (account_id, owner_subject_id),
        )
        return self.get(account_id)

    def get(self, account_id):
        row = self.connection.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s", (account_id,)
        ).fetchone()
        return Account(**row) if row else None

    def memberships(self, account_id, *, include_revoked=False):
        rows = self.connection.execute(
            """SELECT * FROM auth_memberships WHERE account_id=%s AND (%s OR status='active')
            ORDER BY joined_at,subject_id""",
            (account_id, include_revoked),
        ).fetchall()
        return [Membership(**row) for row in rows]

    def for_subject(self, subject_id):
        rows = self.connection.execute(
            """SELECT a.* FROM auth_accounts a JOIN auth_memberships m USING(account_id)
            WHERE m.subject_id=%s AND m.status='active' ORDER BY a.account_id""",
            (subject_id,),
        ).fetchall()
        return [Account(**row) for row in rows]

    def _lock(self, account_id, expected_version):
        row = self.connection.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE", (account_id,)
        ).fetchone()
        if not row:
            raise RecordNotFound()
        if row["entitlement_version"] != expected_version:
            raise VersionConflict()
        return row

    def update(
        self,
        account_id,
        *,
        expected_version,
        account_type=None,
        plan=None,
        status=None,
        seats=None
    ):
        current = self._lock(account_id, expected_version)
        row = self.connection.execute(
            """UPDATE auth_accounts SET account_type=%s,plan=%s,status=%s,seats=%s,
            entitlement_version=entitlement_version+1,updated_at=now() WHERE account_id=%s RETURNING *""",
            (
                account_type if account_type is not None else current["account_type"],
                plan if plan is not None else current["plan"],
                status if status is not None else current["status"],
                seats if seats is not None else current["seats"],
                account_id,
            ),
        ).fetchone()
        return Account(**row)

    def add_member(
        self, account_id, subject_id, *, expected_version, account_role="member"
    ):
        self._lock(account_id, expected_version)
        row = self.connection.execute(
            """INSERT INTO auth_memberships(account_id,subject_id,account_role)
            VALUES (%s,%s,%s) RETURNING *""",
            (account_id, subject_id, account_role),
        ).fetchone()
        return Membership(**row)

    def update_member(
        self,
        account_id,
        subject_id,
        *,
        expected_version,
        account_role=None,
        status=None
    ):
        self._lock(account_id, expected_version)
        row = self.connection.execute(
            """UPDATE auth_memberships SET account_role=COALESCE(%s,account_role),
            status=COALESCE(%s,status) WHERE account_id=%s AND subject_id=%s RETURNING *""",
            (account_role, status, account_id, subject_id),
        ).fetchone()
        if not row:
            raise RecordNotFound()
        return Membership(**row)
