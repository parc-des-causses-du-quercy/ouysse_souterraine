# Guide du développeur

Documentation pour contribuer au code de l'API. Pour l'utilisation, voir le [README](README.md). Pour comprendre les flux opérationnels critiques (horodatage, cadence asymétrique, assimilation, auto-reset, cache ARPEGE, concurrence) **avant** de modifier `state_advance.py`, `forecast_service.py`, `gr4h_runner.py` ou la config Gunicorn, lire **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Architecture en couches

```
Requête HTTP
    |
    v
 api/            Blueprints Flask (validation, routage)
    |                 Pas de logique métier ici.
    v
 services/       Logique métier (orchestration, I/O, états)
    |                 Lève des exceptions métier.
    v
 models/         Calculs numériques (GR4H, KarstMod, ARPEGE)
    |                 Fonctions stateless, pas de fichier I/O.
    v
 db/             Persistance SQLite (tâches)
```

Règle principale : **chaque couche ne connaît que la couche en dessous**.
Un blueprint ne doit jamais appeler un model runner directement.

## Structure des fichiers

```
app/
├── __init__.py              # App factory : logging, extensions, blueprints, error handlers
├── config.py                # Variables d'environnement → attributs de classe
├── extensions.py            # CORS, rate limiter, Swagger (Flasgger)
├── maintenance.py           # Thread daemon : purge tâches + backups toutes les heures
├── api/                     # 1 fichier = 1 blueprint
│   ├── __init__.py          #   register_blueprints()
│   ├── forecast.py          #   POST /forecast, GET/DELETE /tasks
│   ├── points.py            #   GET /points (read-only)
│   ├── states.py            #   GET /states (read-only)
│   ├── sensors.py           #   GET /sensors
│   ├── health.py            #   /health, /readiness
│   └── metrics.py           #   /metrics (Prometheus)
├── services/
│   ├── config_service.py    #   Chargement YAML + cache mtime
│   ├── forecast_service.py  #   Pipeline complet : ARPEGE → GR4H → KarstMod
│   ├── state_service.py     #   JSON + FileLock + backup auto
│   └── task_service.py      #   ThreadPoolExecutor(1) + SQLite
├── models/
│   ├── arpege_fetcher.py    #   Fetch ARPEGE, moyennes spatiales, PE-Oudin
│   ├── arpege_cache.py      #   Cache thread-safe avec TTL (6h)
│   ├── state_advance.py     #   Fenêtres advance/forecast (cf. section dédiée plus bas)
│   ├── gr4h_runner.py       #   Wrapper stateless hydrogr.ModelGr4h
│   ├── karstmod_runner.py   #   Wrapper stateless du moteur numba
│   └── karstmod_engine.py   #   Fonctions @njit — ne pas modifier sans tests
├── schemas/                 #   Schémas Marshmallow (validation)
└── db/
    └── tasks.py             #   Schéma SQLite + CRUD tâches
```

## Conventions par couche

### api/ — Handlers HTTP

Un handler doit :
1. Valider l'entrée (existence du point, format du body)
2. Appeler un service
3. Retourner du JSON

```python
@bp.route("/points/<point_id>/something", methods=["GET"])
def get_something(point_id):
    try:
        result = some_service.do_thing(point_id)
    except PointNotFoundError:
        return jsonify({"error": {
            "code": "POINT_NOT_FOUND",
            "message": f"Point '{point_id}' not found",
            "details": None,
        }}), 404
    return jsonify(result), 200
```

Format d'erreur (toujours le même) :
```json
{"error": {"code": "ERROR_CODE", "message": "...", "details": null}}
```

### services/ — Logique métier

- Lèvent des exceptions métier (`PointNotFoundError`, `ForecastError`)
- Gèrent le I/O (fichiers YAML, JSON, SQLite)
- Loguent avec `extra={}` pour les champs structurés

### models/ — Calculs

- **Stateless** : toutes les entrées en arguments, pas de `self`, pas de fichier
- Retournent `(outputs_df, new_states)`
- Pas de logging sauf pour les durées

```python
def run_my_model(input_df, params, states=None, lastQ=None):
    # calcul...
    return outputs_df, new_states
```

### karstmod_engine.py — Attention

Fonctions `@njit` compilées par Numba. Code copié du modèle original validé.
Ne modifier qu'avec des tests numériques de non-régression.

## Ajouter un endpoint

1. Créer ou compléter un blueprint dans `app/api/`
2. L'enregistrer dans `app/api/__init__.py` → `register_blueprints()`
3. Déléguer à un service (jamais de logique métier dans le handler)
4. Documenter dans la docstring Flasgger (Swagger)

## Ajouter un modèle / affluent

1. Créer `app/models/new_runner.py` avec une fonction `run_new_model()`
2. L'appeler depuis `forecast_service.run_forecast()`
3. Gérer les états via `state_service.load_state()` / `save_state()`
4. Ajouter la config dans le YAML du point

## Ajouter un nouveau point de mesure

Un point de mesure = un fichier YAML dans `configs/points/` + un dossier d'états dans `states/`.

### 1. Créer le fichier YAML

Le nom du fichier **doit** correspondre au `point_id` : `configs/points/{point_id}.yaml`.

Structure minimale :

```yaml
point_id: mon_point          # Doit correspondre au nom du fichier
display_name: "Mon Point"    # Nom lisible (non utilisé par le code, documentation uniquement)
latitude: 44.74              # Latitude en degrés décimaux (pour le calcul d'ETP PE-Oudin)

karstmod:
  params:
    # 8 paramètres obligatoires (issus de la calibration)
    RA: 650.0                # Surface du bassin récepteur (km²)
    kCS: 0.239               # Coefficient de vidange conduit → source
    kMS: 0.028               # Coefficient de vidange matrice → source
    kMC: 0.0016              # Coefficient d'échange matrice ↔ conduit
    kEM: 0.00036             # Coefficient épikarst → matrice
    kEC: 0.00001             # Coefficient épikarst → conduit
    alphaMS: 3.59            # Exposant non-linéaire matrice → source
    alphaMC: 2.06            # Exposant non-linéaire matrice ↔ conduit
    # Paramètres optionnels (valeurs par défaut si omis)
    Emin: -15.0              # Niveau minimum épikarst
    aEM: 1.0                 # Exposant épikarst → matrice
    aEC: 1.0                 # Exposant épikarst → conduit
    aES: 1.0                 # Exposant épikarst → source
    kES: 0.0                 # Coefficient épikarst → source directe
    kloss: 0.0               # Coefficient de pertes
    aloss: 1.0               # Exposant de pertes
    Eloss: 100000.0          # Seuil de pertes
  arpege_grid:
    indices:                  # Points de grille ARPEGE 0.01° couvrant le bassin
      - [246, 336]
      - [246, 337]
      # ...
    weights: [0.020, 0.063]  # Poids de chaque point (somme = 1, proportionnels à la surface)

tributaries:
  - basin_id: affluent_1     # Identifiant de l'affluent (nom du fichier d'état)
    gr4h_params:
      X1: 289.604            # Capacité du réservoir de production (mm)
      X2: -1.837             # Coefficient d'échange souterrain (mm/h)
      X3: 59.018             # Capacité du réservoir de routage (mm)
      X4: 5.03               # Temps de base de l'hydrogramme unitaire (h)
    catchment_area_km2: 55.62
    arpege_grid:
      indices:
        - [247, 338]
        - [247, 339]
      weights: [0.043, 0.169]

  - basin_id: affluent_2
    gr4h_params: {X1: 320.0, X2: -1.5, X3: 54.0, X4: 27.0}
    catchment_area_km2: 53.2
    arpege_grid:
      indices:
        - [248, 337]
        - [248, 338]
      weights: [0.275, 0.724]

qsink_formula:
  multiplier: 1.2            # Facteur multiplicatif sur la somme des débits affluents
```

### 2. Déterminer les grilles ARPEGE

Les indices correspondent aux points de la grille ARPEGE 0.01° (résolution ~1 km).
Pour un point de coordonnées (lat, lon) :
- Indice ligne ≈ `(lat - origin_lat) / 0.01`
- Indice colonne ≈ `(lon - origin_lon) / 0.01`

Les poids représentent la proportion de surface du bassin versant couverte par chaque maille.
Leur somme doit être égale à 1 (ou très proche).

### 3. Calibrer les paramètres

- **GR4H** (X1–X4) : calibration sur les données observées de chaque affluent via la bibliothèque `hydrogr`
- **KarstMod** (RA, kCS, kMS, etc.) : calibration sur les données observées à l'exutoire via KarstMod desktop ou optimisation numérique
- **qsink_formula.multiplier** : ratio entre la somme des affluents modélisés et le Qsink total réel (compense les affluents non modélisés)

### 4. Créer le dossier d'états (optionnel)

Au premier lancement, si le dossier `states/{point_id}/` n'existe pas, les modèles démarrent avec des états par défaut (réservoirs vides). Après le premier run, les états sont créés automatiquement :

```
states/{point_id}/
├── {basin_id}_gr4h.json     # Un par affluent
└── karstmod.json
```

### 5. Vérifier

```bash
# L'API détecte le nouveau point automatiquement (pas de redémarrage nécessaire)
curl http://localhost:5000/api/v1/points

# Lancer une première prévision
curl -X POST http://localhost:5000/api/v1/points/{point_id}/forecast \
  -H "Content-Type: application/json" \
  -d '{
    "lastQ_datetime": "2026-03-18T14:00:00",
    "tributaries": {
      "affluent_1": {"lastQ": 1.5},
      "affluent_2": {"lastQ": 0.8}
    },
    "karstmod": {"lastQ": 2.3}
  }'
```

### Renommer un point existant

Si tu renommes le `point_id`, il faut aussi renommer :
1. Le fichier YAML : `configs/points/{ancien}.yaml` → `configs/points/{nouveau}.yaml`
2. Le `point_id` à l'intérieur du YAML
3. Le dossier d'états : `states/{ancien}/` → `states/{nouveau}/`
4. Le dossier de backups : `backups/{ancien}/` → `backups/{nouveau}/`

Les noms des fichiers d'état (`{basin_id}_gr4h.json`) ne changent que si tu renommes aussi les `basin_id`.

## Flux d'une prévision

```
POST /forecast
 └─ forecast.py valide, soumet à task_service
     └─ ThreadPoolExecutor (1 worker)
         └─ forecast_service.run_forecast()
              ├─ config_service.load_point_config()
              ├─ arpege_fetcher.fetch_arpege_for_grids()
              │   ├─ Vérifie arpege_cache (TTL 6h)
              │   ├─ Si miss : fetch API Météo-France (~2 min)
              │   └─ Moyennes spatiales pondérées + PE-Oudin
              ├─ Pour chaque affluent :
              │   ├─ state_service.load_state()
              │   ├─ gr4h_runner.run_gr4h()
              │   └─ state_service.save_state()
              ├─ Somme des débits → Qsink (× multiplicateur)
              ├─ state_service.load_state("karstmod")
              ├─ karstmod_runner.run_karstmod()
              ├─ state_service.save_state("karstmod")
              └─ Retourne le résultat

GET /tasks/{id}  →  Interroge SQLite  →  Retourne statut + résultat
```

## Logging

```python
import logging
logger = logging.getLogger(__name__)

# Toujours utiliser extra pour les champs structurés
logger.info("Model run completed", extra={
    "duration_seconds": 3.45,
    "point_id": "ouysse",
})
```

Sortie texte (défaut) :
```
2026-03-18 14:05:32,000 [INFO] app.models.gr4h_runner: Model run completed | duration_seconds=3.45 point_id=ouysse
```

Niveaux :
- `INFO` : événements normaux (démarrage, fin de tâche, run modèle)
- `WARNING` : dégradations (retry ARPEGE, fallback cache périmé)
- `ERROR` : échecs (tâche échouée, erreur service)
- `DEBUG` : cache hit/miss, détails requêtes

## Gestion des états

```
states/{point_id}/{component}.json       # État courant
backups/{point_id}/{YYYYMMDD_HHMMSS}/    # Backup auto avant écrasement
```

- Écriture atomique (`.tmp` + rename)
- Verrouillage par `FileLock` (accès concurrent)
- Nettoyage auto des backups > 7 jours

### Fenêtrage temporel — `state_advance.py`

Chaque état persisté porte le timestamp `T_state` de l'instant qu'il représente. Quand une nouvelle prévision arrive avec `lastQ_datetime = T_target`, deux fenêtres sont calculées par `compute_sim_window(df_index, state_time, target_time)` :

- **advance window** : rows ARPEGE dans `]T_state, T_target]`. Permet d'avancer l'état d'exactement `T_target − T_state`, indépendamment de la cadence des appels.
- **forecast window** : rows postérieures à `T_state` (full simulation). Inclut la fenêtre advance puis la prévision proprement dite.

Garde-fous (`StateAdvanceError`) :
- Erreur si `T_target − T_state > ADVANCE_MAX_HOURS` (24 h) — l'état est trop vieux pour être avancé en confiance. Récupéré automatiquement par `forecast_service` (voir « Reprise après dérive d'état »).
- Avertissement si `> ADVANCE_WARN_HOURS` (6 h).
- Si `T_state` précède le début des données ARPEGE :
  - Backward gap ≤ `BACKWARD_TOLERANCE_HOURS` (6 h) — *clip silencieux* à `data_start`, log INFO. Cas typique d'un roll-forward d'ARPEGE entre deux mises à jour d'assimilation à cadence lente (alzou). La perte de quelques heures de météo est négligeable face à la stabilité du pipeline.
  - Backward gap > 6 h — `StateAdvanceError` levée (capturée ensuite par l'auto-reset si forward gap ≤ 7 j).

Les runners (`gr4h_runner`, `karstmod_runner`) utilisent ces masques pour : (1) avancer l'état d'entrée jusqu'à `T_target`, (2) lancer la simulation de prévision sur la fenêtre complète, (3) repersister l'état avancé avec le nouveau timestamp.

### Reprise après dérive d'état (auto-recovery)

**Pourquoi ça arrive** : si le client n'envoie plus de données pendant plus de 24 h, l'état persisté devient « trop vieux » par rapport au `lastQ_datetime` reçu. ARPEGE ne fournit que du futur (run le plus récent → +96 h), il n'y a donc pas de pluie passée pour faire un véritable warmup forward des réservoirs sur la période de coupure. La seule récupération automatique réaliste est un **reset** depuis les valeurs par défaut du YAML.

**Trois régimes** dans `forecast_service.run_forecast` :

| Écart `T_target − T_state` | Comportement |
|---|---|
| `≤ 24 h` (`ADVANCE_MAX_HOURS`) | Pipeline normal. `metadata.state_was_reset = False`. |
| `24 h < gap ≤ 168 h` (`AUTO_RESET_MAX_HOURS` = 7 j) | **Auto-reset** : log `ERROR` avec `alarm=STATE_AUTO_RESET`, backup horodaté dans `backups/{point_id}/YYYYMMDD_HHMMSS/`, suppression des fichiers d'état, retry du forecast (qui passe par la branche `state_time=None`). Réponse : `metadata.state_was_reset = True` + `metadata.reset_reason = "..."`. Compteur `state_resets_total{point_id, reason="age"}` incrémenté. |
| `gap > 168 h` | **Refus** : log `CRITICAL` avec `alarm=STATE_TOO_OLD_FOR_AUTO_RESET`, `ForecastError(code="STATE_TOO_OLD_FOR_AUTO_RESET")` propagée jusqu'au client via `task.error`. Aucune suppression d'état. Intervention humaine requise (procédure ci-dessous). |

Le seuil 7 j n'existe pas pour interdire une procédure technique différente — la procédure manuelle est *identique* au reset auto. Il existe pour **forcer une vérification humaine** que la cause racine de la coupure est réellement résolue avant que l'API ne se répare elle-même, et pour qu'une trace écrite finisse dans le run-book.

**Conséquences hydrologiques d'un reset** :
- Les réservoirs (`production_store`, `routing_store` GR4H ; `wlE`, `C`, `M` KarstMod) reviennent aux valeurs par défaut du YAML.
- L'assimilation de `lastQ` corrige immédiatement le débit prévu à T+0 — le client voit un débit cohérent dès le pas 0.
- Les pas plus lointains (T+24 h..T+96 h) sont moins fiables tant que les réservoirs n'ont pas reconvergé via les assimilations quotidiennes (typiquement 24-48 h).
- Le karst (constantes de temps de plusieurs semaines pour `M`) peut rester loin du réel ; ce n'est généralement perceptible qu'en régime hydrologique extrême.

**Comment monitorer** :
```promql
# Alerte simple : un reset est arrivé dans la dernière heure
increase(state_resets_total[1h]) > 0

# Alerte préventive : approche du seuil ADVANCE_MAX_HOURS
# (nécessite l'ajout d'une gauge state_age_hours, pas encore implémenté)
```
Et bien sûr, grep des logs sur `STATE_AUTO_RESET` ou `STATE_TOO_OLD_FOR_AUTO_RESET`.

**Procédure d'intervention manuelle** (cas `STATE_TOO_OLD_FOR_AUTO_RESET`) :

1. **Diagnostic** — vérifier que le client est revenu en ligne. Tant que la cause racine de la coupure n'est pas levée, recommencer ne sert à rien.
   ```bash
   docker compose logs api --since 24h | grep "Forecast task started"
   ```

2. **Backup ceinture+bretelles** (le code fait déjà un backup, on double pour les longues coupures) :
   ```bash
   cd hydro_forecast_api
   cp -r states/{point_id} states/{point_id}.bak.$(date +%Y%m%d_%H%M%S)
   ```

3. **Reset manuel** (techniquement identique à l'auto-reset) :
   ```bash
   rm -f states/{point_id}/*.json
   ```

4. **Relancer un forecast normal** : le pipeline prend la branche `state_time=None` et tout repart. La réponse aura `metadata.state_was_reset = False` (cold start, pas un reset déclenché par erreur).

5. **Tracer l'intervention dans un run-book** : qui, quand, durée de la coupure constatée, raison. Utile pour décider plus tard si un keep-alive externe ou une instrumentation client supplémentaire est nécessaire.

6. **Surveiller la convergence** pendant 24-48 h : comparer débits prévus / observés et noter les écarts.

## Exécution asynchrone

Les prévisions tournent dans un `ThreadPoolExecutor(max_workers=1)` :
- 1 seule prévision à la fois (les suivantes sont en file d'attente)
- Le thread HTTP n'est jamais bloqué
- Le client poll `GET /tasks/{id}` jusqu'à `completed` ou `failed`
- Les tâches sont persistées en SQLite (survit aux redémarrages)

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests/
```
