-- =============================================================================
-- UrbanHub - schéma de l'entrepôt PostgreSQL
-- Le marqueur {schema} est remplacé par POSTGRES_SCHEMA (défaut : urbanhub).
-- Script idempotent : il peut être rejoué sans perte de données.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS {schema};

-- -----------------------------------------------------------------------------
-- PARTIE 1 - Météo (NOAA Global Hourly, batch)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {schema}.weather_station (
    station_id   TEXT PRIMARY KEY,          -- USAF + WBAN (11 caractères)
    name         TEXT,
    latitude     DOUBLE PRECISION,
    longitude    DOUBLE PRECISION,
    elevation    REAL,
    city         TEXT                       -- ville principale la plus proche (<= 30 km)
);

CREATE TABLE IF NOT EXISTS {schema}.weather_hourly (
    station_id     TEXT        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL,    -- heure UTC
    temperature    REAL,                    -- °C
    wind_speed     REAL,                    -- m/s
    wind_direction REAL,                    -- degrés (0 = nord)
    visibility     REAL,                    -- km
    pressure       REAL,                    -- hPa (niveau de la mer)
    precipitation  REAL,                    -- mm/h
    PRIMARY KEY (station_id, ts)
);
CREATE INDEX IF NOT EXISTS weather_hourly_ts_idx ON {schema}.weather_hourly (ts);

CREATE TABLE IF NOT EXISTS {schema}.weather_daily (
    station_id      TEXT NOT NULL,
    day             DATE NOT NULL,
    t_mean          REAL,
    t_min           REAL,
    t_max           REAL,
    wind_mean       REAL,
    wind_max        REAL,
    visibility_mean REAL,
    visibility_min  REAL,
    pressure_mean   REAL,
    precipitation   REAL,                   -- mm/jour (estimation)
    n_hours         SMALLINT,
    PRIMARY KEY (station_id, day)
);

-- Météo récente (Open-Meteo) : l'archive NOAA s'arrête en 2025, ce complément
-- couvre la période de collecte des vélos et de la pollution (analyse croisée).
CREATE TABLE IF NOT EXISTS {schema}.weather_recent (
    city           TEXT        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL,
    temperature    REAL,
    wind_speed     REAL,
    wind_direction REAL,
    visibility     REAL,
    pressure       REAL,
    precipitation  REAL,
    PRIMARY KEY (city, ts)
);

-- -----------------------------------------------------------------------------
-- PARTIE 2 - Mobilité (CityBikes, streaming)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {schema}.bike_station (
    station_id   TEXT PRIMARY KEY,
    network_id   TEXT NOT NULL,
    city         TEXT,
    station_name TEXT,
    latitude     DOUBLE PRECISION,
    longitude    DOUBLE PRECISION,
    capacity     INTEGER,
    last_seen    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS {schema}.bike_status (
    station_id      TEXT        NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,   -- horodatage de l'observation (API)
    bikes_available INTEGER,
    free_slots      INTEGER,
    ebikes          INTEGER,
    PRIMARY KEY (station_id, ts)
);
CREATE INDEX IF NOT EXISTS bike_status_ts_idx ON {schema}.bike_status (ts);

-- -----------------------------------------------------------------------------
-- PARTIE 3 - Pollution (OpenAQ, IoT)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS {schema}.air_location (
    location_id INTEGER PRIMARY KEY,
    name        TEXT,
    locality    TEXT,
    city        TEXT,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    provider    TEXT
);

CREATE TABLE IF NOT EXISTS {schema}.air_sensor (
    sensor_id   INTEGER PRIMARY KEY,
    location_id INTEGER NOT NULL,
    pollutant   TEXT NOT NULL,
    unit        TEXT
);

CREATE TABLE IF NOT EXISTS {schema}.air_measurement (
    sensor_id  INTEGER     NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    pollutant  TEXT        NOT NULL,
    value      REAL,                        -- valeur brute, dans l'unité d'origine
    unit       TEXT,
    value_ugm3 REAL,                        -- valeur normalisée en µg/m³
    latitude   DOUBLE PRECISION,
    longitude  DOUBLE PRECISION,
    source     TEXT,                        -- 'stream' (flux IoT) ou 'backfill'
    PRIMARY KEY (sensor_id, ts)
);
CREATE INDEX IF NOT EXISTS air_measurement_ts_idx ON {schema}.air_measurement (ts);

-- =============================================================================
-- VUES « GOLD » (consommées par le notebook et par Metabase)
-- =============================================================================
DROP VIEW IF EXISTS {schema}.v_weather_city_daily CASCADE;
DROP VIEW IF EXISTS {schema}.v_weather_city_hourly CASCADE;
DROP VIEW IF EXISTS {schema}.v_bike_status CASCADE;
DROP VIEW IF EXISTS {schema}.v_air_measurement CASCADE;
DROP VIEW IF EXISTS {schema}.v_air_city_hourly CASCADE;

-- Météo horaire par ville : moyenne des stations NOAA de la ville,
-- complétée par Open-Meteo après la fin de l'archive NOAA.
CREATE VIEW {schema}.v_weather_city_hourly AS
WITH noaa AS (
    SELECT s.city, h.ts,
           AVG(h.temperature)    AS temperature,
           AVG(h.wind_speed)     AS wind_speed,
           -- moyenne circulaire (la moyenne de 350° et 10° doit donner 0°, pas 180°)
           CAST(DEGREES(ATAN2(AVG(SIN(RADIANS(h.wind_direction))),
                              AVG(COS(RADIANS(h.wind_direction))))) + 360 AS NUMERIC) % 360
                                 AS wind_direction,
           AVG(h.visibility)     AS visibility,
           AVG(h.pressure)       AS pressure,
           AVG(h.precipitation)  AS precipitation
    FROM {schema}.weather_hourly h
    JOIN {schema}.weather_station s USING (station_id)
    WHERE s.city IS NOT NULL
    GROUP BY s.city, h.ts
), noaa_end AS (
    SELECT city, MAX(ts) AS max_ts FROM noaa GROUP BY city
)
SELECT city, ts, temperature, wind_speed, wind_direction, visibility, pressure, precipitation,
       'noaa'::TEXT AS source
FROM noaa
UNION ALL
SELECT r.city, r.ts, r.temperature, r.wind_speed, r.wind_direction, r.visibility, r.pressure,
       r.precipitation, 'open-meteo'::TEXT AS source
FROM {schema}.weather_recent r
LEFT JOIN noaa_end e USING (city)
WHERE e.max_ts IS NULL OR r.ts > e.max_ts;

-- Moyenne des stations de la ville (y compris pour min/max : une station isolée
-- très exposée, comme un phare, ne doit pas à elle seule qualifier la ville).
CREATE VIEW {schema}.v_weather_city_daily AS
SELECT s.city, d.day,
       AVG(d.t_mean)          AS t_mean,
       AVG(d.t_min)           AS t_min,
       AVG(d.t_max)           AS t_max,
       AVG(d.wind_mean)       AS wind_mean,
       AVG(d.wind_max)        AS wind_max,
       AVG(d.visibility_mean) AS visibility_mean,
       AVG(d.visibility_min)  AS visibility_min,
       AVG(d.pressure_mean)   AS pressure_mean,
       AVG(d.precipitation)   AS precipitation,
       COUNT(*)               AS n_stations
FROM {schema}.weather_daily d
JOIN {schema}.weather_station s USING (station_id)
WHERE s.city IS NOT NULL
GROUP BY s.city, d.day;

-- Statut vélos avec toutes les variables demandées par le sujet
CREATE VIEW {schema}.v_bike_status AS
SELECT b.station_id, s.station_name, b.ts, s.latitude, s.longitude,
       b.free_slots, b.bikes_available, b.ebikes,
       s.city, s.network_id, s.capacity,
       b.bikes_available::REAL / NULLIF(b.bikes_available + b.free_slots, 0) AS occupancy
FROM {schema}.bike_status b
JOIN {schema}.bike_station s USING (station_id);

CREATE VIEW {schema}.v_air_measurement AS
SELECT m.sensor_id, m.pollutant, m.ts, m.latitude, m.longitude, m.value, m.unit, m.value_ugm3,
       l.location_id, l.name AS location_name, l.city, m.source
FROM {schema}.air_measurement m
JOIN {schema}.air_sensor se USING (sensor_id)
JOIN {schema}.air_location l ON l.location_id = se.location_id;

CREATE VIEW {schema}.v_air_city_hourly AS
SELECT city, pollutant, date_trunc('hour', ts) AS ts,
       AVG(value_ugm3) AS value_ugm3, COUNT(DISTINCT sensor_id) AS n_sensors
FROM {schema}.v_air_measurement
WHERE city IS NOT NULL AND value_ugm3 IS NOT NULL
GROUP BY city, pollutant, date_trunc('hour', ts);
