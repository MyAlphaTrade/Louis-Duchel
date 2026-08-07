"""
Portfolio Risk Manager — Real Capital Risk Engine, part 2/2 (Module 1 of the
2026-08-06 professional transformation plan).

Part 1 (see local_functions.calculate_lot/build_order) fixed how a SINGLE
trade is sized against real capital. This module answers a different
question: even if each trade is sized correctly on its own, should this
NEW trade be allowed to open at all, given everything already open?

Two real, deterministic checks — no LLM, no guessing:
  1. Portfolio exposure cap — the combined risk still open across every
     position (measured from each position's CURRENT price to its CURRENT
     stop loss, not the original entry — what could still be lost from
     here, not what was risked at entry) plus this new trade's own risk,
     must stay under a cap expressed as % of equity.
  2. Correlation proxy — positions in the same broad asset category
     (crypto/metals/forex/indices/commodities, via the same
     _infer_asset_category heuristic already used by Asset Discovery) are
     treated as correlated: a category maxing out its position count blocks
     a new one, even if the portfolio-wide risk cap alone would allow it.

A third function, consecutive_loss_multiplier(), is adaptive rather than a
hard gate: after a real losing streak, it scales risk_percent DOWN before
calculate_lot ever sees it (wired into build_order — see local_functions.py)
so the system trades smaller while it's actually losing, then returns to
full size the moment a trade closes in profit. It only ever shrinks risk;
it never enlarges it — there is no "revenge sizing up" after a win streak.
"""

from local_store import list_entities

# Conservative, documented defaults — not yet tuned by any backtest (that
# validation is a later phase of the transformation plan, once the Fusion
# Engine Validation harness exists). Deliberately on the cautious side: it
# is much cheaper to loosen a cap later, once real data justifies it, than
# to have shipped one too loose on day one.
DEFAULT_MAX_PORTFOLIO_RISK_PERCENT = 3.0
DEFAULT_MAX_POSITIONS_PER_CATEGORY = 2
CONSECUTIVE_LOSS_THRESHOLD = 3
CONSECUTIVE_LOSS_RISK_MULTIPLIER = 0.5

CONTRACT_SIZES = {
    "XAUUSD": 100, "EURUSD": 100000, "GBPUSD": 100000, "USDJPY": 100000,
    "BTCUSD": 1, "ETHUSD": 1, "SP500": 50, "NAS100": 20,
}


def _infer_asset_category(raw):
    """Mirrors local_functions._infer_asset_category exactly (duplicated,
    not imported, to keep this module import-independent of local_functions —
    it is deliberately a leaf module other things depend on, not the reverse)."""
    import re
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


def _position_open_risk(pos):
    """What could still be lost from here if this position hits its current
    stop — not the original 1R at entry, the REAL remaining exposure right
    now, which is what a portfolio cap needs to measure. Returns 0 for a
    position with no stop loss set rather than crashing, but that is flagged
    separately by the caller (an unprotected position is itself a finding
    worth surfacing, not a silent zero)."""
    sl = pos.get("stop_loss")
    if not sl:
        return 0.0
    current = pos.get("current_price") or pos.get("entry_price") or 0
    lot = pos.get("lot") or 0
    contract_size = CONTRACT_SIZES.get((pos.get("symbol") or "").upper(), 100000)
    return abs(current - sl) * lot * contract_size


def portfolio_exposure_check(symbol, positions, equity, planned_risk_percent,
                              max_portfolio_risk_percent=None, max_positions_per_category=None):
    """Pure function — `positions` is the already-fetched list from
    get_open_positions() (or an empty list), never fetched here. Returns
    {"allowed": bool, "reason": str, "findings": [str, ...]}.

    Fails CLOSED on missing equity: if equity isn't a real positive number,
    this refuses the trade rather than dividing by an unknown — consistent
    with the Real Capital Risk Engine's "no real capital, no order" rule.
    """
    max_portfolio_risk_percent = max_portfolio_risk_percent or DEFAULT_MAX_PORTFOLIO_RISK_PERCENT
    max_positions_per_category = max_positions_per_category or DEFAULT_MAX_POSITIONS_PER_CATEGORY
    positions = positions or []
    findings = []

    if not equity or equity <= 0:
        return {"allowed": False, "reason": "CAPITAL_UNAVAILABLE",
                "findings": ["Capital réel indisponible — impossible d'évaluer l'exposition du portefeuille en toute sécurité."]}

    unprotected = [p for p in positions if not p.get("stop_loss")]
    if unprotected:
        findings.append(f"{len(unprotected)} position(s) ouverte(s) sans stop loss — exposition réelle sous-estimée pour celles-ci.")

    open_risk = sum(_position_open_risk(p) for p in positions)
    planned_risk_amount = equity * (planned_risk_percent / 100 if planned_risk_percent is not None else 0.01)
    projected_total_pct = ((open_risk + planned_risk_amount) / equity) * 100
    findings.append(
        f"Exposition ouverte actuelle : {(open_risk / equity * 100):.2f}% de l'equity. "
        f"Avec ce nouveau trade : {projected_total_pct:.2f}% (plafond {max_portfolio_risk_percent:.2f}%)."
    )
    if projected_total_pct > max_portfolio_risk_percent:
        return {"allowed": False, "reason": "PORTFOLIO_RISK_CAP",
                "findings": findings + [f"Refusé : dépasserait le plafond d'exposition combinée ({max_portfolio_risk_percent:.2f}% de l'equity)."]}

    category = _infer_asset_category(symbol)
    same_category = [p for p in positions if _infer_asset_category(p.get("symbol")) == category]
    findings.append(f"{len(same_category)} position(s) déjà ouverte(s) dans la même catégorie d'actif ({category}).")
    if len(same_category) >= max_positions_per_category:
        return {"allowed": False, "reason": "CORRELATION_CAP",
                "findings": findings + [f"Refusé : {max_positions_per_category} positions maximum autorisées par catégorie corrélée ({category})."]}

    return {"allowed": True, "reason": "OK", "findings": findings}


def consecutive_loss_multiplier(threshold=None, reduction=None, lookback=10):
    """Reads the most recently closed trades (real MT5 outcomes via the
    Trade entity, reconciled by reconcileTrades.js) and, if the last
    `threshold` of them were all losses, returns a risk multiplier below 1.0
    to shrink the next position size. Returns to 1.0 the instant the most
    recent closed trade was a win — no gradual "cooldown", the system trades
    at full size again as soon as it has real evidence it should.

    This never LOOSENS risk beyond the trader's own configured
    max_risk_percent — it only ever multiplies it down, and 1.0 (no change)
    is the default when there isn't enough history to say anything."""
    threshold = threshold or CONSECUTIVE_LOSS_THRESHOLD
    reduction = reduction if reduction is not None else CONSECUTIVE_LOSS_RISK_MULTIPLIER

    recent = list_entities("Trade", query={"status": "closed"}, sort="-closed_at", limit=lookback)
    streak = 0
    for t in recent:
        pnl = t.get("pnl")
        if pnl is None:
            break
        if pnl < 0:
            streak += 1
        else:
            break
    if streak >= threshold:
        return reduction
    return 1.0
