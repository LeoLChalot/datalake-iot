# Projet Data Lake IoT — Quatre réponses métier (mise à jour CityBikes 2025)

## Périmètre vérifié

- Archive fournie `silver_citybikes_2025.rar` : contient `silver_citybikes_2025.sql`, dump PostgreSQL de `public.silver_velo_stations_2025`.
- Analyse du dump : **3 570 166 lignes**, **433 stations**, ville **Lyon seulement**, du **01/01/2025 00:00 UTC** au **31/12/2025 23:00 UTC** ; **365 journées** et **8 734 instants horaires distincts**. Une année non bissextile aurait 8 760 heures : il manque donc 26 instants horaires dans la couverture globale, en plus d'éventuelles lacunes par station.
- Météo NOAA : 2021–24/08/2025 ; OpenAQ : 2025–2026. L'intersection en principe pertinente pour **Lyon** est **janvier–août 2025**, à vérifier par `gold_lyon_croisement_2025`.
- Les heures CityBikes sont explicitement UTC ; les colonnes NOAA/OpenAQ sont `timestamp without time zone` ; vérifier qu'elles sont effectivement interprétées en UTC dans l'ETL.
- Météo : Lyon Bron (station 07480099999) est un **proxy régional**, pas un capteur au niveau de chaque station vélo.
- Les unités météo (température/vent/pluie) doivent être vérifiées auprès de l'ETL avant une interprétation physique.
- Un relevé `bikes_available` est une **photographie de stock** ; ses baisses horaires ne sont pas des trajets certifiés (rééquilibrages, retours et rotations entre deux relevés).

## Q1 — Relation entre météo et pollution

**Table / requêtes :** `analytics.gold_correlations_meteo_pollution` et `analytics.gold_meteo_pollution_daily`.

**Indicateurs :** Pearson `CORR` de la concentration de chaque polluant avec température, vent et précipitations, par ville sur les jours communs ; conserver `nb_jours_communs` et exclure les groupes < 30 jours.

**Résultats observés (issus de la sortie PostgreSQL fournie par le groupe) :**

- Température–ozone : corrélation **positive dans les 10 villes exploitables**, de **+0,520 (Nantes)** à **+0,798 (Nice)** ; **Lyon +0,754**.
- Température–NO₂ : **négative** dans les 10 villes, entre **−0,132 (Montpellier)** et **−0,634 (Lille)** ; **Lyon −0,337**.
- Vent–NO₂ : **Marseille −0,725**, **Lyon −0,580**, compatible avec une dispersion plus forte lorsque le vent augmente.
- Précipitations : corrélations globalement faibles dans les séries quotidiennes calculées, cela **ne signifie pas absence de tout effet**.
- **Paris** n'est pas représentée dans le tableau des 42 corrélations : la station météo associée n'avait que **13 jours** de couverture en 2025, contre le minimum de 30 jours retenu.

**Graphe Metabase :** barres de `r_temperature` pour les polluants O₃ et NO₂ dans les villes, ou nuage de points à Lyon (X = température, Y = O₃).

**Texte oral (30–40 sec) :**
> « Nous avons agrégé météo et pollution à la journée et par ville, puis calculé les corrélations de Pearson. L'ozone augmente avec la température dans toutes les villes étudiées, avec r = +0,754 à Lyon. Le NO₂ présente plutôt une relation négative, notamment avec le vent, avec r = −0,580 à Lyon. Ces résultats sont compatibles avec des mécanismes atmosphériques connus, sans prouver qu'une variable cause l'autre : la saison, l'activité urbaine et la localisation des capteurs peuvent jouer. »

## Q2 — La météo influence-t-elle l'utilisation des vélos ?

**Ce qui change grâce au nouveau fichier :** les données de 2025 de Lyon **chevauchent maintenant** météo NOAA et OpenAQ. L'ancien diagnostic « zéro jour commun » de `gold_diagnostic_meteo_velos` concerne seulement les **captures de 2026** et ne doit **plus** servir de réponse à cette question.

**Tables :** `analytics.gold_velo_lyon_hourly_2025`, `analytics.gold_velo_lyon_daily_2025`, `analytics.gold_lyon_croisement_2025`, `analytics.gold_lyon_correlations_2025`.

**Indicateur de mobilité :** sommes des **baisses horaires de vélos disponibles**, uniquement entre deux snapshots d'une même station séparés d'une heure, normalisées en **départs apparents pour 100 station-heures valides**. Ce proxy n'est PAS le nombre réel de trajets.

**Indicateur statistique :** `r_activite_temperature`, `r_activite_vent`, `r_activite_precipitation`. Comparer aussi les jours de semaine et les week-ends pour vérifier la sensibilité au contexte.

**Graphe :** nuage de points (X = température moyenne du jour ; Y = départs apparents normalisés), et ligne mensuelle de la variation du proxy.

**Conclusion à compléter après exécution :** reprendre les valeurs réelles de `SELECT * FROM analytics.gold_lyon_correlations_2025`. Un `r` positif (négatif) indique une association positive (négative), et un `r` proche de zéro ne montre pas de lien *linéaire* significatif dans cet échantillon. Ne pas conclure à un effet causal ; des variables (jour de semaine, saisons, vacances, rééquilibrage) ne sont pas contrôlées.

**Texte oral (modèle, compléter les coefficients) :**
> « Initialement nous n'avions pas d'historique vélo cohérent avec la météo. Nous avons ajouté 3,57 millions de relevés horaires de stations lyonnaises pour 2025. Nous estimons les variations d'activité à partir des baisses de vélos disponibles, normalisées par le nombre d'observations valides. En croisant par jour avec la météo de Lyon, nous obtenons r = [R_TEMP] pour la température et r = [R_PLUIE] pour la pluie. Il s'agit d'une association entre météo et *activité apparente*, et non d'une mesure directe des trajets ni d'une preuve causale. »

## Q3 — Conditions météorologiques favorables à la mobilité douce (**ta partie**)

**Table :** `analytics.gold_lyon_conditions_mobilite_2025`.

**Hypothèse transparente :** un « environnement favorable relatif » combine : température dans l'intervalle interquartile observé à Lyon en 2025 et vent, pluie, ozone, PM2.5 inférieurs ou égaux aux **médianes** de la période locale. Ce sont des **seuils exploratoires** : ni recommandations sanitaires ni conditions universelles de pratique.

**Nouvelle possibilité grâce aux vélos :** comparer l'**activité apparente normalisée** des journées qualifiées de favorables aux autres journées évaluables. Mesurer aussi un coefficient point-bisérial via `CORR(0/1, activité)` ; si aucun jour favorable ou aucun contraste, le coefficient est NULL et il faut présenter la comparaison météo favorable / air favorable **séparément**.

**Graphe :** colonnes comparant l'activité moyenne « environnement favorable » vs « autres jours évaluables », complétées par le % de jours favorables par mois.

**Important :** si le proxy d'activité augmente, cela suggère une association sur ces relevés lyonnais ; si la différence est faible ou inverse, ne pas forcer la conclusion. Les moyennes et leur écart peuvent varier avec les week-ends et la couverture des stations.

**Texte oral (45 sec) :**
> « Nous ne nous sommes pas contentés de définir une belle journée. Une journée chaude peut aussi avoir davantage d'ozone ; nous intégrons donc météo ET pollution. Nous avons fixé une grille de conditions favorables relative à Lyon en 2025, puis comparé l'activité apparente des stations pendant ces journées aux autres. Nous obtenons [N] journées favorables sur [TOTAL] évaluables, et une activité apparente moyenne de [A] contre [B] baisses de stock par 100 station-heures. Le coefficient avec l'indicateur favorable est r = [R]. C'est un résultat descriptif utile pour évaluer une hypothèse de mobilité douce, pas une démonstration causale ni une norme de santé. »

## Q4 — Périodes d'interactions météo, pollution et mobilité (**ta partie**)

**Table :** `analytics.gold_lyon_episodes_2025`.

**Méthode :** calculer des scores Z par variable sur l'intersection lyonnaise de 2025 : `z = (valeur - moyenne) / écart_type`. Pour le vent faible, le signe est inversé. Identifier d'abord les épisodes météo-pollution : chaleur + ozone élevé, ou vent faible + NO₂ élevé (scores >= +1). Ajouter la condition **|z_activite| >= 1** pour repérer, sur le même jour, une activité apparente anormalement **haute ou basse**.

**Indicateurs :** nombre de journées `episode_triple_chaleur_ozone_mobilite`, nombre de journées `episode_triple_vent_no2_mobilite` ; coefficient `CORR(z_activite,z_ozone)` et `CORR(z_activite,z_no2)`.

**Graphes :** (1) séries temporelles des scores Z (à filtrer sur des journées/périodes significatives), (2) nuage de points X = z_temp, Y = z_ozone avec dates et z_activite au survol ; (3) barres par mois du nombre d'épisodes triples.

**Texte oral (45 sec) :**
> « Nous avons enfin recherché des journées où les trois phénomènes étaient atypiques simultanément. Plutôt que d'additionner des degrés, des microgrammes et des vélos, nous avons standardisé chaque mesure par un score Z. Les épisodes chaleur–ozone ou vent faible–NO₂ ont été croisés avec des changements inhabituels de disponibilité des vélos. Nous identifions [N1] et [N2] épisodes conjoints, avec des corrélations activité–ozone de [R1] et activité–NO₂ de [R2]. Cette analyse met en évidence des co-occurrences dans les observations, pas une influence causale démontrée. »

## Lecture rapide du coefficient de Pearson

- `r` proche de **+1** : relation linéaire positive ; proche de **−1** : négative ; proche de **0** : peu ou pas de relation *linéaire*.
- Le **signe** indique une direction, la **valeur absolue** donne une idée de l'intensité descriptive.
- Corrélation n'est pas causalité ; examiner **n**, valeurs aberrantes, saisonnalité, jour de semaine et différences d'emplacement des stations.
- Les corrélations calculées ne constituent pas à elles seules un test d'hypothèse (aucune p-value ni intervalle de confiance calculés ici).
- Ne **jamais** inventer les valeurs Q2/Q3/Q4 : les chiffres sont à remplir après exécution sur la base `main_bd`.

## Démonstration live recommandée (2-3 minutes)

1. Montrer la présence de `public.silver_velo_stations_2025` et ses dates, comparer aux sources météo/pollution.
2. Afficher la table persistante `analytics.gold_lyon_croisement_2025` (une ligne par jour, champs des **trois sources**).
3. Afficher Q1 : 42 corrélations, pointer Lyon ozone/température (+0,754).
4. Afficher Q2 : coefficient météo–activité et scatter plot.
5. **Ta partie Q3 :** indicateur favorable, barres d'activité ; commenter limites.
6. **Ta partie Q4 :** scores Z, épisodes triples et graphique ; expliquer co-occurrence ≠ causalité.
7. Conclure sur la robustesse et améliorations : historique de trajets réels, coordonnées NOAA précises, fuseaux horaires et contrôle saisonnier.
