---
name: decision-review
description: Convene the four-lens decision panel before committing to a judgement that is expensive to reverse — merging, accepting a red or ambiguous gate result, obeying a plan or table written elsewhere, sequencing work, closing a bead whose DoD was not proven, or writing a number into a rule. Produces decisions with differential acceptance criteria, not findings. Use when you are about to say "this is fine, proceed" and would not be able to name the evidence.
---

# Decision review — the four-lens panel

This replaces "report findings and wait for a human to decide". You convene the
panel, you argue it out, you decide, and you state what would change your mind.
The human reviews decisions, not raw output.

Derived from a working session on 2026-08-15 in which four independent agents
each hit the same failure class, and the coordinating human's factual claims were
wrong four times out of roughly fifteen. Both facts are why the rules below are
mechanical rather than aspirational.

This file was itself put through Rule 1 before installation on 2026-08-15. Three
of its claims were wrong, and one of the "corrections" was itself wrong; both
are recorded in the ledger at the bottom. A skill about verification that
shipped unverified would have been the joke that wrote itself — and the review
that shipped an unmeasured correction very nearly was.

---

## When to convene

Convene when a judgement is **expensive to reverse** or **will be believed later**:

- before a merge, a push, or a deploy
- when a gate is red, or green in a way you cannot fully account for
- when you are about to obey a plan, table, checklist or hand-off written by
  someone else — including by the human, including by a previous you
- when sequencing: which of these three things first, and why
- when closing a bead whose Definition of Done was not actually executed
- when a number, threshold or count is about to enter a rule, a doc, or a commit
  message

Do **not** convene for: mechanical edits with a passing gate, a task whose DoD ran
green and covered the change, or anything you could redo in five minutes. The
panel costs context; spend it where reversal is expensive.

---

## Rule 0 — Measurement precedes assertion

**No number, count, filename, line number or status appears in your output unless
a command in this session produced it.** Not from memory, not from a report, not
from a doc, not from a previous turn.

If you must cite something you did not measure, mark it: `(unverified — from
<source>)`. That marker is not a weakness; an unmarked stale number is.

Corollaries, each earned on 2026-08-15:

- **Never report the length of truncated output as a total.** A `| head -10` that
  yields ten lines is not "ten files". This exact error was committed while
  cataloguing this exact error class.
- **A plausible number is more dangerous than an implausible one.** "the other 15
  bench modules" was challenged; "84 frappe-free modules" sat unchallenged in
  three files for longer, and was off by 2.1×. Recheck the ones that look right.
- **Prefer naming the set over counting it.** `the modules listed in
  .github/frappe-free-tests.txt` cannot rot; `the 84 modules` rots the next time
  someone adds a test. If a count is unavoidable, stamp it with its measurement
  date.
- **Naming the set is necessary, not sufficient — the set's own header rots too.**
  Measured 2026-08-15: `.github/frappe-free-tests.txt` contains 178 module lines
  while its own header line 3 still reads *"Verified 2026-07-26: 84 of 99
  modules."* The rule that points at the file is correct; the file lies about
  itself. When you name a set, check what the set claims about its own size.

---

## Rule 1 — Verify the instruction before obeying it

A table handed to you is a claim, not a fact. Before acting on each row, check it
against the code.

On 2026-08-15 this rule caught, in one session: a "contradiction" that was not one
(`AGENTS.md:38` already deferred to CLAUDE.md), a fourth occurrence of a stale
number that the requester's grep pattern could not match, a "decision" that was
actually a completed-work record, and an item count that was wrong by one. Every
one of these would have shipped if the instruction had been obeyed as written.

When you find the instruction wrong: say so plainly, state what is actually true,
and proceed on the corrected version. Do not silently comply, and do not stop
work over it.

---

## The four lenses

Take each in turn. Write two or three sentences per lens — not a paragraph. If a
lens has nothing to say on this decision, write "nothing" and move on; a lens that
always speaks is decoration.

**System Architect** — Is this the right shape, or a workaround that will need
undoing? Does a pattern for this already exist in this repo? What does this
decision make harder later?

Three patterns already exist here; check them before inventing a fourth
(all three verified 2026-08-15):

| Pattern | Where | What it actually is |
|---|---|---|
| the ratchet | `Makefile:9-17`, `Makefile:90` | lint only the files you touched, so the gate is never permanently red |
| the pinned-version file | `.ruff-version` (`0.16.0`) | one line, one tool, no drift between machines |
| the derived list | `Makefile:190` — `BENCH_TESTS := $(shell ls stabler/tests/test_*.py ...)` | the list is computed, so it cannot go stale |

Note the distinction, because it was got wrong once already:
`.github/frappe-free-tests.txt` is **not** a derived list — it is hand-maintained
("Adding a test? ... append it here"), which is exactly why its header count went
stale. `BENCH_TESTS` is the derived one. A *named* set beats a count; a *derived*
set beats a named one.

**Dev Team** — What is this like to live with? Where will the friction be, and
what will people do to get around it? A policy that loses to friction is not a
policy. Is the failure mode obvious at the moment it happens, or discovered a week
later?

**DevOps** — What is the environment this depends on, and is it pinned? Who runs
it, when, and what happens when nobody does? Is the result reproducible tomorrow,
on a different site, by a different session?

**Skeptic** — see below. Not a lens you wear; an agent you spawn.

---

## The Skeptic runs as a subagent. Always.

Self-skepticism inside your own context is weak — you are arguing with the
reasoning that produced the conclusion, using that reasoning. Spawn it:

> "Here is a decision I am about to commit to: <decision>. Here is the evidence:
> <evidence, with the commands that produced it>. Your job is to **refute it**.
> Find the assumption that is doing the load-bearing work and attack it. Check
> whether any number came from a report rather than a measurement. Check whether
> the acceptance criterion could be satisfied by something that did nothing.
> Default to 'this is not proven' when uncertain. Return your strongest objection
> first, and say explicitly whether it should block."

Take the objections seriously enough to change the decision. On 2026-08-15 the
skeptic's objections changed the outcome three times: an unbounded environment
cleanup got a stop condition, a merge acceptance criterion moved from "green" to
"green **and** the test count increased", and a proposed symlink was required to
be proven before it was written into a rule.

If the skeptic finds nothing, say so — that is a result, and it is rare enough to
be worth noting.

---

## The failure class to check every time

Three shapes of the same bug: **a result that looks complete but proves nothing.**
Ask which of these could be true of what you are about to accept.

Each row is tagged with whether the repo has actually fixed it. Read the tags:
a table that mixes fixed and live examples in the present tense reads as a
current-state audit when it is a history, and that is its own stale value.

| Shape | Looks like | Repo instance (measured 2026-08-15) | Status |
|---|---|---|---|
| **Silent skip** | exit 0 | `make check` skips exactly two sub-gates when `node_modules` is absent: `lint-js-changed` (`Makefile:97-99`) and `test-js` (`Makefile:242-244`). Both echo a note and return 0. | **LIVE — not fixed** |
| **Silent skip** | exit 0 | a bench module whose every test skipped printed `OK`. Two real instances, measured: `test_related_documents_integration` **skipped 3 of 3** and printed `OK (skipped=3)` (bead `stabler-97o`); `test_crm_deal_trash_integration` **skipped 10 of 10** (bead `stabler-ytx`). `test_deploy_migrate_gate` is the third shape — collected none at all (bead `stabler-56v`). | **DETECTED** since `44fe689` — `ZERO COVERAGE` sets `fail=1` (`Makefile:220`). The modules themselves are still red; they are in `.github/bench-known-red.txt`. |
| **Silent truncation** | a complete-looking list | `bd ready` defaults to `--limit 10` (confirmed: `bd ready --help`, `-n, --limit int … (default 10)`). Ready work measured 2026-08-15: **66**. `head -10` reported as a total. | **LIVE** — the default is the tool's, not ours |
| **Stale value** | a confident number | a "no matches" baseline that was 17 on remeasurement; `84 of 99` in `.github/frappe-free-tests.txt:3` against 178 actual lines (2.1×); `15` bench modules against 50 (3.3×) | **PARTLY FIXED** — `Makefile:151` now refuses to write the count; the `frappe-free-tests.txt` header still carries the stale one |

The standing fix for all three: **whatever was skipped, truncated or assumed must
say so out loud, and the result must be red — not green with a note.** A gate is a
gate or it is not one.

Note what the two LIVE rows have in common: both are gates that degrade to a
message when their environment is missing. That is the shape to hunt for.

---

## Acceptance criteria must be differential

"Green" is not an acceptance criterion when the suite was already partly red, and
"the tests pass" is not one when the new tests may not have run at all.

State acceptance as a **change** you can observe:

- the count of executed tests in the affected module **increases**
- the known-red set **shrinks or stays identical** — never grows
- the measured value moves from X to Y, where X was measured, not recalled

If a criterion could be satisfied by something that did nothing, it is not a
criterion. Rewrite it.

## Ratchet, not big-bang

When a gate is newly honest and the tree fails it, do not demand a clean tree
before anything may proceed — the repo already learned this for lint. Verbatim,
`Makefile:9-11`:

> permanently red, and a permanently red hook is one everybody bypasses with
> `--no-verify`. So `check` lints only the files you touched: new code clean, old
> code untouched.

Record the known-bad set in a file, pinned to the environment it was measured on,
each entry pointing at a bead. Enforce mechanically in both directions: a new
failure is red, and an entry that has started passing is also red ("remove it from
the list"). The set only tightens. Intention is not a mechanism.

---

## Output contract

End every panel with exactly this, and nothing decorative:

```
DECISIONS
  1. <decision> — because <the evidence, naming the command that produced it>
  2. ...

ACCEPTANCE
  <differential, observable criterion per decision>

NOT DECIDED
  <what you deliberately left open, and who or what would settle it>

WOULD CHANGE MY MIND
  <the specific observation that would reverse this>

CORRECTIONS
  <anything in the input instruction that was wrong, and what is actually true>
```

Then act on the decisions. Do not wait for approval unless a decision is in the
irreversible set — push, deploy, delete, or history rewrite — in which case stop
and present the panel output.

---

## Keep your own error ledger

Append to the session log every factual claim of yours that turned out wrong, with
what caused it. Not as penance — as calibration data. Four wrong claims in fifteen
is a 27% error rate on facts, and knowing that number is what makes Rule 0
non-negotiable rather than fussy.

The pattern to watch for in your own output: the errors cluster on **numbers you
carried forward instead of measuring**, and on **counts taken from truncated
output**. If you catch yourself typing a figure without a command behind it in
this session, stop and run the command.

### Ledger — this file's own installation review, 2026-08-15

| Claim as written | Measured | Verdict |
|---|---|---|
| `Makefile` ratchet paragraph quoted verbatim | `Makefile:10-11` matches word for word | correct |
| `.ruff-version` is a pinned-version file | exists, contains `0.16.0` | correct |
| `bd ready` truncates at 10 by default | `--limit` default is 10 | correct |
| …"10 of 50" | 66 ready, and the figure rots — Rule 0 violation by this file | **wrong** |
| `.github/frappe-free-tests.txt` is the derived-not-hardcoded list | hand-maintained; `BENCH_TESTS` (`Makefile:190`) is the derived one | **wrong** |
| a bench module "skipping 3 of 3 tests" | ~~10 of 10~~ — **the reviewer was wrong, the file was right**: `make test-bench` on 2026-08-16 measured `test_related_documents_integration` skipping exactly 3 of 3 | correct |
| the failure table describes current state | the bench row's *detection* was fixed in `44fe689` before this file was written; the modules are still red | **half wrong** |

Three wrong out of seven, not four — and the seventh line is the one worth
keeping. The reviewer marked "3 of 3" as wrong because a bead described a
*different* module skipping 10 of 10, and pattern-matched it to the same claim.
That is Rule 0 violated by the person enforcing Rule 0: a status asserted from a
bead instead of from a run. `make test-bench` settled it in one command, and it
settled it against the reviewer.

The lesson is narrower and more useful than "measure things": **a plausible
match is not a match.** When you set out to refute a claim and find something
that looks like it, check that it *is* it before writing the correction. A wrong
correction is more expensive than the wrong claim, because it arrives wearing
the authority of a review.
