"""tests/unit/test_topology.py — unit tests for jobs/stage1/topology.py"""

import uuid
from datetime import UTC, datetime, timedelta

from db.models import LogEvent
from jobs.stage1.topology import TopologyInferrer

SUBMISSION_ID = uuid.uuid4()


def _event(
    service: str,
    level: str = "ERROR",
    offset_seconds: float = 0,
) -> LogEvent:
    return LogEvent(
        event_id=uuid.uuid4(),
        submission_id=SUBMISSION_ID,
        service_name=service,
        event_timestamp=datetime(2026, 10, 16, 10, 0, 0, tzinfo=UTC)
        + timedelta(seconds=offset_seconds),
        level=level,
        message=f"{service} error",
        raw_line=f"ERROR {service}",
    )


# ── test_simple_chain ──────────────────────────────────────────────────────────


def test_simple_chain():
    """
    A→B→C cascade: payment at t=0, order at t=1.2s, gateway at t=2.8s.
    Expected: payment=root_cause, order=propagated_error, gateway=symptom.
    """
    events = [
        _event("payment-service", offset_seconds=0),
        _event("order-service", offset_seconds=1.2),
        _event("api-gateway", offset_seconds=2.8),
    ]
    result = TopologyInferrer().infer(events)

    roles = result["node_roles"]
    assert roles["payment-service"] == "root_cause"
    assert roles["order-service"] == "propagated_error"
    assert roles["api-gateway"] == "symptom"

    # Edges should exist between adjacent services
    weights = result["edge_weights"]
    assert "payment-service→order-service" in weights
    assert "order-service→api-gateway" in weights


def test_simple_chain_adjacency():
    """Adjacency list is consistent with edge weights."""
    events = [
        _event("svc-a", offset_seconds=0),
        _event("svc-b", offset_seconds=2),
    ]
    result = TopologyInferrer().infer(events)
    assert "svc-b" in result["adjacency"].get("svc-a", [])


# ── test_cycle_detection ───────────────────────────────────────────────────────


def test_cycle_detection():
    """
    Events at t=0 (A), t=1 (B), t=2 (A again) can form a potential A→B→A cycle
    in a naive implementation. TopologyInferrer must break it.
    """
    events = [
        _event("svc-a", offset_seconds=0),
        _event("svc-b", offset_seconds=1),
        _event("svc-a", offset_seconds=2),  # could form back edge B→A
    ]
    result = TopologyInferrer().infer(events)

    # Build adjacency and verify no cycle
    adjacency = result["adjacency"]
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def has_cycle(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for neighbour in adjacency.get(node, []):
            if neighbour not in visited:
                if has_cycle(neighbour):
                    return True
            elif neighbour in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    all_nodes = set(adjacency.keys()) | {d for dsts in adjacency.values() for d in dsts}
    for node in all_nodes:
        if node not in visited:
            assert not has_cycle(node), f"Cycle detected involving {node}"


# ── test_single_service ────────────────────────────────────────────────────────


def test_single_service():
    """All events from one service → 1 node, no edges."""
    events = [_event("payment-service", offset_seconds=i) for i in range(5)]
    result = TopologyInferrer().infer(events)

    assert result["adjacency"] == {} or all(len(v) == 0 for v in result["adjacency"].values())
    assert result["edge_weights"] == {}
    assert result["node_roles"]["payment-service"] == "root_cause"


def test_single_service_unaffected_others():
    """Services that only appear in non-error events are marked unaffected."""
    events = [
        _event("error-svc", level="ERROR", offset_seconds=0),
        _event("healthy-svc", level="INFO", offset_seconds=0),
    ]
    result = TopologyInferrer().infer(events)
    assert result["node_roles"]["healthy-svc"] == "unaffected"


# ── test_role_assignment ───────────────────────────────────────────────────────


def test_role_assignment():
    """
    in-degree 0 → root_cause; depth-1 → propagated_error; depth-2+ → symptom.
    """
    events = [
        _event("root", offset_seconds=0),
        _event("middle", offset_seconds=1),
        _event("leaf", offset_seconds=2),
    ]
    result = TopologyInferrer().infer(events)
    roles = result["node_roles"]
    assert roles["root"] == "root_cause"
    assert roles["middle"] == "propagated_error"
    assert roles["leaf"] == "symptom"


def test_no_events_returns_empty():
    """Empty event list → all-empty topology."""
    result = TopologyInferrer().infer([])
    assert result["adjacency"] == {}
    assert result["edge_weights"] == {}
    assert result["node_roles"] == {}
