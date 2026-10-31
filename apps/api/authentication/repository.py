"""All methods share the caller's transaction; none commit or infer ownership."""

from uuid import uuid4
from .models import Identity, ExternalIdentity
from .errors import RecordNotFound, VersionConflict


class IdentityRepository:
    def __init__(self, connection):
        self.connection = connection

    def create(self, *, kind="person", platform_role="external_user"):
        row = self.connection.execute(
            "INSERT INTO auth_identities(subject_id,kind,platform_role) VALUES (%s,%s,%s) RETURNING *",
            (uuid4(), kind, platform_role),
        ).fetchone()
        return Identity(**row)

    def get(self, subject_id):
        row = self.connection.execute(
            "SELECT * FROM auth_identities WHERE subject_id=%s", (subject_id,)
        ).fetchone()
        return Identity(**row) if row else None

    def link_external(
        self, subject_id, issuer, external_subject, *, email=None, email_verified=False
    ):
        row = self.connection.execute(
            """INSERT INTO auth_external_identities
            (subject_id,issuer,external_subject,email,email_verified) VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (subject_id, issuer, external_subject, email, email_verified),
        ).fetchone()
        return ExternalIdentity(**row)

    def by_external(self, issuer, external_subject):
        row = self.connection.execute(
            """SELECT i.* FROM auth_identities i JOIN auth_external_identities e USING(subject_id)
            WHERE e.issuer=%s AND e.external_subject=%s""",
            (issuer, external_subject),
        ).fetchone()
        return Identity(**row) if row else None

    def external_identities(self, subject_id):
        rows = self.connection.execute(
            "SELECT * FROM auth_external_identities WHERE subject_id=%s ORDER BY issuer,external_subject",
            (subject_id,),
        ).fetchall()
        return [ExternalIdentity(**row) for row in rows]

    def set_status(self, subject_id, status, *, expected_version):
        current = self.connection.execute(
            "SELECT subject_version FROM auth_identities WHERE subject_id=%s FOR UPDATE",
            (subject_id,),
        ).fetchone()
        if not current:
            raise RecordNotFound()
        if current["subject_version"] != expected_version:
            raise VersionConflict()
        row = self.connection.execute(
            """UPDATE auth_identities SET status=%s,subject_version=subject_version+1,
            updated_at=now() WHERE subject_id=%s RETURNING *""",
            (status, subject_id),
        ).fetchone()
        return Identity(**row)
