# UrbanHub

**Lien du sujet :** [Notion -> UrbanHub](https://sayf-bejaoui.notion.site/UrbanHub-31fa172557588052bec1c3383fa11041)

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