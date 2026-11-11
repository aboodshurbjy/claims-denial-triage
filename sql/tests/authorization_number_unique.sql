-- severity: error
-- One row per authorization number.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT auth_number, count(*) AS n FROM object.authorization GROUP BY auth_number HAVING count(*) > 1;
