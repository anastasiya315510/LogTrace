---
name: safe-side-effects
description: Dry-run mode — preview every side effect before it happens. Shows exactly what files would be written, what commands would run, what API calls would be made, and what DB changes would occur, without executing any of them. Use before a risky operation to review the full impact. Pairs with /get-shit-done — plan with /safe-side-effects, execute with /get-shit-done.
allowed-tools: Bash(git status), Bash(git diff), Bash(ls), Bash(find), Glob, Grep, Read
disable-model-invocation: true
---

Dry-run mode: show every side effect without executing any of them.

## Behavior

Analyze the task in `$ARGUMENTS` and produce a complete preview of what would happen if it were executed — with NO writes, NO command execution (beyond read-only commands like `ls`, `git status`, `git diff`), and NO external API calls.

## Output format

```
## Dry-Run Preview: <task description>

### Files that would be CREATED
- `path/to/new/file.py` — <what it contains>

### Files that would be MODIFIED
- `api/dependencies.py:24` — add `require_api_key_sse` function
  Before: async def require_api_key(...)
  After:  + async def require_api_key_sse(...) [new function below existing one]

### Files that would be DELETED
- (none)

### Commands that would run
1. `pytest tests/unit/ -v`  — verify tests pass after changes
2. `ruff check . --fix`     — auto-fix lint issues
3. `alembic upgrade head`   — apply DB migrations (if any)

### External API calls
- (none) / Nebius Token Factory: 1 call to verify model availability

### Database changes
- (none) / ALTER TABLE: add column `foo` to `incidents`

### Git changes
- 3 files staged, 0 deleted
- Suggested commit message: "fix: SSE auth query param support"

### Risks
- `alembic upgrade head` is irreversible on a live DB without a rollback migration
- Modifying `api/dependencies.py` affects all 12 endpoints that import `require_api_key`

### Summary
Safe to proceed: YES / REVIEW RISKS ABOVE
```

## Rules

- Do NOT write any files.
- Do NOT run any destructive commands.
- Read-only commands allowed: `ls`, `find`, `cat` (via Read), `grep` (via Grep), `git status`, `git diff`, `git log`.
- If the task cannot be fully analyzed without executing something, describe what you would need to run and why, but do not run it.
- If `$ARGUMENTS` is empty, ask: "What operation do you want to preview?"
