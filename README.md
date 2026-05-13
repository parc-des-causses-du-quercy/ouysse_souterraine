# Modèle de prévision hydrologique — Bassin de l'Ouysse

Ce dépôt contient le modèle de prévision des débits de l'Ouysse, rivière du Lot dont l'exutoire est une source karstique. Le système combine :

- **GR4H** (`hydrogr`) — modèle pluie-débit horaire pour les affluents (Thémines, Alzou).
- **KarstMod** — modèle d'aquifère karstique (épikarst + matrice/conduit) implémenté en Numba pour la source de l'Ouysse.
- **ARPEGE** (`meteofetch`) — données de prévision météo Météo-France comme forçage pluie/température.
- **PE-Oudin** (`pe_oudin`) — calcul de l'évapotranspiration potentielle.
- **Assimilation** — correction du débit modélisé à partir du dernier débit observé.

## Structure du dépôt

Le dépôt sépare nettement les deux faces du projet : ce qui tourne en **production**, et ce qui a servi à le **concevoir**.

| Élément | Rôle |
|---|---|
| [`hydro_forecast_api/`](hydro_forecast_api/) | **API Flask de production** : modèles encapsulés derrière une API REST asynchrone avec Swagger. Voir son [README](hydro_forecast_api/README.md) et son [guide développeur](hydro_forecast_api/CONTRIBUTING.md). |
| [`deploy/`](deploy/) | Scripts de déploiement Docker (build et publication d'image). |
| [`research/`](research/) | **Matériel d'élaboration scientifique** : notebook chercheur de référence, script monolithique d'origine, paramètres et états initiaux, outils de validation croisée. Voir [`research/README.md`](research/README.md) pour la cartographie détaillée. |

## Démarrer en production (API)

```bash
cd hydro_forecast_api
cp .env.example .env
docker compose up -d
```

Swagger UI : http://localhost:5000/

Voir [hydro_forecast_api/README.md](hydro_forecast_api/README.md) pour les exemples d'appels et la liste des endpoints.

## Reproduire la chaîne d'origine ou valider l'API

Le notebook chercheur (référence scientifique) et le script monolithique vivent dans [`research/`](research/). Pour rejouer la chaîne d'origine ou comparer l'API à la référence, voir [`research/README.md`](research/README.md).

## Pré-requis

- Python 3.11+
- Docker + Docker Compose (pour la production)
- Accès Internet (téléchargement des grilles ARPEGE depuis Météo-France)

## Crédits & propriété intellectuelle

Ce dépôt contient deux strates distinctes de propriété intellectuelle. Le fichier [LICENSE](LICENSE) à la racine décrit le cadre précis ; les paragraphes ci-dessous résument l'attribution.

### Éditeur / intégrateur production

**Synapse Informatique SARL** — [synapse-info.com](https://synapse-info.com) — a conçu et développé l'**API de prévision** ([`hydro_forecast_api/`](hydro_forecast_api/)) et l'**infrastructure de déploiement** ([`deploy/`](deploy/)), dans le cadre d'un contrat d'intégration avec le Parc naturel régional des Causses du Quercy.

© 2025-2026 Synapse Informatique SARL. Tous droits réservés sur le code d'intégration. Voir [LICENSE](LICENSE), section A.

### Commanditaire / bénéficiaire d'usage

**Parc naturel régional des Causses du Quercy** — commanditaire de l'intégration, utilisateur final de la solution pour le suivi hydrologique du bassin de l'Ouysse, et co-titulaire (avec les chercheurs du SNO Karst) du modèle scientifique versionné dans [`research/`](research/).

### Modèles scientifiques

Le code de production met en œuvre trois modèles issus de la communauté scientifique. Toute publication ou présentation s'appuyant sur ce projet est invitée à citer leurs auteurs et institutions :

- [**KarstMod**](https://github.com/snokarst-tools/KarstMod) — modèle pluie-débit karstique développé par les chercheurs du **SNO Karst** (Service National d'Observation du Karst, INSU/CNRS).
  
- [**GR4H**](https://github.com/hydrogr/airgr) — modèle pluie-débit horaire à 4 paramètres, famille GR développée par **INRAE** (anciennement IRSTEA / Cemagref). Voir le package [airGR](https://hydrogr.github.io/airGR/).

- [**PE-Oudin**](https://github.com/hydrogr/airgr) — formulation de l'évapotranspiration potentielle par Ludovic Oudin (INRAE), implémentée dans le package airGR.

Pour les références bibliographiques précises de chaque modèle, se rapporter à la documentation officielle des institutions citées.

Le contenu de [`research/`](research/) (notebook chercheur, script monolithique d'origine, paramètres calibrés, états initiaux) est **la propriété du Parc et des chercheurs du SNO Karst**. Synapse Informatique l'utilise dans le cadre du contrat d'intégration mais n'en revendique pas la propriété — voir [LICENSE](LICENSE) section B et [`research/README.md`](research/README.md).
