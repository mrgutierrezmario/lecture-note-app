"""Sign-in lockout and per-user usage caps."""

from accounts import ratelimit


def setup_function():
    ratelimit._buckets.clear()
    ratelimit._usage.clear()


def test_lockout_after_failures_and_escalation(monkeypatch):
    monkeypatch.setattr(ratelimit, "LOCKOUT", 10)
    for _ in range(ratelimit.MAX_FAILURES - 1):
        ratelimit.record_failure("ip:a")
    assert ratelimit.retry_after("ip:a") == 0
    ratelimit.record_failure("ip:a")
    first = ratelimit.retry_after("ip:a")
    assert 0 < first <= 11
    # Other keys are independent.
    assert ratelimit.retry_after("ip:b") == 0
    # A second lockout doubles.
    ratelimit._buckets["ip:a"].locked_until = 0
    for _ in range(ratelimit.MAX_FAILURES):
        ratelimit.record_failure("ip:a")
    assert ratelimit.retry_after("ip:a") > first


def test_success_clears():
    for _ in range(ratelimit.MAX_FAILURES):
        ratelimit.record_failure("user:bob", "ip:a")
    assert ratelimit.retry_after("user:bob") > 0
    ratelimit.record_success("user:bob", "ip:a")
    assert ratelimit.retry_after("user:bob", "ip:a") == 0


def test_allow_sliding_window():
    results = [ratelimit.allow("chat:u1", 3, 60)[0] for _ in range(4)]
    assert results == [True, True, True, False]
    allowed, wait = ratelimit.allow("chat:u1", 3, 60)
    assert not allowed and 0 < wait <= 61
    # Refusals are not counted and other users are unaffected.
    assert ratelimit.allow("chat:u2", 3, 60) == (True, 0)
