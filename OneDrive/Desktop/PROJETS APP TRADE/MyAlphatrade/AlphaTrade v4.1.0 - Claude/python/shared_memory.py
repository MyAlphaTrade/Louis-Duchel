"""Shared Market Memory -- fondation v5.1.0 (9 des 14 compartiments cibles).

Dict Python en memoire du process, recree a chaque redemarrage du moteur --
coherent avec status_payload() deja recalcule a chaque cycle. Pas de nouvelle
base de donnees. Voir Proposition_Technique_MiseEnOeuvre_v5.1.0.html, section
"Shared Market Memory -- implementation".

Chaque compartiment est une enveloppe :
    {created_at, source, confidence, version, valid_until, payload}
jamais une valeur brute -- pour que le CAIO sache qui a produit l'information,
quand, et si elle est encore valable (une information vieille de 30 min n'a
pas la meme valeur sur M1 que sur H4).

Contrat : un agent n'ecrit jamais dans un compartiment qui n'est pas le sien
(applique en code ci-dessous, pas seulement documente -- COMPARTMENT_OWNERS).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_report import AgentReport

# Compartiments 5.1.0 (les 5 restants -- structures/smart_money/liquidity/
# trading_plan/active_scenarios/pending_orders/indicators/gold_knowledge --
# arrivent avec les agents/etapes correspondants, voir Architecture doc).
COMPARTMENT_OWNERS: dict[str, set[str]] = {
    "market_context": {"market_observer"},
    "structures": {"structure_analyst"},
    "smart_money": {"smart_money_analyst"},
    "liquidity": {"structure_analyst"},
    "risk": {"risk_manager"},
    "open_positions": {"position_manager"},
    "trading_objectives": {"trading_mission_manager"},
    "performance": {"performance_manager"},
    "learning_history": {"caio", "trading_coach", "learning_manager"},
    # v5.1.1 Phase 1 (Market Scenario Engine) -- compartiment reserve des
    # maintenant, meme s'il n'est encore ecrit par personne (le Scenario
    # Generator arrive en Phase 2). Voir scenario.py.
    "active_scenarios": {"scenario_generator"},
    # v5.1.1 chantier 4 -- Portfolio Brain : exposition agregee du panier
    # XAUUSD (positions BOT ouvertes simultanement -- principale/renfort/
    # rebond/scalp). Voir portfolio_brain.py.
    "portfolio": {"portfolio_brain"},
}

# Compartiments d'etat factuel (pas une opinion d'agent) -- confidence fixee
# a 100 par defaut, payload = donnee brute plutot qu'un AgentReport.
STATE_COMPARTMENTS = {"open_positions", "performance"}


class SharedMemory:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def _check_owner(self, compartment: str, source: str) -> None:
        if compartment not in COMPARTMENT_OWNERS:
            raise KeyError(f"Compartiment inconnu: {compartment!r} (v5.1.0: {sorted(COMPARTMENT_OWNERS)})")
        allowed = COMPARTMENT_OWNERS[compartment]
        if source not in allowed:
            raise PermissionError(
                f"'{source}' ne peut pas ecrire dans '{compartment}' (autorise: {sorted(allowed)})"
            )

    def write(
        self,
        compartment: str,
        source: str,
        payload: Any,
        *,
        confidence: float | None = None,
        ttl_seconds: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Ecrit une enveloppe. `payload` est soit un dict brut (compartiments
        d'etat), soit un AgentReport.to_dict() (compartiments d'avis)."""
        self._check_owner(compartment, source)
        now = now or datetime.now(timezone.utc)
        if confidence is None:
            if isinstance(payload, dict) and "confidence" in payload:
                confidence = float(payload["confidence"])
            elif compartment in STATE_COMPARTMENTS:
                confidence = 100.0
            else:
                confidence = 0.0
        previous_version = self._store.get(compartment, {}).get("version", 0)
        valid_until = (now + timedelta(seconds=ttl_seconds)).isoformat() if ttl_seconds else None
        envelope = {
            "created_at": now.isoformat(),
            "source": source,
            "confidence": max(0.0, min(100.0, float(confidence))),
            "version": previous_version + 1,
            "valid_until": valid_until,
            "payload": payload,
        }
        self._store[compartment] = envelope
        return envelope

    def write_report(
        self, compartment: str, source: str, report: AgentReport, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Raccourci pour ecrire un AgentReport -- confidence/expiration derives du rapport."""
        now = now or datetime.now(timezone.utc)
        ttl_seconds = None
        if report.expiration:
            try:
                expires_at = datetime.fromisoformat(report.expiration)
                ttl_seconds = max(0.0, (expires_at - now).total_seconds())
            except ValueError:
                ttl_seconds = None
        return self.write(
            compartment, source, report.to_dict(), confidence=report.confidence, ttl_seconds=ttl_seconds, now=now
        )

    def read(self, compartment: str) -> dict[str, Any] | None:
        return self._store.get(compartment)

    def read_payload(self, compartment: str, *, now: datetime | None = None) -> Any | None:
        """Retourne le payload seul, ou None si absent ou perime."""
        envelope = self._store.get(compartment)
        if envelope is None:
            return None
        if self.is_expired(compartment, now=now):
            return None
        return envelope["payload"]

    def is_expired(self, compartment: str, *, now: datetime | None = None) -> bool:
        envelope = self._store.get(compartment)
        if envelope is None or not envelope.get("valid_until"):
            return False
        now = now or datetime.now(timezone.utc)
        try:
            valid_until = datetime.fromisoformat(envelope["valid_until"])
        except ValueError:
            return False
        return now >= valid_until

    def snapshot(self) -> dict[str, Any]:
        """Copie complete pour debug (ex: data/shared_memory_debug.json) --
        jamais une source de verite persistante."""
        return {k: dict(v) for k, v in self._store.items()}


# Instance unique du process -- meme convention que les autres etats globaux
# du moteur (AI_SERVER_STATE, REBOND_META...).
SHARED_MEMORY = SharedMemory()
