"""
jobs/stage1/parser.py

Format-agnostic log line parser.

Design:
- BaseParser ABC — one method: parse_line() returns LogEvent | None (never raises)
- JsonLineParser — maps known fields, stashes unknowns in metadata JSONB
- PlaintextParser — two regex patterns covering common layouts
- detect_format() — inspect the first non-empty line and return the right parser class
"""

import json
import re
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import structlog
from dateutil import parser as dateutil_parser

from db.models import LogEvent

log = structlog.get_logger()

_LEVEL_NORMALISE = {
    "WARNING": "WARN",
    "WARN": "WARN",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "CRITICAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "FATAL": "CRITICAL",
    "INFO": "INFO",
    "DEBUG": "DEBUG",
    "DBG": "DEBUG",
    "TRACE": "DEBUG",
}

_KNOWN_FIELDS = {
    "timestamp",
    "time",
    "ts",
    "@timestamp",
    "level",
    "severity",
    "lvl",
    "service",
    "service_name",
    "app",
    "message",
    "msg",
    "trace_id",
    "traceId",
    "trace-id",
    "span_id",
    "spanId",
    "span-id",
    "error_type",
    "errorType",
    "exception",
    "stack_trace",
    "stackTrace",
    "stack",
    "duration_ms",
    "durationMs",
    "duration",
}


def _normalise_level(raw: str) -> str:
    return _LEVEL_NORMALISE.get(raw.upper().strip(), "INFO")


def _parse_timestamp(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    try:
        dt = dateutil_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return datetime.now(UTC)


class BaseParser(ABC):
    @abstractmethod
    def parse_line(
        self,
        line: str,
        service_name: str,
        submission_id: uuid.UUID,
    ) -> LogEvent | None:
        """Parse one log line. Return None for lines that should be skipped."""


class JsonLineParser(BaseParser):
    def parse_line(
        self,
        line: str,
        service_name: str,
        submission_id: uuid.UUID,
    ) -> LogEvent | None:
        line = line.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            log.debug("json_parse_skip", reason="invalid_json")
            return None

        if not isinstance(data, dict):
            return None

        # Resolve field aliases
        timestamp_raw = (
            data.get("timestamp") or data.get("time") or data.get("ts") or data.get("@timestamp")
        )
        level_raw = data.get("level") or data.get("severity") or data.get("lvl") or "INFO"
        service_raw = (
            data.get("service") or data.get("service_name") or data.get("app") or service_name
        )
        message = data.get("message") or data.get("msg") or ""
        trace_id = data.get("trace_id") or data.get("traceId") or data.get("trace-id") or None
        span_id = data.get("span_id") or data.get("spanId") or data.get("span-id") or None
        error_type = (
            data.get("error_type") or data.get("errorType") or data.get("exception") or None
        )
        stack_trace = data.get("stack_trace") or data.get("stackTrace") or data.get("stack") or None

        # Collect unknown fields into metadata
        extra = {k: v for k, v in data.items() if k not in _KNOWN_FIELDS}

        return LogEvent(
            submission_id=submission_id,
            service_name=service_raw,
            event_timestamp=_parse_timestamp(str(timestamp_raw) if timestamp_raw else None),
            level=_normalise_level(str(level_raw)),
            message=str(message),
            trace_id=str(trace_id)[:64] if trace_id else None,
            span_id=str(span_id)[:32] if span_id else None,
            error_type=str(error_type)[:200] if error_type else None,
            stack_trace=str(stack_trace) if stack_trace else None,
            raw_line=line,
            extra_metadata=extra if extra else None,
        )


class PlaintextParser(BaseParser):
    """
    Two regex patterns covering the most common plaintext log layouts.

    Pattern 1: [TIMESTAMP] LEVEL SERVICE: MESSAGE
    Pattern 2: TIMESTAMP LEVEL MESSAGE   (two-part, no service prefix)
    """

    _PATTERNS = [
        re.compile(
            r"^\[(?P<ts>[^\]]+)\]\s+(?P<level>CRITICAL|ERROR|WARN(?:ING)?|INFO|DEBUG)\s+"
            r"(?P<svc>\S+):\s+(?P<msg>.*)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*)\s+"
            r"(?P<level>CRITICAL|ERROR|WARN(?:ING)?|INFO|DEBUG)\s+(?P<msg>.*)$",
            re.IGNORECASE,
        ),
    ]

    def parse_line(
        self,
        line: str,
        service_name: str,
        submission_id: uuid.UUID,
    ) -> LogEvent | None:
        line = line.strip()
        if not line:
            return None

        for pattern in self._PATTERNS:
            m = pattern.match(line)
            if m:
                groups = m.groupdict()
                svc = groups.get("svc") or service_name
                return LogEvent(
                    submission_id=submission_id,
                    service_name=svc,
                    event_timestamp=_parse_timestamp(groups.get("ts")),
                    level=_normalise_level(groups["level"]),
                    message=groups["msg"].strip(),
                    raw_line=line,
                )

        log.debug("plaintext_parse_skip", reason="no_pattern_match", line_prefix=line[:60])
        return None


def detect_format(first_line: str) -> type[BaseParser]:
    """Inspect the first non-empty line and return the appropriate parser class."""
    for line in first_line.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
            return JsonLineParser
        except json.JSONDecodeError:
            return PlaintextParser
    return PlaintextParser
