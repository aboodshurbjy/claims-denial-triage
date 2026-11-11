-- Shared cleaning and matching macros. Every model below builds on these.

CREATE OR REPLACE MACRO clean_text(s) AS
    nullif(trim(regexp_replace(CAST(s AS VARCHAR), '\s+', ' ', 'g')), '');

-- Source systems disagree on date formats; recognise each shape explicitly
-- so an unexpected format becomes NULL (and trips an assertion) instead of
-- being silently misread.
CREATE OR REPLACE MACRO parse_date(s) AS (
    CASE
        WHEN s IS NULL THEN NULL
        WHEN regexp_matches(trim(s), '^\d{4}-\d{2}-\d{2}([ T].*)?$')
            THEN try_cast(substr(trim(s), 1, 10) AS DATE)
        WHEN regexp_matches(trim(s), '^\d{1,2}/\d{1,2}/\d{4}$')
            THEN CAST(try_strptime(trim(s), '%m/%d/%Y') AS DATE)
        WHEN regexp_matches(trim(s), '^\d{1,2}/\d{1,2}/\d{2}$')
            THEN CAST(try_strptime(trim(s), '%m/%d/%y') AS DATE)
        WHEN regexp_matches(trim(s), '^\d{1,2}-[A-Za-z]{3}-\d{4}$')
            THEN CAST(try_strptime(trim(s), '%d-%b-%Y') AS DATE)
        WHEN regexp_matches(trim(s), '^\d{8}$')
            THEN CAST(try_strptime(trim(s), '%Y%m%d') AS DATE)
    END
);

-- Two-digit years can land in the future; nobody is born there.
CREATE OR REPLACE MACRO parse_dob(s) AS (
    CASE
        WHEN parse_date(s) > current_date THEN CAST(parse_date(s) - INTERVAL 100 YEAR AS DATE)
        ELSE parse_date(s)
    END
);

-- Medicaid IDs are ten digits. Strip punctuation and restore the leading
-- zeros that spreadsheets drop.
CREATE OR REPLACE MACRO clean_medicaid_id(s) AS (
    CASE
        WHEN regexp_replace(coalesce(CAST(s AS VARCHAR), ''), '[^0-9]', '', 'g') = '' THEN NULL
        ELSE lpad(regexp_replace(CAST(s AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
    END
);

CREATE OR REPLACE MACRO clean_code(s) AS
    nullif(upper(regexp_replace(coalesce(CAST(s AS VARCHAR), ''), '[^A-Za-z0-9]', '', 'g')), '');

-- Letters only, upper case: "Garcia-Lopez " -> "GARCIALOPEZ".
CREATE OR REPLACE MACRO norm_name(s) AS
    nullif(upper(regexp_replace(coalesce(CAST(s AS VARCHAR), ''), '[^A-Za-z]', '', 'g')), '');

-- First word, upper case: "John A." -> "JOHN".
CREATE OR REPLACE MACRO first_token(s) AS
    nullif(upper(split_part(trim(regexp_replace(coalesce(CAST(s AS VARCHAR), ''), '[^A-Za-z]+', ' ', 'g')), ' ', 1)), '');

-- "GARCIA-LOPEZ" -> "Garcia-Lopez".
CREATE OR REPLACE MACRO proper(s) AS
    array_to_string(
        list_transform(
            string_split(
                array_to_string(
                    list_transform(string_split(lower(trim(s)), ' '), lambda w: upper(w[1]) || w[2:]),
                    ' '),
                '-'),
            lambda w: upper(w[1]) || w[2:]),
        '-');

CREATE OR REPLACE MACRO parse_money(s) AS
    try_cast(regexp_replace(coalesce(CAST(s AS VARCHAR), ''), '[^0-9.\-]', '', 'g') AS DECIMAL(12, 2));

CREATE OR REPLACE MACRO parse_int(s) AS
    try_cast(try_cast(trim(CAST(s AS VARCHAR)) AS DOUBLE) AS INTEGER);

-- Entity-resolution comparators. Inputs are already normalised (and first
-- names already mapped from nickname to formal name).
CREATE OR REPLACE MACRO first_name_match(a, b) AS
    jaro_winkler_similarity(a, b) >= 0.9;

CREATE OR REPLACE MACRO last_name_match(a, b) AS (
    a = b
    OR jaro_winkler_similarity(a, b) >= 0.92
    OR (least(length(a), length(b)) >= 4 AND (starts_with(a, b) OR starts_with(b, a)))
);
