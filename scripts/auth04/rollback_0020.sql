-- EMPTY disposable schema rehearsal only; production rollback preserves data.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM auth_password_credentials) OR EXISTS(SELECT 1 FROM auth_sessions)
 OR EXISTS(SELECT 1 FROM auth_audit_outbox)
 OR EXISTS(SELECT 1 FROM auth_schema_versions WHERE version>'0020_auth04_sessions') THEN
  RAISE EXCEPTION 'nonempty or newer auth schema' USING ERRCODE='23514';
 END IF;
END $$;
DROP TABLE auth_sessions;
DROP TABLE auth_password_credentials;
DROP TABLE auth_subject_security;
DROP TABLE auth_login_limits;
DROP TABLE auth_audit_outbox;
DROP FUNCTION auth04_password_version();
DROP FUNCTION auth04_session_immutable();
DELETE FROM auth_schema_versions WHERE version='0020_auth04_sessions';
