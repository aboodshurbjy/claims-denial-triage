-- Typed claims, one row per claim number (the export repeats some rows).
CREATE OR REPLACE TABLE staged.claims AS
WITH typed AS (
    SELECT
        _row_number,
        upper(clean_text(claim_number))             AS claim_id,
        clean_text(patient_name)                    AS patient_name,
        clean_medicaid_id(member_id)                AS medicaid_id,
        -- "LAST, FIRST M." or "First Last"
        CASE WHEN contains(patient_name, ',')
             THEN first_token(split_part(patient_name, ',', 2))
             ELSE first_token(patient_name)
        END                                         AS first_norm,
        CASE WHEN contains(patient_name, ',')
             THEN norm_name(split_part(patient_name, ',', 1))
             ELSE norm_name(regexp_replace(trim(patient_name), '^\S+\s*', ''))
        END                                         AS last_norm,
        parse_dob(dob)                              AS dob,
        clean_code(rendering_npi)                   AS provider_npi,
        clean_text(rendering_provider)              AS provider_name,
        clean_code(proc_code)                       AS service_code,
        parse_date(dos)                             AS date_of_service,
        parse_int(units)                            AS units,
        parse_money(charge)                         AS billed_amount,
        clean_code(auth_number)                     AS auth_number,
        parse_date(created)                         AS created_date
    FROM raw.claims
    WHERE clean_text(claim_number) IS NOT NULL
)
SELECT
    t.* EXCLUDE (_row_number),
    coalesce(n.canonical, t.first_norm) AS first_canon
FROM typed t
LEFT JOIN staged.nickname n ON n.nickname = t.first_norm
QUALIFY row_number() OVER (PARTITION BY t.claim_id ORDER BY t._row_number) = 1;
