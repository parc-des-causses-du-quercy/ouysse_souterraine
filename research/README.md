# research/ — matériel d'élaboration scientifique

Ce dossier contient tout ce qui a servi à **concevoir** le modèle de prévision de l'Ouysse, distinct de ce qui le fait tourner en **production**.

## Attribution

Le contenu de ce dossier (notebook chercheur, script monolithique d'origine, paramètres KarstMod calibrés, états initiaux) constitue le **code scientifique d'origine** du projet. Il est la **propriété du Parc naturel régional des Causses du Quercy et des chercheurs du SNO Karst** ayant développé le modèle KarstMod.

Synapse Informatique SARL, qui a réalisé l'intégration de production dans [`hydro_forecast_api/`](../hydro_forecast_api/) et [`deploy/`](../deploy/), n'exerce aucun droit de propriété intellectuelle sur ce dossier — il est conservé ici pour traçabilité scientifique et validation croisée.

Voir le fichier [LICENSE](../LICENSE) racine (section B) pour les détails et conditions de réutilisation.

## Frontière prod / élaboration

| Vivant | Emplacement | Statut |
|---|---|---|
| Production | [`hydro_forecast_api/`](../hydro_forecast_api/) | API Flask déployée. Source de vérité fonctionnelle. |
| Production | [`deploy/`](../deploy/) | Build et publication Docker. |
| Élaboration | `research/` (ce dossier) | Référence scientifique figée + outils de validation. |

Toute évolution **fonctionnelle** se fait dans `hydro_forecast_api/`. `research/` ne bouge que pour acter une nouvelle correction scientifique de référence (nouveau notebook, mise à jour de paramètres calibrés, etc.).

Pour comprendre les flux opérationnels de l'API (horodatage, cadence asymétrique, assimilation, auto-reset, cache ARPEGE), voir [`hydro_forecast_api/docs/ARCHITECTURE.md`](../hydro_forecast_api/docs/ARCHITECTURE.md) — c'est le doc de référence transverse.

## Contenu

| Sous-dossier | Rôle |
|---|---|
| [`notebook/`](notebook/) | Notebook chercheur d'origine (`Modèle_Ouysse_corrigé.ipynb`). Référence scientifique vivante — c'est ce qui définit le comportement attendu du modèle. Voir le [README dédié](notebook/README.md) pour les écarts intentionnels avec l'API. |
| [`legacy_script/`](legacy_script/) | Première version monolithique du modèle (`modèle_Ouysse.py`) avec ses dépendances Python (`requirements.txt`). Conservé comme jalon historique ; **la référence vivante est le notebook**, pas ce script. |
| [`parameters/`](parameters/) | Paramètres KarstMod calibrés au format CSV (`params_ouysse.csv`). Source de vérité pour les valeurs reportées dans `hydro_forecast_api/configs/points/ouysse.yaml`. |
| [`states/`](states/) | États initiaux des réservoirs (JSON) du modèle d'origine. Conservés pour traçabilité ; en production les états vivent dans `hydro_forecast_api/states/` et évoluent à chaque run. |
## Reproduire la chaîne d'origine

Le notebook est exécutable tel quel dans Jupyter (nécessite l'environnement Python décrit dans `legacy_script/requirements.txt`). Le script monolithique peut aussi être lancé directement :

```powershell
python -m venv venv_research
.\venv_research\Scripts\activate
pip install -r research\legacy_script\requirements.txt
python "research\legacy_script\modèle_Ouysse.py"
```

Le script lit ses paramètres et états dans `research/parameters/` et `research/states/` via des chemins relatifs à sa propre position : il peut être lancé depuis n'importe quel cwd.

