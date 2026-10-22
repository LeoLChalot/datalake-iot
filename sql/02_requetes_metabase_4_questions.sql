-- DATALAKE-IOT - Quatre questions métier / PostgreSQL & Metabase
-- COLLER UNE REQUÊTE À LA FOIS dans Metabase, base main_bd.
-- Les tables GOLD de 01_creation_gold_velos_2025.sql doivent déjà exister.

-- === Q1 : Météo x pollution, comparaison villes/polluants ===
SELECT city, pollutant, nb_jours_communs,
       r_temperature, r_vent, r_precipitation
FROM analytics.gold_correlations_meteo_pollution
WHERE nb_jours_communs >= 30
ORDER BY city, pollutant;

-- Q1 graphique : dispersion - X température (°C si confirmé), Y ozone (µg/m³), Lyon.
SELECT jour, temperature_moyenne, pollution_moyenne AS ozone_moyen
FROM analytics.gold_meteo_pollution_daily
WHERE city = 'Lyon' AND pollutant = 'o3'
  AND temperature_moyenne IS NOT NULL AND pollution_moyenne IS NOT NULL
ORDER BY jour;

-- Q1 graphique alternatif : barres de r température par ville pour ozone et NO2.
SELECT city, pollutant, r_temperature
FROM analytics.gold_correlations_meteo_pollution
WHERE pollutant IN ('o3', 'no2') AND nb_jours_communs >= 30
ORDER BY city, pollutant;

-- === Q2 : Météo x variations de vélos (LYON UNIQUEMENT) ===
-- Indicateur = baisses de stock observées à 1h, pour 100 station-heures valides.
SELECT * FROM analytics.gold_lyon_correlations_2025;

-- Q2 dispersion X température / Y départs apparents normalisés.
SELECT jour, temperature_moyenne,
       departs_apparents_par_100_station_heures AS activite_apparente
FROM analytics.gold_lyon_croisement_2025
WHERE temperature_moyenne IS NOT NULL
  AND departs_apparents_par_100_station_heures IS NOT NULL
ORDER BY jour;

-- Q2 évolutions mensuelles (graphique lignes / barres doubles avec axes adaptés).
SELECT DATE_TRUNC('month', jour)::DATE AS mois,
       ROUND(AVG(temperature_moyenne)::NUMERIC, 2) AS temp_moyenne,
       ROUND(AVG(departs_apparents_par_100_station_heures)::NUMERIC, 2) AS activite_apparente_moyenne,
       COUNT(*) AS jours
FROM analytics.gold_lyon_croisement_2025
GROUP BY 1 ORDER BY 1;

-- Q2 robustesse : corrélation uniquement les jours de semaine vs week-end.
SELECT CASE WHEN jour_semaine_iso IN (6,7) THEN 'Week-end' ELSE 'Semaine' END AS type_jour,
       COUNT(*) AS nb_jours,
       ROUND(CORR(departs_apparents_par_100_station_heures, temperature_moyenne)::NUMERIC, 3)
         AS r_temperature_activite,
       ROUND(CORR(departs_apparents_par_100_station_heures, precipitation_moyenne)::NUMERIC, 3)
         AS r_pluie_activite
FROM analytics.gold_lyon_croisement_2025
GROUP BY 1 ORDER BY 1;

-- === Q3 : Conditions potentiellement favorables à la mobilité douce ===
-- Indicateurs relatifs, non normes sanitaires ; mobilité = activité apparente.
SELECT
  CASE WHEN environnement_favorable_relatif THEN 'Environnement favorable'
       ELSE 'Autres jours évaluables' END AS categorie,
  COUNT(*) AS nb_jours,
  ROUND(AVG(departs_apparents_par_100_station_heures)::NUMERIC, 2) AS activite_apparente_moyenne,
  ROUND(AVG(part_velos_disponibles)::NUMERIC, 3) AS part_velos_disponibles_moyenne
FROM analytics.gold_lyon_conditions_mobilite_2025
WHERE environnement_favorable_relatif IS NOT NULL
  AND departs_apparents_par_100_station_heures IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Q3 : r point-bisérial (Pearson avec condition favorable codée 0/1).
SELECT COUNT(*) AS nb_jours_evaluables,
       COUNT(*) FILTER (WHERE environnement_favorable_relatif) AS nb_jours_favorables,
       ROUND(CORR(
             CASE WHEN environnement_favorable_relatif THEN 1.0 ELSE 0.0 END,
             departs_apparents_par_100_station_heures
       )::NUMERIC, 3) AS r_favorabilite_activite
FROM analytics.gold_lyon_conditions_mobilite_2025
WHERE environnement_favorable_relatif IS NOT NULL
  AND departs_apparents_par_100_station_heures IS NOT NULL;

-- Q3 graphique : % de journées favorables par mois (sur journées évaluables seulement).
SELECT DATE_TRUNC('month',jour)::DATE AS mois,
       COUNT(*) FILTER (WHERE environnement_favorable_relatif) AS jours_favorables,
       COUNT(*) FILTER (WHERE environnement_favorable_relatif IS NOT NULL) AS jours_evaluables,
       ROUND(100.0 * COUNT(*) FILTER (WHERE environnement_favorable_relatif)
           / NULLIF(COUNT(*) FILTER (WHERE environnement_favorable_relatif IS NOT NULL), 0), 1)
           AS pct_jours_favorables,
       ROUND(AVG(departs_apparents_par_100_station_heures)::NUMERIC, 2) AS activite_apparente_moyenne
FROM analytics.gold_lyon_conditions_mobilite_2025
GROUP BY 1 ORDER BY 1;

-- Q3 diagnostic si le critère combiné est trop restrictif : météo / air séparément.
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE meteo_favorable_relative) AS jours_meteo_favorable,
       COUNT(*) FILTER (WHERE air_favorable_relatif) AS jours_air_favorable,
       COUNT(*) FILTER (WHERE environnement_favorable_relatif) AS jours_combine_favorable
FROM analytics.gold_lyon_conditions_mobilite_2025;

-- === Q4 : Périodes d'interaction météo / pollution / vélos ===
-- Standardisation relative à Lyon 2025 ; |z_activite| >= 1 => écart important,
-- mais le sens peut être hausse OU baisse d'activité apparente.
SELECT COUNT(*) AS jours,
       COUNT(*) FILTER (WHERE episode_chaleur_ozone) AS jours_chaleur_ozone,
       COUNT(*) FILTER (WHERE episode_vent_faible_no2) AS jours_vent_faible_no2,
       COUNT(*) FILTER (WHERE episode_triple_chaleur_ozone_mobilite)
         AS jours_triples_chaleur_ozone_mobilite,
       COUNT(*) FILTER (WHERE episode_triple_vent_no2_mobilite)
         AS jours_triples_vent_no2_mobilite,
       ROUND(CORR(z_activite, z_ozone)::NUMERIC, 3) AS r_activite_ozone,
       ROUND(CORR(z_activite, z_no2)::NUMERIC, 3) AS r_activite_no2
FROM analytics.gold_lyon_episodes_2025;

-- Q4 tableau d'épisodes (triplés ; ne montre que ceux effectivement détectés).
SELECT jour,
       ROUND(z_temperature::NUMERIC, 2) AS z_temperature,
       ROUND(z_ozone::NUMERIC, 2) AS z_ozone,
       ROUND(z_vent_faible::NUMERIC, 2) AS z_vent_faible,
       ROUND(z_no2::NUMERIC, 2) AS z_no2,
       ROUND(z_activite::NUMERIC, 2) AS z_activite,
       episode_triple_chaleur_ozone_mobilite,
       episode_triple_vent_no2_mobilite
FROM analytics.gold_lyon_episodes_2025
WHERE episode_triple_chaleur_ozone_mobilite
   OR episode_triple_vent_no2_mobilite
ORDER BY jour;

-- Q4 graphique : nuage de points X=z_temp, Y=z_ozone ; activité au survol/date.
SELECT jour, z_temperature, z_ozone, z_activite,
       episode_triple_chaleur_ozone_mobilite
FROM analytics.gold_lyon_episodes_2025
WHERE z_temperature IS NOT NULL AND z_ozone IS NOT NULL
ORDER BY jour;

-- Q4 périodes mensuelles d'épisodes à 3 sources.
SELECT DATE_TRUNC('month', jour)::DATE AS mois,
       COUNT(*) FILTER (WHERE episode_triple_chaleur_ozone_mobilite) AS episodes_chaleur_ozone_velos,
       COUNT(*) FILTER (WHERE episode_triple_vent_no2_mobilite) AS episodes_vent_no2_velos
FROM analytics.gold_lyon_episodes_2025
GROUP BY 1 ORDER BY 1;
