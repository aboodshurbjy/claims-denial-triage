-- severity: error
-- Every roster row is assigned to exactly one member.
SELECT r.roster_row_id, count(x.member_id) AS members FROM staged.member_roster r
LEFT JOIN object.member_roster_xref x USING (roster_row_id)
GROUP BY r.roster_row_id HAVING count(x.member_id) <> 1;
