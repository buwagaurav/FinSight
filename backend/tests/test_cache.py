import threading
import time

import pytest

from app import cache


@pytest.fixture(autouse=True)
def fresh():
    cache._store.clear()
    cache._inflight.clear()


def test_concurrent_callers_share_one_computation():
    calls = []

    def slow():
        calls.append(1)
        time.sleep(0.3)
        return "value"

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.cached("k", 60, slow))) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and results == ["value"] * 50


def test_different_keys_run_in_parallel():
    def slow():
        time.sleep(0.3)
        return 1

    started = time.time()
    threads = [threading.Thread(target=cache.cached, args=(f"k{i}", 60, slow)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.time() - started < 1.0          # ten 0.3 s computations at once, not one after another


def test_a_failure_is_not_cached_and_waiters_retry():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            time.sleep(0.2)
            raise RuntimeError("Yahoo hiccup")
        return "ok"

    out = {}

    def call(i):
        try:
            out[i] = cache.cached("k", 60, flaky)
        except RuntimeError:
            out[i] = "error"
    threads = [threading.Thread(target=call, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert out[0] == "error" or "error" in out.values()   # the caller whose fetch failed sees the error
    assert list(out.values()).count("ok") >= 1 and len(attempts) == 2   # the next waiter retried once, rest shared it
    assert not cache._inflight


def test_expired_values_are_recomputed():
    n = []
    cache.cached("k", 0.1, lambda: n.append(1) or len(n))
    time.sleep(0.15)
    assert cache.cached("k", 0.1, lambda: n.append(1) or len(n)) == 2


def test_ttl_cache_decorator_keys_on_arguments():
    calls = []

    @cache.ttl_cache(60)
    def f(x):
        calls.append(x)
        return x * 2
    assert (f(1), f(1), f(2)) == (2, 2, 4) and calls == [1, 2]
