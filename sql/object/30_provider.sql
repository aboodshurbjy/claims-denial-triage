-- Provider: one row per NPI seen on a claim or an authorization.
CREATE OR REPLACE TABLE object.provider AS
WITH seen AS (
    SELECT provider_npi, provider_name, 1 AS on_claim FROM staged.claims
    UNION ALL
    SELECT provider_npi, provider_name, 0 AS on_claim FROM staged.authorizations
)
SELECT
    provider_npi                  AS provider_id,
    provider_npi                  AS npi,
    mode(provider_name)           AS provider_name,
    CAST(sum(on_claim) AS INTEGER) AS claim_count
FROM seen
WHERE provider_npi IS NOT NULL
GROUP BY provider_npi;
