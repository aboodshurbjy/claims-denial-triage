-- severity: error
-- Every roster row has a date of birth that parsed.
-- Returns the offending rows; an empty result means the assertion holds.
SELECT roster_row_id FROM staged.member_roster WHERE dob IS NULL;
