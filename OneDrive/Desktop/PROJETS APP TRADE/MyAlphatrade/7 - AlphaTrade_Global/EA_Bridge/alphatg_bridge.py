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

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("alphatg_bridge")

# ── Flask app ────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)


@app.after_request
def add_pna_headers(resp):
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# ── API Key management ───────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_FILE = os.path.join(_SCRIPT_DIR, "bridge_api_key.txt")


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
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    if request.path == "/health":
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

# ── MT5 auto-connection ──────────────────────────────────────────
_connection = {"initialized": False, "account_type": None}
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

    _connection.update({"initialized": True, "account_type": account_type})

    log.info("=" * 60)
    log.info("MT5 CONNECTED SUCCESSFULLY")
    log.info("  Account: %s", info.login)
    log.info("  Server:  %s", info.server)
    log.info("  Type:    %s", account_type)
    log.info("  Balance: %s %s", info.balance, info.currency)
    log.info("=" * 60)
    return True


def mt5_disconnect():
    if _connection["initialized"] and mt5 is not None:
        mt5.shutdown()
    _connection.update({"initialized": False, "account_type": None})
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
        "magic": 234000,
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
        "magic": 234000,
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


@app.route("/symbols", methods=["GET"])
def get_symbols():
    if not _connection["initialized"]:
        return jsonify({"ok": False, "error": "MT5 not connected"}), 400

    symbols = mt5.symbols_get() or []
    symbol_names = [s.name for s in symbols]
    return jsonify({"ok": True, "symbols": symbol_names})


_MT5_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}


@app.route("/rates", methods=["GET"])
def get_rates():
    """Real OHLCV candles from MT5 — the actual price data behind the
    analysis engines. No candles here means no real technical analysis,
    only a text description a model has to guess at."""
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400

    symbol = (request.args.get("symbol") or "").strip().upper()
    timeframe = (request.args.get("timeframe") or "H1").strip().upper()
    from_str = request.args.get("from")
    to_str = request.args.get("to")

    if not symbol:
        return jsonify(_structured_error("INVALID_REQUEST", "symbol is required")), 400

    tf_attr = _MT5_TIMEFRAMES.get(timeframe)
    if tf_attr is None:
        return jsonify(_structured_error(
            "INVALID_REQUEST",
            "Unsupported timeframe: " + timeframe,
            extra={"supported": list(_MT5_TIMEFRAMES.keys())},
        )), 400
    tf_const = getattr(mt5, tf_attr)

    mapping = resolve_symbol(symbol)
    resolved = mapping.get("resolved")
    if not mapping.get("found") or not resolved:
        return jsonify(_structured_error(
            "SYMBOL_NOT_FOUND", "Symbol not found: " + symbol, symbol=symbol,
            extra={"similar": mapping.get("similar", [])},
        )), 404

    # Two modes: a date range for backtesting over a historical period, or the
    # last N bars for live analysis snapshots. copy_rates_range has no bar limit.
    if from_str or to_str:
        try:
            date_from = datetime.fromisoformat(from_str.replace("Z", "+00:00")) if from_str else datetime(2000, 1, 1)
            date_to = datetime.fromisoformat(to_str.replace("Z", "+00:00")) if to_str else datetime.utcnow()
        except ValueError:
            return jsonify(_structured_error("INVALID_REQUEST", "from/to must be ISO date strings (YYYY-MM-DD)")), 400
        with _mt5_lock:
            rates = mt5.copy_rates_range(resolved, tf_const, date_from, date_to)
    else:
        try:
            count = min(max(int(request.args.get("count", 300)), 1), 1000)
        except ValueError:
            return jsonify(_structured_error("INVALID_REQUEST", "count must be an integer")), 400
        with _mt5_lock:
            rates = mt5.copy_rates_from_pos(resolved, tf_const, 0, count)

    if rates is None or len(rates) == 0:
        return jsonify(_structured_error(
            "NO_DATA", "No rate data returned for " + resolved, symbol=resolved,
        )), 400

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


@app.route("/close_position", methods=["POST"])
def close_position():
    if not _connection["initialized"]:
        return jsonify(_structured_error("CONNECTION_LOST", "MT5 not connected")), 400

    data = request.json or {}
    ticket = int(data.get("ticket", 0))

    with _mt5_lock:
        positions = mt5.positions_get(ticket=ticket) or []
    if not positions:
        return jsonify(_structured_error("POSITION_NOT_FOUND", "Position not found: " + str(ticket))), 404

    pos = positions[0]
    trade_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

    # Resolve symbol + filling mode (same robustness as send_order)
    fill_result = get_supported_filling_mode(pos.symbol)
    filling_const_val = fill_result.get("selected_const", mt5.ORDER_FILLING_RETURN)

    with _mt5_lock:
        tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return jsonify(_structured_error("NO_PRICE", "No price available for " + pos.symbol, symbol=pos.symbol)), 400

    price = tick.bid if trade_type == mt5.ORDER_TYPE_SELL else tick.ask

    request_data = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": trade_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 234000,
        "comment": "AT Global — Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_const_val,
    }

    result = mt5.order_send(request_data)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else 0
        return jsonify(_structured_error(
            "CLOSE_FAILED",
            "Close failed: retcode=" + str(retcode) + ", comment=" + str(getattr(result, "comment", "")),
            symbol=pos.symbol,
            extra={"retcode": retcode},
        )), 400

    log.info("[CLOSE_OK] ticket=%s symbol=%s closed at %s", ticket, pos.symbol, price)
    return jsonify({"ok": True, "ticket": str(result.order)})


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

    log.info("Connecting to MT5 terminal...")
    if mt5_auto_connect():
        log.info("Bridge ready — starting real-time monitor...")
        start_monitor()
    else:
        log.warning("MT5 not connected. Open MT5, log in, then restart this bridge.")

    app.run(host=host, port=port, debug=False, threaded=True)