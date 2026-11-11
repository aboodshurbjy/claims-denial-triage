-- severity: error
-- A Medicaid ID belongs to exactly one member.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT medicaid_id, count(DISTINCT member_id) AS members FROM object.member_identifier
GROUP BY medicaid_id HAVING count(DISTINCT member_id) > 1;
