-- severity: error
-- Every member has at least one coverage span.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT m.member_id FROM object.member m
LEFT JOIN object.member_eligibility e USING (member_id)
WHERE e.member_id IS NULL;
