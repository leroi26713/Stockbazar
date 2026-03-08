# REDESTOCK

REDESTOCK est une application de gestion boutique orientee terrain (Togo):
- suivi stock (entrees/sorties)
- alertes de rupture
- gestion dettes clients (credit boutique)
- dashboard indicateurs
- recu de paiement apres encaissement d'une dette

## Demarrage local (WSL recommande)

```bash
cd /mnt/c/Users/HP/Desktop/Stockbazar/StockBazar_v2/backend
./start.sh
```

Le script `start.sh`:
- utilise un environnement virtuel dedie WSL: `.venv_wsl`
- installe les dependances
- cree `.env` depuis `.env.example` si absent
- lance l'API + frontend sur le port `8010`

Ecran d'authentification:
- Connexion affichee en premier
- Bloc "Creer un compte" juste sous le formulaire de connexion

URLs:
- App: `http://127.0.0.1:8010/`
- Docs API: `http://127.0.0.1:8010/docs`
- Health: `http://127.0.0.1:8010/api/health`

## Demarrage local (CMD/PowerShell Windows)

```bat
cd C:\Users\HP\Desktop\Stockbazar\StockBazar_v2\backend
py -m venv .venv_win
.venv_win\Scripts\activate
pip install -r requirements.txt
if not exist .env copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

## Authentification API

Les routes metier exigent un token Bearer:
1. Creer un compte: `POST /api/auth/signup`
2. Se connecter: `POST /api/auth/login`
3. Envoyer le header: `Authorization: Bearer <token>`

Exemples de routes protegees:
- `GET /api/products`
- `POST /api/products`
- `POST /api/stock/move`
- `POST /api/debts`
- `POST /api/debts/{id}/pay`
- `GET /api/summary`

## Endpoints utiles

- `GET /api/auth/me`
- `GET /api/products`
- `GET /api/alerts/low-stock`
- `GET /api/debts`
- `GET /api/debts/followups?status=overdue&limit=30`
- `GET /api/debts/export.csv?status=all&q=client`
- `GET /api/stock/movements?limit=50`
- `GET /api/debts/{id}/payments`
- `GET /api/receipts/verify/{receipt_number}`

## Notes environnement

- Sous WSL, ne pas reutiliser un venv cree depuis Windows (`venv`/`.venv_win`).
- Utiliser `.venv_wsl` pour eviter les conflits de binaire Python.
- Si besoin de repartir proprement sous WSL:

```bash
cd /mnt/c/Users/HP/Desktop/Stockbazar/StockBazar_v2/backend
rm -rf .venv_wsl
./start.sh
```

- Sauvegarder la base SQLite:

```bash
cd /mnt/c/Users/HP/Desktop/Stockbazar/StockBazar_v2/backend
./backup_db.sh
```

## Hebergement (Render)

Le projet inclut deja un fichier `render.yaml` pret pour deployment:
- service web Python
- port dynamique `$PORT`
- base SQLite persistante sur disque Render (`/var/data/stockbazar.db`)
- uploads persistants (`/var/data/uploads`)

### Etapes

1. Creer un depot GitHub et pousser le projet.
2. Sur Render, cliquer **New +** -> **Blueprint**.
3. Connecter le repo GitHub.
4. Render detecte `render.yaml` et propose le service `stockbazar`.
5. Lancer le deploy.

### Variables importantes

Dans Render (Environment), verifier:
- `AUTH_SECRET` (genere automatiquement, ne pas partager)
- `CORS_ALLOW_ORIGINS` (`*` en MVP, a restreindre ensuite a ton domaine)

### URL apres deploy

- App: `https://<ton-service>.onrender.com/`
- Docs API: `https://<ton-service>.onrender.com/docs`
