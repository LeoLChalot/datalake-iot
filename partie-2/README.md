# Partie 2 : mobilité urbaine (flux streaming CityBikes)

Le script [citybikes-collector.py](citybikes-collector.py) récupère toutes les 150 s les stations de vélos de 10 grandes villes (Paris, Lyon, Marseille, Toulouse, Nantes, Bordeaux, Lille, Strasbourg, Montpellier, Rennes). Il dépose un CSV par ville dans le bucket MinIO `datalake-citybikes`, avec un simple `curl` et sans identifiants.

## Configuration du bucket

Une seule fois, dans le conteneur MinIO. L'alias `mon-minio` est créé dans la section « Configuration du bucket MinIO » du [README principal](../README.md).

```bash
procjet_folder$ docker exec -it minio sh

sh-5.3# mc mb --ignore-existing mon-minio/datalake-citybikes
sh-5.3# mc anonymous set public mon-minio/datalake-citybikes
Access permission for `mon-minio/datalake-citybikes` is set to `public`
```

> Attention : le bucket est alors lisible et modifiable par tout le monde : OK en local, pas en production.

## Lancement de la collecte

Le collecteur est un service du `docker-compose.yaml`. Il démarre avec les autres services et redémarre tout seul (plantage, redémarrage du PC) tant que Docker Desktop tourne.

Commandes à lancer depuis la racine du projet :

```bash
docker compose up -d                     # démarre tout, collecteur compris
docker logs -f citybikes-collector       # suivre les collectes en direct
docker compose stop citybikes-collector  # mettre la collecte en pause
```

Pour un test ponctuel hors Docker, depuis la racine du projet (Ctrl+C pour arrêter ; ne pas le lancer en même temps que le service, sinon les relevés sont doublés) :

```bash
python partie-2/citybikes-collector.py
```

## Données produites

Fichiers : `datalake-citybikes/<reseau>/<YYYY-MM-DD>/<HHMMSS>.csv`

Colonnes : `station_id, station_name, timestamp, latitude, longitude, free_slots, bikes_available, city`

## Bronze → Silver et analyse

Le notebook [mobilite-urbaine.ipynb](mobilite-urbaine.ipynb) lit les CSV bruts de MinIO (bronze), les nettoie et les charge dans la table `silver_velo_stations` de la base PostgreSQL `urbanhub` (silver), puis répond aux questions Q1 à Q5. Chaque exécution ne charge que les nouvelles collectes.

Préparation (une seule fois) :

```bash
docker exec -it postgres-db psql -U myuser -d mydatabase -c "CREATE DATABASE urbanhub;"
pip install pandas sqlalchemy psycopg2-binary matplotlib boto3 jupyter
```

Metabase : `postgresql://myuser:mypassword@postgres-db:5432/urbanhub`
