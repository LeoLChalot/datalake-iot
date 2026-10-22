-- DATALAKE IOT - Intégration CityBikes 2025 / Lyon
-- PostgreSQL 17 - base main_bd - schéma analytics
-- Prérequis : public.silver_velo_stations_2025, analytics.meteo_daily,
--             analytics.noaa_station_city_map, analytics.gold_meteo_pollution_daily.
-- Cette procédure laisse les tables public.silver_* et les Gold précédentes intactes.
-- Elle RECRÉE uniquement les 6 tables Gold nommées ci-dessous.
-- Hypothèse à vérifier : timestamps NOAA/OpenAQ sans fuseau exprimés en UTC.
\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA IF NOT EXISTS analytics;

-- Supprimer uniquement nos nouvelles tables de travail (dans l'ordre inverse des dépendances).
DROP TABLE IF EXISTS analytics.gold_lyon_episodes_2025;
DROP TABLE IF EXISTS analytics.gold_lyon_conditions_mobilite_2025;
DROP TABLE IF EXISTS analytics.gold_lyon_correlations_2025;
DROP TABLE IF EXISTS analytics.gold_lyon_croisement_2025;
DROP TABLE IF EXISTS analytics.gold_velo_lyon_daily_2025;
DROP TABLE IF EXISTS analytics.gold_velo_lyon_hourly_2025;

-- 1) Toutes les observations horaires, à partir des snapshots par station.
-- 'departs_apparents' = somme des baisses de stock à 1h d'intervalle.
-- Ce n'est PAS un nombre certifié de trajets (rééquilibrage, retours, trajets entre relevés).
CREATE TABLE analytics.gold_velo_lyon_hourly_2025 AS
WITH dedup AS (
    SELECT DISTINCT ON (station_id, collected_at)
        station_id, collected_at, bikes_available, capacity
    FROM public.silver_velo_stations_2025
    WHERE BTRIM(city) = 'Lyon'
      AND station_id IS NOT NULL
      AND collected_at >= TIMESTAMPTZ '2025-01-01 00:00:00+00'
      AND collected_at < TIMESTAMPTZ '2026-01-01 00:00:00+00'
    ORDER BY station_id, collected_at
), observations AS (
    SELECT station_id, collected_at, bikes_available, capacity,
           LAG(collected_at) OVER w AS precedent_at,
           LAG(bikes_available) OVER w AS velos_precedents,
           LAG(capacity) OVER w AS capacite_precedente
    FROM dedup
    WINDOW w AS (PARTITION BY station_id ORDER BY collected_at)
), deltas AS (
    SELECT collected_at, bikes_available, capacity,
           CASE WHEN precedent_at = collected_at - INTERVAL '1 hour'
                     AND capacite_precedente > 0 AND capacity > 0
                     AND velos_precedents BETWEEN 0 AND capacite_precedente
                     AND bikes_available BETWEEN 0 AND capacity
                THEN GREATEST(velos_precedents - bikes_available, 0)
                ELSE NULL
           END AS departs_apparents
    FROM observations
)
SELECT
    DATE_TRUNC('hour', collected_at AT TIME ZONE 'UTC') AS heure_utc,
    COUNT(*) AS nb_stations_observees,
    COUNT(departs_apparents) AS nb_intervalles_valides,
    SUM(departs_apparents) AS departs_apparents,
    SUM(bikes_available) FILTER (WHERE capacity > 0 AND bikes_available BETWEEN 0 AND capacity) AS velos_disponibles,
    SUM(capacity) FILTER (WHERE capacity > 0 AND bikes_available BETWEEN 0 AND capacity) AS capacite_totale
FROM deltas
GROUP BY DATE_TRUNC('hour', collected_at AT TIME ZONE 'UTC');
CREATE UNIQUE INDEX idx_gold_velo_lyon_hour ON analytics.gold_velo_lyon_hourly_2025(heure_utc);
ANALYZE analytics.gold_velo_lyon_hourly_2025;

-- 2) Une ligne par jour. Normalisation par 100 station-heures valides,
-- afin de moins confondre variation d'activité et variation de couverture des stations.
CREATE TABLE analytics.gold_velo_lyon_daily_2025 AS
SELECT heure_utc::DATE AS jour,
       COUNT(*) AS heures_observees,
       ROUND(AVG(nb_stations_observees)::NUMERIC, 1) AS stations_moyennes,
       SUM(nb_intervalles_valides) AS station_heures_valides,
       SUM(departs_apparents) AS departs_apparents,
       100.0 * SUM(departs_apparents) / NULLIF(SUM(nb_intervalles_valides), 0)
         AS departs_apparents_par_100_station_heures,
       AVG(velos_disponibles::DOUBLE PRECISION / NULLIF(capacite_totale, 0))
         AS part_velos_disponibles
FROM analytics.gold_velo_lyon_hourly_2025
GROUP BY heure_utc::DATE;
CREATE UNIQUE INDEX idx_gold_velo_lyon_jour ON analytics.gold_velo_lyon_daily_2025(jour);
ANALYZE analytics.gold_velo_lyon_daily_2025;

-- 3) Croisement : une ligne LYON x JOUR (sans dupliquer les jours par polluant).
-- NOAA = station de référence assignée à Lyon par la table de correspondance.
-- OpenAQ = moyennes journalières de la ville (déjà présentes dans la Gold précédente).
-- NOAA/OpenAQ sont 'timestamp without time zone' : leur interprétation UTC doit être validée.
CREATE TABLE analytics.gold_lyon_croisement_2025 AS
WITH meteo AS (
    SELECT m.jour,
           AVG(m.temperature_moyenne) AS temperature_moyenne,
           AVG(m.vent_moyen) AS vent_moyen,
           AVG(m.precipitation_moyenne) AS precipitation_moyenne,
           AVG(m.visibilite_moyenne) AS visibilite_moyenne
    FROM analytics.meteo_daily m
    JOIN analytics.noaa_station_city_map carte USING (station_id)
    WHERE carte.city = 'Lyon'
      AND m.jour >= DATE '2025-01-01'
      AND m.jour <= DATE '2025-08-24'
    GROUP BY m.jour
), polluants AS (
    SELECT jour,
           MAX(pollution_moyenne) FILTER (WHERE pollutant = 'no2' AND unit = 'µg/m³') AS no2_moyen,
           MAX(pollution_moyenne) FILTER (WHERE pollutant = 'o3' AND unit = 'µg/m³') AS ozone_moyen,
           MAX(pollution_moyenne) FILTER (WHERE pollutant = 'pm25' AND unit = 'µg/m³') AS pm25_moyen,
           MAX(pollution_moyenne) FILTER (WHERE pollutant = 'pm10' AND unit = 'µg/m³') AS pm10_moyen
    FROM analytics.gold_meteo_pollution_daily
    WHERE city = 'Lyon'
    GROUP BY jour
)
SELECT 'Lyon'::TEXT AS city, v.jour,
       EXTRACT(ISODOW FROM v.jour)::INTEGER AS jour_semaine_iso,
       v.heures_observees, v.stations_moyennes, v.station_heures_valides,
       v.departs_apparents, v.departs_apparents_par_100_station_heures,
       v.part_velos_disponibles,
       m.temperature_moyenne, m.vent_moyen, m.precipitation_moyenne,
       m.visibilite_moyenne,
       p.no2_moyen, p.ozone_moyen, p.pm25_moyen, p.pm10_moyen
FROM analytics.gold_velo_lyon_daily_2025 v
JOIN meteo m USING (jour)
LEFT JOIN polluants p USING (jour);
CREATE UNIQUE INDEX idx_gold_lyon_joint_jour ON analytics.gold_lyon_croisement_2025(jour);
ANALYZE analytics.gold_lyon_croisement_2025;

-- 4) Q2 : coefficients de corrélation de Pearson avec un proxy NORMALISÉ.
CREATE TABLE analytics.gold_lyon_correlations_2025 AS
SELECT 'Lyon'::TEXT AS city,
       COUNT(*) AS jours_meteo_velos,
       COUNT(*) FILTER (WHERE departs_apparents_par_100_station_heures IS NOT NULL) AS jours_activite_evaluable,
       COUNT(*) FILTER (WHERE ozone_moyen IS NOT NULL) AS jours_ozone_disponible,
       ROUND(CORR(departs_apparents_par_100_station_heures, temperature_moyenne)::NUMERIC, 3)
           AS r_activite_temperature,
       ROUND(CORR(departs_apparents_par_100_station_heures, vent_moyen)::NUMERIC, 3)
           AS r_activite_vent,
       ROUND(CORR(departs_apparents_par_100_station_heures, precipitation_moyenne)::NUMERIC, 3)
           AS r_activite_precipitation,
       ROUND(CORR(departs_apparents_par_100_station_heures, ozone_moyen)::NUMERIC, 3)
           AS r_activite_ozone,
       ROUND(CORR(departs_apparents_par_100_station_heures, no2_moyen)::NUMERIC, 3)
           AS r_activite_no2,
       ROUND(CORR(departs_apparents_par_100_station_heures, pm25_moyen)::NUMERIC, 3)
           AS r_activite_pm25
FROM analytics.gold_lyon_croisement_2025;

-- 5) Q3 : critères relatifs, à interpréter comme grille de travail, PAS norme santé.
-- Température entre Q1 et Q3 de la ville ; vent, pluie, O3 et PM2.5 <= médianes.
-- Lien aux baisses de stock réellement observées dans la base 2025.
CREATE TABLE analytics.gold_lyon_conditions_mobilite_2025 AS
WITH seuils AS (
    SELECT
      PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY temperature_moyenne) AS temperature_q25,
      PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY temperature_moyenne) AS temperature_q75,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY vent_moyen) AS vent_mediane,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY precipitation_moyenne) AS pluie_mediane,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ozone_moyen) AS ozone_mediane,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pm25_moyen) AS pm25_mediane,
      PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY departs_apparents_par_100_station_heures)
        AS activite_q75
    FROM analytics.gold_lyon_croisement_2025
)
SELECT j.*,
       CASE WHEN j.temperature_moyenne IS NULL OR j.vent_moyen IS NULL
                  OR j.precipitation_moyenne IS NULL THEN NULL
            ELSE j.temperature_moyenne BETWEEN s.temperature_q25 AND s.temperature_q75
             AND j.vent_moyen <= s.vent_mediane
             AND j.precipitation_moyenne <= s.pluie_mediane
       END AS meteo_favorable_relative,
       CASE WHEN j.ozone_moyen IS NULL OR j.pm25_moyen IS NULL THEN NULL
            ELSE j.ozone_moyen <= s.ozone_mediane AND j.pm25_moyen <= s.pm25_mediane
       END AS air_favorable_relatif,
       CASE WHEN j.temperature_moyenne IS NULL OR j.vent_moyen IS NULL
                 OR j.precipitation_moyenne IS NULL OR j.ozone_moyen IS NULL
                 OR j.pm25_moyen IS NULL THEN NULL
            ELSE j.temperature_moyenne BETWEEN s.temperature_q25 AND s.temperature_q75
             AND j.vent_moyen <= s.vent_mediane
             AND j.precipitation_moyenne <= s.pluie_mediane
             AND j.ozone_moyen <= s.ozone_mediane
             AND j.pm25_moyen <= s.pm25_mediane
       END AS environnement_favorable_relatif,
       CASE WHEN j.departs_apparents_par_100_station_heures IS NULL THEN NULL
            ELSE j.departs_apparents_par_100_station_heures >= s.activite_q75
       END AS activite_apparente_elevee,
       s.temperature_q25, s.temperature_q75, s.vent_mediane, s.pluie_mediane,
       s.ozone_mediane, s.pm25_mediane, s.activite_q75
FROM analytics.gold_lyon_croisement_2025 j CROSS JOIN seuils s;
CREATE UNIQUE INDEX idx_gold_lyon_conditions_jour ON analytics.gold_lyon_conditions_mobilite_2025(jour);

-- 6) Q4 : score Z par variable sur la période commune 2025, épisodes de co-occurrence.
-- Les épisodes combinent une météo atypique + pollution atypique +
-- activité apparente atypique ; ce n'est PAS une preuve de causalité.
CREATE TABLE analytics.gold_lyon_episodes_2025 AS
WITH stats AS (
    SELECT AVG(temperature_moyenne) AS mu_temp, STDDEV_SAMP(temperature_moyenne) AS sd_temp,
           AVG(vent_moyen) AS mu_vent, STDDEV_SAMP(vent_moyen) AS sd_vent,
           AVG(ozone_moyen) AS mu_o3, STDDEV_SAMP(ozone_moyen) AS sd_o3,
           AVG(no2_moyen) AS mu_no2, STDDEV_SAMP(no2_moyen) AS sd_no2,
           AVG(departs_apparents_par_100_station_heures) AS mu_activite,
           STDDEV_SAMP(departs_apparents_par_100_station_heures) AS sd_activite
    FROM analytics.gold_lyon_croisement_2025
), z AS (
    SELECT j.*,
           (j.temperature_moyenne-s.mu_temp)/NULLIF(s.sd_temp, 0) AS z_temperature,
           (s.mu_vent-j.vent_moyen)/NULLIF(s.sd_vent, 0) AS z_vent_faible,
           (j.ozone_moyen-s.mu_o3)/NULLIF(s.sd_o3, 0) AS z_ozone,
           (j.no2_moyen-s.mu_no2)/NULLIF(s.sd_no2, 0) AS z_no2,
           (j.departs_apparents_par_100_station_heures-s.mu_activite)/NULLIF(s.sd_activite, 0)
             AS z_activite
    FROM analytics.gold_lyon_croisement_2025 j CROSS JOIN stats s
)
SELECT z.*,
       CASE WHEN z_temperature IS NULL OR z_ozone IS NULL THEN NULL
            ELSE z_temperature >= 1 AND z_ozone >= 1 END AS episode_chaleur_ozone,
       CASE WHEN z_vent_faible IS NULL OR z_no2 IS NULL THEN NULL
            ELSE z_vent_faible >= 1 AND z_no2 >= 1 END AS episode_vent_faible_no2,
       CASE WHEN z_temperature IS NULL OR z_ozone IS NULL OR z_activite IS NULL THEN NULL
            ELSE z_temperature >= 1 AND z_ozone >= 1 AND ABS(z_activite) >= 1
       END AS episode_triple_chaleur_ozone_mobilite,
       CASE WHEN z_vent_faible IS NULL OR z_no2 IS NULL OR z_activite IS NULL THEN NULL
            ELSE z_vent_faible >= 1 AND z_no2 >= 1 AND ABS(z_activite) >= 1
       END AS episode_triple_vent_no2_mobilite
FROM z;
CREATE UNIQUE INDEX idx_gold_lyon_episodes_jour ON analytics.gold_lyon_episodes_2025(jour);
ANALYZE analytics.gold_lyon_conditions_mobilite_2025;
ANALYZE analytics.gold_lyon_episodes_2025;
COMMIT;

-- Bilan de la création : ne pas extrapoler les valeurs sans consulter les résultats.
SELECT 'gold_velo_lyon_hourly_2025' AS objet, COUNT(*) AS lignes FROM analytics.gold_velo_lyon_hourly_2025
UNION ALL SELECT 'gold_velo_lyon_daily_2025', COUNT(*) FROM analytics.gold_velo_lyon_daily_2025
UNION ALL SELECT 'gold_lyon_croisement_2025', COUNT(*) FROM analytics.gold_lyon_croisement_2025
UNION ALL SELECT 'gold_lyon_correlations_2025', COUNT(*) FROM analytics.gold_lyon_correlations_2025
UNION ALL SELECT 'gold_lyon_conditions_mobilite_2025', COUNT(*) FROM analytics.gold_lyon_conditions_mobilite_2025
UNION ALL SELECT 'gold_lyon_episodes_2025', COUNT(*) FROM analytics.gold_lyon_episodes_2025;
