"""Tests isoles pour check_mission_target_slack() (alphatrade_engine.py,
v5.1.0) -- deduplication des notifications Slack d'objectif atteint (une
seule fois par periode jour/semaine/mois)."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, params, event_type, color, blocks, text):
        self.calls.append((event_type, text))


def _mission(daily_profit=0, daily_target=50, weekly_profit=0, weekly_target=250, monthly_profit=0, monthly_target=1000):
    return {
        "daily_profit": daily_profit, "daily_target": daily_target,
        "weekly_profit": weekly_profit, "weekly_target": weekly_target,
        "monthly_profit": monthly_profit, "monthly_target": monthly_target,
    }


def test_no_notification_when_target_not_reached():
    spy = _Spy()
    original = ae.notify_slack
    ae.notify_slack = spy
    try:
        state = {}
        ae.check_mission_target_slack({}, _mission(daily_profit=10, daily_target=50), state)
        assert spy.calls == []
    finally:
        ae.notify_slack = original
    print("test_no_notification_when_target_not_reached OK")


def test_notifies_once_when_target_reached():
    spy = _Spy()
    original = ae.notify_slack
    ae.notify_slack = spy
    try:
        state = {}
        ae.check_mission_target_slack({}, _mission(daily_profit=55, daily_target=50), state)
        assert len(spy.calls) == 1
        assert spy.calls[0][0] == "mission_target"
        # meme cycle, meme periode -> pas de doublon
        ae.check_mission_target_slack({}, _mission(daily_profit=60, daily_target=50), state)
        assert len(spy.calls) == 1
    finally:
        ae.notify_slack = original
    print("test_notifies_once_when_target_reached OK")


def test_day_week_month_are_independent():
    spy = _Spy()
    original = ae.notify_slack
    ae.notify_slack = spy
    try:
        state = {}
        ae.check_mission_target_slack({}, _mission(
            daily_profit=55, daily_target=50,
            weekly_profit=260, weekly_target=250,
            monthly_profit=100, monthly_target=1000,
        ), state)
        assert len(spy.calls) == 2  # jour + semaine, pas mois
        assert state["slack_mission_notified"].get("day")
        assert state["slack_mission_notified"].get("week")
        assert "month" not in state["slack_mission_notified"]
    finally:
        ae.notify_slack = original
    print("test_day_week_month_are_independent OK")


def test_zero_target_never_notifies():
    spy = _Spy()
    original = ae.notify_slack
    ae.notify_slack = spy
    try:
        state = {}
        ae.check_mission_target_slack({}, _mission(daily_profit=100, daily_target=0), state)
        assert spy.calls == []
    finally:
        ae.notify_slack = original
    print("test_zero_target_never_notifies OK")


if __name__ == "__main__":
    test_no_notification_when_target_not_reached()
    test_notifies_once_when_target_reached()
    test_day_week_month_are_independent()
    test_zero_target_never_notifies()
    print("ALL TESTS PASSED")
