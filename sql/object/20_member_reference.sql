-- Resolve the member references found on claims and authorizations.
-- Medicaid ID first; name + date of birth only when the ID finds nobody,
-- and only when that fallback points at exactly one member.
CREATE OR REPLACE TABLE object.member_reference AS
WITH refs AS (
    SELECT DISTINCT medicaid_id, first_canon, last_norm, dob FROM staged.claims
    UNION
    SELECT DISTINCT medicaid_id, first_canon, last_norm, dob FROM staged.authorizations
),
keyed AS (
    SELECT row_number() OVER () AS ref_id, * FROM refs
),
by_id AS (
    SELECT k.ref_id, i.member_id
    FROM keyed k
    JOIN object.member_identifier i ON i.medicaid_id = k.medicaid_id
),
by_name AS (
    SELECT k.ref_id, min(a.member_id) AS member_id
    FROM keyed k
    JOIN object.member_alias a
      ON a.dob = k.dob
     AND first_name_match(a.first_canon, k.first_canon)
     AND last_name_match(a.last_norm, k.last_norm)
    GROUP BY k.ref_id
    HAVING count(DISTINCT a.member_id) = 1
)
SELECT
    k.medicaid_id,
    k.first_canon,
    k.last_norm,
    k.dob,
    coalesce(by_id.member_id, by_name.member_id) AS member_id,
    CASE
        WHEN by_id.member_id IS NOT NULL THEN 'medicaid_id'
        WHEN by_name.member_id IS NOT NULL THEN 'name_dob'
    END AS match_method
FROM keyed k
LEFT JOIN by_id USING (ref_id)
LEFT JOIN by_name USING (ref_id);
