"""
Real backtest engine — replays a coded, deterministic strategy bar-by-bar
over real historical candles. No LLM in this file: every trade, price and
statistic here is arithmetic on real MT5 data, reproducible on every run.

Faithful Python port of Dist/base44/shared/backtestEngine.ts.
"""

from indicators import ema, rsi, atr, find_swings, fibonacci_levels
from local_functions import CONTRACT_SIZES, calculate_lot

SWING_LOOKBACK = 3


def _known_swings_at(all_swings, i):
    """Swings a strategy could actually have known about at bar `i` — a swing
    at index j needs SWING_LOOKBACK bars after it to be confirmed, so it
    isn't "visible" until bar j + SWING_LOOKBACK."""
    return [sw for sw in all_swings if sw["index"] + SWING_LOOKBACK < i]


def _build_series(candles):
    closes = [c["close"] for c in candles]
    return {
        "candles": candles,
        "closes": closes,
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "rsi14": rsi(closes, 14),
        "atr14": atr(candles, 14),
        "all_swings": find_swings(candles, SWING_LOOKBACK),
    }


def _trend_following(s, i):
    """Pullback continuation: price dips to EMA50 and closes back on the
    trend side, with EMA50/EMA200 confirming the trend."""
    e50, e200, e50prev = s["ema50"][i], s["ema200"][i], s["ema50"][i - 1]
    if e50 is None or e200 is None or e50prev is None:
        return None
    c = s["candles"][i]
    if e50 > e200 and c["low"] <= e50 and c["close"] > e50:
        return {"direction": "BUY", "rationale": f"Pullback sur EMA50 ({e50:.2f}) en tendance haussière (EMA50>EMA200)"}
    if e50 < e200 and c["high"] >= e50 and c["close"] < e50:
        return {"direction": "SELL", "rationale": f"Pullback sur EMA50 ({e50:.2f}) en tendance baissière (EMA50<EMA200)"}
    return None


def _mean_reversion(s, i):
    """Classic RSI extreme reversal — no trend filter, this strategy fades moves."""
    r, r_prev = s["rsi14"][i], s["rsi14"][i - 1]
    if r is None or r_prev is None:
        return None
    if r_prev < 30 and r >= 30:
        return {"direction": "BUY", "rationale": f"RSI(14) sort de survente ({r_prev:.1f}→{r:.1f})"}
    if r_prev > 70 and r <= 70:
        return {"direction": "SELL", "rationale": f"RSI(14) sort de surachat ({r_prev:.1f}→{r:.1f})"}
    return None


def _breakout_structure(s, i):
    """Break of the last confirmed swing, confirmed by above-average volume."""
    if i < 30:
        return None
    swings = _known_swings_at(s["all_swings"], i)
    last_high = next((sw for sw in reversed(swings) if sw["type"] == "high"), None)
    last_low = next((sw for sw in reversed(swings) if sw["type"] == "low"), None)
    vol_window = s["candles"][max(0, i - 20):i]
    avg_volume = sum(c["tick_volume"] for c in vol_window) / len(vol_window)
    c = s["candles"][i]
    volume_confirmed = c["tick_volume"] > avg_volume * 1.3
    if not volume_confirmed:
        return None
    if last_high and c["close"] > last_high["price"]:
        return {"direction": "BUY", "rationale": f"Cassure du dernier swing high ({last_high['price']:.2f}) avec volume {c['tick_volume'] / avg_volume:.1f}x"}
    if last_low and c["close"] < last_low["price"]:
        return {"direction": "SELL", "rationale": f"Cassure du dernier swing low ({last_low['price']:.2f}) avec volume {c['tick_volume'] / avg_volume:.1f}x"}
    return None


def _smart_money_fibonacci(s, i):
    """Retracement into the 61.8-78.6% golden pocket of the last swing, then a
    bounce back in the direction of that swing."""
    if i < 30:
        return None
    swings = _known_swings_at(s["all_swings"], i)
    last_high = next((sw for sw in reversed(swings) if sw["type"] == "high"), None)
    last_low = next((sw for sw in reversed(swings) if sw["type"] == "low"), None)
    if not last_high or not last_low:
        return None
    direction = "down" if last_high["index"] > last_low["index"] else "up"
    fib = fibonacci_levels(last_high["price"], last_low["price"], direction)
    golden_618 = fib["levels"]["0.618"]
    golden_786 = fib["levels"]["0.786"]
    zone_low, zone_high = (golden_618, golden_786) if golden_618 < golden_786 else (golden_786, golden_618)
    c = s["candles"][i]
    in_zone = c["low"] <= zone_high and c["high"] >= zone_low
    if not in_zone:
        return None
    if direction == "up" and c["close"] > c["open"]:
        return {"direction": "BUY", "rationale": f"Rebond dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) du swing haussier"}
    if direction == "down" and c["close"] < c["open"]:
        return {"direction": "SELL", "rationale": f"Rebond dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) du swing baissier"}
    return None


STRATEGY_REGISTRY = {
    "Trend Following": _trend_following,
    "Mean Reversion": _mean_reversion,
    "Breakout Structure": _breakout_structure,
    "Smart Money + Fibonacci": _smart_money_fibonacci,
}


def is_known_strategy(name):
    return name in STRATEGY_REGISTRY


def evaluate_live_signal(strategy_name, candles):
    """Evaluates whether `strategy_name` would open a position on the most
    recent closed candle — same signal functions as the backtest, just
    called once at the last bar instead of replayed over history. Returns
    None if the strategy is unknown, there isn't enough history, or the
    strategy simply has no signal right now (most of the time)."""
    signal_fn = STRATEGY_REGISTRY.get(strategy_name)
    if not signal_fn or not candles:
        return None
    s = _build_series(candles)
    return signal_fn(s, len(candles) - 1)


def run_backtest(candles, strategy_name, params):
    """Walks the candles bar-by-bar with exactly one open position at a time.
    On the same bar a position could hit both SL and TP, the SL is assumed to
    trigger first — the standard conservative convention for backtests that
    only have OHLC bars, not tick-by-tick data.

    params: {"symbol": str, "capital": float, "risk_percent": float,
             "sl_atr_multiple": float (default 1.5), "tp_atr_multiple": float (default 3)}
    """
    signal_fn = STRATEGY_REGISTRY.get(strategy_name)
    if not signal_fn:
        raise ValueError(f"Stratégie inconnue: {strategy_name}")

    s = _build_series(candles)
    sl_mult = params.get("sl_atr_multiple", 1.5)
    tp_mult = params.get("tp_atr_multiple", 3)
    contract_size = CONTRACT_SIZES.get(params["symbol"].upper(), 100000)
    capital = params["capital"]
    risk_percent = params["risk_percent"]

    trades = []
    open_position = None

    for i in range(1, len(candles)):
        c = candles[i]

        if open_position:
            direction = open_position["direction"]
            stop_loss = open_position["stop_loss"]
            take_profit = open_position["take_profit"]
            entry_price = open_position["entry_price"]
            lot = open_position["lot"]

            hit_sl = c["low"] <= stop_loss if direction == "BUY" else c["high"] >= stop_loss
            hit_tp = c["high"] >= take_profit if direction == "BUY" else c["low"] <= take_profit
            if hit_sl or hit_tp:
                exit_price = stop_loss if hit_sl else take_profit
                pnl = (exit_price - entry_price) * lot * contract_size if direction == "BUY" else (entry_price - exit_price) * lot * contract_size
                pnl_percent = (pnl / capital) * 100
                trades.append({
                    "date": open_position["entry_date"],
                    "entry_date": open_position["entry_date"],
                    "exit_date": c["time"],
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "pnl": round(pnl * 100) / 100,
                    "pnl_percent": round(pnl_percent * 10000) / 10000,
                    "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven",
                    "rationale": open_position["rationale"],
                })
                open_position = None
            continue  # one position at a time — no new entry while one is open

        atr_val = s["atr14"][i]
        if atr_val is None or atr_val <= 0:
            continue

        signal = signal_fn(s, i)
        if not signal:
            continue

        entry_price = c["close"]
        stop_loss = entry_price - atr_val * sl_mult if signal["direction"] == "BUY" else entry_price + atr_val * sl_mult
        take_profit = entry_price + atr_val * tp_mult if signal["direction"] == "BUY" else entry_price - atr_val * tp_mult
        lot = calculate_lot(params["symbol"], entry_price=entry_price, stop_loss=stop_loss, capital=capital, risk_percent=risk_percent)

        open_position = {
            "direction": signal["direction"],
            "entry_price": entry_price,
            "entry_date": c["time"],
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "lot": lot,
            "rationale": signal["rationale"],
        }

    return {"trades": trades, "stats": compute_stats(trades, capital)}


def compute_stats(trades, capital):
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    total_pnl = sum(t["pnl"] for t in trades)
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    equity = capital
    peak = capital
    max_drawdown = 0.0
    for t in trades:
        equity += t["pnl"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, ((peak - equity) / peak) * 100)

    win_rate_frac = (len(wins) / len(trades)) if trades else 0
    avg_win = (gross_win / len(wins)) if wins else 0
    avg_loss = (-gross_loss / len(losses)) if losses else 0
    # Expectancy — the real-world question profit factor and win rate don't
    # answer on their own: "on average, how much does one trade of this
    # system actually make or lose?" A system can have a flattering win
    # rate and still have negative expectancy if losses are large enough,
    # or a low win rate and strongly positive expectancy if wins are big
    # enough (Module 5, Fusion Engine Validation, 2026-08-06).
    expectancy = win_rate_frac * avg_win + (1 - win_rate_frac) * avg_loss

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate_frac * 1000) / 10,
        "total_pnl": round(total_pnl * 100) / 100,
        "total_pnl_percent": round((total_pnl / capital) * 10000) / 100,
        "max_drawdown": round(max_drawdown * 100) / 100,
        "profit_factor": (round((gross_win / gross_loss) * 100) / 100) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0),
        "avg_win": round(avg_win * 100) / 100,
        "avg_loss": round(avg_loss * 100) / 100,
        "expectancy": round(expectancy * 100) / 100,
        "expectancy_percent": round((expectancy / capital) * 10000) / 100 if capital else 0,
        "best_trade": max((t["pnl"] for t in trades), default=0),
        "worst_trade": min((t["pnl"] for t in trades), default=0),
    }
