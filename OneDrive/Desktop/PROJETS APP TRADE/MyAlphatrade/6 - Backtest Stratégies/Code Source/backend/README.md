# AlphaTrade Strategy Lab -- Backend

Backend autonome (FastAPI + SQLite) qui remplace le SDK Base44 pour
l'outil de backtest de strategies. Isole du reste du repo AlphaTrade :
ne partage ni base de donnees ni code avec les autres backends du projet.

## Lancer en local

```bash
cd "6 - Backtest Stratégies/Code Source/backend"
pip install -r requirements.txt
cp .env.example .env   # ajuster si besoin (JWT_SECRET notamment)
uvicorn main:app --reload --port 8010
```

Le fichier SQLite (`data/strategylab.db`) est cree automatiquement au
premier demarrage.

## Config (`.env`)

- `JWT_SECRET` -- secret de signature des JWT (a changer en prod)
- `DB_PATH` -- chemin du fichier SQLite (relatif au dossier backend/ si pas absolu)
- `CORS_ORIGINS` -- origines autorisees, separees par des virgules (defaut `http://localhost:5173`)
- `PORT` -- port d'ecoute (defaut `8010`)

## Endpoints

### Auth

- `POST /auth/register` `{email, password, full_name}` -> `{token, user}`
- `POST /auth/login` `{email, password}` -> `{token, user}`
- `GET /auth/me` (Bearer token) -> `{id, email, full_name, created_at}`
- `POST /auth/logout` -> `{ok: true}` (no-op cote serveur, JWT stateless)

### Entites (CRUD generique, scope automatiquement par utilisateur connecte)

Types autorises : `TradingAsset`, `Strategy`, `BacktestResult`, `PaperTrade`,
`Signal`, `MarketData`.

- `GET /entities/{entity_type}?sort=-created_date&limit=500`
- `POST /entities/{entity_type}` `{...champs}`
- `PUT /entities/{entity_type}/{id}` `{...champs a mettre a jour}`
- `DELETE /entities/{entity_type}/{id}`

Toutes ces routes exigent `Authorization: Bearer <token>` et ne
retournent/modifient que les enregistrements appartenant a l'utilisateur
connecte (404 si l'enregistrement n'existe pas ou appartient a quelqu'un
d'autre).
