"""tests/unit/test_correlator.py — unit tests for jobs/stage1/correlator.py"""

import uuid
from datetime import UTC, datetime, timedelta

from db.models import LogEvent
from jobs.stage1.correlator import (
    TimeWindowCorrelator,
    TraceIdCorrelator,
    select_correlator,
)

SUBMISSION_ID = uuid.uuid4()


def _event(
    service: str = "svc",
    level: str = "ERROR",
    trace_id: str | None = None,
    offset_seconds: float = 0,
    message: str = "error occurred",
) -> LogEvent:
    return LogEvent(
        event_id=uuid.uuid4(),
        submission_id=SUBMISSION_ID,
        service_name=service,
        event_timestamp=datetime(2026, 10, 16, 10, 0, 0, tzinfo=UTC)
        + timedelta(seconds=offset_seconds),
        level=level,
        message=message,
        raw_line=f"{level} {message}",
        trace_id=trace_id,
    )


# ── TraceIdCorrelator ──────────────────────────────────────────────────────────


def test_trace_id_correlation():
    """10 events sharing a trace_id → exactly 1 incident."""
    tid = "trace-abc"
    events = [_event(service=f"svc-{i}", trace_id=tid) for i in range(10)]
    groups = TraceIdCorrelator().correlate(events)

    assert len(groups) == 1
    assert groups[0].incident.event_count == 10


def test_trace_id_no_error_events_skipped():
    """Trace groups with only INFO events produce no incidents."""
    events = [_event(level="INFO", trace_id="t1"), _event(level="INFO", trace_id="t1")]
    groups = TraceIdCorrelator().correlate(events)
    assert len(groups) == 0


def test_trace_id_multiple_groups():
    """Two distinct trace IDs produce two incidents."""
    events = [
        _event(trace_id="t1"),
        _event(trace_id="t1"),
        _event(trace_id="t2"),
    ]
    groups = TraceIdCorrelator().correlate(events)
    assert len(groups) == 2


# ── TimeWindowCorrelator ───────────────────────────────────────────────────────


def test_time_window_correlation():
    """6 ERROR events within 30 s → 1 incident."""
    events = [_event(offset_seconds=i * 4) for i in range(6)]  # 0, 4, 8, 12, 16, 20s
    groups = TimeWindowCorrelator(window_seconds=30).correlate(events)
    assert len(groups) == 1
    assert groups[0].incident.event_count == 6


def test_time_window_two_incidents():
    """Events at t=0 and t=120s fall into two separate incidents."""
    early = [_event(offset_seconds=i) for i in range(4)]
    late = [_event(offset_seconds=120 + i) for i in range(4)]
    groups = TimeWindowCorrelator(window_seconds=30).correlate(early + late)
    assert len(groups) == 2


def test_time_window_no_errors_returns_empty():
    events = [_event(level="INFO", offset_seconds=i) for i in range(5)]
    groups = TimeWindowCorrelator().correlate(events)
    assert len(groups) == 0


def test_dedup():
    """Same service+message within 1 s → only 1 copy retained in the incident."""
    events = [
        _event(service="svc-a", offset_seconds=0.0, message="pool timeout"),
        _event(service="svc-a", offset_seconds=0.3, message="pool timeout"),
        _event(service="svc-a", offset_seconds=0.6, message="pool timeout"),
    ]
    groups = TimeWindowCorrelator(window_seconds=30).correlate(events)
    assert len(groups) == 1
    assert groups[0].incident.event_count == 1


def test_dedup_different_messages_kept():
    """Different messages within 1 s are NOT deduplicated."""
    events = [
        _event(offset_seconds=0.0, message="msg-a"),
        _event(offset_seconds=0.1, message="msg-b"),
    ]
    groups = TimeWindowCorrelator(window_seconds=30).correlate(events)
    assert groups[0].incident.event_count == 2


# ── select_correlator ──────────────────────────────────────────────────────────


def test_select_correlator_prefers_trace_id():
    events = [_event(trace_id="t1"), _event(trace_id=None)]
    correlator = select_correlator(events)
    assert isinstance(correlator, TraceIdCorrelator)


def test_select_correlator_falls_back_to_time_window():
    events = [_event(trace_id=None), _event(trace_id=None)]
    correlator = select_correlator(events)
    assert isinstance(correlator, TimeWindowCorrelator)
