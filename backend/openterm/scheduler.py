"""Background jobs so user requests hit warm caches and tripped providers recover on their own."""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .cache import Cache
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


async def prune_cache(cache: Cache) -> None:
    """Daily housekeeping: drop old and excess rows from the SQLite cache table."""
    removed = await cache.prune()
    if removed:
        log.info("cache pruned: %d rows removed", removed)


def start(router: Router, cache: Cache | None = None) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    sched.add_job(probe_down_providers, "interval", seconds=30, args=[router], max_instances=1, coalesce=True)
    if cache is not None:
        # first run 5 min after start (not at boot, which is busy), then every 6 hours
        sched.add_job(prune_cache, "interval", hours=6, args=[cache], id="cache_prune", max_instances=1, coalesce=True,
                      next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    sched.start()
    return sched


BRIEF_JOB = "brief"


def schedule_brief(sched: AsyncIOScheduler, app, cfg: dict) -> None:
    """Adds, replaces or removes the daily-brief cron job from the delivery `brief` settings
    ({enabled, time "HH:MM", days "mon-fri"|"daily", tz "" = this machine's zone}).
    replace_existing makes a settings change take effect without a restart."""
    from apscheduler.jobstores.base import JobLookupError
    from apscheduler.triggers.cron import CronTrigger

    from .brief import scheduled_run

    if not cfg.get("enabled"):
        try:
            sched.remove_job(BRIEF_JOB)
        except JobLookupError:
            pass  # was never scheduled
        return
    hour, minute = (int(x) for x in cfg["time"].split(":"))
    trigger = CronTrigger(day_of_week="mon-fri" if cfg["days"] == "mon-fri" else "*", hour=hour, minute=minute,
                          timezone=cfg.get("tz") or None)  # None = apscheduler's local zone
    sched.add_job(scheduled_run, trigger, args=[app], id=BRIEF_JOB, replace_existing=True,
                  max_instances=1, coalesce=True, misfire_grace_time=3600)
