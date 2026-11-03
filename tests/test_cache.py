from aggregator.cache import InMemoryTTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_entry_expires_after_ttl():
    clock = FakeClock()
    cache: InMemoryTTLCache[str] = InMemoryTTLCache(clock=clock)
    await cache.set("k", "v", ttl_seconds=10)
    assert await cache.get("k") == "v"
    clock.now = 10
    assert await cache.get("k") is None


async def test_delete_and_bounded_size():
    clock = FakeClock()
    cache: InMemoryTTLCache[int] = InMemoryTTLCache(max_entries=2, clock=clock)
    await cache.set("a", 1, 100)
    await cache.set("b", 2, 50)
    await cache.set("c", 3, 100)  # evicts "b" (closest to expiry)
    assert await cache.get("b") is None
    assert await cache.get("a") == 1
    await cache.delete("a")
    assert await cache.get("a") is None
