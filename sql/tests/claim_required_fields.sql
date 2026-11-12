-- severity: error
-- Claims have a parsed date of service, service code, provider, units and amount.
SELECT claim_id FROM object.claim
WHERE date_of_service IS NULL OR service_code IS NULL OR provider_id IS NULL
   OR units IS NULL OR billed_amount IS NULL;
