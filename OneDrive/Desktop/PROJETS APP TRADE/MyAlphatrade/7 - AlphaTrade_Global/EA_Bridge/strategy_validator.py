"""
Strategy Validator — runs every coded strategy from backtest_engine.py
against real candles and decides, by fixed thresholds, which ones are
good enough to trade live. No LLM opinion involved: a strategy earns its
way onto the account by clearing numbers, not by sounding convincing.

Faithful Python port of Dist/base44/shared/strategyValidator.ts.
"""

from backtest_engine import STRATEGY_REGISTRY, run_backtest

# Defaults chosen to be conservative, not optimistic: real spread/slippage
# isn't modeled here, so the backtest edge needs headroom above breakeven.
DEFAULT_THRESHOLDS = {
    "min_trades": 20,
    "min_profit_factor": 1.2,
    "min_win_rate": 30,
    "max_drawdown": 25,
}


def validate_strategy(candles, strategy_name, symbol, capital, risk_percent, thresholds=None):
    thresholds = thresholds or DEFAULT_THRESHOLDS
    result = run_backtest(candles, strategy_name, {"symbol": symbol, "capital": capital, "risk_percent": risk_percent})
    stats = result["stats"]
    reasons = []

    if stats["total_trades"] < thresholds["min_trades"]:
        reasons.append(f"Pas assez de trades pour être statistiquement significatif ({stats['total_trades']} < {thresholds['min_trades']})")
    if stats["profit_factor"] < thresholds["min_profit_factor"]:
        reasons.append(f"Profit factor insuffisant ({stats['profit_factor']} < {thresholds['min_profit_factor']})")
    if stats["win_rate"] < thresholds["min_win_rate"]:
        reasons.append(f"Taux de réussite insuffisant ({stats['win_rate']}% < {thresholds['min_win_rate']}%)")
    if stats["max_drawdown"] > thresholds["max_drawdown"]:
        reasons.append(f"Drawdown maximum trop élevé ({stats['max_drawdown']}% > {thresholds['max_drawdown']}%)")

    passed = len(reasons) == 0
    if passed:
        reasons.append(f"Validée : profit factor {stats['profit_factor']}, {stats['total_trades']} trades, drawdown max {stats['max_drawdown']}%")

    return {"strategy_name": strategy_name, "passed": passed, "stats": stats, "reasons": reasons}


def validate_all_strategies(candles, symbol, capital, risk_percent, thresholds=None):
    return [
        validate_strategy(candles, name, symbol, capital, risk_percent, thresholds)
        for name in STRATEGY_REGISTRY
    ]


def select_best_strategy(results):
    """Among validated strategies, the highest profit factor wins — favors
    consistency of edge over raw trade count or win rate alone."""
    passed = [r for r in results if r["passed"]]
    if not passed:
        return None
    return max(passed, key=lambda r: r["stats"]["profit_factor"])
