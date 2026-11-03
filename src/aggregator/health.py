"""Tiny `/health` HTTP endpoint so Docker (or anything else) can probe a process."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiohttp import web

HealthCheck = Callable[[], Awaitable[bool]]


async def start_health_server(
    port: int, check: HealthCheck | None = None, host: str = "0.0.0.0"
) -> web.AppRunner:
    async def handler(_: web.Request) -> web.Response:
        ok = await check() if check else True
        return web.json_response({"status": "ok" if ok else "unhealthy"}, status=200 if ok else 503)

    app = web.Application()
    app.router.add_get("/health", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner
