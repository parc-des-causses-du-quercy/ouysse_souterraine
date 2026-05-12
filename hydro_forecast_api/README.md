# Hydro Forecast API

API REST de prévision hydrologique pour les systèmes karstiques.
Combine les modèles GR4H (pluie-débit) et KarstMod (aquifère karstique) avec les données météorologiques ARPEGE de Météo-France.

## Démarrage rapide

### Avec Docker (recommandé)

```bash
# Copier et configurer l'environnement
cp .env.example .env

# Lancer l'API
docker compose up -d

# Vérifier que ça tourne
curl http://localhost:5000/health
```

L'interface Swagger est accessible à la racine : **http://localhost:5000/**

### Sans Docker (développement)

```bash
# Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt

# Lancer le serveur
python wsgi.py
```

## Utilisation

### 1. Lister les points de mesure configurés

```bash
curl http://localhost:5000/api/v1/points
```

### 2. Lancer une prévision

```bash
curl -X POST http://localhost:5000/api/v1/points/ouysse/forecast \
  -H "Content-Type: application/json" \
  -d '{
    "lastQ_datetime": "2026-03-12T14:00:00",
    "tributaries": {
      "themines": {"lastQ": 2.28},
      "alzou": {"lastQ": 2.28}
    },
    "karstmod": {"lastQ": 2.57}
  }'
```

Réponse (202 Accepted) :
```json
{
  "task_id": "a1b2c3d4-...",
  "point_id": "ouysse",
  "status": "pending",
  "poll_url": "/api/v1/tasks/a1b2c3d4-..."
}
```

### 3. Récupérer le résultat

```bash
curl http://localhost:5000/api/v1/tasks/{task_id}
```

Quand `status` = `completed`, le champ `result` contient la prévision complète :
- `records` : débits prévus par capteur (exutoire + affluents) — `[[offset_h, débit_m3s], ...]`
- `forecast_date`, `arpege_reference_time`, `offset_unit`
- `metadata` :
  - `assimilation_applied` (bool) — `lastQ` fournis et appliqués
  - `active_tributaries` (list)
  - `qsink_multiplier` (float)
  - `state_was_reset` (bool) — `true` si l'API a auto-réinitialisé un état trop vieux avant cette prévision
  - `reset_reason` (string|null) — détail si `state_was_reset = true`

### 4. Lister les tâches

```bash
# Toutes les tâches
curl http://localhost:5000/api/v1/tasks

# Filtrer par point et statut
curl "http://localhost:5000/api/v1/tasks?point_id=ouysse&status=completed"
```

**Format des réponses (succès et erreurs) — contrat unique** : voir [docs/API_RESPONSES.md](docs/API_RESPONSES.md). C'est la référence à utiliser côté client pour modéliser les types de désérialisation. Ne pas inférer les schémas depuis des exemples — l'API a déjà eu un cas où un client `(client C# orchestrateur)` avait modélisé `task.error` en `string` alors qu'il s'agit d'un objet `{code, message, details}` ; c'est précisément ce que le contrat documenté évite.

## Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/api/v1/points/{id}/forecast` | Lancer une prévision (async) |
| `GET` | `/api/v1/tasks/{id}` | Statut et résultat d'une tâche |
| `GET` | `/api/v1/tasks` | Liste des tâches |
| `DELETE` | `/api/v1/tasks/{id}` | Supprimer une tâche |
| `GET` | `/api/v1/points` | Liste des points configurés |
| `GET` | `/api/v1/points/{id}` | Config d'un point |
| `GET` | `/api/v1/points/{id}/sensors` | Capteurs d'entrée/sortie |
| `GET` | `/api/v1/points/{id}/states` | États des réservoirs |
| `GET` | `/api/v1/points/{id}/states/{comp}` | État d'un composant |
| `GET` | `/health` | Liveness check |
| `GET` | `/readiness` | Readiness check |
| `GET` | `/metrics` | Métriques Prometheus |

## Configuration

### Variables d'environnement (.env)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `FLASK_ENV` | `production` | Environnement Flask |
| `API_PORT` | `5000` | Port de l'API |
| `LOG_LEVEL` | `INFO` | Niveau de log (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FORMAT` | `text` | Format des logs (text ou json) |
| `RATE_LIMIT_DEFAULT` | `60/minute` | Rate limit global |
| `RATE_LIMIT_FORECAST` | `10/minute` | Rate limit sur /forecast |
| `PROMETHEUS_ENABLED` | `true` | Activer les métriques Prometheus |
| `BACKUP_RETENTION_DAYS` | `7` | Durée de conservation des backups |

### Configuration d'un point de mesure

Chaque point est un fichier YAML dans `configs/points/`. Voir `configs/points/ouysse.yaml` pour un exemple complet.

Le fichier contient :
- Paramètres GR4H calibrés par affluent
- Paramètres KarstMod calibrés
- Grilles ARPEGE (indices et poids) par composant
- Multiplicateur Qsink

Pour ajouter un nouveau point, voir le [guide du développeur](CONTRIBUTING.md#ajouter-un-nouveau-point-de-mesure).

## Architecture

```
POST /forecast  -->  TaskService (ThreadPool 1 worker)
                         |
                    ForecastService
                    /       |        \
              GR4H x N   ARPEGE    KarstMod
                    \       |        /
                     Résultat + États sauvés
                         |
                    GET /tasks/{id}  -->  Résultat
```

- **Asynchrone** : les prévisions sont exécutées en arrière-plan
- **File d'attente** : ThreadPoolExecutor avec 1 worker (mono-prévision)
- **États persistants** : les niveaux des réservoirs sont conservés entre les runs
- **Backup automatique** : les états sont sauvegardés avant chaque modification

Pour le détail des flux opérationnels (horodatage, cadence asymétrique, assimilation, auto-reset, cache ARPEGE, concurrence) avec diagrammes Mermaid, voir **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Logs

Les logs sont émis sur stdout en format texte lisible par défaut :
```
2026-03-12 14:05:32,000 [INFO] app.services.forecast_service: Forecast completed | point_id=ouysse duration_total_seconds=96.92
```

Pour du JSON structuré (Docker, Portainer, ELK), définir `LOG_FORMAT=json` dans `.env`.

## Troubleshooting

### Tâche en `failed` avec `StateAdvanceError` ou code `STATE_TOO_OLD_FOR_AUTO_RESET`

Ce scénario survient quand le client n'a pas alimenté l'API en `lastQ` pendant plus de 24 h (ARPEGE n'archive pas le passé, donc l'état des réservoirs ne peut pas être avancé numériquement sans observation intermédiaire).

- **Coupure < 7 jours** : l'API se réinitialise automatiquement à la requête suivante. La réponse contient `metadata.state_was_reset = true` et un `reset_reason` explicite. Les prévisions T+24..T+96 h sont dégradées 24-48 h le temps que les réservoirs reconvergent. Aucune action.
- **Coupure ≥ 7 jours** : l'API refuse pour forcer une vérification humaine. Le code d'erreur est `STATE_TOO_OLD_FOR_AUTO_RESET`. Procédure de reprise détaillée dans le runbook : [CONTRIBUTING.md § Reprise après dérive d'état](CONTRIBUTING.md#reprise-après-dérive-détat-auto-recovery).

Métriques associées :
- Compteur Prometheus `state_resets_total{point_id, reason}` exposé sur `/metrics`
- Logs : grep `STATE_AUTO_RESET` (auto-reset effectué) ou `STATE_TOO_OLD_FOR_AUTO_RESET` (refus, alerte critique)
