"""
OrderServiceProducer — simulates an order management microservice.

Cascade role: PROPAGATED FAILURE
  - Waits 1.2 seconds after the payment-service cascade starts, then injects
    UpstreamTimeoutError events caused by payment calls timing out.
"""

import asyncio
import random

from demo.producers.base_producer import BaseProducer

_NORMAL_MESSAGES = [
    ("INFO", "Order created", lambda: random.randint(20, 60)),
    ("INFO", "Order confirmed", lambda: random.randint(30, 80)),
    ("INFO", "Order dispatched to fulfillment", lambda: random.randint(10, 25)),
    ("INFO", "Inventory reserved successfully", lambda: random.randint(5, 20)),
    ("DEBUG", "Payment gateway call initiated", lambda: random.randint(1, 5)),
    ("INFO", "Payment gateway responded OK", lambda: random.randint(90, 250)),
    ("INFO", "Order status updated to PAID", lambda: random.randint(5, 15)),
    ("INFO", "Customer notification sent", lambda: random.randint(50, 150)),
    ("DEBUG", "Cart cleared after successful checkout", lambda: random.randint(2, 8)),
    ("INFO", "Return request accepted", lambda: random.randint(10, 30)),
]

_CASCADE_ERRORS = [
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

_STACK_TRACE = """\
Traceback (most recent call last):
  File "order_service/handlers/checkout.py", line 78, in confirm_payment
    response = await payment_client.charge(order_id, amount, timeout=5.0)
  File "order_service/clients/payment.py", line 34, in charge
    return await asyncio.wait_for(self._post("/charge", payload), timeout=5.0)
asyncio.exceptions.TimeoutError
order_service.exceptions.UpstreamTimeoutError: payment-service did not respond
within 5000ms — upstream pool exhaustion suspected\
"""


class OrderServiceProducer(BaseProducer):
    """
    Simulates the order-service microservice.
    Normal traffic: order lifecycle events at ~1 event/second.
    Cascade: UpstreamTimeoutError bursts starting 1.2s after payment-service failure.
    """

    def __init__(self, ingest_url: str, api_key: str) -> None:
        super().__init__("order-service", ingest_url, api_key)

    # ── Normal traffic ────────────────────────────────────────────────────────

    async def run_normal(self, duration_seconds: int) -> None:
        end = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end:
            level, message, duration_fn = random.choice(_NORMAL_MESSAGES)
            event = self.make_event(level, message, duration_ms=duration_fn())
            await self.push([event])
            await asyncio.sleep(random.uniform(0.9, 1.6))

    # ── Cascade injection ─────────────────────────────────────────────────────

    async def run_cascade(self, trace_id: str) -> None:
        """
        Wait 1.2s (propagation delay), then fire 10 UpstreamTimeoutError events.
        """
        await asyncio.sleep(1.2)
        self._active_trace_id = trace_id

        for i, message in enumerate(_CASCADE_ERRORS):
            level = "WARN" if i < 2 else "ERROR"
            event = self.make_event(
                level,
                message,
                error_type="UpstreamTimeoutError",
                stack_trace=_STACK_TRACE if i >= 2 else None,
                trace_id=trace_id,
                duration_ms=5_000,
            )
            await self.push([event])
            await asyncio.sleep(2.0)

        self._active_trace_id = None
