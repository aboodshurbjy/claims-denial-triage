-- Claims export exactly as delivered: every column text, nothing dropped.
CREATE OR REPLACE TABLE raw.claims AS
SELECT
    row_number() OVER ()     AS _row_number,
    "Claim #"                AS claim_number,
    "Patient Name"           AS patient_name,
    "Member ID"              AS member_id,
    "DOB"                    AS dob,
    "Rendering NPI"          AS rendering_npi,
    "Rendering Provider"     AS rendering_provider,
    "Proc Code"              AS proc_code,
    "DOS"                    AS dos,
    "Units"                  AS units,
    "Charge"                 AS charge,
    "Auth #"                 AS auth_number,
    "Created"                AS created
FROM read_csv(
    getvariable('data_dir') || '/claims_export.csv',
    header = true,
    all_varchar = true
);
