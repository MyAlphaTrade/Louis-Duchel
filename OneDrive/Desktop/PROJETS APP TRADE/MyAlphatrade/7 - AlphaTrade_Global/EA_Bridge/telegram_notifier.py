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

# Real app logo (2026-08-20, Louis's explicit request) — lives next to this
# file, not the persistent data dir: it's a build asset (see
# build-desktop.js's assets/ copy step), not per-machine secret/state, so
# it travels with the code, same reasoning as any other bridge module.
# Two real variants, both A/B'd live with Louis on 2026-08-20 (the original
# full-size logo.png rendered too large in a photo bubble):
#   - logo_photo.png (160x160 PNG) for send_photo — smaller, still one
#     single message with the caption, but Telegram's own minimum photo
#     render width means it's "smaller", not truly icon/sticker-sized.
#   - logo_sticker.webp (512px static WEBP, Telegram's real sticker spec)
#     for send_sticker — genuinely small like a sticker, but the Bot API
#     has no caption on a sticker, so that path is two real messages
#     (sticker, then the text right after) instead of one.
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_LOGO_PHOTO_PATH = os.path.join(_ASSETS_DIR, "logo_photo.png")
_LOGO_STICKER_PATH = os.path.join(_ASSETS_DIR, "logo_sticker.webp")


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


def send_photo(chat_id, caption):
    """Real logo + caption via sendPhoto, ONE message (2026-08-20, Louis:
    only on a real position opening and a real WINNING close — never on a
    loss, the daily goal/protection notice, or an economic alert, so the
    image stays a "good news" marker rather than routine noise). Falls
    back to a plain send_message if the logo file isn't packaged on this
    machine (an old install that predates it, or a dev run outside the
    built app) — a missing image is never a reason to drop the real trade
    information."""
    if not os.path.isfile(_LOGO_PHOTO_PATH):
        log.warning("[TELEGRAM] Logo introuvable (%s) — envoi en texte simple.", _LOGO_PHOTO_PATH)
        return send_message(chat_id, caption)
    if not chat_id:
        return {"ok": False, "error": "chat_id manquant — colle le tien dans Réglages avant d'activer les notifications."}
    api_base = _api_base()
    if not api_base:
        return {"ok": False, "error": f"Bot Telegram non configuré sur cette machine — place le token dans {_TOKEN_FILE}."}
    try:
        with open(_LOGO_PHOTO_PATH, "rb") as f:
            resp = requests.post(
                f"{api_base}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": f},
                timeout=REQUEST_TIMEOUT,
            )
        data = resp.json()
        if not data.get("ok"):
            desc = data.get("description") or "Envoi Telegram échoué"
            log.warning("[TELEGRAM] sendPhoto failed: %s", desc)
            return {"ok": False, "error": desc}
        return {"ok": True}
    except Exception as e:
        log.warning("[TELEGRAM] sendPhoto exception: %s", e)
        return {"ok": False, "error": str(e)}


def send_sticker(chat_id, caption):
    """Real logo as a genuine Telegram sticker, TWO messages (2026-08-20,
    Louis, A/B alternative to send_photo above) — the Bot API's sendSticker
    has no caption parameter at all, so the only way to keep the sticker
    AND the real trade text is to send them as two separate real messages,
    sticker first. Same fallback discipline as send_photo: no sticker file
    on this machine just means plain text, never a dropped notification."""
    if not os.path.isfile(_LOGO_STICKER_PATH):
        log.warning("[TELEGRAM] Sticker introuvable (%s) — envoi en texte simple.", _LOGO_STICKER_PATH)
        return send_message(chat_id, caption)
    if not chat_id:
        return {"ok": False, "error": "chat_id manquant — colle le tien dans Réglages avant d'activer les notifications."}
    api_base = _api_base()
    if not api_base:
        return {"ok": False, "error": f"Bot Telegram non configuré sur cette machine — place le token dans {_TOKEN_FILE}."}
    try:
        with open(_LOGO_STICKER_PATH, "rb") as f:
            resp = requests.post(
                f"{api_base}/sendSticker",
                data={"chat_id": chat_id},
                files={"sticker": f},
                timeout=REQUEST_TIMEOUT,
            )
        data = resp.json()
        if not data.get("ok"):
            desc = data.get("description") or "Envoi Telegram échoué"
            log.warning("[TELEGRAM] sendSticker failed: %s", desc)
            # Sticker failed — still send the real trade info as text
            # rather than silently losing the notification.
            return send_message(chat_id, caption)
    except Exception as e:
        log.warning("[TELEGRAM] sendSticker exception: %s", e)
        return send_message(chat_id, caption)
    return send_message(chat_id, caption)


# Pas de bouclier/emoji ici (2026-08-20, Louis) — juste le nom, en gras.
# Sur trade_opened/trade_closed-gagnant le vrai logo (send_photo/send_sticker
# ci-dessus) porte déjà l'identité visuelle ; sur les autres messages (perte,
# économique, test) ce nom en tête suffit sans rejouer une icône générique.
_HEADER = "*AlphaTrade Global*"

# daily_goal garde le tout premier en-tête proposé (bouclier emoji), pas le
# texte nu ci-dessus — 2026-08-20, Louis a explicitement préféré revenir à
# "la première proposition du début" pour CE message précis après avoir vu
# les deux côte à côte, alors que trade_opened/trade_closed gardent le
# nouveau langage (bulle + logo réel). Volontairement différent, pas un
# oubli d'harmonisation.
_HEADER_DAILY_GOAL = "🛡 *AlphaTrade Global*"


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


def _fmt_time_utc(iso_str):
    """For a real UTC timestamp (frontend's `new Date().toISOString()`,
    e.g. trade_opened's real order time) — converts to this machine's
    local time, since that's what the trader actually reads on their
    phone/broker terminal."""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d/%m %H:%M")
    except (ValueError, TypeError, AttributeError):
        return datetime.now().strftime("%d/%m %H:%M")


def _fmt_time_raw(iso_str):
    """For a timestamp of UNKNOWN timezone origin (MT5 history's closed_at,
    passed straight through by reconcileTrades.js — real, disclosed data
    gap: it is NOT UTC-tagged the way trade_opened's own timestamp is, so
    running it through astimezone() could silently shift it by the
    broker's UTC offset. Reformats the date/time parts as given, no
    conversion — accurate to what MT5 reported, not adjusted."""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", ""))
        return dt.strftime("%d/%m %H:%M")
    except (ValueError, TypeError, AttributeError):
        return None


def _risk_reward(entry, sl, tp):
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        return round(abs(tp - entry) / risk, 1)
    except (TypeError, ValueError):
        return None


def format_trade_opened(data):
    # Bulle rouge/verte par direction (2026-08-20, Louis: pas d'icône de
    # médaille par symbole — revient au langage visuel simple d'origine,
    # appliqué maintenant partout, y compris clôture/objectif ci-dessous).
    direction = data.get("direction")
    bubble = "🟢" if direction == "BUY" else "🔴"
    lines = [
        _HEADER,
        f"{bubble} *{data.get('symbol')} {direction}* ouvert",
        "",
        f"Heure : {_fmt_time_utc(data.get('time'))}",
        f"Lot : `{data.get('lot')}`  •  Entrée : `{_fmt_price(data.get('entry_price'))}`",
    ]
    sl, tp = data.get("stop_loss"), data.get("take_profit")
    if sl:
        line = f"SL : `{_fmt_price(sl)}`"
        if tp:
            line += f"  •  TP : `{_fmt_price(tp)}`"
        lines.append(line)
        rr = _risk_reward(data.get("entry_price"), sl, tp) if tp else None
        if rr:
            lines.append(f"R:R ≈ 1:{rr}")
    if data.get("confidence") is not None:
        lines.append(f"Confiance : *{data.get('confidence')}%*")
    if data.get("trading_profile"):
        lines.append(f"Profil : {str(data.get('trading_profile')).capitalize()}")
    if data.get("ticket"):
        lines.append(f"Ticket : `#{data.get('ticket')}`")
    return "\n".join(lines)


def format_trade_closed(data):
    # Bulle par résultat, pas par direction (2026-08-20, Louis) — vert =
    # gagnant, rouge = perdant, même langage visuel que trade_opened mais
    # sur l'axe qui compte à la clôture: le résultat, pas le sens pris.
    # Heures d'entrée ET de clôture + ticket (2026-08-20, Louis: "détaillé"
    # veut dire ça aussi sur les clôtures, pas seulement les ouvertures).
    pnl = data.get("pnl") or 0
    bubble = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
    direction = data.get("direction")
    side = f" {direction}" if direction else ""
    lines = [
        _HEADER,
        f"{bubble} *{data.get('symbol')}*{side} clôturé",
        "",
        f"Résultat : *{_fmt_money(pnl)}*",
    ]
    entry, exit_ = data.get("entry_price"), data.get("exit_price")
    if entry and exit_:
        lines.append(f"Entrée : `{_fmt_price(entry)}`  →  Sortie : `{_fmt_price(exit_)}`")
    if data.get("lot"):
        lines.append(f"Lot : `{data.get('lot')}`")
    opened_time = _fmt_time_utc(data.get("opened_at")) if data.get("opened_at") else None
    if opened_time:
        lines.append(f"Ouvert : {opened_time}")
    closed_time = _fmt_time_raw(data.get("closed_at"))
    if closed_time:
        lines.append(f"Clôturé : {closed_time}")
    if data.get("ticket"):
        lines.append(f"Ticket : `#{data.get('ticket')}`")
    return "\n".join(lines)


def format_daily_goal(data):
    # Revenu à la toute première maquette (2026-08-20, Louis, après avoir vu
    # la variante "bulle" et préféré la première) — en-tête bouclier, 🎯/🛑
    # au lieu d'une bulle rouge/verte. `pnl` ici est déjà daily_goal_status()'s
    # somme réelle de TOUS les trades clôturés du jour (gains ET pertes
    # nets, jamais les gains seuls) — voir local_functions.daily_goal_status:
    # goal_reached exige pnl >= goal_amount sur ce net, donc un jour avec de
    # grosses pertes ne peut jamais se voir déclarer "objectif atteint"
    # juste sur des gains bruts.
    reason = data.get("reason")
    pnl = _fmt_money(data.get("pnl"))
    lines = [_HEADER_DAILY_GOAL]
    if reason == "protection_triggered":
        lines.append("🛑 *Protection de perte déclenchée*")
        lines.append("")
        lines.append(f"PnL net du jour : *{pnl}*")
        if data.get("loss_limit"):
            lines.append(f"Limite : −{_fmt_price(data.get('loss_limit'))}$")
    else:
        lines.append("🎯 *Objectif journalier atteint*")
        lines.append("")
        lines.append(f"PnL net du jour : *{pnl}*")
        if data.get("goal_amount"):
            lines.append(f"Objectif : {_fmt_price(data.get('goal_amount'))}$")
    lines.append("")
    lines.append("Nouvelles ouvertures suspendues jusqu'à demain (sauf reprise manuelle dans l'app).")
    return "\n".join(lines)


def format_economic_event(title, country, minutes_until, forecast=None, previous=None):
    # Detail reel (2026-08-20, Louis) -- forecast/previous sont des vrais
    # champs du flux calendrier (voir economic_calendar._fetch_calendar,
    # jamais remplis a la main) ; `actual` n'existe presque jamais encore a
    # ce stade puisqu'on alerte AVANT l'evenement, donc pas affiche.
    when = "maintenant" if minutes_until <= 1 else f"dans {round(minutes_until)} min"
    lines = [_HEADER, f"📅 *Événement à fort impact* {when}", f"{title} ({country})"]
    if forecast:
        lines.append(f"Prévision : `{forecast}`" + (f"  •  Précédent : `{previous}`" if previous else ""))
    elif previous:
        lines.append(f"Précédent : `{previous}`")
    return "\n".join(lines)


_FORMATTERS = {
    "trade_opened": format_trade_opened,
    "trade_closed": format_trade_closed,
    "daily_goal": format_daily_goal,
}


def notify(kind, chat_id, data):
    """Single dispatch point used by alphatg_bridge.py's /functions/telegramNotifier
    route. `kind='test'` sends a fixed friendly confirmation instead of a
    real-data-shaped message (see TelegramNotifierSection.jsx).

    Real logo — 2026-08-20, Louis chose separately per case after an A/B
    test on real Telegram, corrected twice as he saw the real results: the
    real sticker (two messages) on a real position OPENING; a single-
    message photo (good resolution — see logo_photo.png, NOT the first
    over-shrunk 160px attempt) on a real WINNING close AND on a real
    goal-reached notice — same "good news, single message" pattern for
    both. A losing close, the protection-triggered notice, an economic
    alert, and the test ping all stay plain text via send_message, no
    logo at all — bad/neutral news never gets the logo treatment."""
    if kind == "test":
        text = f"{_HEADER}\n\n✅ Test réussi — les notifications sont bien connectées à ce chat."
        return send_message(chat_id, text)

    formatter = _FORMATTERS.get(kind)
    if not formatter:
        return {"ok": False, "error": f"Type de notification inconnu: {kind}"}
    text = formatter(data)

    if kind == "trade_opened":
        return send_sticker(chat_id, text)
    if kind == "trade_closed" and (data.get("pnl") or 0) > 0:
        return send_photo(chat_id, text)
    if kind == "daily_goal" and data.get("reason") != "protection_triggered":
        return send_photo(chat_id, text)
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
        text = format_economic_event(e.get("title"), e.get("country"), minutes_until, e.get("forecast"), e.get("previous"))
        result = send_message(chat_id, text)
        if result.get("ok"):
            already_sent.add(key)
