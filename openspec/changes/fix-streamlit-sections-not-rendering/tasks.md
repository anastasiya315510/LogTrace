# Tasks

## 1. Fix render_incident() polling structure

- [x] 1.1 In `render_incident()` (`streamlit_portal/app.py` ~line 592), remove the `if is_live: sleep(3); st.rerun()` block that sits **before** the three-column panel. Verify the block is gone and no `st.rerun()` call precedes the `# ── Three-column panel ──` comment.

- [x] 1.2 After the three-column panel and any other sections have been rendered, add the refresh logic at the bottom of `render_incident()`:
  ```python
  # Auto-refresh while analysis is in-flight
  if is_live:
      time.sleep(3)
      st.rerun()
  # One-shot trailing refresh: catch cascade/fix data that arrives after status=complete
  elif status == "complete" and not (cascade and fixes):
      time.sleep(2)
      st.rerun()
  ```
  Verify: the `if is_live` block is the last substantive code in `render_incident()`, after all panel rendering.

## 2. Verify end-to-end behaviour

- [ ] 2.1 Run the Streamlit portal (`streamlit run streamlit_portal/app.py`) and trigger a demo incident. Confirm that during analysis the Cascade Chain and Fix Suggestions placeholders ("No cascade data yet", "No suggestions yet") are **visible** (not hidden) while the page auto-refreshes every 3 seconds.

- [ ] 2.2 After the incident reaches `complete`, confirm that Cascade Chain steps and Fix Suggestion cards appear **automatically** without a manual browser reload.


## Workflow follow-up

- Archive the change once the fix is confirmed working end-to-end.