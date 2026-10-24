# Design

## Context

See proposal.md — Why.

`render_incident()` in `streamlit_portal/app.py` (line 533) fetches a single incident and checks `is_live = status not in ("complete", "failed")`. The current structure is:

```
fetch incident
is_live = status not in ("complete", "failed")
...render header, metrics...
if is_live:
    sleep(3)
    st.rerun()          ← terminates script HERE
# ── Three-column panel ──   ← NEVER reached while is_live=True
render Cascade Chain
render Service Topology
render Fix Suggestions
```

`st.rerun()` raises `RerunException`, so execution never proceeds to the three-column panel while the incident is in-flight. When status becomes `"complete"` the loop stops, but cascade_chain and fix_suggestions may still be empty (pipeline writes them after setting status), leaving the user with blank sections and no further refresh.

## Goals / Non-Goals

**Goals:**
- Cascade Chain, Service Topology, and Fix Suggestions always render, even during in-flight polling
- Sections auto-populate without a manual browser reload when data arrives after status=complete
- Preserve the 3-second refresh cadence while in-flight

**Non-Goals:**
- Changing polling logic in the React portal (separate system)
- Changing the API or data model
- Altering the PDF export rendering path (uses separate `render_pdf_incident()`)

## Decisions

### Decision 1 — Move `st.rerun()` to the end of `render_incident()`

**Chosen:** Restructure `render_incident()` so all panels are rendered unconditionally, then the rerun/sleep is the last statement.

**Rationale:** The panels have no dependency on the refresh loop position. Moving the guard to the end lets Streamlit render all available data on every cycle, including partial data during analysis.

**Alternative considered:** Wrap each panel in its own `if is_live: st.rerun()` check — rejected, duplicates logic and still causes early termination.

### Decision 2 — One-shot trailing rerun after `complete`

**Chosen:** After the loop stops (status=`"complete"`), check if `cascade_chain` or `fix_suggestions` are empty. If so, sleep 2 s and call `st.rerun()` once more.

**Rationale:** Handles the race where the backend marks the incident complete before persisting cascade/fix data. One extra rerun is sufficient — if data is missing after the second complete-state render, it genuinely is not coming.

**Alternative considered:** Keep polling indefinitely until data is non-empty — rejected, could loop forever if the model produced no cascade chain.

## Risks / Trade-offs

- **Partial data flash**: Users will briefly see "No cascade data yet" / "No suggestions yet" placeholders during the in-flight phase. This is the correct placeholder text that already exists in the code.
- **One trailing rerun may be insufficient**: If the fix_suggestions pipeline is very slow, one extra rerun might not be enough. Mitigation: the user can still manually reload; this is a best-effort improvement over the current broken state.