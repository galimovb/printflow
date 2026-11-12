"""WB studio on the PrintFlow queue and S3.

discover -> one WB_CARD job per product -> review -> WB_PUBLISH per merge group.
Studio only wires the three services together and is what the queue, the API and the scripts talk to.
"""

import asyncio

from printflow.wb_studio.infrastructure.wb.publisher import Publisher
from printflow.wb_studio.infrastructure.wb.search import discover

from .campaigns import Campaigns
from .cards import CardService
from .publication import Publications
from .supervisor import supervise

__all__ = ["Studio"]


class Studio:
    def __init__(
        self,
        repository,
        storage,
        env,
        *,
        search=discover,
        generator=None,
        publisher=None,
        fetch=None,
        models=None,
        templates=None,
    ):
        self.repo = repository
        self.storage = storage
        self.env = env
        self.publisher = publisher or Publisher(env.get("PRINTFLOW_WB_API_KEY") or env.get("WB_API_KEY", ""))
        self.campaigns = Campaigns(repository, env, search)
        self.cards = CardService(
            repository, storage, env, generator=generator, fetch=fetch, models=models, templates=templates
        )
        self.publications = Publications(repository, env, self.publisher)

        # Queue handlers and the API.
        self.configuration = self.campaigns.configuration
        self.campaign = self.campaigns.campaign
        self.urls = self.campaigns.urls
        self.sources = self.campaigns.sources
        self.discovery = self.campaigns.discovery
        self.enqueue_cards = self.campaigns.enqueue_cards
        self.top_up_campaigns = self.campaigns.top_up
        self.card = self.cards.card
        self.storage_buckets = self.cards.storage_buckets
        self.enqueue_publication = self.publications.enqueue_publication
        self.create_publication = self.publications.create_publication
        self.publish_finished_groups = self.publications.publish_finished_groups
        self.review_queue = self.publications.review_queue
        self.decide = self.publications.decide
        self.publish_approved = self.publications.publish_approved
        self.publish = self.publications.publish

    async def supervise(self, stop: asyncio.Event, publish: bool, interval: float = 60) -> None:
        await supervise(self.campaigns, self.publications, stop, publish, interval)
