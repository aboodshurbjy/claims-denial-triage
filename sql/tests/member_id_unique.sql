-- severity: error
-- One row per member.
SELECT member_id, count(*) AS n FROM object.member GROUP BY member_id HAVING count(*) > 1;
