"""
ApiGatewayProducer — simulates the public-facing API gateway.

Cascade role: SYMPTOM
  - Waits 2.8 seconds after the payment-service cascade starts, then injects
    ServiceUnavailableError events that are what the end-user actually sees.
"""

import asyncio
import random

from demo.producers.base_producer import BaseProducer

_NORMAL_MESSAGES = [
    ("INFO", "Request routed to order-service", lambda: random.randint(1, 5)),
    ("INFO", "Request routed to payment-service", lambda: random.randint(1, 4)),
    ("INFO", "Response 200 OK forwarded to client", lambda: random.randint(100, 300)),
    ("DEBUG", "Rate limit check passed", lambda: random.randint(1, 3)),
    ("INFO", "Auth token validated", lambda: random.randint(5, 15)),
    ("DEBUG", "Request logged to audit trail", lambda: random.randint(1, 2)),
    ("INFO", "TLS handshake completed", lambda: random.randint(10, 40)),
    ("INFO", "Keepalive connection reused", lambda: random.randint(0, 2)),
    ("DEBUG", "Load balancer selected backend-2", lambda: random.randint(1, 3)),
    ("INFO", "Cache HIT for /products/featured", lambda: random.randint(1, 5)),
]

_CASCADE_ERRORS = [
    "Upstream service returned 503 — propagating to client",
    "ServiceUnavailableError: order-service returned HTTP 503",
    "ServiceUnavailableError: payment-service health check FAILED",
    "Circuit breaker OPEN for route /checkout — upstream unhealthy",
    "ServiceUnavailableError: all upstream replicas returning 5xx",
    "ServiceUnavailableError: retry budget exhausted for /api/orders",
    "503 Service Unavailable: downstream cascade in payment-service",
    "ServiceUnavailableError: load balancer has no healthy backends",
    "Returning 503 to clients — SLA breach imminent",
    "ServiceUnavailableError: dependency graph health critical",
    "Emergency rate-limit engaged — upstream not recovering",
    "ServiceUnavailableError: cascade propagation from payment → order → gateway",
]

_STACK_TRACE = """\
Traceback (most recent call last):
  File "api_gateway/proxy/router.py", line 203, in forward_request
    resp = await upstream.send(request, timeout=10.0)
  File "api_gateway/clients/upstream.py", line 67, in send
    raise ServiceUnavailableError(f"upstream {backend} returned {status}")
api_gateway.exceptions.ServiceUnavailableError: upstream order-service returned
HTTP 503 — cascaded from payment-service PoolTimeoutError\
"""


class ApiGatewayProducer(BaseProducer):
    """
    Simulates the api-gateway microservice.
    Normal traffic: routing / auth events at ~1 event/second.
    Cascade: ServiceUnavailableError bursts starting 2.8s after payment-service failure.
    This is what the end-user sees — the visible symptom of the upstream chain.
    """

    def __init__(self, ingest_url: str, api_key: str) -> None:
        super().__init__("api-gateway", ingest_url, api_key)

    # ── Normal traffic ────────────────────────────────────────────────────────

    async def run_normal(self, duration_seconds: int) -> None:
        end = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end:
            level, message, duration_fn = random.choice(_NORMAL_MESSAGES)
            event = self.make_event(level, message, duration_ms=duration_fn())
            await self.push([event])
            await asyncio.sleep(random.uniform(0.7, 1.3))

    # ── Cascade injection ─────────────────────────────────────────────────────

    async def run_cascade(self, trace_id: str) -> None:
        """
        Wait 2.8s (propagation delay through order-service), then fire 12
        ServiceUnavailableError events — the visible user-facing symptom.
        """
        await asyncio.sleep(2.8)
        self._active_trace_id = trace_id

        for i, message in enumerate(_CASCADE_ERRORS):
            level = "WARN" if i < 2 else "ERROR"
            event = self.make_event(
                level,
                message,
                error_type="ServiceUnavailableError",
                stack_trace=_STACK_TRACE if i >= 2 else None,
                trace_id=trace_id,
                duration_ms=10_000,
            )
            await self.push([event])
            await asyncio.sleep(1.8)

        self._active_trace_id = None
