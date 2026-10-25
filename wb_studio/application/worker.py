"""Queue worker wiring for the studio job kinds."""

from printflow.config import QueueSettings
from printflow.wb_studio.domain.models import PRODUCT


def queue_settings(env):
    delays = tuple(float(x.strip()) for x in env.get("PRINTFLOW_WB_RETRY_DELAYS_SEC", "15,60,180").split(","))
    if not delays or min(delays) < 0:
        raise ValueError("PRINTFLOW_WB_RETRY_DELAYS_SEC: нужны неотрицательные паузы")
    return QueueSettings(
        workers=max(1, int(env.get("PRINTFLOW_WB_WORKERS", "30"))),
        max_attempts=max(1, int(env.get("PRINTFLOW_WB_MAX_ATTEMPTS", "3"))),
        retry_delays_sec=delays,
        poll_sec=max(0.01, float(env.get("PRINTFLOW_WB_QUEUE_POLL_SEC", "2"))),
        error_pause_sec=max(0.01, float(env.get("PRINTFLOW_WB_ERROR_PAUSE_SEC", "5"))),
        first_article_number=1,
    )


def worker(studio, env, *, publication=True):
    from printflow.domain.models import JobKind
    from printflow.workers.queue import QueueWorker

    handlers = {JobKind.WB_DISCOVER: studio.discovery, JobKind.WB_CARD: studio.card}
    if publication:
        handlers[JobKind.WB_PUBLISH] = studio.publish
    return QueueWorker(studio.repo, handlers, queue_settings(env), product=PRODUCT)
