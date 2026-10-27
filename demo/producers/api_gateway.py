"""
ApiGatewayProducer — simulates the public-facing API gateway.

Cascade roles by scenario:
  pool_exhaustion — SYMPTOM  (ServiceUnavailableError: 503s to users)
  memory_leak     — SYMPTOM  (GatewayTimeoutError: 504s from upstream latency)
  slow_query      — SYMPTOM  (ServiceDegradedError: partial 503s on checkout endpoints)
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

# ── Scenario: pool_exhaustion ─────────────────────────────────────────────────

_SERVICE_UNAVAILABLE_ERRORS = [
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

_SERVICE_UNAVAILABLE_STACK = """\
Traceback (most recent call last):
  File "api_gateway/proxy/router.py", line 203, in forward_request
    resp = await upstream.send(request, timeout=10.0)
  File "api_gateway/clients/upstream.py", line 67, in send
    raise ServiceUnavailableError(f"upstream {backend} returned {status}")
api_gateway.exceptions.ServiceUnavailableError: upstream order-service returned
HTTP 503 — cascaded from payment-service PoolTimeoutError\
"""

# ── Scenario: memory_leak ─────────────────────────────────────────────────────

_GATEWAY_TIMEOUT_ERRORS = [
    "Upstream request timed out: /api/checkout → payment-service (5002ms)",
    "GatewayTimeoutError: order-service did not respond within 10s",
    "504 Gateway Timeout: payment-service exceeding SLA (upstream GC pause)",
    "GatewayTimeoutError: checkout endpoint P99 latency 18s — breaching 2s SLA",
    "504 Gateway Timeout: load balancer health probe failing on payment backends",
    "GatewayTimeoutError: 78% of /checkout requests returning 504",
    "Upstream connection pool backing up — 1200 requests queued",
    "GatewayTimeoutError: request hedging disabled — all upstream replicas slow",
    "504 Gateway Timeout: streaming payment response stalled (GC pause upstream)",
    "GatewayTimeoutError: circuit breaker tripping — upstream memory pressure",
    "Client-visible error rate: 94% on /checkout — SLA breach alert",
    "GatewayTimeoutError: all payment-service instances degraded by OOM event",
]

_GATEWAY_TIMEOUT_STACK = """\
Traceback (most recent call last):
  File "api_gateway/proxy/router.py", line 198, in forward_request
    resp = await asyncio.wait_for(upstream.send(request), timeout=30.0)
asyncio.exceptions.TimeoutError
api_gateway.exceptions.GatewayTimeoutError: upstream payment-service did not
respond within 30s — GC pause / memory leak suspected\
"""

# ── Scenario: slow_query ──────────────────────────────────────────────────────

_SERVICE_DEGRADED_ERRORS = [
    "Checkout endpoint /api/checkout degraded — upstream latency spike",
    "ServiceDegradedError: /checkout returning 503 for 43% of requests",
    "Partial outage: payment routes degraded, other endpoints healthy",
    "ServiceDegradedError: payment-service DB lock causing checkout failures",
    "503 on /api/orders/confirm — order-service lock wait propagated",
    "ServiceDegradedError: checkout circuit breaker HALF-OPEN (12% success rate)",
    "Rate of 503s increasing: 200 req/min → 850 req/min on checkout routes",
    "ServiceDegradedError: payment DB deadlock causing cascading timeouts",
    "SLA breach: checkout success rate 8% (SLA: 99.5%)",
    "ServiceDegradedError: all payment-related routes returning 503",
    "Partial failover attempted — payment replica also deadlocked",
]

_SERVICE_DEGRADED_STACK = """\
Traceback (most recent call last):
  File "api_gateway/proxy/router.py", line 211, in forward_request
    resp = await upstream.send(request, timeout=15.0)
  File "api_gateway/clients/upstream.py", line 71, in send
    raise ServiceDegradedError(f"upstream {backend} partially unavailable")
api_gateway.exceptions.ServiceDegradedError: order-service degraded due to
upstream payment-service DB deadlock — checkout routes returning 503\
"""


class ApiGatewayProducer(BaseProducer):
    def __init__(self, ingest_url: str, api_key: str) -> None:
        super().__init__("api-gateway", ingest_url, api_key)

    async def run_normal(self, duration_seconds: int) -> None:
        end = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end:
            level, message, duration_fn = random.choice(_NORMAL_MESSAGES)
            event = self.make_event(level, message, duration_ms=duration_fn())
            await self.push([event])
            await asyncio.sleep(random.uniform(0.7, 1.3))

    async def run_cascade(self, trace_id: str, scenario: str = "pool_exhaustion") -> None:
        self._active_trace_id = trace_id
        if scenario == "memory_leak":
            await self._run_gateway_timeout(trace_id)
        elif scenario == "slow_query":
            await self._run_service_degraded(trace_id)
        else:
            await self._run_service_unavailable(trace_id)
        self._active_trace_id = None

    async def _run_service_unavailable(self, trace_id: str) -> None:
        await asyncio.sleep(2.8)
        for i, message in enumerate(_SERVICE_UNAVAILABLE_ERRORS):
            level = "WARN" if i < 2 else "ERROR"
            await self.push(
                [
                    self.make_event(
                        level,
                        message,
                        error_type="ServiceUnavailableError",
                        stack_trace=_SERVICE_UNAVAILABLE_STACK if i >= 2 else None,
                        trace_id=trace_id,
                        duration_ms=10_000,
                    )
                ]
            )
            await asyncio.sleep(1.8)

    async def _run_gateway_timeout(self, trace_id: str) -> None:
        await asyncio.sleep(4.0)
        for i, message in enumerate(_GATEWAY_TIMEOUT_ERRORS):
            level = "WARN" if i < 3 else "ERROR"
            await self.push(
                [
                    self.make_event(
                        level,
                        message,
                        error_type="GatewayTimeoutError",
                        stack_trace=_GATEWAY_TIMEOUT_STACK if i >= 3 else None,
                        trace_id=trace_id,
                        duration_ms=random.randint(5000, 30_000),
                    )
                ]
            )
            await asyncio.sleep(2.0)

    async def _run_service_degraded(self, trace_id: str) -> None:
        await asyncio.sleep(3.5)
        for i, message in enumerate(_SERVICE_DEGRADED_ERRORS):
            level = "WARN" if i < 3 else "ERROR"
            await self.push(
                [
                    self.make_event(
                        level,
                        message,
                        error_type="ServiceDegradedError",
                        stack_trace=_SERVICE_DEGRADED_STACK if i >= 2 else None,
                        trace_id=trace_id,
                        duration_ms=15_000,
                    )
                ]
            )
            await asyncio.sleep(2.0)
