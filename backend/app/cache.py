"""Tiny in-process TTL cache. Swap for Redis when FinSight runs on more than one worker.

Concurrent callers asking for the same key while it is being computed wait for that one computation instead of
starting their own ("single flight"): fifty people opening a stock whose cache just expired cost one Yahoo call.
"""
import threading
import time
from functools import wraps

_store: dict = {}
_lock = threading.Lock()
_inflight: dict = {}   # key -> lock held while that key is being computed


def cached(key, seconds: float, compute):
    """Value for `key` if computed in the last `seconds`, else compute (once, however many threads ask) and
    store it. For caches whose lifetime depends on the arguments (e.g. 30 s for 1-minute candles, an hour for
    weekly ones)."""
    with _lock:
        hit = _store.get(key)
        if hit and time.time() - hit[0] < seconds:
            return hit[1]
        key_lock = _inflight.setdefault(key, threading.Lock())
    with key_lock:
        with _lock:   # another thread may have filled it while we waited
            hit = _store.get(key)
            if hit and time.time() - hit[0] < seconds:
                return hit[1]
        try:
            value = compute()   # errors propagate to this caller; waiting callers then try once themselves
        except BaseException:
            with _lock:
                _inflight.pop(key, None)
            raise
        with _lock:   # store before clearing the in-flight marker, so no caller slips in between and recomputes
            _store[key] = (time.time(), value)
            _inflight.pop(key, None)
        return value


def ttl_cache(seconds: int):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args):
            return cached((fn.__qualname__, args), seconds, lambda: fn(*args))

        return wrapper

    return decorator
