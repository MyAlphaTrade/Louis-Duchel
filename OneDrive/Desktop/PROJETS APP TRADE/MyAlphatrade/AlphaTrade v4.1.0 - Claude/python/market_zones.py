from __future__ import annotations

# KB3 — Zones importantes, module partagé.
#
# S'appuie sur les swings déjà détectés par KB2 (market_structure.detect_swings) :
# - Support / Résistance : clusters de swings proches en prix (plus il y a de
#   "touches" dans un cluster, plus le niveau est fort).
# - Supply / Demand : le swing d'origine d'un mouvement impulsif (mouvement vers
#   le swing suivant nettement plus grand que la moyenne) — la zone d'où le prix
#   est parti fortement, susceptible de le faire réagir s'il y revient.
# - Zones institutionnelles : confluence — une zone Supply/Demand qui coïncide
#   avec un cluster Support/Résistance déjà touché plusieurs fois (conviction
#   plus forte que chaque signal pris séparément).
#
# Module pur : ne dépend pas de MT5, prend en entrée une liste de swings déjà
# calculée (format detect_swings/classify_swings) — testable isolément.


def support_resistance_zones(swings: list[dict], cluster_tolerance_pct: float = 0.15) -> dict:
    def cluster(points):
        zones: list[dict] = []
        for p in sorted(points, key=lambda s: s["price"]):
            target = None
            for z in zones:
                if abs(p["price"] - z["price"]) / z["price"] * 100 <= cluster_tolerance_pct:
                    target = z
                    break
            if target is None:
                zones.append({"price": p["price"], "touches": [p]})
            else:
                target["touches"].append(p)
                target["price"] = sum(t["price"] for t in target["touches"]) / len(target["touches"])
        return sorted(zones, key=lambda z: -len(z["touches"]))

    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]
    return {"resistance": cluster(highs), "support": cluster(lows)}


def supply_demand_zones(swings: list[dict], impulse_multiplier: float = 1.5) -> list[dict]:
    if len(swings) < 3:
        return []
    ordered = sorted(swings, key=lambda s: s["index"])
    moves = [abs(ordered[i + 1]["price"] - ordered[i]["price"]) for i in range(len(ordered) - 1)]
    avg_move = sum(moves) / len(moves) if moves else 0.0
    if avg_move <= 0:
        return []

    zones = []
    for i in range(len(ordered) - 1):
        origin, target = ordered[i], ordered[i + 1]
        move = abs(target["price"] - origin["price"])
        if move < impulse_multiplier * avg_move:
            continue
        if origin["type"] == "high" and target["price"] < origin["price"]:
            zones.append({"type": "supply", "price": origin["price"], "index": origin["index"], "move": move})
        elif origin["type"] == "low" and target["price"] > origin["price"]:
            zones.append({"type": "demand", "price": origin["price"], "index": origin["index"], "move": move})
    return zones


def institutional_zones(sr_zones: dict, sd_zones: list[dict], price_tolerance_pct: float = 0.15) -> list[dict]:
    """Confluence Supply/Demand + Support/Résistance déjà touché plusieurs fois."""
    result = []
    for sd in sd_zones:
        pool = sr_zones["resistance"] if sd["type"] == "supply" else sr_zones["support"]
        for sr in pool:
            if sr["price"] == 0:
                continue
            if abs(sd["price"] - sr["price"]) / sr["price"] * 100 <= price_tolerance_pct:
                result.append({**sd, "sr_touches": len(sr["touches"]), "sr_price": sr["price"]})
                break
    return result


def market_zones(swings: list[dict], cluster_tolerance_pct: float = 0.15, impulse_multiplier: float = 1.5) -> dict:
    sr = support_resistance_zones(swings, cluster_tolerance_pct)
    sd = supply_demand_zones(swings, impulse_multiplier)
    institutional = institutional_zones(sr, sd, cluster_tolerance_pct)
    return {
        "support": sr["support"],
        "resistance": sr["resistance"],
        "supply_demand": sd,
        "institutional": institutional,
    }
