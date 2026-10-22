| Service   | Usage | Accès depuis votre machine (Navigateur / Python)  | Accès interne (Entre les conteneurs Docker)   | Identifiants |
|:---|:---|:---:|:---:|:---|
| MinIO (Console)   | Interface d'administration Web (créer des buckets, voir les fichiers) | http://localhost:9001 | http://minio:9001 | User : minioadmin Pass : minioadmin123 |
| MinIO (API S3)    | Point de terminaison pour vos scripts Python (boto3, s3fs, etc.)  | http://localhost:9000 | http://minio:9000 | Access Key : minioadmin Secret Key : minioadmin123 |
| Metabase	        | Interface Web de Business Intelligence    | http://localhost:3000 | http://metabase:3000  | À créer lors du premier accès via l'assistant d'accueil |
| PostgreSQL	    | Base de données relationnelle (via DBeaver, pgAdmin, psycopg2, SQLAlchemy)    | http://localhost:5432 | http://postgres-db:5432   | DB : mydatabaseUser : myuserPass : mypassword |

## Sources de données exploitées

- **Données météorologiques**: [https://noaa-global-hourly-pds.s3.amazonaws.com/index.html](https://noaa-global-hourly-pds.s3.amazonaws.com/index.html)
- **CityBikes API**: [https://api.citybik.es/v2/](https://api.citybik.es/v2/)
- **OpenAQ**: [https://api.openaq.org/](https://api.openaq.org/)

## Création de la base de données

```bash
docker exec -it postgres-db psql -U myuser -d mydatabase -c "CREATE DATABASE db_name;"
```

## Connexion à Metabase
URI de connexion pour Metabase : `postgresql://myuser:mypassword@postgres-db:5432/db_name`

## Configuration du bucket MinIO et S3 NOAA
```bash
procjet_folder$ docker ps
CONTAINER ID   IMAGE                             COMMAND                  CREATED       STATUS                    PORTS                                                             NAMES
7a16646b37bf   metabase/metabase:latest          "/app/run_metabase.sh"   4 hours ago   Up 25 minutes             0.0.0.0:3000->3000/tcp, [::]:3000->3000/tcp                       metabase
49f91832d923   postgres:17                       "docker-entrypoint.s…"   4 hours ago   Up 25 minutes (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp                       postgres-db
2bd20bb18260   cgr.dev/chainguard/minio:latest   "/usr/bin/minio serv…"   4 hours ago   Up 25 minutes             0.0.0.0:9000-9001->9000-9001/tcp, [::]:9000-9001->9000-9001/tcp   minio

procjet_folder$ docker exec -it 2bd20bb18260 sh

# Config de l'accès local
sh-5.3# mc alias set mon-minio http://127.0.0.1:9000 minioadmin minioadmin123
mc: Configuration written to `/root/.mc/config.json`. Please update your access credentials.
mc: Successfully created `/root/.mc/share`.
mc: Initialized share uploads `/root/.mc/share/uploads.json` file.
mc: Initialized share downloads `/root/.mc/share/downloads.json` file.
Added `mon-minio` successfully.

# Config accès S3 NOAA
sh-5.3# mc alias set noaa https://s3.amazonaws.com "" ""
Added `noaa` successfully.

# Création bucket local
sh-5.3# mc mb --ignore-existing mon-minio/datalake-noaa
Bucket created successfully `mon-minio/datalake-noaa`.
```