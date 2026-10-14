"""Housekeeping: delete old jobs, ads, uploads and leftover work folders (DATA_RETENTION_HOURS)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from typing import Optional

from ..config import Settings
from ..store.db import Database
from .ads import Ads
from .assets import AssetStore

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 30 * 60


class Maintenance:
    """Runs the cleanup once at start and then every 30 minutes in the background."""

    def __init__(self, settings: Settings, db: Database, ads: Ads, assets: AssetStore):
        """Remember what to clean."""
        self.settings = settings
        self.db = db
        self.ads = ads
        self.assets = assets
        self._task: Optional[asyncio.Task] = None

    async def run_once(self) -> dict[str, int]:
        """Delete everything older than the retention window. Returns counts per kind."""
        if self.settings.data_retention_hours <= 0:
            return {"jobs": 0, "ads": 0, "assets": 0, "work": 0}
        cutoff = time.time() - self.settings.data_retention_hours * 3600
        jobs = len(await self.db.pop_older_than("job", cutoff))
        ads = await self.ads.purge_older_than(cutoff)
        assets = await self.assets.purge_older_than(cutoff)
        work = 0
        work_dir = self.ads.work_dir
        if work_dir.is_dir():
            for folder in work_dir.iterdir():
                try:
                    if folder.is_dir() and folder.stat().st_mtime < time.time() - 86400:
                        shutil.rmtree(folder, ignore_errors=True)
                        work += 1
                except OSError:
                    continue
        counts = {"jobs": jobs, "ads": ads, "assets": assets, "work": work}
        if any(counts.values()):
            logger.info("cleanup removed %s", counts)
        return counts

    def start(self) -> None:
        """Start the background loop."""
        self._task = asyncio.create_task(self._loop(), name="maintenance")

    async def _loop(self) -> None:
        """Clean up now, then every INTERVAL_SECONDS; errors are logged, never fatal."""
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cleanup failed")
            await asyncio.sleep(INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stop the background loop."""
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
