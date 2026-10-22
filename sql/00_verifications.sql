-- À exécuter après restauration de silver_citybikes_2025.sql.
-- Ces requêtes vérifient la couverture et la cohérence avant l'analyse.
\set ON_ERROR_STOP on
SELECT COUNT(*) AS nb_lignes,
       COUNT(DISTINCT station_id) AS nb_stations,
       COUNT(DISTINCT collected_at) AS nb_instants_horaires,
       COUNT(DISTINCT ((collected_at AT TIME ZONE 'UTC')::DATE)) AS nb_jours_utc,
       MIN(collected_at) AS date_min,
       MAX(collected_at) AS date_max
FROM public.silver_velo_stations_2025;

SELECT city, COUNT(*) AS lignes FROM public.silver_velo_stations_2025 GROUP BY city ORDER BY lignes DESC;

SELECT COUNT(*) AS nb_valeurs_incoherentes
FROM public.silver_velo_stations_2025
WHERE capacity IS NULL OR capacity <= 0
   OR bikes_available IS NULL OR bikes_available < 0
   OR bikes_available > capacity;

-- Optionnel : détecter des doublons station + instant (peut prendre du temps).
-- SELECT station_id, collected_at, COUNT(*) AS nb
-- FROM public.silver_velo_stations_2025
-- GROUP BY station_id, collected_at HAVING COUNT(*) > 1 LIMIT 20;

-- Attention : le nombre de points horaires couverts n'implique pas une couverture exhaustive de toutes les stations.
