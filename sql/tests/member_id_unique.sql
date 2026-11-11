-- severity: error
-- One row per member.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT member_id, count(*) AS n FROM object.member GROUP BY member_id HAVING count(*) > 1;
