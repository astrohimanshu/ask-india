-- Seed fixture for the walking skeleton. Stamped 'seed-v0'.
-- These rows are synthetic (placeholder carriers, round numbers) and must never be presented
-- as real data; every consumer checks dataset_version before treating a row as ingested.
\set ON_ERROR_STOP on
SET ROLE askindia_app;

INSERT INTO meta.datasets (dataset, table_name, title, source_org, source_url, cadence,
                           coverage_from, coverage_to, current_version, is_seed)
VALUES ('dgca_airline_traffic', 'data.dgca_airline_traffic',
        'Domestic scheduled airline traffic (seed fixture)', 'seed', NULL, 'monthly',
        '2024-01-01', '2024-03-01', 'seed-v0', true);

INSERT INTO data.dgca_airline_traffic
    (period, airline, passengers_carried, market_share_pct, passenger_load_factor_pct, dataset_version)
VALUES
    ('2024-01-01', 'Carrier Alpha',  6000000, 60.00, 90.00, 'seed-v0'),
    ('2024-01-01', 'Carrier Beta',   2500000, 25.00, 85.00, 'seed-v0'),
    ('2024-01-01', 'Carrier Gamma',  1500000, 15.00, 80.00, 'seed-v0'),
    ('2024-02-01', 'Carrier Alpha',  6200000, 62.00, 91.00, 'seed-v0'),
    ('2024-02-01', 'Carrier Beta',   2400000, 24.00, 84.00, 'seed-v0'),
    ('2024-02-01', 'Carrier Gamma',  1400000, 14.00, 79.00, 'seed-v0'),
    ('2024-03-01', 'Carrier Alpha',  6500000, 65.00, 92.00, 'seed-v0'),
    ('2024-03-01', 'Carrier Beta',   2300000, 23.00, 83.00, 'seed-v0'),
    ('2024-03-01', 'Carrier Gamma',  1200000, 12.00, 78.00, 'seed-v0');

RESET ROLE;
