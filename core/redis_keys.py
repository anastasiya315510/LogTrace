"""
Single source of truth for every Redis key and channel name in NemoTrace.

All modules (API, Stream Processor, Jobs, Portal) import from here.
Changing a key name requires editing exactly one place.
"""


class RedisKeys:
    # ── Ingest queues ─────────────────────────────────────────────────────────
    # One Redis Stream per service; Stream Processor reads these with XREADGROUP.
    @staticmethod
    def ingest_stream(service: str) -> str:
        return f"stream:ingest:{service}"

    # ── Demo orchestration ────────────────────────────────────────────────────
    # Hash of demo runtime state (phase, session_id, trace_id, per-service counters).
    DEMO_STATE = "demo:state"
    # Pub/sub channel for start_normal / cascade / stop commands → producers.
    DEMO_COMMANDS = "demo:commands"

    # ── Auth cache ────────────────────────────────────────────────────────────
    # Caches validated API keys for 5 minutes to avoid per-request DB hits.
    @staticmethod
    def auth_cache(key_hash: str) -> str:
        return f"auth:key:{key_hash}"

    # ── SSE progress channels ─────────────────────────────────────────────────
    # Stage-1 and Stage-2 jobs publish tokens here; submissions/stream subscribes.
    @staticmethod
    def sse_channel(submission_id: str) -> str:
        return f"sse:submission:{submission_id}"

    # ── Analysis queue ────────────────────────────────────────────────────────
    # Stream Processor and Stage-1 write job payloads here; Stage-2 reads them.
    @staticmethod
    def analysis_queue() -> str:
        return "queue:analysis"

    # ── Stream Processor consumer group ──────────────────────────────────────
    SP_CONSUMER_GROUP = "nemotrace-sp"
    SP_CONSUMER_NAME = "sp-consumer-1"

    # ── Stream Processor reset signal ─────────────────────────────────────────
    # Set by demo reset; stream processor clears in-memory windows on next tick.
    SP_RESET_SIGNAL = "stream_processor:reset"
