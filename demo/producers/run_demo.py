"""
run_demo.py — Demo producer orchestrator.

Starts all three producer services and connects each to the Redis command channel.
All producers run concurrently; the cascade is triggered via POST /demo/cascade.

Usage (inside Docker or locally):
    python -m demo.producers.run_demo
"""

import asyncio
import os

import structlog

from demo.producers.api_gateway import ApiGatewayProducer
from demo.producers.order_service import OrderServiceProducer
from demo.producers.payment_service import PaymentServiceProducer

log = structlog.get_logger()

_INGEST_URL = os.getenv("INGEST_URL", "http://api:8000/api/v1/ingest")
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_API_KEY = os.getenv("DEMO_API_KEY", "demo-secret")


def _build_producers() -> list:
    return [
        PaymentServiceProducer(_INGEST_URL, _API_KEY),
        OrderServiceProducer(_INGEST_URL, _API_KEY),
        ApiGatewayProducer(_INGEST_URL, _API_KEY),
    ]


async def main() -> None:
    log.info(
        "demo_producers_starting",
        services=["payment-service", "order-service", "api-gateway"],
        ingest_url=_INGEST_URL,
        redis_url=_REDIS_URL,
    )

    # Loop forever: after a stop command, rebuild producers and wait for next start.
    while True:
        producers = _build_producers()
        await asyncio.gather(*(p.listen_for_commands(_REDIS_URL) for p in producers))
        log.info("demo_producers_stopped — waiting for next start command")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
