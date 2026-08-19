"""
Telegram Notifier — real push notifications for real trading events,
replacing the never-implemented "slackNotifier" stub (see
local_functions.py's _STUB_NOOPS, now removed from that set).

One shared bot for the whole team (2026-08-19, real request — Louis):
each collaborator runs their OWN independent install and MT5 account, but
they all use the SAME bot identity (created once via @BotFather) — only
each person's own chat_id (obtained by messaging the bot once, /start) is
per-install config, read from Parameter.telegram_chat_id.

The bot TOKEN itself is a real secret (2026-08-19, Louis's explicit
choice) — unlike the MT5 magic number or the app's own branding, this is
NOT hardcoded in source: it lives in a local file, same treatment as
alphatg_bridge.py's own bridge_api_key.txt (same directory, same
.gitignore category, never committed). Each machine that should send
real Telegram alerts needs this file placed once — see
_TOKEN_FILE/load_bot_token() below. Unlike the API key, this one is
never auto-generated (there's nothing to generate — it's Louis's real
token from @BotFather), so a missing file means "not configured yet",
handled as a clean, visible error rather than a crash.

Four real triggers (Louis's own choice, 2026-08-19):
  - trade_opened   : a real order was just sent to MT5
  - trade_closed   : a real position closed (see reconcileTrades.js)
  - daily_goal     : daily profit goal reached OR loss protection triggered
  - economic_event : a real high-impact calendar event is imminent
"""
import logging
import os
import time
from datetime import datetime

import requests

import economic_calendar
import local_store

log = logging.getLogger("telegram_notifier")

# Same persistent directory as the entity DB and the bridge API key (see
# alphatg_bridge.py's own _KEY_FILE) — travels together, survives a
# reinstall via the same real BRIDGE_DATA_DIR.
_TOKEN_FILE = os.path.join(os.path.dirname(local_store.DB_PATH), "telegram_bot_token.txt")
REQUEST_TIMEOUT = 10


def load_bot_token():
    """Reads the real bot token from disk. Returns None (never raises) if
    the file doesn't exist yet or is empty — callers must treat that as
    "not configured", not a crash. Re-read on every call (cheap, one small
    file) rather than cached at import time, so placing the file after the
    bridge already started still works without a restart."""
    if os.path.isfile(_TOKEN_FILE):
        with open(_TOKEN_FILE, "r") as f:
            token = f.read().strip()
            if token:
                return token
    return None


def _api_base():
    token = load_bot_token()
    return f"https://api.telegram.org/bot{token}" if token else None

# Economic-event alert: how far ahead to warn, and how often to check.
# 30 min chosen as a real, actionable lead time — enough to close/avoid
# opening a position before real volatility risk, not so early it's noise
# hours in advance. High-impact only (mirrors economic_calendar.score_economic's
# own filter) — Medium/Low events are common enough to be pure noise for a
# phone alert, even though they still feed the "economic" engine's score.
ECONOMIC_ALERT_LEAD_MINUTES = 30
ECONOMIC_ALERT_CHECK_INTERVAL_SEC = 300  # 5 min — the calendar itself is cached 15 min anyway


def send_message(chat_id, text):
    """Real send via Telegram's Bot API. Never raises — a failed
    notification must never be able to break the caller (a real trade
    already happened or is about to; a notification failure is not a
    reason to interrupt that)."""
    if not chat_id:
        return {"ok": False, "error": "chat_id manquant — colle le tien dans Réglages avant d'activer les notifications."}
    api_base = _api_base()
    if not api_base:
        return {"ok": False, "error": f"Bot Telegram non configuré sur cette machine — place le token dans {_TOKEN_FILE}."}
    try:
        resp = requests.post(
            f"{api_base}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        if not data.get("ok"):
            desc = data.get("description") or "Envoi Telegram échoué"
            log.warning("[TELEGRAM] sendMessage failed: %s", desc)
            return {"ok": False, "error": desc}
        return {"ok": True}
    except Exception as e:
        log.warning("[TELEGRAM] sendMessage exception: %s", e)
        return {"ok": False, "error": str(e)}


def _fmt_price(v):
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_money(v):
    try:
        v = float(v)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}$"
    except (TypeError, ValueError):
        return "—"


def format_trade_opened(data):
    direction = data.get("direction")
    emoji = "🟢" if direction == "BUY" else "🔴"
    lines = [
        f"{emoji} *{data.get('symbol')} {direction}* ouvert",
        f"Lot: {data.get('lot')} @ {_fmt_price(data.get('entry_price'))}",
    ]
    if data.get("stop_loss"):
        sl_tp = f"SL: {_fmt_price(data.get('stop_loss'))}"
        if data.get("take_profit"):
            sl_tp += f" | TP: {_fmt_price(data.get('take_profit'))}"
        lines.append(sl_tp)
    if data.get("confidence") is not None:
        lines.append(f"Confiance: {data.get('confidence')}%")
    return "\n".join(lines)


def format_trade_closed(data):
    pnl = data.get("pnl") or 0
    emoji = "✅" if pnl > 0 else ("⚠️" if pnl < 0 else "➖")
    return f"{emoji} *{data.get('symbol')} {data.get('direction') or ''}* clôturé: {_fmt_money(pnl)}".replace("  ", " ")


def format_daily_goal(data):
    reason = data.get("reason")
    pnl = _fmt_money(data.get("pnl"))
    if reason == "protection_triggered":
        return f"🛑 *Protection de perte déclenchée* — PnL du jour: {pnl}\nNouvelles ouvertures suspendues pour aujourd'hui."
    return f"🎯 *Objectif journalier atteint* — PnL du jour: {pnl}"


def format_economic_event(title, country, minutes_until):
    when = "maintenant" if minutes_until <= 1 else f"dans {round(minutes_until)} min"
    return f"📅 *Événement à fort impact* {when}\n{title} ({country})"


_FORMATTERS = {
    "trade_opened": format_trade_opened,
    "trade_closed": format_trade_closed,
    "daily_goal": format_daily_goal,
}


def notify(kind, chat_id, data):
    """Single dispatch point used by alphatg_bridge.py's /functions/telegramNotifier
    route. `kind='test'` sends a fixed friendly confirmation instead of a
    real-data-shaped message (see TelegramNotifierSection.jsx)."""
    if kind == "test":
        text = "✅ Test réussi — les notifications Telegram d'AlphaTrade Global sont bien connectées à ce chat."
    else:
        formatter = _FORMATTERS.get(kind)
        if not formatter:
            return {"ok": False, "error": f"Type de notification inconnu: {kind}"}
        text = formatter(data)
    return send_message(chat_id, text)


def check_and_send_economic_alerts(chat_id, already_sent, lead_minutes=ECONOMIC_ALERT_LEAD_MINUTES):
    """Checks every currently-active symbol's relevant currency for a real
    high-impact event within `lead_minutes`, sends at most one alert per
    real event (deduplicated via `already_sent`, a set the caller owns and
    keeps across calls — see alphatg_bridge.py's scheduler loop)."""
    assets = local_store.list_entities("Asset", query={"is_active": True})
    currencies = set()
    for a in assets:
        currencies.update(economic_calendar._currencies_for_symbol(a.get("symbol")))
    if not currencies:
        return

    now = time.time()
    events = economic_calendar._fetch_calendar()
    for e in events:
        if e.get("impact") != "High" or e.get("country") not in currencies:
            continue
        try:
            event_time = datetime.fromisoformat(e["date"]).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        minutes_until = (event_time - now) / 60
        if not (0 <= minutes_until <= lead_minutes):
            continue
        key = f"{e.get('title')}|{e.get('date')}"
        if key in already_sent:
            continue
        text = format_economic_event(e.get("title"), e.get("country"), minutes_until)
        result = send_message(chat_id, text)
        if result.get("ok"):
            already_sent.add(key)
