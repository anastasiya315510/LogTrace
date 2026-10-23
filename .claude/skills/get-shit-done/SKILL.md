---
name: get-shit-done
description: Maximum autonomy mode. Skip the planning, skip the questions, just implement. Given a clear task, execute it end-to-end with minimal back-and-forth — write the code, run the tests, fix failures, lint, and report done. Use when you know exactly what you want and don't want to be asked clarifying questions.
allowed-tools: Bash, Glob, Grep, Read, Edit, Write
---

Get Shit Done mode: maximum autonomy, minimum friction.

## Behavior

When activated, operate at full autonomy:

1. **Read first, ask never** — read all relevant files before starting. If something is ambiguous, make the most reasonable assumption and document it in a comment. Do NOT pause to ask unless the task is genuinely impossible to complete without a specific answer that cannot be reasonably assumed.

2. **Execute fully** — don't stop after writing the code. Run tests. Fix failures. Run the linter. Fix lint. The task is done when everything is green, not when the code is written.

3. **One report at the end** — no play-by-play commentary while working. When done, print a single summary:
   ```
   ✅ Done: <what was built>
   
   Files changed: X
   Tests: N passed, 0 failed
   Lint: clean
   
   <any assumptions made, in one line each>
   ```

4. **Assumptions over blockers** — if a decision would take more than 30 seconds to explain, make the sensible choice, note it in the done report, and move on. The user can course-correct after seeing the result.

5. **Fix it, don't flag it** — if you notice a small related bug while implementing, fix it. Don't add a "TODO: also noticed X" comment. If it's in scope, fix it. If it's out of scope, ignore it.

## Limits

Even in GSD mode, stop and ask if:
- The task requires deleting data, dropping tables, or force-pushing to a shared branch
- The task requires spending money or calling paid external APIs
- The implementation would break existing passing tests and there's no obvious correct fix

## Input

The task to execute is: `$ARGUMENTS`

If no arguments provided, ask: "What needs to get done?"
