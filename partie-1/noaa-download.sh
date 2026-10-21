for year in 2021 2022 2023 2024 2025; do
    (
        echo "=== Démarrage de l'année $year (France) ==="
        mc find "noaa/noaa-global-hourly-pds/$year" --name "07*.csv" --exec "mc cp {} mon-minio/datalake-noaa/$year/"
        echo "=== Fin de l'année $year ==="
    ) &
done
wait
echo "=== Synchronisation parallèle de toutes les stations françaises terminée ! ==="