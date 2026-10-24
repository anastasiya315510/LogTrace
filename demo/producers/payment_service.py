"""
PaymentServiceProducer — simulates a payment microservice.

Cascade roles by scenario:
  pool_exhaustion — ROOT CAUSE  (PoolTimeoutError: DB pool exhausted)
  memory_leak     — ROOT CAUSE  (OutOfMemoryError: heap leak → GC pauses)
  slow_query      — ROOT CAUSE  (DeadlockError: DB deadlock on transactions table)
"""

import asyncio
import random

from demo.producers.base_producer import BaseProducer

_NORMAL_MESSAGES = [
    ("INFO",  "Payment authorisation started",      lambda: random.randint(10, 30)),
    ("INFO",  "Payment authorisation succeeded",     lambda: random.randint(80, 200)),
    ("INFO",  "Card tokenisation completed",         lambda: random.randint(5, 15)),
    ("DEBUG", "DB connection acquired from pool",    lambda: random.randint(1, 5)),
    ("DEBUG", "DB connection released to pool",      lambda: random.randint(1, 3)),
    ("INFO",  "Fraud check passed",                  lambda: random.randint(20, 60)),
    ("INFO",  "Settlement batch enqueued",           lambda: random.randint(2, 8)),
    ("INFO",  "Refund processed successfully",       lambda: random.randint(50, 120)),
    ("DEBUG", "Idempotency key validated",           lambda: random.randint(1, 4)),
    ("INFO",  "3DS challenge completed",             lambda: random.randint(300, 800)),
]

# ── Scenario: pool_exhaustion ─────────────────────────────────────────────────

_POOL_ERRORS = [
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

_POOL_STACK = """\
Traceback (most recent call last):
  File "payment_service/handlers/charge.py", line 112, in handle_charge
    conn = await pool.acquire(timeout=30.0)
  File "sqlalchemy/pool/asyncio.py", line 89, in acquire
    return await asyncio.wait_for(self._do_acquire(), timeout)
asyncio.exceptions.TimeoutError
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 5 reached,
connection timed out, timeout 30.00\
"""

# ── Scenario: memory_leak ─────────────────────────────────────────────────────

_MEMORY_ERRORS = [
    "Heap usage at 72% — allocation rate anomaly detected",
    "OutOfMemoryError: payment session cache growing unbounded",
    "GC pause 1.2s — heap pressure from unclosed tokenisation objects",
    "OutOfMemoryError: fraud-score cache leaked 2.4 GB",
    "GC pause 3.7s — full collection triggered at 89% heap",
    "OutOfMemoryError: card-bin lookup table not evicted (TTL bug)",
    "JVM heap: 7.8 GB / 8 GB — OOM imminent",
    "OutOfMemoryError: thread pool exhausted due to GC stall",
    "GC pause 8.1s — application threads stopped",
    "OutOfMemoryError: unable to allocate native buffer for TLS session",
    "Heap dump written — service entering degraded mode",
    "OutOfMemoryError: circuit breaker cannot open, GC loop",
    "RSS grew from 2 GB to 11 GB in 4 minutes — leak confirmed",
]

_MEMORY_STACK = """\
Traceback (most recent call last):
  File "payment_service/cache/session_store.py", line 88, in _store_session
    self._cache[session_id] = SessionRecord(data, ttl=None)  # BUG: TTL never set
  File "payment_service/cache/session_store.py", line 43, in __setitem__
    self._internal[key] = value
builtins.MemoryError: cannot allocate 64 MB for session record
payment_service.exceptions.OutOfMemoryError: heap exhausted — session cache unbounded\
"""

# ── Scenario: slow_query ──────────────────────────────────────────────────────

_DEADLOCK_ERRORS = [
    "Slow query detected: SELECT on transactions table took 4200ms",
    "DeadlockError: transaction lock wait timeout exceeded (innodb_lock_wait_timeout=50)",
    "DB deadlock on transactions table — rollback forced",
    "DeadlockError: two concurrent UPDATE statements deadlocked (txn_id=8821, txn_id=8847)",
    "Lock wait timeout: row-level lock held >50s on payments.transactions",
    "DeadlockError: cycle detected in lock dependency graph",
    "Slow query 12.3s: UPDATE transactions SET status=settled WHERE batch_id=...",
    "DeadlockError: InnoDB deadlock — victim transaction rolled back",
    "Index scan degraded: missing index on transactions(created_at, merchant_id)",
    "DeadlockError: deadlock retry limit exceeded (attempt 5/5)",
    "Table statistics stale — query planner chose full table scan (18M rows)",
    "DeadlockError: settlement batch job conflicting with real-time charge writes",
]

_DEADLOCK_STACK = """\
Traceback (most recent call last):
  File "payment_service/settlement/batch.py", line 67, in run_batch
    await db.execute("UPDATE transactions SET status='settled' WHERE ...")
  File "sqlalchemy/engine/asyncio.py", line 134, in execute
    return await asyncio.shield(self._execute_async(object_, *args, **kw))
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError)
(1213, 'Deadlock found when trying to get lock; try restarting transaction')
payment_service.exceptions.DeadlockError: DB deadlock — settlement batch vs charge handler\
"""


class PaymentServiceProducer(BaseProducer):
    def __init__(self, ingest_url: str, api_key: str) -> None:
        super().__init__("payment-service", ingest_url, api_key)

    async def run_normal(self, duration_seconds: int) -> None:
        end = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end:
            level, message, duration_fn = random.choice(_NORMAL_MESSAGES)
            event = self.make_event(level, message, duration_ms=duration_fn())
            await self.push([event])
            await asyncio.sleep(random.uniform(0.8, 1.5))

    async def run_cascade(self, trace_id: str, scenario: str = "pool_exhaustion") -> None:
        self._active_trace_id = trace_id
        if scenario == "memory_leak":
            await self._run_memory_leak(trace_id)
        elif scenario == "slow_query":
            await self._run_slow_query(trace_id)
        else:
            await self._run_pool_exhaustion(trace_id)
        self._active_trace_id = None

    async def _run_pool_exhaustion(self, trace_id: str) -> None:
        for i, message in enumerate(_POOL_ERRORS):
            level = "WARN" if i < 3 else "ERROR"
            await self.push([self.make_event(
                level, message,
                error_type="PoolTimeoutError",
                stack_trace=_POOL_STACK if i >= 3 else None,
                trace_id=trace_id,
                duration_ms=30_000,
            )])
            await asyncio.sleep(25 / len(_POOL_ERRORS))

    async def _run_memory_leak(self, trace_id: str) -> None:
        for i, message in enumerate(_MEMORY_ERRORS):
            level = "WARN" if i < 1 else "ERROR"
            await self.push([self.make_event(
                level, message,
                error_type="OutOfMemoryError",
                stack_trace=_MEMORY_STACK if i >= 5 else None,
                trace_id=trace_id,
                duration_ms=random.randint(1200, 8100) if "GC pause" in message else 100,
            )])
            await asyncio.sleep(28 / len(_MEMORY_ERRORS))

    async def _run_slow_query(self, trace_id: str) -> None:
        for i, message in enumerate(_DEADLOCK_ERRORS):
            level = "WARN" if i < 1 else "ERROR"
            await self.push([self.make_event(
                level, message,
                error_type="DeadlockError",
                stack_trace=_DEADLOCK_STACK if i >= 3 else None,
                trace_id=trace_id,
                duration_ms=random.randint(4200, 12300) if "Slow query" in message else 50_000,
            )])
            await asyncio.sleep(25 / len(_DEADLOCK_ERRORS))