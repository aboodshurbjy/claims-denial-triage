-- severity: error
-- Every claim number in the raw export reaches the object layer.
SELECT DISTINCT upper(clean_text(claim_number)) AS claim_id FROM raw.claims WHERE clean_text(claim_number) IS NOT NULL
EXCEPT
SELECT claim_id FROM object.claim;
