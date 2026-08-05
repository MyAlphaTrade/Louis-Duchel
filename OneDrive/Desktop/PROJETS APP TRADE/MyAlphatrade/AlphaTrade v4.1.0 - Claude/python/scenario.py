"""Contrat Scenario (v5.1.1) -- Market Scenario Engine.

Correction de Louis du 04/08/2026 : le scenario ne doit pas etre "un signal
d'entree ameliore" ni seulement une preparation de trade -- il doit devenir
la memoire de contexte permanent du marche : pourquoi une zone existe,
pourquoi elle etait valide, combien de fois le prix a reagi dessus, comment
sa sante a evolue, et son resultat final. Sans cette trace, "il restera
juste un filtre sophistique" (citation directe) -- rien n'alimenterait
l'extension future de calibration statistique (toujours v5.1.1, pas une
version separee -- voir Architecture_ScenarioEngine_v5.1.1.html section 8).

Contrat + persistance, module pur (aucune dependance MT5/reseau), testable
isolement -- meme discipline que agent_report.py/shared_memory.py en 5.1.0.
Phase 2 (scenario_generator.py) genere et valide des instances reelles,
branchees en observation dans auto_trade_step() derriere
`scenario_engine_enabled`. L'arbitrage CAIO (Phase 3) et le Dynamic Position
Manager (Phase 4) restent a construire."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

DIRECTION_VALUES = ("BUY", "SELL")
STATUS_VALUES = ("CANDIDATE", "VALIDATED", "ACTIVE", "DEGRADED", "INVALIDATED", "EXPIRED", "COMPLETED")
TERMINAL_STATUSES = ("INVALIDATED", "EXPIRED", "COMPLETED")

# Transitions autorisees -- empeche un scenario de "sauter" une etape (ex:
# CANDIDATE -> ACTIVE sans passer par VALIDATED, ce qui contredirait le role
# du Scenario Validator : "le CAIO choisit parmi des scenarios deja valides,
# il ne cree pas lui-meme leur validite").
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "CANDIDATE": {"VALIDATED", "EXPIRED", "INVALIDATED"},
    "VALIDATED": {"ACTIVE", "EXPIRED", "INVALIDATED"},
    "ACTIVE": {"DEGRADED", "INVALIDATED", "EXPIRED", "COMPLETED"},
    "DEGRADED": {"ACTIVE", "INVALIDATED", "EXPIRED", "COMPLETED"},
    "INVALIDATED": set(),
    "EXPIRED": set(),
    "COMPLETED": set(),
}


@dataclass
class ScenarioEvent:
    """Une ligne de la trace de raisonnement -- le 'pourquoi' a chaque
    transition, pas seulement le 'quoi'. C'est cette liste qui fait du
    Scenario une memoire de contexte plutot qu'un simple objet de
    preparation de trade."""
    at: str
    status: str
    note: str
    scenario_health: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"at": self.at, "status": self.status, "note": self.note, "scenario_health": self.scenario_health}


@dataclass
class Scenario:
    scenario_id: str
    symbol_key: str
    direction: str
    zone: dict[str, float]  # {"low": ..., "high": ...}
    confluences: list[str] = field(default_factory=list)
    scenario_confidence: float = 0.0  # score a la creation -- jamais "probability" tant que la
    # calibration statistique reelle (extension future, toujours v5.1.1) n'existe pas (renommage explicite demande par Louis)
    scenario_confidence_at_entry: float | None = None  # fige a l'activation, ne bouge plus ensuite
    scenario_health: float | None = None  # vivant, recalcule en continu une fois ACTIVE/DEGRADED --
    # distinct de scenario_confidence_at_entry (le prix peut etre loin de invalidation_price
    # pendant que l'idee est deja en train de mourir)
    market_context: dict[str, Any] = field(default_factory=dict)  # trend/volatility/session/atr/timeframe_alignment
    invalidation_price: float | None = None
    targets: list[dict[str, Any]] = field(default_factory=list)  # [{"price": ..., "label": ...}, ...]
    anchor_plan: dict[str, Any] = field(default_factory=dict)  # {"entry": ..., "sl": ..., "tp": ...}
    scalp_allowed: bool = False
    status: str = "CANDIDATE"
    reaction_count: int = 0  # nb de fois ou le prix a reellement reagi dans la zone --
    # lu par le Scenario Validator (Phase 2), pas seulement "le prix est passe par la"
    simulated_scalp_count: int = 0  # nb d'opportunites de scalp detectees par le Dynamic
    # Position Manager (Phase 4) -- jamais de position reelle en Phase 4, juste la trace
    outcome: str | None = None  # resultat final a la cloture (ex: WIN/LOSS/BREAKEVEN/UNUSED)
    outcome_profit: float | None = None
    anchor_ticket: int | None = None  # ticket MT5 reel de la position d'ancrage --
    # None tant qu'aucune n'a ete tentee (execution reelle activee le 05/08/2026,
    # demande explicite de Louis ; None reste la norme en observation pure)
    anchor_status: str = "NONE"  # NONE | OPEN | FAILED | CLOSED -- une seule
    # tentative d'ouverture par scenario, jamais retentee en boucle (voir
    # execute_scenario_anchor() dans alphatrade_engine.py)
    executed_scalp_count: int = 0  # nb de VRAIS scalps executes -- distinct de
    # simulated_scalp_count (detection pure, inchange, sert toujours au
    # Learning). Voir execute_scenario_scalp().
    last_scalp_executed_at: str | None = None  # horodatage ISO du dernier
    # scalp reellement execute -- base du cooldown (scenario_scalp_cooldown_sec)
    maximum_validity_min: int = 45
    created_at: str = ""
    last_evaluated_at: str = ""
    expires_at: str | None = None
    history: list[ScenarioEvent] = field(default_factory=list)
    last_validation: dict[str, bool] = field(default_factory=dict)  # dernier resultat du Scenario
    # Validator (zone_touched/reaction/risk_ok/market_ok) -- pas un historique,
    # juste l'etat de la derniere evaluation (l'historique complet est deja
    # dans `history` via les transitions/notes)

    def __post_init__(self) -> None:
        if self.direction not in DIRECTION_VALUES:
            raise ValueError(f"direction invalide: {self.direction!r} (attendu: {DIRECTION_VALUES})")
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status invalide: {self.status!r} (attendu: {STATUS_VALUES})")
        if not isinstance(self.zone, dict) or "low" not in self.zone or "high" not in self.zone:
            raise ValueError("zone doit etre un dict avec au moins les cles 'low' et 'high'")
        self.scenario_confidence = max(0.0, min(100.0, float(self.scenario_confidence)))
        if self.scenario_health is not None:
            self.scenario_health = max(0.0, min(100.0, float(self.scenario_health)))

    def transition(self, new_status: str, note: str, *, now: datetime | None = None) -> None:
        """Seul point d'entree pour changer `status` -- refuse une transition
        non autorisee et journalise systematiquement dans `history`, jamais
        un changement silencieux."""
        if new_status not in STATUS_VALUES:
            raise ValueError(f"status invalide: {new_status!r} (attendu: {STATUS_VALUES})")
        allowed = ALLOWED_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"transition refusee: {self.status} -> {new_status} (autorise depuis {self.status}: {sorted(allowed) or 'aucune'})"
            )
        now = now or datetime.now(timezone.utc)
        self.status = new_status
        self.last_evaluated_at = now.isoformat()
        self.history.append(
            ScenarioEvent(at=now.isoformat(), status=new_status, note=note, scenario_health=self.scenario_health)
        )

    def update_health(self, scenario_health: float, note: str, *, now: datetime | None = None) -> None:
        """Met a jour la sante vivante sans changer de statut -- utilise par
        le futur Dynamic Position Manager (Phase 4) a chaque cycle tant que
        le scenario est ACTIVE/DEGRADED. Journalise dans `history` pour que
        la trajectoire complete (79 -> 55 -> 32) reste consultable, pas
        seulement la derniere valeur."""
        now = now or datetime.now(timezone.utc)
        self.scenario_health = max(0.0, min(100.0, float(scenario_health)))
        self.last_evaluated_at = now.isoformat()
        self.history.append(
            ScenarioEvent(at=now.isoformat(), status=self.status, note=note, scenario_health=self.scenario_health)
        )

    def record_reaction(self) -> None:
        """Incremente le compteur de reactions du prix dans la zone."""
        self.reaction_count += 1

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.expires_at:
            return False
        now = now or datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False
        return now >= expires_at

    def health_trajectory(self) -> list[float]:
        """Suite des valeurs de scenario_health observees dans `history`,
        dans l'ordre chronologique -- pratique pour l'UI (courbe 79→55→32)
        et pour un futur calcul de vitesse de degradation."""
        return [e.scenario_health for e in self.history if e.scenario_health is not None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "symbol_key": self.symbol_key,
            "direction": self.direction,
            "zone": dict(self.zone),
            "confluences": list(self.confluences),
            "scenario_confidence": self.scenario_confidence,
            "scenario_confidence_at_entry": self.scenario_confidence_at_entry,
            "scenario_health": self.scenario_health,
            # health_curve/activated : alias de commodite (deduits de history/status),
            # pour un log directement exploitable sans rejouer les transitions --
            # demande explicite de Louis (04/08/2026) sur le format scenario_log.jsonl.
            "health_curve": self.health_trajectory(),
            "activated": self.status not in ("CANDIDATE", "VALIDATED"),
            "validation": dict(self.last_validation),
            "market_context": dict(self.market_context),
            "invalidation_price": self.invalidation_price,
            "targets": [dict(t) for t in self.targets],
            "anchor_plan": dict(self.anchor_plan),
            "scalp_allowed": self.scalp_allowed,
            "status": self.status,
            "reaction_count": self.reaction_count,
            "simulated_scalp_count": self.simulated_scalp_count,
            "outcome": self.outcome,
            "outcome_profit": self.outcome_profit,
            "anchor_ticket": self.anchor_ticket,
            "anchor_status": self.anchor_status,
            "executed_scalp_count": self.executed_scalp_count,
            "last_scalp_executed_at": self.last_scalp_executed_at,
            "maximum_validity_min": self.maximum_validity_min,
            "created_at": self.created_at,
            "last_evaluated_at": self.last_evaluated_at,
            "expires_at": self.expires_at,
            "history": [e.to_dict() for e in self.history],
        }


def make_scenario(
    scenario_id: str,
    symbol_key: str,
    direction: str,
    zone: dict[str, float],
    *,
    confluences: list[str] | None = None,
    scenario_confidence: float = 0.0,
    market_context: dict[str, Any] | None = None,
    invalidation_price: float | None = None,
    targets: list[dict[str, Any]] | None = None,
    anchor_plan: dict[str, Any] | None = None,
    maximum_validity_min: int = 45,
    now: datetime | None = None,
) -> Scenario:
    """Fabrique standard -- calcule created_at/expires_at de facon coherente
    et journalise automatiquement la creation dans `history` (premiere ligne
    de la trace de raisonnement)."""
    now = now or datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=maximum_validity_min)).isoformat()
    scenario = Scenario(
        scenario_id=scenario_id,
        symbol_key=symbol_key,
        direction=direction,
        zone=dict(zone),
        confluences=list(confluences or []),
        scenario_confidence=scenario_confidence,
        market_context=dict(market_context or {}),
        invalidation_price=invalidation_price,
        targets=list(targets or []),
        anchor_plan=dict(anchor_plan or {}),
        maximum_validity_min=maximum_validity_min,
        created_at=now.isoformat(),
        last_evaluated_at=now.isoformat(),
        expires_at=expires_at,
    )
    scenario.history.append(
        ScenarioEvent(at=now.isoformat(), status="CANDIDATE", note="Scenario cree.", scenario_health=None)
    )
    return scenario


def activate_scenario(scenario: Scenario, note: str = "", *, now: datetime | None = None) -> None:
    """VALIDATED -> ACTIVE : fige scenario_confidence_at_entry et initialise
    scenario_health a cette meme valeur (point de depart de la trajectoire
    vivante)."""
    now = now or datetime.now(timezone.utc)
    scenario.scenario_confidence_at_entry = scenario.scenario_confidence
    scenario.scenario_health = scenario.scenario_confidence
    scenario.scalp_allowed = True
    scenario.transition("ACTIVE", note or "Scenario active -- position d'ancrage.", now=now)


def close_scenario(
    scenario: Scenario,
    status: str,
    outcome: str,
    *,
    profit: float | None = None,
    note: str = "",
    now: datetime | None = None,
) -> None:
    """Cloture propre -- seul point d'entree qui remplit `outcome`/
    `outcome_profit`, pour que la future calibration statistique (extension
    v5.1.1, pas une version separee) lise toujours un resultat coherent avec
    le statut terminal."""
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"close_scenario n'accepte que des statuts terminaux {TERMINAL_STATUSES}, recu: {status!r}")
    scenario.outcome = outcome
    scenario.outcome_profit = profit
    scenario.transition(status, note or f"Scenario cloture: {status} ({outcome}).", now=now)
