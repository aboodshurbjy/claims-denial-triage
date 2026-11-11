-- Authorization: one row per auth number, linked to a resolved member.
CREATE OR REPLACE TABLE object.authorization AS
SELECT
    a.auth_number,
    m.member_id,
    a.medicaid_id       AS medicaid_id_on_auth,
    a.provider_npi      AS provider_id,
    a.service_code,
    a.start_date,
    a.end_date,
    a.units_approved,
    a.status,
    a.updated_at
FROM staged.authorizations a
LEFT JOIN object.member_reference m
  ON m.medicaid_id IS NOT DISTINCT FROM a.medicaid_id
 AND m.first_canon IS NOT DISTINCT FROM a.first_canon
 AND m.last_norm   IS NOT DISTINCT FROM a.last_norm
 AND m.dob         IS NOT DISTINCT FROM a.dob;
