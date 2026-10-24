# Design

## Context

See proposal.md — Why.

`IncidentView.jsx` current `startStream` → `onComplete` path:

```js
onComplete: () => {
    setIsStreaming(false)
    setProgressPct(100)
    getIncident(incidentId)          // ← single fetch, then nothing
        .then((data) => setIncident(data))
        .catch(() => {})
},
```

`cascade_chain` lives in `IncidentAnalysis.cascade_chain_json` (written during RCA).
`fix_suggestions` are separate `FixSuggestion` rows written by the Tavily job that runs **after** the RCA stream finishes. The `__DONE__` SSE message is published before Tavily completes, so the single post-stream fetch always misses fix suggestions.

Both panels receive their data as props from `IncidentView`:
- `CascadeChain` receives `cascadeChain = incident?.cascade_chain ?? []`
- `FixSuggestions` receives `fixSuggestions = incident?.fix_suggestions ?? []`

Neither panel has its own data-fetching logic — they are pure display components.

## Goals / Non-Goals

**Goals:**
- `CascadeChain` and `FixSuggestions` populate automatically after stream ends without browser reload
- Polling stops as soon as both are populated (or after 60 s)
- No memory leaks on unmount or incidentId change

**Non-Goals:**
- Polling during the live SSE stream phase (SSE already handles that)
- Changing `CascadeChain.jsx` or `FixSuggestions.jsx`
- Adding a visible loading indicator for the post-stream phase (keep UX change minimal)

## Decisions

### Decision 1 — `setInterval` inside `onComplete`, cleared by a ref

**Chosen:** Store the interval ID in a `pollRef = useRef(null)`. Start it in `onComplete`; clear it both when data arrives and in the `useEffect` cleanup.

```js
const pollRef = useRef(null)

// In onComplete:
pollRef.current = setInterval(async () => {
    try {
        const data = await getIncident(incidentId)
        setIncident(data)
        const hasCascade = data.cascade_chain?.length > 0
        const hasFixes   = data.fix_suggestions?.length > 0
        if (hasCascade && hasFixes) {
            clearInterval(pollRef.current)
            pollRef.current = null
        }
    } catch {}
}, 3000)

// Safety cap — stop after 60 s regardless
setTimeout(() => {
    if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
    }
}, 60_000)

// In useEffect cleanup:
if (pollRef.current) {
    clearInterval(pollRef.current)
    pollRef.current = null
}
```

**Rationale:** Same pattern already used for `esRef` (SSE EventSource). A ref avoids stale closure issues with state. Clearing on unmount prevents state updates on an unmounted component.

**Alternative considered:** `useEffect` with a `[incident]` dependency that re-triggers when data changes — rejected, introduces re-render cycles and harder to cap.

### Decision 2 — 3-second poll, 60-second hard cap

**Chosen:** 3 s interval matches the existing Dashboard polling cadence. 60 s cap covers the slowest observed Tavily responses with margin.

**Alternative considered:** Poll forever until data arrives — rejected, Tavily can genuinely return zero results, causing an infinite loop.

## Risks / Trade-offs

- **Extra API calls:** Up to ~20 extra `GET /api/v1/incidents/{id}` calls per incident view (one every 3 s for 60 s). Negligible in a demo context.
- **Stale closure:** `incidentId` is captured in the `onComplete` closure. If `incidentId` prop changes while polling is active, the old interval would fetch the wrong incident. Mitigation: the `useEffect` cleanup clears the interval on `incidentId` change (it already cleans up `esRef`).