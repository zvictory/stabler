---
description: Planned handoff when the 60% context budget is hit mid-task. Beats compaction.
argument-hint: <bead-id>
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(bd:*), Write
---

# Planned handoff — `$ARGUMENTS`

Triggered because `/context` passed ~60% before the micro-task finished. This is not a
failure to hide — it is data: **the task was mis-sized.** Record it.

## Step 1 — Snapshot the truth
!`git status --porcelain`
!`git diff --stat`

## Step 2 — WIP commit (yes, even half-done)
A WIP commit is cheap and revertible. An uncommitted tree that survives a compaction is not.

    git add <explicit paths>
    git commit -m "wip($ARGUMENTS): <exactly where this stands>"

## Step 3 — Write the handoff file
Write `.claude/handoff/last-handoff.md` with, and only with:
- Bead id and the one-line goal
- What is **done and verified** (with the command that proved it)
- What is **done but unverified**
- The **exact next action** — a command or a file:line, not a paragraph
- Known traps discovered (so the next session doesn't rediscover them at 50k tokens)
- Files already explored, so the next session **does not re-explore them**

Keep it under 60 lines. A fresh session reads this; every line costs it budget.

## Step 4 — Split the remainder into a real bead
!`bd create "<remaining work for $ARGUMENTS>" -t task --deps discovered-from:$ARGUMENTS`

## Step 5 — Diagnose the mis-size (one honest line)
Which was it?
- Scope was larger than one subsystem -> should have been an epic
- Exploration ran on the main thread instead of a subagent -> protocol break
- Command output was pulled inline instead of redirected to a file
- Unrelated work crept in

Append that line to the handoff file. This is how the sizing heuristic gets better.

## Step 6 — Stop
"Handoff written, WIP committed, remainder filed as `<new-id>`. Run `/clear`, then `/mt <new-id>`."
Do not continue. Do not `/compact`.
