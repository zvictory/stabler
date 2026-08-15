---
description: Close a micro-task — verify DoD, commit atomically, close the bead, end the session cleanly.
argument-hint: <bead-id>
allowed-tools: Bash(make check), Bash(make test), Bash(git status:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*), Bash(bd:*)
---

# Micro-task done — `$ARGUMENTS`

## Step 1 — DoD, not opinion
!`make check > /tmp/mt-check.log 2>&1; echo "exit=$?"; tail -40 /tmp/mt-check.log`

**If this is not green, the task is not done.** Do not commit. Do not close the bead.
Do not write "should be fine". Report the failure and stop.

If the change touched DB-dependent code, state clearly that `make test-bench` (the 15
bench modules, not covered by `check`) is still outstanding — do not silently treat
`check` as full proof.

## Step 2 — Review what you are about to commit
!`git status --porcelain`
!`git diff --stat`

Anything not part of bead `$ARGUMENTS` must be removed from the commit or filed as its
own bead. **Never `git add -A`. Stage explicit paths only.** Never stage dev/build junk
(`graphify-out/`, `stabler/translations/.tx_*.json`, `.smoke/`, scratch `tests/`).

## Step 3 — Atomic commit
    git add <explicit paths>
    git commit -m "<type>($ARGUMENTS): <what changed, imperative>"

One micro-task = one commit. After it exists, nothing in this conversation is
load-bearing any more.

## Step 4 — Close the bead with a reason worth reading
!`bd close $ARGUMENTS --reason "<what landed> — commit <sha>, make check green"`

The reason field is what the *next* session reads instead of this transcript. Write it
for a reader with zero context: what changed, what was verified, what was left out.

## Step 5 — File anything discovered
    bd create "<discovered work>" -t task --deps discovered-from:$ARGUMENTS

## Step 6 — End the session
!`bd ready`

Tell the user: "`$ARGUMENTS` is landed and committed. Run `/clear`, then `/mt <next-id>`."
Do **not** start the next bead in this window. A fresh window is free; a compacted one is not.
