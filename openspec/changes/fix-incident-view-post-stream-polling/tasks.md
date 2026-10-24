# Tasks

## 1. Add post-stream polling to IncidentView

- [x] 1.1 In `portal/src/components/IncidentView.jsx`, add `const pollRef = useRef(null)` alongside the existing `esRef` ref (line ~42). Verify the ref is declared inside the component function.

- [x] 1.2 In the `useEffect` cleanup (line ~72), add cleanup for `pollRef`:
  ```js
  if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
  }
  ```
  Verify both `esRef` and `pollRef` are cleaned up in the same cleanup function.

- [x] 1.3 Replace the single `getIncident` call inside `onComplete` (line ~103) with a polling interval:
  ```js
  onComplete: () => {
      setIsStreaming(false)
      setProgressPct(100)
      // Start polling for cascade_chain and fix_suggestions (arrive after stream ends)
      pollRef.current = setInterval(async () => {
          try {
              const data = await getIncident(incidentId)
              setIncident(data)
              if (data.cascade_chain?.length > 0 && data.fix_suggestions?.length > 0) {
                  clearInterval(pollRef.current)
                  pollRef.current = null
              }
          } catch {}
      }, 3000)
      // Hard cap: stop polling after 60 s regardless
      setTimeout(() => {
          if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
          }
      }, 60_000)
  },
  ```
  Verify no standalone `getIncident` call remains in `onComplete`.

## 2. Verify

- [ ] 2.1 Run `npm run dev` in `portal/` and open a demo incident that is still in-flight. Confirm that after the RCA stream finishes, Cascade Chain and Fix Suggestions populate automatically within ~10–15 s without a browser reload.

- [ ] 2.2 Navigate away from the incident and back while polling is active. Confirm the browser console shows no "Can't perform a React state update on an unmounted component" warnings (cleanup is working).


## Workflow follow-up

- Archive this change after verification.