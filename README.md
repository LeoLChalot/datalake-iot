# UrbanHub : jumeau numérique urbain

Plateforme Big Data Smart City : **collecter, stocker, analyser et exploiter** les données d'une ville (sujet : [UrbanHub-Sujet.pdf](UrbanHub-Sujet.pdf)).

| Partie | Flux | Source | Commande |
|---|---|---|---|
| 1. Météo | **Batch** | [NOAA Global Hourly](https://www.ncei.noaa.gov/data/global-hourly/access/) | `python -m urbanhub batch` |
| 2. Mobilité | **Streaming** | [CityBikes API](https://api.citybik.es/v2/) | `python -m urbanhub bikes` |
| 3. Pollution | **IoT** | [OpenAQ API](https://docs.openaq.org/) | `python -m urbanhub air` |
| 4. Analyse croisée | Batch × Streaming × IoT | les trois sources (+ Open-Meteo) | [notebooks/UrbanHub.ipynb](notebooks/UrbanHub.ipynb) |

## Architecture

```
 Sources              Ingestion (urbanhub/)          Data Lake MinIO                 Entrepôt PostgreSQL         Exploitation
 ───────              ─────────────────────          ───────────────                 ───────────────────         ────────────
 NOAA (S3)     ──►    batch/      16 threads   ──►   bronze/noaa/        (CSV brut)  weather_* ─┐
 CityBikes     ──►    streaming/  toutes 150 s ──►   bronze/citybikes/   (JSON)      bike_*     ├─► vues v_*  ──►  Notebook
 OpenAQ        ──►    iot/        toutes 15 min──►   bronze/openaq/      (JSONL)     air_*      │   (gold)         Metabase
 Open-Meteo    ──►    enrichment/              ──►   silver/weather_hourly/ (Parquet)            ─┘
```

- **Bronze** : données brutes, telles que reçues. Elles permettent de tout retraiter.
- **Silver** : données nettoyées et typées (Parquet).
- **Gold** : tables relationnelles et vues d'indicateurs dans PostgreSQL (schéma `urbanhub`, voir [sql/init.sql](sql/init.sql)).

## Organisation du code

```
datalake-iot/
├── docker-compose.yaml        PostgreSQL, MinIO, Metabase (+ collecteurs, profil « collectors »)
├── Dockerfile                 image des collecteurs
├── requirements.txt
├── .env.example               configuration (copier en .env)
├── sql/init.sql               schéma de l'entrepôt : tables + vues gold
├── notebooks/UrbanHub.ipynb   analyses, visualisations et interprétations (Parties 1 à 4)
└── urbanhub/
    ├── __main__.py            CLI : python -m urbanhub <commande>
    ├── config.py              paramètres (villes, URLs, intervalles, seuils OMS…)
    ├── geo.py                 distances, rattachement aux villes
    ├── storage/
    │   ├── datalake.py        MinIO (S3) : bronze / silver
    │   └── warehouse.py       PostgreSQL : upsert massif (COPY + ON CONFLICT)
    ├── batch/                 PARTIE 1
    │   ├── noaa_stations.py   inventaire des stations FR + fichiers disponibles
    │   ├── noaa_download.py   téléchargement parallèle (ThreadPoolExecutor)
    │   ├── noaa_clean.py      décodage ISD, unités, qualité, agrégation horaire
    │   └── pipeline.py        orchestration bronze -> silver -> PostgreSQL
    ├── streaming/             PARTIE 2
    │   ├── citybikes_client.py
    │   ├── transform.py
    │   └── collector.py       boucle toutes les 2-3 min
    ├── iot/                   PARTIE 3
    │   ├── openaq_client.py   client v3 avec limitation de débit
    │   ├── inventory.py       capteurs FR des polluants étudiés
    │   ├── transform.py       normalisation en µg/m³
    │   ├── collector.py       flux IoT simulé (messages capteurs)
    │   └── backfill.py        historique horaire
    ├── enrichment/
    │   └── open_meteo.py      météo récente (la NOAA s'arrête en 2025)
    └── analysis/              une fonction par question métier
        ├── data.py            chargement depuis les vues gold
        ├── weather.py         Partie 1 : Q1-Q4
        ├── mobility.py        Partie 2 : Q1-Q5
        ├── pollution.py       Partie 3 : Q1-Q4
        ├── cross.py           Partie 4 : Q1-Q4
        └── plots.py           helpers matplotlib
```

## Démarrage rapide

```bash
# 1. Infrastructure
docker compose up -d

# 2. Environnement Python
python -m venv .venv && .venv\Scripts\activate     # (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                              # puis renseigner OPENAQ_API_KEY

# 3. Création du bucket et du schéma
python -m urbanhub init

# 4. Ingestion
python -m urbanhub batch                  # Partie 1 : 5 ans, toutes les stations FR (~1 000 fichiers)
python -m urbanhub batch --cities-only    #   variante rapide : stations des 11 grandes villes (~2 min)
python -m urbanhub bikes                  # Partie 2 : tourne en continu (Ctrl+C pour arrêter)
python -m urbanhub air-backfill --days 60 # Partie 3 : historique
python -m urbanhub air                    # Partie 3 : flux IoT continu
python -m urbanhub weather-recent         # météo de la période de collecte (Partie 4)

python -m urbanhub status                 # volumes stockés

# 5. Analyses
jupyter notebook notebooks/UrbanHub.ipynb
```

Pour faire tourner les collecteurs en continu dans Docker :

```bash
docker compose --profile collectors up -d --build    # bikes-collector + air-collector
docker compose logs -f bikes-collector
```

## Choix techniques

| Sujet | Choix | Pourquoi |
|---|---|---|
| Téléchargement NOAA | `ThreadPoolExecutor` (16 threads), une session HTTP par thread, retries | téléchargement **parallèle** exigé ; tâche limitée par le réseau, donc les threads suffisent |
| Fenêtre NOAA | 5 dernières années **disponibles** (2021-2025) | l'archive publique (désormais sur S3 `noaa-global-hourly-pds`) s'arrête en août 2025 |
| Nettoyage NOAA | codes qualité, sentinelles, bornes physiques, une ligne par heure, direction du vent en moyenne circulaire, interpolation ≤ 3 h | voir l'en-tête de [noaa_clean.py](urbanhub/batch/noaa_clean.py) |
| Chargement PostgreSQL | `COPY` dans une table temporaire puis `INSERT … ON CONFLICT` | rapide (≈1 M lignes en quelques secondes) et **idempotent** (rejouer = pas de doublons) |
| Streaming vélos | interrogation toutes les 150 s, réseaux en parallèle | intervalle de 2 à 3 min demandé ; l'historique se construit dans le temps (API temps réel) |
| Usage vélo | mouvements = \|Δ vélos\| entre deux relevés | l'API ne donne pas les trajets ; c'est une borne basse de l'usage |
| Flux IoT | une mesure = un message JSON (comme MQTT ou Kafka), archivé en JSONL | simulation d'un flux capteurs avec les données OpenAQ |
| Pollution | conversion en µg/m³ et comparaison aux seuils OMS 2021 | rend les polluants comparables entre eux |
| Analyse croisée | grain commun (ville, heure) ; météo NOAA + Open-Meteo | recouvrement temporel avec les flux récents |

## Services (docker-compose)

| Service   | Usage | Accès depuis votre machine (Navigateur / Python)  | Accès interne (Entre les conteneurs Docker)   | Identifiants |
|:---|:---|:---:|:---:|:---|
| MinIO (Console)   | Interface d'administration Web (créer des buckets, voir les fichiers) | http://localhost:9001 | http://minio:9001 | User : minioadmin Pass : minioadmin123 |
| MinIO (API S3)    | Point de terminaison pour vos scripts Python (boto3, s3fs, etc.)  | http://localhost:9000 | http://minio:9000 | Access Key : minioadmin Secret Key : minioadmin123 |
| Metabase	        | Interface Web de Business Intelligence    | http://localhost:3000 | http://metabase:3000  | À créer lors du premier accès via l'assistant d'accueil |
| PostgreSQL	    | Base de données relationnelle (via DBeaver, pgAdmin, psycopg2, SQLAlchemy)    | localhost:5432 | postgres-db:5432   | DB : mydatabase · User : myuser · Pass : mypassword |

**Metabase** : ajouter une base PostgreSQL avec l'hôte `postgres-db`, le port `5432`, la base `mydatabase` et les identifiants ci-dessus. Les vues `urbanhub.v_weather_city_daily`, `urbanhub.v_bike_status` et `urbanhub.v_air_city_hourly` sont prêtes pour les tableaux de bord.

## Reste à faire

- [ ] **Clé OpenAQ** : créer une clé gratuite sur https://explore.openaq.org/register, l'ajouter dans `.env` (`OPENAQ_API_KEY=...`), puis lancer :
  ```bash
  python -m urbanhub air-backfill --days 60   # historique
  python -m urbanhub air                      # flux IoT continu
  ```
  La Partie 3 a été testée uniquement sur des réponses simulées : il faut la valider sur l'API réelle.
- [ ] **Collecte vélos** : laisser tourner `python -m urbanhub bikes` (ou `docker compose --profile collectors up -d`) **au moins 24 h, idéalement une semaine**. Les pics journaliers (Partie 2 Q3) et l'analyse croisée (Partie 4) en dépendent.
- [ ] **Météo récente** : relancer `python -m urbanhub weather-recent` après la collecte, pour couvrir la même période que les vélos et la pollution.
- [ ] **Batch complet** : lancer `python -m urbanhub batch` sans option pour charger toutes les stations françaises (~1 000 fichiers). Seules les stations des grandes villes sont chargées pour l'instant (`--cities-only`).
- [ ] **Notebook** : le réexécuter une fois les données collectées, puis relire les interprétations des Parties 2, 3 et 4. Elles décrivent pour l'instant les tendances attendues, à confirmer avec les chiffres réels.
- [ ] **Metabase** : créer les tableaux de bord à partir des vues `urbanhub.v_*`.
- [ ] **Vidéos de démonstration** : `Démo-UrbanHub-Partie1.mp4` et `Démo-UrbanHub-Partie2.mp4`.

## Limites connues

- **NOAA** : pas de données après août 2025 dans l'archive publique. Open-Meteo complète la période récente pour l'analyse croisée.
- **CityBikes** : temps réel uniquement. L'historique « depuis l'existence de Vélib' » n'est pas exposé par l'API, il s'accumule en laissant tourner le collecteur. Certains réseaux ont un flux défaillant (Marseille renvoie 0 vélo partout) : ils sont détectés et exclus par `mobility.network_quality`.
- **OpenAQ** : une clé API gratuite est nécessaire, limitée à 60 requêtes par minute.
