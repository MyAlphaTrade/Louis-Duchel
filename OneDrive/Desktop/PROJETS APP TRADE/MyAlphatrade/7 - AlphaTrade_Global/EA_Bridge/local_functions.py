"""
AlphaTrade Global — local_functions
====================================

Deterministic, LLM-free replacements for the Base44 Deno functions
(`tradingConnector`, `tradeManager`) plus explicit "not yet ported"
stubs for the functions that used to call an LLM (`marketBrain`,
`engineTest`, `strategyOrchestrator`, `strategyTester`, `aiProvider`,
`slackNotifier`). The stubs return a clearly-labelled WAIT decision
instead of crashing the UI while those engines are rewritten as pure
rule-based Python logic.

Ported faithfully from:
  - base44/functions/tradingConnector/entry.ts
  - base44/shared/alphatradeConnector.ts
  - base44/functions/tradeManager/entry.ts
"""

import hashlib
import secrets
from datetime import datetime, timezone

from local_store import create_entity, list_entities, update_entity

DEFAULT_LOCAL_EMAIL = "louismarieduchel@gmail.com"
DEFAULT_LOCAL_PASSWORD = "Projetalpha1234"

CONTRACT_SIZES = {
    "XAUUSD": 100,
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "USDJPY": 100000,
    "BTCUSD": 1,
    "ETHUSD": 1,
    "SP500": 50,
    "NAS100": 20,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mask_secret(value):
    if not value:
        return ""
    value = str(value)
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _mask_login(value):
    if not value:
        return ""
    value = str(value)
    if len(value) <= 3:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 2)


def _get_account():
    accounts = list_entities("TradingAccount", sort="-created_date", limit=1)
    return accounts[0] if accounts else None


# ── Local login (single-user bypass, no cloud auth) ────────────────

def _hash_password(password, salt):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _get_or_seed_local_auth():
    existing = list_entities("LocalAuth", limit=1)
    if existing:
        return existing[0]
    salt = secrets.token_hex(16)
    return create_entity("LocalAuth", {
        "email": DEFAULT_LOCAL_EMAIL,
        "salt": salt,
        "password_hash": _hash_password(DEFAULT_LOCAL_PASSWORD, salt),
    })


def auth_login(body, local_user):
    auth = _get_or_seed_local_auth()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    if email != (auth.get("email") or "").strip().lower():
        return {"ok": False, "error": "Email ou mot de passe invalide."}, 401
    if _hash_password(password, auth["salt"]) != auth["password_hash"]:
        return {"ok": False, "error": "Email ou mot de passe invalide."}, 401
    return {"ok": True, "user": {**local_user, "email": auth["email"]}}, 200


def auth_reset_password(body):
    auth = _get_or_seed_local_auth()
    new_password = str(body.get("new_password") or "")
    if len(new_password) < 6:
        return {"ok": False, "error": "Le mot de passe doit contenir au moins 6 caractères."}, 400
    patch = {"password_hash": _hash_password(new_password, auth["salt"])}
    new_email = body.get("email")
    if new_email:
        patch["email"] = str(new_email).strip()
    update_entity("LocalAuth", auth["id"], patch)
    return {"ok": True}, 200


# ── tradingConnector ──────────────────────────────────────────────

def trading_connector_read():
    acct = _get_account()
    if not acct:
        return {"configured": False, "platform": "simulation", "connection_status": "not_configured"}

    result = {
        "configured": True,
        "platform": acct.get("platform") or "simulation",
        "broker": acct.get("broker") or "",
        "account_type": acct.get("account_type") or "demo",
        "login": acct.get("login") or "",
        "login_masked": _mask_login(acct.get("login") or ""),
        "server": acct.get("server") or "",
        "currency": acct.get("currency") or "USD",
        "leverage": acct.get("leverage") or "1:100",
        "api_url": acct.get("api_url") or "",
        "api_key_masked": _mask_secret(acct.get("api_key") or ""),
        "account_number": acct.get("account_number") or "",
        "connection_status": acct.get("connection_status") or "not_configured",
        "last_tested_at": acct.get("last_tested_at"),
        "last_sync_at": acct.get("last_sync_at"),
        "last_error": acct.get("last_error"),
        "latency_ms": acct.get("latency_ms"),
        "balance": acct.get("balance") or 0,
        "equity": acct.get("equity") or 0,
        "floating_profit": acct.get("floating_profit") or 0,
        "daily_profit": acct.get("daily_profit") or 0,
        "margin": acct.get("margin") or 0,
        "margin_level": acct.get("margin_level") or 0,
        "open_positions_count": acct.get("open_positions_count") or 0,
        "pending_orders_count": acct.get("pending_orders_count") or 0,
        "drawdown_percent": acct.get("drawdown_percent") or 0,
        "win_rate": acct.get("win_rate") or 0,
    }
    if acct.get("platform") in ("mt5", "mt4"):
        result["api_key"] = acct.get("api_key") or ""
    return result


def trading_connector_save(body):
    payload = {
        "platform": body.get("platform") or "simulation",
        "broker": str(body.get("broker") or ""),
        "account_type": body.get("account_type") or "demo",
        "login": str(body.get("login") or ""),
        "server": str(body.get("server") or ""),
        "currency": str(body.get("currency") or "USD"),
        "leverage": str(body.get("leverage") or "1:100"),
        "api_url": str(body.get("api_url") or "").strip(),
        "connection_status": "untested",
        "last_error": None,
    }
    if body.get("password"):
        payload["password"] = str(body["password"])
    if body.get("api_key"):
        payload["api_key"] = str(body["api_key"])

    existing = _get_account()
    if existing:
        update_entity("TradingAccount", existing["id"], payload)
    else:
        payload["user_id"] = "local"
        create_entity("TradingAccount", payload)
    return {"ok": True}


def trading_connector_test(get_account_snapshot):
    """get_account_snapshot: callable returning the bridge's own live MT5
    snapshot dict (see alphatg_bridge.get_account_snapshot), or None."""
    acct = _get_account()
    if not acct:
        return {"ok": False, "error": "Aucune configuration trouvée. Sauvegardez d'abord vos identifiants."}

    platform = acct.get("platform") or "simulation"

    if platform in ("simulation", "paper_trading"):
        update_entity("TradingAccount", acct["id"], {
            "connection_status": "connected",
            "last_tested_at": _now_iso(),
            "last_error": None,
            "latency_ms": None,
            "account_number": acct.get("account_number") or acct.get("login") or "SIMULATION",
        })
        return {"ok": True, "latency_ms": None}

    if platform in ("mt5", "mt4"):
        snap = get_account_snapshot()
        if snap is None:
            update_entity("TradingAccount", acct["id"], {
                "connection_status": "failed",
                "last_tested_at": _now_iso(),
                "last_error": "MT5 non connecté au terminal — ouvrez MetaTrader 5 et connectez-vous.",
            })
            return {"ok": False, "error": "MT5 non connecté au terminal — ouvrez MetaTrader 5 et connectez-vous."}

        update_entity("TradingAccount", acct["id"], {
            "connection_status": "connected",
            "last_tested_at": _now_iso(),
            "last_sync_at": _now_iso(),
            "last_error": None,
            "latency_ms": 0,
            "account_type": snap.get("account_type") or acct.get("account_type") or "demo",
            "account_number": snap.get("account_number") or acct.get("account_number") or "",
            "currency": snap.get("currency") or acct.get("currency") or "USD",
            "leverage": snap.get("leverage") or acct.get("leverage") or "1:100",
            "balance": snap.get("balance") or 0,
            "equity": snap.get("equity") or 0,
            "floating_profit": snap.get("floating_profit") or 0,
            "open_positions_count": snap.get("open_positions_count") or 0,
        })
        return {"ok": True, "latency_ms": 0}

    return {"ok": False, "error": f"Plateforme '{platform}' non prise en charge par le service local (MT5 uniquement)."}


def calculate_lot(symbol, entry_price=None, stop_loss=None, capital=None, risk_percent=None):
    capital = capital or 1000
    risk_percent = risk_percent if risk_percent is not None else 1
    risk_amount = capital * (risk_percent / 100)
    contract_size = CONTRACT_SIZES.get((symbol or "").upper(), 100000)
    sl_distance = abs((entry_price or 0) - (stop_loss or 0))
    if sl_distance <= 0:
        return 0.01
    lot = risk_amount / (sl_distance * contract_size)
    return max(0.01, round(lot * 100) / 100)


def build_order(body):
    direction = "SELL" if body.get("direction") == "SELL" else "BUY"
    symbol = (body.get("symbol") or "").upper()
    return {
        "symbol": symbol,
        "direction": direction,
        "lot": calculate_lot(
            symbol,
            entry_price=body.get("entry_price"),
            stop_loss=body.get("stop_loss"),
            capital=body.get("capital"),
            risk_percent=body.get("risk_percent"),
        ),
        "entry_price": body.get("entry_price"),
        "stop_loss": body.get("stop_loss") or 0,
        "take_profit_1": body.get("take_profit_1") or 0,
        "take_profit_2": body.get("take_profit_2"),
        "break_even": body.get("break_even"),
        "confidence": body.get("confidence") or 0,
        "rationale": body.get("rationale") or [],
    }


# ── tradeManager ──────────────────────────────────────────────────

def trade_manager_close_trade(body, get_entity_fn):
    trade_id = str(body.get("trade_id") or "")
    try:
        exit_price = float(body.get("exit_price"))
    except (TypeError, ValueError):
        return {"error": "trade_id et exit_price sont requis"}, 400
    if not trade_id:
        return {"error": "trade_id et exit_price sont requis"}, 400

    trade = get_entity_fn("Trade", trade_id)
    if not trade:
        return {"error": "Trade introuvable"}, 404
    if trade.get("status") == "closed":
        return {"error": "Trade déjà clôturé"}, 400

    entry_price = trade.get("entry_price") or 0
    lot = trade.get("lot") or 0.01
    direction = trade.get("direction")
    contract_size = CONTRACT_SIZES.get((trade.get("symbol") or "").upper(), 100000)

    try:
        real_pnl = float(body.get("pnl"))
    except (TypeError, ValueError):
        real_pnl = None

    if real_pnl is not None:
        pnl = real_pnl
    elif direction == "BUY":
        pnl = (exit_price - entry_price) * lot * contract_size
    else:
        pnl = (entry_price - exit_price) * lot * contract_size

    pnl_percent = (pnl / (entry_price * lot * contract_size)) * 100 if entry_price > 0 else 0

    closed_at_raw = body.get("closed_at")
    closed_at = closed_at_raw if closed_at_raw else _now_iso()
    today = closed_at.split("T")[0]

    update_entity("Trade", trade_id, {
        "status": "closed",
        "exit_price": exit_price,
        "pnl": round(pnl * 100) / 100,
        "pnl_percent": round(pnl_percent * 100) / 100,
        "closed_at": closed_at,
    })

    existing_perf = list_entities("DailyPerformance", query={"date": today}, sort="-created_date", limit=1)
    perf = existing_perf[0] if existing_perf else None

    if perf:
        new_pnl = (perf.get("pnl") or 0) + pnl
        new_wins = (perf.get("wins") or 0) + 1 if pnl > 0 else (perf.get("wins") or 0)
        new_losses = (perf.get("losses") or 0) + 1 if pnl < 0 else (perf.get("losses") or 0)
        update_entity("DailyPerformance", perf["id"], {
            "pnl": round(new_pnl * 100) / 100,
            "trades_count": (perf.get("trades_count") or 0) + 1,
            "wins": new_wins,
            "losses": new_losses,
            "trade_ids": (perf.get("trade_ids") or []) + [trade_id],
        })
    else:
        create_entity("DailyPerformance", {
            "date": today,
            "pnl": round(pnl * 100) / 100,
            "trades_count": 1,
            "wins": 1 if pnl > 0 else 0,
            "losses": 1 if pnl < 0 else 0,
            "trade_ids": [trade_id],
        })

    outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven"
    conditions = [
        f"Symbol: {trade.get('symbol')}",
        f"Direction: {trade.get('direction')}",
        f"Lot: {lot}",
        f"Entry: {entry_price}",
        f"Exit: {exit_price}",
        f"Stop Loss: {trade.get('stop_loss', 'N/A')}",
        f"Take Profit: {trade.get('take_profit', 'N/A')}",
    ]
    if trade.get("management_events"):
        conditions.append("Events: " + ", ".join(trade["management_events"]))

    create_entity("LearningData", {
        "trade_id": trade_id,
        "outcome": outcome,
        "conditions": conditions,
        "errors": [],
        "lessons": [],
        "accuracy_delta": 0,
        "reviewed": False,
    })

    create_entity("AppLog", {
        "level": "info",
        "category": "trade",
        "message": f"Trade clôturé: {trade.get('symbol')} {trade.get('direction')} → {outcome} ({pnl:.2f})",
        "source": "tradeManager",
        "payload": {"trade_id": trade_id, "pnl": pnl, "outcome": outcome},
    })

    return {
        "ok": True,
        "trade_id": trade_id,
        "pnl": round(pnl * 100) / 100,
        "pnl_percent": round(pnl_percent * 100) / 100,
        "outcome": outcome,
    }, 200


def trade_manager_sync_daily(body):
    date = body.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trades = list_entities("Trade", query={"status": "closed"}, sort="-closed_at", limit=500)
    day_trades = [t for t in trades if t.get("closed_at") and t["closed_at"].split("T")[0] == date]

    if not day_trades:
        return {"ok": True, "date": date, "message": "Aucun trade clôturé ce jour."}, 200

    pnl = sum(t.get("pnl") or 0 for t in day_trades)
    wins = sum(1 for t in day_trades if (t.get("pnl") or 0) > 0)
    losses = sum(1 for t in day_trades if (t.get("pnl") or 0) < 0)
    trade_ids = [t["id"] for t in day_trades]

    existing = list_entities("DailyPerformance", query={"date": date}, sort="-created_date", limit=1)
    payload = {
        "pnl": round(pnl * 100) / 100,
        "trades_count": len(day_trades),
        "wins": wins,
        "losses": losses,
        "trade_ids": trade_ids,
    }
    if existing:
        update_entity("DailyPerformance", existing[0]["id"], payload)
    else:
        create_entity("DailyPerformance", {"date": date, **payload})

    return {"ok": True, "date": date, **payload}, 200


# ── Stubs for functions not yet ported off the LLM (next phase) ──

_STUB_LABEL = "Moteur en cours de portage vers une logique déterministe Python (LLM retiré) — pas encore actif."

_STUB_DECISIONS = {"marketBrain", "engineTest", "strategyOrchestrator", "strategyTester"}
_STUB_NOOPS = {"aiProvider", "slackNotifier"}


def deterministic_stub_response(function_name, body):
    if function_name in _STUB_DECISIONS:
        return {
            "decision": {
                "decision": "WAIT",
                "confidence": 0,
                "explanation": _STUB_LABEL,
            },
            "ok": True,
            "note": _STUB_LABEL,
        }
    if function_name in _STUB_NOOPS:
        return {"ok": True, "note": _STUB_LABEL}
    return {"error": f"Fonction inconnue: {function_name}"}, 404
