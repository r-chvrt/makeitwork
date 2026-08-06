# MakeItWork 💼

Agrégateur d'offres d'emploi : interroge **Welcome to the Jungle**, **Indeed** et **Hellowork** en parallèle et affiche les résultats dans une interface web unique (thème clair / sombre).

## Fonctionnalités

- Recherche par **métier / mots-clés** et **zone géographique** (ville, code postal…) avec rayon réglable (10–100 km)
- Pour chaque offre : titre, entreprise, lieu, **date de publication**, **salaire** (ou « non indiqué »), **télétravail** (total / partiel / occasionnel / non précisé), type de contrat, **résumé** et **lien vers l'annonce d'origine**
- Filtres : salaire indiqué uniquement, télétravail uniquement ; tri par date ou pertinence
- Thème **clair / sombre** avec bouton de bascule (préférence mémorisée, suit le thème système par défaut)
- Les erreurs d'une source n'empêchent pas les autres de répondre (bandeau d'avertissement)
- **Épinglés** : chaque offre peut être épinglée avec une couleur / un statut — 🔵 À postuler, 🟠 Postulé, 🟢 Entretien — via les pastilles en haut à droite des cartes. Onglet « 📌 Épinglées » groupé par statut. Stockage **côté serveur en SQLite** (`data/makeitwork.db`), rien dans le navigateur : un vidage de cache ne perd rien.

## Épinglés & SSO

Pas de gestion de compte dans l'app : l'authentification est déléguée au reverse-proxy (Traefik forward-auth).
Si le proxy injecte l'en-tête `X-Forwarded-User`, chaque utilisateur a sa propre liste d'épinglés ;
sans en-tête, tout va dans une liste partagée (`default`). L'offre est snapshotée en base au moment de
l'épinglage : elle reste consultable même si l'annonce disparaît des sites.

API : `GET /api/pins` · `PUT /api/pins` (`{"status": "a_postuler|postule|entretien", "offer": {...}}`) · `DELETE /api/pins?url=…`

## Comment ça marche

| Source | Méthode |
|---|---|
| Welcome to the Jungle | API de recherche Algolia du site (index `wttj_jobs_production_fr`), géoloc via l'API Adresse data.gouv.fr |
| Indeed | API GraphQL de l'application mobile (`apis.indeed.com`) — le site web est protégé par Cloudflare |
| Hellowork | Parsing HTML de la page de recherche + pages détail (en parallèle) pour les résumés |

- **Déduplication** : une offre publiée sur plusieurs sites n'apparaît qu'une fois (similarité titre + entreprise + lieu compatibles). La carte fusionnée garde l'offre la plus complète, récupère les infos manquantes des doublons (ex : le salaire indiqué seulement sur Hellowork), et liste les autres sites en « Aussi sur … ».

## Déploiement Docker (derrière Traefik)

```bash
docker compose up -d --build
```

- La base des épinglés est persistée dans `./data` (monté sur `/app/data`).
- Les labels Traefik sont dans [docker-compose.yml](docker-compose.yml) : adapter le `Host(...)` et le nom du middleware SSO (`sso@file`).
- Pour des listes d'épinglés **séparées par personne**, le middleware forward-auth doit propager l'en-tête `X-Forwarded-User` (option `authResponseHeaders` de Traefik). Sans cet en-tête, la liste est partagée.
- Test rapide sans Traefik : décommenter le mapping `ports` puis ouvrir http://serveur:8000.

## Lancement

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Puis ouvrir http://127.0.0.1:8000

## Installation (si nouvel environnement)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## API

`GET /api/search?q=développeur+python&location=Paris&sources=wttj,indeed,hellowork&limit=15&radius_km=30`

Réponse : `{ "results": [...], "errors": {}, "took_ms": 1200 }`

## Limites connues

- Les scrapers dépendent de la structure interne des sites : si un site change son HTML ou ses clés d'API, le scraper correspondant peut casser (l'erreur s'affiche alors dans l'interface, les autres sources continuent de fonctionner).
- Les clés utilisées (Algolia WTTJ, API mobile Indeed) sont les clés **publiques** embarquées dans les apps officielles ; usage personnel raisonnable recommandé.
- La date Hellowork est reconstituée depuis « il y a X jours » (précision au jour près).
