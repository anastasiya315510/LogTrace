"""
jobs/stage2/classifier.py

Batch-classify LogEvents using Nemotron Nano 8B.

- build_nano_prompt()    — render the nano_classify.prompt template for a batch
- parse_nano_response()  — parse Nano JSON; mark all as noise/unknown on failure
- batch_classify()       — semaphore-bounded asyncio.gather over all batches
"""

import asyncio
import json
from pathlib import Path

import structlog

from db.models import EventClassification, LogEvent

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "nano_classify.prompt"


def _load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def build_nano_prompt(batch: list[LogEvent]) -> str:
    """Render the classification prompt for a batch of events."""
    template = _load_prompt_template()
    events_payload = json.dumps(
        [
            {
                "event_index": i,
                "service": e.service_name,
                "level": e.level,
                "message": e.message,
                "error_type": e.error_type,
                "stack_trace": e.stack_trace,
            }
            for i, e in enumerate(batch)
        ],
        indent=2,
    )
    prompt = template.replace("{{EVENTS_JSON}}", events_payload)
    prompt = prompt.replace("{{BATCH_SIZE}}", str(len(batch)))
    return prompt


def parse_nano_response(
    content: str,
    batch: list[LogEvent],
) -> list[EventClassification]:
    """
    Parse Nano's JSON array response.

    On any failure (malformed JSON, wrong array length, missing fields):
    mark all events as noise/unknown with anomaly_score=0.0 — never raise.
    """
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
        if len(data) != len(batch):
            log.warning(
                "nano_response_length_mismatch",
                expected=len(batch),
                got=len(data),
            )
            raise ValueError("Array length mismatch")

        classifications = []
        for item, event in zip(data, batch, strict=False):
            classifications.append(
                EventClassification(
                    event_id=event.event_id,
                    anomaly_score=float(item.get("anomaly_score", 0.0)),
                    event_role=str(item.get("event_role", "noise")),
                    error_category=str(item.get("error_category", "unknown")),
                )
            )
        return classifications

    except Exception as exc:
        log.warning("nano_parse_fallback", error=str(exc), batch_size=len(batch))
        return [
            EventClassification(
                event_id=e.event_id,
                anomaly_score=0.0,
                event_role="noise",
                error_category="unknown",
            )
            for e in batch
        ]


async def batch_classify(
    events: list[LogEvent],
    client,  # openai.AsyncOpenAI
    model_id: str,
    batch_size: int = 20,
    parallel: int = 10,
) -> list[EventClassification]:
    """
    Classify all events in semaphore-bounded parallel batches.

    Returns one EventClassification per LogEvent in the same order.
    """
    batches = [events[i : i + batch_size] for i in range(0, len(events), batch_size)]
    semaphore = asyncio.Semaphore(parallel)

    async def classify_one_batch(batch: list[LogEvent]) -> list[EventClassification]:
        async with semaphore:
            prompt = build_nano_prompt(batch)
            try:
                response = await client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                content = response.choices[0].message.content or "[]"
            except Exception as exc:
                log.warning("nano_api_error", error=str(exc), batch_size=len(batch))
                content = "[]"

            return parse_nano_response(content, batch)

    results = await asyncio.gather(*[classify_one_batch(b) for b in batches])
    return [c for batch_result in results for c in batch_result]
