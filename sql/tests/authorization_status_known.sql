-- severity: error
-- Authorization status is one the rules understand.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT auth_number, status FROM object.authorization
WHERE status IS NULL OR status NOT IN ('approved', 'pending', 'denied');
