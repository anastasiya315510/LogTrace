import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Submission(Base):
    __tablename__ = "submissions"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # push | upload | auto_trigger
    source_method: Mapped[str] = mapped_column(String(32), nullable=False)
    # nullable — only for upload submissions
    file_names: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    object_keys: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # nullable — only for push/auto_trigger submissions
    ingest_window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ingest_window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # received | processing | complete | failed | no_incidents
    raw_status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="submission")
    log_events: Mapped[list["LogEvent"]] = relationship(back_populates="submission")


class LogEvent(Base):
    __tablename__ = "log_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.submission_id"), nullable=False
    )
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    submission: Mapped["Submission"] = relationship(back_populates="log_events")
    classification: Mapped["EventClassification | None"] = relationship(
        back_populates="event", uselist=False
    )


class Incident(Base):
    __tablename__ = "incidents"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.submission_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # trace_id | time_window
    correlation_strategy: Mapped[str] = mapped_column(String(20), nullable=False)
    services_involved: Mapped[dict] = mapped_column(JSONB, nullable=False)
    service_topology_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_event_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # pending | classifying | analyzing | complete | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    submission: Mapped["Submission"] = relationship(back_populates="incidents")
    analysis: Mapped["IncidentAnalysis | None"] = relationship(
        back_populates="incident", uselist=False
    )
    fix_suggestions: Mapped[list["FixSuggestion"]] = relationship(back_populates="incident")


class EventClassification(Base):
    __tablename__ = "event_classifications"

    classification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("log_events.event_id"), nullable=False
    )
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    # root_candidate | propagated_error | symptom | noise
    event_role: Mapped[str] = mapped_column(String(30), nullable=False)
    # timeout | null_pointer | connection_refused | out_of_memory |
    # authentication_failure | data_corruption | unknown
    error_category: Mapped[str] = mapped_column(String(40), nullable=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    event: Mapped["LogEvent"] = relationship(back_populates="classification")


class IncidentAnalysis(Base):
    __tablename__ = "incident_analyses"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id"), nullable=False
    )
    root_cause_service: Mapped[str | None] = mapped_column(String(100), nullable=True)
    root_cause_method: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cascade_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    cascade_chain_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    alternative_hypotheses_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    conversation_history_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    incident: Mapped["Incident"] = relationship(back_populates="analysis")


class FixSuggestion(Base):
    __tablename__ = "fix_suggestions"

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id"), nullable=False
    )
    search_query: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    tavily_score: Mapped[float] = mapped_column(Float, nullable=False)
    # remediation | vulnerability
    query_type: Mapped[str] = mapped_column(String(20), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    incident: Mapped["Incident"] = relationship(back_populates="fix_suggestions")


class ApiKey(Base):
    __tablename__ = "api_keys"

    key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # plain key stored only in dev for the demo key — production uses hash only
    key_plain: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    daily_submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
