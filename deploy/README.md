# Déploiement

Fichiers de déploiement Docker pour `hydro-forecast-ouysse`.

| Fichier | Rôle |
|---|---|
| [`docker-compose.yml`](docker-compose.yml) | Orchestration du conteneur API en production. |
| [`.env`](.env) / [`.env.example`](.env.example) | Variables d'environnement de production (template). |
| [`publish-docker-image.ps1`](publish-docker-image.ps1) | Script de build + push de l'image vers un registry Docker. |

## Pré-requis

- Docker + Docker Compose installés sur le serveur cible
- Accès à un registry Docker pour héberger l'image (à configurer dans `docker-compose.yml`)
- Volumes locaux préparés sur le serveur (`./configs`, `./states`, `./backups`, `./data`)

## Configuration

1. Copier `.env.example` vers `.env` et adapter si besoin :

   ```bash
   cp .env.example .env
   ```

   Variables disponibles :
   - `API_PORT` — port exposé sur l'hôte (défaut `5000`)
   - `LOG_LEVEL` — niveau de log (`INFO`, `DEBUG`, `WARNING`, `ERROR`)
   - `LOG_FORMAT` — `text` (défaut, lisible) ou `json` (structuré pour ELK/Loki)
   - `RATE_LIMIT_DEFAULT` / `RATE_LIMIT_FORECAST` — limites de débit API
   - `BACKUP_RETENTION_DAYS` — rétention des backups d'états (jours)

2. Adapter [`docker-compose.yml`](docker-compose.yml) :
   - Remplacer `{YOUR_REGISTRY}` par l'URL de ton registry Docker
   - Vérifier les chemins de volumes (`./configs`, `./states`, ...)

3. Préparer les configs de points de mesure dans `./configs/points/` (un fichier YAML par point — voir [hydro_forecast_api/CONTRIBUTING.md](../hydro_forecast_api/CONTRIBUTING.md#ajouter-un-nouveau-point-de-mesure)).

## Build & publication de l'image

```powershell
# Build local + push vers le registry configuré dans le script
.\publish-docker-image.ps1
```

Pré-requis : `docker login` sur ton registry au préalable.

## Démarrage en production

```bash
# Récupérer la dernière image
docker pull {YOUR_REGISTRY}/hydro-forecast-ouysse:latest

# Lancer
docker compose up -d

# Vérifier
curl http://localhost:5000/health
docker compose logs -f
```

## Mise à jour

```bash
# Pull de la nouvelle image
docker compose pull

# Redémarrage avec la nouvelle image (les volumes — états, configs, backups — sont préservés)
docker compose up -d
```

## Opérations courantes

| Action | Commande |
|---|---|
| Logs en direct | `docker compose logs -f` |
| Statut healthcheck | `docker compose ps` |
| Redémarrer | `docker compose restart` |
| Arrêter | `docker compose down` |
| Stats ressources | `docker stats hydro-forecast-api` |

## Volumes

| Volume | Contenu | Sauvegarde recommandée |
|---|---|---|
| `./configs` | Définitions YAML des points de mesure | Versionné (git) |
| `./states` | États courants des réservoirs (JSON) | Backup quotidien |
| `./backups` | Snapshots automatiques des états (avant chaque run) | Rotation auto (`BACKUP_RETENTION_DAYS`) |
| `./data` | Base SQLite des tâches asynchrones | Backup quotidien |

## Endpoints exposés

- `GET /health` — liveness (Docker healthcheck)
- `GET /readiness` — readiness check
- `GET /metrics` — métriques Prometheus
- `GET /` — Swagger UI (documentation interactive de l'API)

Voir [hydro_forecast_api/README.md](../hydro_forecast_api/README.md) pour la liste complète des endpoints fonctionnels.
