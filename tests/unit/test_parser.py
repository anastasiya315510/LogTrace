"""tests/unit/test_parser.py — unit tests for jobs/stage1/parser.py"""

import json
import uuid
from datetime import UTC, datetime

from jobs.stage1.parser import JsonLineParser, PlaintextParser, detect_format

SUBMISSION_ID = uuid.uuid4()
SERVICE = "payment-service"


def _ts() -> str:
    return datetime.now(UTC).isoformat()


# ── JsonLineParser ─────────────────────────────────────────────────────────────


def test_json_line_parser_full_schema():
    """All known fields are mapped to the correct LogEvent columns."""
    tid = "abc123"
    line = json.dumps(
        {
            "timestamp": _ts(),
            "level": "ERROR",
            "service": "order-service",
            "message": "DB timeout",
            "trace_id": tid,
            "span_id": "span001",
            "error_type": "TimeoutError",
            "stack_trace": "File foo.py line 1",
            "extra_key": "extra_value",
        }
    )
    parser = JsonLineParser()
    event = parser.parse_line(line, SERVICE, SUBMISSION_ID)

    assert event is not None
    assert event.level == "ERROR"
    assert event.service_name == "order-service"
    assert event.message == "DB timeout"
    assert event.trace_id == tid
    assert event.span_id == "span001"
    assert event.error_type == "TimeoutError"
    assert event.stack_trace == "File foo.py line 1"
    # Unknown field goes into metadata
    assert event.extra_metadata is not None
    assert event.extra_metadata.get("extra_key") == "extra_value"


def test_json_line_parser_partial():
    """Missing optional fields are accepted; no exception raised."""
    line = json.dumps(
        {
            "timestamp": _ts(),
            "level": "INFO",
            "message": "ping",
        }
    )
    parser = JsonLineParser()
    event = parser.parse_line(line, SERVICE, SUBMISSION_ID)

    assert event is not None
    assert event.trace_id is None
    assert event.error_type is None
    assert event.stack_trace is None


def test_json_line_parser_malformed_returns_none():
    """Malformed JSON line returns None — no exception raised."""
    parser = JsonLineParser()
    result = parser.parse_line("{not: valid json", SERVICE, SUBMISSION_ID)
    assert result is None


def test_json_line_parser_empty_line_returns_none():
    parser = JsonLineParser()
    assert parser.parse_line("", SERVICE, SUBMISSION_ID) is None
    assert parser.parse_line("   ", SERVICE, SUBMISSION_ID) is None


def test_json_line_parser_level_normalised():
    """Level aliases are normalised: 'warning' → 'WARN'."""
    line = json.dumps({"timestamp": _ts(), "level": "warning", "message": "x"})
    event = JsonLineParser().parse_line(line, SERVICE, SUBMISSION_ID)
    assert event is not None
    assert event.level == "WARN"


# ── PlaintextParser ────────────────────────────────────────────────────────────


def test_plaintext_parser_standard_format():
    """Pattern 1: [TIMESTAMP] LEVEL SERVICE: MESSAGE."""
    line = "[2026-10-16T10:00:00Z] ERROR payment-service: Connection pool exhausted"
    parser = PlaintextParser()
    event = parser.parse_line(line, SERVICE, SUBMISSION_ID)

    assert event is not None
    assert event.level == "ERROR"
    assert "Connection pool exhausted" in event.message


def test_plaintext_parser_iso_format():
    """Pattern 2: TIMESTAMP LEVEL MESSAGE."""
    line = "2026-10-16T10:00:01Z ERROR pool timeout after 30s"
    parser = PlaintextParser()
    event = parser.parse_line(line, SERVICE, SUBMISSION_ID)

    assert event is not None
    assert event.level == "ERROR"
    assert "pool timeout" in event.message


def test_plaintext_parser_unrecognised_returns_none():
    """Unrecognised format: skip with no exception."""
    parser = PlaintextParser()
    result = parser.parse_line("random line with no timestamp", SERVICE, SUBMISSION_ID)
    assert result is None


def test_plaintext_parser_empty_returns_none():
    parser = PlaintextParser()
    assert parser.parse_line("", SERVICE, SUBMISSION_ID) is None


# ── detect_format ──────────────────────────────────────────────────────────────


def test_format_detection_json():
    first_line = json.dumps({"timestamp": _ts(), "level": "INFO", "message": "ok"})
    assert detect_format(first_line) is JsonLineParser


def test_format_detection_plaintext():
    first_line = "2026-10-16T10:00:00Z INFO Service started"
    assert detect_format(first_line) is PlaintextParser
