# Faire tourner le modèle de l'Ouysse sur un PC Windows

Ce guide explique, **pas à pas et sans pré-requis technique**, comment exécuter l'API de prévision
de l'Ouysse en local sur une machine Windows. Il permet de lancer des prévisions soi-même, de
comparer le fonctionnement avec ou sans assimilation des débits observés, et de consulter l'état des
réservoirs — le tout indépendamment de la chaîne de production.

> En local, le modèle utilise **ses propres fichiers d'état** de réservoirs, distincts de ceux de la
> production. Voir la section [Les états des réservoirs en local](#les-états-des-réservoirs-en-local).

---

## 1. Ce dont on a besoin

- Un PC sous **Windows 10 ou 11** (64 bits).
- Une connexion **Internet** (le modèle télécharge les prévisions météo ARPEGE de Météo-France, qui
  sont publiques — aucun identifiant requis).
- Environ **5 Go d'espace disque** libre et 4 Go de RAM disponibles.
- **Docker Desktop** (installé à l'étape suivante). Docker est un outil qui fait tourner l'API dans un
  « conteneur » isolé : pas besoin d'installer Python ni aucune autre dépendance à la main.

---

## 2. Installer Docker Desktop

1. Télécharger Docker Desktop pour Windows : <https://www.docker.com/products/docker-desktop/>
2. Lancer l'installateur, accepter les options par défaut (laisser cochée l'option **WSL 2** si elle
   est proposée).
3. **Redémarrer Windows** à la fin de l'installation.
4. Démarrer **Docker Desktop** depuis le menu Démarrer et attendre que l'icône (la baleine, en bas à
   droite près de l'horloge) indique que Docker est démarré (« Docker Desktop is running »).

Vérification : ouvrir **PowerShell** (menu Démarrer → taper « PowerShell » → Entrée) et saisir :

```powershell
docker --version
```

Une ligne du type `Docker version 27.x.x, build ...` doit s'afficher. Si c'est le cas, Docker est
prêt.

> Si la commande n'est pas reconnue, c'est que Docker Desktop n'est pas démarré ou que Windows n'a pas
> été redémarré après l'installation.

---

## 3. Récupérer le code

Deux options, au choix.

**Option simple (sans Git)** — depuis la page GitHub du dépôt :
1. Cliquer sur le bouton vert **« Code »** puis **« Download ZIP »**.
2. Décompresser le ZIP, par exemple dans `C:\Users\<nom>\Documents\ouysse`.

**Option avec Git** (si Git est installé) :
```powershell
git clone <url-du-depot> C:\Users\<nom>\Documents\ouysse
```

Dans la suite, on suppose que le dépôt se trouve dans `C:\Users\<nom>\Documents\ouysse`.

---

## 4. Démarrer l'API

Pour une **exécution locale**, tout se passe dans le sous-dossier `hydro_forecast_api`. (Le dossier
`deploy/` sert à un autre usage — un déploiement sur un serveur avec une image pré-construite — et
n'est pas nécessaire ici.)

Dans PowerShell :

```powershell
# Se placer dans le dossier de l'API
cd C:\Users\<nom>\Documents\ouysse\hydro_forecast_api

# Préparer le fichier de configuration (à faire une seule fois)
Copy-Item .env.example .env

# Construire et lancer l'API
docker compose up -d
```

Le **premier lancement** télécharge et construit l'image : cela peut prendre **2 à 5 minutes**, et
l'affichage semble parfois figé — c'est normal. Les fois suivantes, le démarrage est quasi immédiat.

Vérifier que l'API répond :

```powershell
curl http://localhost:5000/health
```

Une réponse `{"status": "ok"}` indique que tout fonctionne.

---

## 5. Utiliser l'API depuis le navigateur (Swagger)

Pas besoin de ligne de commande pour piloter l'API : une interface web (Swagger) permet de tout faire
depuis le navigateur.

Ouvrir : **<http://localhost:5000/>**

On y voit la liste des opérations disponibles. Pour chacune : cliquer dessus pour la déplier, cliquer
sur **« Try it out »**, remplir les champs, puis cliquer sur **« Execute »**. Le résultat s'affiche
juste en dessous.

### 5.1 Lancer une prévision

1. Déplier **`POST /api/v1/points/{point_id}/forecast`**, cliquer sur **« Try it out »**.
2. Dans le champ `point_id`, saisir `ouysse`.
3. Dans le corps de la requête (« Request body »), saisir par exemple :

   ```json
   {
     "lastQ_datetime": "2026-06-25T11:00:00",
     "tributaries": {
       "themines": {"lastQ": 2.28},
       "alzou": {"lastQ": 2.28}
     },
     "karstmod": {"lastQ": 2.57}
   }
   ```

   - `lastQ_datetime` est la date de référence de la prévision (le « maintenant » du modèle).
   - Les `lastQ` sont les derniers débits observés, utilisés pour recaler la sortie (assimilation).
4. Cliquer sur **« Execute »**. La réponse renvoie un `task_id` : la prévision tourne en arrière-plan.
5. Déplier **`GET /api/v1/tasks/{task_id}`**, « Try it out », coller le `task_id`, « Execute ».
   Quand `status` vaut `completed`, le champ `result` contient les débits prévus (`records`).

### 5.2 Voir le fonctionnement « libre » (sans assimilation)

Pour observer le modèle **sans recalage par les débits observés** (la « trajectoire libre »), il
suffit de **ne pas fournir de `lastQ`**. Par exemple :

```json
{
  "lastQ_datetime": "2026-06-25T11:00:00"
}
```

La prévision est alors la sortie brute du modèle. Dans la réponse, `metadata.assimilation_applied`
vaut `false`. En lançant deux prévisions (une avec `lastQ`, une sans) à la même `lastQ_datetime`, on
peut comparer directement l'effet de l'assimilation.

---

## 6. Consulter l'état des réservoirs

Les « états » sont les niveaux d'eau internes du modèle (réservoirs des modèles GR4H et KarstMod),
conservés d'une prévision à l'autre pour assurer la continuité.

Dans Swagger : déplier **`GET /api/v1/points/{point_id}/states`**, « Try it out », saisir `ouysse`,
« Execute ». La réponse liste l'état de chaque composant (par ex. `themines_gr4h`, `karstmod`), avec
un `state_time` indiquant la date que représente cet état.

---

## 7. Les états des réservoirs en local

- En exécution locale, les états sont stockés sur **cette machine**, dans le dossier :
  `C:\Users\<nom>\Documents\ouysse\hydro_forecast_api\states\ouysse\`
- Ces fichiers sont **indépendants** de ceux de la chaîne de production : exécuter le modèle en local
  ne modifie rien côté production, et inversement.
- Au tout premier run, si aucun état n'existe encore, le modèle démarre avec des **réservoirs par
  défaut** ; les états réels sont créés ensuite automatiquement.
- **Supprimer le dossier `states/`** revient à repartir de réservoirs « à froid » : les premières
  prévisions sont alors dégradées le temps que les réservoirs se recalent. Il est donc conseillé de
  ne pas y toucher, et de le sauvegarder si l'on veut conserver un historique.

---

## 8. Arrêter, relancer, repartir de zéro

```powershell
# Arrêter l'API (les états sont conservés)
docker compose down

# Relancer
docker compose up -d

# Voir les logs en direct (diagnostic)
docker compose logs -f
```

---

## 9. Problèmes fréquents

| Symptôme | Cause probable / solution |
|---|---|
| `docker : ... n'est pas reconnu` | Docker Desktop n'est pas démarré, ou Windows n'a pas été redémarré après l'installation. |
| Le démarrage semble bloqué plusieurs minutes | Normal au **premier** lancement (construction de l'image). Patienter. |
| `port is already allocated` / port 5000 occupé | Une autre application utilise le port 5000. Modifier `API_PORT` dans le fichier `.env` (par ex. `API_PORT=5001`) puis relancer `docker compose up -d`, et utiliser `http://localhost:5001/`. |
| `http://localhost:5000/` ne s'ouvre pas | Vérifier que le conteneur tourne (`docker compose ps`) et consulter `docker compose logs -f`. |
| La prévision échoue avec un code `STATE_TOO_OLD_FOR_AUTO_RESET` | L'état local est trop ancien (> 7 jours). Voir le README de l'API, section *Troubleshooting*. |

---

Pour aller plus loin (liste complète des endpoints, format détaillé des réponses, variables de
configuration), voir [hydro_forecast_api/README.md](hydro_forecast_api/README.md) et
[hydro_forecast_api/docs/API_RESPONSES.md](hydro_forecast_api/docs/API_RESPONSES.md).
