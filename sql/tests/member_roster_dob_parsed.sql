-- severity: error
-- Every roster row has a date of birth that parsed.
SELECT roster_row_id FROM staged.member_roster WHERE dob IS NULL;
