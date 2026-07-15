from __future__ import annotations

# KB8 — Gestion intelligente de position, module partagé.
#
# Règle fondamentale (rappelée par Louis dès le départ) : rien ici n'est un
# nombre de pips fixe recopié. Tout est calculé à partir des specs réelles du
# broker (tick_value, tick_size, spread) et de ratios configurables (risque,
# risk:reward, fraction de la distance au stop) :
# - calculate_lot() : capital -> risque% -> distance stop -> lot.
# - take_profit_levels() : TP1/TP2/TP3 en multiples risk:reward de la
#   distance au stop, avec un % de clôture partielle configurable par palier.
# - break_even_trigger()/break_even_level() : le passage à Break-Even se
#   déclenche à une fraction de la distance au stop, et le niveau couvre au
#   minimum le spread + une marge de sécurité en ticks — jamais juste le prix
#   d'entrée nu (on se ferait sortir immédiatement par le spread).
# - trailing_stop_level() : distance de trailing en ticks (calibrée broker).
# - manage_position() : orchestrateur qui décide de l'action à prendre selon
#   l'état courant de la position (clôture partielle, passage BE, trailing).
#
# Module pur : ne dépend pas de MT5 — testable isolément. L'exécution réelle
# (clôtures partielles natives MT5, modification du stop) reste hors scope,
# gérée par l'engine au moment de l'intégration.


def calculate_lot(capital: float, risk_pct: float, entry_price: float, stop_price: float,
                   tick_value: float, tick_size: float,
                   lot_min: float = 0.01, lot_max: float = 100.0, lot_step: float = 0.01) -> dict:
    stop_distance = abs(entry_price - stop_price)
    risk_amount = round(capital * (risk_pct / 100.0), 2)
    if stop_distance <= 0 or tick_size <= 0:
        return {"lot": lot_min, "risk_amount": risk_amount, "raw_lot": None, "capped": True,
                "reason": "distance de stop ou tick_size invalide"}
    stop_distance_ticks = stop_distance / tick_size
    loss_per_lot = stop_distance_ticks * tick_value
    if loss_per_lot <= 0:
        return {"lot": lot_min, "risk_amount": risk_amount, "raw_lot": None, "capped": True,
                "reason": "tick_value invalide"}
    raw_lot = risk_amount / loss_per_lot
    lot = max(lot_min, min(lot_max, raw_lot))
    lot = round(round(lot / lot_step) * lot_step, 2)
    return {"lot": lot, "risk_amount": risk_amount, "raw_lot": round(raw_lot, 4),
            "capped": abs(lot - round(raw_lot, 2)) > 1e-9, "reason": None}


def take_profit_levels(entry_price: float, stop_price: float, direction: str,
                        rr_ratios=(1.0, 2.0, 3.0), close_pct=(0.4, 0.3, 0.3)) -> list[dict]:
    if len(rr_ratios) != len(close_pct):
        raise ValueError("rr_ratios et close_pct doivent avoir la meme longueur")
    if abs(sum(close_pct) - 1.0) > 1e-6:
        raise ValueError("close_pct doit sommer a 1.0")
    stop_distance = abs(entry_price - stop_price)
    sign = 1 if direction == "bullish" else -1
    return [
        {"tier": i, "rr": rr, "price": round(entry_price + sign * stop_distance * rr, 5), "close_pct": pct}
        for i, (rr, pct) in enumerate(zip(rr_ratios, close_pct))
    ]


def break_even_trigger(entry_price: float, stop_price: float, direction: str, activation_rr: float = 0.5) -> float:
    stop_distance = abs(entry_price - stop_price)
    sign = 1 if direction == "bullish" else -1
    return round(entry_price + sign * stop_distance * activation_rr, 5)


def break_even_level(entry_price: float, direction: str, spread: float, tick_size: float, buffer_ticks: float = 5) -> float:
    sign = 1 if direction == "bullish" else -1
    safety = spread + buffer_ticks * tick_size
    return round(entry_price + sign * safety, 5)


def trailing_stop_level(current_price: float, direction: str, tick_size: float, trail_ticks: float) -> float:
    sign = -1 if direction == "bullish" else 1
    return round(current_price + sign * trail_ticks * tick_size, 5)


def manage_position(position: dict, levels: list[dict], be_config: dict | None = None,
                     trail_config: dict | None = None) -> dict:
    """position: {entry_price, stop_price, current_price, direction, tp_hit: set[int], be_applied: bool}"""
    direction = position["direction"]
    current = position["current_price"]
    entry = position["entry_price"]
    tp_hit = position.get("tp_hit") or set()

    for level in levels:
        if level["tier"] in tp_hit:
            continue
        reached = (current >= level["price"]) if direction == "bullish" else (current <= level["price"])
        if reached:
            return {"action": "PARTIAL_CLOSE", "tier": level["tier"], "price": level["price"], "close_pct": level["close_pct"]}

    if not position.get("be_applied") and be_config:
        trigger = break_even_trigger(entry, position["stop_price"], direction, be_config.get("activation_rr", 0.5))
        reached = (current >= trigger) if direction == "bullish" else (current <= trigger)
        if reached:
            be_price = break_even_level(entry, direction, be_config["spread"], be_config["tick_size"], be_config.get("buffer_ticks", 5))
            return {"action": "MOVE_TO_BREAK_EVEN", "price": be_price}

    if trail_config and len(tp_hit) >= trail_config.get("activate_after_tier", 1):
        new_stop = trailing_stop_level(current, direction, trail_config["tick_size"], trail_config["trail_ticks"])
        improves = (new_stop > position["stop_price"]) if direction == "bullish" else (new_stop < position["stop_price"])
        if improves:
            return {"action": "TRAIL_STOP", "price": new_stop}

    return {"action": "NONE"}
