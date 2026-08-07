"""
Auto Optimization Lab — Module 4 of the 2026-08-07 professional
transformation plan, first slice: automatic validation of an asset before
it's trusted for autonomous trading, and periodically after, without
requiring anyone to manually launch a backtest.

Runs the SAME harness already built and proven in Phase 4
(fusion_backtest.py + strategy_validator.py) — no new decision logic here,
only automation of WHEN it runs and WHAT HAPPENS with the result.

Trigger points (wired in alphatg_bridge.py):
  - Immediately when a symbol is added to the active watchlist (Asset
    entity created) — see _enqueue_asset_validation.
  - Periodically for every symbol already on the watchlist (see
    ASSET_REVALIDATION_INTERVAL_DAYS below), so a real edge that fades
    over time gets caught even if nobody adds anything new — this is
    exactly the situation from the 2026-08-07 finding: a system can look
    fine when it was last checked and quietly stop being fine.

Never auto-removes an asset from the watchlist, and never blocks trading
on a symbol by itself — only ever writes a result (AssetValidation entity)
and a clear AppLog notification. The trader keeps the final say on what
stays active, the same principle already applied everywhere else in this
system that touches real capital.
"""

from datetime import datetime, timedelta, timezone

from local_store import create_entity, list_entities, update_entity
from strategy_validator import validate_fusion_backtest

MULTI_TIMEFRAMES = ["D1", "H4", "M15", "M5"]
VALIDATION_PERIOD_DAYS = 90
ASSET_REVALIDATION_INTERVAL_DAYS = 7


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_asset(symbol, fetch_candles_fn, capital=1000, risk_percent=1, period_days=VALIDATION_PERIOD_DAYS):
    """fetch_candles_fn: same signature as alphatg_bridge.fetch_candles_direct
    (symbol, timeframe, count, from_str, to_str) -> (candles, resolved, error).
    Stores one AssetValidation record per symbol (overwritten each run, the
    history isn't kept — only "what does the latest real check say" matters
    for a live trading decision) and always logs the outcome, pass or fail."""
    from_str = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    h1, resolved, error = fetch_candles_fn(symbol, "H1", 5000, from_str, None)
    if not h1:
        create_entity("AppLog", {
            "level": "warning", "category": "asset",
            "message": f"Validation automatique de {symbol} impossible : {error or 'aucune donnée H1 disponible'}.",
            "source": "assetValidation", "payload": {"symbol": symbol},
        })
        return {"ok": False, "error": error or f"Aucune donnée H1 pour {symbol}"}

    mtf = {}
    for tf in MULTI_TIMEFRAMES:
        c, _resolved, _error = fetch_candles_fn(symbol, tf, 5000, from_str, None)
        if c:
            mtf[tf] = c

    result = validate_fusion_backtest(symbol, "H1", h1, mtf_candles=mtf, capital=capital, risk_percent=risk_percent)
    record = {
        "symbol": symbol,
        "status": "passed" if result["passed"] else "failed",
        "checked_at": _now_iso(),
        "period_days": period_days,
        "stats": result["stats"],
        "reasons": result["reasons"],
    }
    existing = list_entities("AssetValidation", query={"symbol": symbol}, sort="-checked_at", limit=1)
    if existing:
        update_entity("AssetValidation", existing[0]["id"], record)
    else:
        create_entity("AssetValidation", record)

    stats = result["stats"]
    if result["passed"]:
        message = (
            f"{symbol} validé automatiquement ({period_days}j réels) : profit factor {stats['profit_factor']}, "
            f"{stats['total_trades']} trades, win rate {stats['win_rate']}%, drawdown max {stats['max_drawdown']}%."
        )
    else:
        message = (
            f"{symbol} ne passe plus la validation automatique ({period_days}j réels) : "
            + " ; ".join(result["reasons"])
            + " — le trading autonome sur cet actif reste actif, mais mérite d'être revu."
        )
    create_entity("AppLog", {
        "level": "info" if result["passed"] else "warning",
        "category": "asset",
        "message": message,
        "source": "assetValidation",
        "payload": {"symbol": symbol, "passed": result["passed"], "stats": stats},
    })
    return {"ok": True, "passed": result["passed"], "stats": stats, "reasons": result["reasons"]}


def assets_due_for_revalidation():
    """Active watchlist assets (Asset entity, NOT the 799-symbol
    AssetRegistry catalog) that have never been validated, or whose last
    validation is older than ASSET_REVALIDATION_INTERVAL_DAYS."""
    assets = [a for a in list_entities("Asset", limit=500) if a.get("is_active")]
    cutoff = datetime.now(timezone.utc) - timedelta(days=ASSET_REVALIDATION_INTERVAL_DAYS)
    due = []
    for a in assets:
        symbol = a.get("symbol")
        if not symbol:
            continue
        existing = list_entities("AssetValidation", query={"symbol": symbol}, sort="-checked_at", limit=1)
        if not existing:
            due.append(symbol)
            continue
        try:
            checked_at = datetime.fromisoformat(existing[0]["checked_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            due.append(symbol)
            continue
        if checked_at < cutoff:
            due.append(symbol)
    return due
