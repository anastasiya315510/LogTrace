"""
jobs/stage1/correlator.py

Groups parsed LogEvents into Incident objects.

- TraceIdCorrelator  — group ERROR/CRITICAL events sharing a trace_id
- TimeWindowCorrelator — group ERROR/CRITICAL events within a configurable time window
- select_correlator() — pick the right correlator based on the event set

correlate() returns a list of IncidentGroup (Incident + its events) so the caller
has both without a DB round-trip.
"""

import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

import structlog

from db.models import Incident, LogEvent

log = structlog.get_logger()

_INCIDENT_LEVELS = {"ERROR", "CRITICAL"}
_WINDOW_SECONDS = 30  # default


@dataclass
class IncidentGroup:
    """Transient container produced by correlators — not persisted directly."""

    incident: Incident
    events: list[LogEvent] = field(default_factory=list)


class BaseCorrelator(ABC):
    @abstractmethod
    def correlate(self, events: list[LogEvent]) -> list[IncidentGroup]:
        """Group events into IncidentGroup objects. Never raises."""


class TraceIdCorrelator(BaseCorrelator):
    """Groups events that share the same non-empty trace_id."""

    def correlate(self, events: list[LogEvent]) -> list[IncidentGroup]:
        groups: dict[str, list[LogEvent]] = defaultdict(list)
        for event in events:
            if event.trace_id:
                groups[event.trace_id].append(event)

        result: list[IncidentGroup] = []
        for trace_id, group in groups.items():
            if not any(e.level in _INCIDENT_LEVELS for e in group):
                continue  # skip trace groups with no errors
            incident = _make_incident(group, "trace_id")
            result.append(IncidentGroup(incident=incident, events=group))
            log.debug(
                "trace_incident_created",
                trace_id=trace_id,
                event_count=len(group),
            )
        return result


class TimeWindowCorrelator(BaseCorrelator):
    """
    Groups ERROR/CRITICAL events whose timestamps fall within a sliding window.

    Algorithm:
    1. Filter to ERROR/CRITICAL, sort by timestamp.
    2. Sweep: open a new window at the first unclustered event; include every
       subsequent event whose timestamp ≤ window_start + window_seconds.
    3. For each window, collect ALL events (any level) within [first_ts, last_ts].
    4. Dedup: same service+message within 1 second → keep first.
    """

    def __init__(self, window_seconds: int = _WINDOW_SECONDS) -> None:
        self._window_seconds = window_seconds

    def correlate(self, events: list[LogEvent]) -> list[IncidentGroup]:
        error_events = sorted(
            [e for e in events if e.level in _INCIDENT_LEVELS],
            key=lambda e: e.event_timestamp,
        )
        if not error_events:
            return []

        window_td = timedelta(seconds=self._window_seconds)
        windows: list[tuple] = []

        i = 0
        while i < len(error_events):
            window_start = error_events[i].event_timestamp
            window_end = window_start
            j = i + 1
            while j < len(error_events):
                if error_events[j].event_timestamp <= window_start + window_td:
                    window_end = error_events[j].event_timestamp
                    j += 1
                else:
                    break
            windows.append((window_start, window_end))
            i = j

        result: list[IncidentGroup] = []
        for window_start, window_end in windows:
            group = [e for e in events if window_start <= e.event_timestamp <= window_end]
            group = _dedup(group)
            if not any(e.level in _INCIDENT_LEVELS for e in group):
                continue
            incident = _make_incident(group, "time_window")
            result.append(IncidentGroup(incident=incident, events=group))
            log.debug(
                "time_window_incident_created",
                window_start=str(window_start),
                window_end=str(window_end),
                event_count=len(group),
            )
        return result


def _dedup(events: list[LogEvent]) -> list[LogEvent]:
    """Remove duplicate events: same service+message within 1 second → keep first."""
    seen: set[tuple[str, str, str]] = set()
    result: list[LogEvent] = []
    for e in sorted(events, key=lambda x: x.event_timestamp):
        bucket_ts = e.event_timestamp.replace(microsecond=0)
        key = (e.service_name, e.message, str(bucket_ts))
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def _make_incident(group: list[LogEvent], strategy: str) -> Incident:
    services = list({e.service_name for e in group})
    timestamps = [e.event_timestamp for e in group]
    return Incident(
        incident_id=uuid.uuid4(),
        submission_id=group[0].submission_id,
        correlation_strategy=strategy,
        services_involved={"services": services},
        event_count=len(group),
        first_event_timestamp=min(timestamps),
        last_event_timestamp=max(timestamps),
        status="pending",
    )


def select_correlator(
    events: list[LogEvent],
    window_seconds: int = _WINDOW_SECONDS,
) -> BaseCorrelator:
    """
    Choose the appropriate correlator.

    Use TraceIdCorrelator when ≥1 ERROR/CRITICAL event carries a trace_id.
    Fall back to TimeWindowCorrelator otherwise.
    """
    has_trace_ids = any(e.trace_id for e in events if e.level in _INCIDENT_LEVELS)
    if has_trace_ids:
        log.debug("correlator_selected", strategy="trace_id")
        return TraceIdCorrelator()
    log.debug("correlator_selected", strategy="time_window")
    return TimeWindowCorrelator(window_seconds=window_seconds)
