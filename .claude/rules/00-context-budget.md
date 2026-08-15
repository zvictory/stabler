---
description: Context budget and micro-task discipline. Always active.
---

# Context budget — non-negotiable

The context window is a **consumable resource with a budget**. Auto-compaction is not a
feature you use; it is an **alarm meaning the unit of work was mis-sized**.

1. **Exploration never happens on the main thread.** "Where is X", "what does this module
   do", "which tests cover it" → delegate to the `Explore` subagent; it burns its own
   window and returns a conclusion. Reading 8 files inline costs ~50k tokens; the same
   answer from a subagent costs ~1.5k. On the main thread, `Read` is for files you are
   **about to edit** — nothing else.
2. **State lives on disk, not in the conversation.** Queue → `bd`. Progress → git commits.
   In-flight position → `.claude/handoff/last-handoff.md`. A fact that exists only in the
   transcript does not exist.
3. **One micro-task per session.** A micro-task is the *largest* unit that satisfies all
   four: one verification command (`make check`), one atomic commit (explicit paths),
   ≤ 60% of the window, inputs and outputs on disk.

## The 60% rule
Check `/context` at boundaries. Past ~60% with the task unfinished: **stop advancing** —
run `/mt-handoff`, wip-commit, file the remainder as a bead, and tell the user to `/clear`.
A planned handoff is faster and lossless; a compaction is neither.

## Sizing
| Signal | Micro-task | Split into an epic |
|---|---|---|
| Files touched | 3–8 | > 8 |
| Subsystems | 1 | ≥ 2 |
| Tool calls | ≤ 25 | > 25 |
| DoD commands | 1 | ≥ 2 |

More than one subsystem → do not start coding. Create beads with `--deps` and work the
first ready one.

## Cheap-output habits
- Read line ranges (`offset`/`limit`), not whole files.
- `rg -c` / `rg -l` first; pull content only for hits that matter.
- Long output to a file, then grep it: `make check > /tmp/c.log 2>&1; tail -40 /tmp/c.log`
- Never `cat` a file over ~200 lines "to have a look". Never re-read a file you edited.

## Prefer /clear over /compact
`/compact` keeps a lossy session alive. `/clear` ends it — and because state lives on disk,
ending it costs nothing. Compaction is only expensive because state was kept in the chat.
