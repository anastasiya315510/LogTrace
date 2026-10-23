"""Initial schema — all 7 tables with indexes.

Revision ID: 001
Revises:
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "submissions",
        sa.Column("submission_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_method", sa.String(32), nullable=False),
        sa.Column("file_names", JSONB, nullable=True),
        sa.Column("object_keys", JSONB, nullable=True),
        sa.Column("ingest_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingest_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "log_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submission_id",
            UUID(as_uuid=True),
            sa.ForeignKey("submissions.submission_id"),
            nullable=False,
        ),
        sa.Column("service_name", sa.String(100), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("span_id", sa.String(32), nullable=True),
        sa.Column("error_type", sa.String(200), nullable=True),
        sa.Column("stack_trace", sa.Text, nullable=True),
        sa.Column("raw_line", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
    )

    # Primary query pattern: correlation engine reads all events for a submission
    op.create_index(
        "idx_log_events_submission_level_ts",
        "log_events",
        ["submission_id", "level", sa.text("event_timestamp DESC")],
    )

    # Strategy-A correlation: group by trace_id
    op.create_index(
        "idx_log_events_trace_id",
        "log_events",
        ["trace_id"],
        postgresql_where=sa.text("trace_id IS NOT NULL"),
    )

    op.create_table(
        "incidents",
        sa.Column("incident_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submission_id",
            UUID(as_uuid=True),
            sa.ForeignKey("submissions.submission_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("correlation_strategy", sa.String(20), nullable=False),
        sa.Column("services_involved", JSONB, nullable=False),
        sa.Column("service_topology_json", JSONB, nullable=True),
        sa.Column("event_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_event_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )

    op.create_table(
        "event_classifications",
        sa.Column("classification_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("log_events.event_id"),
            nullable=False,
        ),
        sa.Column("anomaly_score", sa.Float, nullable=False),
        sa.Column("event_role", sa.String(30), nullable=False),
        sa.Column("error_category", sa.String(40), nullable=False),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "incident_analyses",
        sa.Column("analysis_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incidents.incident_id"),
            nullable=False,
        ),
        sa.Column("root_cause_service", sa.String(100), nullable=True),
        sa.Column("root_cause_method", sa.String(200), nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("cascade_explanation", sa.Text, nullable=True),
        sa.Column("cascade_chain_json", JSONB, nullable=True),
        sa.Column("alternative_hypotheses_json", JSONB, nullable=True),
        sa.Column("conversation_history_json", JSONB, nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "fix_suggestions",
        sa.Column("suggestion_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incidents.incident_id"),
            nullable=False,
        ),
        sa.Column("search_query", sa.String(500), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("source_title", sa.String(300), nullable=False),
        sa.Column("excerpt", sa.Text, nullable=False),
        sa.Column("tavily_score", sa.Float, nullable=False),
        sa.Column("query_type", sa.String(20), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column("key_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_plain", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("daily_submission_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("daily_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("fix_suggestions")
    op.drop_table("incident_analyses")
    op.drop_table("event_classifications")
    op.drop_table("incidents")
    op.drop_index("idx_log_events_trace_id", table_name="log_events")
    op.drop_index("idx_log_events_submission_level_ts", table_name="log_events")
    op.drop_table("log_events")
    op.drop_table("submissions")
