-- severity: error
-- Units and billed amount are greater than zero.
SELECT claim_id, units, billed_amount FROM object.claim WHERE units <= 0 OR billed_amount <= 0;
