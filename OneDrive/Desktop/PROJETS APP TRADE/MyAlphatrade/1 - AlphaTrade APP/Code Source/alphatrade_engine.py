from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import tempfile
import time
import argparse
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from market_microstructure import MicrostructureObserver

MAGIC = 20260607
AVA_MAGIC = 7525001
VERSION = "0.2.0"
HARD_REAL_LOT_CAP = 0.10
HARD_DEMO_LOT_CAP = 0.10
HARD_RISK_PCT_CAP = 0.50
HARD_AUTO_POSITION_CAP = 8

DATA_DIR = Path(os.environ.get("ALPHATRADE_DATA_DIR", Path.home() / "AlphaTrade"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = {
    "XAUUSD": {
        "aliases": ["XAUUSD", "Gold vs US Dollar", "XAUUSD."],
        "label": "XAU/USD",
        "market": "gold",
    },
    "EURUSD": {
        "aliases": ["EURUSD", "EURUSD.", "Euro vs US Dollar"],
        "label": "EUR/USD",
        "market": "forex",
    },
}

DEFAULT_PARAMS = {
    "mt5_path": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "active_symbol": "XAUUSD",
    "mode": "monitor",
    "strategy_mode": "scalping_fast",
    "trading_enabled": False,
    "demo_only": False,
    "auto_max_positions": 2,
    "session_target": 25.0,
    "daily_target": 50.0,
    "session_max_loss": -150.0,
    "giveback": 100.0,
    "profit_protection_enabled": True,
    "profit_protection_start": 25.0,
    "profit_drawdown_pct": 30.0,
    "profit_drawdown_min": 10.0,
    "profit_warning_ratio": 0.75,
    "profit_ai_grace_sec": 30,
    "min_profit": 0.20,
    "risk_pct": 0.35,
    "real_lot_cap": 0.10,
    "demo_lot_cap": 0.10,
    "max_trades_hour": 300,
    "cadence_sec": 30,
    "max_hold_sec": 45,
    "position_review_sec": 120,
    "confidence_min": 62,
    "anti_top_bottom": True,
    "lookback_candles": 200,
    "edge_zone_pct": 20,
    "min_score_gap": 8,
    "reinforcement_enabled": True,
    "reinforcement_min_confidence_margin": 5,
    "reinforcement_min_score_gap": 8,
    "reinforcement_cooldown_sec": 30,
    "ai_server_enabled": True,
    "ai_server_url": "http://127.0.0.1:8765",
    "ai_server_token": "",
    "ai_observation_mode": True,
    "ai_server_trade_confirmation": True,
    "ai_sync_interval_sec": 5,
    "ai_retrain_interval_min": 360,
    "rebond_enabled": True,
    "rebond_min_zone_strength": 35,
    "rebond_cooldown_sec": 180,
    "rebond_max_hold_sec": 90,
    "rebond_stop_pips": 0.60,
    "microstructure_enabled": True,
    "microstructure_interval_sec": 2,
    "hyperliquid_observer_enabled": False,
    "hyperliquid_symbols": ["BTC", "ETH"],
    "symbols": {
        "XAUUSD": {
            "lot": 0.05,
            "lot_min": 0.01,
            "lot_max": 0.10,
            "tp_pips": 30,
            "max_positions": 5,
            "max_position_loss": 20,
            "max_floating_loss": 50,
            "timeframe": "M5",
            "confidence_min": 60,
            "cadence_sec": 15,
            "max_trades_hour": 120,
            "max_hold_sec": 3600,
            "position_review_sec": 300,
            "profit_target": 5.00,
            "profit_lock_trigger": 0.50,
            "profit_lock_drawdown": 0.20,
            "emergency_loss_limit": 50.00,
            "min_positive_exit": 0.50,
            "signal_reversal_margin": 99,
            "cooldown_after_loss_sec": 30,
            "session_filter_enabled": False,
            "session_start_utc": 7,
            "session_end_utc": 22,
            "stop_before_end_min": 10,
        },
        "EURUSD": {
            "lot": 0.01,
            "lot_min": 0.001,
            "lot_max": 0.02,
            "tp_pips": 8,
            "max_positions": 2,
            "max_position_loss": 3,
            "max_floating_loss": 6,
            "timeframe": "M15",
            "confidence_min": 68,
            "cadence_sec": 45,
            "max_trades_hour": 40,
            "max_hold_sec": 300,
            "position_review_sec": 120,
            "profit_target": 0.50,
            "profit_lock_trigger": 0.30,
            "profit_lock_drawdown": 0.12,
            "emergency_loss_limit": 4.00,
            "min_positive_exit": 0.05,
            "signal_reversal_margin": 9,
            "cooldown_after_loss_sec": 120,
            "session_filter_enabled": True,
            "session_start_utc": 7,
            "session_end_utc": 20,
            "stop_before_end_min": 30,
        },
    },
}

STRATEGY_PROFILES = {
    "scalping_fast": {
        "label": "Scalping rapide",
        "description": "Plus reactif: petits gains frequents, signaux courts et sorties rapides.",
        "global": {"lookback_candles": 120, "min_score_gap": 8, "edge_zone_pct": 18},
        "symbols": {
            "XAUUSD": {"timeframe": "M5", "confidence_min": 55, "cadence_sec": 10, "position_review_sec": 60, "profit_target": 3.00, "max_hold_sec": 600},
            "EURUSD": {"timeframe": "M5", "confidence_min": 60, "cadence_sec": 20, "position_review_sec": 60, "profit_target": 1.00, "max_hold_sec": 300},
        },
    },
    "scalping_safe": {
        "label": "Scalping prudent",
        "description": "Moins de trades: confirmations plus propres et filtres de risque plus stricts.",
        "global": {"lookback_candles": 200, "min_score_gap": 10, "edge_zone_pct": 20},
        "symbols": {
            "XAUUSD": {"timeframe": "M5", "confidence_min": 60, "cadence_sec": 15, "position_review_sec": 120, "profit_target": 5.00, "max_hold_sec": 1800},
            "EURUSD": {"timeframe": "M15", "confidence_min": 65, "cadence_sec": 45, "position_review_sec": 120, "profit_target": 2.00, "max_hold_sec": 600},
        },
    },
    "long_analysis": {
        "label": "Analyse longue",
        "description": "Moins d'entrees: lecture multi-timeframe, objectif par trade plus eleve.",
        "global": {"lookback_candles": 300, "min_score_gap": 12, "edge_zone_pct": 24},
        "symbols": {
            "XAUUSD": {"timeframe": "M15", "confidence_min": 65, "cadence_sec": 60, "position_review_sec": 300, "profit_target": 10.0, "max_hold_sec": 3600, "max_positions": 3},
            "EURUSD": {"timeframe": "H1", "confidence_min": 70, "cadence_sec": 120, "position_review_sec": 300, "profit_target": 5.0, "max_hold_sec": 3600, "max_positions": 2},
        },
    },
    "combined": {
        "label": "Mode combine",
        "description": "Scalping seulement si la tendance longue ne contredit pas le signal court.",
        "global": {"lookback_candles": 240, "min_score_gap": 8, "edge_zone_pct": 20},
        "symbols": {
            "XAUUSD": {"timeframe": "M5", "confidence_min": 58, "cadence_sec": 12, "position_review_sec": 120, "profit_target": 5.00, "max_hold_sec": 1800},
            "EURUSD": {"timeframe": "M15", "confidence_min": 65, "cadence_sec": 40, "position_review_sec": 120, "profit_target": 2.00, "max_hold_sec": 900},
        },
    },
}

AI_SERVER_STATE = {
    "enabled": True,
    "connected": False,
    "mode": "OBSERVATION",
    "url": "http://127.0.0.1:8765",
    "models": {},
    "predictions": {},
    "last_sync": None,
    "error": "",
}
AI_TRAIN_ATTEMPTS: dict[str, float] = {}
CLOSE_ATTEMPTS: dict[int, float] = {}

# ── Module Capture Rebond ──────────────────────────────────────────────────────
# Gère les positions contra-tendance sur rebonds identifiés via zones S&D
# multi-timeframe. La position principale reste ouverte; seul le rebond est
# capturé avec un lot dynamique, puis fermé rapidement avant la résistance.
REBOND_STATE: dict = {
    "active": False,          # Un BUY/SELL contra-tendance est en cours
    "ticket": None,           # Ticket MT5 de la position contra-tendance
    "direction": None,        # Direction du rebond (opposée à la principale)
    "open_price": 0.0,        # Prix d'ouverture du rebond
    "target_price": 0.0,      # Niveau cible (support/résistance identifié)
    "lot": 0.0,               # Lot utilisé pour le rebond
    "opened_at": 0.0,         # Timestamp d'ouverture
    "zones": [],              # Zones S&D identifiées sur M5/M15
    "last_scan": 0.0,         # Dernier scan des zones
    "last_rebond_at": 0.0,    # Dernier rebond ouvert (cooldown)
}

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception as exc:
    mt5 = None
    MT5_IMPORT_ERROR = str(exc)
else:
    MT5_IMPORT_ERROR = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(name: str, payload: dict) -> None:
    path = DATA_DIR / name
    fd, tmp = tempfile.mkstemp(prefix="alphatrade_", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
        try:
            os.replace(tmp, path)
        except PermissionError:
            # Windows: fichier verrouillé — écriture directe en fallback
            import time as _time
            _time.sleep(0.05)
            try:
                os.replace(tmp, path)
            except PermissionError:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=True, separators=(",", ":"))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def read_json(name: str, fallback=None):
    try:
        path = DATA_DIR / name
        if not path.exists():
            return fallback
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def log(message: str, level: str = "INFO") -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {message}"
    print(line, flush=True)
    with (DATA_DIR / "alphatrade.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def append_jsonl(name: str, payload: dict) -> None:
    with (DATA_DIR / name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")


def merge_params() -> dict:
    saved = read_json("params.json", {}) or {}
    merged = json.loads(json.dumps(DEFAULT_PARAMS))
    for key, value in saved.items():
        if key == "symbols" and isinstance(value, dict):
            for sym, sym_params in value.items():
                if sym in merged["symbols"] and isinstance(sym_params, dict):
                    merged["symbols"][sym].update(sym_params)
        else:
            merged[key] = value
    if not (DATA_DIR / "params.json").exists():
        write_json("params.json", merged)
    return merged


def effective_params_for_strategy(params: dict) -> dict:
    effective = json.loads(json.dumps(params))
    mode = str(effective.get("strategy_mode") or "scalping_fast")
    profile = STRATEGY_PROFILES.get(mode, STRATEGY_PROFILES["scalping_fast"])
    saved = read_json("params.json", {}) or {}
    for key, value in profile.get("global", {}).items():
        # Ne pas écraser si l'utilisateur a explicitement défini la valeur
        if key not in saved:
            effective[key] = value
    for symbol_key, overrides in profile.get("symbols", {}).items():
        if symbol_key in effective.get("symbols", {}):
            saved_sym = saved.get("symbols", {}).get(symbol_key, {})
            for k, v in overrides.items():
                # Ne pas écraser si l'utilisateur a explicitement défini la valeur
                if k not in saved_sym:
                    effective["symbols"][symbol_key][k] = v
    effective["strategy_profile"] = {
        "key": mode,
        "label": profile.get("label", mode),
        "description": profile.get("description", ""),
    }
    return effective


def initialize_mt5(params: dict) -> bool:
    if mt5.initialize():
        log("Terminal MT5 actif detecte automatiquement.")
        return True
    configured = str(params.get("mt5_path") or "").strip()
    candidates = [
        configured,
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            if mt5.initialize(path=candidate):
                log(f"Terminal MT5 detecte: {candidate}")
                return True
            log(f"Connexion refusee via {candidate}: {mt5.last_error()}", "WARNING")
    return bool(mt5.initialize())


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATA_DIR / "alphatrade.db")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
          id TEXT PRIMARY KEY,
          ticket INTEGER,
          position_id INTEGER,
          symbol TEXT,
          direction TEXT,
          origin TEXT,
          lot REAL,
          open_price REAL,
          open_time TEXT,
          close_price REAL,
          close_time TEXT,
          profit REAL,
          status TEXT
        )
        """
    )
    conn.commit()
    return conn


def resolve_symbol(key: str) -> str | None:
    if mt5 is None:
        return None
    for alias in SYMBOLS[key]["aliases"]:
        info = mt5.symbol_info(alias)
        if info is not None:
            mt5.symbol_select(alias, True)
            return alias
    return None


def tf_const(name: str):
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping.get(str(name).upper(), mt5.TIMEFRAME_M5)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in deltas[-period:]]
    losses = [max(-x, 0) for x in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def default_learning_state() -> dict:
    symbols = {}
    for key in SYMBOLS:
        symbols[key] = {
            "samples": 0,
            "wins": 0,
            "losses": 0,
            "total_profit": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "confidence_offset": 0.0,
            "weights": {
                "trend": 1.0,
                "rsi": 1.0,
                "macd": 1.0,
                "edge": 1.0,
                "momentum": 1.0,
            },
            "processed_positions": [],
            "last_outcome": "",
            "last_closed_at": "",
        }
    return {"version": 1, "symbols": symbols, "updated_at": ""}


def load_learning_state() -> dict:
    state = read_json("learning_state.json", {}) or {}
    merged = default_learning_state()
    for key, value in state.items():
        if key != "symbols":
            merged[key] = value
    for key, value in (state.get("symbols") or {}).items():
        if key not in merged["symbols"] or not isinstance(value, dict):
            continue
        merged["symbols"][key].update(value)
        merged["symbols"][key]["weights"].update(value.get("weights") or {})
    return merged


def save_learning_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json("learning_state.json", state)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ai_server_request(params: dict, path: str, payload: dict | None = None, timeout: float = 1.5) -> dict:
    base = str(params.get("ai_server_url") or "http://127.0.0.1:8765").rstrip("/")
    body = None if payload is None else json.dumps(payload, ensure_ascii=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = str(params.get("ai_server_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers=headers,
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def update_ai_server_state(
    params: dict,
    symbol_names: dict[str, str],
    analyses: dict[str, dict],
    train_missing: bool = False,
) -> dict:
    global AI_SERVER_STATE
    enabled = bool(params.get("ai_server_enabled", True))
    base = str(params.get("ai_server_url") or "http://127.0.0.1:8765").rstrip("/")
    if not enabled:
        AI_SERVER_STATE = {
            **AI_SERVER_STATE,
            "enabled": False,
            "connected": False,
            "url": base,
            "error": "Serveur IA desactive dans les parametres.",
        }
        return AI_SERVER_STATE
    try:
        health = ai_server_request(params, "/health", timeout=0.8)
        model_payload = ai_server_request(params, "/v1/models", timeout=0.8)
        models = dict(model_payload.get("models") or {})
        retrain_minutes = max(30, int(params.get("ai_retrain_interval_min", 360)))
        for key, name in symbol_names.items():
            model = models.get(key)
            due = model is None
            if model and model.get("trained_at"):
                try:
                    trained_at = datetime.fromisoformat(str(model["trained_at"]))
                    if trained_at.tzinfo is None:
                        trained_at = trained_at.replace(tzinfo=timezone.utc)
                    due = (
                        datetime.now(timezone.utc) - trained_at.astimezone(timezone.utc)
                    ).total_seconds() >= retrain_minutes * 60
                except ValueError:
                    due = True
            last_attempt = float(AI_TRAIN_ATTEMPTS.get(key, 0))
            if due and (train_missing or time.time() - last_attempt >= 1800):
                AI_TRAIN_ATTEMPTS[key] = time.time()
                candles = symbol_candles(
                    name,
                    params.get("symbols", {}).get(key, {}),
                    limit=1200,
                )
                trained = ai_server_request(
                    params,
                    "/v1/train",
                    {
                        "symbol": key,
                        "candles": candles,
                        "horizon_bars": 3 if key == "XAUUSD" else 5,
                    },
                    timeout=30,
                )
                if trained.get("active_model"):
                    models[key] = trained["active_model"]
        predictions = {}
        for key, name in symbol_names.items():
            candles = symbol_candles(
                name,
                params.get("symbols", {}).get(key, {}),
                limit=120,
            )
            predictions[key] = ai_server_request(
                params,
                "/v1/predict",
                {
                    "symbol": key,
                    "candles": candles,
                    "local": analyses.get(key, {}),
                },
                timeout=2,
            )
        AI_SERVER_STATE = {
            "enabled": True,
            "connected": bool(health.get("ok")),
            "mode": "OBSERVATION",
            "url": base,
            "server_version": health.get("version"),
            "models": models,
            "predictions": predictions,
            "last_sync": utc_now(),
            "error": "",
        }
    except (OSError, ValueError, urllib.error.URLError) as exc:
        AI_SERVER_STATE = {
            **AI_SERVER_STATE,
            "enabled": True,
            "connected": False,
            "url": base,
            "last_sync": utc_now(),
            "error": str(exc),
        }
    return AI_SERVER_STATE


def server_trade_confirmation(
    params: dict,
    active: str,
    symbol: str,
    decision: dict,
    analysis: dict,
    payload: dict,
    positions: list[dict],
    lot_info: dict,
) -> tuple[bool, dict]:
    if not bool(params.get("ai_server_enabled", True)):
        return True, {"ok": True, "approved": True, "reason": "Serveur IA desactive."}
    if not bool(params.get("ai_server_trade_confirmation", True)):
        return True, {"ok": True, "approved": True, "reason": "Confirmation serveur IA desactivee."}

    context = {
        "symbol_key": active,
        "symbol": symbol,
        "local_decision": {
            "signal": decision.get("signal"),
            "confidence": decision.get("confidence"),
            "reason": decision.get("reason"),
            "eligible": decision.get("eligible"),
        },
        "analysis": {
            "signal": analysis.get("signal"),
            "confidence": analysis.get("confidence"),
            "trend": analysis.get("trend"),
            "fast_signal": analysis.get("fast_signal"),
            "score_gap": analysis.get("score_gap"),
            "rsi": analysis.get("rsi"),
            "edge_position": analysis.get("edge_position"),
            "learned_threshold": analysis.get("learned_threshold"),
            "zone": analysis.get("zone"),
            "strategy_mode": analysis.get("strategy_mode"),
            "multi_timeframe_bias": analysis.get("multi_timeframe_bias"),
            "multi_timeframe_score": analysis.get("multi_timeframe_score"),
            "support_zone": analysis.get("support_zone"),
            "resistance_zone": analysis.get("resistance_zone"),
        },
        "protection": payload.get("protection"),
        "session_access": payload.get("session_access", {}).get(active),
        "positions": [
            {
                "symbol_key": item.get("symbol_key"),
                "origin": item.get("origin"),
                "direction": item.get("direction"),
                "lot": item.get("lot"),
                "profit": item.get("profit"),
                "open_price": item.get("open_price"),
                "current_price": item.get("current_price"),
            }
            for item in positions[:8]
        ],
        "lot_safety": lot_info,
        "params": {
            "auto_max_positions": params.get("auto_max_positions"),
            "risk_pct": params.get("risk_pct"),
            "min_score_gap": params.get("min_score_gap"),
            "anti_top_bottom": params.get("anti_top_bottom"),
            "lookback_candles": params.get("lookback_candles"),
            "symbol": params.get("symbols", {}).get(active, {}),
            "strategy_mode": params.get("strategy_mode"),
            "strategy_profile": params.get("strategy_profile"),
        },
    }
    try:
        reply = ai_server_request(
            params,
            "/v1/decision",
            {"context": context},
            timeout=22,
        )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        reply = {
            "ok": False,
            "approved": False,
            "decision": "WAIT",
            "confidence": 0,
            "reason": f"Serveur IA indisponible: {exc}",
        }
    approved = bool(reply.get("ok")) and bool(reply.get("approved"))
    return approved, reply


def candle_reversal_context(rates, edge_position: float, edge_limit: float, rsi_value: float) -> dict:
    if rates is None or len(rates) < 8:
        return {"signal": "WAIT", "confidence": 0.0, "reason": "Pas assez de bougies."}
    last = rates[-1]
    prev = rates[-2]
    open_price = float(last[1])
    high = float(last[2])
    low = float(last[3])
    close = float(last[4])
    prev_open = float(prev[1])
    prev_close = float(prev[4])
    body = max(abs(close - open_price), 1e-9)
    upper_wick = max(0.0, high - max(open_price, close))
    lower_wick = max(0.0, min(open_price, close) - low)
    closes = [float(row[4]) for row in rates[-8:]]
    short_momentum = closes[-1] - closes[-4]
    bearish_candle = close < open_price
    bullish_candle = close > open_price
    bearish_engulf = bearish_candle and prev_close > prev_open and close < prev_open and open_price >= prev_close
    bullish_engulf = bullish_candle and prev_close < prev_open and close > prev_open and open_price <= prev_close
    top_extreme = edge_position >= 100 - edge_limit
    bottom_extreme = edge_position <= edge_limit

    if top_extreme:
        rejection = bool(
            bearish_engulf
            or bearish_candle
            or upper_wick >= body * 1.15
            or short_momentum < 0
            or rsi_value >= 60
        )
        if rejection:
            confidence = 55 + min(18, (edge_position - (100 - edge_limit)) * 0.5) + min(10, max(0, rsi_value - 58) * 0.35)
            if bearish_engulf:
                confidence += 6
            if upper_wick >= body * 1.15:
                confidence += 4
            if short_momentum < 0:
                confidence += 4
            return {
                "signal": "SELL",
                "confidence": round(clamp(confidence, 55, 82), 1),
                "reason": "Zone haute: rejet/essoufflement detecte, reanalyse en SELL.",
            }

    if bottom_extreme:
        rejection = bool(
            bullish_engulf
            or bullish_candle
            or lower_wick >= body * 1.15
            or short_momentum > 0
            or rsi_value <= 40
        )
        if rejection:
            confidence = 55 + min(18, (edge_limit - edge_position) * 0.5) + min(10, max(0, 42 - rsi_value) * 0.35)
            if bullish_engulf:
                confidence += 6
            if lower_wick >= body * 1.15:
                confidence += 4
            if short_momentum > 0:
                confidence += 4
            return {
                "signal": "BUY",
                "confidence": round(clamp(confidence, 55, 82), 1),
                "reason": "Zone basse: rejet/rebond detecte, reanalyse en BUY.",
            }

    return {"signal": "WAIT", "confidence": 0.0, "reason": "Aucun retournement confirme."}


def timeframe_trend_context(symbol: str, timeframe: str, limit: int = 160) -> dict:
    rates = mt5.copy_rates_from_pos(symbol, tf_const(timeframe), 0, limit)
    if rates is None or len(rates) < 55:
        return {"timeframe": timeframe, "trend": "COLLECTING", "score": 0.0}
    closes = [float(row[4]) for row in rates]
    highs = [float(row[2]) for row in rates[-80:]]
    lows = [float(row[3]) for row in rates[-80:]]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    momentum = closes[-1] - closes[-8]
    support = min(lows) if lows else closes[-1]
    resistance = max(highs) if highs else closes[-1]
    zone_pos = (closes[-1] - support) / (resistance - support) if resistance > support else 0.5
    trend = "RANGE"
    score = 0.0
    if e9 > e21 > e50 and momentum > 0:
        trend = "BULLISH"
        score = 1.0
    elif e9 < e21 < e50 and momentum < 0:
        trend = "BEARISH"
        score = -1.0
    elif e9 > e21:
        trend = "BULLISH"
        score = 0.45
    elif e9 < e21:
        trend = "BEARISH"
        score = -0.45
    return {
        "timeframe": timeframe,
        "trend": trend,
        "score": round(score, 3),
        "ema9": round(e9, 2),
        "ema21": round(e21, 2),
        "ema50": round(e50, 2),
        "support": round(support, 5),
        "resistance": round(resistance, 5),
        "zone_position": round(zone_pos * 100, 1),
    }


def multi_timeframe_context(symbol: str, symbol_key: str | None) -> dict:
    frames = ["M5", "M15", "M30", "H1"]
    contexts = [timeframe_trend_context(symbol, frame) for frame in frames]
    valid = [item for item in contexts if item.get("trend") != "COLLECTING"]
    if not valid:
        return {"bias": "COLLECTING", "score": 0.0, "frames": contexts}
    total = sum(float(item.get("score") or 0) for item in valid)
    avg = total / max(1, len(valid))
    bullish = sum(1 for item in valid if item.get("trend") == "BULLISH")
    bearish = sum(1 for item in valid if item.get("trend") == "BEARISH")
    bias = "RANGE"
    if avg >= 0.35 and bullish >= bearish:
        bias = "BULLISH"
    elif avg <= -0.35 and bearish >= bullish:
        bias = "BEARISH"
    supports = [float(item.get("support") or 0) for item in valid if item.get("support")]
    resistances = [float(item.get("resistance") or 0) for item in valid if item.get("resistance")]
    return {
        "bias": bias,
        "score": round(avg, 3),
        "frames": contexts,
        "support_zone": round(max(supports), 5) if supports else 0,
        "resistance_zone": round(min(resistances), 5) if resistances else 0,
    }


def symbol_analysis(symbol: str, params: dict, symbol_key: str | None = None, learning_state: dict | None = None) -> dict:
    if mt5 is None:
        return {}
    requested_lookback = max(20, int(params.get("lookback_candles", 200)))
    rates = mt5.copy_rates_from_pos(symbol, tf_const(params.get("timeframe", "M5")), 0, max(120, requested_lookback + 60))
    if rates is None or len(rates) < 30:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "score_buy": 0,
            "score_sell": 0,
            "trend": "COLLECTING",
            "rsi": 50,
        }
    closes = [float(row[4]) for row in rates]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    rv = rsi(closes)
    macd = ema(closes, 12) - ema(closes, 26)
    prev_macd = ema(closes[:-1], 12) - ema(closes[:-1], 26)
    trend = "BULLISH" if e9 > e21 > e50 else "BEARISH" if e9 < e21 < e50 else "RANGE"
    momentum = ((closes[-1] - closes[-5]) / closes[-5] * 10000) if closes[-5] else 0

    learned = (
        (learning_state or {}).get("symbols", {}).get(symbol_key, {})
        if symbol_key
        else {}
    )
    weights = learned.get("weights") or {}
    weight = lambda name: clamp(float(weights.get(name, 1.0)), 0.65, 1.35)
    components = {
        "trend": 1 if e9 > e21 else -1 if e9 < e21 else 0,
        "rsi": 1 if 50 <= rv <= 70 else -1 if 30 <= rv < 50 else 0,
        "macd": 1 if macd > 0 and macd > prev_macd else -1 if macd < 0 and macd < prev_macd else 0,
        "edge": 0,
        "momentum": 1 if momentum > 0 else -1 if momentum < 0 else 0,
    }
    buy = 25.0
    sell = 25.0
    if e9 > e21:
        buy += 18 * weight("trend")
    if e9 < e21:
        sell += 18 * weight("trend")
    if 50 <= rv <= 70:
        buy += 16 * weight("rsi")
    if 30 <= rv <= 50:
        sell += 16 * weight("rsi")
    if macd > 0 and macd > prev_macd:
        buy += 16 * weight("macd")
    if macd < 0 and macd < prev_macd:
        sell += 16 * weight("macd")

    lookback = max(5, min(len(closes), requested_lookback))
    zone = max(1, float(params.get("edge_zone_pct", 20))) / 100
    recent = closes[-lookback:]
    low, high = min(recent), max(recent)
    pos = (closes[-1] - low) / (high - low) if high > low else 0.5
    if pos < 1 - zone:
        buy += 8 * weight("edge")
        components["edge"] = 1
    if pos > zone:
        sell += 8 * weight("edge")
        if components["edge"] == 0:
            components["edge"] = -1
    if momentum > 0:
        buy += min(12, momentum / 3) * weight("momentum")
    if momentum < 0:
        sell += min(12, -momentum / 3) * weight("momentum")

    mtf = multi_timeframe_context(symbol, symbol_key)
    strategy_mode = str(params.get("strategy_mode") or "scalping_fast")
    mtf_bias = str(mtf.get("bias") or "RANGE")
    mtf_weight = 8.0
    if strategy_mode == "long_analysis":
        mtf_weight = 18.0
    elif strategy_mode == "combined":
        mtf_weight = 12.0
    elif strategy_mode == "scalping_safe":
        mtf_weight = 10.0
    if mtf_bias == "BULLISH":
        buy += mtf_weight
    elif mtf_bias == "BEARISH":
        sell += mtf_weight

    buy = round(max(0, min(100, buy)), 1)
    sell = round(max(0, min(100, sell)), 1)
    confidence = max(buy, sell)
    signal = "WAIT"
    learned_threshold = clamp(
        float(params.get("confidence_min", 62)) + float(learned.get("confidence_offset", 0)),
        55,
        82,
    )
    if confidence >= learned_threshold:
        signal = "BUY" if buy > sell else "SELL"
    fast_timeframe = mt5.TIMEFRAME_M5
    fast_rates = mt5.copy_rates_from_pos(symbol, fast_timeframe, 0, 40)
    fast_signal = "WAIT"
    fast_momentum = 0.0
    if fast_rates is not None and len(fast_rates) >= 15:
        fast_closes = [float(row[4]) for row in fast_rates]
        fast_e5 = ema(fast_closes, 5)
        fast_e13 = ema(fast_closes, 13)
        fast_momentum = fast_closes[-1] - fast_closes[-4]
        if fast_e5 > fast_e13 and fast_momentum > 0:
            fast_signal = "BUY"
        elif fast_e5 < fast_e13 and fast_momentum < 0:
            fast_signal = "SELL"
    reversal = candle_reversal_context(rates, round(pos * 100, 1), max(5.0, min(45.0, float(params.get("edge_zone_pct", 20)))), rv)
    score_gap = round(abs(buy - sell), 1)
    mtf_conflict = signal in {"BUY", "SELL"} and mtf_bias in {"BULLISH", "BEARISH"} and (
        (signal == "BUY" and mtf_bias == "BEARISH") or (signal == "SELL" and mtf_bias == "BULLISH")
    )
    regime_risk = 0
    if score_gap < float(params.get("min_score_gap", 8)):
        regime_risk += 30
    if mtf_conflict:
        regime_risk += 35
    if abs(fast_momentum) > max(abs(momentum), 1e-6) * 1.8:
        regime_risk += 20
    if reversal["signal"] not in {"WAIT", signal}:
        regime_risk += 15
    regime_risk = min(100, regime_risk)
    quant_veto = regime_risk >= 85
    quant_signal = "WAIT" if quant_veto else signal
    return {
        "signal": signal,
        "confidence": confidence,
        "score_buy": buy,
        "score_sell": sell,
        "trend": trend,
        "rsi": round(rv, 1),
        "ema9": round(e9, 2),
        "ema21": round(e21, 2),
        "ema50": round(e50, 2),
        "macd": round(macd, 4),
        "momentum": round(momentum, 2),
        "edge_position": round(pos * 100, 1),
        "components": components,
        "learned_threshold": round(learned_threshold, 1),
        "learning_samples": int(learned.get("samples", 0)),
        "learning_weights": {name: round(weight(name), 3) for name in components},
        "fast_signal": fast_signal,
        "fast_momentum": round(fast_momentum, 5),
        "score_gap": score_gap,
        "quant_signal": quant_signal,
        "quant_confidence": round(confidence if not quant_veto else max(0, confidence - regime_risk / 2), 1),
        "quant_regime_risk": regime_risk,
        "quant_veto": quant_veto,
        "quant_reason": "Gouverneur de risque actif" if quant_veto else "Consensus signal, structure et multi-timeframe",
        "strategy_mode": strategy_mode,
        "multi_timeframe_bias": mtf_bias,
        "multi_timeframe_score": mtf.get("score", 0),
        "multi_timeframe": mtf.get("frames", []),
        "support_zone": mtf.get("support_zone", 0),
        "resistance_zone": mtf.get("resistance_zone", 0),
        "reversal_signal": reversal["signal"],
        "reversal_confidence": reversal["confidence"],
        "reversal_reason": reversal["reason"],
    }


def symbol_candles(symbol: str, params: dict, limit: int = 90) -> list[dict]:
    if mt5 is None:
        return []
    rates = mt5.copy_rates_from_pos(symbol, tf_const(params.get("timeframe", "M5")), 0, limit)
    if rates is None:
        return []
    candles = []
    for row in rates:
        candles.append(
            {
                "time": int(row[0]),
                "open": round(float(row[1]), 5),
                "high": round(float(row[2]), 5),
                "low": round(float(row[3]), 5),
                "close": round(float(row[4]), 5),
            }
        )
    return candles


def trade_origin(magic: int, comment: str = "") -> str:
    normalized = str(comment or "").lower()
    if int(magic or 0) == MAGIC:
        return "BOT"
    # Deriv Demo ne conserve pas toujours le magic number
    # On identifie aussi par le commentaire de l'ordre
    if "alphatrade" in normalized or "alphakaris" in normalized:
        return "BOT"
    if int(magic or 0) == AVA_MAGIC or "ava" in normalized or "bridge" in normalized:
        return "EXTERNAL_AI"
    if int(magic or 0) != 0:
        return "EXTERNAL_AI"
    return "MANUAL"


def live_positions(symbol_names: dict[str, str]) -> list[dict]:
    if mt5 is None:
        return []
    rows = []
    all_positions = mt5.positions_get()
    if not all_positions:
        return rows
    reverse = {v: k for k, v in symbol_names.items()}
    for p in all_positions:
        key = reverse.get(p.symbol)
        if key is None and "EURUSD" in p.symbol.upper():
            key = "EURUSD"
        if key is None and "XAU" in p.symbol.upper():
            key = "XAUUSD"
        if key is None:
            continue
        rows.append(
            {
                "ticket": int(p.ticket),
                "symbol_key": key,
                "symbol": p.symbol,
                "direction": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "origin": trade_origin(
                    int(getattr(p, "magic", 0)),
                    str(getattr(p, "comment", "")),
                ),
                "lot": float(p.volume),
                "open_price": float(p.price_open),
                "current_price": float(p.price_current),
                "profit": round(float(p.profit), 2),
                "open_timestamp": int(p.time),
                "open_time": datetime.fromtimestamp(int(p.time)).isoformat(timespec="seconds"),
            }
        )
    return rows


def sync_history(conn: sqlite3.Connection, symbol_names: dict[str, str], days: int = 7) -> list[dict]:
    reverse = {v: k for k, v in symbol_names.items()}

    def from_db() -> list[dict]:
        rows = conn.execute(
            "SELECT id,ticket,position_id,symbol,direction,origin,lot,open_price,open_time,close_price,close_time,profit,status FROM trades ORDER BY close_time DESC LIMIT 500"
        ).fetchall()
        keys = ["id", "ticket", "position_id", "symbol", "direction", "origin", "lot", "open_price", "open_time", "close_price", "close_time", "profit", "status"]
        output = []
        for row in rows:
            item = dict(zip(keys, row))
            item["symbol_key"] = reverse.get(item["symbol"], "EURUSD" if "EURUSD" in item["symbol"].upper() else "XAUUSD" if "XAU" in item["symbol"].upper() else item["symbol"])
            item["move"] = round((item["close_price"] - item["open_price"]) if item["direction"] == "BUY" else (item["open_price"] - item["close_price"]), 2)
            output.append(item)
        return output

    if mt5 is None:
        return from_db()
    start = datetime.now() - timedelta(days=days)
    end = datetime.now() + timedelta(minutes=2)
    deals = mt5.history_deals_get(start, end)
    if not deals:
        return from_db()
    entries: dict[int, dict] = {}
    exits: dict[int, list] = {}
    for d in deals:
        symbol = getattr(d, "symbol", "")
        key = reverse.get(symbol)
        if key is None and "EURUSD" in symbol.upper():
            key = "EURUSD"
        if key is None and "XAU" in symbol.upper():
            key = "XAUUSD"
        if key is None:
            continue
        entry_type = int(getattr(d, "entry", -1))
        pos_id = int(getattr(d, "position_id", 0) or getattr(d, "order", 0))
        if entry_type == mt5.DEAL_ENTRY_IN:
            entries[pos_id] = {
                "position_id": pos_id,
                "ticket": int(getattr(d, "ticket", 0)),
                "symbol": symbol,
                "symbol_key": key,
                "direction": "BUY" if int(getattr(d, "type", -1)) == mt5.DEAL_TYPE_BUY else "SELL",
                "origin": trade_origin(
                    int(getattr(d, "magic", 0)),
                    str(getattr(d, "comment", "")),
                ),
                "lot": float(getattr(d, "volume", 0)),
                "open_price": float(getattr(d, "price", 0)),
                "open_time": datetime.fromtimestamp(int(getattr(d, "time", 0))).isoformat(timespec="seconds"),
            }
        elif entry_type in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
            exits.setdefault(pos_id, []).append(d)

    trades = []
    for pos_id, entry in entries.items():
        closed = exits.get(pos_id, [])
        if not closed:
            continue
        close_time = max(int(getattr(d, "time", 0)) for d in closed)
        close_price = float(closed[-1].price)
        profit = sum(float(getattr(d, "profit", 0)) + float(getattr(d, "commission", 0)) + float(getattr(d, "swap", 0)) for d in closed)
        trade = {
            **entry,
            "id": f"MT5-{pos_id}",
            "close_price": close_price,
            "close_time": datetime.fromtimestamp(close_time).isoformat(timespec="seconds"),
            "profit": round(profit, 2),
            "status": "CLOSED",
            "move": round((close_price - entry["open_price"]) if entry["direction"] == "BUY" else (entry["open_price"] - close_price), 2),
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO trades
            (id,ticket,position_id,symbol,direction,origin,lot,open_price,open_time,close_price,close_time,profit,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trade["id"],
                trade["ticket"],
                trade["position_id"],
                trade["symbol"],
                trade["direction"],
                trade["origin"],
                trade["lot"],
                trade["open_price"],
                trade["open_time"],
                trade["close_price"],
                trade["close_time"],
                trade["profit"],
                trade["status"],
            ),
        )
        trades.append(trade)
    conn.commit()

    rows = conn.execute(
        """
        SELECT id,ticket,position_id,symbol,direction,origin,lot,open_price,open_time,close_price,close_time,profit,status
        FROM trades ORDER BY close_time DESC LIMIT 500
        """
    ).fetchall()
    keys = ["id", "ticket", "position_id", "symbol", "direction", "origin", "lot", "open_price", "open_time", "close_price", "close_time", "profit", "status"]
    output = []
    for row in rows:
        item = dict(zip(keys, row))
        item["symbol_key"] = reverse.get(item["symbol"], "EURUSD" if "EURUSD" in item["symbol"].upper() else "XAUUSD" if "XAU" in item["symbol"].upper() else item["symbol"])
        item["move"] = round((item["close_price"] - item["open_price"]) if item["direction"] == "BUY" else (item["open_price"] - item["close_price"]), 2)
        output.append(item)
    return output


def stats(trades: list[dict], positions: list[dict]) -> dict:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    wins = [t for t in closed if float(t.get("profit") or 0) > 0]
    losses = [t for t in closed if float(t.get("profit") or 0) < 0]
    gross_win = sum(float(t["profit"]) for t in wins)
    gross_loss = abs(sum(float(t["profit"]) for t in losses))
    total = gross_win - gross_loss
    winrate = (len(wins) / len(closed) * 100) if closed else 0
    avg_win = gross_win / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    expectancy = (winrate / 100 * avg_win) - ((100 - winrate) / 100 * avg_loss)
    floating = sum(float(p.get("profit") or 0) for p in positions)
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(winrate, 1),
        "profit_closed": round(total, 2),
        "profit_floating": round(floating, 2),
        "profit_live": round(total + floating, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (999 if gross_win else 0),
        "expectancy": round(expectancy, 3),
    }


def utc_trade_day(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def daily_stats(trades: list[dict], positions: list[dict]) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    today_trades = [t for t in trades if utc_trade_day(t.get("close_time")) == today]
    return stats(today_trades, positions)


def application_session_stats(trades: list[dict], positions: list[dict], account_login: int | None) -> dict:
    stored = read_json("session_state.json", {}) or {}
    if stored.get("account") != account_login:
        return stats([], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    started_at = str(stored.get("reset_at") or "")
    if not started_at:
        return stats([], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    try:
        threshold = datetime.fromisoformat(started_at)
        if threshold.tzinfo is None:
            threshold = threshold.astimezone()
        threshold = threshold.astimezone(timezone.utc)
    except ValueError:
        return stats([], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    session_trades = []
    for trade in trades:
        closed_at = trade.get("close_time")
        if not closed_at:
            continue
        try:
            closed = datetime.fromisoformat(str(closed_at))
            if closed.tzinfo is None:
                closed = closed.astimezone()
            closed = closed.astimezone(timezone.utc)
        except ValueError:
            continue
        if closed >= threshold and trade.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS"):
            session_trades.append(trade)
    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    return stats(session_trades, bot_positions)


def session_access(symbol_key: str, symbol_params: dict) -> dict:
    filter_enabled = bool(symbol_params.get("session_filter_enabled", False))
    if not filter_enabled:
        return {
            "state": "OPEN",
            "entries_allowed": True,
            "reason": f"{symbol_key}: trading autorise sans restriction de session.",
        }
    now = datetime.now(timezone.utc)
    start = int(symbol_params.get("session_start_utc", 8))
    end = int(symbol_params.get("session_end_utc", 17))
    stop_before = max(0, int(symbol_params.get("stop_before_end_min", 30)))
    minute = now.hour * 60 + now.minute
    start_minute = start * 60
    end_minute = end * 60
    preclose_minute = max(start_minute, end_minute - stop_before)
    if start_minute <= minute < preclose_minute:
        return {
            "state": "OPEN",
            "entries_allowed": True,
            "reason": f"{symbol_key}: session autorisee {start:02d}h-{end:02d}h UTC.",
        }
    if preclose_minute <= minute < end_minute:
        return {
            "state": "PRECLOSE",
            "entries_allowed": False,
            "reason": f"{symbol_key}: pre-fermeture, nouvelles entrees bloquees.",
        }
    return {
        "state": "CLOSED",
        "entries_allowed": False,
        "reason": f"{symbol_key}: hors session autorisee {start:02d}h-{end:02d}h UTC.",
    }


def reset_session_state(account_login: int | None, current_daily_profit: float) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    stored = read_json("session_state.json", {}) or {}
    same_day = stored.get("date") == today and stored.get("account") == account_login
    payload = {
        "date": today,
        "account": account_login,
        "session_number": int(stored.get("session_number", 1)) + 1 if same_day else 1,
        "session_baseline": round(current_daily_profit, 2),
        # Réinitialiser daily_peak au redémarrage pour débloquer le plancher
        # Le pic repart de zéro à chaque redémarrage
        "daily_peak": round(max(0.0, current_daily_profit), 2),
        "session_locked": False,
        "daily_locked": False,
        "reset_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json("session_state.json", payload)
    return payload


def protection_state(params: dict, daily: dict, account_login: int | None) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    stored = read_json("session_state.json", {}) or {}
    same_session = stored.get("date") == today and stored.get("account") == account_login
    current = float(daily.get("profit_live") or 0)
    # A newly connected account starts from its current daily result. Trades
    # completed before AlphaTrade connected must not complete a fresh session.
    baseline = float(stored.get("session_baseline") or 0) if same_session else current
    session_profit = current - baseline
    daily_peak = max(float(stored.get("daily_peak") or stored.get("peak") or 0), current) if same_session else max(0.0, current)
    enabled = bool(params.get("profit_protection_enabled", True))
    activation = max(0.0, float(params.get("daily_target", params.get("profit_protection_start", 50))))
    pct = max(0.0, float(params.get("profit_drawdown_pct", 30)))
    pct_allowance = daily_peak * pct / 100
    min_allowance = max(0.0, float(params.get("profit_drawdown_min", 10)))
    max_allowance = max(0.0, float(params.get("giveback", 100)))
    allowance = max(min_allowance, pct_allowance)
    if max_allowance:
        allowance = min(allowance, max_allowance)
    floor = max(activation, daily_peak - allowance) if daily_peak >= activation else 0.0
    warning_ratio = min(0.95, max(0.1, float(params.get("profit_warning_ratio", 0.75))))
    warning_floor = max(floor, daily_peak - allowance * warning_ratio)
    activated = enabled and daily_peak >= activation
    session_locked = bool(stored.get("session_locked", stored.get("hard_locked", False))) if same_session else False
    daily_locked = bool(stored.get("daily_locked", False)) if same_session else False
    state = "INACTIVE"
    reason = f"Protection journaliere active a partir de +${activation:.2f}."
    if current <= float(params.get("session_max_loss", -150)):
        daily_locked = True
        state = "HARD_LOCK"
        reason = "Perte maximale journaliere atteinte."
    elif session_profit >= float(params.get("session_target", 25)):
        session_locked = True
        state = "TARGET_REACHED"
        reason = "Objectif de cette session atteint; nouvelle session requise."
    elif activated and current <= floor:
        daily_locked = True
        state = "HARD_LOCK"
        reason = "Plancher de protection du profit journalier atteint."
    elif daily_locked:
        state = "HARD_LOCK"
        reason = "Journee verrouillee apres declenchement de la protection."
    elif session_locked:
        state = "TARGET_REACHED"
        reason = "Session verrouillee; utilisez Nouvelle session pour reprendre."
    elif activated and current <= warning_floor:
        state = "WARNING"
        reason = "Zone d'avertissement: nouvelles entrees bloquees, observation IA limitee."
    elif activated:
        state = "ARMED"
        reason = "Protection du profit armee."

    payload = {
        "date": today,
        "account": account_login,
        "state": state,
        "reason": reason,
        "enabled": enabled,
        "activated": activated,
        "hard_locked": daily_locked,
        "daily_locked": daily_locked,
        "session_locked": session_locked,
        "session_number": int(stored.get("session_number", 1)) if same_session else 1,
        "reset_at": stored.get("reset_at") if same_session else datetime.now(timezone.utc).isoformat(),
        "session_baseline": round(baseline, 2),
        "session_profit": round(session_profit, 2),
        "current": round(current, 2),
        "peak": round(daily_peak, 2),
        "daily_peak": round(daily_peak, 2),
        "allowance": round(allowance, 2),
        "floor": round(floor, 2),
        "warning_floor": round(warning_floor, 2),
        "ai_grace_sec": max(0, int(params.get("profit_ai_grace_sec", 30))),
    }
    write_json("session_state.json", payload)
    return payload


def lot_safety_state(params: dict, account, symbol_names: dict[str, str]) -> dict:
    is_demo = bool(account and ("demo" in str(account.server).lower() or int(account.trade_mode) == 0))
    configured_account_cap = max(
        0.0,
        float(params.get("demo_lot_cap" if is_demo else "real_lot_cap", 0.10 if is_demo else 0.10)),
    )
    hard_account_cap = HARD_DEMO_LOT_CAP if is_demo else HARD_REAL_LOT_CAP
    account_cap = configured_account_cap if configured_account_cap > 0 else hard_account_cap
    balance = float(account.balance) if account else 0.0
    effective_risk_pct = min(
        max(0.0, float(params.get("risk_pct", 0.35))),
        HARD_RISK_PCT_CAP,
    )
    risk_budget = max(0.0, balance * effective_risk_pct / 100)
    result = {}
    for key, symbol_params in params.get("symbols", {}).items():
        configured = max(0.0, float(symbol_params.get("lot", 0)))
        symbol_cap = max(0.0, float(symbol_params.get("lot_max", configured)))
        requested_min = max(0.0, float(symbol_params.get("lot_min", 0)))
        name = symbol_names.get(key)
        info = mt5.symbol_info(name) if mt5 and name else None
        tick = mt5.symbol_info_tick(name) if mt5 and name else None
        broker_min = float(info.volume_min) if info else requested_min
        broker_step = float(info.volume_step) if info else broker_min or 0.01
        loss_per_lot = 0.0
        risk_lot_cap = 0.0
        if mt5 and info and tick:
            stop_distance = max(
                float(info.point),
                money_price_distance(
                    name,
                    "BUY",
                    1.0,
                    float(tick.ask),
                    info,
                    float(symbol_params.get("emergency_loss_limit", 3.0)),
                ),
            )
            estimated = mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY,
                name,
                1.0,
                float(tick.ask),
                float(tick.ask) - stop_distance,
            )
            loss_per_lot = abs(float(estimated or 0))
            if loss_per_lot > 0 and risk_budget > 0:
                risk_lot_cap = risk_budget / loss_per_lot
        caps = [value for value in (account_cap, symbol_cap, risk_lot_cap) if value > 0]
        cap = min(caps) if caps else 0.0
        effective = min(configured, cap) if cap > 0 else 0.0
        if broker_step > 0:
            effective = math.floor((effective + 1e-12) / broker_step) * broker_step
        effective = round(effective, 8)
        rejected = effective < broker_min or effective <= 0
        result[key] = {
            "configured_lot": configured,
            "account_cap": account_cap,
            "configured_account_cap": configured_account_cap,
            "hard_account_cap": hard_account_cap,
            "symbol_cap": symbol_cap,
            "broker_min": broker_min,
            "broker_step": broker_step,
            "effective_lot": 0.0 if rejected else effective,
            "risk_budget": round(risk_budget, 2),
            "effective_risk_pct": effective_risk_pct,
            "estimated_loss_per_lot": round(loss_per_lot, 2),
            "risk_lot_cap": round(risk_lot_cap, 8),
            "rejected": rejected,
            "reason": (
                "Lot minimal du broker superieur a la limite de securite."
                if rejected
                else f"Lot limite par le profil de risque et le plafond absolu {hard_account_cap:.3f}."
            ),
        }
    return result


def is_demo_account(account) -> bool:
    return bool(account and ("demo" in str(account.server).lower() or int(account.trade_mode) == 0))


def mt5_trading_permission() -> tuple[bool, str]:
    if not mt5:
        return False, "Module MetaTrader 5 indisponible."
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        return False, "Connexion MT5 indisponible."
    if bool(getattr(terminal, "tradeapi_disabled", False)):
        return (
            False,
            "Trading automatique bloque par MT5 (10027). Activez le bouton Trading Algo dans MT5.",
        )
    if not bool(getattr(terminal, "trade_allowed", True)):
        return (
            False,
            "Trading automatique desactive dans MT5. Activez le bouton Trading Algo dans MT5.",
        )
    if not bool(getattr(account, "trade_allowed", True)):
        return False, "Ce compte MT5 n'autorise pas actuellement les operations de trading."
    if not bool(getattr(account, "trade_expert", True)):
        return (
            False,
            "Les Expert Advisors sont interdits sur ce compte. Autorisez le trading algorithmique dans MT5.",
        )
    return True, ""


def load_trading_state() -> dict:
    state = read_json("trading_state.json", {}) or {}
    return {
        "enabled": bool(state.get("enabled", False)),
        "real_confirmed": bool(state.get("real_confirmed", False)),
        "last_entry_at": float(state.get("last_entry_at", 0)),
        "last_attempt_at": float(state.get("last_attempt_at", 0)),
        "entry_times": [float(value) for value in state.get("entry_times", [])],
        "last_action": str(state.get("last_action", "")),
        "last_error": str(state.get("last_error", "")),
        "allowed": bool(state.get("allowed", False)),
        "account_mode": str(state.get("account_mode", "-")),
        "reason": str(state.get("reason", "")),
    }


def save_trading_state(state: dict) -> None:
    write_json("trading_state.json", state)


def position_contexts() -> dict:
    return read_json("position_context.json", {}) or {}


def save_position_contexts(contexts: dict) -> None:
    write_json("position_context.json", contexts)


def track_position_contexts(
    positions: list[dict],
    trades: list[dict],
    analyses: dict,
    learning_state: dict,
) -> dict:
    contexts = position_contexts()
    live_tickets = {
        str(position["ticket"])
        for position in positions
        if position.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    for position in positions:
        if position.get("origin", "").upper() not in ("BOT", "ALPHATRADE", "ALPHAKARIS"):
            continue
        ticket = str(position["ticket"])
        context = contexts.get(ticket)
        if not context:
            context = {
                "ticket": int(position["ticket"]),
                "symbol_key": position.get("symbol_key"),
                "direction": position.get("direction"),
                "opened_at": position.get("open_time"),
                "analysis": analyses.get(position.get("symbol_key"), {}),
                "max_profit": float(position.get("profit") or 0),
                "min_profit": float(position.get("profit") or 0),
            }
        profit = float(position.get("profit") or 0)
        context["max_profit"] = round(max(float(context.get("max_profit") or profit), profit), 2)
        context["min_profit"] = round(min(float(context.get("min_profit") or profit), profit), 2)
        context["last_seen_at"] = now_iso
        contexts[ticket] = context

    closed_by_position = {
        str(int(trade.get("position_id") or 0)): trade
        for trade in trades
        if trade.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS") and trade.get("status") == "CLOSED"
    }
    for ticket, context in list(contexts.items()):
        if ticket in live_tickets:
            continue
        trade = closed_by_position.get(ticket)
        if not trade:
            continue
        key = context.get("symbol_key") or trade.get("symbol_key")
        learned = learning_state["symbols"].get(key)
        if not learned:
            contexts.pop(ticket, None)
            continue
        processed = {str(value) for value in learned.get("processed_positions", [])}
        position_id = str(int(trade.get("position_id") or 0))
        if position_id in processed:
            contexts.pop(ticket, None)
            continue
        profit = float(trade.get("profit") or 0)
        reward = clamp(profit / max(0.25, abs(float(context.get("min_profit") or 0)), abs(float(context.get("max_profit") or 0))), -1, 1)
        direction_sign = 1 if context.get("direction") == "BUY" else -1
        features = (context.get("analysis") or {}).get("components") or {}
        weights = learned.get("weights") or {}
        for name in ("trend", "rsi", "macd", "edge", "momentum"):
            stance = int(features.get(name, 0) or 0)
            if stance == 0:
                continue
            alignment = 1 if stance == direction_sign else -1
            delta = 0.025 * reward * alignment
            weights[name] = round(clamp(float(weights.get(name, 1.0)) + delta, 0.65, 1.35), 4)
        learned["weights"] = weights
        samples = int(learned.get("samples", 0)) + 1
        learned["samples"] = samples
        learned["wins"] = int(learned.get("wins", 0)) + (1 if profit > 0 else 0)
        learned["losses"] = int(learned.get("losses", 0)) + (1 if profit < 0 else 0)
        learned["total_profit"] = round(float(learned.get("total_profit", 0)) + profit, 2)
        learned["avg_mfe"] = round(
            ((float(learned.get("avg_mfe", 0)) * (samples - 1)) + max(0, float(context.get("max_profit") or 0))) / samples,
            3,
        )
        learned["avg_mae"] = round(
            ((float(learned.get("avg_mae", 0)) * (samples - 1)) + abs(min(0, float(context.get("min_profit") or 0)))) / samples,
            3,
        )
        offset = float(learned.get("confidence_offset", 0))
        offset += 0.45 if profit < 0 else -0.12
        learned["confidence_offset"] = round(clamp(offset, -4, 10), 2)
        learned["last_outcome"] = "WIN" if profit > 0 else "LOSS" if profit < 0 else "FLAT"
        learned["last_closed_at"] = trade.get("close_time") or now_iso
        learned["processed_positions"] = [*list(processed)[-199:], position_id]
        append_jsonl(
            "learning_events.jsonl",
            {
                "timestamp": now_iso,
                "event": "LEARNING_UPDATE",
                "symbol_key": key,
                "position_id": position_id,
                "profit": profit,
                "max_favorable_excursion": context.get("max_profit", 0),
                "max_adverse_excursion": context.get("min_profit", 0),
                "confidence_offset": learned["confidence_offset"],
                "weights": weights,
            },
        )
        contexts.pop(ticket, None)
    save_position_contexts(contexts)
    save_learning_state(learning_state)
    return contexts


def money_price_distance(symbol: str, direction: str, volume: float, price: float, info, money_target: float) -> float:
    point = float(info.point)
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    probe_close = price - point if direction == "BUY" else price + point
    probe = mt5.order_calc_profit(order_type, symbol, volume, price, probe_close)
    loss_per_point = abs(float(probe or 0))
    if loss_per_point <= 0:
        return max(point, float(getattr(info, "trade_stops_level", 0)) * point)
    points = max(1.0, abs(money_target) / loss_per_point)
    return points * point


def send_deal(request: dict):
    info = mt5.symbol_info(request["symbol"]) if mt5 else None
    fills = []
    if info is not None:
        filling_flags = int(getattr(info, "filling_mode", 0))
        if filling_flags & 1:
            fills.append(mt5.ORDER_FILLING_FOK)
        if filling_flags & 2:
            fills.append(mt5.ORDER_FILLING_IOC)
        if int(getattr(info, "trade_exemode", -1)) != 2:
            fills.append(mt5.ORDER_FILLING_RETURN)
    fills.extend([mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC])
    last_result = None
    for filling in dict.fromkeys(fills):
        attempt = {**request, "type_filling": filling}
        checked = mt5.order_check(attempt)
        if checked is None:
            continue
        last_result = checked
        if int(checked.retcode) == mt5.TRADE_RETCODE_INVALID_FILL:
            continue
        if int(checked.retcode) != 0:
            return checked
        result = mt5.order_send(attempt)
        last_result = result
        if result is not None and int(result.retcode) in {
            mt5.TRADE_RETCODE_DONE,
            mt5.TRADE_RETCODE_DONE_PARTIAL,
            mt5.TRADE_RETCODE_PLACED,
        }:
            return result
        if result is not None and int(result.retcode) != mt5.TRADE_RETCODE_INVALID_FILL:
            break
    return last_result


def open_position(symbol_key: str, symbol: str, direction: str, params: dict, lot_info: dict, analysis: dict, allow_real: bool):
    account = mt5.account_info()
    if not account:
        return False, "Compte MT5 indisponible.", None
    if not is_demo_account(account) and not allow_real:
        return False, "Confirmation du compte reel requise.", None
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False, "Prix ou specification symbole indisponible.", None
    volume = float(lot_info.get("effective_lot") or 0)
    if volume <= 0:
        return False, str(lot_info.get("reason") or "Lot invalide."), None
    symbol_params = params.get("symbols", {}).get(symbol_key, {})
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = float(tick.ask if direction == "BUY" else tick.bid)
    point = float(info.point)
    spread_distance = max(0.0, float(tick.ask) - float(tick.bid))
    broker_stop_distance = float(getattr(info, "trade_stops_level", 0)) * point
    min_distance = max(point, broker_stop_distance + spread_distance + (5 * point))
    tp_distance = max(
        min_distance,
        money_price_distance(
            symbol,
            direction,
            volume,
            price,
            info,
            float(symbol_params.get("profit_target", 0.50)),
        ),
    )
    tp = price + tp_distance if direction == "BUY" else price - tp_distance
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        # No broker-side SL: brief negative fluctuations stay under engine review.
        "sl": 0.0,
        "tp": round(tp, int(info.digits)),
        "deviation": 30,
        "magic": MAGIC,
        "comment": f"AlphaTrade {VERSION}",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    started = time.perf_counter()
    result = send_deal(request)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = bool(result is not None and int(result.retcode) in {
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_DONE_PARTIAL,
        mt5.TRADE_RETCODE_PLACED,
    })
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "ENTRY",
        "ok": ok,
        "symbol": symbol,
        "symbol_key": symbol_key,
        "direction": direction,
        "volume": volume,
        "price_requested": price,
        "retcode": int(result.retcode) if result is not None else None,
        "comment": str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error()),
        "latency_ms": latency_ms,
        "analysis": analysis,
        "broker_stop_loss": False,
        "catastrophic_loss_limit": float(symbol_params.get("emergency_loss_limit", 3.0)),
        "profit_target": float(symbol_params.get("profit_target", 0.50)),
    }
    append_jsonl("learning_events.jsonl", event)
    if ok:
        return True, f"{direction} {volume:.3f} {symbol} execute en {latency_ms:.0f} ms.", event
    return False, f"Ordre refuse: {event['retcode']} {event['comment']}", event


def close_bot_position(position: dict, reason: str):
    symbol = position["symbol"]
    ticket = int(position["ticket"])
    now = time.time()
    last_attempt = CLOSE_ATTEMPTS.get(ticket, 0.0)
    if now - last_attempt < 5.0:
        return False, f"Fermeture {ticket} en attente avant nouvelle tentative."
    CLOSE_ATTEMPTS[ticket] = now
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, "Prix indisponible pour fermeture."
    is_buy = position["direction"] == "BUY"
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": symbol,
        "volume": float(position["lot"]),
        "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
        "price": float(tick.bid if is_buy else tick.ask),
        "deviation": 40,
        "magic": MAGIC,
        # Keep the broker comment short. Some MT5 brokers reject long comments
        # before the request reaches the market.
        "comment": "AT close",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    started = time.perf_counter()
    result = send_deal(request)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = bool(result is not None and int(result.retcode) in {
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_DONE_PARTIAL,
        mt5.TRADE_RETCODE_PLACED,
    })
    append_jsonl(
        "learning_events.jsonl",
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "EXIT",
            "ok": ok,
            "ticket": ticket,
            "symbol": symbol,
            "direction": position["direction"],
            "profit_seen": float(position.get("profit") or 0),
            "reason": reason,
            "retcode": int(result.retcode) if result is not None else None,
            "comment": str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error()),
            "latency_ms": latency_ms,
        },
    )
    if ok:
        CLOSE_ATTEMPTS.pop(ticket, None)
        return True, f"Fermeture {ticket} {reason}: OK."
    detail = str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error())
    retcode = int(result.retcode) if result is not None else None
    return False, f"Fermeture {ticket} {reason}: REFUSEE ({retcode}: {detail})."


def position_exit_reason(
    position: dict,
    pos_params: dict,
    position_analysis: dict,
    protection_state_name: str,
    session_state_name: str,
    peak: float,
    age: float,
) -> str:
    profit = float(position.get("profit") or 0)
    review_sec = max(30, int(pos_params.get("position_review_sec", 120)))
    opposite = "SELL" if position.get("direction") == "BUY" else "BUY"
    threshold = float(position_analysis.get("learned_threshold") or pos_params.get("confidence_min", 62))
    reversal = (
        position_analysis.get("signal") == opposite
        and float(position_analysis.get("confidence") or 0)
        >= threshold + float(pos_params.get("signal_reversal_margin", 7))
    )

    # Reaching the session target stops new entries, but must not liquidate
    # positions that were already open. Only a critical hard lock may force
    # an immediate protection exit.
    if protection_state_name == "HARD_LOCK":
        return "PROTECTION"
    if session_state_name in {"PRECLOSE", "CLOSED"}:
        return "SESSION"
    if peak >= float(pos_params.get("profit_lock_trigger", 0.30)):
        drawdown = float(pos_params.get("profit_lock_drawdown", 0.12))
        if profit > 0 and profit <= peak - drawdown:
            return "PROFIT_TRAIL"
    min_positive_exit = max(0.0, float(pos_params.get("min_positive_exit", 0.05)))
    # Si le module Capture Rebond est actif, on ne ferme JAMAIS sur signal inversé.
    # La position principale reste ouverte — le rebond est géré par auto_rebond_step.
    rebond_enabled = bool(pos_params.get("rebond_enabled", True))
    if not rebond_enabled:
        # Fermeture sur signal inversé uniquement si module rebond désactivé
        if age >= review_sec and reversal and profit >= min_positive_exit:
            return "SIGNAL_REVERSED_POSITIVE"
        if (
            age >= review_sec
            and reversal
            and profit <= -abs(float(pos_params.get("emergency_loss_limit", 3.0)))
        ):
            return "CATASTROPHIC_PROTECTION"
    # Fermeture sur profit cible atteint
    if age >= max(review_sec, int(pos_params.get("max_hold_sec", 45))) and profit >= float(
        pos_params.get("profit_target", 0.50)
    ):
        return "TARGET"
    return ""


# ── Fonctions du module Capture Rebond ────────────────────────────────────────

def detect_sd_zones(symbol: str, timeframes: list[str] | None = None) -> list[dict]:
    """Détecte les zones d'offre (Supply) et de demande (Demand) sur plusieurs
    timeframes. Une zone est identifiée par une consolidation serrée suivie d'une
    bougie impulsive forte. Retourne les zones actives triées par force décroissante."""
    if mt5 is None:
        return []
    if timeframes is None:
        timeframes = ["M5", "M15", "M30", "H1"]
    zones: list[dict] = []
    for tf in timeframes:
        rates = mt5.copy_rates_from_pos(symbol, tf_const(tf), 0, 200)
        if rates is None or len(rates) < 20:
            continue
        current_price = float(rates[-1][4])
        for i in range(4, len(rates) - 2):
            # Bougie impulsive = range de la bougie >= 1.8x la moyenne des 4 précédentes
            candle_range = abs(float(rates[i][2]) - float(rates[i][3]))
            prev_ranges = [abs(float(rates[j][2]) - float(rates[j][3])) for j in range(i - 4, i)]
            avg_range = sum(prev_ranges) / len(prev_ranges) if prev_ranges else 0
            if avg_range <= 0 or candle_range < avg_range * 1.6:
                continue
            open_c = float(rates[i][1])
            close_c = float(rates[i][4])
            high_c = float(rates[i][2])
            low_c = float(rates[i][3])
            is_bullish = close_c > open_c
            # Zone de demande : base de la bougie haussière (rebond potentiel vers le haut)
            # Zone d'offre  : sommet de la bougie baissière (rejet potentiel vers le bas)
            if is_bullish:
                zone_top = max(open_c, close_c)
                zone_bot = min(open_c, close_c)
                zone_type = "DEMAND"
            else:
                zone_top = max(open_c, close_c)
                zone_bot = min(open_c, close_c)
                zone_type = "SUPPLY"
            # Compter combien de fois le prix a touché cette zone depuis
            touches = 0
            for j in range(i + 1, min(i + 60, len(rates))):
                future_low = float(rates[j][3])
                future_high = float(rates[j][2])
                if future_low <= zone_top and future_high >= zone_bot:
                    touches += 1
            # Fraîcheur: les zones récentes valent plus (index plus élevé = plus récent)
            recency_score = (i / len(rates)) * 30
            # Force globale de la zone
            strength = min(100, int(
                (candle_range / max(avg_range, 1e-9) - 1) * 25
                + touches * 8
                + recency_score
            ))
            if strength < 25:
                continue
            zones.append({
                "type": zone_type,
                "top": round(zone_top, 5),
                "bot": round(zone_bot, 5),
                "mid": round((zone_top + zone_bot) / 2, 5),
                "strength": strength,
                "touches": touches,
                "timeframe": tf,
                "distance": round(abs(current_price - (zone_top + zone_bot) / 2), 5),
                "candle_index": i,
            })
    # Dédoublonner les zones très proches (même niveau, TF différents)
    merged: list[dict] = []
    for z in sorted(zones, key=lambda x: -x["strength"]):
        too_close = any(abs(z["mid"] - m["mid"]) < z["mid"] * 0.0003 for m in merged)
        if not too_close:
            merged.append(z)
    return sorted(merged, key=lambda x: x["distance"])


def nearest_obstacle(current_price: float, direction: str, zones: list[dict]) -> dict | None:
    """Retourne la zone la plus proche dans la direction du rebond
    (résistance pour un BUY contra, support pour un SELL contra).
    Cible fermeture AVANT le niveau — marge de 20% de la zone."""
    if not zones:
        return None
    if direction == "BUY":
        # Cherche la zone SUPPLY la plus proche au-dessus du prix actuel
        # dont la cible (20% avant le bas) est elle-même au-dessus du prix actuel.
        # Les zones très larges produisent sinon une cible sous le prix → fermeture immédiate.
        candidates = sorted(
            [z for z in zones if z["type"] == "SUPPLY" and z["bot"] > current_price],
            key=lambda z: z["bot"],
        )
        for zone in candidates:
            target = zone["bot"] - (zone["top"] - zone["bot"]) * 0.2
            if target > current_price:
                return {"zone": zone, "target_price": round(target, 5)}
        return None
    else:
        # Cherche la zone DEMAND la plus proche en-dessous du prix actuel
        # dont la cible (20% après le haut) est elle-même en-dessous du prix actuel.
        candidates = sorted(
            [z for z in zones if z["type"] == "DEMAND" and z["top"] < current_price],
            key=lambda z: -z["top"],
        )
        for zone in candidates:
            target = zone["top"] + (zone["top"] - zone["bot"]) * 0.2
            if target < current_price:
                return {"zone": zone, "target_price": round(target, 5)}
        return None


def rebond_lot(main_lot: float, zone_strength: int, params: dict, is_demo: bool) -> float:
    """Calcule le lot du rebond selon la force de la zone détectée.
    Plus la zone est forte, plus le lot est agressif (jusqu'au lot_max).
    Le lot est toujours capé par les limites de sécurité existantes."""
    sym_params = params.get("symbols", {}).get("XAUUSD", {})
    lot_min = float(sym_params.get("lot_min", 0.01))
    lot_max = float(sym_params.get("lot_max", 0.10))
    hard_cap = HARD_DEMO_LOT_CAP if is_demo else HARD_REAL_LOT_CAP
    if zone_strength >= 80:
        # Zone très forte → lot maximum pour maximiser le gain rapide
        lot = lot_max
    elif zone_strength >= 65:
        # Zone forte → double du lot principal
        lot = min(main_lot * 2, lot_max)
    else:
        # Zone modérée → lot standard
        lot = main_lot
    lot = max(lot_min, min(lot, lot_max, hard_cap))
    # Arrondir au step 0.01
    lot = round(round(lot / 0.01) * 0.01, 3)
    return lot


def should_open_rebond(
    symbol_key: str,
    symbol: str,
    positions: list[dict],
    analysis: dict,
    zones: list[dict],
    params: dict,
) -> tuple[bool, str, dict | None]:
    """Décide si on doit ouvrir une position contra-tendance de rebond.
    Retourne (ok, raison, info_rebond_ou_None)."""
    global REBOND_STATE
    # Déjà un rebond actif
    if REBOND_STATE.get("active"):
        return False, "Rebond déjà actif.", None
    # Cooldown entre deux rebonds (utilise le paramètre rebond_cooldown_sec)
    cooldown = float(params.get("rebond_cooldown_sec", 180))
    if time.time() - float(REBOND_STATE.get("last_rebond_at", 0)) < cooldown:
        return False, "Cooldown rebond en cours.", None
    # Pas de zones identifiées
    if not zones:
        return False, "Aucune zone S&D détectée.", None
    # Chercher une position principale ouverte par le bot
    bot_positions = [p for p in positions if p.get("symbol_key") == symbol_key
                     and p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    if not bot_positions:
        return False, "Aucune position principale ouverte.", None
    main_pos = bot_positions[0]
    main_dir = str(main_pos.get("direction", ""))
    if main_dir not in ("BUY", "SELL"):
        return False, "Direction principale inconnue.", None
    # La contra-direction est l'opposé de la position principale
    contra_dir = "BUY" if main_dir == "SELL" else "SELL"
    # Vérifier que l'analyse multi-TF confirme un rebond contra probable
    score_buy = float(analysis.get("score_buy", 0))
    score_sell = float(analysis.get("score_sell", 0))
    rsi_val = float(analysis.get("rsi", 50))
    # Signal contra-tendance : seuil abaissé à 50% pour capter les corrections
    # Le signal principal ne doit pas être trop écrasant (< 90%)
    main_score = score_sell if contra_dir == "BUY" else score_buy
    if main_score >= 90:
        return False, f"Signal principal trop fort ({main_score:.0f}%) — rebond trop risqué.", None
    if contra_dir == "BUY":
        contra_score = score_buy
        rsi_ok = rsi_val <= 40
    else:
        contra_score = score_sell
        rsi_ok = rsi_val >= 60
    if contra_score < 50 and not rsi_ok:
        return False, f"Signal contra ({contra_score:.0f}%) insuffisant pour rebond.", None
    # Obtenir le prix actuel via le nom MT5 résolu
    tick = mt5.symbol_info_tick(symbol) if mt5 else None
    if tick is None:
        return False, "Prix actuel indisponible.", None
    current_price = float(tick.bid if contra_dir == "SELL" else tick.ask)
    obstacle = nearest_obstacle(current_price, contra_dir, zones)
    if obstacle is None:
        return False, f"Aucune zone obstacle trouvée en {contra_dir}.", None
    zone = obstacle["zone"]
    target = obstacle["target_price"]
    # Le potentiel de pip doit valoir le coup (minimum 8 pips pour XAU)
    pip_potential = abs(target - current_price)
    if pip_potential < 0.80:  # 0.80 = ~8 pips XAUUSD
        return False, f"Potentiel rebond trop faible ({pip_potential:.2f} pts).", None
    # Zone suffisamment forte (utilise le paramètre rebond_min_zone_strength)
    min_strength = int(params.get("rebond_min_zone_strength", 35))
    if zone["strength"] < min_strength:
        return False, f"Zone trop faible (force {zone['strength']} < {min_strength}).", None
    return True, "Rebond autorisé.", {
        "direction": contra_dir,
        "target_price": target,
        "zone": zone,
        "current_price": current_price,
        "pip_potential": pip_potential,
    }


def check_close_rebond(symbol: str) -> tuple[bool, str]:
    """Vérifie si la position de rebond doit être fermée.
    Conditions: prix proche de la cible, signal contra s'affaiblit,
    ou durée maximale atteinte (90 secondes)."""
    global REBOND_STATE
    if not REBOND_STATE.get("active") or not REBOND_STATE.get("ticket"):
        return False, ""
    if mt5 is None:
        return False, ""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, ""
    now = time.time()
    direction = str(REBOND_STATE.get("direction", ""))
    target = float(REBOND_STATE.get("target_price", 0))
    open_price = float(REBOND_STATE.get("open_price", 0))
    current = float(tick.bid if direction == "BUY" else tick.ask)
    age = now - float(REBOND_STATE.get("opened_at", now))
    # Fermeture si prix atteint la cible (90% du chemin)
    if direction == "BUY" and current >= target:
        return True, "Cible rebond atteinte (résistance approchée)."
    if direction == "SELL" and current <= target:
        return True, "Cible rebond atteinte (support approché)."
    # Fermeture si le rebond repart contre nous (stop 20 pips)
    if direction == "BUY" and current < open_price - 2.00:
        return True, "Stop rebond: prix retourné contre le BUY contra."
    if direction == "SELL" and current > open_price + 2.00:
        return True, "Stop rebond: prix retourné contre le SELL contra."
    # Fermeture temporelle maximale (60 secondes)
    if age >= 60:
        return True, "Durée maximale rebond atteinte (60s)."
    return False, ""


def auto_rebond_step(
    params: dict,
    symbol_key: str,
    symbol: str,
    positions: list[dict],
    analysis: dict,
    allow_real: bool,
    is_demo: bool,
) -> dict:
    """Étape principale du module Capture Rebond.
    Appelée à chaque cycle de auto_trade_step après la gestion des positions normales.
    Gère l'ouverture et la fermeture des positions de rebond contra-tendance."""
    global REBOND_STATE
    rebond_enabled = bool(params.get("rebond_enabled", True))
    if not rebond_enabled:
        return {"rebond_active": False, "reason": "Module Capture Rebond désactivé."}

    # ── 1. Fermeture du rebond en cours ──────────────────────────────────────
    if REBOND_STATE.get("active") and REBOND_STATE.get("ticket"):
        ticket = int(REBOND_STATE["ticket"])
        should_close, close_reason = check_close_rebond(symbol)
        if should_close:
            # Trouver la position MT5 correspondante
            rebond_pos = next(
                (p for p in positions if int(p.get("ticket", 0)) == ticket),
                None,
            )
            if rebond_pos:
                rebond_profit = float(rebond_pos.get('profit', 0))
                ok, msg = close_bot_position(rebond_pos, f"REBOND_{close_reason[:20]}")
                if ok:
                    log(f"[REBOND] Fermé: {close_reason} | Profit: {rebond_profit:.2f}", "SUCCESS")
                    REBOND_STATE["active"] = False
                    REBOND_STATE["ticket"] = None
                    REBOND_STATE["last_rebond_at"] = time.time()
                    # ── Phase 3 : Renfort dans le sens principal à la résistance ──
                    # Si le rebond s'est fermé à la résistance (cible atteinte)
                    # → c'est le meilleur endroit pour renforcer la position principale
                    if "Cible" in close_reason and rebond_profit > 0:
                        main_dir = REBOND_STATE.get("main_direction")
                        if main_dir in ("BUY", "SELL"):
                            sym_params = params.get("symbols", {}).get(symbol_key, {})
                            main_lot = float(sym_params.get("lot", 0.05))
                            lot_renfort = {
                                "effective_lot": main_lot,
                                "reason": "Renfort Phase 3 — résistance atteinte après rebond",
                            }
                            ok_r, msg_r, _ = open_position(
                                symbol_key, symbol, main_dir,
                                params, lot_renfort, analysis, allow_real,
                            )
                            if ok_r:
                                log(f"[REBOND Phase3] Renfort {main_dir} ouvert à la résistance.", "SUCCESS")
                            else:
                                log(f"[REBOND Phase3] Renfort refusé: {msg_r}", "WARNING")
                    return {"rebond_active": False, "last_action": f"REBOND fermé: {close_reason}"}
                else:
                    log(f"[REBOND] Fermeture échouée: {msg}", "ERROR")
            else:
                # Position déjà fermée automatiquement (TP atteint par MT5)
                log("[REBOND] Position rebond déjà fermée par MT5 (TP).", "INFO")
                REBOND_STATE["active"] = False
                REBOND_STATE["ticket"] = None
                REBOND_STATE["last_rebond_at"] = time.time()
        return {
            "rebond_active": True,
            "direction": REBOND_STATE.get("direction"),
            "target": REBOND_STATE.get("target_price"),
            "reason": "Rebond en cours, surveillance active.",
        }

    # ── 2. Scan des zones S&D (toutes les 30 secondes) ───────────────────────
    now = time.time()
    if now - float(REBOND_STATE.get("last_scan", 0)) >= 30:
        REBOND_STATE["zones"] = detect_sd_zones(symbol, ["M5", "M15", "M30", "H1"])
        REBOND_STATE["last_scan"] = now

    zones = REBOND_STATE.get("zones", [])

    # ── 3. Décision d'ouverture du rebond ────────────────────────────────────
    ok, reason, rebond_info = should_open_rebond(symbol_key, symbol, positions, analysis, zones, params)
    if not ok:
        log(f"[REBOND] Bloqué: {reason}", "INFO")
        return {"rebond_active": False, "zones_count": len(zones), "reason": reason}

    # ── 4. Calcul du lot dynamique ────────────────────────────────────────────
    sym_params = params.get("symbols", {}).get(symbol_key, {})
    main_lot = float(sym_params.get("lot", 0.05))
    zone_strength = int(rebond_info["zone"]["strength"])
    lot = rebond_lot(main_lot, zone_strength, params, is_demo)
    lot_info_rebond = {
        "effective_lot": lot,
        "reason": f"Rebond contra-tendance, force zone {zone_strength}",
    }

    # ── 5. Ouverture de la position rebond ────────────────────────────────────
    direction = str(rebond_info["direction"])
    target_price = float(rebond_info["target_price"])
    ok_open, msg_open, event = open_position(
        symbol_key,
        symbol,
        direction,
        params,
        lot_info_rebond,
        analysis,
        allow_real,
    )
    if ok_open and event:
        # Retrouver le ticket de la position qu'on vient d'ouvrir
        time.sleep(0.2)
        fresh_positions = live_positions({symbol_key: symbol})
        # La plus récente position BOT dans la contra-direction
        new_pos = next(
            (p for p in sorted(fresh_positions, key=lambda x: -int(x.get("open_timestamp", 0)))
             if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
             and p.get("direction") == direction
             and p.get("symbol_key") == symbol_key),
            None,
        )
        REBOND_STATE["active"] = True
        REBOND_STATE["ticket"] = int(new_pos["ticket"]) if new_pos else None
        REBOND_STATE["direction"] = direction
        REBOND_STATE["main_direction"] = "SELL" if direction == "BUY" else "BUY"
        REBOND_STATE["open_price"] = float(rebond_info["current_price"])
        REBOND_STATE["target_price"] = target_price
        REBOND_STATE["lot"] = lot
        REBOND_STATE["opened_at"] = time.time()
        log(
            f"[REBOND] {direction} {lot:.3f} ouvert @ {rebond_info['current_price']:.2f} "
            f"| Cible: {target_price:.2f} | Zone {rebond_info['zone']['type']} "
            f"force {zone_strength} ({rebond_info['zone']['timeframe']})",
            "SUCCESS",
        )
        return {
            "rebond_active": True,
            "direction": direction,
            "lot": lot,
            "open_price": rebond_info["current_price"],
            "target_price": target_price,
            "zone_strength": zone_strength,
            "last_action": msg_open,
        }
    else:
        log(f"[REBOND] Ouverture refusée: {msg_open}", "WARNING")
        return {"rebond_active": False, "reason": f"Rebond refusé: {msg_open}"}


# ── Fin module Capture Rebond ──────────────────────────────────────────────────


def auto_trade_step(params: dict, symbol_names: dict[str, str], payload: dict, positions: list[dict]) -> dict:
    state = load_trading_state()
    account = mt5.account_info()
    demo = is_demo_account(account)
    state["allowed"] = bool(account and (demo or state.get("real_confirmed")))
    state["account_mode"] = "DEMO" if demo else "REAL" if account else "-"
    if not account:
        state["enabled"] = False
        state["reason"] = "Compte MT5 indisponible."
        save_trading_state(state)
        return state
    if not demo and not state.get("real_confirmed"):
        state["enabled"] = False
        state["reason"] = "Confirmation explicite requise pour le compte reel."
        save_trading_state(state)
        return state
    if not state.get("enabled"):
        state["reason"] = "Connecte a MT5. En attente d'un clic sur Demarrer."
        save_trading_state(state)
        return state
    permission_granted, permission_reason = mt5_trading_permission()
    if not permission_granted:
        if state.get("reason") != permission_reason:
            log(permission_reason, "ERROR")
        state["enabled"] = False
        state["reason"] = permission_reason
        state["last_error"] = permission_reason
        save_trading_state(state)
        return state

    protection = payload.get("protection", {})
    active = payload.get("active_symbol")
    symbol = symbol_names.get(active)
    symbol_params = params.get("symbols", {}).get(active, {})
    access = payload.get("session_access", {}).get(active, {})
    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    contexts = position_contexts()

    for position in bot_positions:
        pos_params = params.get("symbols", {}).get(position.get("symbol_key"), {})
        profit = float(position.get("profit") or 0)
        context = contexts.get(str(position.get("ticket")), {})
        peak = max(profit, float(context.get("max_profit") or profit))
        age = max(0, time.time() - float(position.get("open_timestamp") or time.time()))
        position_analysis = payload.get("analysis", {}).get(position.get("symbol_key"), {})
        close_reason = position_exit_reason(
            position,
            pos_params,
            position_analysis,
            str(protection.get("state") or ""),
            str(payload.get("session_access", {}).get(position.get("symbol_key"), {}).get("state") or ""),
            peak,
            age,
        )
        if close_reason:
            ok, message = close_bot_position(position, close_reason)
            if "en attente avant nouvelle tentative" not in message:
                log(message, "SUCCESS" if ok else "ERROR")
            state["last_action"] = message
            if not ok:
                state["last_error"] = message
            save_trading_state(state)
            return state

    now = time.time()
    # Exclure la position de rebond du comptage — elle est secondaire
    rebond_ticket = int(REBOND_STATE.get("ticket") or 0)
    symbol_bot_positions = [
        p for p in bot_positions
        if p.get("symbol_key") == active
        and int(p.get("ticket", 0)) != rebond_ticket
    ]
    # Pour le comptage max, on compte TOUTES les positions principales
    # (pas seulement dans le sens du signal actuel)
    symbol_main_positions = symbol_bot_positions
    max_positions = max(
        1,
        min(
            HARD_AUTO_POSITION_CAP,
            int(params.get("auto_max_positions", 2)),
            int(symbol_params.get("max_positions", 5)),
        ),
    )
    # Réserver 1 slot pour le rebond
    rebond_enabled = bool(params.get("rebond_enabled", True))
    effective_max = max(1, max_positions - 1) if rebond_enabled and max_positions > 1 else max_positions
    if len(symbol_main_positions) >= effective_max:
        state["reason"] = f"Max {effective_max} positions sur {active} (1 réservé rebond)."
        save_trading_state(state)
        return state

    decision = payload.get("simulated_decision", {})
    if not symbol or not decision.get("eligible"):
        reason = str(decision.get("reason") or "Aucun signal eligible.")
        if state.get("reason") != reason:
            log(reason, "INFO")
        state["reason"] = reason
        save_trading_state(state)
        return state
    if not access.get("entries_allowed"):
        state["reason"] = str(access.get("reason") or "Session fermee.")
        save_trading_state(state)
        return state

    cadence = max(1, int(symbol_params.get("cadence_sec", 30)))
    last_attempt = max(
        float(state.get("last_entry_at", 0)),
        float(state.get("last_attempt_at", 0)),
    )
    if now - last_attempt < cadence:
        state["reason"] = "Cadence minimale en cours."
        save_trading_state(state)
        return state
    entry_times = [value for value in state.get("entry_times", []) if now - float(value) < 3600]
    max_hour = max(1, int(symbol_params.get("max_trades_hour", 120)))
    if len(entry_times) >= max_hour:
        state["reason"] = "Limite de trades par heure atteinte."
        state["entry_times"] = entry_times
        save_trading_state(state)
        return state

    analysis = payload.get("analysis", {}).get(active, {})
    if symbol_main_positions:
        directions = {position.get("direction") for position in symbol_main_positions}
        if str(decision.get("signal")) not in directions:
            # Autoriser l'inversion si le multi-timeframe confirme fortement le retournement
            signal = str(decision.get("signal") or "WAIT")
            mtf_bias = str(analysis.get("multi_timeframe_bias") or "RANGE")
            confidence = float(analysis.get("confidence") or 0)
            score_gap = float(analysis.get("score_gap") or 0)
            threshold = float(analysis.get("learned_threshold") or symbol_params.get("confidence_min", 62))
            reversal_confirmed = (
                (signal == "SELL" and mtf_bias == "BEARISH")
                or (signal == "BUY" and mtf_bias == "BULLISH")
            ) and confidence >= threshold + 15 and score_gap >= 20
            if not reversal_confirmed:
                state["reason"] = "Signal oppose a la position principale ouverte; nouvelle entree bloquee."
                save_trading_state(state)
                return state
        if not bool(params.get("reinforcement_enabled", True)):
            state["reason"] = "Renfort desactive dans les parametres."
            save_trading_state(state)
            return state
        first_profit = max(float(position.get("profit") or 0) for position in symbol_main_positions)
        threshold = float(analysis.get("learned_threshold") or symbol_params.get("confidence_min", 62))
        confidence = float(analysis.get("confidence") or 0)
        margin = max(1.0, float(params.get("reinforcement_min_confidence_margin", 5)))
        required_gap = max(1.0, float(params.get("reinforcement_min_score_gap", 15)))
        trend = str(analysis.get("trend") or "RANGE")
        fast_signal = str(analysis.get("fast_signal") or "WAIT")
        signal = str(decision.get("signal") or "WAIT")
        trend_confirms = (
            (signal == "BUY" and trend == "BULLISH")
            or (signal == "SELL" and trend == "BEARISH")
        )
        score_gap = float(analysis.get("score_gap") or 0)
        if first_profit < 0 and not (
            confidence >= threshold + margin
            and score_gap >= required_gap
        ):
            state["reason"] = "Renfort refuse: signal insuffisant pour renforcer en negatif."
            save_trading_state(state)
            return state
        newest_open = max(float(position.get("open_timestamp") or 0) for position in symbol_main_positions)
        reinforcement_pause = max(10, int(params.get("reinforcement_cooldown_sec", 30)))
        if newest_open and now - newest_open < reinforcement_pause:
            state["reason"] = f"Renfort en attente: {int(reinforcement_pause - (now - newest_open))} s."
            save_trading_state(state)
            return state
    learned = payload.get("learning", {}).get("symbols", {}).get(active, {})
    if learned.get("last_outcome") == "LOSS" and learned.get("last_closed_at"):
        try:
            closed_at = datetime.fromisoformat(str(learned["last_closed_at"]))
            if closed_at.tzinfo is None:
                closed_at = closed_at.astimezone()
            elapsed = (datetime.now(timezone.utc) - closed_at.astimezone(timezone.utc)).total_seconds()
            cooldown = max(0, int(symbol_params.get("cooldown_after_loss_sec", 75)))
            if elapsed < cooldown:
                state["reason"] = f"Pause apres perte: {int(cooldown - elapsed)} s restantes."
                save_trading_state(state)
                return state
        except ValueError:
            pass
    lot_info = payload.get("lot_safety", {}).get(active, {})
    approved_by_server, server_reply = server_trade_confirmation(
        params,
        active,
        symbol,
        decision,
        analysis,
        payload,
        positions,
        lot_info,
    )
    state["last_server_decision"] = server_reply
    if not approved_by_server:
        reason = str(server_reply.get("reason") or "Entree bloquee par validation IA serveur.")
        server_signal = str(server_reply.get("decision") or "WAIT")
        server_confidence = float(server_reply.get("confidence") or 0)
        message = f"Validation IA serveur: {server_signal} {server_confidence:.1f}% - {reason}"
        if state.get("reason") != message:
            log(message, "INFO")
        state["reason"] = message
        save_trading_state(state)
        return state
    state["last_attempt_at"] = now
    save_trading_state(state)
    ok, message, _ = open_position(
        active,
        symbol,
        str(decision.get("signal")),
        params,
        lot_info,
        analysis,
        bool(demo or state.get("real_confirmed")),
    )
    log(message, "SUCCESS" if ok else "ERROR")
    state["last_action"] = message
    state["reason"] = message
    if ok:
        state["last_entry_at"] = now
        state["entry_times"] = [*entry_times, now]
        state["last_error"] = ""
    else:
        state["last_error"] = message
    save_trading_state(state)

    # ── Module Capture Rebond ──────────────────────────────────────────────────
    # Exécuté après la logique principale. Gère les positions contra-tendance
    # sur rebonds sans interférer avec la position principale.
    if symbol and active and bool(params.get("rebond_enabled", True)):
        rebond_result = auto_rebond_step(
            params,
            active,
            symbol,
            positions,
            payload.get("analysis", {}).get(active, {}),
            bool(demo or state.get("real_confirmed")),
            demo,
        )
        state["rebond"] = rebond_result
        save_trading_state(state)
    # ── Fin module Capture Rebond ──────────────────────────────────────────────

    return state


def fast_confirmation_state(
    signal: str,
    fast_signal: str,
    trend: str,
    confidence: float,
    confidence_min: float,
    score_gap: float,
    min_score_gap: float,
) -> tuple[bool, bool]:
    if signal not in {"BUY", "SELL"}:
        return False, False
    if fast_signal in {signal, "WAIT"}:
        return False, False
    # Si le fast_signal est dans le sens contraire mais que la confiance
    # principale est très forte (≥ confidence_min + 10) → on laisse passer
    # pour que le module Capture Rebond puisse gérer le rebond
    if confidence >= confidence_min + 10:
        return False, True
    trend_confirms = (
        (signal == "BUY" and trend == "BULLISH")
        or (signal == "SELL" and trend == "BEARISH")
    )
    strong_primary_signal = bool(
        trend_confirms
        and confidence >= confidence_min + 6
        and score_gap >= min_score_gap * 2
    )
    return not strong_primary_signal, strong_primary_signal


def status_payload(params: dict, symbol_names: dict[str, str], trades: list[dict], positions: list[dict]) -> dict:
    account = mt5.account_info() if mt5 else None
    learning = load_learning_state()
    status_symbols = {}
    analyses = {}
    for key, name in symbol_names.items():
        tick = mt5.symbol_info_tick(name) if mt5 else None
        info = mt5.symbol_info(name) if mt5 else None
        tick_price = float(tick.bid) if tick else 0
        spread = round(float(tick.ask - tick.bid), 2) if tick else 0
        sym_trades = [t for t in trades if t.get("symbol_key") == key]
        sym_positions = [p for p in positions if p.get("symbol_key") == key]
        status_symbols[key] = {
            "name": name,
            "label": SYMBOLS[key]["label"],
            "price": round(tick_price, 2),
            "spread": spread,
            "trade_mode": int(info.trade_mode) if info else None,
            "positions": sym_positions,
            "stats": stats(sym_trades, sym_positions),
            "candles": symbol_candles(name, params.get("symbols", {}).get(key, {})),
        }
        analyses[key] = symbol_analysis(
            name,
            {**params, **params.get("symbols", {}).get(key, {})},
            key,
            learning,
        )

    all_stats = stats(trades, positions)
    bot_stats = stats([t for t in trades if t.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    external_stats = stats(
        [t for t in trades if t.get("origin") == "EXTERNAL_AI"],
        [p for p in positions if p.get("origin") == "EXTERNAL_AI"],
    )
    manual_stats = stats(
        [t for t in trades if t.get("origin") == "MANUAL"],
        [p for p in positions if p.get("origin") == "MANUAL"],
    )
    today_stats = daily_stats(trades, positions)
    account_login = int(account.login) if account else None
    session_stats = application_session_stats(trades, positions, account_login)
    protection = protection_state(params, session_stats, account_login)
    lot_safety = lot_safety_state(params, account, symbol_names)
    access = {
        key: session_access(key, params.get("symbols", {}).get(key, {}))
        for key in SYMBOLS
    }
    active = params.get("active_symbol", "XAUUSD")
    if active not in symbol_names and symbol_names:
        active = next(iter(symbol_names.keys()))
    active_analysis = analyses.get(active, {})
    active_access = access.get(active, {"state": "CLOSED", "entries_allowed": False, "reason": "Actif indisponible."})
    active_lot_safety = lot_safety.get(active, {"rejected": True, "reason": "Lot non valide."})
    protection_blocks = protection["state"] in {"WARNING", "HARD_LOCK", "TARGET_REACHED"}
    lot_blocks = bool(active_lot_safety.get("rejected"))
    confidence_min = float(
        active_analysis.get("learned_threshold")
        or params.get("symbols", {}).get(active, {}).get(
            "confidence_min",
            params.get("confidence_min", 62),
        )
    )
    signal = active_analysis.get("signal", "WAIT")
    confidence = float(active_analysis.get("confidence", 0) or 0)
    score_gap = float(active_analysis.get("score_gap", 0) or 0)
    min_score_gap = max(3.0, float(params.get("min_score_gap", 8)))
    edge_position = float(active_analysis.get("edge_position", 50) or 50)
    edge_limit = max(5.0, min(45.0, float(params.get("edge_zone_pct", 20))))
    fast_signal = str(active_analysis.get("fast_signal", "WAIT"))
    trend = str(active_analysis.get("trend", "RANGE"))
    rsi_value = float(active_analysis.get("rsi", 50) or 50)
    decision_signal = signal
    decision_confidence = confidence
    reversal_signal = str(active_analysis.get("reversal_signal", "WAIT"))
    reversal_confidence = float(active_analysis.get("reversal_confidence", 0) or 0)
    reversal_reason = str(active_analysis.get("reversal_reason", ""))
    edge_blocks = bool(
        params.get("anti_top_bottom", True)
        and (
            (signal == "BUY" and edge_position >= 100 - edge_limit)
            or (signal == "SELL" and edge_position <= edge_limit)
        )
    )
    reversal_min = max(
        52.0,
        confidence_min - float(params.get("symbols", {}).get(active, {}).get("signal_reversal_margin", 7)),
    )
    reversal_trend_ok = bool(
        trend == "RANGE"
        or (reversal_signal == "BUY" and trend == "BULLISH")
        or (reversal_signal == "SELL" and trend == "BEARISH")
    )
    reversal_fast_ok = bool(fast_signal in {reversal_signal, "WAIT"})
    reversal_applied = bool(
        edge_blocks
        and reversal_signal in {"BUY", "SELL"}
        and reversal_signal != signal
        and reversal_confidence >= reversal_min
        and reversal_trend_ok
        and reversal_fast_ok
    )
    if reversal_applied:
        decision_signal = reversal_signal
        decision_confidence = reversal_confidence
        edge_blocks = False
    fast_blocks, fast_override = fast_confirmation_state(
        decision_signal,
        fast_signal,
        trend,
        decision_confidence,
        confidence_min,
        score_gap,
        min_score_gap,
    )
    if reversal_applied and fast_blocks and fast_signal == signal:
        fast_blocks = False
        fast_override = True
    rsi_extreme = bool(
        (decision_signal == "BUY" and rsi_value >= 70)
        or (decision_signal == "SELL" and rsi_value <= 20)
    )
    rsi_hard_extreme = bool(
        (decision_signal == "BUY" and rsi_value >= 88)
        or (decision_signal == "SELL" and rsi_value <= 10)
    )
    direction_trend_confirms = bool(
        (decision_signal == "BUY" and trend == "BULLISH")
        or (decision_signal == "SELL" and trend == "BEARISH")
    )
    strategy_mode = str(params.get("strategy_mode") or "scalping_fast")
    mtf_bias = str(active_analysis.get("multi_timeframe_bias") or "RANGE")
    quant_veto = bool(active_analysis.get("quant_veto"))
    mtf_blocks = bool(
        strategy_mode in {"combined", "long_analysis"}
        and mtf_bias in {"BULLISH", "BEARISH"}
        and (
            (decision_signal == "BUY" and mtf_bias == "BEARISH")
            or (decision_signal == "SELL" and mtf_bias == "BULLISH")
        )
        and not reversal_applied
    )
    rsi_override = bool(
        rsi_extreme
        and not rsi_hard_extreme
        and fast_signal == decision_signal
        and direction_trend_confirms
        and decision_confidence >= confidence_min + 12
        and score_gap >= min_score_gap * 2
    )
    rsi_blocks = rsi_extreme and not rsi_override
    gap_blocks = decision_signal in {"BUY", "SELL"} and score_gap < min_score_gap and not reversal_applied
    eligible = bool(
        decision_signal in {"BUY", "SELL"}
        and active_access.get("entries_allowed")
        and not protection_blocks
        and not lot_blocks
        and not edge_blocks
        and not rsi_blocks
        and not fast_blocks
        and not gap_blocks
        and not mtf_blocks
        and not quant_veto
    )
    if quant_veto:
        decision_reason = (
            f"Entree bloquee par le gouverneur quantitatif: risque de regime "
            f"{float(active_analysis.get('quant_regime_risk', 0)):.0f}%."
        )
    elif protection_blocks:
        decision_reason = protection["reason"]
    elif lot_blocks:
        decision_reason = active_lot_safety.get("reason")
    elif not active_access.get("entries_allowed"):
        decision_reason = active_access.get("reason")
    elif edge_blocks:
        if reversal_signal in {"BUY", "SELL"} and reversal_signal != signal:
            decision_reason = (
                f"Entree bloquee: {signal} en zone extreme; reanalyse {reversal_signal} "
                f"insuffisante ({reversal_confidence:.1f}% / {reversal_min:.1f}%)."
            )
        else:
            decision_reason = "Entree bloquee: achat en zone haute ou vente en zone basse; inverse non confirme."
    elif reversal_applied:
        decision_reason = reversal_reason or f"Zone extreme: reanalyse inverse en {decision_signal}."
    elif rsi_blocks:
        decision_reason = f"Entree bloquee: RSI {rsi_value:.1f} en zone extreme."
    elif rsi_override:
        decision_reason = (
            f"Signal {decision_signal} fort confirme: RSI {rsi_value:.1f} eleve, "
            "mais tendance et confirmation rapide concordantes."
        )
    elif fast_blocks:
        decision_reason = f"Entree bloquee: signal principal {signal}, confirmation rapide {fast_signal}."
    elif gap_blocks:
        decision_reason = f"Entree bloquee: ecart BUY/SELL {score_gap:.1f}, minimum {min_score_gap:.1f}."
    elif mtf_blocks:
        decision_reason = f"Entree bloquee: mode {strategy_mode}, tendance large {mtf_bias} contre {decision_signal}."
    elif decision_signal == "WAIT":
        decision_reason = (
            f"En attente d'un signal: confiance {decision_confidence:.1f}%, "
            f"seuil requis {confidence_min:.1f}%."
        )
    elif fast_override:
        decision_reason = (
            f"Signal {signal} fort et tendance {trend}: "
            f"entree autorisee malgre le rebond rapide {fast_signal}."
        )
    else:
        decision_reason = f"Signal {decision_signal} eligible a {decision_confidence:.1f}%."
    simulated_decision = {
        "mode": "SIMULATION",
        "symbol": active,
        "signal": decision_signal,
        "raw_signal": signal,
        "confidence": decision_confidence,
        "raw_confidence": confidence,
        "confidence_min": confidence_min,
        "fast_signal": fast_signal,
        "fast_override": fast_override,
        "rsi_override": rsi_override,
        "reversal_applied": reversal_applied,
        "reversal_min": round(reversal_min, 1),
        "reversal_reason": reversal_reason,
        "strategy_mode": strategy_mode,
        "multi_timeframe_bias": mtf_bias,
        "score_gap": score_gap,
        "min_score_gap": min_score_gap,
        "eligible": eligible,
        "reason": decision_reason,
    }
    return {
        "version": VERSION,
        "state": "connected" if account else "disconnected",
        "mode": "DEMO" if account and ("demo" in str(account.server).lower() or int(account.trade_mode) == 0) else "REAL" if account else "-",
        "account": int(account.login) if account else None,
        "server": str(account.server) if account else "",
        "balance": round(float(account.balance), 2) if account else 0,
        "equity": round(float(account.equity), 2) if account else 0,
        "margin": round(float(account.margin), 2) if account else 0,
        "free_margin": round(float(account.margin_free), 2) if account else 0,
        "active_symbol": active,
        "strategy_profile": params.get("strategy_profile", {}),
        "symbols": status_symbols,
        "analysis": analyses,
        "learning": learning,
        "ai_server": AI_SERVER_STATE,
        "signal": active_analysis.get("signal", "WAIT"),
        "confidence": active_analysis.get("confidence", 0),
        "score_buy": active_analysis.get("score_buy", 0),
        "score_sell": active_analysis.get("score_sell", 0),
        "stats": all_stats,
        "session_stats": session_stats,
        "origin_stats": {
            "ALPHATRADE": bot_stats,
            "EXTERNAL_AI": external_stats,
            "MANUAL": manual_stats,
        },
        "today_stats": today_stats,
        "protection": protection,
        "lot_safety": lot_safety,
        "session_access": access,
        "simulated_decision": simulated_decision,
        "positions": positions,
        "timestamp": int(time.time()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AlphaTrade MT5 monitoring engine")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Write one status/history snapshot, then exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log(f"AlphaTrade engine v{VERSION} - data: {DATA_DIR}")
    params = effective_params_for_strategy(merge_params())
    conn = db_conn()
    microstructure = MicrostructureObserver(DATA_DIR)

    if mt5 is None:
        log(f"MetaTrader5 indisponible: {MT5_IMPORT_ERROR}", "ERROR")
        write_json(
            "status.json",
            {
                "version": VERSION,
                "state": "missing_mt5",
                "error": MT5_IMPORT_ERROR,
                "timestamp": int(time.time()),
                "stats": stats([], []),
                "positions": [],
                "symbols": {},
                "analysis": {},
            },
        )
        return 3 if args.once else wait_for_stop_without_mt5()

    if not initialize_mt5(params):
        log(f"MT5 initialize refuse: {mt5.last_error()}", "ERROR")
        return 2

    account = mt5.account_info()
    log(f"MT5 connecte - compte {account.login if account else '?'} - serveur {account.server if account else '?'}")
    if not args.once:
        reset_session_state(int(account.login) if account else None, 0.0)
        log("Nouvelle session AlphaTrade ouverte; historique MT5 conserve.", "SUCCESS")
    startup_state = load_trading_state()
    startup_state["enabled"] = False
    startup_state["real_confirmed"] = False
    startup_state["reason"] = "Application ouverte en lecture MT5. Cliquez sur Demarrer pour autoriser les nouvelles positions."
    save_trading_state(startup_state)
    account_key = (int(account.login), str(account.server)) if account else None
    symbol_names = {}
    for key in SYMBOLS:
        name = resolve_symbol(key)
        if name:
            symbol_names[key] = name
            log(f"Symbole actif: {key} -> {name}", "SUCCESS")
        else:
            log(f"Symbole introuvable: {key}", "WARNING")

    last_history = 0.0
    last_ai_sync = 0.0
    last_microstructure = 0.0
    last_hyperliquid = 0.0
    ai_bootstrap_attempted = False
    last_command_timestamp = int((read_json("command.json", {}) or {}).get("timestamp") or 0)
    trades: list[dict] = []
    while True:
        params = effective_params_for_strategy(merge_params())
        cmd = read_json("command.json", {}) or {}
        command_timestamp = int(cmd.get("timestamp") or 0)
        is_new_command = command_timestamp > last_command_timestamp
        if cmd.get("command") == "STOP_MONITOR" and is_new_command:
            log("Commande STOP_MONITOR recue.")
            break
        if cmd.get("command") == "ENABLE_TRADING" and is_new_command:
            trading_state = load_trading_state()
            account_now = mt5.account_info()
            real_confirmed = bool((cmd.get("payload") or {}).get("confirm_real"))
            permission_granted, permission_reason = mt5_trading_permission()
            if not permission_granted:
                trading_state["enabled"] = False
                trading_state["real_confirmed"] = False
                trading_state["reason"] = permission_reason
                trading_state["last_error"] = permission_reason
                log(permission_reason, "ERROR")
            elif account_now and (is_demo_account(account_now) or real_confirmed):
                trading_state["enabled"] = True
                trading_state["real_confirmed"] = bool(real_confirmed and not is_demo_account(account_now))
                trading_state["reason"] = "IA demarree: prises de position autorisees."
                trading_state["last_error"] = ""
                log("IA demarree: prises de position autorisees.", "SUCCESS")
            else:
                trading_state["enabled"] = False
                trading_state["real_confirmed"] = False
                trading_state["reason"] = "Activation refusee: confirmation requise."
                trading_state["last_error"] = trading_state["reason"]
                log(trading_state["reason"], "WARNING")
            save_trading_state(trading_state)
        if cmd.get("command") == "DISABLE_TRADING" and is_new_command:
            trading_state = load_trading_state()
            trading_state["enabled"] = False
            trading_state["real_confirmed"] = False
            trading_state["reason"] = "IA arretee: nouvelles prises de position bloquees."
            save_trading_state(trading_state)
            log("IA arretee: nouvelles prises de position bloquees.")
        if cmd.get("command") == "RESET_LEARNING" and is_new_command:
            save_learning_state(default_learning_state())
            save_position_contexts({})
            log("Memoire d'apprentissage reinitialisee pour XAUUSD et EURUSD.", "SUCCESS")

        live_account = mt5.account_info()
        live_account_key = (int(live_account.login), str(live_account.server)) if live_account else None
        if live_account_key != account_key:
            account_key = live_account_key
            symbol_names = {}
            log(
                f"Changement de compte MT5 detecte: {live_account.login if live_account else '?'} - "
                f"{live_account.server if live_account else '?'}"
            )
            for key in SYMBOLS:
                name = resolve_symbol(key)
                if name:
                    symbol_names[key] = name
                    log(f"Symbole actif: {key} -> {name}", "SUCCESS")
                else:
                    log(f"Symbole introuvable: {key}", "WARNING")
            if live_account:
                reset_session_state(int(live_account.login), 0.0)
                log("Nouvelle session AlphaTrade initialisee pour ce compte.", "SUCCESS")

        positions = live_positions(symbol_names)
        now = time.time()
        if now - last_history > 2:
            trades = sync_history(conn, symbol_names)
            write_json("trades.json", {"trades": trades, "ts": int(time.time())})
            last_history = now
        if cmd.get("command") == "NEW_SESSION" and is_new_command:
            account_now = mt5.account_info()
            account_login = int(account_now.login) if account_now else None
            session_now = application_session_stats(trades, positions, account_login)
            state_now = protection_state(params, session_now, account_login)
            bot_positions = [position for position in positions if position.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
            if state_now.get("daily_locked"):
                log("Nouvelle session refusee: la protection journaliere est verrouillee.", "WARNING")
            elif bot_positions:
                log("Nouvelle session refusee: des positions AlphaTrade sont encore ouvertes.", "WARNING")
            else:
                reset_session_state(
                    account_login,
                    0.0,
                )
                log(
                    "Nouvelle session AlphaTrade demarree; positions externes et historique MT5 conserves.",
                    "SUCCESS",
                )
            last_command_timestamp = command_timestamp
        elif is_new_command:
            last_command_timestamp = command_timestamp
        preliminary_learning = load_learning_state()
        if bool(params.get("microstructure_enabled", True)):
            micro_interval = max(1, int(params.get("microstructure_interval_sec", 2)))
            if time.time() - last_microstructure >= micro_interval:
                for key, name in symbol_names.items():
                    tick = mt5.symbol_info_tick(name)
                    if tick:
                        microstructure.observe_mt5_tick(key, tick)
                last_microstructure = time.time()
            if (
                bool(params.get("hyperliquid_observer_enabled", False))
                and time.time() - last_hyperliquid >= 5
            ):
                microstructure.poll_hyperliquid(params.get("hyperliquid_symbols") or ["BTC", "ETH"])
                last_hyperliquid = time.time()
        preliminary_analyses = {
            key: symbol_analysis(
                name,
                {**params, **params.get("symbols", {}).get(key, {})},
                key,
                preliminary_learning,
            )
            for key, name in symbol_names.items()
        }
        ai_interval = max(2, int(params.get("ai_sync_interval_sec", 5)))
        if time.time() - last_ai_sync >= ai_interval:
            update_ai_server_state(
                params,
                symbol_names,
                preliminary_analyses,
                train_missing=not ai_bootstrap_attempted,
            )
            ai_bootstrap_attempted = True
            last_ai_sync = time.time()
        if bool(params.get("reinforcement_enabled", True)):
            track_position_contexts(positions, trades, preliminary_analyses, preliminary_learning)
        payload = status_payload(params, symbol_names, trades, positions)
        payload["microstructure"] = microstructure.snapshot()
        if args.once:
            auto_state = load_trading_state()
            auto_state["allowed"] = is_demo_account(mt5.account_info())
            auto_state["reason"] = "Mode test --once: aucun ordre envoye."
        else:
            auto_state = auto_trade_step(params, symbol_names, payload, positions)
            positions = live_positions(symbol_names)
            payload = status_payload(params, symbol_names, trades, positions)
            payload["microstructure"] = microstructure.snapshot()
        payload["auto_trading"] = auto_state
        write_json("status.json", payload)
        if args.once:
            break
        time.sleep(0.5)

    mt5.shutdown()
    return 0


def wait_for_stop_without_mt5() -> int:
    while True:
        cmd = read_json("command.json", {}) or {}
        if cmd.get("command") == "STOP_MONITOR":
            return 0
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
