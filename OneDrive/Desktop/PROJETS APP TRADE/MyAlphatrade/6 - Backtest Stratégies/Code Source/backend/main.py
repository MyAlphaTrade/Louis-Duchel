"""
AlphaTrade Strategy Lab - Backend API
Backend autonome (SQLite local) qui remplace le SDK Base44 pour l'outil de
backtest de strategies. Isole du reste du repo AlphaTrade -- ne partage ni
base de donnees ni code avec `4 - Backend API/alphatrade-backend`.

Style inspire de ce backend existant (helpers de connexion DB, JWT via
Depends(HTTPBearer), routes FastAPI plates) mais stack differente :
sqlite3 (stdlib) au lieu de pg8000/Postgres, PyJWT + bcrypt au lieu de
jose + sha256/pepper.
"""
import os
import json
import secrets
import sqlite3
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import requests
import resend
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "strategy-lab-dev-secret-changez-moi")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "strategylab.db"))
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, DB_PATH)

CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

PORT = int(os.environ.get("PORT", 8010))

# Pont Export Signaux (Module 5) vers le backend AlphaTrade reel -- seule
# exception deliberee a l'isolation de Strategy Lab. Aucun mot de passe ni
# jeton AlphaTrade n'est jamais stocke ici : /alphatrade/login relaie
# l'authentification a la volee (meme principe BYOK que /ai/generate) et
# /alphatrade/send-signal relaie chaque envoi avec le jeton fourni par le
# frontend a chaque appel (garde en localStorage cote client, jamais en DB).
ALPHATRADE_API_URL = os.environ.get(
    "ALPHATRADE_API_URL", "https://web-production-9312ae.up.railway.app"
)
ALPHATRADE_REQUEST_TIMEOUT = 15
# Doit rester en phase avec ce que le backend AlphaTrade accepte reellement
# pour la commande EXTERNAL_SIGNAL (4 - Backend API/alphatrade-backend/main.py).
ALPHATRADE_SIGNAL_SYMBOLS = {"XAUUSD"}

# Pont prix live MT5 (Module 4 / Paper Trading, mode Live). Paquet Windows
# uniquement, et ne fonctionne que si un terminal MetaTrader 5 est installe
# ET ouvert sur cette meme machine. L'import est protege par un try/except
# (meme pattern que AlphaTrade v4.1.0 - Claude/python/alphatrade_engine.py,
# code de reference en lecture seule, non copie) pour que l'absence du
# package ne fasse jamais planter le demarrage du serveur -- seul l'appel a
# /market-data/live echouera, proprement, avec un message clair.
try:
    import MetaTrader5 as mt5  # type: ignore
except Exception as exc:  # pragma: no cover - depend de l'OS/l'installation
    mt5 = None
    MT5_IMPORT_ERROR = str(exc)
else:
    MT5_IMPORT_ERROR = ""

# Chemins d'installation courants essayes si mt5.initialize() sans argument
# echoue (terminal ferme au demarrage silencieux, ou installe hors PATH).
MT5_PATH_CANDIDATES = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
]

# Reinitialisation de mot de passe par email -- meme prestataire (Resend) et
# meme pattern (lien + token expirant en DB) que le backend AlphaTrade
# existant. Si RESEND_API_KEY est absente (dev sans cle configuree), l'envoi
# est simplement journalise plutot que de planter -- le flow reste testable
# via le token visible dans les logs serveur.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
resend.api_key = RESEND_API_KEY
EMAIL_FROM = os.environ.get("EMAIL_FROM", "AlphaTrade Strategy Lab <noreply@myalphatrade.com>")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
RESET_TOKEN_EXPIRE_MINUTES = 30

# Actifs crees automatiquement pour tout nouveau compte (register) -- avant
# ca, un compte fraichement cree n'avait litteralement aucun actif ni bouton
# visible pour en ajouter facilement (le bouton existe, mais uniquement sur
# la page Gestion des actifs, pas sur Donnees de marche). Donnees reelles
# de Louis, deja utilisees tout au long de cette session -- jamais inventees.
# L'utilisateur reste libre de les supprimer (Gestion des actifs) ou d'en
# ajouter d'autres ensuite, ce sont juste des valeurs de depart.
DEFAULT_ASSETS = [
    {
        "name": "Gold Spot", "symbol": "XAUUSD", "category": "Métaux",
        "description": "Or au comptant face au dollar américain",
        "broker": "Multiple", "color": "amber", "icon": "Coins",
        "status": "active", "digits": 2, "pip_size": 0.01, "default_timeframe": "M15",
    },
    {
        "name": "Boom 1000 Index", "symbol": "BOOM1000", "category": "Indices synthétiques",
        "description": "Index synthétique avec pics haussiers occasionnels",
        "broker": "Deriv", "color": "emerald", "icon": "TrendingUp",
        "status": "active", "digits": 2, "pip_size": 0.001, "default_timeframe": "M1",
    },
    {
        "name": "Crash 1000 Index", "symbol": "CRASH1000", "category": "Indices synthétiques",
        "description": "Index synthétique avec chutes occasionnelles",
        "broker": "Deriv", "color": "rose", "icon": "TrendingDown",
        "status": "active", "digits": 2, "pip_size": 0.001, "default_timeframe": "M1",
    },
    {
        "name": "VIX 75 Index", "symbol": "VIX75", "category": "Indices de volatilité",
        "description": "Index de volatilité basé sur 75 composantes",
        "broker": "Multiple", "color": "violet", "icon": "Activity",
        "status": "active", "digits": 2, "pip_size": 0.01, "default_timeframe": "M5",
    },
]


def seed_default_assets(cur, user_id: int) -> None:
    now = now_iso()
    for asset in DEFAULT_ASSETS:
        cur.execute(
            "INSERT INTO entities (id, user_id, entity_type, data, created_date, updated_date) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, "TradingAsset", json.dumps(asset), now, now),
        )


# Les 7 "entities" Base44 : User est couvert par la table `users` (auth
# dediee) ; les 6 autres sont stockees generiquement dans `entities`,
# scopees par utilisateur.
ENTITY_TYPES = {
    "TradingAsset",
    "Strategy",
    "BacktestResult",
    "PaperTrade",
    "Signal",
    "MarketData",
}

# Colonnes reelles autorisees pour le tri (le prefixe "-" = DESC). On ne
# trie jamais sur une cle arbitraire du JSON `data` pour eviter toute
# injection dans l'ORDER BY.
SORTABLE_COLUMNS = {"created_date", "updated_date", "id"}
DEFAULT_LIMIT = 500
# Un historique MT5 d'un an en M15 fait environ 35 000 bougies -- la limite
# doit rester largement au-dessus de ça pour que le moteur de backtest puisse
# relire tout l'historique importe en un seul appel.
MAX_LIMIT = 200_000
MAX_IMPORT_CANDLES = 200_000

app = FastAPI(title="AlphaTrade Strategy Lab API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer()

# ── DB helpers ───────────────────────────────────────────────────────────────
# SQLite en local : zero serveur, zero credentials. Schema relationnel reel
# (users + entities), requetes parametrees avec des placeholders "?" -- pas
# de f-string SQL, pas de syntaxe SQLite exotique (pas de PRAGMA cache dans
# les requetes metier, pas de UPSERT propriétaire) pour qu'un portage vers
# Postgres plus tard reste une histoire de driver, pas de reecriture.
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor(commit: bool = False):
    """Ouvre une connexion + curseur, ferme toujours proprement. commit=True
    valide la transaction si le bloc ne leve pas d'exception."""
    conn = get_db()
    try:
        cur = conn.cursor()
        yield conn, cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


def rows_to_dicts(rows) -> list:
    return [dict(r) for r in rows]


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            data TEXT NOT NULL,
            created_date TEXT NOT NULL,
            updated_date TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_user_type ON entities(user_id, entity_type)"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()

# ── Auth helpers ─────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(user_id: int, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalide ou expire")
    if payload.get("user_id") is None:
        raise HTTPException(status_code=401, detail="Token invalide")
    return payload


def get_current_user(token=Depends(verify_token)) -> dict:
    """Recharge l'utilisateur depuis la DB (pas seulement le payload JWT) pour
    detecter un compte supprime entre-temps."""
    with db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM users WHERE id = ?", (token["user_id"],))
        user = row_to_dict(cur.fetchone())
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return user


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "created_at": user["created_at"],
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_reset_password_email(email: str, full_name: str, token: str) -> None:
    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
    if not RESEND_API_KEY:
        print(f"[strategy-lab] RESEND_API_KEY absente -- lien de reinitialisation pour {email} : {reset_url}")
        return
    try:
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [email],
            "subject": "Reinitialisation de votre mot de passe — AlphaTrade Strategy Lab",
            "html": f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0e17;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0e17;padding:40px 0">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#0d1220;border-radius:16px;border:1px solid #1a2332;overflow:hidden">
        <tr>
          <td style="background:#0d1220;padding:28px 40px;border-bottom:1px solid #1a2332">
            <span style="font-size:22px;font-weight:800;letter-spacing:-0.5px;color:#f1f5f9">AlphaTrade</span>
            <span style="font-size:11px;color:#f59e0b;letter-spacing:1.5px;text-transform:uppercase;margin-left:10px">Strategy Lab</span>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 40px;color:#cbd5e1">
            <p style="font-size:15px;line-height:1.6;margin:0 0 20px">Bonjour {full_name or ''},</p>
            <p style="font-size:15px;line-height:1.6;margin:0 0 24px">
              Une demande de reinitialisation de mot de passe a ete faite pour votre compte.
              Ce lien est valable {RESET_TOKEN_EXPIRE_MINUTES} minutes.
            </p>
            <table cellpadding="0" cellspacing="0"><tr><td style="border-radius:10px;background:linear-gradient(135deg,#f59e0b,#d97706)">
              <a href="{reset_url}" style="display:inline-block;padding:13px 28px;color:#0a0e17;font-weight:700;font-size:14px;text-decoration:none">
                Reinitialiser mon mot de passe
              </a>
            </td></tr></table>
            <p style="font-size:12px;color:#64748b;line-height:1.6;margin:24px 0 0">
              Si vous n'etes pas a l'origine de cette demande, ignorez cet email.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>""",
        })
    except Exception as exc:
        print(f"[strategy-lab] echec envoi email reset a {email} : {exc}")


# ── Modeles ──────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── Routes racine ────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "AlphaTrade Strategy Lab API", "version": "0.1.0", "status": "ok"}


# ── Auth ─────────────────────────────────────────────────────────────────────
@app.post("/auth/register")
def register(req: RegisterRequest):
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email invalide")
    if not req.password or len(req.password) < 6:
        raise HTTPException(400, "Le mot de passe doit faire au moins 6 caracteres")

    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            raise HTTPException(400, "Email deja utilise")
        created_at = now_iso()
        cur.execute(
            "INSERT INTO users (email, password_hash, full_name, created_at) VALUES (?, ?, ?, ?)",
            (email, hash_password(req.password), req.full_name or "", created_at),
        )
        user_id = cur.lastrowid
        seed_default_assets(cur, user_id)
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = row_to_dict(cur.fetchone())

    return {"token": create_token(user["id"], user["email"]), "user": public_user(user)}


@app.post("/auth/login")
def login(req: LoginRequest):
    email = req.email.strip().lower()
    with db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = row_to_dict(cur.fetchone())

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Email ou mot de passe incorrect")

    return {"token": create_token(user["id"], user["email"]), "user": public_user(user)}


@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return public_user(user)


@app.post("/auth/logout")
def logout():
    # JWT stateless -> rien a invalider cote serveur. Route conservee pour
    # compat avec le contrat attendu par le frontend (ex-SDK Base44).
    return {"ok": True}


@app.post("/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    # Message generique dans tous les cas (compte existant ou non) pour ne
    # jamais reveler si un email est enregistre -- meme comportement que le
    # backend AlphaTrade existant.
    generic = {"message": "Si ce compte existe, un email de reinitialisation a ete envoye."}
    email = req.email.strip().lower()
    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = row_to_dict(cur.fetchone())
        if not user:
            return generic
        cur.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)).isoformat()
        cur.execute(
            "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user["id"], expires_at),
        )
    send_reset_password_email(user["email"], user["full_name"], token)
    return generic


@app.post("/auth/reset-password")
def reset_password(req: ResetPasswordRequest):
    if len(req.new_password) < 6:
        raise HTTPException(400, "Le mot de passe doit faire au moins 6 caracteres")
    with db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT * FROM password_reset_tokens WHERE token = ?", (req.token,))
        row = row_to_dict(cur.fetchone())
        if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(400, "Lien invalide ou expire. Refaites une demande.")
        cur.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(req.new_password), row["user_id"]),
        )
        cur.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (row["user_id"],))
    return {"message": "Mot de passe reinitialise avec succes."}


# ── Entites generiques (CRUD scope par utilisateur) ─────────────────────────
def _validate_entity_type(entity_type: str) -> str:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            400,
            f"Type d'entite inconnu : {entity_type}. Attendu un de {sorted(ENTITY_TYPES)}",
        )
    return entity_type


def _parse_sort(sort: str) -> tuple:
    """'-created_date' -> ('created_date', 'DESC'). Retombe sur
    ('created_date', 'DESC') si le champ demande n'est pas triable en SQL
    (c'est un champ du JSON, pas une colonne reelle)."""
    if not sort:
        return "created_date", "DESC"
    direction = "DESC" if sort.startswith("-") else "ASC"
    column = sort[1:] if sort.startswith("-") else sort
    if column not in SORTABLE_COLUMNS:
        return "created_date", "DESC"
    return column, direction


def _entity_to_dict(row: sqlite3.Row) -> dict:
    data = json.loads(row["data"])
    data["id"] = row["id"]
    data["created_date"] = row["created_date"]
    data["updated_date"] = row["updated_date"]
    return data


# ── Temps reel (WebSocket) ───────────────────────────────────────────────
# Remplace le polling manuel : chaque creation/modification/suppression
# d'entite est diffusee aux autres connexions ouvertes du meme utilisateur
# (autres onglets/appareils), au format attendu par base44.entities.<Type>
# .subscribe() cote frontend (deja ecrit contre ce contrat, jusqu'ici jamais
# alimente -- subscribe() etait un no-op). Registre en memoire uniquement :
# un seul process backend pour cet outil local mono-utilisateur, pas besoin
# d'un bus de messages externe (Redis, etc.).
ws_connections: dict[int, set] = defaultdict(set)


async def broadcast_entity_event(
    user_id: int, entity_type: str, event_type: str, data: Optional[dict] = None, entity_id: Optional[str] = None
) -> None:
    sockets = ws_connections.get(user_id)
    if not sockets:
        return
    message = json.dumps({"entity_type": entity_type, "type": event_type, "data": data, "id": entity_id})
    dead = set()
    for ws in sockets:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    sockets -= dead


@app.websocket("/ws")
async def entities_ws(websocket: WebSocket, token: str = Query(default="")):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise ValueError("token sans user_id")
    except Exception:
        # 4401 (plage privee 4000-4999) plutot que 1008 generique -- permet
        # au frontend de distinguer "jeton invalide, ne pas reessayer" d'une
        # simple coupure reseau a reconnecter automatiquement.
        await websocket.close(code=4401)
        return

    await websocket.accept()
    ws_connections[user_id].add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive -- contenu ignore
    except WebSocketDisconnect:
        pass
    finally:
        ws_connections[user_id].discard(websocket)


@app.get("/entities/{entity_type}")
def list_entities(
    entity_type: str,
    sort: str = Query(default="-created_date"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user),
):
    _validate_entity_type(entity_type)
    column, direction = _parse_sort(sort)
    query = (
        f"SELECT id, data, created_date, updated_date FROM entities "
        f"WHERE user_id = ? AND entity_type = ? ORDER BY {column} {direction} LIMIT ?"
    )
    with db_cursor() as (conn, cur):
        cur.execute(query, (user["id"], entity_type, limit))
        rows = cur.fetchall()
    return [_entity_to_dict(r) for r in rows]


@app.post("/entities/{entity_type}")
async def create_entity(entity_type: str, payload: dict = Body(default={}), user=Depends(get_current_user)):
    _validate_entity_type(entity_type)
    entity_id = str(uuid.uuid4())
    timestamp = now_iso()
    # id/created_date/updated_date sont geres par le serveur, jamais pris du
    # payload client meme s'il en envoie.
    clean_payload = {k: v for k, v in payload.items() if k not in ("id", "created_date", "updated_date")}

    with db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO entities (id, user_id, entity_type, data, created_date, updated_date) VALUES (?, ?, ?, ?, ?, ?)",
            (entity_id, user["id"], entity_type, json.dumps(clean_payload), timestamp, timestamp),
        )

    result = dict(clean_payload)
    result["id"] = entity_id
    result["created_date"] = timestamp
    result["updated_date"] = timestamp
    await broadcast_entity_event(user["id"], entity_type, "create", data=result)
    return result


@app.put("/entities/{entity_type}/{entity_id}")
async def update_entity(
    entity_type: str,
    entity_id: str,
    payload: dict = Body(default={}),
    user=Depends(get_current_user),
):
    _validate_entity_type(entity_type)
    with db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT * FROM entities WHERE id = ? AND user_id = ? AND entity_type = ?",
            (entity_id, user["id"], entity_type),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Enregistrement introuvable")

        current = json.loads(row["data"])
        updates = {k: v for k, v in payload.items() if k not in ("id", "created_date", "updated_date")}
        current.update(updates)
        timestamp = now_iso()

        cur.execute(
            "UPDATE entities SET data = ?, updated_date = ? WHERE id = ? AND user_id = ? AND entity_type = ?",
            (json.dumps(current), timestamp, entity_id, user["id"], entity_type),
        )

    result = dict(current)
    result["id"] = entity_id
    result["created_date"] = row["created_date"]
    result["updated_date"] = timestamp
    await broadcast_entity_event(user["id"], entity_type, "update", data=result)
    return result


@app.delete("/entities/{entity_type}/{entity_id}")
async def delete_entity(entity_type: str, entity_id: str, user=Depends(get_current_user)):
    _validate_entity_type(entity_type)
    with db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM entities WHERE id = ? AND user_id = ? AND entity_type = ?",
            (entity_id, user["id"], entity_type),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Enregistrement introuvable")
        cur.execute(
            "DELETE FROM entities WHERE id = ? AND user_id = ? AND entity_type = ?",
            (entity_id, user["id"], entity_type),
        )
    await broadcast_entity_event(user["id"], entity_type, "delete", entity_id=entity_id)
    return {"ok": True}


# ── Import en masse de bougies (MarketData) ─────────────────────────────────
# Distinct du CRUD generique ci-dessus : un import d'historique MT5 represente
# des dizaines de milliers de bougies -- les creer une par une (un appel HTTP
# chacune) serait beaucoup trop lent. Cet endpoint accepte un lot complet en
# une requete, et remplace l'historique existant pour ce (symbole, timeframe)
# plutot que de l'accumuler -- un ré-import (ex. donnees plus recentes)
# est donc idempotent au lieu de dupliquer les bougies deja presentes.
class Candle(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = 0


class MarketDataImportRequest(BaseModel):
    symbol: str
    timeframe: str
    candles: list[Candle]


@app.post("/market-data/import")
def import_market_data(req: MarketDataImportRequest, user=Depends(get_current_user)):
    if not req.candles:
        raise HTTPException(400, "Aucune bougie a importer")
    if len(req.candles) > MAX_IMPORT_CANDLES:
        raise HTTPException(
            400,
            f"Trop de bougies en un seul import ({len(req.candles)} > {MAX_IMPORT_CANDLES}). Decoupez le fichier.",
        )

    now = now_iso()
    rows = []
    for c in req.candles:
        data = {
            "symbol": req.symbol,
            "timeframe": req.timeframe,
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume or 0,
        }
        rows.append((str(uuid.uuid4()), user["id"], "MarketData", json.dumps(data), now, now))

    with db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM entities WHERE user_id = ? AND entity_type = 'MarketData' "
            "AND json_extract(data, '$.symbol') = ? AND json_extract(data, '$.timeframe') = ?",
            (user["id"], req.symbol, req.timeframe),
        )
        cur.executemany(
            "INSERT INTO entities (id, user_id, entity_type, data, created_date, updated_date) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    return {"ok": True, "imported": len(rows), "symbol": req.symbol, "timeframe": req.timeframe}


@app.get("/market-data")
def list_market_data(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=MAX_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user),
):
    """Lecture des bougies triees par leur vrai timestamp (colonne JSON), pas
    par created_date -- toutes les bougies d'un meme import partagent la meme
    created_date (insertion en un seul lot), donc trier sur created_date ne
    garantirait pas l'ordre chronologique. Utilise par le moteur de backtest."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT data FROM entities WHERE user_id = ? AND entity_type = 'MarketData' "
            "AND json_extract(data, '$.symbol') = ? AND json_extract(data, '$.timeframe') = ? "
            "ORDER BY json_extract(data, '$.timestamp') ASC LIMIT ?",
            (user["id"], symbol, timeframe, limit),
        )
        rows = cur.fetchall()
    return [json.loads(r["data"]) for r in rows]


@app.get("/market-data/summary")
def market_data_summary(user=Depends(get_current_user)):
    """Nombre de bougies + plage de dates deja importees, par (symbole, timeframe) --
    utilise par l'ecran Donnees de marche pour afficher ce qui est deja disponible."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT json_extract(data, '$.symbol') AS symbol, "
            "json_extract(data, '$.timeframe') AS timeframe, "
            "COUNT(*) AS count, "
            "MIN(json_extract(data, '$.timestamp')) AS start, "
            "MAX(json_extract(data, '$.timestamp')) AS end "
            "FROM entities WHERE user_id = ? AND entity_type = 'MarketData' "
            "GROUP BY symbol, timeframe",
            (user["id"],),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Pont prix live MT5 (Module 4 / Paper Trading, mode Live) ───────────────
def _initialize_mt5() -> bool:
    """Tente mt5.initialize() sans argument (terminal deja detecte
    automatiquement), puis quelques chemins d'installation courants.
    Retourne False sans lever si tout echoue -- l'appelant transforme ca en
    HTTPException 503 avec un message clair."""
    if mt5.initialize():
        return True
    for candidate in MT5_PATH_CANDIDATES:
        if os.path.exists(candidate) and mt5.initialize(path=candidate):
            return True
    return False


@app.get("/market-data/live")
def live_market_data(symbol: str = Query(...), user=Depends(get_current_user)):
    """Dernier prix bid/ask reel, lu directement depuis le terminal MT5
    installe sur cette machine (lecture seule -- aucun ordre n'est jamais
    envoye). Utilise par le mode Live du Paper Trading pour evaluer les
    conditions de strategie sur des prix reels en direct."""
    if mt5 is None:
        raise HTTPException(
            503,
            "Le module MetaTrader5 n'est pas disponible sur ce serveur "
            f"({MT5_IMPORT_ERROR or 'package non installe'}). Le mode live "
            "necessite le paquet Python MetaTrader5, disponible uniquement "
            "sous Windows.",
        )

    try:
        if not _initialize_mt5():
            raise HTTPException(
                503,
                "Terminal MetaTrader 5 introuvable ou ferme. Ouvrez MT5 sur "
                "cette machine pour utiliser le mode live.",
            )

        # Rend le symbole visible dans le Market Watch si necessaire --
        # sinon symbol_info_tick peut renvoyer None meme pour un symbole
        # valide chez le broker.
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise HTTPException(
                404,
                f"Symbole introuvable dans MT5 : {symbol}. Verifiez qu'il "
                "est disponible chez votre broker et correctement orthographie.",
            )

        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "timestamp": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        # Ne jamais laisser une erreur MT5 inattendue (deconnexion, IPC,
        # etc.) faire planter la requete sans message exploitable.
        raise HTTPException(503, f"Erreur de communication avec MetaTrader 5 : {exc}")
    finally:
        # Liberation systematique de la connexion IPC -- ce endpoint est
        # appele en polling (toutes les 15-30s) depuis le frontend, pas en
        # connexion permanente comme un service arriere-plan.
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass


# ── AI proxy (AI Strategy Designer, Module 6) ───────────────────────────────
# Anthropic et OpenAI bloquent les appels directs depuis un navigateur (CORS),
# donc le frontend ne peut pas appeler leurs API en fetch() direct. Ce proxy
# relaie la requete avec la cle API fournie par l'utilisateur a chaque appel
# (modele "bring your own key") -- la cle ne transite jamais que dans cette
# requete/reponse et n'est JAMAIS journalisee ni ecrite en base de donnees.
AI_REQUEST_TIMEOUT = 30


class AIGenerateParams(BaseModel):
    temperature: Optional[float] = None
    maxTokens: Optional[int] = None
    topP: Optional[float] = None


class AIGenerateRequest(BaseModel):
    provider: str
    api_key: str
    model: str
    system_prompt: Optional[str] = ""
    prompt: str
    params: Optional[AIGenerateParams] = None


def _ai_provider_error_message(provider: str, status_code: Optional[int]) -> str:
    if status_code == 401 or status_code == 403:
        return f"Cle API invalide ou refusee par {provider}."
    if status_code == 429:
        return f"Limite de requetes atteinte chez {provider}. Reessayez dans quelques instants."
    if status_code is not None and status_code >= 500:
        return f"Le fournisseur IA ({provider}) rencontre un probleme cote serveur. Reessayez plus tard."
    return f"Le fournisseur IA ({provider}) a refuse la requete."


@app.post("/ai/generate")
def ai_generate(req: AIGenerateRequest, user=Depends(get_current_user)):
    provider = (req.provider or "").lower()
    if provider not in ("anthropic", "openai"):
        raise HTTPException(400, f"Fournisseur IA non supporte: {req.provider}")
    if not req.api_key:
        raise HTTPException(400, "Cle API manquante.")

    params = req.params or AIGenerateParams()
    max_tokens = params.maxTokens or 2048
    temperature = params.temperature if params.temperature is not None else 0.7
    top_p = params.topP if params.topP is not None else 1

    try:
        if provider == "anthropic":
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": req.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": req.model,
                    "max_tokens": max_tokens,
                    "system": req.system_prompt or "",
                    "messages": [{"role": "user", "content": req.prompt}],
                    "temperature": temperature,
                    "top_p": top_p,
                },
                timeout=AI_REQUEST_TIMEOUT,
            )
            if not resp.ok:
                raise HTTPException(
                    502 if resp.status_code >= 500 else 400,
                    _ai_provider_error_message("Anthropic", resp.status_code),
                )
            data = resp.json()
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return {"content": text}

        # provider == "openai"
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {req.api_key}"},
            json={
                "model": req.model,
                "messages": [
                    {"role": "system", "content": req.system_prompt or ""},
                    {"role": "user", "content": req.prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
            },
            timeout=AI_REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise HTTPException(
                502 if resp.status_code >= 500 else 400,
                _ai_provider_error_message("OpenAI", resp.status_code),
            )
        data = resp.json()
        choices = data.get("choices") or []
        text = choices[0]["message"]["content"] if choices else ""
        return {"content": text}

    except HTTPException:
        raise
    except requests.Timeout:
        raise HTTPException(502, "Le fournisseur IA n'a pas repondu (delai depasse).")
    except requests.RequestException:
        raise HTTPException(502, "Le fournisseur IA n'a pas repondu.")
    except (KeyError, ValueError, TypeError):
        raise HTTPException(502, "Reponse inattendue du fournisseur IA.")


# ── Export Signaux vers AlphaTrade (Module 5) ───────────────────────────────
# Strategy Lab et AlphaTrade sont deux backends/comptes entierement separes --
# ce proxy est le seul pont entre les deux. /alphatrade/login relaie une
# authentification a la volee (le mot de passe ne transite que dans cet appel,
# jamais stocke ni journalise ici) pour obtenir le jeton AlphaTrade ; le
# frontend le garde en localStorage et le renvoie a chaque envoi de signal.
class AlphaTradeLoginRequest(BaseModel):
    email: str
    password: str


class AlphaTradeSendSignalRequest(BaseModel):
    alphatrade_token: str
    symbol: str
    action: str  # "BUY" | "SELL" -- WAIT n'a rien a envoyer
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: Optional[float] = None
    strategy_name: Optional[str] = ""
    notes: Optional[str] = ""


def _alphatrade_error_message(status_code: Optional[int]) -> str:
    if status_code == 401:
        return "Connexion AlphaTrade expiree ou invalide. Reconnectez-vous depuis Parametres."
    if status_code == 400:
        return "AlphaTrade a refuse le signal (parametres invalides)."
    if status_code is not None and status_code >= 500:
        return "AlphaTrade rencontre un probleme cote serveur. Reessayez plus tard."
    return "AlphaTrade n'a pas accepte la requete."


@app.post("/alphatrade/login")
def alphatrade_login(req: AlphaTradeLoginRequest, user=Depends(get_current_user)):
    try:
        resp = requests.post(
            f"{ALPHATRADE_API_URL}/auth/login",
            json={"email": req.email, "password": req.password},
            timeout=ALPHATRADE_REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(502, "Impossible de joindre AlphaTrade. Reessayez plus tard.")

    if not resp.ok:
        raise HTTPException(
            401 if resp.status_code == 401 else 502,
            "Email ou mot de passe AlphaTrade incorrect." if resp.status_code == 401
            else _alphatrade_error_message(resp.status_code),
        )
    data = resp.json()
    return {"token": data.get("token"), "user": data.get("user")}


@app.post("/alphatrade/send-signal")
def alphatrade_send_signal(req: AlphaTradeSendSignalRequest, user=Depends(get_current_user)):
    if req.action not in ("BUY", "SELL"):
        raise HTTPException(400, "Seuls les signaux BUY ou SELL peuvent etre exportes.")
    if req.symbol not in ALPHATRADE_SIGNAL_SYMBOLS:
        raise HTTPException(400, f"Symbole non pris en charge par AlphaTrade : {req.symbol}")
    if not req.alphatrade_token:
        raise HTTPException(400, "Non connecte a AlphaTrade -- reconnectez-vous depuis Parametres.")

    payload = {
        "symbol": req.symbol,
        "action": req.action,
        "entry_price": req.entry_price,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
        "confidence": req.confidence,
        "source": "strategy_lab",
        "strategy_name": req.strategy_name or "",
        "notes": req.notes or "",
    }
    try:
        resp = requests.post(
            f"{ALPHATRADE_API_URL}/device/command",
            headers={"Authorization": f"Bearer {req.alphatrade_token}"},
            json={"cmd": "EXTERNAL_SIGNAL", "payload": payload},
            timeout=ALPHATRADE_REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(502, "Impossible de joindre AlphaTrade. Reessayez plus tard.")

    if not resp.ok:
        raise HTTPException(
            401 if resp.status_code == 401 else 400 if resp.status_code == 400 else 502,
            _alphatrade_error_message(resp.status_code),
        )
    return resp.json()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
