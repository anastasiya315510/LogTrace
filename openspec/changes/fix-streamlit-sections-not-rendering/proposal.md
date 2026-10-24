# Proposal

## Why

In the Streamlit portal's `render_incident()` function, `st.rerun()` is called inside an `if is_live:` guard that terminates script execution **before** reaching the Cascade Chain, Service Topology, and Fix Suggestions panels. When the backend transitions status to `"complete"`, the auto-refresh loop stops — but cascade_chain and fix_suggestions may still be empty at that moment due to a pipeline race condition. With no further reruns, the empty sections persist until the user manually reloads the browser.

## What Changes

- Move the `if is_live: st.rerun()` guard in `render_incident()` to **after** the three-column panel is rendered, not before it.
- After the loop stops (status = `"complete"`), add a one-shot trailing rerun if cascade_chain or fix_suggestions are still empty, to pick up any data that arrived after status was set.
- This ensures Cascade Chain and Fix Suggestions always appear automatically without a manual browser reload.

## Capabilities

### New Capabilities
<!-- None — this is a pure bug fix restoring intended rendering behavior -->

### Modified Capabilities
<!-- None — no spec-level requirement changes -->

> **Note**: `skip_specs: true` is set in `.openspec.yaml` — this change fixes a rendering defect with no new system behaviors or API contract changes.

## Impact

- `streamlit_portal/app.py` — `render_incident()` function only (~lines 592–670)
- No API, schema, or dependency changes