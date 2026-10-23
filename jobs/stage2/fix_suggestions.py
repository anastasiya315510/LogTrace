"""
jobs/stage2/fix_suggestions.py

Fetch fix suggestions from Tavily for a completed incident.

- Two queries: remediation guide + known vulnerabilities/CVEs
- Dedup by URL, sort by tavily_score DESC, return top 3
- Both-fail path returns [] gracefully — incident is delivered without suggestions
"""

import asyncio
import uuid

import structlog

from db.models import FixSuggestion, IncidentAnalysis

log = structlog.get_logger()

_MAX_RESULTS_PER_QUERY = 5
_TOP_N = 3


async def fetch_fix_suggestions(
    analysis: IncidentAnalysis,
    incident_id: uuid.UUID,
    tavily_api_key: str,
) -> list[FixSuggestion]:
    """
    Issue two Tavily queries (remediation + vulnerability) and return up to 3
    deduplicated FixSuggestion rows sorted by score descending.
    Returns [] if both queries fail.
    """
    from tavily import TavilyClient  # type: ignore[import]

    client = TavilyClient(api_key=tavily_api_key)

    service = analysis.root_cause_service or "microservice"
    error_cat = _infer_error_category(analysis)

    q_remediation = f"{service} {error_cat} fix solution"
    q_vulnerability = f"{error_cat} CVE known bug {service}"

    results = await asyncio.gather(
        asyncio.to_thread(client.search, q_remediation, max_results=_MAX_RESULTS_PER_QUERY),
        asyncio.to_thread(client.search, q_vulnerability, max_results=_MAX_RESULTS_PER_QUERY),
        return_exceptions=True,
    )

    suggestions: list[FixSuggestion] = []
    seen_urls: set[str] = set()

    query_types = ["remediation", "vulnerability"]
    queries = [q_remediation, q_vulnerability]

    for result, query_type, query in zip(results, query_types, queries, strict=False):
        if isinstance(result, Exception):
            log.warning("tavily_query_failed", query_type=query_type, error=str(result))
            continue
        for item in result.get("results", []):
            url = item.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            suggestions.append(
                FixSuggestion(
                    incident_id=incident_id,
                    search_query=query,
                    source_url=url,
                    source_title=item.get("title", url)[:300],
                    excerpt=(item.get("content") or item.get("snippet") or "")[:1000],
                    tavily_score=float(item.get("score", 0.0)),
                    query_type=query_type,
                )
            )

    # Sort by score and take top N
    suggestions.sort(key=lambda s: s.tavily_score, reverse=True)
    return suggestions[:_TOP_N]


def _infer_error_category(analysis: IncidentAnalysis) -> str:
    """Derive a search-friendly error category from the analysis."""
    if analysis.cascade_chain_json:
        chain = analysis.cascade_chain_json
        if isinstance(chain, list) and chain:
            error = chain[0].get("error", "")
            if error:
                return error[:80]
    return "service failure"
