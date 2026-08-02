"""Contrat unifie AgentReport (v5.1.0).

Toute fonction d'agent (Risk Manager, Structure Analyst, Smart Money Analyst,
Mission Manager, CAIO...) retourne exactement cette forme -- voir
Proposition_Technique_MiseEnOeuvre_v5.1.0.html, section "Contrat unifie".
Module pur, aucune dependance MT5/reseau, testable isolement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

STATUS_VALUES = ("OK", "DEGRADED", "UNAVAILABLE")
PRIORITY_VALUES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


@dataclass
class AgentReport:
    agent: str
    status: str
    confidence: float
    priority: str
    recommendation: dict[str, Any]
    arguments: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    expiration: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status invalide: {self.status!r} (attendu: {STATUS_VALUES})")
        if self.priority not in PRIORITY_VALUES:
            raise ValueError(f"priority invalide: {self.priority!r} (attendu: {PRIORITY_VALUES})")
        if not isinstance(self.recommendation, dict) or "action" not in self.recommendation:
            raise ValueError("recommendation doit etre un dict structure avec au moins la cle 'action'")
        self.confidence = max(0.0, min(100.0, float(self.confidence)))

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.expiration:
            return False
        now = now or datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(self.expiration)
        except ValueError:
            return False
        return now >= expires_at

    def is_trustworthy(self, now: datetime | None = None) -> bool:
        """Un rapport UNAVAILABLE ou perime n'est jamais exploitable par le CAIO."""
        return self.status != "UNAVAILABLE" and not self.is_expired(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "status": self.status,
            "confidence": self.confidence,
            "priority": self.priority,
            "recommendation": self.recommendation,
            "arguments": list(self.arguments),
            "risks": list(self.risks),
            "expiration": self.expiration,
            "metadata": dict(self.metadata),
        }


def make_expiration(now: datetime | None = None, *, seconds: float) -> str:
    """Horodatage ISO8601 UTC pour le champ `expiration`, `seconds` a partir de `now`."""
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(seconds=seconds)).isoformat()


def make_agent_report(
    agent: str,
    *,
    status: str = "OK",
    confidence: float = 0.0,
    priority: str = "LOW",
    recommendation: dict[str, Any],
    arguments: list[str] | None = None,
    risks: list[str] | None = None,
    ttl_seconds: float | None = None,
    now: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentReport:
    """Fabrique standard -- prefere a l'instanciation directe pour calculer
    l'expiration de facon coherente entre agents (ttl_seconds -> expiration)."""
    expiration = make_expiration(now, seconds=ttl_seconds) if ttl_seconds else None
    return AgentReport(
        agent=agent,
        status=status,
        confidence=confidence,
        priority=priority,
        recommendation=recommendation,
        arguments=list(arguments or []),
        risks=list(risks or []),
        expiration=expiration,
        metadata=dict(metadata or {}),
    )


def sort_by_priority(reports: list[AgentReport]) -> list[AgentReport]:
    """CRITICAL d'abord, puis HIGH/MEDIUM/LOW -- ordre de lecture du CAIO."""
    return sorted(reports, key=lambda r: PRIORITY_ORDER.get(r.priority, len(PRIORITY_ORDER)))
