---
name: hackathon-checklist
description: Run the full LogTrace hackathon submission readiness checklist. Verifies every requirement from the NVIDIA × Nebius hackathon rules — code quality, credentials, README, LICENSE, deployment config, demo URL readiness, and submission artifacts. Prints a stamped pass/fail report. Use before pushing to GitHub or submitting.
allowed-tools: Bash, Glob, Grep, Read
---

Run the complete hackathon submission readiness checklist for LogTrace.

Check every submission requirement and print a final stamped report. Do not fix anything — only report. If the user says "fix it" after seeing the report, fix the specific failing items.

## Checklist

Run each check and collect results. At the end print the full report.

### Track & Requirements

- [ ] **Track identified**: Confirm `HLD.md` or `README.md` names "Best Apps and Agents Track"
- [ ] **NVIDIA model used**: Grep for `Nemotron` or `nvidia/` in `core/config.py` or docker env
- [ ] **Nebius Token Factory**: Grep for `nebius_base_url` or `api.studio.nebius.ai`

### Repository

- [ ] **LICENSE file exists** at repo root and contains a valid open source license (MIT / Apache / MPL)
- [ ] **README.md exists** at repo root
- [ ] **README has setup instructions**: grep for `docker compose` or `pip install` or `uvicorn`
- [ ] **README mentions NVIDIA/Nemotron**: grep for `Nemotron` in README
- [ ] **README mentions Nebius Token Factory**: grep for `Token Factory` or `nebius` in README (case-insensitive)
- [ ] **.gitignore exists** and contains `.env`

### Credentials & Security

- [ ] **No hardcoded secrets in compose files**: check all `docker-compose*.yml` for literal passwords (not `${VAR}` style)
- [ ] **No hardcoded secrets in Python files**: grep for `api_key\s*=\s*["'][^${\s]{8,}` (case-insensitive) in `api/`, `core/`, `jobs/`
- [ ] **.env not committed**: run `git ls-files .env` — must be empty

### Code Quality

- [ ] **Ruff passes**: run `ruff check .` — must report 0 errors (B008 suppressed is OK)
- [ ] **All unit tests pass**: run `pytest tests/unit/ -q` — must show 0 failures
- [ ] **No TODO/FIXME/HACK in production code**: grep `api/`, `core/`, `jobs/`, `stream_processor/` for `TODO|FIXME|HACK` (warn, not fail)

### Deployment

- [ ] **docker-compose.prod.yml exists**
- [ ] **nginx/logtrace.conf exists**
- [ ] **scripts/start.sh exists and is executable**
- [ ] **.env.example is complete**: grep for all required vars — `NEBIUS_API_KEY`, `NEBIUS_STORAGE_ACCESS_KEY_ID`, `NEBIUS_STORAGE_SECRET_KEY`, `TAVILY_API_KEY`, `DATABASE_URL`, `REDIS_URL`

### Submission Artifacts

- [ ] **demo video**: Ask the user — "Have you recorded and uploaded the 3-minute demo video to YouTube? (y/n)"
- [ ] **live demo URL**: Ask the user — "Is the portal live at a public URL? (provide it or say no)"
- [ ] **public GitHub repo**: Ask the user — "Is the GitHub repo public with the LICENSE visible? (y/n)"

## Report Format

```
╔══════════════════════════════════════════════════════════╗
║        LogTrace — Hackathon Submission Checklist        ║
║              NVIDIA × Nebius Global AI Hackathon         ║
╚══════════════════════════════════════════════════════════╝

Track: Best Apps and Agents  ✓

REQUIREMENTS          PASS  WARN  FAIL
─────────────────────────────────────
Track & Models         3/3
Repository             6/6
Credentials            3/3
Code Quality           4/4    1
Deployment             5/5
Submission Artifacts   1/3          2

─────────────────────────────────────
TOTAL                 22/24   1    2

⚠️  WARNINGS
  · 3 TODO comments in jobs/stage2/rca.py — review before submission

❌  FAILURES (must fix before submitting)
  · Demo video: not confirmed
  · Live demo URL: not provided

VERDICT:  NOT READY — fix 2 failures above
──────────────────────────────────────────
Run /check-secrets for a dedicated credential scan.
```

Replace counts and items with actual findings. End with `READY FOR SUBMISSION ✓` or `NOT READY — fix N failures above`.
