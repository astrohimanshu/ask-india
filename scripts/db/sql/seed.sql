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
    (period, airline, segment, departures, passengers_carried, passenger_load_factor_pct, dataset_version)
VALUES
    ('2024-01-01', 'Carrier Alpha', 'scheduled_domestic', 30000, 6000000, 90.00, 'seed-v0'),
    ('2024-01-01', 'Carrier Beta',  'scheduled_domestic', 12000, 2500000, 85.00, 'seed-v0'),
    ('2024-01-01', 'Carrier Gamma', 'scheduled_domestic',  8000, 1500000, 80.00, 'seed-v0'),
    ('2024-02-01', 'Carrier Alpha', 'scheduled_domestic', 31000, 6200000, 91.00, 'seed-v0'),
    ('2024-02-01', 'Carrier Beta',  'scheduled_domestic', 11500, 2400000, 84.00, 'seed-v0'),
    ('2024-02-01', 'Carrier Gamma', 'scheduled_domestic',  7500, 1400000, 79.00, 'seed-v0'),
    ('2024-03-01', 'Carrier Alpha', 'scheduled_domestic', 32000, 6500000, 92.00, 'seed-v0'),
    ('2024-03-01', 'Carrier Beta',  'scheduled_domestic', 11000, 2300000, 83.00, 'seed-v0'),
    ('2024-03-01', 'Carrier Gamma', 'scheduled_domestic',  7000, 1200000, 78.00, 'seed-v0');

RESET ROLE;
