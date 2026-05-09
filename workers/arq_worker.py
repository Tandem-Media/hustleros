"""Arq WorkerSettings placeholder for HustlerOS queues."""

from arq.connections import RedisSettings

QUEUE_NAMES = [
    "hustleros:queue:default",
    "hustleros:queue:payments",
    "hustleros:queue:notifications",
    "hustleros:queue:reconciliation",
]


class WorkerSettings:
    """Placeholder worker settings for queue wiring in future phases."""

    functions = []
    redis_settings = RedisSettings()
    queue_name = "hustleros:queue:default"
