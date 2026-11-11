-- Typed roster rows with normalised identifiers and names.
CREATE OR REPLACE TABLE staged.member_roster AS
WITH typed AS (
    SELECT
        _sheet_name || ':' || _row_number                               AS roster_row_id,
        _sheet_name                                                     AS sheet_name,
        CAST(_row_number AS INTEGER)                                    AS row_number_in_sheet,
        CAST(try_strptime(_sheet_name || '-01', '%Y-%m-%d') AS DATE)    AS report_month,
        clean_medicaid_id(medicaid_id)                                  AS medicaid_id,
        clean_text(first_name)                                          AS first_name_raw,
        clean_text(last_name)                                           AS last_name_raw,
        first_token(first_name)                                         AS first_norm,
        norm_name(last_name)                                            AS last_norm,
        parse_dob(dob)                                                  AS dob,
        parse_date(elig_start)                                          AS elig_start_parsed,
        parse_date(elig_end)                                            AS elig_end_parsed,
        clean_text(plan)                                                AS plan
    FROM raw.member_roster
    WHERE clean_text(first_name) IS NOT NULL
       OR clean_text(last_name) IS NOT NULL
       OR clean_medicaid_id(medicaid_id) IS NOT NULL
)
SELECT
    t.roster_row_id,
    t.sheet_name,
    t.row_number_in_sheet,
    t.report_month,
    t.medicaid_id,
    t.first_name_raw,
    t.last_name_raw,
    t.first_norm,
    coalesce(n.canonical, t.first_norm)                  AS first_canon,
    t.last_norm,
    t.dob,
    -- a blank start or end means "the whole report month"
    coalesce(t.elig_start_parsed, t.report_month)        AS elig_start,
    coalesce(t.elig_end_parsed, last_day(t.report_month)) AS elig_end,
    t.plan
FROM typed t
LEFT JOIN staged.nickname n ON n.nickname = t.first_norm;
