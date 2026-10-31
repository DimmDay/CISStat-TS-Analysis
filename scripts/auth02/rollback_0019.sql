-- Development rehearsal ONLY. No CASCADE/data loss; production rollback is
-- reader-first compatibility + retained tables, not destructive downgrade.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM auth_identities) OR EXISTS (SELECT 1 FROM auth_accounts)
       OR EXISTS (SELECT 1 FROM auth_schema_versions WHERE version > '0019_auth02_identity_accounts') THEN
        RAISE EXCEPTION 'auth02 downgrade requires empty unused schema'
            USING ERRCODE='23514',CONSTRAINT='auth02_downgrade_nonempty';
    END IF;
END $$;
DROP TABLE auth_memberships;
DROP TABLE auth_external_identities;
DROP TABLE auth_accounts;
DROP TABLE auth_identities;
DROP FUNCTION auth02_membership_invariant();
DROP FUNCTION auth02_membership_write();
DROP FUNCTION auth02_account_update();
DROP FUNCTION auth02_external_update();
DROP FUNCTION auth02_identity_update();
DELETE FROM auth_schema_versions WHERE version='0019_auth02_identity_accounts';
