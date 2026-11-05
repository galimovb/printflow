"""State of a theme search and its cards: what failed for good and what the reserve still has to cover."""

import collections

from printflow.domain.models import JobKind, JobStatus


def transient(job) -> bool:
    """Failed on an error worth retrying (balance, network), not on a rejection of the print itself."""
    return job.status == JobStatus.FAILED and not (job.error or "").startswith("PermanentError")


def settled(job) -> bool:
    """Done or failed: the queue will not run this card again on its own."""
    return job.status in (JobStatus.DONE, JobStatus.FAILED)


def reviewed(job) -> bool:
    """Finished and waiting for publication."""
    return job.status == JobStatus.DONE and bool(job.result.get("review_required"))


def themes(jobs):
    """Finished theme searches with a design limit, each with all of its cards."""
    cards = collections.defaultdict(list)
    for job in jobs:
        if job.kind == JobKind.WB_CARD and job.payload.get("campaign_id"):
            cards[job.payload["campaign_id"]].append(job)
    for campaign in jobs:
        done = campaign.kind == JobKind.WB_DISCOVER and campaign.status == JobStatus.DONE
        if done and campaign.payload.get("design_limit"):
            yield campaign, cards[campaign.id]


def refill(campaign, members) -> list:
    """Reserve sources a theme still needs: one for every card it lost to a permanent rejection."""
    rejected = sum(m.status == JobStatus.FAILED and not transient(m) for m in members)
    missing = campaign.payload["design_limit"] - (len(members) - rejected)
    used = {m.payload["source"]["sku"] for m in members}
    standard = campaign.payload["config"]["algorithm"] == "standard"
    reserve = [
        s for s in campaign.result.get("sources", [])
        if s["sku"] not in used and (standard or s.get("gallery_complete"))
    ]  # fmt: skip
    return reserve[: max(0, missing)]
