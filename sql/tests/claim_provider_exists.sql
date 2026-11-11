-- severity: error
-- Every claim points at a known provider.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT c.claim_id, c.provider_id FROM object.claim c
LEFT JOIN object.provider p USING (provider_id)
WHERE p.provider_id IS NULL;
