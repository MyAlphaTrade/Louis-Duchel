"""Tests isoles pour slack_notifier.py (v5.1.0). Aucun appel reseau reel --
urllib.request.urlopen est remplace par un espion le temps du test."""
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import slack_notifier as sn

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


class _FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return b"ok"


def _spy_urlopen(calls):
    def _fake(request, timeout=None):
        calls.append({"url": request.full_url, "body": request.data, "headers": dict(request.header_items())})
        return _FakeResponse()
    return _fake


def test_notify_only_matching_event_type():
    calls = []
    original = sn.urllib.request.urlopen
    sn.urllib.request.urlopen = _spy_urlopen(calls)
    try:
        params = {"slack_webhooks": [
            {"name": "Trading", "webhook_url": "https://hooks.slack.test/A", "events": ["caio_go"], "enabled": True},
            {"name": "Objectifs", "webhook_url": "https://hooks.slack.test/B", "events": ["mission_target"], "enabled": True},
        ]}
        sn.notify_slack(params, "caio_go", sn.SLACK_GREEN, [{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}], "text")
        assert len(calls) == 1
        assert calls[0]["url"] == "https://hooks.slack.test/A"
    finally:
        sn.urllib.request.urlopen = original
    print("test_notify_only_matching_event_type OK")


def test_notify_skips_disabled_destination():
    calls = []
    original = sn.urllib.request.urlopen
    sn.urllib.request.urlopen = _spy_urlopen(calls)
    try:
        params = {"slack_webhooks": [
            {"name": "Off", "webhook_url": "https://hooks.slack.test/C", "events": ["caio_go"], "enabled": False},
        ]}
        sn.notify_slack(params, "caio_go", sn.SLACK_GREEN, [], "text")
        assert len(calls) == 0
    finally:
        sn.urllib.request.urlopen = original
    print("test_notify_skips_disabled_destination OK")


def test_notify_broadcasts_to_multiple_matching_destinations():
    calls = []
    original = sn.urllib.request.urlopen
    sn.urllib.request.urlopen = _spy_urlopen(calls)
    try:
        params = {"slack_webhooks": [
            {"name": "A", "webhook_url": "https://hooks.slack.test/A", "events": ["trading_toggle"], "enabled": True},
            {"name": "B", "webhook_url": "https://hooks.slack.test/B", "events": ["trading_toggle", "caio_go"], "enabled": True},
        ]}
        sn.notify_slack(params, "trading_toggle", sn.SLACK_GREEN, [], "text")
        assert len(calls) == 2
    finally:
        sn.urllib.request.urlopen = original
    print("test_notify_broadcasts_to_multiple_matching_destinations OK")


def test_notify_network_error_does_not_raise():
    def _raise(request, timeout=None):
        raise OSError("network down")
    original = sn.urllib.request.urlopen
    sn.urllib.request.urlopen = _raise
    try:
        params = {"slack_webhooks": [
            {"name": "A", "webhook_url": "https://hooks.slack.test/A", "events": ["caio_go"], "enabled": True},
        ]}
        sn.notify_slack(params, "caio_go", sn.SLACK_GREEN, [], "text")  # ne doit pas lever
    finally:
        sn.urllib.request.urlopen = original
    print("test_notify_network_error_does_not_raise OK")


def test_notify_no_webhooks_configured_is_noop():
    calls = []
    original = sn.urllib.request.urlopen
    sn.urllib.request.urlopen = _spy_urlopen(calls)
    try:
        sn.notify_slack({}, "caio_go", sn.SLACK_GREEN, [], "text")
        assert len(calls) == 0
    finally:
        sn.urllib.request.urlopen = original
    print("test_notify_no_webhooks_configured_is_noop OK")


def test_blocks_caio_go_buy_vs_sell_emoji():
    blocks, text = sn.blocks_caio_go("XAUUSD", "BUY_MARKET", 2385.4, "smart_money_analyst", "raison")
    assert "🟢" in text
    blocks, text = sn.blocks_caio_go("XAUUSD", "SELL_LIMIT", 2385.4, "structure_analyst", "raison")
    assert "🔴" in text
    print("test_blocks_caio_go_buy_vs_sell_emoji OK")


def test_blocks_mission_target_includes_amounts():
    blocks, text = sn.blocks_mission_target("hebdomadaire", 260.0, 250.0)
    assert "260.00" in text and "250.00" in text
    print("test_blocks_mission_target_includes_amounts OK")


def test_blocks_trading_toggle_start_vs_stop():
    _, text_on = sn.blocks_trading_toggle(True, "DEMO")
    _, text_off = sn.blocks_trading_toggle(False, "REEL")
    assert "démarré" in text_on
    assert "arrêté" in text_off
    print("test_blocks_trading_toggle_start_vs_stop OK")


if __name__ == "__main__":
    test_notify_only_matching_event_type()
    test_notify_skips_disabled_destination()
    test_notify_broadcasts_to_multiple_matching_destinations()
    test_notify_network_error_does_not_raise()
    test_notify_no_webhooks_configured_is_noop()
    test_blocks_caio_go_buy_vs_sell_emoji()
    test_blocks_mission_target_includes_amounts()
    test_blocks_trading_toggle_start_vs_stop()
    print("ALL TESTS PASSED")
