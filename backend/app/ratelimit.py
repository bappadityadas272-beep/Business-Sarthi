"""In-memory sliding-window rate limits (DEC-90, chosen by the human: "moderate").

Kept in process memory: they reset when the server restarts and are not shared between processes, which is enough
for a one-process prototype. Over the limit: 429 `rate_limited` with `retry_after` seconds (body and header).
"""
import math
import threading
import time
from collections import deque

from fastapi import HTTPException

# (bucket, limit, window seconds)
OTP_PER_PHONE = ("otp_phone", 3, 600)          # 3 code requests per phone per 10 minutes
OTP_PER_IP = ("otp_ip", 20, 3600)              # 20 code requests per client address per hour
CHAT_PER_USER = ("chat_user", 20, 60)          # 20 chat messages per user per minute

_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()


def _prune(q: deque, now: float, window: int) -> None:
    while q and q[0] <= now - window:
        q.popleft()


def check(*limits: tuple[tuple[str, int, int], str], now: float | None = None) -> None:
    """Each item is (rule, key). Counts one hit on every rule only if all of them are under their limit."""
    now = time.monotonic() if now is None else now
    with _lock:
        if len(_hits) > 10_000:                          # keep memory bounded
            for k in [k for k, q in _hits.items() if not q or q[-1] <= now - 3600]:
                _hits.pop(k, None)
        wait = 0
        for (bucket, limit, window), key in limits:
            q = _hits.setdefault((bucket, key), deque())
            _prune(q, now, window)
            if len(q) >= limit:
                wait = max(wait, math.ceil(q[0] + window - now))
        if wait:
            raise HTTPException(429, detail={"code": "rate_limited", "retry_after": max(wait, 1)},
                                headers={"Retry-After": str(max(wait, 1))})
        for (bucket, _, _), key in limits:
            _hits[(bucket, key)].append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
