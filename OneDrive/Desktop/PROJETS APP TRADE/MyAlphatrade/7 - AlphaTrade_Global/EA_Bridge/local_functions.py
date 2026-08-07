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
import re
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


# Timestamps are stored in UTC (unambiguous, sorts correctly) but "which day
# did this happen on" is a question about the TRADER's calendar, not UTC's —
# this app runs on the trader's own machine, so "today" and "which day does
# this trade belong to" must use the local system timezone. Bucketing by the
# raw UTC date instead shifts the boundary by the local UTC offset: a trade
# closed late in the local evening (already tomorrow in UTC, for timezones
# west of Greenwich) would silently count against the wrong day's goal/loss
# limit, and the Daily Goal Engine would reset at UTC midnight instead of the
# trader's actual midnight.
def _local_today():
    return datetime.now().strftime("%Y-%m-%d")


def _to_local_date(iso_utc_str):
    if not iso_utc_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_utc_str.replace("Z", "+00:00"))
    except ValueError:
        return iso_utc_str.split("T")[0]
    return dt.astimezone().strftime("%Y-%m-%d")


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


def _coalesce(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _normalize_symbol(raw):
    s = re.sub(r"\s+", "", (raw or "").upper())
    s = re.sub(r"\.[A-Z0-9]+$", "", s)
    s = re.sub(r"INDEX$", "", s)
    return s


def _infer_asset_category(raw):
    s = re.sub(r"\s+", "", (raw or "").upper())
    if re.match(r"^(BOOM|CRASH|STEP)", s) or re.search(r"VIX\d", s):
        return "synthetic"
    if "INDEX" in s:
        return "indices"
    if re.match(r"^(BTC|ETH|SOL|XRP|ADA|DOGE|BNB|LTC|AVAX|LINK|DOT|MATIC|ATOM|TRX|NEAR|APT|FIL|ICP|ARB|OP|INJ|SUI|TIA|RNDR|FTM)", s):
        return "crypto"
    if re.match(r"^X(AU|AG|PT|PD)", s):
        return "metals"
    if re.search(r"(OIL|GAS|COPPER|WHEAT|CORN|SOY|COFFEE|SUGAR|COCOA)", s):
        return "commodities"
    return "forex"


def seed_asset_registry_if_empty(fetch_symbols_fn, platform):
    """The first successful MT5 connection auto-populates the searchable
    asset library from the account's real available symbols — otherwise a
    user would have to "favorite" every single one by hand in Asset
    Discovery just to make search return anything at all."""
    if list_entities("AssetRegistry", limit=1):
        return
    symbols = fetch_symbols_fn() if fetch_symbols_fn else None
    if not symbols:
        return
    for i, raw in enumerate(symbols):
        create_entity("AssetRegistry", {
            "symbol": re.sub(r"\s+", "", raw),
            "name": raw,
            "category": _infer_asset_category(raw),
            "platforms": [platform],
            "is_available": True,
            "sort_order": i,
        })


def _detect_account_type(data, acct):
    """Auto-detect whether an MT5/MT4 account is demo or real from the API
    response. Checks multiple common fields: account_type, demo flag,
    server name pattern."""
    if data.get("account_type"):
        at = str(data["account_type"]).lower()
        if "demo" in at:
            return "demo"
        if "real" in at or "live" in at:
            return "real"
    if isinstance(data.get("demo"), bool):
        return "demo" if data["demo"] else "real"
    if isinstance(data.get("is_demo"), bool):
        return "demo" if data["is_demo"] else "real"
    server = str(data.get("server") or (acct or {}).get("server") or "").lower()
    if "demo" in server:
        return "demo"
    if "live" in server or "real" in server:
        return "real"
    return (acct or {}).get("account_type") or "demo"


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


def trading_connector_test(get_account_snapshot, fetch_symbols_fn=None):
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

        seed_asset_registry_if_empty(fetch_symbols_fn, platform)

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


def trading_connector_save_bridge_result(body, fetch_symbols_fn=None):
    """Persists a test/sync result the frontend already obtained by calling
    the bridge directly (browser → bridge, for mt5/mt4 — see baseConnector.js's
    BRIDGE_ACTIONS routing, which bypasses this backend for the actual HTTP
    call and only comes back here to save the outcome)."""
    acct = _get_account()
    if not acct:
        return {"ok": False, "error": "No config"}, 200

    result = body.get("result") or {}
    platform = acct.get("platform") or "simulation"

    if platform in ("mt5", "mt4"):
        data = result.get("account") or {}
        mt5_connected = result.get("ok") is True
        detected_type = _detect_account_type(data, acct)
        if mt5_connected:
            seed_asset_registry_if_empty(fetch_symbols_fn, platform)
        update_entity("TradingAccount", acct["id"], {
            "connection_status": "connected" if mt5_connected else "failed",
            "last_tested_at": _now_iso(),
            "last_error": None if mt5_connected else (result.get("error") or "MT5 non connecté"),
            "latency_ms": result.get("latency_ms"),
            "account_type": detected_type if mt5_connected else acct.get("account_type"),
            "account_number": _coalesce(data.get("account_number"), acct.get("account_number"), acct.get("login"), ""),
            "currency": _coalesce(data.get("currency"), acct.get("currency"), "USD"),
            "leverage": _coalesce(data.get("leverage"), acct.get("leverage"), "1:100"),
            "balance": _coalesce(data.get("balance"), acct.get("balance"), 0),
            "equity": _coalesce(data.get("equity"), data.get("balance"), 0),
            "floating_profit": data.get("floating_profit") or 0,
            "open_positions_count": data.get("open_positions") or 0,
            "last_sync_at": _now_iso() if mt5_connected else acct.get("last_sync_at"),
        })
        return {"ok": True}, 200

    return {"ok": False, "error": "Not a bridge platform"}, 200


class RealCapitalUnavailable(Exception):
    """Raised when a lot size is needed but no real capital figure is
    available to size it against. Every caller must turn this into an
    explicit refusal (HTTP error / WAIT), never a silent fallback.

    Real Capital Risk Engine, 2026-08-06 (Phase 2 of the professional audit's
    transformation plan): calculate_lot() used to default to a fictitious
    1000$ whenever `capital` was falsy — which was ALWAYS the case in real
    use, because no Settings field in the whole frontend ever wrote
    Parameter.capital. On a real account this meant every position was
    sized against a number with no relationship to the actual balance:
    10x too small on a 10 000$ account, or dangerously oversized on a
    small one. There is now no fallback — see build_order() below, which
    is passed the account's real equity from MT5 by the bridge itself,
    never a value supplied by the caller."""


def calculate_lot(symbol, entry_price=None, stop_loss=None, capital=None, risk_percent=None):
    if not capital or capital <= 0:
        raise RealCapitalUnavailable(
            "Capital réel indisponible (equity MT5 introuvable) — impossible de calculer une taille de position en toute sécurité."
        )
    risk_percent = risk_percent if risk_percent is not None else 1
    risk_amount = capital * (risk_percent / 100)
    contract_size = CONTRACT_SIZES.get((symbol or "").upper(), 100000)
    sl_distance = abs((entry_price or 0) - (stop_loss or 0))
    if sl_distance <= 0:
        return 0.01
    lot = risk_amount / (sl_distance * contract_size)
    return max(0.01, round(lot * 100) / 100)


def build_order(body, account_equity=None):
    """account_equity: the account's real, current equity as read from MT5
    by the bridge (see get_account_snapshot() in alphatg_bridge.py), passed
    in explicitly by the caller — NEVER taken from `body`. A capital figure
    supplied by the frontend can't be trusted for a real order: it might be
    stale, absent, or (before this fix) silently wrong for months. Raises
    RealCapitalUnavailable if account_equity isn't a real positive number;
    the caller (alphatg_bridge.py) must turn that into an explicit error
    response, never send an order sized on a guess.

    Adaptive risk (Portfolio Risk Manager, 2026-08-06): risk_percent is
    scaled down automatically after a real losing streak (see
    portfolio_risk.consecutive_loss_multiplier) — the system trades smaller
    while it's actually losing, never larger. This only ever shrinks the
    trader's own configured risk, it never exceeds it."""
    import portfolio_risk

    direction = "SELL" if body.get("direction") == "SELL" else "BUY"
    symbol = (body.get("symbol") or "").upper()
    risk_percent = body.get("risk_percent")
    if risk_percent is not None:
        risk_percent = risk_percent * portfolio_risk.consecutive_loss_multiplier()
    return {
        "symbol": symbol,
        "direction": direction,
        "lot": calculate_lot(
            symbol,
            entry_price=body.get("entry_price"),
            stop_loss=body.get("stop_loss"),
            capital=account_equity,
            risk_percent=risk_percent,
        ),
        "entry_price": body.get("entry_price"),
        "stop_loss": body.get("stop_loss") or 0,
        "take_profit_1": body.get("take_profit_1") or 0,
        "take_profit_2": body.get("take_profit_2"),
        "break_even": body.get("break_even"),
        "confidence": body.get("confidence") or 0,
        "rationale": body.get("rationale") or [],
    }


# ── Position Management ─────────────────────────────────────────────
# Real break-even + trailing-stop management against live MT5 positions.
# Trade.stop_loss always holds the ORIGINAL stop set at entry (the risk
# unit, "1R") — Trade.trailing_stop holds wherever the SL has actually
# been moved to since. Comparing the two is how we know whether a
# position has already been protected without re-reading MT5's own SL
# (which we've just changed ourselves and don't want to re-derive R from).
DEFAULT_BREAK_EVEN_TRIGGER = 1.0   # R-multiple of profit before locking entry
DEFAULT_PROFIT_PROTECTION_TRIGGER = 1.5  # R-multiple before trailing starts
TRAIL_DISTANCE_R = 0.5  # how far behind price the trailing stop sits, in R

# Partial take-profit (Professional Position Manager, 2026-08-06): TP1 banks
# a third of the position early, TP2 banks half of what's left, and the
# remainder ("TP3") is never closed on a fixed target — it rides the
# trailing stop above instead, so a genuinely large move isn't capped early.
# Fractions are of whatever volume is STILL open at the moment each tier
# fires, not of the original size — so TP1 (33%) then TP2 (50% of the
# remaining ~67%) leaves close to a third of the original position for TP3,
# regardless of how the broker's own lot-step rounding worked out on TP1.
TP1_TRIGGER_R = 1.0
TP1_CLOSE_FRACTION = 0.33
TP2_TRIGGER_R = 2.0
TP2_CLOSE_FRACTION = 0.5

# Emergency close: the one case break-even/trailing/TP can never reach,
# because all of them need an original stop loss to measure R against.
# A position with NO recorded stop (opened manually with none, or a Trade
# record that never got one) has genuinely unbounded downside otherwise —
# this is a hard %-of-equity floor, not an R-multiple, and it is
# deliberately the last line of defense, not a substitute for a real SL.
EMERGENCY_CLOSE_EQUITY_PERCENT = 2.0


def _r_multiple(direction, entry_price, current_price, original_risk):
    if original_risk <= 0:
        return 0
    moved = (current_price - entry_price) if direction == "BUY" else (entry_price - current_price)
    return moved / original_risk


def manage_open_positions(get_positions_fn, modify_fn, params=None, close_fn=None, equity=None):
    """Runs on its own fast loop now (see alphatg_bridge.py's
    _position_manager_loop), independently of the analysis/decision cycle —
    Professional Position Manager, 2026-08-06. For each open MT5 position
    with a matching Trade record: partial take-profit at TP1/TP2, then
    moves the stop to break-even once profit clears break_even_trigger R,
    then trails it once profit clears profit_protection_trigger R. Never
    touches a position it can't trace back to a Trade.

    close_fn(ticket, volume=None) -> {"ok": bool, ...}: real partial (or
    full, if volume is omitted) MT5 close — powers TP1/TP2 and the
    emergency close. Optional for backward compatibility: omitting it skips
    partial take-profit and emergency close, break-even/trailing still run.
    equity: real account equity, used only by the emergency-close check.
    """
    params = params or {}
    be_trigger = params.get("break_even_trigger") or DEFAULT_BREAK_EVEN_TRIGGER
    trail_trigger = params.get("profit_protection_trigger") or DEFAULT_PROFIT_PROTECTION_TRIGGER

    positions = get_positions_fn()
    if positions is None:
        return {"managed": 0, "protected": 0, "eligible": 0, "actions": [], "connected": False}

    open_trades = {t["ticket_mt5"]: t for t in list_entities("Trade", query={"status": "open"}, limit=200) if t.get("ticket_mt5")}
    actions = []
    eligible = 0
    protected = 0

    for pos in positions:
        trade = open_trades.get(pos["ticket"])
        if not trade:
            continue

        direction = pos["direction"]
        entry_price = trade.get("entry_price") or pos["entry_price"]
        original_sl = trade.get("stop_loss")
        events = trade.get("management_events") or []

        if not original_sl:
            # Nothing here to measure R against — the emergency close is the
            # only protection an unprotected position gets.
            if close_fn and equity and equity > 0 and pos["profit"] < 0:
                loss_pct = (-pos["profit"] / equity) * 100
                if loss_pct >= EMERGENCY_CLOSE_EQUITY_PERCENT:
                    result = close_fn(pos["ticket"])
                    if result.get("ok"):
                        actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "emergency_close",
                                         "reason": f"perte {loss_pct:.2f}% de l'equity sans stop loss"})
                    else:
                        actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "failed", "error": result.get("error")})
            continue

        original_risk = abs(entry_price - original_sl)
        if original_risk <= 0:
            continue

        r = _r_multiple(direction, entry_price, pos["current_price"], original_risk)
        remaining_lot = pos["lot"]

        if close_fn and r >= TP1_TRIGGER_R and "tp1_partial" not in events:
            close_vol = round(remaining_lot * TP1_CLOSE_FRACTION, 4)
            result = close_fn(pos["ticket"], volume=close_vol)
            if result.get("ok"):
                remaining_lot = round(remaining_lot - (result.get("closed_volume") or close_vol), 4)
                events = events + ["tp1_partial"]
                update_entity("Trade", trade["id"], {"management_events": events})
                actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "tp1_partial", "closed_volume": result.get("closed_volume")})
            else:
                actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "tp1_failed", "error": result.get("error")})

        if close_fn and remaining_lot > 0 and r >= TP2_TRIGGER_R and "tp1_partial" in events and "tp2_partial" not in events:
            close_vol = round(remaining_lot * TP2_CLOSE_FRACTION, 4)
            result = close_fn(pos["ticket"], volume=close_vol)
            if result.get("ok"):
                remaining_lot = round(remaining_lot - (result.get("closed_volume") or close_vol), 4)
                events = events + ["tp2_partial"]
                update_entity("Trade", trade["id"], {"management_events": events})
                actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "tp2_partial", "closed_volume": result.get("closed_volume")})
            else:
                actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "tp2_failed", "error": result.get("error")})

        if remaining_lot <= 0:
            # TP1/TP2 rounding closed what was left entirely (broker minimum
            # lot step) — nothing left to break-even/trail against.
            continue

        if r < be_trigger:
            continue
        eligible += 1

        current_sl = trade.get("trailing_stop") or original_sl
        at_breakeven_or_better = (current_sl >= entry_price) if direction == "BUY" else (current_sl <= entry_price)

        new_sl = None
        event = None
        if r >= trail_trigger:
            trail_offset = original_risk * TRAIL_DISTANCE_R
            candidate = (pos["current_price"] - trail_offset) if direction == "BUY" else (pos["current_price"] + trail_offset)
            better = (candidate > current_sl) if direction == "BUY" else (candidate < current_sl)
            if better and (candidate > entry_price if direction == "BUY" else candidate < entry_price):
                new_sl, event = candidate, "trailing_stop"
        elif not at_breakeven_or_better:
            new_sl, event = entry_price, "break_even"

        if new_sl is not None:
            result = modify_fn(pos["ticket"], stop_loss=round(new_sl, 5))
            if result.get("ok"):
                update_entity("Trade", trade["id"], {
                    "trailing_stop": new_sl,
                    "management_events": events + [event],
                })
                actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": event, "new_stop_loss": round(new_sl, 5)})
                protected += 1
            else:
                actions.append({"ticket": pos["ticket"], "symbol": pos["symbol"], "event": "failed", "error": result.get("error")})
        elif at_breakeven_or_better or event is None:
            protected += 1

    return {"managed": len(open_trades), "protected": protected, "eligible": eligible, "actions": actions, "connected": True}


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
    date = body.get("date") or _local_today()
    trades = list_entities("Trade", query={"status": "closed"}, sort="-closed_at", limit=500)
    day_trades = [t for t in trades if _to_local_date(t.get("closed_at")) == date]

    if not day_trades:
        return {"ok": True, "date": date, "message": "Aucun trade clôturé ce jour."}, 200

    pnl = sum(t.get("pnl") or 0 for t in day_trades)
    wins = sum(1 for t in day_trades if (t.get("pnl") or 0) > 0)
    losses = sum(1 for t in day_trades if (t.get("pnl") or 0) < 0)
    trade_ids = [t["id"] for t in day_trades]

    params = _get_params()
    capital = params.get("capital") or 1000
    fixed_goal = params.get("daily_goal_amount")
    goal_amount = fixed_goal if fixed_goal is not None else capital * (params.get("daily_goal_percent") or 2) / 100

    existing = list_entities("DailyPerformance", query={"date": date}, sort="-created_date", limit=1)
    payload = {
        "pnl": round(pnl * 100) / 100,
        "pnl_percent": round((pnl / capital) * 100, 2) if capital else 0,
        "goal_amount": round(goal_amount, 2),
        "goal_reached": goal_amount > 0 and pnl >= goal_amount,
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


# ── strategyOrchestrator ────────────────────────────────────────────
# Turns "we can backtest" into "the system decides what to trade". Given
# real candles for a symbol, validates every coded strategy against fixed
# thresholds and activates the best one. If nothing clears the bar, nothing
# goes active — the system stays out of the market rather than trade on a
# strategy that didn't earn it. No LLM anywhere in this path.

def strategy_orchestrator(body):
    import strategy_validator as sv

    symbol = str(body.get("symbol") or "").strip().upper()
    trading_profile = str(body.get("trading_profile") or "intraday").strip()
    timeframe = str(body.get("timeframe") or "H1").strip().upper()
    candles = body.get("candles") or []

    if not symbol:
        return {"error": "Le symbole est requis"}, 400
    if len(candles) < 50:
        return {"error": "Au moins 50 bougies réelles sont nécessaires pour valider une stratégie"}, 400

    params_list = list_entities("Parameter", sort="-created_date", limit=1)
    params = params_list[0] if params_list else {}
    capital = params.get("capital") or 1000
    risk_percent = params.get("max_risk_percent") or 1

    results = sv.validate_all_strategies(candles, symbol, capital, risk_percent)
    best = sv.select_best_strategy(results)

    total_trades = sum(r["stats"]["total_trades"] for r in results)
    summary = (
        f"{best['strategy_name']} validée et activée pour {symbol} ({trading_profile}) — profit factor {best['stats']['profit_factor']}."
        if best else
        f"Aucune stratégie n'a passé les seuils de validation pour {symbol} ({trading_profile}). Aucune activation."
    )
    backtest_run = create_entity("BacktestRun", {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy_name": "Validation automatique (4 stratégies)",
        "strategy_description": f"Validation orchestrée pour le profil {trading_profile}",
        "start_date": candles[0]["time"].split("T")[0],
        "end_date": candles[-1]["time"].split("T")[0],
        "status": "completed",
        "total_trades": total_trades,
        "summary": summary,
        "recommendations": [f"{r['strategy_name']}: {reason}" for r in results for reason in r["reasons"]],
    })

    # Upsert one Strategy record per (symbol, profile, strategy). The winner
    # becomes "active", everything else that was active gets archived — never
    # more than one active strategy per symbol/profile at a time.
    existing = list_entities("Strategy", query={"symbol": symbol, "trading_profile": trading_profile}, sort="-created_date", limit=200)
    existing_by_name = {e["name"]: e for e in existing}

    for r in results:
        is_best = best is not None and r["strategy_name"] == best["strategy_name"]
        status = "active" if is_best else ("testing" if r["passed"] else "archived")
        payload = {
            "name": r["strategy_name"],
            "symbol": symbol,
            "trading_profile": trading_profile,
            "timeframe": timeframe,
            "status": status,
            "backtest_run_id": backtest_run["id"],
            "validated_at": _now_iso(),
            "win_rate": r["stats"]["win_rate"],
            "profit_factor": r["stats"]["profit_factor"],
            "max_drawdown": r["stats"]["max_drawdown"],
            "total_trades": r["stats"]["total_trades"],
            "total_pnl_percent": r["stats"]["total_pnl_percent"],
            "validation_reasons": r["reasons"],
        }
        record = existing_by_name.get(r["strategy_name"])
        if record:
            update_entity("Strategy", record["id"], payload)
        else:
            create_entity("Strategy", payload)

    # Any strategy that was previously active for this symbol/profile but
    # isn't today's winner (including ones no longer in the registry) steps down.
    for e in existing:
        if e.get("status") == "active" and (not best or e.get("name") != best["strategy_name"]):
            update_entity("Strategy", e["id"], {"status": "archived"})

    create_entity("AppLog", {
        "level": "info",
        "category": "strategy",
        "message": (
            f"Stratégie activée pour {symbol} ({trading_profile}): {best['strategy_name']}"
            if best else f"Aucune stratégie validée pour {symbol} ({trading_profile})"
        ),
        "source": "strategyOrchestrator",
        "payload": {
            "symbol": symbol,
            "trading_profile": trading_profile,
            "results": [{"name": r["strategy_name"], "passed": r["passed"], "profit_factor": r["stats"]["profit_factor"]} for r in results],
        },
    })

    return {
        "symbol": symbol,
        "trading_profile": trading_profile,
        "timeframe": timeframe,
        "active_strategy": best["strategy_name"] if best else None,
        "results": results,
        "backtest_run_id": backtest_run["id"],
    }, 200


# ── marketBrain ─────────────────────────────────────────────────────
# Fully deterministic now: direction and confidence come from
# engine_scoring.py's weighted vote across real engine reads, never from
# an LLM. See market_brain.py for the assembly logic.

MULTI_TIMEFRAMES = ["D1", "H4", "H1", "M15", "M5"]


def market_brain_analyze(body, fetch_candles_fn):
    import backtest_engine as bt
    import indicators as ind
    import market_brain as mb

    symbol = str(body.get("symbol") or "").strip().upper()
    trading_profile = str(body.get("trading_profile") or "intraday").strip()
    requested_timeframe = str(body.get("timeframe") or "H1").strip().upper()
    if not symbol:
        return {"error": "Le symbole est requis"}, 400

    mtf_candles = {}
    for tf in MULTI_TIMEFRAMES:
        candles, _resolved, error = fetch_candles_fn(symbol, tf, 300)
        if candles:
            mtf_candles[tf] = candles
    if not mtf_candles:
        return {"error": f"Impossible de récupérer des bougies réelles pour {symbol} — pont MT5 injoignable ou symbole introuvable"}, 400

    tf_selection = None
    if requested_timeframe == "AUTO":
        snapshots = {tf: ind.compute_snapshot(symbol, tf, c) for tf, c in mtf_candles.items()}
        mtf_view = ind.compute_multi_timeframe_view(snapshots)
        timeframe, tf_rationale = mb.select_timeframe(mtf_view)
        tf_selection = {"timeframe": timeframe, "rationale": tf_rationale}
    else:
        timeframe = requested_timeframe

    primary_candles = mtf_candles.get(timeframe)
    if not primary_candles:
        candles, _resolved, error = fetch_candles_fn(symbol, timeframe, 300)
        if not candles:
            return {"error": f"Impossible de récupérer des bougies réelles pour {symbol} ({timeframe}): {error}"}, 400
        primary_candles = candles

    params_list = list_entities("Parameter", sort="-created_date", limit=1)
    params = params_list[0] if params_list else {}
    capital = params.get("capital") or 1000
    risk_percent = params.get("max_risk_percent") or 1

    active = list_entities("Strategy", query={"symbol": symbol, "trading_profile": trading_profile, "status": "active"}, limit=1)
    validated_strategy = None
    if active:
        st = active[0]
        signal = bt.evaluate_live_signal(st["name"], primary_candles)
        validated_strategy = {
            "strategy_name": st["name"],
            "signal": signal,
            "stats": {"win_rate": st.get("win_rate"), "profit_factor": st.get("profit_factor"),
                      "max_drawdown": st.get("max_drawdown"), "total_trades": st.get("total_trades")},
        }

    result = mb.analyze(symbol, timeframe, primary_candles, multi_tf_candles=mtf_candles,
                         validated_strategy=validated_strategy, capital=capital, risk_percent=risk_percent)

    vs_entity = None
    if validated_strategy:
        signal = validated_strategy.get("signal")
        vs_entity = {
            "strategy_name": validated_strategy["strategy_name"],
            "agreement": result["validated_strategy_agreement"],
            "signal_direction": signal["direction"] if signal else None,
            "signal_rationale": signal["rationale"] if signal else None,
        }

    record = create_entity("AIDecision", {
        "symbol": symbol,
        "decision": result["decision"],
        "confidence": result["confidence"],
        "timeframe": result["timeframe"],
        "current_price": result["current_price"],
        "entry_type": result["entry_type"],
        "entry_zone_low": result["entry_zone_low"],
        "entry_zone_high": result["entry_zone_high"],
        "ideal_entry": result["ideal_entry"],
        "stop_loss": result["stop_loss"],
        "take_profit_1": result["take_profit_1"],
        "take_profit_2": result["take_profit_2"],
        "break_even": result["break_even"],
        "rationale": result["rationale"],
        "explanation": result["explanation"],
        "probable_scenario": result["probable_scenario"],
        "invalidation": result["invalidation"],
        "scenarios": result["scenarios"],
        "engine_results": result["engine_results"],
        "conflicts": result["conflicts"],
        "validated_strategy": vs_entity,
        "market_regime": result["market_regime"],
    })

    return {
        "decision": record,
        "tier": result["tier"],
        "fused_confidence": result["fused_confidence"],
        "engine_count": len(result["engine_results"]),
        "timeframe_selection": tf_selection,
    }, 200


# ── engineTest ──────────────────────────────────────────────────────
# Individual-engine diagnostics for the Validation Center, and the
# "pipeline" mode which just delegates to market_brain_analyze.

_ENGINE_TEST_NOT_IMPLEMENTED = {
    "economic": "Pas de source de données de calendrier économique disponible — moteur neutralisé plutôt que simulé.",
    "ai_confidence": "Remplacé par la fusion pondérée réelle des moteurs (voir le résultat du pipeline).",
}


def _get_params():
    params_list = list_entities("Parameter", sort="-created_date", limit=1)
    return params_list[0] if params_list else {}


def is_simulation_mode():
    """Single source of truth for whether a real MT5 order may be sent.
    Checked in the bridge itself (alphatg_bridge.py /send_order and
    /send_pending_order), not just the frontend — execution_mode was
    previously a display-only label with no actual enforcement anywhere in
    the order-sending path, meaning "Mode Simulation" did not stop a real
    order from reaching MT5 if the account happened to be connected."""
    return (_get_params().get("execution_mode") or "simulation") == "simulation"


def _today_closed_trades():
    today = _local_today()
    trades = list_entities("Trade", query={"status": "closed"}, sort="-closed_at", limit=500)
    return [t for t in trades if _to_local_date(t.get("closed_at")) == today]


def score_position_management(get_positions_fn, modify_fn, params):
    result = manage_open_positions(get_positions_fn, modify_fn, params)
    if not result["connected"]:
        return {"confidence": 0, "bias": "neutral", "findings": ["MT5 non connecté — gestion de position indisponible"]}
    if result["managed"] == 0:
        return {"confidence": 100, "bias": "neutral", "findings": ["Aucune position ouverte à gérer"]}
    ratio = (result["protected"] / result["eligible"]) if result["eligible"] else 1
    findings = [f"{result['protected']}/{max(result['eligible'], result['managed'])} position(s) suivie(s) protégée(s) (break-even/trailing)"]
    findings += [f"{a['event']}: {a['symbol']} (ticket {a['ticket']})" + (f" → SL {a['new_stop_loss']}" if a.get("new_stop_loss") else f" — {a.get('error')}") for a in result["actions"][:3]]
    return {"confidence": round(ratio * 100), "bias": "neutral", "findings": findings}


def score_risk_management(params):
    capital = params.get("capital") or 1000
    max_daily_loss_pct = params.get("max_daily_loss_percent") or 2
    max_daily_trades = params.get("max_daily_trades") or 3

    today_trades = _today_closed_trades()
    today_pnl = sum(t.get("pnl") or 0 for t in today_trades)
    loss_budget = capital * max_daily_loss_pct / 100
    loss_used_pct = round(min(100, max(0, -today_pnl / loss_budget * 100))) if loss_budget > 0 else 0
    open_positions = list_entities("Trade", query={"status": "open"}, limit=100)

    findings = [
        f"Budget de perte journalier utilisé : {loss_used_pct}% ({today_pnl:.2f}$ sur limite -{loss_budget:.2f}$)",
        f"Trades clôturés aujourd'hui : {len(today_trades)}/{max_daily_trades}",
        f"Positions ouvertes : {len(open_positions)}",
    ]
    return {"confidence": max(0, 100 - loss_used_pct), "bias": "neutral", "findings": findings}


def score_execution_engine():
    accounts = list_entities("TradingAccount", limit=1)
    acct = accounts[0] if accounts else {}
    latency = acct.get("latency_ms")
    if acct.get("connection_status") != "connected" or latency is None:
        return {"confidence": 0, "bias": "neutral", "findings": ["Compte non connecté — aucune mesure d'exécution disponible"]}
    if latency < 200:
        confidence = 95
    elif latency < 500:
        confidence = 75
    elif latency < 1000:
        confidence = 50
    else:
        confidence = 25
    return {"confidence": confidence, "bias": "neutral", "findings": [f"Latence de connexion mesurée : {latency}ms", f"Plateforme : {acct.get('platform', 'mt5')}"]}


def daily_goal_status(params):
    """Shared by the engine score AND the frontend's pre-trade gate (see
    dispatcher action dailyGoalStatus) — one source of truth for whether
    autonomous execution should keep trading today.

    daily_goal_amount/max_daily_loss_amount (fixed $, settable in Settings)
    take precedence when set — most users think in dollars, not in percent
    of a capital figure they may never have configured. Falls back to the
    original percent-of-capital calculation for backward compatibility."""
    capital = params.get("capital") or 1000
    today_trades = _today_closed_trades()
    pnl = sum(t.get("pnl") or 0 for t in today_trades)

    fixed_goal = params.get("daily_goal_amount")
    goal_amount = fixed_goal if fixed_goal is not None else capital * (params.get("daily_goal_percent") or 2) / 100

    fixed_loss = params.get("max_daily_loss_amount")
    loss_limit = fixed_loss if fixed_loss is not None else capital * (params.get("max_daily_loss_percent") or 2) / 100
    goal_reached = goal_amount > 0 and pnl >= goal_amount
    protection_triggered = loss_limit > 0 and pnl <= -loss_limit
    progress_pct = round(min(100, max(0, pnl / goal_amount * 100))) if goal_amount > 0 else 0
    return {
        "pnl": round(pnl, 2), "goal_amount": round(goal_amount, 2), "loss_limit": round(loss_limit, 2),
        "progress_pct": progress_pct, "goal_reached": goal_reached, "protection_triggered": protection_triggered,
        "stop_trading": goal_reached or protection_triggered,
    }


def score_daily_goal(params):
    status = daily_goal_status(params)
    if status["protection_triggered"]:
        return {"confidence": 100, "bias": "neutral", "findings": [
            f"Protection de capital déclenchée : perte du jour {status['pnl']:.2f}$ ≥ limite -{status['loss_limit']:.2f}$ — trading autonome arrêté pour aujourd'hui"]}
    if status["goal_reached"]:
        return {"confidence": 100, "bias": "neutral", "findings": [
            f"Objectif journalier atteint : {status['pnl']:.2f}$ ≥ {status['goal_amount']:.2f}$ — trading autonome arrêté pour aujourd'hui"]}
    return {"confidence": status["progress_pct"], "bias": "neutral", "findings": [
        f"Progression vers l'objectif : {status['pnl']:.2f}$ / {status['goal_amount']:.2f}$ ({status['progress_pct']}%)"]}


def score_ai_learning():
    learning = list_entities("LearningData", sort="-created_date", limit=200)
    if len(learning) < 10:
        return {"confidence": round(len(learning) * 10), "bias": "neutral", "findings": [
            f"Historique insuffisant ({len(learning)} trade(s) clôturé(s)) pour évaluer la calibration réelle du système"]}
    wins = sum(1 for l in learning if l.get("outcome") == "win")
    win_rate = round(wins / len(learning) * 100)
    return {"confidence": win_rate, "bias": "neutral", "findings": [f"Taux de réussite réel sur les {len(learning)} derniers trades clôturés : {win_rate}%"]}


def score_autonomous_trading(params):
    if not params.get("autonomous_execution_enabled"):
        return {"confidence": 0, "bias": "neutral", "findings": ["Exécution autonome désactivée (mode manuel — les signaux sont créés mais aucun ordre n'est envoyé)"]}
    return {"confidence": 80, "bias": "neutral", "findings": [f"Exécution autonome active — mode {params.get('execution_mode') or 'simulation'}"]}


_REAL_TIME_ENGINE_SCORERS = {
    "position_management": lambda params, get_positions_fn, modify_fn: score_position_management(get_positions_fn, modify_fn, params),
    "risk_management": lambda params, get_positions_fn, modify_fn: score_risk_management(params),
    "daily_goal": lambda params, get_positions_fn, modify_fn: score_daily_goal(params),
    "ai_learning": lambda params, get_positions_fn, modify_fn: score_ai_learning(),
    "execution_engine": lambda params, get_positions_fn, modify_fn: score_execution_engine(),
    "autonomous_trading": lambda params, get_positions_fn, modify_fn: score_autonomous_trading(params),
}


def engine_test(body, fetch_candles_fn, get_positions_fn=None, modify_position_fn=None):
    import engine_scoring as es
    import indicators as ind

    symbol = str(body.get("symbol") or "XAUUSD").strip().upper()
    timeframe = str(body.get("timeframe") or "H1").strip().upper()

    if body.get("pipeline") is True:
        result, status = market_brain_analyze(body, fetch_candles_fn)
        if status != 200:
            return result, status
        decision = result["decision"]
        return {
            "pipeline": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "ok",
            "response_time_ms": 0,
            "decision": decision,
            "tier": result["tier"],
            "fused_confidence": result["fused_confidence"],
            "engine_count": result["engine_count"],
            "logs": [f"Décision: {decision.get('decision')} ({decision.get('confidence')}%)",
                     f"Moteurs analysés: {result['engine_count']}",
                     f"Confiance fusionnée: {result['fused_confidence']}%"],
        }, 200

    engine_id = str(body.get("engine_id") or "").strip()
    if not engine_id:
        return {"error": "engine_id est requis"}, 400

    if engine_id == "session":
        r = es.score_session({})
        return {
            "engine_id": "session", "engine_name": "Session Intelligence", "symbol": symbol, "timeframe": timeframe,
            "status": "ok", "response_time_ms": 0, "confidence": r["confidence"], "bias": r["bias"],
            "findings": r["findings"], "risks": [], "details": "Calcul déterministe depuis l'horloge, aucun LLM appelé.",
            "logs": ["Session calculée directement depuis l'horloge (aucun LLM appelé)"],
        }, 200

    if engine_id in _REAL_TIME_ENGINE_SCORERS:
        params = _get_params()
        r = _REAL_TIME_ENGINE_SCORERS[engine_id](params, get_positions_fn or (lambda: None), modify_position_fn or (lambda *a, **k: {"ok": False, "error": "unavailable"}))
        return {
            "engine_id": engine_id, "engine_name": engine_id, "symbol": symbol, "timeframe": timeframe,
            "status": "ok", "response_time_ms": 0, "confidence": r["confidence"], "bias": r["bias"],
            "findings": r["findings"], "risks": [], "details": "; ".join(r["findings"]),
            "logs": [f"{engine_id} calculé à partir de données réelles (comptes/trades/paramètres), aucun LLM appelé"],
        }, 200

    if engine_id in _ENGINE_TEST_NOT_IMPLEMENTED:
        return {
            "engine_id": engine_id, "engine_name": engine_id, "symbol": symbol, "timeframe": timeframe,
            "status": "not_implemented", "response_time_ms": 0, "confidence": 0, "bias": "neutral",
            "findings": [], "risks": [], "details": _ENGINE_TEST_NOT_IMPLEMENTED[engine_id],
            "logs": [_ENGINE_TEST_NOT_IMPLEMENTED[engine_id]],
        }, 200

    if engine_id == "multi_timeframe":
        mtf_candles = {}
        for tf in MULTI_TIMEFRAMES:
            candles, _resolved, _error = fetch_candles_fn(symbol, tf, 300)
            if candles:
                mtf_candles[tf] = candles
        if not mtf_candles:
            return {"error": "Impossible de récupérer des bougies réelles"}, 400
        snapshots = {tf: ind.compute_snapshot(symbol, tf, c) for tf, c in mtf_candles.items()}
        view = ind.compute_multi_timeframe_view(snapshots)
        findings = [f"{view['timeframes_analyzed']} timeframes analysés, {view['alignment_score']}% alignés sur {view['dominant_bias']}"]
        findings += [f"{t['timeframe']}: {t['bias']}" for t in view["timeframes"]]
        return {
            "engine_id": "multi_timeframe", "engine_name": "Multi-Timeframe Engine", "symbol": symbol, "timeframe": timeframe,
            "status": "ok", "response_time_ms": 0, "confidence": view["alignment_score"], "bias": view["dominant_bias"],
            "findings": findings, "risks": [], "details": f"Biais dominant {view['dominant_bias']} sur {view['timeframes_analyzed']} timeframes réels.",
            "logs": ["Calcul déterministe multi-timeframe, aucun LLM appelé"],
        }, 200

    if engine_id not in es.ENGINE_SCORERS:
        return {"error": f"Moteur inconnu: {engine_id}"}, 400

    candles, _resolved, error = fetch_candles_fn(symbol, timeframe, 300)
    if not candles:
        return {"error": f"Impossible de récupérer des bougies réelles pour {symbol} ({timeframe}): {error}"}, 400

    ctx = es.build_context(candles)
    r = es.ENGINE_SCORERS[engine_id](ctx)
    return {
        "engine_id": engine_id, "engine_name": engine_id, "symbol": symbol, "timeframe": timeframe,
        "status": "ok", "response_time_ms": 0, "confidence": r["confidence"], "bias": r["bias"],
        "findings": r["findings"], "risks": [], "details": "; ".join(r["findings"]),
        "logs": [f"{engine_id} calculé sur {len(candles)} bougies réelles, aucun LLM appelé"],
    }, 200


# ── Stubs for functions not yet ported off the LLM (next phase) ──

_STUB_LABEL = "Moteur en cours de portage vers une logique déterministe Python (LLM retiré) — pas encore actif."

_STUB_DECISIONS = {"strategyTester"}
_STUB_NOOPS = {"slackNotifier"}


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
