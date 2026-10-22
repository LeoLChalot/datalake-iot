# Historique horaire des capteurs OpenAQ des grandes villes françaises.
# Source : archive publique S3 d'OpenAQ (openaq-data-archive), un fichier csv.gz par station et par jour.
# La liste des stations vient de inventory/locations.txt (produit par openaq-inventory.py).
# 16 stations sont copiées en parallèle (mc mirror).

MAX_JOBS=16
YEARS="2025 2026"

for location in $(mc cat mon-minio/datalake-openaq/inventory/locations.txt); do
    for year in $YEARS; do
        while [ "$(jobs -r | wc -l)" -ge "$MAX_JOBS" ]; do wait -n; done
        (
            mc mirror --quiet --skip-errors \
                "openaq/openaq-data-archive/records/csv.gz/locationid=$location/year=$year" \
                "mon-minio/datalake-openaq/archive/locationid=$location/year=$year" > /dev/null 2>&1
            echo "=== Station $location ($year) terminée ==="
        ) &
    done
done
wait
echo "=== Téléchargement parallèle de l'historique OpenAQ terminé ! ==="
