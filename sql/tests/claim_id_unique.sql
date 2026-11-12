-- severity: error
-- Every claim appears exactly once.
SELECT claim_id, count(*) AS n FROM object.claim GROUP BY claim_id HAVING count(*) > 1;
