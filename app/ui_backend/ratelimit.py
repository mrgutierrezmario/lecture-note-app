"""Small in-memory rate limiter for the sign-in endpoints.

Brute-forcing a password is slow because of bcrypt, but nothing else stood in
the way. This adds a lockout: after ``MAX_FAILURES`` wrong attempts within
``WINDOW`` seconds — counted per client address *and* per account name, so
one attacker can't lock everyone out and a distributed one still hits the
per-account limit — further attempts are refused with 429 for ``LOCKOUT``
seconds, doubling on every repeat. A successful sign-in clears the counters.

Memory-only and per process: fine for one backend; a restart forgets it.
"""

import threading
import time
from dataclasses import dataclass, field

MAX_FAILURES = 5
WINDOW = 10 * 60  # seconds in which failures accumulate
LOCKOUT = 60  # first lockout; doubles on each subsequent one, capped
LOCKOUT_MAX = 60 * 60


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0
    lockouts: int = 0  # how many times this bucket has been locked (escalation)


_buckets: dict[str, _Bucket] = {}
_lock = threading.Lock()


def _bucket(key: str) -> _Bucket:
    if key not in _buckets:
        _buckets[key] = _Bucket()
    return _buckets[key]


def _prune(now: float) -> None:
    """Forget idle buckets so the dict can't grow without bound."""
    for key, b in list(_buckets.items()):
        b.failures = [t for t in b.failures if now - t < WINDOW]
        if not b.failures and b.locked_until < now:
            _buckets.pop(key, None)


def retry_after(*keys: str) -> int:
    """Seconds until any of these keys is allowed again (0 = allowed now)."""
    now = time.time()
    with _lock:
        if len(_buckets) > 10_000:
            _prune(now)
        waits = [_buckets[k].locked_until - now for k in keys if k in _buckets]
    longest = max(waits, default=0.0)
    return int(longest) + 1 if longest > 0 else 0


def record_failure(*keys: str) -> None:
    """Count a failed attempt against each key; lock when the limit is hit."""
    now = time.time()
    with _lock:
        for key in keys:
            b = _bucket(key)
            b.failures = [t for t in b.failures if now - t < WINDOW]
            b.failures.append(now)
            if len(b.failures) >= MAX_FAILURES:
                b.lockouts += 1
                b.locked_until = now + min(LOCKOUT * 2 ** (b.lockouts - 1), LOCKOUT_MAX)
                b.failures = []


def record_success(*keys: str) -> None:
    """A correct sign-in wipes the slate for these keys."""
    with _lock:
        for key in keys:
            _buckets.pop(key, None)
