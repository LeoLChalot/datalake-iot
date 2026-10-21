# Partie 1 - NOAA

## Création de la base de données

```bash
docker exec -it postgres-db psql -U myuser -d mydatabase -c "CREATE DATABASE noaa_datalake;"
```

## Connexion à Metabase
URI de connexion pour Metabase : `postgresql://myuser:mypassword@postgres-db:5432/db_name`

## Configuration du bucket MinIO et S3 NOAA
```bash
# Afficher le conteneur MinIO
$ docker ps

CONTAINER ID   IMAGE                             COMMAND                  CREATED       STATUS                    PORTS                                                             NAMES
2bd20bb18260   cgr.dev/chainguard/minio:latest   "/usr/bin/minio serv…"   4 hours ago   Up 25 minutes             0.0.0.0:9000-9001->9000-9001/tcp, [::]:9000-9001->9000-9001/tcp   minio

# Entrer dans le terminal interactif du conteneur
$ docker exec -it 2bd20bb18260 sh

# Config de l'accès MinIO local
sh-5.3# mc alias set mon-minio http://127.0.0.1:9000 minioadmin minioadmin123
mc: Configuration written to `/root/.mc/config.json`. Please update your access credentials.
mc: Successfully created `/root/.mc/share`.
mc: Initialized share uploads `/root/.mc/share/uploads.json` file.
mc: Initialized share downloads `/root/.mc/share/downloads.json` file.
Added `mon-minio` successfully.

# Config accès AWS S3 NOAA
sh-5.3# mc alias set noaa https://s3.amazonaws.com "" ""
Added `noaa` successfully.

# Création bucket MinIO local
sh-5.3# mc mb --ignore-existing mon-minio/datalake-noaa
Bucket created successfully `mon-minio/datalake-noaa`.
```

## Structure de la table silver

```plaintText
                    Table "public.silver_meteo_noaa_clean"
     Column     |            Type             | Collation | Nullable | Default
----------------+-----------------------------+-----------+----------+---------
 name           | text                        |           |          |
 station_id     | text                        |           |          |
 timestamp      | timestamp without time zone |           |          |
 temperature    | double precision            |           |          |
 wind_direction | double precision            |           |          |
 wind_speed     | double precision            |           |          |
 pressure       | double precision            |           |          |
 visibility     | double precision            |           |          |
 precipitation  | double precision            |           |          |
 ```