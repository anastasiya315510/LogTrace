---
name: superpowers
description: Activate deep multi-expert analysis mode. Runs parallel expert reviews — architecture, security, performance, code quality, and test coverage — across the entire codebase or a specified scope. Returns a consolidated findings report with prioritized action items. Use when you want a comprehensive second opinion before a major milestone.
allowed-tools: Bash, Glob, Grep, Read, Agent
---

Activate Superpowers mode: run all expert lenses simultaneously and synthesize findings into one prioritized action list.

## How to invoke

- `/superpowers` — full codebase scan
- `/superpowers api/` — scope to a directory
- `/superpowers "auth flow"` — scope to a topic

## What runs in parallel

Spawn these analyses concurrently using the Agent tool. Each targets the scope provided (or the whole project if none):

### 1. Architecture Review
- Does the module structure follow the responsibilities defined in `CLAUDE.md`?
- Are there circular imports or modules with too many responsibilities?
- Is the SOLID separation maintained (single-purpose ABCs, dependency injection via `Depends`)?
- Identify the top 3 architectural risks.

### 2. Security Scan
- Authentication bypasses or missing auth on any endpoint
- Injection vulnerabilities (SQL, command, SSRF in Tavily/OpenAI URL config)
- Secrets in code or config (beyond what `/check-secrets` catches)
- Insecure defaults or overly permissive CORS/headers

### 3. Performance Hot-Spots
- Any synchronous blocking call inside an `async def` function
- Missing `await` on async operations
- N+1 query patterns in SQLAlchemy (missing `selectinload`)
- Redis operations that could be pipelined but aren't

### 4. Code Quality & Maintainability
- Dead code (unreachable branches, unused imports after ruff)
- Functions longer than 50 lines that should be split
- Magic numbers or hardcoded constants that should be config
- Missing error handling at system boundaries (user input, external APIs)

### 5. Test Coverage Gaps
- Which modules have zero test coverage?
- Which error paths (exception handlers, fallback branches) are untested?
- Which API endpoints have no test at all?

## Synthesis

After all agents complete, synthesize findings into:

```
## Superpowers Report — <scope>

### 🔴 Critical (fix before shipping)
1. <finding> — <file:line> — <why it matters>

### 🟡 Important (fix soon)
1. ...

### 🟢 Minor (nice to have)
1. ...

### ✅ Looking good
- <things that are well done — credit where it's due>

### Summary
N critical, M important, K minor findings across <scope>.
Estimated fix time: <rough estimate>
```

Do not fix anything unless the user explicitly asks. Present findings and wait.
