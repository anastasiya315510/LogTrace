import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── Ingest ────────────────────────────────────────────────────────────────────


class RawEvent(BaseModel):
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    level: str = Field(..., description="ERROR | WARN | INFO | DEBUG | CRITICAL")
    message: str
    trace_id: str | None = None
    span_id: str | None = None
    error_type: str | None = None
    stack_trace: str | None = None
    duration_ms: int | None = None
    # any extra fields are accepted and forwarded as-is
    model_config = {"extra": "allow"}


class IngestPayload(BaseModel):
    service: str = Field(..., min_length=1, max_length=100)
    events: list[RawEvent] = Field(..., min_length=1)


class IngestResponse(BaseModel):
    accepted: int
    dropped: int


# ── Submissions ───────────────────────────────────────────────────────────────


class SubmissionResponse(BaseModel):
    submission_id: uuid.UUID
    status: str


class SubmissionStatusResponse(BaseModel):
    submission_id: uuid.UUID
    status: str
    incident_count: int
    created_at: datetime


# ── Incidents ─────────────────────────────────────────────────────────────────


class IncidentSummary(BaseModel):
    incident_id: uuid.UUID
    status: str
    root_cause_service: str | None
    confidence_score: float | None


class IncidentListResponse(BaseModel):
    incidents: list[IncidentSummary]


class FixSuggestionOut(BaseModel):
    source_title: str
    source_url: str
    excerpt: str
    tavily_score: float
    query_type: str


class IncidentReportResponse(BaseModel):
    incident_id: uuid.UUID
    status: str
    services_involved: list[str]
    service_topology: dict | None
    root_cause_service: str | None
    root_cause_method: str | None
    confidence_score: float | None
    cascade_explanation: str | None
    cascade_chain: list[dict] | None
    alternative_hypotheses: list[dict] | None
    fix_suggestions: list[FixSuggestionOut]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str


class ReadinessCheck(BaseModel):
    postgres: str
    redis: str


class ReadinessResponse(BaseModel):
    status: str
    checks: ReadinessCheck


# ── Demo ──────────────────────────────────────────────────────────────────────


class DemoStartRequest(BaseModel):
    services: list[str] = Field(default=["payment-service", "order-service", "api-gateway"])
    normal_duration_seconds: int = Field(default=60, ge=10, le=300)


class DemoStartResponse(BaseModel):
    demo_session_id: str
    phase: str
    services: list[str]
    message: str


class DemoCascadeRequest(BaseModel):
    scenario: str = Field(default="pool_exhaustion", description="pool_exhaustion | memory_leak | slow_query")


class DemoCascadeResponse(BaseModel):
    phase: str
    trace_id: str
    scenario: str
    cascade_sequence: list[dict]
    expected_trigger_in_seconds: int
    message: str


class DemoStatusResponse(BaseModel):
    phase: str
    events_pushed: dict[str, int]
    auto_triggered: bool
    submission_id: uuid.UUID | None
    incident_id: uuid.UUID | None = None
    message: str | None = None


class DemoResetRequest(BaseModel):
    clear_redis_streams: bool = True
    clear_db_submissions: bool = False


class DemoResetResponse(BaseModel):
    phase: str
    redis_streams_cleared: bool
    db_submissions_cleared: bool
    message: str
