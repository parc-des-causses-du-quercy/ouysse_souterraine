# Notebook de référence — Modèle_Ouysse_corrigé.ipynb

Ce notebook est la **référence scientifique vivante** de la chaîne de prévision Ouysse. Il définit le comportement attendu du modèle ; l'API [`hydro_forecast_api/`](../../hydro_forecast_api/) doit en reproduire les résultats numériques aux écarts intentionnels près (cf. tableau plus bas).

## Origine

- **Auteur** : Gaëtan (Parc naturel régional des Causses du Quercy), maintenu en collaboration avec les chercheurs du SNO Karst (modèle KarstMod).
- **Version intégrée** : `Modèle_Ouysse_corrigé.ipynb` — incorpore deux correctifs :
  1. Contournement du gestionnaire de données de la librairie `hydrogr` : appel direct au moteur Rust (`hydrogr._hydrogr.gr4h`) via `run_gr4h_direct()` pour éviter les artefacts de routage.
  2. Warm-up explicite d'1h des états avant la simulation de prévision (re-instanciation du modèle avec les états initiaux).
- **Date d'intégration côté API** : avril 2026 (suite à l'échange mail de Gaëtan du 30 avril 2026).

## Pourquoi un notebook plutôt qu'un script ?

Le notebook reflète la façon dont les chercheurs raisonnent et itèrent sur le modèle (cellules, sorties commentées, jeux de test). Le script `legacy_script/modèle_Ouysse.py` est une version antérieure conservée pour traçabilité ; **en cas de divergence, le notebook fait foi**.

## Écarts intentionnels API ↔ notebook

L'API ne reproduit pas le notebook au caractère près : trois adaptations ont été faites pour la production. Aucune n'altère la logique scientifique.

| # | Sujet | Notebook | API | Justification |
|---|---|---|---|---|
| 1 | Pluies négatives | `np.diff(prepend=0)` peut produire des valeurs < 0 si ARPEGE saute un timestep | [`arpege_fetcher.py:153`](../../hydro_forecast_api/app/models/arpege_fetcher.py) ajoute `np.maximum(..., 0)` | Une pluie physique ne peut pas être négative ; le notebook tolère par construction de `np.diff` |
| 2 | Warm-up des états | Warm-up fixe d'1h via `model.run(df.iloc[:1])` puis re-instanciation | [`state_advance.py`](../../hydro_forecast_api/app/models/state_advance.py) calcule `Δt = T_target − T_state` dynamiquement, avance l'état d'exactement Δt | Robuste aux runs ratés et aux changements de cadence (4h → 1h sans toucher au code). Strictement équivalent au notebook quand T_state = T_target − 1h |
| 3 | Coefficient 1.2 sur Qsink | Hardcodé dans la cellule main (`(Themines + Alzou) * 1.2`) | [`configs/points/ouysse.yaml`](../../hydro_forecast_api/app/configs/points/ouysse.yaml) `qsink_formula.multiplier: 1.2`, boucle sur tributaires actifs dans [`forecast_service.py`](../../hydro_forecast_api/app/services/forecast_service.py) | Theminettes activable plus tard sans toucher au code. Comportement identique aujourd'hui pour Ouysse |

**Vérifié strictement identique** : paquet ARPEGE (`SP1`), variables (`t2m, tp`), drop `step`, dot product avec weights, conversion K→°C, PE-Oudin (lat=44.74, `mm/hour`), paramètres GR4H (X1/X2/X3/X4, surfaces 55.62/53.2/42.1), lecture CSV KarstMod, engine numba (`tf_E`, `tf_MC`, `MCth`, `ki_seuil`, `Eth`) copié ligne pour ligne, constantes `Emin=-15`, `aEM=aEC=aES=1`, `kES=0`, `kloss=0`, `aloss=1`, `Eloss=1e5`, `aCS=1`, formule d'assimilation et conversions m³/s ↔ mm/h.

## Mettre à jour le notebook de référence

Quand Gaëtan transmet une nouvelle version corrigée :

1. Remplacer le fichier `Modèle_Ouysse_corrigé.ipynb` ici.
3. Si un nouvel écart apparaît, soit l'intégrer dans l'API et croiser ici dans le tableau, soit le documenter comme dérive temporaire.
4. Mettre à jour la section "Origine" ci-dessus (auteur, date, nature de la correction).
5. Committer avec un message du type `Update reference notebook (Gaëtan, YYYY-MM-DD): <résumé correction>`.
