-- severity: warn
-- Claims whose patient could not be matched to the roster.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT claim_id, medicaid_id_on_claim, patient_name_on_claim FROM object.claim WHERE member_id IS NULL;
