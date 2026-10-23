"""
PaymentServiceProducer — simulates a payment microservice.

Cascade role: ROOT CAUSE
  - Injects 15 PoolTimeoutError events over 25 seconds.
  - All cascade events share the trace_id so NemoTrace can correlate them.
"""

import asyncio
import random

from demo.producers.base_producer import BaseProducer

_NORMAL_MESSAGES = [
    ("INFO", "Payment authorisation started", lambda: random.randint(10, 30)),
    ("INFO", "Payment authorisation succeeded", lambda: random.randint(80, 200)),
    ("INFO", "Card tokenisation completed", lambda: random.randint(5, 15)),
    ("DEBUG", "DB connection acquired from pool", lambda: random.randint(1, 5)),
    ("DEBUG", "DB connection released to pool", lambda: random.randint(1, 3)),
    ("INFO", "Fraud check passed", lambda: random.randint(20, 60)),
    ("INFO", "Settlement batch enqueued", lambda: random.randint(2, 8)),
    ("INFO", "Refund processed successfully", lambda: random.randint(50, 120)),
    ("DEBUG", "Idempotency key validated", lambda: random.randint(1, 4)),
    ("INFO", "3DS challenge completed", lambda: random.randint(300, 800)),
]

_CASCADE_ERRORS = [
    "DB connection pool exhausted after 30s timeout",
    "PoolTimeoutError: no idle connections available (pool_size=10, overflow=5)",
    "PoolTimeoutError: timed out waiting for connection from pool",
    "DB connection pool exhausted — all 15 connections busy",
    "PoolTimeoutError: acquire() exceeded timeout=30.0s",
    "Connection pool saturated — request dropped",
    "PoolTimeoutError: pool queue depth=47, giving up",
    "DB pool health check failed — connections unresponsive",
    "PoolTimeoutError: checkout timed out (pool_timeout=30)",
    "DB pool overflow limit reached — rejecting new requests",
    "PoolTimeoutError: maximum overflow size reached",
    "Database connection pool deadlock detected",
    "PoolTimeoutError: pre-ping failed on 12/15 connections",
    "DB pool not recovering — all acquire() calls timing out",
    "PoolTimeoutError: circuit breaker OPEN after 15 consecutive failures",
]

_STACK_TRACE = """\
Traceback (most recent call last):
  File "payment_service/handlers/charge.py", line 112, in handle_charge
    conn = await pool.acquire(timeout=30.0)
  File "sqlalchemy/pool/asyncio.py", line 89, in acquire
    return await asyncio.wait_for(self._do_acquire(), timeout)
asyncio.exceptions.TimeoutError
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 5 reached,
connection timed out, timeout 30.00 (Background on this error at:
https://sqlalche.me/e/14/3o7r)\
"""


class PaymentServiceProducer(BaseProducer):
    """
    Simulates the payment-service microservice.
    Normal traffic: random authorisation / refund events at ~1 event/second.
    Cascade: 15 PoolTimeoutError bursts over 25 seconds (root cause of the chain).
    """

    def __init__(self, ingest_url: str, api_key: str) -> None:
        super().__init__("payment-service", ingest_url, api_key)

    # ── Normal traffic ────────────────────────────────────────────────────────

    async def run_normal(self, duration_seconds: int) -> None:
        end = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end:
            level, message, duration_fn = random.choice(_NORMAL_MESSAGES)
            event = self.make_event(level, message, duration_ms=duration_fn())
            await self.push([event])
            await asyncio.sleep(random.uniform(0.8, 1.5))

    # ── Cascade injection ─────────────────────────────────────────────────────

    async def run_cascade(self, trace_id: str) -> None:
        """
        Fire 15 PoolTimeoutError events spread over 25 seconds.
        Events escalate from WARN to ERROR as the pool degrades.
        """
        self._active_trace_id = trace_id

        for i, message in enumerate(_CASCADE_ERRORS):
            # First 3 events are WARN (pool pressure); remaining are ERROR
            level = "WARN" if i < 3 else "ERROR"
            event = self.make_event(
                level,
                message,
                error_type="PoolTimeoutError",
                stack_trace=_STACK_TRACE if i >= 3 else None,
                trace_id=trace_id,
                duration_ms=30_000,  # 30s timeout
            )
            await self.push([event])
            # Spread 15 events over 25 seconds (~1.67s apart)
            await asyncio.sleep(25 / len(_CASCADE_ERRORS))

        self._active_trace_id = None
