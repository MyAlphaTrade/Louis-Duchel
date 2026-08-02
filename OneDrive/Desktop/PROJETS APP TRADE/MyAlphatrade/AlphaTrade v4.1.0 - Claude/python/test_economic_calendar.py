"""Tests isoles pour economic_calendar_report() (v5.1.0). Aucun appel reseau --
injecte directement dans le cache module-level (meme approche que le fetch
reel, juste avec des donnees synthetiques)."""
import os
import tempfile
import time
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import economic_calendar as ec

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _inject(events):
    # _fetch_calendar() compare sa fraicheur a time.time() (horloge reelle),
    # jamais au `now` simule passe a economic_calendar_report() -- il faut
    # donc horodater le cache avec l'heure reelle pour eviter un vrai appel
    # reseau pendant le test, meme si NOW simule une autre date pour les
    # calculs de delta_hours.
    ec._cache["data"] = events
    ec._cache["fetched_at"] = time.time()


def _event(hours_from_now, impact="High", country="USD", title="NFP"):
    ts = NOW.timestamp() + hours_from_now * 3600
    date = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return {"title": title, "country": country, "impact": impact, "date": date}


def test_no_events_returns_neutral_low_confidence():
    _inject([])
    report = ec.economic_calendar_report("XAUUSD", now=NOW)
    assert report.recommendation["action"] == "WAIT"
    assert report.priority == "LOW"
    assert report.confidence == 15
    assert "any_rejected" not in report.recommendation
    print("test_no_events_returns_neutral_low_confidence OK")


def test_imminent_event_blocks_critical():
    _inject([_event(1.0)])  # dans 1h, sous le seuil de blocage par defaut (2h)
    report = ec.economic_calendar_report("XAUUSD", block_hours=2.0, now=NOW)
    assert report.priority == "CRITICAL"
    assert report.recommendation["any_rejected"] is True
    assert report.confidence == 75
    print("test_imminent_event_blocks_critical OK")


def test_near_event_informational_not_blocking():
    _inject([_event(10.0)])  # dans 10h -- au-dela du seuil de blocage, sous near_hours
    report = ec.economic_calendar_report("XAUUSD", block_hours=2.0, near_hours=24.0, now=NOW)
    assert report.priority == "MEDIUM"
    assert "any_rejected" not in report.recommendation
    assert report.confidence == 40
    print("test_near_event_informational_not_blocking OK")


def test_low_impact_event_ignored():
    _inject([_event(1.0, impact="Low")])
    report = ec.economic_calendar_report("XAUUSD", now=NOW)
    assert report.priority == "LOW"
    assert report.confidence == 15
    print("test_low_impact_event_ignored OK")


def test_wrong_currency_ignored():
    _inject([_event(1.0, country="EUR")])  # XAUUSD ne suit que USD
    report = ec.economic_calendar_report("XAUUSD", now=NOW)
    assert report.priority == "LOW"
    print("test_wrong_currency_ignored OK")


def test_just_released_event_still_counts():
    _inject([_event(-0.2)])  # publie il y a 12 minutes -- volatilite post-release
    report = ec.economic_calendar_report("XAUUSD", block_hours=2.0, now=NOW)
    assert report.priority == "CRITICAL"
    print("test_just_released_event_still_counts OK")


def test_action_is_always_wait_never_directional():
    for hours in (1.0, 10.0, 100.0):
        _inject([_event(hours)])
        report = ec.economic_calendar_report("XAUUSD", now=NOW)
        assert report.recommendation["action"] == "WAIT"
    print("test_action_is_always_wait_never_directional OK")


if __name__ == "__main__":
    test_no_events_returns_neutral_low_confidence()
    test_imminent_event_blocks_critical()
    test_near_event_informational_not_blocking()
    test_low_impact_event_ignored()
    test_wrong_currency_ignored()
    test_just_released_event_still_counts()
    test_action_is_always_wait_never_directional()
    print("ALL TESTS PASSED")
