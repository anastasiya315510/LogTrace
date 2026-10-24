# Proposal

## Why

`IncidentView.jsx` fires exactly **one** `getIncident` fetch inside the SSE `onComplete` callback, then never fetches again. The Tavily fix-suggestions job runs **after** the RCA stream ends, so `fix_suggestions` is always empty at `onComplete` time. `cascade_chain` can also arrive a few hundred ms late. After that single fetch, neither `CascadeChain` nor `FixSuggestions` ever receives updated props — both panels show placeholder text ("No cascade data yet" / "No suggestions yet") until the user forces a browser reload.

## What Changes

- After the SSE stream's `onComplete` fires, start a **polling interval** (every 3 s) that keeps calling `getIncident` until both `cascade_chain` and `fix_suggestions` are populated, or until a 60-second cap is reached.
- Clear the polling interval on component unmount to avoid memory leaks and stale state updates.
- No changes to `CascadeChain.jsx`, `FixSuggestions.jsx`, or any backend code.

## Capabilities

### New Capabilities
<!-- None — pure bug fix, no new system behaviors -->

### Modified Capabilities
<!-- None -->

> **Note:** `skip_specs: true` is set — this is a client-side rendering bug fix with no API or contract changes.

## Impact

- `portal/src/components/IncidentView.jsx` — `useEffect` and `startStream` function only
- No API, schema, or other component changes