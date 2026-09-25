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
