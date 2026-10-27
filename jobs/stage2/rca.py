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
# Fallback: opening tag present but closing tag missing (truncated response)
_ANALYSIS_JSON_OPEN_RE = re.compile(r"<ANALYSIS_JSON>\s*(\{.*)", re.DOTALL)


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


def _extract_bare_json(text: str) -> str | None:
    """
    Find the outermost balanced JSON object in *text*.
    Returns the raw JSON string, or None if not found.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


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

    log.info(
        "ultra_response_parse_start",
        incident_id=str(incident_id),
        response_len=len(full_text),
        has_analysis_json_tag="<ANALYSIS_JSON>" in full_text,
        regex_matched=bool(match),
    )

    if match:
        # JSON-first format: explanation is the prose AFTER the closing tag.
        # Fall back to text before the block for legacy responses.
        after = full_text[match.end() :].strip()
        before = full_text[: match.start()].strip()
        cascade_explanation = after if after else before
        try:
            data = json.loads(match.group(1))
            root_cause_service = data.get("root_cause_service")
            root_cause_method = data.get("root_cause_method")
            raw_score = data.get("confidence_score")
            if raw_score is not None:
                confidence_score = float(raw_score)
                # Normalize: model sometimes outputs 0-100 instead of 0.0-1.0
                if confidence_score > 1.0:
                    confidence_score = confidence_score / 100.0
            raw_chain = data.get("cascade_chain")
            # Ensure cascade_chain is a list; model may wrap it in a dict
            cascade_chain_json = raw_chain if isinstance(raw_chain, list) else None
            alternative_hypotheses_json = data.get("alternative_hypotheses")
            log.info(
                "ultra_json_parsed",
                incident_id=str(incident_id),
                root_cause_service=root_cause_service,
                confidence_score=confidence_score,
                cascade_chain_len=len(cascade_chain_json)
                if isinstance(cascade_chain_json, list)
                else cascade_chain_json,
                has_hypotheses=bool(alternative_hypotheses_json),
            )
        except Exception as exc:
            log.warning(
                "ultra_json_parse_failed",
                error=str(exc),
                matched_text_preview=match.group(1)[:200],
            )
    else:
        # Fallback: try truncated block (opening tag present, closing tag missing)
        open_match = _ANALYSIS_JSON_OPEN_RE.search(full_text)
        if open_match:
            # With JSON-first: no text before the opening tag normally;
            # store full text so the prose narrative is still visible.
            cascade_explanation = full_text[: open_match.start()].strip() or full_text
            partial = open_match.group(1)
            # Try to parse as-is first, then progressively trim trailing garbage
            parsed_partial = False
            for attempt in (partial, partial.rstrip() + "}"):
                try:
                    data = json.loads(attempt)
                    root_cause_service = data.get("root_cause_service")
                    root_cause_method = data.get("root_cause_method")
                    raw_score = data.get("confidence_score")
                    if raw_score is not None:
                        confidence_score = float(raw_score)
                        if confidence_score > 1.0:
                            confidence_score = confidence_score / 100.0
                    raw_chain = data.get("cascade_chain")
                    cascade_chain_json = raw_chain if isinstance(raw_chain, list) else None
                    alternative_hypotheses_json = data.get("alternative_hypotheses")
                    parsed_partial = True
                    log.info(
                        "ultra_json_partial_parsed",
                        incident_id=str(incident_id),
                        root_cause_service=root_cause_service,
                    )
                    break
                except Exception:
                    pass
            if not parsed_partial:
                # Last resort: regex-extract individual scalar fields
                for field, pat in [
                    ("root_cause_service", r'"root_cause_service"\s*:\s*"([^"]+)"'),
                    ("root_cause_method", r'"root_cause_method"\s*:\s*"([^"]+)"'),
                    ("confidence_score", r'"confidence_score"\s*:\s*([0-9.]+)'),
                ]:
                    m = re.search(pat, partial)
                    if m:
                        val = m.group(1)
                        if field == "confidence_score":
                            try:
                                confidence_score = float(val)
                                if confidence_score > 1.0:
                                    confidence_score /= 100.0
                            except ValueError:
                                pass
                        elif field == "root_cause_service":
                            root_cause_service = val
                        elif field == "root_cause_method":
                            root_cause_method = val
                log.warning(
                    "ultra_json_truncated_scalar_extract",
                    incident_id=str(incident_id),
                    root_cause_service=root_cause_service,
                    confidence_score=confidence_score,
                )
        else:
            # Last resort: model didn't use tags at all — extract the outermost JSON
            # object from the response (model outputs the data, just without the wrapper)
            bare_json_candidate = _extract_bare_json(full_text)
            if bare_json_candidate and "root_cause_service" in bare_json_candidate:
                try:
                    data = json.loads(bare_json_candidate)
                    root_cause_service = data.get("root_cause_service")
                    root_cause_method = data.get("root_cause_method")
                    raw_score = data.get("confidence_score")
                    if raw_score is not None:
                        confidence_score = float(raw_score)
                        if confidence_score > 1.0:
                            confidence_score /= 100.0
                    raw_chain = data.get("cascade_chain")
                    cascade_chain_json = raw_chain if isinstance(raw_chain, list) else None
                    alternative_hypotheses_json = data.get("alternative_hypotheses")
                    log.info(
                        "ultra_json_bare_parsed",
                        incident_id=str(incident_id),
                        root_cause_service=root_cause_service,
                        cascade_chain_len=len(cascade_chain_json)
                        if isinstance(cascade_chain_json, list)
                        else None,
                    )
                except Exception as exc:
                    log.warning(
                        "ultra_json_bare_parse_failed", incident_id=str(incident_id), error=str(exc)
                    )
                    log.warning(
                        "ultra_analysis_json_missing",
                        incident_id=str(incident_id),
                        response_tail=full_text[-500:] if len(full_text) > 500 else full_text,
                    )
            else:
                log.warning(
                    "ultra_analysis_json_missing",
                    incident_id=str(incident_id),
                    response_tail=full_text[-500:] if len(full_text) > 500 else full_text,
                )

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
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert SRE performing root cause analysis. "
                        "Your response MUST begin with a <ANALYSIS_JSON> block containing "
                        "a single JSON object with keys: root_cause_service, root_cause_method, "
                        "confidence_score (0.0-1.0), cascade_chain (array), alternative_hypotheses (array). "
                        'Example: <ANALYSIS_JSON>{"root_cause_service": "...", ...}</ANALYSIS_JSON>\n'
                        "Output the JSON block FIRST, before any prose explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
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
