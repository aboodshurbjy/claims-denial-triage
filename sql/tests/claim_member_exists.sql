-- severity: error
-- A claim's member_id, when set, exists in the member table.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT c.claim_id, c.member_id FROM object.claim c
LEFT JOIN object.member m USING (member_id)
WHERE c.member_id IS NOT NULL AND m.member_id IS NULL;
