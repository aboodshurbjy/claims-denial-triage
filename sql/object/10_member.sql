-- Member: one row per resolved person, plus the supporting tables that
-- record how each source row and identifier maps onto that person.

CREATE OR REPLACE TABLE object.member_roster_xref AS
SELECT
    r.roster_row_id,
    'M' || lpad(CAST(dense_rank() OVER (ORDER BY c.cluster_root) AS VARCHAR), 5, '0') AS member_id
FROM staged.member_roster r
JOIN staged.member_signature s
  ON s.medicaid_id IS NOT DISTINCT FROM r.medicaid_id
 AND s.first_canon IS NOT DISTINCT FROM r.first_canon
 AND s.last_norm   IS NOT DISTINCT FROM r.last_norm
 AND s.dob         IS NOT DISTINCT FROM r.dob
JOIN staged.member_cluster c ON c.sig_id = s.sig_id;

CREATE OR REPLACE TABLE object.member AS
SELECT
    x.member_id,
    -- the ID on the most recent roster is the one the payer expects
    max_by(r.medicaid_id, strftime(r.report_month, '%Y%m') || r.medicaid_id)
        FILTER (WHERE r.medicaid_id IS NOT NULL)                AS medicaid_id,
    proper(mode(r.first_norm))                                  AS first_name,
    proper(mode(r.last_name_raw))                               AS last_name,
    mode(r.dob)                                                 AS date_of_birth,
    count(*)                                                    AS source_record_count,
    count(DISTINCT r.medicaid_id)                               AS medicaid_id_count,
    list(DISTINCT r.first_name_raw || ' ' || r.last_name_raw
         ORDER BY r.first_name_raw || ' ' || r.last_name_raw)   AS name_variants,
    min(r.report_month)                                         AS first_roster_month,
    max(r.report_month)                                         AS last_roster_month
FROM staged.member_roster r
JOIN object.member_roster_xref x USING (roster_row_id)
GROUP BY x.member_id;

-- Every Medicaid ID a member has ever appeared under.
CREATE OR REPLACE TABLE object.member_identifier AS
SELECT DISTINCT x.member_id, r.medicaid_id
FROM staged.member_roster r
JOIN object.member_roster_xref x USING (roster_row_id)
WHERE r.medicaid_id IS NOT NULL;

-- Every normalised name + DOB a member has appeared under; the fallback
-- key for matching claims and authorizations whose ID is wrong or missing.
CREATE OR REPLACE TABLE object.member_alias AS
SELECT DISTINCT x.member_id, r.first_canon, r.last_norm, r.dob
FROM staged.member_roster r
JOIN object.member_roster_xref x USING (roster_row_id)
WHERE r.first_canon IS NOT NULL AND r.last_norm IS NOT NULL AND r.dob IS NOT NULL;

-- Coverage spans: monthly roster rows merged into continuous periods.
CREATE OR REPLACE TABLE object.member_eligibility AS
WITH spans AS (
    SELECT DISTINCT x.member_id, r.elig_start, r.elig_end
    FROM staged.member_roster r
    JOIN object.member_roster_xref x USING (roster_row_id)
    WHERE r.elig_start IS NOT NULL AND r.elig_end >= r.elig_start
),
ordered AS (
    SELECT
        *,
        max(elig_end) OVER (
            PARTITION BY member_id ORDER BY elig_start, elig_end
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS previous_end
    FROM spans
),
islands AS (
    SELECT
        *,
        sum(CASE WHEN previous_end IS NULL OR elig_start > previous_end + 1 THEN 1 ELSE 0 END) OVER (
            PARTITION BY member_id ORDER BY elig_start, elig_end
        ) AS island
    FROM ordered
)
SELECT
    member_id,
    min(elig_start) AS coverage_start,
    max(elig_end)   AS coverage_end
FROM islands
GROUP BY member_id, island;
