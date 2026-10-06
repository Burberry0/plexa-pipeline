from datetime import datetime, timedelta, timezone

from guardrails import ReplyDecision, decide_reply, parse_airtable_datetime

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _decide(**overrides):
    kwargs = dict(enabled=True, reply_count=0, last_reply_at=None, max_replies=2, cooldown_minutes=5, now=NOW)
    kwargs.update(overrides)
    return decide_reply(**kwargs)


def test_first_reply_ok():
    assert _decide() == ReplyDecision(True, "ok")


def test_disabled_wins_over_everything():
    assert _decide(enabled=False) == ReplyDecision(False, "auto_reply_disabled")


def test_max_replies():
    assert _decide(reply_count=2) == ReplyDecision(False, "max_replies_reached")
    assert _decide(reply_count=1, last_reply_at=NOW - timedelta(hours=1)).should_reply is True


def test_cooldown():
    assert _decide(reply_count=1, last_reply_at=NOW - timedelta(minutes=4)) == ReplyDecision(False, "cooldown_active")
    assert _decide(reply_count=1, last_reply_at=NOW - timedelta(minutes=5)).should_reply is True


def test_accepts_airtable_iso_string():
    assert _decide(reply_count=1, last_reply_at="2026-10-05T11:58:00.000Z").reason == "cooldown_active"


def test_parse_airtable_datetime():
    assert parse_airtable_datetime("2026-10-05T11:58:00.000Z") == datetime(2026, 10, 5, 11, 58, tzinfo=timezone.utc)
    assert parse_airtable_datetime("2026-10-05T11:58:00Z") == datetime(2026, 10, 5, 11, 58, tzinfo=timezone.utc)
    assert parse_airtable_datetime(None) is None
    assert parse_airtable_datetime("garbage") is None
