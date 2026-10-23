import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import require_api_key
from api.models.schemas import ChatRequest, FixSuggestionOut, IncidentReportResponse
from core.config import get_settings
from core.database import get_db
from db.models import ApiKey, Incident, IncidentAnalysis

log = structlog.get_logger()
router = APIRouter()


@router.get("/incidents/{incident_id}", response_model=IncidentReportResponse)
async def get_incident_report(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> IncidentReportResponse:
    result = await db.execute(
        select(Incident)
        .where(Incident.incident_id == incident_id)
        .options(
            selectinload(Incident.analysis),
            selectinload(Incident.fix_suggestions),
        )
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    analysis = incident.analysis
    suggestions = sorted(
        incident.fix_suggestions,
        key=lambda s: s.tavily_score,
        reverse=True,
    )

    services = incident.services_involved
    if isinstance(services, dict):
        services = list(services.get("services", []))

    return IncidentReportResponse(
        incident_id=incident.incident_id,
        status=incident.status,
        services_involved=services,
        service_topology=incident.service_topology_json,
        root_cause_service=analysis.root_cause_service if analysis else None,
        root_cause_method=analysis.root_cause_method if analysis else None,
        confidence_score=analysis.confidence_score if analysis else None,
        cascade_explanation=analysis.cascade_explanation if analysis else None,
        cascade_chain=analysis.cascade_chain_json if analysis else None,
        alternative_hypotheses=analysis.alternative_hypotheses_json if analysis else None,
        fix_suggestions=[
            FixSuggestionOut(
                source_title=s.source_title,
                source_url=s.source_url,
                excerpt=s.excerpt,
                tavily_score=s.tavily_score,
                query_type=s.query_type,
            )
            for s in suggestions
        ],
    )


@router.post("/incidents/{incident_id}/chat")
async def chat(
    incident_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> StreamingResponse:
    """
    Stream a Q&A response backed by Nemotron Ultra 253B.
    Requires the incident to be in `complete` status.
    Conversation history is capped at qa_max_turns turns.
    """
    settings = get_settings()

    result = await db.execute(
        select(Incident)
        .where(Incident.incident_id == incident_id)
        .options(selectinload(Incident.analysis))
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != "complete":
        raise HTTPException(status_code=400, detail="Incident analysis is not yet complete")

    analysis = incident.analysis
    if analysis is None:
        raise HTTPException(status_code=400, detail="No analysis found for this incident")

    history: list[dict] = analysis.conversation_history_json or []

    system_msg = {
        "role": "system",
        "content": (
            f"You are an SRE assistant analysing incident {incident_id}. "
            f"Root cause: {analysis.root_cause_service or 'unknown'}. "
            f"Confidence: {analysis.confidence_score or 'unknown'}. "
            "Answer questions concisely using the incident context."
        ),
    }
    messages = [system_msg] + history + [{"role": "user", "content": body.question}]

    client = AsyncOpenAI(
        api_key=settings.nebius_api_key,
        base_url=settings.nebius_base_url,
    )

    async def token_stream():
        full_answer = ""
        try:
            stream = await client.chat.completions.create(
                model=settings.ultra_model_id,
                messages=messages,
                stream=True,
                temperature=0.3,
            )
            async for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                full_answer += token
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as exc:
            log.error("chat_stream_error", error=str(exc))
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        # Persist history capped at max_turns * 2 messages
        updated_history = history + [
            {"role": "user", "content": body.question},
            {"role": "assistant", "content": full_answer},
        ]
        max_messages = settings.qa_max_turns * 2
        updated_history = updated_history[-max_messages:]

        async with db.begin_nested():
            await db.execute(
                update(IncidentAnalysis)
                .where(IncidentAnalysis.incident_id == incident_id)
                .values(conversation_history_json=updated_history)
            )
        await db.commit()

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(token_stream(), media_type="text/event-stream")


@router.get("/incidents/{incident_id}/export")
async def export_report(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> StreamingResponse:
    """
    Download a Markdown incident report.
    Includes root cause, confidence, cascade chain, analysis text, and fix suggestions.
    """
    result = await db.execute(
        select(Incident)
        .where(Incident.incident_id == incident_id)
        .options(
            selectinload(Incident.analysis),
            selectinload(Incident.fix_suggestions),
        )
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    analysis = incident.analysis
    suggestions = sorted(
        incident.fix_suggestions or [],
        key=lambda s: s.tavily_score,
        reverse=True,
    )

    services = incident.services_involved
    if isinstance(services, dict):
        services = services.get("services", [])

    lines = [
        f"# NemoTrace Incident Report — {incident_id}",
        "",
        f"**Status:** {incident.status}",
        f"**Services Involved:** {', '.join(services)}",
    ]

    if analysis:
        conf = f"{analysis.confidence_score * 100:.0f}%" if analysis.confidence_score else "N/A"
        lines += [
            f"**Root Cause:** {analysis.root_cause_service or 'unknown'}"
            + (f" / {analysis.root_cause_method}" if analysis.root_cause_method else ""),
            f"**Confidence:** {conf}",
            "",
            "## Cascade Timeline",
        ]
        chain = analysis.cascade_chain_json
        if chain and isinstance(chain, list):
            for step in chain:
                lines.append(
                    f"{step.get('step', '?')}. **{step.get('service', '?')}** — "
                    f"{step.get('error', '')} *(t={step.get('timestamp', '')})*"
                )
        else:
            lines.append("*(not available)*")

        lines += [
            "",
            "## Analysis (Nemotron Ultra 253B via Nebius Token Factory)",
            "",
            analysis.cascade_explanation or "*(not available)*",
        ]

    if suggestions:
        lines += ["", "## Fix Suggestions (Tavily)", ""]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. **[{s.source_title}]({s.source_url})**")
            lines.append(f"   > {s.excerpt[:200]}")
            lines.append(f"   *Score: {s.tavily_score:.2f} | Type: {s.query_type}*")
            lines.append("")

    content = "\n".join(lines)

    return StreamingResponse(
        iter([content]),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="incident-{incident_id}.md"',
        },
    )
