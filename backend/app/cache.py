"""Tiny in-process TTL cache. Swap for Redis when FinSight runs on more than one worker."""
import threading
import time
from functools import wraps

_store: dict = {}
_lock = threading.Lock()


def ttl_cache(seconds: int):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args):
            key = (fn.__qualname__, args)
            now = time.time()
            with _lock:
                hit = _store.get(key)
                if hit and now - hit[0] < seconds:
                    return hit[1]
            value = fn(*args)
            with _lock:
                _store[key] = (now, value)
            return value

        return wrapper

    return decorator


def cached(key, seconds: float, compute):
    """Value for `key` if computed in the last `seconds`, else compute and store it. For caches whose lifetime
    depends on the arguments (e.g. 30 s for 1-minute candles, an hour for weekly ones)."""
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit and now - hit[0] < seconds:
            return hit[1]
    value = compute()
    with _lock:
        _store[key] = (now, value)
    return value
