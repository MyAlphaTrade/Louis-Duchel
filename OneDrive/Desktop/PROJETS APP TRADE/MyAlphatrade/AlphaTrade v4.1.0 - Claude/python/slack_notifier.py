"""Slack Notifier (v5.1.0) -- notifications via Webhooks entrants, plusieurs
destinations configurables (params['slack_webhooks']), chacune choisissant
quels types d'evenement elle recoit. Contrairement a AlphaTrade Global (dont
le slackNotifier depend d'un connecteur OAuth Base44 desormais retire et
inactif -- _STUB_NOOPS), ceci utilise des Webhooks entrants Slack : aucune
app Slack a publier, aucun jeton a gerer, l'utilisateur cree l'URL lui-meme
dans les reglages de son espace Slack et la colle dans Parametres.

Style visuel inspire de Global (emoji directionnel + Block Kit) + couleur
native Slack via `attachments[].color` (vert '#2eb886' = bonne nouvelle,
rouge marque Slack '#E01E5A' = arret/alerte)."""
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("slack_notifier")

REQUEST_TIMEOUT = 5
SLACK_GREEN = "#2eb886"
SLACK_RED = "#E01E5A"


def notify_slack(params: dict, event_type: str, color: str, blocks: list, text: str) -> None:
    """Envoie a tous les webhooks configures qui ecoutent `event_type`.
    Best-effort : ne leve jamais -- un Slack indisponible ne doit pas casser
    le cycle de trading."""
    destinations = params.get("slack_webhooks") or []
    payload = {"text": text, "attachments": [{"color": color, "blocks": blocks}]}
    body = json.dumps(payload).encode("utf-8")
    for dest in destinations:
        if not dest.get("enabled", True):
            continue
        if event_type not in (dest.get("events") or []):
            continue
        url = str(dest.get("webhook_url") or "").strip()
        if not url:
            continue
        try:
            request = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("[SLACK] Envoi echoue vers '%s': %s", dest.get("name") or "?", e)


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _fields(pairs: list[tuple[str, str]]) -> dict:
    return {"type": "section", "fields": [{"type": "mrkdwn", "text": f"*{k}:*\n{v}"} for k, v in pairs]}


def blocks_caio_go(symbol: str, order_type: str, price, source_agent: str, raison: str) -> tuple[list, str]:
    is_buy = "BUY" in str(order_type or "")
    emoji = "🟢" if is_buy else "🔴"
    header_text = f"{emoji} Gold AI Brain — {order_type} {symbol}"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        _fields([
            ("Prix", f"{price:.2f}" if price is not None else "N/A"),
            ("Agent retenu", source_agent or "N/A"),
        ]),
    ]
    if raison:
        blocks.append(_section(f"*Raison du CAIO :*\n{raison}"))
    return blocks, header_text


def blocks_mission_target(period_label: str, profit: float, target: float) -> tuple[list, str]:
    header_text = f"🎯 Objectif {period_label} atteint — +{profit:.2f}$ / {target:.2f}$"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        _section(f"Le Trading Mission Manager a atteint l'objectif *{period_label}* configure dans AlphaTrade Gold."),
    ]
    return blocks, header_text


def blocks_trading_toggle(enabled: bool, account_mode: str) -> tuple[list, str]:
    emoji = "▶️" if enabled else "⏹️"
    action = "démarré" if enabled else "arrêté"
    now_str = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    header_text = f"{emoji} AlphaTrade — trading {action} ({account_mode})"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        _section(f"Trading {action} à {now_str} — compte *{account_mode}*."),
    ]
    return blocks, header_text
