-- severity: error
-- Authorizations have a start date, and an end date that is not before it.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT auth_number, start_date, end_date FROM object.authorization
WHERE start_date IS NULL OR end_date < start_date;
