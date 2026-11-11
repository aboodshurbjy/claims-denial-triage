-- Member entity resolution, in three steps.
--
-- 1. Signature: each distinct (Medicaid ID, first name, last name, DOB)
--    combination seen on the roster. Thousands of roster rows collapse to
--    a few hundred signatures, which keeps the pairwise comparison small.
-- 2. Edge: two signatures refer to the same person when
--      a. they carry the same Medicaid ID, or
--      b. date of birth is identical AND first names match AND last names
--         match (see first_name_match / last_name_match).
--    Rule b is what joins a row with a missing ID, and a member who was
--    re-enrolled under a new ID. Twins survive it: same DOB and last name,
--    but different first names and different IDs.
-- 3. Cluster: connected components over the edges. A = B and B = C puts
--    A, B and C in one cluster even if A and C never matched directly.

CREATE OR REPLACE TABLE staged.member_signature AS
SELECT
    row_number() OVER (ORDER BY medicaid_id NULLS LAST, last_norm, first_canon, dob) AS sig_id,
    medicaid_id,
    first_canon,
    last_norm,
    dob
FROM (
    SELECT DISTINCT medicaid_id, first_canon, last_norm, dob
    FROM staged.member_roster
);

CREATE OR REPLACE TABLE staged.member_match_edge AS
SELECT
    a.sig_id AS sig_a,
    b.sig_id AS sig_b,
    CASE WHEN a.medicaid_id = b.medicaid_id THEN 'medicaid_id' ELSE 'name_dob' END AS match_rule
FROM staged.member_signature a
JOIN staged.member_signature b
  ON a.sig_id <> b.sig_id
 AND (
        a.medicaid_id = b.medicaid_id
     OR (
            a.dob = b.dob
        AND first_name_match(a.first_canon, b.first_canon)
        AND last_name_match(a.last_norm, b.last_norm)
        )
     );

CREATE OR REPLACE TABLE staged.member_cluster AS
WITH RECURSIVE reach(sig_id, root) AS (
    SELECT sig_id, sig_id FROM staged.member_signature
    UNION
    SELECT e.sig_b, r.root
    FROM reach r
    JOIN staged.member_match_edge e ON e.sig_a = r.sig_id
)
SELECT sig_id, min(root) AS cluster_root
FROM reach
GROUP BY sig_id;
