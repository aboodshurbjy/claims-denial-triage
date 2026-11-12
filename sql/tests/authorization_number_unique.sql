-- severity: error
-- One row per authorization number.
SELECT auth_number, count(*) AS n FROM object.authorization GROUP BY auth_number HAVING count(*) > 1;
