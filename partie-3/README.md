# Partie 3 - OpenAQ (flux IoT : pollution urbaine)

Collecte des mesures de pollution (PM2.5, PM10, NO₂, O₃, CO) des capteurs OpenAQ situés à moins de 20 km des 11 principales villes françaises (Paris, Marseille, Lyon, Toulouse, Nice, Nantes, Montpellier, Strasbourg, Bordeaux, Lille, Rennes).

```plaintext
API OpenAQ v3 ──► openaq-inventory.py ──► inventory/   (liste des capteurs)
                                              │
S3 openaq-data-archive ──► openaq-download.sh ┴► archive/   (historique 2025-2026, csv.gz)
API OpenAQ v3 ──► openaq-collector.py (15 min) ──► stream/  (flux IoT, JSONL)
                                                      │
                     notebook-clean-data.ipynb ◄──────┘
                     silver_pollution_openaq_clean ──► gold_pollution_* ──► Metabase
```

## Prérequis

### Clé API OpenAQ

Créer une clé gratuite sur https://explore.openaq.org/register, puis la mettre dans un fichier `.env` à la racine du projet (il est ignoré par git) :

```bash
OPENAQ_API_KEY=votre_cle
```

### Environnement Python

```bash
uv sync
```

## 1. Inventaire des capteurs

Liste les stations françaises actives, garde celles proches d'une grande ville qui mesurent au moins un des 5 polluants, et dépose la liste dans MinIO (le bucket `datalake-openaq` est créé s'il n'existe pas).

```bash
uv run python partie-3/openaq-inventory.py
```

Fichiers produits : `datalake-openaq/inventory/sensors.csv` et `datalake-openaq/inventory/locations.txt`.

## 2. Historique : téléchargement parallèle depuis le S3 OpenAQ

OpenAQ publie tout son historique sur un bucket S3 public (`openaq-data-archive`, un fichier `csv.gz` par station et par jour). Comme pour la NOAA, on le copie dans MinIO avec `mc`, 16 stations en parallèle.

```bash
# Entrer dans le terminal interactif du conteneur
$ docker exec -it minio sh

# Config de l'accès MinIO local (si pas déjà fait en Partie 1)
sh-5.3# mc alias set mon-minio http://127.0.0.1:9000 minioadmin minioadmin123

# Config accès AWS S3 OpenAQ
sh-5.3# mc alias set openaq https://s3.amazonaws.com "" ""
Added `openaq` successfully.
```

Puis, depuis la machine :

```bash
docker cp partie-3/openaq-download.sh minio:/tmp/openaq-download.sh
docker exec minio bash /tmp/openaq-download.sh
```

Fichiers produits : `datalake-openaq/archive/locationid=<id>/year=<année>/month=<mois>/location-<id>-<date>.csv.gz` (environ 65 000 fichiers, 33 Mo, 1 min 30).

## 3. Flux IoT : collecte toutes les 15 minutes

Simule une passerelle IoT : toutes les 15 min, le script récupère la dernière mesure de chaque station (`/v3/locations/{id}/latest`) et dépose les **nouvelles** mesures dans MinIO, une mesure = un message JSON. Un cycle prend environ 2 min 30 à cause de la limite de l'API (60 requêtes / minute), davantage si le quota horaire est atteint : le script attend alors la remise à zéro. Les mesures de plus de 24 h (capteurs en panne) sont ignorées.

```bash
uv run python partie-3/openaq-collector.py   # Ctrl+C pour arrêter
```

Fichiers produits : `datalake-openaq/stream/<YYYY-MM-DD>/<HHMMSS>.jsonl`

```json
{"sensor_id": 5587, "pollutant": "no2", "timestamp": "2026-10-22T07:00:00Z", "latitude": 45.7748, "longitude": 4.8985, "value": 32.1, "unit": "µg/m³", "location_id": 2680, "city": "Lyon"}
```

## 4. Nettoyage et tables gold

Exécuter `partie-3/notebook-clean-data.ipynb`. Il lit l'archive et le flux dans MinIO, nettoie les données, charge la table silver puis crée une table gold par question métier.

Nettoyages appliqués :

- seuls les 5 polluants et les capteurs de l'inventaire sont gardés ;
- timestamp converti en UTC (l'archive est en heure locale, le flux en UTC) ;
- unités ppm / ppb converties en µg/m³ ;
- valeurs manquantes, négatives ou au-delà des bornes physiques supprimées ;
- doublons (même capteur et même heure dans l'archive et le flux) supprimés.

## Connexion à Metabase

URI de connexion pour Metabase : `postgresql://myuser:mypassword@postgres-db:5432/mydatabase`

## Structure de la table silver

```plaintext
            Table "public.silver_pollution_openaq_clean"
    Column     |            Type             | Nullable
---------------+-----------------------------+----------
 sensor_id     | bigint                      |
 location_id   | bigint                      |
 location_name | text                        |
 city          | text                        |
 pollutant     | text                        |
 timestamp     | timestamp without time zone |   (UTC)
 latitude      | double precision            |
 longitude     | double precision            |
 value         | double precision            |   (µg/m³)
 unit          | text                        |
 source        | text                        |   (archive / stream)
```

## Tables gold

| Question métier | Table | Contenu |
|---|---|---|
| Q1. Zones les plus polluées | `gold_pollution_zones` | par station et polluant : moyenne, indice OMS (moyenne / seuil journalier), % de jours au-dessus du seuil, coordonnées |
| Q2. Variation journalière | `gold_pollution_daily_profile` | par ville, polluant, semaine / week-end et heure locale : concentration moyenne |
| Q3. Polluants dominants | `gold_pollution_dominant` | par ville et polluant : indice OMS et rang (1 = polluant dominant) |
| Q4. Épisodes anormaux | `gold_pollution_anomalies` | jours anormaux (z-score > 2,5 par rapport au mois ou moyenne > 2 × seuil OMS), regroupés en épisodes |

Seuils journaliers OMS 2021 utilisés (table `ref_pollution_who`) : PM2.5 15 µg/m³, PM10 45, NO₂ 25, O₃ 100, CO 4 000.
