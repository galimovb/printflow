"""Background loop of the queue container: refill themes from their reserve and publish what is finished."""

import asyncio
import contextlib
import logging

logger = logging.getLogger(__name__)


async def supervise(campaigns, publications, stop: asyncio.Event, publish: bool, interval: float = 60) -> None:
    while not stop.is_set():
        added = [card for card in campaigns.top_up() if card["created"]]
        if added:
            logger.info("WB: из запаса добавлено %s товаров", len(added))
        for job, was_created in publications.publish_finished_groups() if publish else ():
            if was_created:
                logger.info("WB: группа %s поставлена на публикацию", job.payload["merge_group"])
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), interval)
