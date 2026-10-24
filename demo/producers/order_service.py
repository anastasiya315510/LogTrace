"""
OrderServiceProducer — simulates an order management microservice.

Cascade roles by scenario:
  pool_exhaustion — PROPAGATED FAILURE  (UpstreamTimeoutError: payment calls timing out)
  memory_leak     — PROPAGATED FAILURE  (HighLatencyError: payment GC pauses cause slow responses)
  slow_query      — PROPAGATED FAILURE  (LockWaitTimeoutError: waiting on payment-service DB locks)
"""

import asyncio
import random

from demo.producers.base_producer import BaseProducer

_NORMAL_MESSAGES = [
    ("INFO",  "Order created",                          lambda: random.randint(20, 60)),
    ("INFO",  "Order confirmed",                        lambda: random.randint(30, 80)),
    ("INFO",  "Order dispatched to fulfillment",        lambda: random.randint(10, 25)),
    ("INFO",  "Inventory reserved successfully",        lambda: random.randint(5, 20)),
    ("DEBUG", "Payment gateway call initiated",         lambda: random.randint(1, 5)),
    ("INFO",  "Payment gateway responded OK",           lambda: random.randint(90, 250)),
    ("INFO",  "Order status updated to PAID",           lambda: random.randint(5, 15)),
    ("INFO",  "Customer notification sent",             lambda: random.randint(50, 150)),
    ("DEBUG", "Cart cleared after successful checkout", lambda: random.randint(2, 8)),
    ("INFO",  "Return request accepted",                lambda: random.randint(10, 30)),
]

# ── Scenario: pool_exhaustion ─────────────────────────────────────────────────

_UPSTREAM_TIMEOUT_ERRORS = [
    "Payment service call timed out after 5000ms",
    "UpstreamTimeoutError: payment-service did not respond within SLA",
    "UpstreamTimeoutError: 3 retries exhausted — payment-service unreachable",
    "Order processing halted: upstream payment timeout",
    "UpstreamTimeoutError: payment gateway circuit breaker HALF-OPEN",
    "UpstreamTimeoutError: payment-service connection refused (pool exhausted upstream)",
    "Unable to confirm payment — order left in PENDING state",
    "UpstreamTimeoutError: payment-service health check failing",
    "Order queue backlog growing — payment confirmations not arriving",
    "UpstreamTimeoutError: downstream cascade detected from payment-service",
]

_UPSTREAM_STACK = """\
Traceback (most recent call last):
  File "order_service/handlers/checkout.py", line 78, in confirm_payment
    response = await payment_client.charge(order_id, amount, timeout=5.0)
  File "order_service/clients/payment.py", line 34, in charge
    return await asyncio.wait_for(self._post("/charge", payload), timeout=5.0)
asyncio.exceptions.TimeoutError
order_service.exceptions.UpstreamTimeoutError: payment-service did not respond
within 5000ms — upstream pool exhaustion suspected\
"""

# ── Scenario: memory_leak ─────────────────────────────────────────────────────

_HIGH_LATENCY_ERRORS = [
    "Payment-service response latency: 3800ms (SLA: 500ms)",
    "HighLatencyError: payment call took 6200ms — upstream GC pause suspected",
    "Order checkout timeout: payment-service P99 latency spiked to 9400ms",
    "HighLatencyError: payment-service not meeting SLA for 4 consecutive requests",
    "Checkout flow stalled: payment response taking >8s",
    "HighLatencyError: payment-service thread pool saturated due to GC stall",
    "Order queue depth 847 — payment confirmations severely delayed",
    "HighLatencyError: circuit breaker entering HALF-OPEN (payment latency >10s)",
    "Timeout escalation: extending payment timeout from 5s to 30s (emergency)",
    "HighLatencyError: 95% of payment calls exceeding 15s — SLA breach",
]

_HIGH_LATENCY_STACK = """\
Traceback (most recent call last):
  File "order_service/handlers/checkout.py", line 82, in await_payment
    result = await asyncio.wait_for(payment_client.charge(amount), timeout=30.0)
asyncio.exceptions.TimeoutError
order_service.exceptions.HighLatencyError: payment-service exceeded 30s timeout
— GC pause or memory pressure upstream suspected\
"""

# ── Scenario: slow_query ──────────────────────────────────────────────────────

_LOCK_WAIT_ERRORS = [
    "Payment confirmation delayed: payment-service DB lock contention",
    "LockWaitTimeoutError: payment status query blocked by upstream deadlock",
    "Order checkout stuck: payment-service returning lock wait timeouts",
    "LockWaitTimeoutError: SELECT on payment.transactions blocked for 12s",
    "Downstream lock propagation: order cannot read payment status",
    "LockWaitTimeoutError: payment batch job holding exclusive lock on transactions",
    "Order stuck in PENDING: payment-service unable to commit",
    "LockWaitTimeoutError: cascade from payment deadlock — order service degraded",
    "Order processing rate dropped 94% — payment lock contention",
    "LockWaitTimeoutError: abandoning checkout after 5 lock wait retries",
]

_LOCK_WAIT_STACK = """\
Traceback (most recent call last):
  File "order_service/clients/payment.py", line 55, in get_payment_status
    return await self._get(f"/payments/{payment_id}/status", timeout=15.0)
  File "order_service/clients/payment.py", line 71, in _get
    raise LockWaitTimeoutError(f"payment-service lock wait exceeded 15s")
order_service.exceptions.LockWaitTimeoutError: upstream DB deadlock causing
payment-service to block — order checkout cannot proceed\
"""


class OrderServiceProducer(BaseProducer):
    def __init__(self, ingest_url: str, api_key: str) -> None:
        super().__init__("order-service", ingest_url, api_key)

    async def run_normal(self, duration_seconds: int) -> None:
        end = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end:
            level, message, duration_fn = random.choice(_NORMAL_MESSAGES)
            event = self.make_event(level, message, duration_ms=duration_fn())
            await self.push([event])
            await asyncio.sleep(random.uniform(0.9, 1.6))

    async def run_cascade(self, trace_id: str, scenario: str = "pool_exhaustion") -> None:
        self._active_trace_id = trace_id
        if scenario == "memory_leak":
            await self._run_high_latency(trace_id)
        elif scenario == "slow_query":
            await self._run_lock_wait(trace_id)
        else:
            await self._run_upstream_timeout(trace_id)
        self._active_trace_id = None

    async def _run_upstream_timeout(self, trace_id: str) -> None:
        await asyncio.sleep(1.2)
        for i, message in enumerate(_UPSTREAM_TIMEOUT_ERRORS):
            level = "WARN" if i < 2 else "ERROR"
            await self.push([self.make_event(
                level, message,
                error_type="UpstreamTimeoutError",
                stack_trace=_UPSTREAM_STACK if i >= 2 else None,
                trace_id=trace_id,
                duration_ms=5_000,
            )])
            await asyncio.sleep(2.0)

    async def _run_high_latency(self, trace_id: str) -> None:
        await asyncio.sleep(2.0)
        for i, message in enumerate(_HIGH_LATENCY_ERRORS):
            level = "WARN" if i < 3 else "ERROR"
            await self.push([self.make_event(
                level, message,
                error_type="HighLatencyError",
                stack_trace=_HIGH_LATENCY_STACK if i >= 4 else None,
                trace_id=trace_id,
                duration_ms=random.randint(3800, 30_000),
            )])
            await asyncio.sleep(2.5)

    async def _run_lock_wait(self, trace_id: str) -> None:
        await asyncio.sleep(1.5)
        for i, message in enumerate(_LOCK_WAIT_ERRORS):
            level = "WARN" if i < 2 else "ERROR"
            await self.push([self.make_event(
                level, message,
                error_type="LockWaitTimeoutError",
                stack_trace=_LOCK_WAIT_STACK if i >= 3 else None,
                trace_id=trace_id,
                duration_ms=random.randint(12_000, 50_000),
            )])
            await asyncio.sleep(2.2)