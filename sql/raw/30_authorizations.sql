-- Authorization feed: one row per record, payload kept as untouched JSON.
CREATE OR REPLACE TABLE raw.authorizations AS
SELECT
    row_number() OVER () AS _index,
    generated_at         AS _feed_generated_at,
    payload
FROM (
    SELECT
        "generatedAt"          AS generated_at,
        unnest(authorizations) AS payload
    FROM read_json(
        getvariable('data_dir') || '/authorizations.json',
        columns = {'generatedAt': 'VARCHAR', 'authorizations': 'JSON[]'}
    )
);
