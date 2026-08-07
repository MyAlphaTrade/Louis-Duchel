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


def _evaluate_stats(stats, thresholds):
    """Shared pass/fail evaluation — used both for the 4 standalone coded
    strategies below and for a full fusion-engine backtest result (see
    fusion_backtest.py / validate_fusion_backtest), so the same bar applies
    to both: no strategy or configuration earns a place in production on
    anything looser than these numbers, regardless of which layer it's
    validating."""
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
    return passed, reasons


def validate_strategy(candles, strategy_name, symbol, capital, risk_percent, thresholds=None):
    thresholds = thresholds or DEFAULT_THRESHOLDS
    result = run_backtest(candles, strategy_name, {"symbol": symbol, "capital": capital, "risk_percent": risk_percent})
    stats = result["stats"]
    passed, reasons = _evaluate_stats(stats, thresholds)
    return {"strategy_name": strategy_name, "passed": passed, "stats": stats, "reasons": reasons}


def validate_fusion_backtest(symbol, primary_timeframe, primary_candles, mtf_candles=None,
                              capital=1000, risk_percent=1, thresholds=None):
    """Same pass/fail bar as the 4 standalone strategies, applied to the
    REAL production decision engine (market_brain's 13-engine fusion) via
    fusion_backtest.run_fusion_backtest() — Module 5, Fusion Engine
    Validation. This is what Auto Optimization Lab (Module 4) will check a
    candidate configuration against before letting it anywhere near a real
    account: nothing enters production on a result this function marks
    passed=False."""
    from fusion_backtest import run_fusion_backtest

    thresholds = thresholds or DEFAULT_THRESHOLDS
    result = run_fusion_backtest(symbol, primary_timeframe, primary_candles, mtf_candles=mtf_candles,
                                  capital=capital, risk_percent=risk_percent)
    stats = result["stats"]
    passed, reasons = _evaluate_stats(stats, thresholds)
    return {"symbol": symbol, "timeframe": primary_timeframe, "passed": passed, "stats": stats,
            "reasons": reasons, "trades": result["trades"]}


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
