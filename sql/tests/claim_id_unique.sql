-- severity: error
-- Every claim appears exactly once.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT claim_id, count(*) AS n FROM object.claim GROUP BY claim_id HAVING count(*) > 1;
