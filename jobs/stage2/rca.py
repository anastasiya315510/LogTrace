"""
jobs/stage2/rca.py

Root cause analysis using Nemotron Ultra 253B.

- build_ultra_prompt()   — render the ultra_rca.prompt template
- parse_ultra_response() — extract structured ANALYSIS_JSON; fallback to full text
- stream_rca()           — stream tokens via Redis pub/sub while Ultra generates
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

from db.models import EventClassification, Incident, IncidentAnalysis, LogEvent

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "ultra_rca.prompt"
_ANALYSIS_JSON_RE = re.compile(
    r"<ANALYSIS_JSON>\s*(\{.*?\})\s*</ANALYSIS_JSON>",
    re.DOTALL,
)


def _load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def build_ultra_prompt(
    incident: Incident,
    events: list[LogEvent],
    classifications: list[EventClassification],
) -> str:
    template = _load_prompt_template()

    services = incident.services_involved
    if isinstance(services, dict):
        services = services.get("services", [])
    services_str = ", ".join(services) if isinstance(services, list) else str(services)

    topology_str = json.dumps(incident.service_topology_json or {}, indent=2)

    # Build classified event summary (errors/anomalies only)
    cls_map = {c.event_id: c for c in classifications}
    classified_lines = []
    for e in sorted(events, key=lambda x: x.event_timestamp):
        cls = cls_map.get(e.event_id)
        if cls and cls.event_role in ("root_candidate", "propagated_error", "symptom"):
            classified_lines.append(
                f"{e.service_name} | {e.event_timestamp.isoformat()} | {e.level} | "
                f"{e.error_type or '-'} | {e.message[:120]} | "
                f"{cls.event_role} | {cls.error_category} | {cls.anomaly_score:.2f}"
            )
    classified_str = "\n".join(classified_lines) if classified_lines else "(none)"

    # Full event log (chronological, capped at 200 events to fit context)
    all_lines = []
    for e in sorted(events, key=lambda x: x.event_timestamp)[:200]:
        all_lines.append(
            f"{e.event_timestamp.isoformat()} [{e.level}] {e.service_name}: {e.message[:120]}"
        )
    full_events_str = "\n".join(all_lines)

    first_ts = (
        incident.first_event_timestamp.isoformat() if incident.first_event_timestamp else "unknown"
    )
    last_ts = (
        incident.last_event_timestamp.isoformat() if incident.last_event_timestamp else "unknown"
    )

    return (
        template.replace("{{INCIDENT_ID}}", str(incident.incident_id))
        .replace("{{SUBMISSION_ID}}", str(incident.submission_id))
        .replace("{{CORRELATION_STRATEGY}}", incident.correlation_strategy)
        .replace("{{SERVICES_INVOLVED}}", services_str)
        .replace("{{FIRST_EVENT_TIMESTAMP}}", first_ts)
        .replace("{{LAST_EVENT_TIMESTAMP}}", last_ts)
        .replace("{{EVENT_COUNT}}", str(incident.event_count))
        .replace("{{TOPOLOGY_JSON}}", topology_str)
        .replace("{{CLASSIFIED_EVENTS}}", classified_str)
        .replace("{{FULL_EVENTS}}", full_events_str)
    )


def parse_ultra_response(
    full_text: str, incident_id: uuid.UUID, model_used: str
) -> IncidentAnalysis:
    """
    Extract the structured <ANALYSIS_JSON> block from Ultra's response.
    If absent or malformed, store full text as cascade_explanation with NULL
    structured fields — the incident is still delivered.
    """
    match = _ANALYSIS_JSON_RE.search(full_text)
    cascade_explanation = full_text
    root_cause_service = None
    root_cause_method = None
    confidence_score = None
    cascade_chain_json = None
    alternative_hypotheses_json = None

    if match:
        cascade_explanation = full_text[: match.start()].strip()
        try:
            data = json.loads(match.group(1))
            root_cause_service = data.get("root_cause_service")
            root_cause_method = data.get("root_cause_method")
            raw_score = data.get("confidence_score")
            if raw_score is not None:
                confidence_score = float(raw_score)
            cascade_chain_json = data.get("cascade_chain")
            alternative_hypotheses_json = data.get("alternative_hypotheses")
        except Exception as exc:
            log.warning("ultra_json_parse_failed", error=str(exc))

    return IncidentAnalysis(
        incident_id=incident_id,
        root_cause_service=root_cause_service,
        root_cause_method=root_cause_method,
        confidence_score=confidence_score,
        cascade_explanation=cascade_explanation,
        cascade_chain_json=cascade_chain_json,
        alternative_hypotheses_json=alternative_hypotheses_json,
        model_used=model_used,
    )


async def stream_rca(
    incident: Incident,
    events: list[LogEvent],
    classifications: list[EventClassification],
    client,  # openai.AsyncOpenAI
    model_id: str,
    progress_callback: Callable[[str], Awaitable[None]],
) -> IncidentAnalysis:
    """
    Stream Ultra 253B token by token; forward each token via progress_callback.
    Returns the parsed IncidentAnalysis.
    """
    prompt = build_ultra_prompt(incident, events, classifications)
    full_text = ""

    try:
        stream = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=0.3,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            full_text += token
            if token:
                await progress_callback(token)
    except Exception as exc:
        log.error("ultra_stream_error", error=str(exc))
        full_text = full_text or f"[RCA failed: {exc}]"

    return parse_ultra_response(full_text, incident.incident_id, model_id)
