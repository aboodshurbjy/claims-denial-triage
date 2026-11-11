-- Flattened authorizations. The feed can carry several revisions of one
-- auth number; the most recently updated revision wins.
CREATE OR REPLACE TABLE staged.authorizations AS
WITH typed AS (
    SELECT
        _index,
        clean_code(json_extract_string(payload, '$.authNumber'))               AS auth_number,
        lower(clean_text(json_extract_string(payload, '$.status')))            AS status,
        clean_medicaid_id(json_extract_string(payload, '$.member.medicaidId')) AS medicaid_id,
        first_token(json_extract_string(payload, '$.member.firstName'))        AS first_norm,
        norm_name(json_extract_string(payload, '$.member.lastName'))           AS last_norm,
        parse_dob(json_extract_string(payload, '$.member.dob'))                AS dob,
        clean_code(json_extract_string(payload, '$.service.code'))             AS service_code,
        clean_code(json_extract_string(payload, '$.provider.npi'))             AS provider_npi,
        clean_text(json_extract_string(payload, '$.provider.name'))            AS provider_name,
        parse_date(json_extract_string(payload, '$.effective.start'))          AS start_date,
        parse_date(json_extract_string(payload, '$.effective.end'))            AS end_date,
        parse_int(json_extract_string(payload, '$.unitsApproved'))             AS units_approved,
        try_cast(json_extract_string(payload, '$.updatedAt') AS TIMESTAMPTZ)   AS updated_at
    FROM raw.authorizations
)
SELECT
    t.* EXCLUDE (_index),
    coalesce(n.canonical, t.first_norm) AS first_canon
FROM typed t
LEFT JOIN staged.nickname n ON n.nickname = t.first_norm
WHERE t.auth_number IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY t.auth_number ORDER BY t.updated_at DESC NULLS LAST, t._index DESC) = 1;
