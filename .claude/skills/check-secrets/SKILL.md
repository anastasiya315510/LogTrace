---
name: check-secrets
description: Scan the project for credential leaks — hardcoded secrets, passwords, API keys, or tokens in tracked files. Checks .gitignore coverage, docker-compose files, YAML/env configs, and any recently staged files. Reports findings with file:line references and suggests fixes.
allowed-tools: Bash, Glob, Grep, Read
---

Scan the project for potential credential leaks before pushing to a public repository.

## What to check

Run all checks from the project root. Report each finding with `file:line` and the exact matching text (redact the actual secret value — show only the pattern that matched).

### 1. `.gitignore` coverage
- Verify `.env` is listed in `.gitignore`. Fail if absent.
- Verify `.env.local`, `.env.*.local` are listed or covered by a wildcard.
- Report any other files present on disk that look like they contain secrets but are NOT in `.gitignore` (e.g. `*.pem`, `*.key`, `credentials.json`, `secrets.yaml`).

### 2. Hardcoded secrets in tracked files
Search all files tracked by git (or all non-ignored files if not a git repo) for patterns that suggest hardcoded credentials:

- Passwords in connection strings: `://[^:]+:[^@]{4,}@` (matches `user:password@host`)
- Bare API key assignments: `(api_key|apikey|api-key|secret|token|password)\s*[:=]\s*["'][^${\s"']{8,}` (case-insensitive, excludes `${...}` substitution and placeholder text)
- AWS/Nebius-style key patterns: `[A-Z0-9]{20}` or long hex/base64 strings assigned to a key variable
- Private key headers: `-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----`

Skip:
- Files matched by `.gitignore`
- `*.md` documentation files (unless they contain `BEGIN PRIVATE KEY`)
- Test fixtures that use obviously fake values (e.g. `test-key`, `fake-secret`, `stubhash`)
- Template placeholders like `your-key-here`, `<your_key>`, `${VAR}`

### 3. Docker Compose / YAML environment blocks
Inspect all `docker-compose*.yml` files for environment values that are literal strings rather than `${VAR}` references:
- Passwords in `DATABASE_URL:` or `REDIS_URL:` values that are not `${...}`
- Any `*_KEY`, `*_SECRET`, `*_PASSWORD`, `*_TOKEN` set to a non-`${...}` value

### 4. Staged files (pre-push check)
If inside a git repo, run `git diff --cached --name-only` and apply checks 2–3 to staged files specifically. Flag any staged file that introduces a new credential pattern.

### 5. `.env` file present?
If `.env` exists on disk, confirm it is excluded from git tracking (`git check-ignore .env`). Do NOT read or display any content from `.env`.

## Output format

```
## Secret Scan Results

### ✅ Passed
- .env is in .gitignore
- No private key headers found
- ...

### ⚠️ Warnings (review these)
- docker-compose.yml:38  DATABASE_URL contains hardcoded password
  → Move to .env: DATABASE_URL=postgresql+asyncpg://user:${DB_PASS}@host/db

### ❌ Failed (fix before pushing)
- api/config.py:12  api_key = "sk-abc..."
  → Replace with: api_key = os.environ["API_KEY"]

### Summary
N issues found (X failed, Y warnings).
Safe to push: YES / NO
```

If no issues are found, print a brief "All clear — no credential leaks detected" message.

## After reporting

- Do NOT automatically fix issues. Report findings and wait for the user to confirm before editing any file.
- If the user says "fix it", apply the minimal change: replace the hardcoded value with a `${VAR}` reference in config files, or `os.environ["VAR"]` in Python code, and add the variable to `.env.example` with a placeholder value.
