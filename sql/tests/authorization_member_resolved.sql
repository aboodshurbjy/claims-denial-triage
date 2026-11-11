-- severity: warn
-- Authorizations whose member could not be matched to the roster.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT auth_number, medicaid_id_on_auth FROM object.authorization WHERE member_id IS NULL;
