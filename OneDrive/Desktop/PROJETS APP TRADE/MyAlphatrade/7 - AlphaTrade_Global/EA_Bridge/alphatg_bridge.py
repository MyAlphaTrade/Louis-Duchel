"""
AlphaTrade Global — alphatg_bridge (Real-Time Edition)
======================================================

This Python script runs on the machine where MetaTrader 5 is installed
and acts as the local bridge between the web UI and the MT5 terminal.

ARCHITECTURE:
  - REST endpoints for one-off operations (orders, symbols, history)
  - SSE /stream endpoint for real-time push of account & position changes
  - Background monitor thread polls MT5 every 200ms and pushes ONLY on change

REAL-TIME PATH:
  MT5 Python API  →  Monitor thread (200ms)  →  Change detection  →  SSE queue  →  Browser

This gives ~200ms latency (vs 3000ms with the old polling approach).
For sub-10ms latency, deploy the MQL5 EA (alphatg_monitor.mq5) which uses
OnTradeTransaction() to push events via TCP socket to this bridge.

PREREQUISITES:
  pip install MetaTrader5 flask flask-cors

USAGE:
  python alphatg_bridge.py
  # REST API on http://localhost:8000
  # SSE stream on http://localhost:8000/stream
"""

import os
import sys
import json
import secrets
import logging
import threading
import queue
import time
from datetime import datetime, timedelta

# ── Optional imports (checked at runtime) ───────────────────────
try:
    import MetaTrader5 as mt5
except ImportError:
    print("WARNING: MetaTrader5 package not installed.")
    print("Run: pip install MetaTrader5")
    mt5 = None

try:
    from flask import Flask, request, jsonify, Response
    from flask_cors import CORS
except ImportError:
    print("ERROR: Flask not installed.")
    print("Run: pip install flask flask-cors")
    sys.exit(1)

import local_store
import local_functions
import hyperliquid_connector
import global_market_intelligence
import portfolio_risk
import asset_validation
import learning_engine
import instance_lock

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("alphatg_bridge")

# ── Allowed origins (Security Hardening, 2026-08-06) ──────────────
# The bridge only listening on 127.0.0.1 is NOT a real security boundary on
# its own: with CORS wide open ("*") and no Origin check, any unrelated web
# page open in the SAME browser could fetch()/POST/PATCH/DELETE against
# /entities or /functions from its own JavaScript — the browser sends the
# request regardless of which tab is "focused". That is the real app's own
# renderer origin (verified against electron-main.js):
#   - Packaged app: mainWindow.loadFile(...) over file:// — the Fetch spec
#     serializes a file:// document's Origin header as the literal string
#     "null", not the word "none" or an empty header.
#   - Dev app / Electron dev mode: mainWindow.loadURL('http://localhost:5173')
#     (matches Dist's own Vite dev server port, see .claude/launch.json).
# A request with NO Origin header at all (curl, server-to-server, or some
# non-browser HTTP clients) is also allowed — Origin is a browser-added
# header, and this bridge already trusts anything running on the same
# machine (127.0.0.1) that isn't a browser tab from an unrelated site.
ALLOWED_ORIGINS = {"null", "http://localhost:5173", "http://127.0.0.1:5173"}


def _request_origin_allowed():
    origin = request.headers.get("Origin")
    return origin is None or origin in ALLOWED_ORIGINS


def _cors_origin_header():
    """Echo back the caller's own Origin if it's allowed (required for
    Access-Control-Allow-Origin to work with a non-"*" allowlist — the
    header must match the request's Origin exactly, it can't be a list).
    Falls back to the dev origin for non-browser callers (no Origin sent),
    which is harmless since those callers don't enforce CORS anyway."""
    origin = request.headers.get("Origin")
    return origin if origin in ALLOWED_ORIGINS else "http://localhost:5173"


# ── Flask app ────────────────────────────────────────────────────
# CORS is handled entirely by hand below (add_pna_headers + the OPTIONS
# branch in check_auth) rather than via flask_cors.CORS(): the two systems
# fought over the Access-Control-Allow-Origin header when both were active
# (flask_cors's own after_request hook silently overwrote the origin-echo
# logic below with "*", defeating the whole point of ALLOWED_ORIGINS —
# caught by the live curl tests during the 2026-08-06 security hardening).
# flask_cors stays a listed dependency only because CORS(...)'s import
# guard above gives a clear "pip install flask flask-cors" error message.
app = Flask(__name__)


@app.after_request
def add_pna_headers(resp):
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    resp.headers["Access-Control-Allow-Origin"] = _cors_origin_header()
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# ── API Key management ───────────────────────────────────────────
# Same persistent directory as the entity DB (Task #82) — travels together
# with alphatg_local.db so a real BRIDGE_DATA_DIR protects both, and a
# pre-existing key survives the upgrade via the same one-time migration.
_KEY_FILE = os.path.join(os.path.dirname(local_store.DB_PATH), "bridge_api_key.txt")
local_store.migrate_legacy_file("bridge_api_key.txt")


def load_or_create_api_key():
    if os.path.isfile(_KEY_FILE):
        with open(_KEY_FILE, "r") as f:
            key = f.read().strip()
            if key:
                return key
    key = "atg_" + secrets.token_hex(16)
    with open(_KEY_FILE, "w") as f:
        f.write(key)
    log.info("Generated new API key (saved to %s)", _KEY_FILE)
    return key


BRIDGE_API_KEY = load_or_create_api_key()

# ── CORS preflight + Auth middleware ────────────────────────────
@app.before_request
def check_auth():
    if request.method == "OPTIONS":
        resp = app.response_class(status=204)
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        resp.headers["Access-Control-Allow-Origin"] = _cors_origin_header()
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    if request.path == "/health":
        return None

    # Local app data (entities/auth/functions) is not MT5-order-sensitive, and
    # keeping the API key requirement here would create a chicken-and-egg
    # problem (the frontend needs to read TradingAccount before it can even
    # display the API key field) — so these stay key-free. But "the bridge
    # only listens on 127.0.0.1" is NOT by itself a security boundary: any
    # unrelated web page open in the same browser can still reach 127.0.0.1
    # from its own JavaScript. The real boundary enforced here is Origin —
    # only the app's own renderer (see ALLOWED_ORIGINS above) may call these
    # paths without a key. Hardened 2026-08-06 after the professional audit
    # flagged this as the most realistic attack surface on a local desktop
    # trading app: an attacker can't send an MT5 order this way (/send_order
    # and friends are outside this exemption and still require the API key
    # below), but could otherwise have rewritten Parameter/TradingAccount —
    # e.g. max_risk_percent or execution_mode — which the legitimate app
    # would then have traded on at its next cycle, believing it was its own
    # configuration.
    if request.path.startswith("/auth") or request.path.startswith("/entities") or request.path.startswith("/functions"):
        if not _request_origin_allowed():
            return jsonify({"ok": False, "error": "Origin non autorisée"}), 403
        return None

    # SSE endpoint accepts key via query param (EventSource can't set headers)
    if request.path == "/stream":
        token = request.args.get("key", "")
        if token != BRIDGE_API_KEY:
            return jsonify({"ok": False, "error": "Invalid or missing API key"}), 401
        return None

    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer") else ""

    if token != BRIDGE_API_KEY:
        return jsonify({"ok": False, "error": "Invalid or missing API key"}), 401

# ── MT5 terminal auto-detection ──────────────────────────────────
def detect_mt5_terminal():
    candidates = []

    if sys.platform == "win32":
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
        appdata = os.environ.get("APPDATA", "")

        candidates = [
            os.path.join(program_files, "MetaTrader 5", "terminal64.exe"),
            os.path.join(program_files_x86, "MetaTrader 5", "terminal64.exe"),
            os.path.join(appdata, "MetaTrader 5", "terminal64.exe"),
            os.path.join(program_files_x86, "MetaQuotes", "Terminal", "terminal64.exe"),
        ]

        terminals_dir = os.path.join(appdata, "MetaQuotes", "Terminal")
        if os.path.isdir(terminals_dir):
            for subdir in os.listdir(terminals_dir):
                exe = os.path.join(terminals_dir, subdir, "terminal64.exe")
                if os.path.isfile(exe):
                    candidates.insert(0, exe)

    elif sys.platform == "darwin":
        candidates = [
            "/Applications/MetaTrader 5.app/Contents/MacOS/metatrader5",
            "/Applications/MetaTrader 5.app/Contents/MacOS/MetaTrader 5",
        ]

    for path_str in candidates:
        if os.path.isfile(path_str):
            log.info("MT5 terminal detected: %s", path_str)
            return path_str

    log.warning("MT5 terminal not found in standard locations.")
    return None

# Magic number stamped on every order Global itself sends (all 4 order
# routes below) — the same value an MT5 EA would use to tag its own
# trades. Doubles as the trade-origin signal for _get_recent_trades():
# a closed deal carrying this magic came from Global's own autonomous/
# manual-in-app execution; anything else (0, or a different EA's magic)
# was placed outside the app (MT5 terminal directly, another EA, a
# manual order on the broker's mobile app, etc.) — see Task #82.
GLOBAL_MAGIC_NUMBER = 234000

# ── MT5 auto-connection ──────────────────────────────────────────
_connection = {"initialized": False, "account_type": None, "login": None, "instance_lock_acquired": False}
_mt5_lock = threading.Lock()


def mt5_auto_connect():
    if mt5 is None:
        log.error("MetaTrader5 Python package not installed.")
        return False

    terminal_path = detect_mt5_terminal()
    init_kwargs = {"path": terminal_path} if terminal_path else {}

    if not mt5.initialize(**init_kwargs):
        error = mt5.last_error()
        log.error("MT5 initialize() failed: %s", error)
        log.error("Make sure MetaTrader 5 is running and you are logged in.")
        return False

    info = mt5.account_info()
    if info is None:
        log.error("MT5 connected but no account info. Log in to MT5 first, then restart the bridge.")
        mt5.shutdown()
        return False

    server_lower = (info.server or "").lower()
    if "demo" in server_lower:
        account_type = "demo"
    elif "live" in server_lower or "real" in server_lower:
        account_type = "real"
    elif hasattr(info, "trade_mode") and info.trade_mode == 2:
        account_type = "real"
    else:
        account_type = "demo"

    # Instance lock (2026-08-07) — see instance_lock.py's module docstring
    # for the real incident this closes. Must run BEFORE _connection is
    # marked initialized so callers checking _connection["initialized"]
    # never see a half-registered connection.
    acquired, holder = instance_lock.acquire_or_check(os.path.dirname(local_store.DB_PATH), info.login)
    _connection.update({
        "initialized": True, "account_type": account_type,
        "login": info.login, "instance_lock_acquired": acquired,
    })

    log.info("=" * 60)
    log.info("MT5 CONNECTED SUCCESSFULLY")
    log.info("  Account: %s", info.login)
    log.info("  Server:  %s", info.server)
    log.info("  Type:    %s", account_type)
    log.info("  Balance: %s %s", info.balance, info.currency)
    if not acquired:
        log.error("=" * 60)
        log.error("DUPLICATE BRIDGE DETECTED — another live process (pid %s) is already",
                   holder.get("pid") if holder else "?")
        log.error("managing this SAME MT5 account (login %s, last heartbeat %s).",
                   info.login, holder.get("heartbeat_at") if holder else "?")
        log.error("Position Manager will NOT start here, and order-mutating requests")
        log.error("will be refused, to avoid two bridges fighting over the same positions.")
        log.error("=" * 60)
    log.info("=" * 60)
    return True


def mt5_disconnect():
    if _connection["initialized"] and mt5 is not None:
        mt5.shutdown()
    _connection.update({"initialized": False, "account_type": None, "login": None, "instance_lock_acquired": False})
    log.info("MT5 disconnected")

# ── Snapshot helper (used by both REST and SSE) ──────────────────
def get_account_snapshot():
    """Read current account + positions state from MT5. Thread-safe."""
    if not _connection["initialized"] or mt5 is None:
        return None

    with _mt5_lock:
        info = mt5.account_info()
        if info is None:
            return None

        positions = mt5.positions_get() or []
        floating_profit = sum(p.profit for p in positions)
        orders = mt5.orders_get() or []

    return {
        "ok": True,
        "balance": info.balance,
        "equity": info.equity,
        "floating_profit": floating_profit,
        "daily_profit": floating_profit,
        "margin": info.margin,
        "margin_level": info.margin_level,
        "open_positions_count": len(positions),
        "pending_orders_count": len(orders),
        "drawdown": 0,
        "win_rate": 0,
        "account_number": str(info.login),
        "currency": info.currency,
        "leverage": "1:" + str(info.leverage),
        "server": info.server,
        "account_type": _connection["account_type"],
    }

# ── Open positions (real-time) ───────────────────────────────────
def get_open_positions():
    """Read current open positions from MT5. Thread-safe."""
    if not _connection["initialized"] or mt5 is None:
        return None

    with _mt5_lock:
        positions = mt5.positions_get() or []

    result = []
    for p in positions:
        direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        result.append({
            "ticket": str(p.ticket),
            "symbol": p.symbol,
            "direction": direction,
            "lot": p.volume,
            "entry_price": p.price_open,
            "current_price": p.price_current,
            "stop_loss": p.sl,
            "take_profit": p.tp,
            "profit": round(p.profit, 2),
            "swap": round(getattr(p, "swap", 0), 2),
            "opened_at": datetime.fromtimestamp(p.time).isoformat() if p.time else None,
        })
    result.sort(key=lambda x: x.get("opened_at") or "", reverse=True)
    return result


# ── Symbol resolution (auto-mapping for broker suffixes) ─────────
# Brokers append suffixes to symbol names (XAGUSD.m, XAGUSD.raw, etc).
# The bridge must find the actual symbol available in the terminal.

_SYMBOL_CACHE = {}  # requested → resolved symbol (avoids repeated lookups)


def resolve_symbol(requested_symbol):
    """Find the actual MT5 symbol matching the requested name.

    Tries exact match first, then scans Market Watch for symbols
    starting with the requested name (covering .m, .raw, .a, etc).

    Returns: {"requested": str, "resolved": str|None, "found": bool, "similar": list}
    """
    if not _connection["initialized"] or mt5 is None:
        return {"requested": requested_symbol, "resolved": None, "found": False, "similar": [], "reason": "CONNECTION_LOST"}

    if requested_symbol in _SYMBOL_CACHE:
        resolved = _SYMBOL_CACHE[requested_symbol]
        log.info("[SYMBOL_MAPPING] requested=%s resolved=%s (cache hit)", requested_symbol, resolved)
        return {"requested": requested_symbol, "resolved": resolved, "found": True, "similar": []}

    with _mt5_lock:
        # 1. Exact match
        info = mt5.symbol_info(requested_symbol)
        if info is not None:
            mt5.symbol_select(requested_symbol, True)
            _SYMBOL_CACHE[requested_symbol] = requested_symbol
            log.info("[SYMBOL_MAPPING] requested=%s resolved=%s (exact)", requested_symbol, requested_symbol)
            return {"requested": requested_symbol, "resolved": requested_symbol, "found": True, "similar": []}

        # 2. Pattern search via MT5 group filter (much faster than fetching all symbols)
        #    Group pattern uses * as wildcard — "*XAGUSD*" matches any symbol containing XAGUSD
        prefix = requested_symbol.upper()
        pattern_matches = mt5.symbols_get(group="*" + prefix + "*") or []
        matches = [s.name for s in pattern_matches]

        # 3. Also try prefix-only search (symbol starts with requested name)
        if not matches:
            prefix_matches = mt5.symbols_get(group=prefix + "*") or []
            matches = [s.name for s in prefix_matches]

        # 4. Try without trailing digits (XAGUSD4 → XAGUSD)
        if not matches and prefix[-1].isdigit():
            prefix_no_digit = prefix.rstrip("0123456789")
            matches = [s.name for s in (mt5.symbols_get(group="*" + prefix_no_digit + "*") or [])]

    if matches:
        resolved = matches[0]
        mt5.symbol_select(resolved, True)
        _SYMBOL_CACHE[requested_symbol] = resolved
        log.info("[SYMBOL_MAPPING] requested=%s resolved=%s (auto-detected from %d candidates)", requested_symbol, resolved, len(matches))
        return {
            "requested": requested_symbol,
            "resolved": resolved,
            "found": True,
            "similar": matches[:5],
        }

    # 5. Fallback: fetch all symbols and compare normalized names.
    #    Handles "Crash 1000 Index" → "CRASH1000", "SP 500" → "SP500", etc.
    #    MT5 stores symbols with spaces and suffixes that break exact/group matching.
    all_syms = mt5.symbols_get() or []
    requested_norm = requested_symbol.upper().replace(" ", "").replace("INDEX", "").replace(".", "")
    for s in all_syms:
        sym_norm = s.name.upper().replace(" ", "").replace("INDEX", "").replace(".", "")
        if sym_norm == requested_norm:
            mt5.symbol_select(s.name, True)
            _SYMBOL_CACHE[requested_symbol] = s.name
            log.info("[SYMBOL_MAPPING] requested=%s resolved=%s (normalized match)", requested_symbol, s.name)
            return {
                "requested": requested_symbol,
                "resolved": s.name,
                "found": True,
                "similar": [],
            }

    log.warning("[SYMBOL_MAPPING] requested=%s NOT FOUND (no matching symbol in terminal)", requested_symbol)
    return {
        "requested": requested_symbol,
        "resolved": None,
        "found": False,
        "similar": [],
        "reason": "SYMBOL_NOT_FOUND",
    }


# ── Filling mode auto-detection ─────────────────────────────────
# Each symbol/broker supports specific filling modes. Sending the wrong
# one causes retcode 10030 (Unsupported filling mode).
# We read symbol_info.filling_mode bitmask and pick the first supported.

_FILLING_PRIORITY = [
    ("FOK", "ORDER_FILLING_FOK"),
    ("IOC", "ORDER_FILLING_IOC"),
    ("RETURN", "ORDER_FILLING_RETURN"),
]


def get_supported_filling_mode(symbol):
    """Determine which filling mode the broker accepts for this symbol.

    Returns: {"symbol": str, "available_modes": list, "selected_mode": str}
    """
    if not _connection["initialized"] or mt5 is None:
        return {"symbol": symbol, "available_modes": [], "selected_mode": None, "reason": "CONNECTION_LOST"}

    with _mt5_lock:
        info = mt5.symbol_info(symbol)

    if info is None:
        return {"symbol": symbol, "available_modes": [], "selected_mode": None, "reason": "SYMBOL_NOT_FOUND"}

    filling_mask = getattr(info, "filling_mode", 0) or 0
    available = []

    # MT5 bitmask: bit 0 = FOK (SYMBOL_FILLING_FOK=1), bit 1 = IOC (SYMBOL_FILLING_IOC=2)
    if filling_mask & 1:
        available.append("FOK")
    if filling_mask & 2:
        available.append("IOC")

    # If mask is 0 (broker didn't set it), try all modes in priority order.
    # Most forex symbols use FOK (Fill or Kill) — the MT5 spec window is
    # the source of truth, and many brokers leave filling_mode=0 despite it.
    if not available:
        available = ["FOK", "IOC", "RETURN"]

    # Select first available — priority order
    selected = available[0]
    selected_const = getattr(mt5, "ORDER_FILLING_" + selected, mt5.ORDER_FILLING_RETURN)

    log.info("[ORDER_FILLING_CHECK] symbol=%s available_modes=%s selected_mode=%s (mask=%s)",
             symbol, available, selected, filling_mask)

    return {
        "symbol": symbol,
        "available_modes": available,
        "selected_mode": selected,
        "selected_const": selected_const,
    }


# ── Pre-order validation checklist ──────────────────────────────
# Runs a full checklist before sending any order. If any check fails,
# the order is NOT sent and a structured error is returned.

def pre_order_validation(symbol, lot, direction):
    """Validate all preconditions before sending an order.

    Returns: {"valid": bool, "reason": str, "details": dict}
    """
    details = {}

    # 1. MT5 connection active
    if not _connection["initialized"] or mt5 is None:
        return {"valid": False, "reason": "CONNECTION_LOST", "details": {"connected": False}}

    # 2. Symbol resolution
    sym_result = resolve_symbol(symbol)
    if not sym_result["found"]:
        return {"valid": False, "reason": "SYMBOL_NOT_FOUND", "details": {
            "requested": symbol, "similar": sym_result.get("similar", []),
        }}
    resolved = sym_result["resolved"]
    details["resolved_symbol"] = resolved

    with _mt5_lock:
        info = mt5.symbol_info(resolved)
        tick = mt5.symbol_info_tick(resolved)

    if info is None:
        return {"valid": False, "reason": "SYMBOL_NOT_FOUND", "details": {"requested": symbol}}

    # 3. Market open
    # trade_mode: 0=disabled, 1=long only, 2=short only, 3=full access
    if getattr(info, "trade_mode", 3) == 0:
        return {"valid": False, "reason": "MARKET_CLOSED", "details": {"symbol": resolved, "trade_mode": info.trade_mode}}
    details["trade_mode"] = getattr(info, "trade_mode", None)

    # 4. Tick available (price feed active)
    if tick is None:
        return {"valid": False, "reason": "MARKET_CLOSED", "details": {"symbol": resolved, "reason": "no tick"}}
    details["tick_price"] = tick.ask if direction.upper() == "BUY" else tick.bid

    # 5. Volume validation (min/max/step)
    min_vol = getattr(info, "volume_min", 0.01)
    max_vol = getattr(info, "volume_max", 100.0)
    vol_step = getattr(info, "volume_step", 0.01)
    details["volume"] = {"lot": lot, "min": min_vol, "max": max_vol, "step": vol_step}

    if lot < min_vol:
        return {"valid": False, "reason": "INVALID_VOLUME", "details": {
            "symbol": resolved, "lot": lot, "min": min_vol, "issue": "below_minimum",
        }}
    if lot > max_vol:
        return {"valid": False, "reason": "INVALID_VOLUME", "details": {
            "symbol": resolved, "lot": lot, "max": max_vol, "issue": "above_maximum",
        }}
    # Normalize lot to step
    normalized_lot = round(round(lot / vol_step) * vol_step, 4)
    if normalized_lot < min_vol:
        normalized_lot = min_vol
    details["normalized_lot"] = normalized_lot

    # 6. Filling mode compatible
    fill_result = get_supported_filling_mode(resolved)
    if fill_result.get("selected_const") is None:
        return {"valid": False, "reason": "FILLING_MODE_UNSUPPORTED", "details": {"symbol": resolved}}
    details["filling_mode"] = fill_result["selected_mode"]
    details["filling_const"] = fill_result["selected_const"]

    return {"valid": True, "reason": None, "details": details}


def validate_and_adjust_stops(symbol, direction, entry_price, stop_loss, take_profit):
    """Validate and adjust SL/TP to respect the broker's minimum stops level.

    MT5 rejects orders (retcode 10016 "Invalid stops") when SL/TP are too close
    to the current price. Each symbol has a trade_stops_level (in points) that
    defines the minimum distance. This function adjusts SL/TP to comply.

    Returns: {"sl": float, "tp": float, "adjusted": list[str]}
    """
    adjustments = []
    if not _connection["initialized"] or mt5 is None:
        return {"sl": 0, "tp": 0, "adjusted": adjustments}

    with _mt5_lock:
        info = mt5.symbol_info(symbol)

    if info is None:
        return {"sl": stop_loss, "tp": take_profit, "adjusted": adjustments}

    stops_level = getattr(info, "trade_stops_level", 0) or 0
    point = getattr(info, "point", 0.0001) or 0.0001
    min_distance = stops_level * point

    # Add a small buffer (20%) to avoid edge-case rejections due to price movement
    min_distance = min_distance * 1.2

    sl = float(stop_loss) if stop_loss else 0
    tp = float(take_profit) if take_profit else 0
    is_buy = direction.upper() == "BUY"

    if sl > 0:
        if is_buy:
            # BUY: SL must be below entry by at least min_distance
            max_sl = entry_price - min_distance
            if sl > max_sl:
                sl = round(max_sl, 5)
                adjustments.append("SL adjusted to %s (was too close)" % sl)
        else:
            # SELL: SL must be above entry by at least min_distance
            min_sl = entry_price + min_distance
            if sl < min_sl:
                sl = round(min_sl, 5)
                adjustments.append("SL adjusted to %s (was too close)" % sl)

    if tp > 0:
        if is_buy:
            # BUY: TP must be above entry by at least min_distance
            min_tp = entry_price + min_distance
            if tp < min_tp:
                tp = round(min_tp, 5)
                adjustments.append("TP adjusted to %s (was too close)" % tp)
        else:
            # SELL: TP must be below entry by at least min_distance
            max_tp = entry_price - min_distance
            if tp > max_tp:
                tp = round(max_tp, 5)
                adjustments.append("TP adjusted to %s (was too close)" % tp)

    if adjustments:
        log.info("[STOPS_ADJUSTMENT] symbol=%s direction=%s entry=%s stops_level=%s min_dist=%s → sl=%s tp=%s adjustments=%s",
                 symbol, direction, entry_price, stops_level, min_distance, sl, tp, adjustments)

    return {"sl": sl, "tp": tp, "adjusted": adjustments}


def _structured_error(error_code, message, symbol=None, extra=None):
    """Build a consistent error response payload for the frontend."""
    payload = {
        "ok": False,
        "success": False,
        "error_code": error_code,
        "reason": error_code,
        "message": message,
    }
    if symbol:
        payload["symbol"] = symbol
    if extra:
        payload.update(extra)
    return payload


def _reject_if_duplicate_bridge():
    """Guard for every order-mutating route (send_order, send_pending_order,
    close_position, modify_position) — see instance_lock.py's module
    docstring for the real incident this closes. Returns a Flask response
    tuple to return immediately if this process must not touch orders on
    the current MT5 account, or None if it's safe to proceed."""
    if not instance_lock.is_held_by_this_process(os.path.dirname(local_store.DB_PATH), _connection.get("login")):
        return jsonify(_structured_error(
            "DUPLICATE_BRIDGE",
            "Un autre processus pont gère déjà ce compte MT5 — action refusée pour éviter un conflit d'ordres.",
        )), 409
    return None


# ── Real-time monitor thread ─────────────────────────────────────
# Polls MT5 every MONITOR_INTERVAL_MS and pushes changes to all SSE clients.

MONITOR_INTERVAL_MS = 100  # 100ms = ~10 updates/sec, latency < 150ms

_subscribers = []          # list of queue.Queue — one per SSE client
_subscribers_lock = threading.Lock()
_last_snapshot = {"account": None}
_last_history_hash = None
_last_positions_hash = None


def _snapshot_hash(snap):
    """Produce a lightweight hash of the volatile fields."""
    if not snap:
        return ""
    return "|".join(str(snap.get(k, "")) for k in (
        "balance", "equity", "floating_profit", "margin",
        "margin_level", "open_positions_count", "pending_orders_count"
    ))


def _broadcast(event_type, data):
    """Push an event to every connected SSE client."""
    msg = json.dumps({"type": event_type, "data": data, "ts": int(time.time() * 1000)})
    with _subscribers_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)
        # Visible pipeline log
        summary = ""
        if event_type == "account":
            summary = "equity=%s positions=%s floating=%s" % (
                data.get("equity"), data.get("open_positions_count"), data.get("floating_profit"))
        elif event_type == "history":
            summary = "%d trades" % len(data)
        log.info("[BROADCAST] type=%s clients=%d %s", event_type, len(_subscribers), summary)


def _get_recent_trades(from_str=None, to_str=None):
    """Fetch closed-trade history from MT5. Returns list of dicts or None.
    Optionally filter by from/to ISO date strings (timezone-aware)."""
    if not _connection["initialized"] or mt5 is None:
        return None
    with _mt5_lock:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=30)

        # Parse optional date filters (ISO format, may include timezone suffix)
        if from_str:
            try:
                parsed = datetime.fromisoformat(from_str.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                from_date = parsed
            except Exception:
                pass
        if to_str:
            try:
                parsed = datetime.fromisoformat(to_str.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                to_date = parsed
            except Exception:
                pass

        deals = mt5.history_deals_get(from_date, to_date) or []

    positions = {}
    for d in deals:
        pid = getattr(d, "position_id", 0)
        if pid == 0:
            continue
        positions.setdefault(pid, []).append(d)

    trades = []
    for pid, pid_deals in positions.items():
        entry_deals = [d for d in pid_deals if d.entry == mt5.DEAL_ENTRY_IN]
        exit_deals = [d for d in pid_deals if d.entry == mt5.DEAL_ENTRY_OUT]
        entry = entry_deals[0] if entry_deals else None
        exit_deal = exit_deals[-1] if exit_deals else None
        if not entry and not exit_deal:
            continue
        total_profit = sum(d.profit for d in exit_deals) if exit_deals else 0
        if entry:
            direction = "BUY" if entry.type == mt5.DEAL_TYPE_BUY else "SELL"
        elif exit_deal:
            direction = "SELL" if exit_deal.type == mt5.DEAL_TYPE_BUY else "BUY"
        else:
            continue
        ref = entry or exit_deal
        # Origin classification (Task #82) — magic/comment come from the
        # ENTRY deal (the order that actually opened the position); a
        # position with no entry deal in this window (opened before the
        # lookback range) falls back to the exit deal's own magic, which
        # MT5 still carries even for a deal that only closes a position.
        # magic==0 is MT5's own convention for a manually-placed order (the
        # terminal never sets one on its own; only an EA/bot does) — the
        # same 3-way split "Global IA / externe / manuel" already used by
        # AlphaTrade Gold, not something invented here.
        magic = getattr(ref, "magic", 0) or 0
        comment = getattr(ref, "comment", "") or ""
        if magic == GLOBAL_MAGIC_NUMBER:
            origin = "global_ia"
        elif magic == 0:
            origin = "manual"
        else:
            origin = "external"
        trades.append({
            "id": str(pid),
            "ticket_mt5": str(pid),
            "symbol": ref.symbol,
            "direction": direction,
            "status": "closed" if exit_deals else "open",
            "lot": ref.volume,
            "entry_price": entry.price if entry else None,
            "exit_price": exit_deal.price if exit_deal else None,
            "pnl": round(total_profit, 2),
            "opened_at": datetime.fromtimestamp(entry.time).isoformat() if entry else None,
            "closed_at": datetime.fromtimestamp(exit_deal.time).isoformat() if exit_deal else None,
            "magic": magic,
            "comment": comment,
            "origin": origin,
        })
    trades.sort(key=lambda t: t.get("closed_at") or t.get("opened_at") or "", reverse=True)
    return trades


def _monitor_loop():
    """Background thread: poll MT5, detect changes, push to SSE clients.

    Features:
      - Account snapshot pushed only when volatile fields change
      - History pushed only when trade count or latest trade changes
      - MT5 reconnection attempted after consecutive failures
    """
    global _last_history_hash
    global _last_positions_hash
    log.info("Monitor thread started (interval=%dms)", MONITOR_INTERVAL_MS)
    fail_count = 0
    history_counter = 0
    _last_positions_count = None

    while _connection["initialized"]:
        try:
            snap = get_account_snapshot()
            if snap:
                fail_count = 0
                new_hash = _snapshot_hash(snap)
                if new_hash != _snapshot_hash(_last_snapshot.get("account")):
                    _last_snapshot["account"] = snap
                    _broadcast("account", snap)
                    log.info("[MONITOR] Pushed account update: equity=%s positions=%s floating=%s",
                             snap.get("equity"), snap.get("open_positions_count"), snap.get("floating_profit"))

                    # If position count changed (trade opened/closed), push history immediately
                    current_positions = snap.get("open_positions_count", 0)
                    if _last_positions_count is not None and current_positions != _last_positions_count:
                        log.info("[MONITOR] Position count changed %s→%s — pushing history NOW",
                                 _last_positions_count, current_positions)
                        trades = _get_recent_trades()
                        if trades is not None:
                            h_hash = str(len(trades)) + ":" + (trades[0].get("id", "") if trades else "")
                            if h_hash != _last_history_hash:
                                _last_history_hash = h_hash
                                _broadcast("history", trades)
                    _last_positions_count = current_positions
            else:
                fail_count += 1
                if fail_count >= 10:
                    log.warning("MT5 unresponsive (%d failures) — attempting reconnection", fail_count)
                    try:
                        mt5.shutdown()
                    except Exception:
                        pass
                    if mt5_auto_connect():
                        fail_count = 0
                        log.info("MT5 reconnected successfully — resuming monitor")
                    else:
                        _connection["initialized"] = False
                        log.error("MT5 reconnection failed — monitor stopping")
                        break

            # History check every ~0.5s (5 cycles * 100ms)
            history_counter += 1
            if history_counter >= 5:
                history_counter = 0
                trades = _get_recent_trades()
                if trades is not None:
                    h_hash = str(len(trades)) + ":" + (trades[0].get("id", "") if trades else "")
                    if h_hash != _last_history_hash:
                        _last_history_hash = h_hash
                        _broadcast("history", trades)
                        log.info("[MONITOR] Pushed history update: %d trades", len(trades))

            # Positions check every cycle — push when positions change (open/close/PnL)
            positions = get_open_positions()
            if positions is not None:
                p_hash = str(len(positions)) + ":" + "|".join(
                    p["ticket"] + ":" + str(p["profit"]) for p in positions
                )
                if p_hash != _last_positions_hash:
                    _last_positions_hash = p_hash
                    _broadcast("positions", positions)
                    log.info("[MONITOR] Pushed positions update: %d open", len(positions))

        except Exception as e:
            log.warning("Monitor error: %s", e)

        time.sleep(MONITOR_INTERVAL_MS / 1000.0)

    log.info("Monitor thread stopped (MT5 disconnected)")


_monitor_thread = None


def start_monitor():
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
    _monitor_thread.start()


# ── Position Manager loop (Professional Position Manager, 2026-08-06) ────
# Boucle 1 of the transformation plan's 3-loop architecture: protection of
# already-open positions, running on its own ~1s cadence, completely
# independent of the analysis/decision cycle (Boucle 2, cadenced by the
# trading profile — 30s to 600s). Before this, break-even/trailing/TP only
# ran once per analysis cycle, meaning a Swing-profile position could go
# unprotected for up to 10 minutes after crossing its trigger — exactly the
# gap the professional audit flagged. This loop is what makes that gap real
# instead of theoretical: position protection no longer depends on how
# often the app happens to be scanning for new opportunities.
POSITION_MANAGER_INTERVAL_SEC = 1.0
_position_manager_thread = None


def _position_manager_loop():
    log.info("Position Manager thread started (interval=%.1fs)", POSITION_MANAGER_INTERVAL_SEC)
    db_dir = os.path.dirname(local_store.DB_PATH)
    while _connection["initialized"]:
        try:
            # Refresh this process's ownership of the account lock every
            # cycle — see instance_lock.py. Cheap (one small file write);
            # keeps a crashed process's lock from blocking a legitimate
            # restart for more than LOCK_STALE_SECONDS.
            instance_lock.heartbeat(db_dir, _connection["login"])
            params_list = local_store.list_entities("Parameter", sort="-created_date", limit=1)
            params = params_list[0] if params_list else {}
            snap = get_account_snapshot()
            equity = snap.get("equity") if snap else None
            result = local_functions.manage_open_positions(
                get_open_positions, modify_position_direct, params,
                close_fn=close_position_direct, equity=equity,
            )
            if result.get("actions"):
                log.info("[POSITION_MANAGER] %s", "; ".join(
                    f"{a['event']} {a['symbol']} (ticket {a['ticket']})" for a in result["actions"]
                ))
        except Exception as e:
            log.warning("Position Manager error: %s", e)
        time.sleep(POSITION_MANAGER_INTERVAL_SEC)
    log.info("Position Manager thread stopped (MT5 disconnected)")


def start_position_manager():
    global _position_manager_thread
    # Instance lock guard (2026-08-07) — see instance_lock.py's module
    # docstring for the real incident this prevents. A second bridge
    # process connected to the same MT5 account must never run its own
    # Position Manager alongside the one that already holds the lock.
    if not _connection.get("instance_lock_acquired"):
        log.error("Position Manager NOT started — another bridge process already holds "
                   "the instance lock for this MT5 account (see DUPLICATE BRIDGE DETECTED above).")
        return
    if _position_manager_thread and _position_manager_thread.is_alive():
        return
    _position_manager_thread = threading.Thread(target=_position_manager_loop, daemon=True)
    _position_manager_thread.start()


# ── Asset Validation (Auto Optimization Lab, 2026-08-07) ──────────────
# Runs fusion_backtest.py automatically — on adding an asset to the active
# watchlist, and periodically afterward — instead of requiring someone to
# launch it by hand. One worker processes one symbol at a time (each real
# validation takes minutes; queuing avoids piling up concurrent MT5-heavy
# backtests). Never removes an asset itself — see asset_validation.py's
# module docstring for why.
_asset_validation_queue = queue.Queue()
ASSET_REVALIDATION_CHECK_INTERVAL_SEC = 3600  # how often to check what's due, not how often anything actually re-runs (see asset_validation.ASSET_REVALIDATION_INTERVAL_DAYS)


def _enqueue_asset_validation(symbol):
    log.info("[ASSET_VALIDATION] %s mis en file pour validation automatique", symbol)
    _asset_validation_queue.put(symbol)


def _asset_validation_worker():
    while True:
        symbol = _asset_validation_queue.get()
        try:
            params_list = local_store.list_entities("Parameter", sort="-created_date", limit=1)
            params = params_list[0] if params_list else {}
            snap = get_account_snapshot()
            capital = (snap.get("equity") if snap else None) or params.get("capital") or 1000
            risk_percent = params.get("max_risk_percent") or 1
            log.info("[ASSET_VALIDATION] Démarrage de la validation de %s (capital=%.2f, risk=%.2f%%)...", symbol, capital, risk_percent)
            result = asset_validation.validate_asset(symbol, fetch_candles_direct, capital=capital, risk_percent=risk_percent)
            log.info("[ASSET_VALIDATION] %s -> %s", symbol, "passed" if result.get("passed") else result.get("error") or "failed")
        except Exception as e:
            log.warning("[ASSET_VALIDATION] Échec inattendu pour %s: %s", symbol, e)
        finally:
            _asset_validation_queue.task_done()


def start_asset_validation_worker():
    threading.Thread(target=_asset_validation_worker, daemon=True).start()


def _asset_revalidation_scheduler_loop():
    """Checks hourly which active watchlist assets haven't been validated
    in ASSET_REVALIDATION_INTERVAL_DAYS and enqueues them — the actual
    heavy work stays in the worker above, one at a time."""
    while True:
        try:
            if _connection["initialized"]:
                for symbol in asset_validation.assets_due_for_revalidation():
                    _enqueue_asset_validation(symbol)
        except Exception as e:
            log.warning("[ASSET_VALIDATION] scheduler error: %s", e)
        time.sleep(ASSET_REVALIDATION_CHECK_INTERVAL_SEC)


def start_asset_revalidation_scheduler():
    threading.Thread(target=_asset_revalidation_scheduler_loop, daemon=True).start()

# ── SSE stream endpoint ──────────────────────────────────────────

@app.route("/stream", methods=["GET"])
def stream():
    """Server-Sent Events stream — pushes account/position changes in real time.

    The browser connects with: new EventSource('/stream?key=API_KEY')
    Each event: data: {"type": "account", "data": {...}, "ts": 1234567890}
    """
    q = queue.Queue(maxsize=100)
    with _subscribers_lock:
        _subscribers.append(q)
        log.info("[SSE] New subscriber connected — total clients: %d", len(_subscribers))

    # Send initial snapshot immediately so the client doesn't have to poll
    initial = get_account_snapshot()
    if initial:
        log.info("[SSE] Sending initial account snapshot to new subscriber")
        try:
            q.put_nowait(json.dumps({"type": "account", "data": initial, "ts": int(time.time() * 1000)}))
        except queue.Full:
            pass

    # Send initial positions so the client shows open orders immediately
    initial_positions = get_open_positions()
    if initial_positions is not None:
        try:
            q.put_nowait(json.dumps({"type": "positions", "data": initial_positions, "ts": int(time.time() * 1000)}))
        except queue.Full:
            pass

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=30)  # 30s timeout → sends keepalive
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    # Keepalive comment — prevents proxy/browser timeout
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _subscribers_lock:
                if q in _subscribers:
                    _subscribers.remove(q)
                    log.info("[SSE] Subscriber disconnected — remaining clients: %d", len(_subscribers))

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"  # Disable Nginx buffering
    resp.headers["Connection"] = "keep-alive"
    return resp

# ── REST API endpoints ───────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "service": "alphatg_bridge",
        "mt5_connected": _connection["initialized"],
        "account_type": _connection["account_type"],
        "sse_enabled": True,
        "monitor_interval_ms": MONITOR_INTERVAL_MS,
    })


@app.route("/hyperliquid/intelligence", methods=["GET"])
def hyperliquid_intelligence():
    """Real crypto order-book pressure (OBI), funding rate and open
    interest from Hyperliquid's public API — OBSERVATION ONLY. Does not
    require MT5 to be connected (independent data source). Never consumed
    by market_brain.py or any decision path; see hyperliquid_connector.py
    for why this stays observation-only until validated."""
    coins_param = request.args.get("coins")
    coins = [c.strip().upper() for c in coins_param.split(",")] if coins_param else None
    return jsonify(hyperliquid_connector.get_crypto_intelligence(coins))


@app.route("/global-intelligence", methods=["GET"])
def global_intelligence():
    """Aggregated market_regime/crypto_pressure/liquidity_state/
    volatility_state/crypto_intelligence_score snapshot — OBSERVATION
    ONLY, see global_market_intelligence.py. Not consumed by
    market_brain.py."""
    coins_param = request.args.get("coins")
    coins = [c.strip().upper() for c in coins_param.split(",")] if coins_param else None
    macro = global_market_intelligence.get_macro_snapshot(fetch_candles_direct) if _connection["initialized"] else None
    return jsonify(global_market_intelligence.get_global_market_intelligence(coins, macro=macro))


@app.route("/global-intelligence/history", methods=["GET"])
def global_intelligence_history():
    """The observation journal itself — snapshots recorded automatically
    every 10 minutes (see the collector thread in __main__), for reviewing
    whether this data would actually have helped before any activation."""
    limit = int(request.args.get("limit", 100))
    snapshots = local_store.list_entities("CryptoIntelSnapshot", sort="-created_date", limit=limit)
    return jsonify({"ok": True, "count": len(snapshots), "snapshots": snapshots})


@app.route("/account", methods=["GET"])
@app.route("/sync", methods=["GET"])
def sync():
    snap = get_account_snapshot()
    if snap is None:
        if not _connection["initialized"]:
            return jsonify({"ok": False, "error": "MT5 not connected"}), 400
        return jsonify({"ok": False, "error": "Failed to get account info"}), 500
    return jsonify(snap)


@app.route("/order", methods=["POST"])
@app.route("/send_order", methods=["POST"])
def send_order():
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400
    rejection = _reject_if_duplicate_bridge()
    if rejection:
        return rejection

    data = request.json or {}
    symbol = data.get("symbol")
    direction = data.get("direction", "BUY")
    lot = float(data.get("lot", 0.01))
    stop_loss = float(data.get("stop_loss", 0))
    take_profit_1 = float(data.get("take_profit_1", 0))

    if not symbol:
        return jsonify(_structured_error("SYMBOL_NOT_FOUND", "symbol required")), 400

    # ── Pre-order validation checklist ──
    validation = pre_order_validation(symbol, lot, direction)
    if not validation["valid"]:
        log.warning("[PRE_ORDER_VALIDATION] FAILED symbol=%s reason=%s", symbol, validation["reason"])
        return jsonify(_structured_error(
            validation["reason"],
            "Order rejected at validation stage: " + validation["reason"],
            symbol=symbol,
            extra={"stage": "PRE_ORDER_VALIDATION", "details": validation.get("details", {})},
        )), 400

    details = validation["details"]
    resolved = details["resolved_symbol"]
    normalized_lot = details["normalized_lot"]
    filling_const_val = details.get("filling_const", mt5.ORDER_FILLING_RETURN)
    price = details["tick_price"]

    # Simulation mode: validated as if real (real symbol/price/lot/market
    # hours above), but never reaches mt5.order_send — no real order, no
    # real fill. Checked here, not just in the frontend, so it can't be
    # bypassed by any caller of this endpoint.
    if local_functions.is_simulation_mode():
        sim_ticket = "SIM-" + str(int(time.time() * 1000))
        log.info("[ORDER_SIMULATED] %s %s %s @ %s (resolved=%s, lot=%s) — execution_mode=simulation, no real MT5 order sent",
                 direction, symbol, lot, price, resolved, normalized_lot)
        return jsonify({
            "ok": True,
            "simulated": True,
            "ticket": sim_ticket,
            "executed_price": price,
            "resolved_symbol": resolved,
            "lot": normalized_lot,
            "order_response": {"status": "simulated", "ticket": sim_ticket, "executed_price": price},
        })

    trade_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL

    # ── Validate & adjust SL/TP to respect broker's minimum stops level ──
    # Prevents retcode 10016 "Invalid stops" — SL/TP too close to entry price.
    stops = validate_and_adjust_stops(resolved, direction, price, stop_loss, take_profit_1)
    adjusted_sl = stops["sl"]
    adjusted_tp = stops["tp"]

    log.info("[ORDER_SEND] %s %s %s (resolved=%s, lot=%s, filling=%s, price=%s, sl=%s, tp=%s, stops_adjusted=%s)",
             direction, symbol, lot, resolved, normalized_lot, details.get("filling_mode"), price,
             adjusted_sl, adjusted_tp, len(stops["adjusted"]))

    request_data = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": resolved,
        "volume": normalized_lot,
        "type": trade_type,
        "price": price,
        "sl": adjusted_sl,
        "tp": adjusted_tp,
        "deviation": 20,
        "magic": GLOBAL_MAGIC_NUMBER,
        "comment": "AT Global",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_const_val,
    }

    # ── Send order with auto-retry on filling mode rejection (retcode 10030) ──
    # Some brokers don't set filling_mode bitmask correctly, so the first
    # attempt may fail. We retry with alternate filling modes automatically.
    filling_modes_to_try = [filling_const_val]
    for alt in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
        if alt != filling_const_val and alt not in filling_modes_to_try:
            filling_modes_to_try.append(alt)

    result = None
    for idx, fill_const in enumerate(filling_modes_to_try):
        request_data["type_filling"] = fill_const
        result = mt5.order_send(request_data)

        if result is None:
            return jsonify(_structured_error("ORDER_SEND_FAILED", "order_send returned None", symbol=resolved)), 500

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("[ORDER_OK] %s %s %s @ %s, ticket=%s (filling_mode_attempt=%d)", direction, lot, resolved, price, result.order, idx + 1)
            break

        # If retcode is NOT 10030 (filling mode), stop retrying — it's a different error
        if result.retcode != 10030:
            break

        log.warning("[ORDER_RETRY] retcode=10030 (filling mode %d/%d rejected), trying next mode", idx + 1, len(filling_modes_to_try))

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        # Decode known retcodes into structured error codes
        retcode = result.retcode if result else 0
        if retcode == 10030:
            err_code = "FILLING_MODE_UNSUPPORTED"
        elif retcode == 10014:
            err_code = "INVALID_VOLUME"
        elif retcode == 10015:
            err_code = "MARKET_CLOSED"
        elif retcode == 10016:
            err_code = "INVALID_STOPS"
        elif retcode == 10013:
            err_code = "INVALID_REQUEST"
        elif retcode == 10018:
            err_code = "INSUFFICIENT_FUNDS"
        elif retcode == 10027:
            err_code = "AUTOTRADING_DISABLED"
        elif retcode == 10006 or retcode == 10021:
            err_code = "NO_PRICE"
        else:
            err_code = "ORDER_REJECTED"
        return jsonify(_structured_error(
            err_code,
            "Order failed: retcode=" + str(retcode) + ", comment=" + str(result.comment if result else "N/A"),
            symbol=resolved,
            extra={"retcode": retcode, "comment": str(result.comment if result else ""), "stage": "MT5_EXECUTION"},
        )), 400

    return jsonify({
        "ok": True,
        "ticket": str(result.order),
        "executed_price": result.price,
        "resolved_symbol": resolved,
        "lot": normalized_lot,
        "order_response": {
            "status": "executed",
            "ticket": str(result.order),
            "executed_price": result.price,
        },
    })


@app.route("/send_pending_order", methods=["POST"])
def send_pending_order():
    """Places a pending order (BUY/SELL LIMIT/STOP) instead of a market order.
    Lets the AI plan an entry level in advance instead of only reacting to
    whatever the price is doing right now."""
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400
    rejection = _reject_if_duplicate_bridge()
    if rejection:
        return rejection

    data = request.json or {}
    symbol = data.get("symbol")
    direction = (data.get("direction") or "BUY").upper()
    lot = float(data.get("lot", 0.01))
    stop_loss = float(data.get("stop_loss", 0))
    take_profit = float(data.get("take_profit_1", data.get("take_profit", 0)))
    expiration = data.get("expiration")  # optional ISO datetime string; GTC if absent

    if not symbol:
        return jsonify(_structured_error("SYMBOL_NOT_FOUND", "symbol required")), 400
    if direction not in ("BUY", "SELL"):
        return jsonify(_structured_error("INVALID_REQUEST", "direction must be BUY or SELL")), 400
    try:
        entry_price = float(data.get("entry_price"))
    except (TypeError, ValueError):
        return jsonify(_structured_error("INVALID_REQUEST", "entry_price is required for a pending order")), 400

    validation = pre_order_validation(symbol, lot, direction)
    if not validation["valid"]:
        log.warning("[PRE_ORDER_VALIDATION] FAILED (pending) symbol=%s reason=%s", symbol, validation["reason"])
        return jsonify(_structured_error(
            validation["reason"],
            "Pending order rejected at validation stage: " + validation["reason"],
            symbol=symbol,
            extra={"stage": "PRE_ORDER_VALIDATION", "details": validation.get("details", {})},
        )), 400

    details = validation["details"]
    resolved = details["resolved_symbol"]
    normalized_lot = details["normalized_lot"]
    filling_const_val = details.get("filling_const", mt5.ORDER_FILLING_RETURN)
    current_price = details["tick_price"]

    with _mt5_lock:
        info = mt5.symbol_info(resolved)
    point = getattr(info, "point", 0.0001) or 0.0001
    stops_level = getattr(info, "trade_stops_level", 0) or 0
    min_distance = stops_level * point * 1.2  # same 20% safety buffer as market-order SL/TP

    distance = abs(entry_price - current_price)
    if distance < min_distance:
        return jsonify(_structured_error(
            "TOO_CLOSE_TO_MARKET",
            "entry_price (" + str(entry_price) + ") is too close to the current price (" + str(current_price) +
            ") for a pending order — needs at least " + str(round(min_distance, 5)) +
            " distance. Use an immediate market order instead.",
            symbol=resolved,
            extra={"current_price": current_price, "min_distance": min_distance},
        )), 400

    # BUY: entry below current price = LIMIT (waiting for a pullback down),
    # entry above = STOP (waiting for a breakout up). SELL is the mirror.
    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if entry_price < current_price else mt5.ORDER_TYPE_BUY_STOP
        pending_kind = "BUY_LIMIT" if entry_price < current_price else "BUY_STOP"
    else:
        order_type = mt5.ORDER_TYPE_SELL_LIMIT if entry_price > current_price else mt5.ORDER_TYPE_SELL_STOP
        pending_kind = "SELL_LIMIT" if entry_price > current_price else "SELL_STOP"

    # Same simulation gate as /send_order — see there for why this is
    # enforced here rather than trusted to the frontend.
    if local_functions.is_simulation_mode():
        sim_ticket = "SIM-" + str(int(time.time() * 1000))
        log.info("[PENDING_ORDER_SIMULATED] %s %s %s @ %s (resolved=%s, lot=%s) — execution_mode=simulation, no real MT5 order sent",
                 pending_kind, symbol, lot, entry_price, resolved, normalized_lot)
        return jsonify({
            "ok": True,
            "simulated": True,
            "ticket": sim_ticket,
            "order_type": pending_kind,
            "resolved_symbol": resolved,
            "lot": normalized_lot,
            "entry_price": entry_price,
        })

    stops = validate_and_adjust_stops(resolved, direction, entry_price, stop_loss, take_profit)

    request_data = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": resolved,
        "volume": normalized_lot,
        "type": order_type,
        "price": entry_price,
        "sl": stops["sl"],
        "tp": stops["tp"],
        "deviation": 20,
        "magic": GLOBAL_MAGIC_NUMBER,
        "comment": "AT Global",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_const_val,
    }

    if expiration:
        try:
            exp_dt = datetime.fromisoformat(str(expiration).replace("Z", "+00:00"))
            request_data["type_time"] = mt5.ORDER_TIME_SPECIFIED
            request_data["expiration"] = int(exp_dt.timestamp())
        except ValueError:
            log.warning("[PENDING_ORDER] Malformed expiration '%s' — falling back to GTC", expiration)

    log.info("[PENDING_ORDER_SEND] %s %s %s @ %s (current=%s, resolved=%s, lot=%s)",
             pending_kind, symbol, lot, entry_price, current_price, resolved, normalized_lot)

    filling_modes_to_try = [filling_const_val]
    for alt in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
        if alt != filling_const_val and alt not in filling_modes_to_try:
            filling_modes_to_try.append(alt)

    result = None
    for idx, fill_const in enumerate(filling_modes_to_try):
        request_data["type_filling"] = fill_const
        result = mt5.order_send(request_data)
        if result is None:
            return jsonify(_structured_error("ORDER_SEND_FAILED", "order_send returned None", symbol=resolved)), 500
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("[PENDING_ORDER_OK] %s %s @ %s, ticket=%s (filling_mode_attempt=%d)", pending_kind, resolved, entry_price, result.order, idx + 1)
            break
        if result.retcode != 10030:
            break
        log.warning("[PENDING_ORDER_RETRY] retcode=10030 (filling mode %d/%d rejected), trying next mode", idx + 1, len(filling_modes_to_try))

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else 0
        if retcode == 10030:
            err_code = "FILLING_MODE_UNSUPPORTED"
        elif retcode == 10014:
            err_code = "INVALID_VOLUME"
        elif retcode == 10015 or retcode == 10018:
            # MT5 retcode reference: 10018 is TRADE_RETCODE_MARKET_CLOSED, not
            # insufficient funds (that's 10019) — a mislabel already present in
            # the market-order endpoint above, corrected here.
            err_code = "MARKET_CLOSED"
        elif retcode == 10016:
            err_code = "INVALID_STOPS"
        elif retcode == 10013:
            err_code = "INVALID_REQUEST"
        elif retcode == 10019:
            err_code = "INSUFFICIENT_FUNDS"
        elif retcode == 10027:
            err_code = "AUTOTRADING_DISABLED"
        elif retcode == 10006 or retcode == 10021:
            err_code = "NO_PRICE"
        else:
            err_code = "ORDER_REJECTED"
        return jsonify(_structured_error(
            err_code,
            "Pending order failed: retcode=" + str(retcode) + ", comment=" + str(result.comment if result else "N/A"),
            symbol=resolved,
            extra={"retcode": retcode, "comment": str(result.comment if result else ""), "stage": "MT5_EXECUTION"},
        )), 400

    return jsonify({
        "ok": True,
        "ticket": str(result.order),
        "order_type": pending_kind,
        "resolved_symbol": resolved,
        "lot": normalized_lot,
        "entry_price": entry_price,
    })


@app.route("/pending_orders", methods=["GET"])
def get_pending_orders_endpoint():
    if not _connection["initialized"]:
        return jsonify({"ok": False, "error": "MT5 not connected"}), 400

    with _mt5_lock:
        orders = mt5.orders_get() or []

    type_names = {
        mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
        mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
        mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
        mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
    }
    result = [
        {
            "ticket": str(o.ticket),
            "symbol": o.symbol,
            "type": type_names.get(o.type, str(o.type)),
            "lot": o.volume_current,
            "price": o.price_open,
            "stop_loss": o.sl,
            "take_profit": o.tp,
            "placed_at": datetime.fromtimestamp(o.time_setup).isoformat() if o.time_setup else None,
            "comment": o.comment,
            "magic": o.magic,
        }
        for o in orders
    ]
    return jsonify({"ok": True, "orders": result})


@app.route("/cancel_order", methods=["POST"])
def cancel_pending_order():
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400

    data = request.json or {}
    try:
        ticket = int(data.get("ticket", 0))
    except (TypeError, ValueError):
        ticket = 0
    if not ticket:
        return jsonify(_structured_error("INVALID_REQUEST", "ticket is required")), 400

    request_data = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
    result = mt5.order_send(request_data)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else 0
        return jsonify(_structured_error(
            "CANCEL_FAILED",
            "Cancel failed: retcode=" + str(retcode) + ", comment=" + str(result.comment if result else "N/A"),
            extra={"retcode": retcode, "ticket": ticket},
        )), 400

    log.info("[PENDING_ORDER_CANCELLED] ticket=%s", ticket)
    return jsonify({"ok": True, "ticket": str(ticket)})


@app.route("/positions", methods=["GET"])
def get_positions_endpoint():
    positions = get_open_positions()
    if positions is None:
        if not _connection["initialized"]:
            return jsonify({"ok": False, "error": "MT5 not connected"}), 400
        return jsonify({"ok": False, "error": "Failed to get positions"}), 500
    return jsonify({"ok": True, "positions": positions})


def fetch_symbols_direct():
    """In-process symbol list fetch — same MT5 path as /symbols, callable
    directly from route handlers without an HTTP round trip to itself."""
    if not _connection["initialized"]:
        return None
    with _mt5_lock:
        symbols = mt5.symbols_get() or []
    return [s.name for s in symbols]


@app.route("/symbols", methods=["GET"])
def get_symbols():
    symbol_names = fetch_symbols_direct()
    if symbol_names is None:
        return jsonify({"ok": False, "error": "MT5 not connected"}), 400
    return jsonify({"ok": True, "symbols": symbol_names})


_MT5_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}


def fetch_candles_direct(symbol, timeframe, count=300, from_str=None, to_str=None):
    """In-process candle fetch — same MT5 path as the /rates endpoint, but
    callable directly from route handlers (e.g. marketBrain) without an
    HTTP round trip to itself. Returns (candles, resolved_symbol, error).
    """
    if not _connection["initialized"]:
        return None, None, "MT5 not connected"

    tf_attr = _MT5_TIMEFRAMES.get(timeframe.upper())
    if tf_attr is None:
        return None, None, "Unsupported timeframe: " + timeframe
    tf_const = getattr(mt5, tf_attr)

    mapping = resolve_symbol(symbol.upper())
    resolved = mapping.get("resolved")
    if not mapping.get("found") or not resolved:
        return None, None, "Symbol not found: " + symbol

    if from_str or to_str:
        try:
            date_from = datetime.fromisoformat(from_str.replace("Z", "+00:00")) if from_str else datetime(2000, 1, 1)
            date_to = datetime.fromisoformat(to_str.replace("Z", "+00:00")) if to_str else datetime.utcnow()
        except ValueError:
            return None, None, "from/to must be ISO date strings"
        with _mt5_lock:
            rates = mt5.copy_rates_range(resolved, tf_const, date_from, date_to)
    else:
        with _mt5_lock:
            rates = mt5.copy_rates_from_pos(resolved, tf_const, 0, min(max(count, 1), 1000))

    if rates is None or len(rates) == 0:
        return None, resolved, "No rate data returned for " + resolved

    candles = [
        {
            "time": datetime.utcfromtimestamp(int(r["time"])).isoformat() + "Z",
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "spread": int(r["spread"]),
        }
        for r in rates
    ]
    return candles, resolved, None


@app.route("/rates", methods=["GET"])
def get_rates():
    """Real OHLCV candles from MT5 — the actual price data behind the
    analysis engines. No candles here means no real technical analysis,
    only a text description a model has to guess at."""
    symbol = (request.args.get("symbol") or "").strip().upper()
    timeframe = (request.args.get("timeframe") or "H1").strip().upper()
    from_str = request.args.get("from")
    to_str = request.args.get("to")

    if not symbol:
        return jsonify(_structured_error("INVALID_REQUEST", "symbol is required")), 400
    if timeframe not in _MT5_TIMEFRAMES:
        return jsonify(_structured_error(
            "INVALID_REQUEST",
            "Unsupported timeframe: " + timeframe,
            extra={"supported": list(_MT5_TIMEFRAMES.keys())},
        )), 400

    try:
        count = min(max(int(request.args.get("count", 300)), 1), 1000)
    except ValueError:
        return jsonify(_structured_error("INVALID_REQUEST", "count must be an integer")), 400

    candles, resolved, error = fetch_candles_direct(symbol, timeframe, count=count, from_str=from_str, to_str=to_str)
    if error:
        if error == "MT5 not connected":
            return jsonify(_structured_error("CONNECTION_LOST", error)), 400
        if error.startswith("Symbol not found"):
            return jsonify(_structured_error("SYMBOL_NOT_FOUND", error, symbol=symbol)), 404
        return jsonify(_structured_error("NO_DATA", error, symbol=resolved)), 400

    return jsonify({
        "ok": True,
        "symbol": resolved,
        "requested_symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
    })


@app.route("/history", methods=["GET"])
def get_history():
    if not _connection["initialized"]:
        return jsonify({"ok": False, "error": "MT5 not connected"}), 400
    from_str = request.args.get("from")
    to_str = request.args.get("to")
    trades = _get_recent_trades(from_str, to_str)
    if trades is None:
        return jsonify({"ok": False, "error": "Failed to get history"}), 500
    return jsonify({"ok": True, "trades": trades})


def close_position_direct(ticket, volume=None):
    """In-process position close, full or partial — TRADE_ACTION_DEAL in the
    opposite direction against the position ticket. Shared by the /close_position
    endpoint and the Position Manager loop (TP1/TP2 partial take-profit,
    emergency close on an unprotected position).

    volume=None closes the entire remaining position. A requested partial
    volume is rounded to the symbol's real lot step, and if what would be
    LEFT over falls below the broker's minimum tradeable size, closes
    everything instead of stranding an un-tradeable sliver — the caller
    finds out via the returned closed_volume, never silently wrong."""
    if not _connection["initialized"]:
        return {"ok": False, "error": "MT5 not connected"}

    with _mt5_lock:
        positions = mt5.positions_get(ticket=ticket) or []
    if not positions:
        return {"ok": False, "error": "Position not found: " + str(ticket)}

    pos = positions[0]

    if volume is not None:
        with _mt5_lock:
            info = mt5.symbol_info(pos.symbol)
        vol_step = getattr(info, "volume_step", 0.01) if info else 0.01
        vol_min = getattr(info, "volume_min", 0.01) if info else 0.01
        close_volume = round(round(float(volume) / vol_step) * vol_step, 4)
        remainder = round(pos.volume - close_volume, 4)
        if close_volume < vol_min or remainder < vol_min:
            close_volume = pos.volume
    else:
        close_volume = pos.volume

    trade_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

    fill_result = get_supported_filling_mode(pos.symbol)
    filling_const_val = fill_result.get("selected_const", mt5.ORDER_FILLING_RETURN)

    with _mt5_lock:
        tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return {"ok": False, "error": "No price available for " + pos.symbol}

    price = tick.bid if trade_type == mt5.ORDER_TYPE_SELL else tick.ask

    request_data = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": close_volume,
        "type": trade_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": GLOBAL_MAGIC_NUMBER,
        "comment": "AT Global — Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_const_val,
    }

    result = mt5.order_send(request_data)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else 0
        return {"ok": False, "error": "retcode=" + str(retcode) + " " + str(getattr(result, "comment", ""))}

    log.info("[CLOSE_OK] ticket=%s symbol=%s volume=%s closed at %s", ticket, pos.symbol, close_volume, price)
    return {"ok": True, "ticket": str(result.order), "closed_volume": close_volume, "price": price}


@app.route("/close_position", methods=["POST"])
def close_position():
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400
    rejection = _reject_if_duplicate_bridge()
    if rejection:
        return rejection

    data = request.json or {}
    ticket = int(data.get("ticket", 0))

    with _mt5_lock:
        exists = mt5.positions_get(ticket=ticket)
    if not exists:
        return jsonify(_structured_error("POSITION_NOT_FOUND", "Position not found: " + str(ticket))), 404

    symbol = exists[0].symbol
    result = close_position_direct(ticket, data.get("volume"))
    if not result["ok"]:
        return jsonify(_structured_error("CLOSE_FAILED", result["error"], symbol=symbol)), 400
    return jsonify(result)


def modify_position_direct(ticket, stop_loss=None, take_profit=None):
    """In-process SL/TP change (TRADE_ACTION_SLTP) — shared by the HTTP
    endpoint and the position-management engine (manage_open_positions),
    which calls this directly without a round trip to itself."""
    if not _connection["initialized"]:
        return {"ok": False, "error": "MT5 not connected"}

    with _mt5_lock:
        positions = mt5.positions_get(ticket=ticket) or []
    if not positions:
        return {"ok": False, "error": "Position not found: " + str(ticket)}

    pos = positions[0]
    new_sl = float(stop_loss) if stop_loss is not None else pos.sl
    new_tp = float(take_profit) if take_profit is not None else pos.tp

    request_data = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": pos.symbol,
        "position": ticket,
        "sl": new_sl,
        "tp": new_tp,
        "magic": GLOBAL_MAGIC_NUMBER,
    }
    result = mt5.order_send(request_data)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else 0
        return {"ok": False, "error": "retcode=" + str(retcode) + " " + str(getattr(result, "comment", ""))}

    log.info("[MODIFY_OK] ticket=%s symbol=%s new_sl=%s new_tp=%s", ticket, pos.symbol, new_sl, new_tp)
    return {"ok": True, "ticket": str(ticket), "stop_loss": new_sl, "take_profit": new_tp}


@app.route("/modify_position", methods=["POST"])
def modify_position():
    """Changes SL/TP on an already-open position — used manually or by the
    real position-management engine to move a position to break-even or
    trail its stop."""
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400
    rejection = _reject_if_duplicate_bridge()
    if rejection:
        return rejection

    data = request.json or {}
    ticket = int(data.get("ticket", 0))
    result = modify_position_direct(ticket, data.get("stop_loss"), data.get("take_profit"))
    if not result["ok"]:
        return jsonify(_structured_error("MODIFY_FAILED", result["error"])), 400
    return jsonify(result)


# ── Local entity store (replaces Base44 database) ─────────────────
LOCAL_USER = {
    "id": "local",
    "email": "local@alphatrade.global",
    "full_name": "AlphaTrade Global",
    "role": "admin",
    "is_admin": True,
}


@app.route("/auth/me", methods=["GET"])
def auth_me():
    return jsonify(LOCAL_USER)


@app.route("/auth/login", methods=["POST"])
def auth_login():
    body = request.json or {}
    payload, status = local_functions.auth_login(body, LOCAL_USER)
    return jsonify(payload), status


@app.route("/auth/reset_password", methods=["POST"])
def auth_reset_password():
    body = request.json or {}
    payload, status = local_functions.auth_reset_password(body)
    return jsonify(payload), status


@app.route("/entities/<entity_type>", methods=["GET", "POST"])
def entities_collection(entity_type):
    if request.method == "POST":
        data = request.json or {}
        record = local_store.create_entity(entity_type, data)
        # Auto Optimization Lab (2026-08-07): adding a symbol to the active
        # watchlist queues a real fusion_backtest validation automatically —
        # no more "add it and hope", see asset_validation.py.
        if entity_type == "Asset" and record.get("symbol"):
            _enqueue_asset_validation(record["symbol"])
        return jsonify(record)

    query = None
    raw_filter = request.args.get("filter")
    if raw_filter:
        try:
            query = json.loads(raw_filter)
        except (TypeError, ValueError):
            return jsonify({"error": "filter invalide (JSON attendu)"}), 400

    sort = request.args.get("sort")
    limit_raw = request.args.get("limit")
    limit = int(limit_raw) if limit_raw and limit_raw.isdigit() else None

    return jsonify(local_store.list_entities(entity_type, query=query, sort=sort, limit=limit))


@app.route("/entities/<entity_type>/<entity_id>", methods=["GET", "PATCH", "DELETE"])
def entities_item(entity_type, entity_id):
    if request.method == "GET":
        record = local_store.get_entity(entity_type, entity_id)
        if record is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(record)

    if request.method == "PATCH":
        patch = request.json or {}
        record = local_store.update_entity(entity_type, entity_id, patch)
        if record is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(record)

    deleted = local_store.delete_entity(entity_type, entity_id)
    if not deleted:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@app.route("/functions/<function_name>", methods=["POST"])
def call_function(function_name):
    body = request.json or {}
    action = str(body.get("action") or "")

    if function_name == "tradingConnector":
        if action == "read":
            return jsonify(local_functions.trading_connector_read())
        if action == "save":
            return jsonify(local_functions.trading_connector_save(body))
        if action in ("test", "connect", "reconnect"):
            return jsonify(local_functions.trading_connector_test(get_account_snapshot, fetch_symbols_direct))
        if action == "build_order":
            # Real Capital Risk Engine (2026-08-06): the lot is sized against
            # the account's real, current equity read from MT5 right now —
            # never a capital figure supplied by the caller (see
            # local_functions.build_order's docstring). If MT5 isn't
            # connected or the account snapshot has no usable equity, refuse
            # explicitly rather than let calculate_lot() guess.
            snap = get_account_snapshot()
            equity = snap.get("equity") if snap else None
            try:
                order = local_functions.build_order(body, account_equity=equity)
            except local_functions.RealCapitalUnavailable as e:
                return jsonify({"ok": False, "error": str(e), "reason": "CAPITAL_UNAVAILABLE"}), 400
            return jsonify({"ok": True, "order": order})
        if action == "save_bridge_result":
            payload, status = local_functions.trading_connector_save_bridge_result(body, fetch_symbols_direct)
            return jsonify(payload), status
        return jsonify({"error": "Action inconnue"}), 400

    if function_name == "tradeManager":
        if action == "close_trade":
            payload, status = local_functions.trade_manager_close_trade(body, local_store.get_entity)
            return jsonify(payload), status
        if action == "sync_daily":
            payload, status = local_functions.trade_manager_sync_daily(body)
            return jsonify(payload), status
        return jsonify({"error": "Action inconnue"}), 400

    if function_name == "strategyOrchestrator":
        payload, status = local_functions.strategy_orchestrator(body)
        return jsonify(payload), status

    if function_name == "marketBrain":
        payload, status = local_functions.market_brain_analyze(body, fetch_candles_direct)
        return jsonify(payload), status

    if function_name == "engineTest":
        payload, status = local_functions.engine_test(body, fetch_candles_direct, get_open_positions, modify_position_direct)
        return jsonify(payload), status

    if function_name == "positionManagement":
        # Kept callable on demand (manual "check now" from the UI, and for
        # tests) even though the real, always-on protection is the
        # independent ~1s Position Manager loop below (start_position_manager)
        # — not this request/response path anymore.
        params_list = local_store.list_entities("Parameter", sort="-created_date", limit=1)
        params = params_list[0] if params_list else {}
        snap = get_account_snapshot()
        equity = snap.get("equity") if snap else None
        result = local_functions.manage_open_positions(
            get_open_positions, modify_position_direct, params,
            close_fn=close_position_direct, equity=equity,
        )
        return jsonify({"ok": True, **result})

    if function_name == "dailyGoalStatus":
        params_list = local_store.list_entities("Parameter", sort="-created_date", limit=1)
        params = params_list[0] if params_list else {}
        return jsonify({"ok": True, **local_functions.daily_goal_status(params)})

    if function_name == "learningPatterns":
        # AI Trade Memory (2026-08-07) — read-only diagnostic, see
        # learning_engine.py's module docstring for why this doesn't
        # influence any live decision yet.
        return jsonify({"ok": True, "patterns": learning_engine.pattern_win_rates()})

    if function_name == "portfolioRisk":
        # Portfolio Risk Manager (2026-08-06) — checked by the frontend
        # BEFORE creating a Signal/order, in addition to (not instead of)
        # the per-symbol exposure dedup already in autoExecute(). Real
        # positions + real equity, read fresh here rather than trusted from
        # the caller — same principle as build_order's account_equity.
        symbol = str(body.get("symbol") or "").strip().upper()
        risk_percent = body.get("risk_percent")
        snap = get_account_snapshot()
        equity = snap.get("equity") if snap else None
        positions = get_open_positions() or []
        params_list = local_store.list_entities("Parameter", sort="-created_date", limit=1)
        params = params_list[0] if params_list else {}
        result = portfolio_risk.portfolio_exposure_check(
            symbol, positions, equity, risk_percent,
            max_portfolio_risk_percent=params.get("max_portfolio_risk_percent"),
            max_positions_per_category=params.get("max_positions_per_category"),
        )
        return jsonify({"ok": True, **result})

    stub = local_functions.deterministic_stub_response(function_name, body)
    if isinstance(stub, tuple):
        payload, status = stub
        return jsonify(payload), status
    return jsonify(stub)


# ── Entry point ──────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("BRIDGE_PORT", 8000))
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")

    log.info("=" * 60)
    log.info("AlphaTrade Global — alphatg_bridge (Real-Time Edition)")
    log.info("=" * 60)
    log.info("  API Key: %s", BRIDGE_API_KEY)
    log.info("  → Copy this key into Settings → Trading Platform → API Key")
    log.info("  Bridge URL: http://%s:%d", host, port)
    log.info("  SSE Stream: http://%s:%d/stream?key=API_KEY", host, port)
    log.info("  Monitor interval: %dms (latency < %dms)", MONITOR_INTERVAL_MS, MONITOR_INTERVAL_MS + 50)
    log.info("=" * 60)

    # MT5 connection runs in the background: mt5.initialize() blocks until
    # the terminal finishes starting up, which can take anywhere from a
    # couple seconds to well over a minute on a cold start. Gating the
    # whole HTTP server behind that meant the app (entities, auth, login —
    # none of which need MT5) was unreachable for that entire window, with
    # no way to tell the difference between "still starting" and "broken".
    def connect_mt5_and_start_monitor():
        log.info("Connecting to MT5 terminal...")
        if mt5_auto_connect():
            log.info("Bridge ready — starting real-time monitor...")
            start_monitor()
            start_position_manager()
        else:
            log.warning("MT5 not connected. Open MT5, log in, then restart this bridge.")

    threading.Thread(target=connect_mt5_and_start_monitor, daemon=True).start()

    # Crypto Intelligence journal — independent of MT5 (Hyperliquid is a
    # separate data source), collects a snapshot every 10 minutes so real
    # observation history accumulates over the coming weeks whether or not
    # any UI is open. Deliberately never touches market_brain.py or any
    # decision — see global_market_intelligence.py's module docstring for
    # why this stays observation-only until validated.
    CRYPTO_INTEL_INTERVAL_SEC = 600

    def collect_crypto_intelligence_loop():
        while True:
            try:
                macro_fn = fetch_candles_direct if _connection["initialized"] else None
                snapshot = global_market_intelligence.record_snapshot(macro_fn)
                log.info("[CRYPTO_INTEL] regime=%s score=%s band=%s",
                         snapshot["market_regime"], snapshot["crypto_intelligence_score"]["average"],
                         snapshot["crypto_intelligence_score"]["band"])
            except Exception as e:
                log.warning("[CRYPTO_INTEL] snapshot failed: %s", e)
            time.sleep(CRYPTO_INTEL_INTERVAL_SEC)

    threading.Thread(target=collect_crypto_intelligence_loop, daemon=True).start()

    # Auto Optimization Lab (2026-08-07): worker starts immediately (it just
    # blocks on an empty queue until something needs validating — harmless
    # without MT5) ; the scheduler itself checks _connection["initialized"]
    # before doing anything, same pattern as the crypto loop above.
    start_asset_validation_worker()
    start_asset_revalidation_scheduler()

    app.run(host=host, port=port, debug=False, threaded=True)