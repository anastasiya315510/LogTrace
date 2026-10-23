---
name: "Check Secrets"
description: "Scan the project for credential leaks before pushing to a public repository"
allowed-tools: Bash, Glob, Grep, Read
category: "Security"
tags: ["security", "credentials", "secrets", "pre-push"]
---

Scan the project for credential leaks — hardcoded secrets, passwords, API keys, or tokens in tracked files. Checks .gitignore coverage, docker-compose files, YAML/env configs, and staged files. Reports findings with file:line references and suggests fixes.

$ARGUMENTS
