"""Arq worker entry point for HustlerOS."""

from __future__ import annotations

import asyncio
import logging

from arq import run_worker
from workers.arq_worker import WorkerSettings

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("Starting HustlerOS Arq worker")
    asyncio.run(run_worker(WorkerSettings))
