-- 1. Inactivation de la règle courante (v1.0 à 5%)
UPDATE dim_business_rules 
SET is_active = FALSE;

-- 2. Insertion de la nouvelle règle v2.0 à 7%
INSERT INTO dim_business_rules
(version, prime_rate, min_activities_wellness, wellness_days, max_walk_dist_km, max_bike_dist_km, is_active)
VALUES
('v2.0', 0.070, 15, 5, 15.0, 25.0, TRUE);