---
description: Start one micro-task from a bead. Locks scope, delegates exploration, keeps the main thread clean.
argument-hint: <bead-id>   (omit to pick from `bd ready`)
allowed-tools: Bash(bd:*), Bash(git status:*), Bash(git log:*), Bash(git branch:*), Bash(rg:*), Read, Agent
---

# Micro-task start — `$ARGUMENTS`

You are starting **exactly one** micro-task. Do not begin a second one in this session.

## Step 1 — Load the unit of work (disk, not memory)
!`bd show $ARGUMENTS 2>/dev/null || bd ready`

If no bead id was given: show `bd ready`, ask the user to pick **one**, and stop.
Never pick two. Never start work on a blocked bead.

## Step 2 — Sanity-check the tree
!`git status --porcelain`
!`git rev-parse --abbrev-ref HEAD`

If the tree is dirty with unrelated changes, say so and stop — a micro-task starts clean.

## Step 3 — Size the task BEFORE exploring
State, in <= 5 lines:
- **Scope:** which files/subsystem (expect 3–8 files, 1 subsystem)
- **Definition of Done:** the single command that proves it — normally `make check`.
  If DB-dependent code is involved, note that `make test-bench` is also required.
- **Out of scope:** what you will explicitly NOT touch

If the task needs > 1 subsystem, > 8 files, or >= 2 DoD commands: **do not start.**
Split it with `bd create … --deps discovered-from:$ARGUMENTS` and stop.

## Step 4 — Exploration goes to a subagent. Always.
Do **not** read files on the main thread to "understand the area". Spawn an `Explore`
subagent with a precise question, e.g.:

> "For bead $ARGUMENTS: list the exact files and symbols involved in <feature>, the
> existing test modules that cover it, and the established pattern to follow. Return
> file paths + line ranges + a 10-line summary of the pattern. No file dumps."

Accept its summary as your map. On the main thread, `Read` only the specific line
ranges you are about to edit.

## Step 5 — Implement, then verify
Edit. Then run the DoD command **once**, redirecting output:

    make check > /tmp/mt-check.log 2>&1; tail -40 /tmp/mt-check.log

Red -> fix the specific failure. Do not re-explore.

## Step 6 — Budget check
Ask the user to check `/context`. Over ~60%: run `/mt-handoff` instead of pushing on.

## Step 7 — Close out
When `make check` is green, run `/mt-done $ARGUMENTS`.

---
**Rules for this session:** one bead, no unrelated refactors, no "while I'm here" fixes
(file those as new beads with `--deps discovered-from:$ARGUMENTS`), never `git add -A`.
