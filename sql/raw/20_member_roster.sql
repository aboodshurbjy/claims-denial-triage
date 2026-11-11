-- Monthly roster workbook, one row per spreadsheet row across all sheets.
-- The loader exposes the workbook cells as text in _xlsx_member_roster
-- (typed cells are why the spreadsheet is the one source not read by SQL).
CREATE OR REPLACE TABLE raw.member_roster AS
SELECT
    sheet_name   AS _sheet_name,
    row_number   AS _row_number,
    medicaid_id,
    last_name,
    first_name,
    dob,
    elig_start,
    elig_end,
    plan
FROM _xlsx_member_roster;
