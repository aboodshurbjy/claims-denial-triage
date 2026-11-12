-- severity: error
-- Coverage spans are well-formed and do not overlap within a member.
SELECT a.member_id, a.coverage_start, a.coverage_end FROM object.member_eligibility a
WHERE a.coverage_end < a.coverage_start
   OR EXISTS (
        SELECT 1 FROM object.member_eligibility b
        WHERE b.member_id = a.member_id
          AND b.coverage_start > a.coverage_start
          AND b.coverage_start <= a.coverage_end
   );
