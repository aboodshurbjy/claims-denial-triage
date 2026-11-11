-- Claim: one row per claim, linked to a resolved member where possible.
-- member_id stays NULL when nobody on the roster matches; the eligibility
-- rule turns that into a finding instead of the pipeline dropping the row.
CREATE OR REPLACE TABLE object.claim AS
SELECT
    c.claim_id,
    m.member_id,
    m.match_method      AS member_match_method,
    c.medicaid_id       AS medicaid_id_on_claim,
    c.patient_name      AS patient_name_on_claim,
    c.provider_npi      AS provider_id,
    c.service_code,
    c.date_of_service,
    c.units,
    c.billed_amount,
    c.auth_number,
    c.created_date
FROM staged.claims c
LEFT JOIN object.member_reference m
  ON m.medicaid_id IS NOT DISTINCT FROM c.medicaid_id
 AND m.first_canon IS NOT DISTINCT FROM c.first_canon
 AND m.last_norm   IS NOT DISTINCT FROM c.last_norm
 AND m.dob         IS NOT DISTINCT FROM c.dob;
