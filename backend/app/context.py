"""AppContext: every long-lived object of the backend in one place, created at startup and closed at shutdown."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .ai.prompt_builder import PromptBuilder
from .config import Settings
from .ratelimit import RateLimiter
from .scraper.service import Scraper
from .services.ads import Ads
from .services.assets import AssetStore
from .services.maintenance import Maintenance
from .services.scrape_jobs import ScrapeJobs
from .studio.jobs import StudioJobs
from .store.cache import Cache, make_cache
from .store.db import Database
from .video import voice
from .video.service import VideoService

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Holds settings, storage and the services. Tests build one with fakes through `create(...)` overrides."""

    settings: Settings
    db: Database
    cache: Cache
    scraper: Scraper
    scrape_jobs: ScrapeJobs
    assets: AssetStore
    prompts: PromptBuilder
    video: VideoService
    ads: Ads
    maintenance: Maintenance
    limiter: RateLimiter
    studio: StudioJobs

    @classmethod
    async def create(
        cls, settings: Settings, *, scraper: Optional[Scraper] = None, prompts: Optional[PromptBuilder] = None,
        video: Optional[VideoService] = None, cache: Optional[Cache] = None, start_background: bool = True,
    ) -> "AppContext":
        """Open the database and cache, build the services, recover unfinished work and start the cleanup loop."""
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db = Database(settings.database_path)
        await db.init()
        cache = cache or await make_cache(settings.redis_url)
        scraper = scraper or Scraper(settings)
        prompts = prompts or PromptBuilder(settings)
        video = video or VideoService(settings)
        scrape_jobs = ScrapeJobs(settings, db, cache, scraper)
        assets = AssetStore(settings, db)
        ads = Ads(settings, db, scrape_jobs, scraper, assets, prompts, video)
        maintenance = Maintenance(settings, db, ads, assets)
        voice.configure(settings)
        ctx = cls(settings, db, cache, scraper, scrape_jobs, assets, prompts, video, ads, maintenance, RateLimiter(settings.rate_limit_per_minute), StudioJobs(settings))
        recovered = await scrape_jobs.recover() + await ads.recover()
        if recovered:
            logger.warning("closed %s unfinished job(s) from the previous run", recovered)
        if start_background:
            maintenance.start()
        return ctx

    async def close(self) -> None:
        """Stop background work, then close the scraper, cache and database."""
        await self.maintenance.stop()
        await self.ads.close()
        await self.scrape_jobs.close()
        await self.scraper.close()
        await self.cache.close()
        await self.db.close()
