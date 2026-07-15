from __future__ import annotations

# KB4 — Fibonacci automatique, module partagé.
#
# Réutilise les swings déjà détectés par KB2 (market_structure.detect_swings) :
# le dernier mouvement (swing précédent -> dernier swing) définit le range de
# retracement. Sens "up" (creux -> sommet, retracement mesuré depuis le
# sommet) ou "down" (sommet -> creux, retracement mesuré depuis le creux) —
# la formule diffère selon le sens, sinon les niveaux sont inversés.
#
# Module pur : ne dépend pas de MT5, prend en entrée une liste de swings déjà
# calculée — testable isolément.

FIBO_RATIOS = (0.382, 0.5, 0.618, 0.705, 0.786)
GOLDEN_ZONE = (0.618, 0.786)  # "zone d'achat privilégiée" (OTE)


def fibonacci_levels(swing_low: float, swing_high: float, direction: str, ratios=FIBO_RATIOS) -> dict:
    span = swing_high - swing_low
    levels = {}
    for r in ratios:
        price = swing_high - span * r if direction == "up" else swing_low + span * r
        levels[r] = round(price, 5)
    return levels


def last_leg(swings: list[dict]):
    """Dernier mouvement : avant-dernier swing -> dernier swing (déjà en
    alternance haut/bas grâce à detect_swings). None si pas assez de swings."""
    if len(swings) < 2:
        return None
    ordered = sorted(swings, key=lambda s: s["index"])
    origin, target = ordered[-2], ordered[-1]
    if origin["type"] == "low" and target["type"] == "high":
        return origin, target, "up"
    if origin["type"] == "high" and target["type"] == "low":
        return origin, target, "down"
    return None


def fibonacci_from_swings(swings: list[dict], ratios=FIBO_RATIOS, golden_zone=GOLDEN_ZONE, current_price: float | None = None) -> dict:
    leg = last_leg(swings)
    if leg is None:
        return {"levels": {}, "direction": None, "swing_low": None, "swing_high": None,
                "golden_zone": None, "in_golden_zone": None, "nearest_level": None}

    origin, target, direction = leg
    swing_low = origin["price"] if direction == "up" else target["price"]
    swing_high = target["price"] if direction == "up" else origin["price"]

    levels = fibonacci_levels(swing_low, swing_high, direction, ratios)
    g_lo = fibonacci_levels(swing_low, swing_high, direction, (golden_zone[0],))[golden_zone[0]]
    g_hi = fibonacci_levels(swing_low, swing_high, direction, (golden_zone[1],))[golden_zone[1]]
    golden_zone_prices = tuple(sorted([g_lo, g_hi]))

    in_golden_zone = None
    nearest_level = None
    if current_price is not None:
        in_golden_zone = golden_zone_prices[0] <= current_price <= golden_zone_prices[1]
        nearest_level = min(levels.items(), key=lambda kv: abs(kv[1] - current_price))

    return {
        "levels": levels,
        "direction": direction,
        "swing_low": swing_low,
        "swing_high": swing_high,
        "golden_zone": golden_zone_prices,
        "in_golden_zone": in_golden_zone,
        "nearest_level": nearest_level,
    }
