"""Background jobs so user requests hit warm caches and tripped providers recover on their own."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .providers.base import Provider, ProviderError
from .router import Router

log = logging.getLogger("openterm.scheduler")


async def probe_down_providers(router: Router) -> None:
    """Half-open check: a tripped provider gets one cheap probe; success closes the breaker."""
    for name, p in router.providers.items():
        h = router.health[name]
        if not h.consecutive:
            continue
        if type(p).probe is Provider.probe:
            continue  # no probe(): the cooldown simply runs out (a missing probe used to count as a fresh failure every 30 s)
        try:
            await router._attempt(p, lambda prov: prov.probe())
            log.info("provider %s recovered", name)
        except ProviderError:
            pass


def start(router: Router) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    sched.add_job(probe_down_providers, "interval", seconds=30, args=[router], max_instances=1, coalesce=True)
    sched.start()
    return sched
