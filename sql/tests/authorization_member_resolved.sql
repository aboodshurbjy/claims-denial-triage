-- severity: warn
-- Authorizations whose member could not be matched to the roster.
SELECT auth_number, medicaid_id_on_auth FROM object.authorization WHERE member_id IS NULL;
