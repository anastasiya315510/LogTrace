---
name: "Safe Side Effects"
description: "Dry-run mode — preview every side effect before executing. Files, commands, DB changes, API calls — all shown, nothing run."
allowed-tools: Bash(git status), Bash(git diff), Bash(ls), Bash(find), Glob, Grep, Read
disable-model-invocation: true
category: "Safety"
tags: ["dry-run", "preview", "safety", "side-effects"]
---

Dry-run mode: show every side effect the task would produce without executing any of them.

Task to preview: $ARGUMENTS
