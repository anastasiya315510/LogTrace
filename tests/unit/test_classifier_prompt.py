"""tests/unit/test_classifier_prompt.py — unit tests for jobs/stage2/classifier.py"""

import json
import uuid
from datetime import UTC, datetime

from db.models import LogEvent
from jobs.stage2.classifier import build_nano_prompt, parse_nano_response

SUBMISSION_ID = uuid.uuid4()


def _event(i: int) -> LogEvent:
    return LogEvent(
        event_id=uuid.uuid4(),
        submission_id=SUBMISSION_ID,
        service_name="svc",
        event_timestamp=datetime.now(UTC),
        level="ERROR",
        message=f"error message {i}",
        raw_line=f"error {i}",
    )


def test_batch_prompt_construction():
    """20 events → all 20 appear in the rendered prompt."""
    events = [_event(i) for i in range(20)]
    prompt = build_nano_prompt(events)

    # All 20 event messages must appear in the prompt
    for i in range(20):
        assert f"error message {i}" in prompt, f"event {i} missing from prompt"

    # The batch size placeholder is substituted
    assert "20" in prompt

    # The events are embedded as a JSON array containing event_index keys
    assert '"event_index"' in prompt
    # All 20 indices 0–19 must appear
    for i in range(20):
        assert f'"event_index": {i}' in prompt


def test_nano_response_malformed_returns_fallback():
    """Invalid JSON → 20 noise/unknown classifications, no exception raised."""
    events = [_event(i) for i in range(20)]
    result = parse_nano_response("{not valid json", events)

    assert len(result) == 20
    for r in result:
        assert r.event_role == "noise"
        assert r.error_category == "unknown"
        assert r.anomaly_score == 0.0


def test_nano_response_length_mismatch_returns_fallback():
    """Array shorter than batch → all fallback, no exception raised."""
    events = [_event(i) for i in range(5)]
    short_response = json.dumps(
        [
            {
                "event_index": 0,
                "event_role": "noise",
                "error_category": "unknown",
                "anomaly_score": 0.0,
            }
        ]
    )
    result = parse_nano_response(short_response, events)

    assert len(result) == 5
    for r in result:
        assert r.event_role == "noise"


def test_nano_response_valid():
    """Valid JSON array with correct length → classifications returned."""
    events = [_event(i) for i in range(3)]
    response = json.dumps(
        [
            {
                "event_index": 0,
                "event_role": "root_candidate",
                "error_category": "timeout",
                "anomaly_score": 1.0,
            },
            {
                "event_index": 1,
                "event_role": "propagated_error",
                "error_category": "connection_refused",
                "anomaly_score": 0.8,
            },
            {
                "event_index": 2,
                "event_role": "noise",
                "error_category": "noise",
                "anomaly_score": 0.1,
            },
        ]
    )
    result = parse_nano_response(response, events)

    assert len(result) == 3
    assert result[0].event_role == "root_candidate"
    assert result[0].error_category == "timeout"
    assert result[0].anomaly_score == 1.0


def test_nano_response_non_array_returns_fallback():
    """Non-array JSON → fallback, no exception."""
    events = [_event(0)]
    result = parse_nano_response('{"key": "value"}', events)
    assert len(result) == 1
    assert result[0].event_role == "noise"
