---
name: stabler-orchestrator
description: Use when delegating Stabler implementation work to the Antigravity (agy) CLI — writing the implementation contract, launching agy in an isolated worktree, reviewing the diff independently, running the verification gates, and merging to main. Also use when asked how the Claude→agy→review loop works, or before any production deploy decision.
---

# Stabler orchestration — Claude specs, Antigravity implements, Claude verifies

You are the architect, reviewer and integrator. Antigravity (`agy`) is an
implementation subagent that runs in an isolated git worktree and does exactly
one task's contract. Human-facing walkthrough and the measured CLI facts live in
`docs/runbooks/claude-antigravity-orchestration.md` — read it when you need the
exact invocation; this file is the workflow you follow.

## Ownership boundary (non-negotiable)

| Claude owns | Antigravity owns |
|---|---|
| Repository exploration, root-cause analysis | Implementing the contract, nothing else |
| Architecture and interface decisions | Running the tests named in the contract |
| Accounting, tenant-isolation, migration, security, deploy judgment | Returning a structured completion report |
| Independent diff review and final verification | — |
| `git add <explicit paths>`, commit, `--no-ff` merge, push | — |

Antigravity **never** deploys, touches production or SSH, merges, pushes,
or rewrites history. Production deployment **always**
requires explicit approval from Zafar — one `bench restart` blips all seven
tenants.

## 0. Discover before you ask

Read the code before forming questions. `git status --short --branch`,
`git worktree list --porcelain`, `git log --oneline -10`. Never disturb
in-flight work: if the tree is dirty or another worktree holds a branch, do not
stash, checkout over it, reformat or stage anything you do not own — open your
own branch and worktree instead.

Only ask Zafar when a **business decision** is missing (which account, which
rounding rule, which tenant owns it). Never ask what the code can answer.

## 1. The contract, before anything else

One file: `docs/plans/<yyyy-mm-dd>-<topic>.md`, the repository's existing
convention. It holds the frozen contract and, appended below it, the running log —
`conversation_id`, review findings, correction-cycle counter, blockers. Do not
split it into `REQUIREMENT.md` / `IMPLEMENTATION.md` / `REVIEW.md`, and do not
stand up a tracker; there is none (`bd` was removed 2026-08-18).

**Before freezing a contract, verify EVERY symbol, path and endpoint in it against the
codebase. A fabricated path is implemented literally inside a decision-complete contract —
this is delegation's primary failure mode.** Measured 2026-08-15: the frozen phase-3
design named `stabler.api.vehicle_finance.v1.*` for all twenty callables; ten of them
live in `read.py` and `work.py`, and the wrong path reached slice 3a's contract before
review caught it. Grep the definitions, do not trust a design document — including one
you wrote.

The contract must be **decision-complete** — agy implements it literally, so any
gap becomes an invented behaviour. Required sections:

```
Objective and business reason
Owner tenant and owner module            # see CLAUDE.md tenant table
Current architecture and patterns to copy
Files to inspect first (read-before-code)
Allowed files / subsystem ownership
Forbidden and out-of-scope areas
Backend behaviour and interfaces         # endpoint, args, return shape, errors
Frontend states                          # loading, empty, error, permission-denied
Migration and compatibility requirements # idempotent, pre-model-sync guards
Accounting and currency invariants       # precision, base vs account currency
Tenant-isolation requirements            # enable_* + _MODULE_ROLES + meta.module
Edge cases and failure behaviour
Measurable acceptance criteria
Exact verification commands
Required completion report
```

## 2. Risk classification and model routing

`agy agents` is **empty** on this machine — no installed agents. Route with
`--model`, never `--agent`.

| Risk | Route to | Work |
|---|---|---|
| Low | `--model gemini-3.6-flash-high` | CSS/spacing, straightforward Vue components, CRUD screens, translations, mechanical refactors, isolated tests |
| Medium | `--model gemini-3.1-pro-high` | Multi-file business logic, API changes, concurrency, non-trivial bug fixes |
| High | **Claude main thread — do not delegate** | Architecture; GL / Payment Entry / allocation semantics; FX; permissions; multi-tenancy; migrations; production incidents; final review; deploy decisions |

For sensitive work that *is* delegated, make the contract decision-complete
first. You stay accountable for every invariant and must verify it yourself. If
a requirement cannot be made deterministic, implement that part yourself or ask
Zafar for the missing business decision.

## 3. Branch and isolated worktree

```bash
git checkout main && git pull --ff-only
git worktree add -b feat/<tenant-or-module>-<topic> .worktrees/agy-<task> main
ln -s "$(git rev-parse --show-toplevel)/node_modules" .worktrees/agy-<task>/node_modules
mkdir -p .worktrees/logs   # frappe/utils/logger.py:24 opens <parent of cwd>/logs/frappe.log; without it `make check` is red on unrelated tests (measured 2026-09-04)
```

**Every bench command names the site.** The bench's `default_site` (and `sites/currentsite.txt`) is `stabler`, a
local copy of ANJAN and Mikas data — an unqualified `bench run-tests`, or a briefing that says "run the probe"
without the command, lands there and WRITES fixtures into tenant data. Measured 2026-09-04: a delegated cycle
ran four commands with `--site stabler`, executed a patch by hand and left two half-cancelled invoices (backlog,
"the `stabler` site carries a bench probe's residue"). Write `--site genesis-test.local` into the command you hand
over, every time, and read a proposed cleanup script before approving it — never its description.

`fix/…` and `chore/…` for the other two kinds. `.worktrees/` is gitignored
(`.gitignore:11`), so the worktree never enters a commit. **One writing agent per
worktree** — never point two at the same directory.

**The symlink is not optional, and it is not a convenience.** A fresh worktree has
no `node_modules`, and until 2026-08-17 `lint-js-changed` and `test-js` answered
that by echoing "node_modules missing" and exiting 0. So `make check` printed
`OK — pre-push gate passed` with two of its six gates switched off — measured by
putting an unterminated call in a `.vue` file and watching it through. Since most
of what a delegated agent writes here is Vue, that is the majority of the diff
going unlinted and untested. The Makefile now FAILS instead outside CI, so a
worktree without the symlink cannot report a false green; the symlink is what
makes it report anything at all. `npm ci` is not the alternative — the tracked
lockfile is out of sync with `package.json` and it exits 1; `npm install` works
but rewrites the tracked `package-lock.json` inside the worktree.

**`make test-bench` cannot be run from a worktree**, and the target refuses. It
does `cd $(LOCAL_BENCH) && bench run-tests`, and the bench venv resolves the
`stabler` package through `stabler.pth`, which points at the MAIN tree — so a
worktree run measures main's code and reports the verdict as the branch's.

**One module at a time CAN be measured from a worktree, for the red/green loop
only.** `stabler.pth` is a plain path line appended by `site`-module processing;
`PYTHONPATH` is consulted before it, so prepending the worktree's own root makes
`import stabler` resolve entirely to the worktree:

```bash
PYTHONPATH=/abs/path/to/.worktrees/agy-<task> \
  bench --site genesis-test.local run-tests --module stabler.tests.<module>
```

Measured 2026-08-21, four ways on one worktree: `stabler.__file__` and
`frappe.get_app_path("stabler")` both resolve to the worktree; a guard mutated in
the worktree turns that module RED; the same mutated tree **without**
`PYTHONPATH` stays GREEN, proving an unset run still measures main. No git
operation and no write to the main tree — one env var on one invocation.

**It measures the worktree's PYTHON, never its SCHEMA.** Doctype meta comes from
`genesis-test.local`'s already-migrated database, so a branch that also changes
doctype JSON or `patches.txt` is not covered — and the two ways that fails are
not equally visible:

| Branch adds | What the probe run does |
|---|---|
| a new doctype | LOUD — `DoesNotExistError: DocType <X> not found` |
| a field to an existing doctype | **SILENT — `meta.get_field()` returns `None` and `insert()` SUCCEEDS with the field dropped** |

The silent row is the whole hazard: measured 2026-08-21, a document carrying a
worktree-only field inserted clean and read back with the attribute simply
missing. That is the same false-pass class the tree guard exists to prevent,
re-entered through a different door. Such a branch must have the site migrated
first, which writes the branch's schema into shared state — a merge-to-main
decision, not a worktree one. (A probe run does not sync JSON on its own:
verified the worktree-only doctype was still absent from the site afterwards.)

**This adds no locking.** It is a raw `bench` call and never touches the
`.stabler-test-bench.lock` directory `make test-bench` holds, so it can land in
the middle of someone else's run. There is still exactly one bench, one pinned
site (`genesis-test.local`, enforced by the `#pin` line in
`.github/bench-known-red.txt`), one MariaDB and one redis, so two concurrent runs
collide inside `before_tests` regardless — and `before_tests` itself resolves
through the worktree's own `hooks.py`, writing that branch's fixtures into the
shared database. Check the lock is free and no other agent is mid-run first.

**It is the inner loop, not the gate.** It proves one module red then green while
you iterate. It does not run the derived `BENCH_TESTS` sweep, the ZERO COVERAGE
check or the four-way ratchet against `.github/bench-known-red.txt` — those live
in `make test-bench` and still require the main tree. So a bench-gated task is
*iterated* in parallel but *gated* sequentially: merge into the main tree and run
`make test-bench` there before the verdict counts.

## 4. Launch agy

Run from inside the worktree. The completion report comes from `--json-schema`,
which adds a schema-validated `structured_output` object to the envelope — read
that, never parse the free-text `.response`.

```bash
cd .worktrees/agy-<task>
agy \
  --model gemini-3.1-pro-high \
  --effort high \
  --mode accept-edits \
  --sandbox \
  --dangerously-skip-permissions \
  --output-format json \
  --json-schema .worktrees/agy-report.schema.json \
  --print-timeout 60m \
  --print "<bounded implementation instruction>" > /tmp/agy-<task>.json
```

`--dangerously-skip-permissions` is permitted **only while all six controls hold
at once**: execution is inside `.worktrees/agy-<task>`; `--sandbox` is on; no
`--add-dir` widens the scope; the prompt forbids production, SSH, deploy, merge,
push, destructive git and unrelated files; you wait for agy to exit before
touching that worktree; you review the complete diff before accepting it. If any
one of those is false, drop the flag.

Instruct agy to leave its changes **uncommitted**. Record `conversation_id` in
the contract log immediately — without it you cannot resume for fixes.

## 5. Review independently

Treat the completion report as a claim, not evidence. Then:

```bash
cd .worktrees/agy-<task>
git status --short
git diff $(git merge-base HEAD origin/main)
```

Read every changed file in full, check the acceptance criteria one by one, check
existing callers and interfaces, and run the deterministic checks yourself.
Delegate the adversarial pass to the `stabler-diff-reviewer` agent, then
adjudicate its findings — it is read-only and cannot fix anything.

Classify in the contract log as **P0** (correctness, money, security, data loss),
**P1** (contract violation, missing acceptance criterion), **P2** (rule
violation, missing i18n/state), **P3** (polish). Fix P0–P2 before merging.

**"The UI opened" is not proof the displayed financial data is real.** Cross-check
displayed amounts against the backing API or database and against an existing
real-data card on the same screen. A screen full of hardcoded demo `ref()` values
compiles, passes tests, deploys, and lies.

## 6. Correction cycles — maximum three

Resume the same conversation in the same worktree:

```bash
agy --conversation <conversation-id> --mode accept-edits --sandbox \
    --dangerously-skip-permissions --output-format json \
    --json-schema .worktrees/agy-report.schema.json --print-timeout 60m \
    --print "<exact findings and the exact required corrections>"
```

After the third failed cycle: stop. Leave the branch as it is, write the
blocker and the evidence into notes, and ask Zafar for direction. Do not silently
finish the work yourself and call the delegation a success.

## 7. Verification gates

Minimum for every change: `make check` and `git diff --check`. Add by impact:

| Change touches | Also run |
|---|---|
| Frontend | targeted ESLint/Vitest + `bench build --app stabler` |
| Forms | the `qa-forms` workflow (`.claude/workflows/qa-forms.js`) + direct-route refresh |
| DB / GL / Payment Entry | iterate per module from the worktree with the `PYTHONPATH=` probe (section 3); the gate is still `make test-bench` **in the main tree, one at a time** |
| Patches / doctypes | local migrate rehearsal + re-run for idempotency. The `PYTHONPATH=` probe does **not** cover these — it reads the site's already-migrated schema, and a worktree-only field fails *silently* (section 3) |
| Translations | all five catalogs (en, ru, uz, uzc, tr) present; after deploy, Redis lookup |
| Multi-tenant feature | owner tenant **and** one non-owner leakage smoke test |

`make check`, GitLab CI, `qa-forms.js`, `deploy_stabler.sh` and `bd` stay
authoritative in their own domains. Do not add a second formatter, test hook,
deploy script, tracker or browser framework.

## 8. Integrate

```bash
cd .worktrees/agy-<task>
git add <explicit paths>            # never `git add -A`; translations as five CSVs
git commit                          # trailer: Co-Authored-By: Claude <noreply@anthropic.com>
git fetch origin && git merge origin/main     # merge, never rebase
make check                                    # re-run after the merge
cd <main tree> && git checkout main
git merge --no-ff feat/<...> && git push      # one chain
git rev-parse main origin/main                # must match
git status --porcelain                        # must be empty
git worktree remove .worktrees/agy-<task>  # only the one you created
```

The commit trailer carries **no model version** — a pinned name goes stale and
conflicts with whatever the harness injects.

Rebase is banned here by measurement, not taste: CRLF translation CSVs re-conflict
on every commit (23 consecutive, `docs/runbooks/parallel-development.md:42`).

## 9. Deployment boundary

Stop after push and **request explicit approval from Zafar.** Only then:

1. Confirm `main` clean and `main == origin/main`.
2. Run the canonical `deploy_stabler.sh`. Never hand-reconstruct rsync/migrate/restart.
3. Verify the owner tenant, then at least one secondary Stabler tenant.
4. If patches/doctypes changed: verify the DDL on every Stabler-bearing site —
   `frappe.db.table_exists` first, because `has_column` raises on sites that lack
   the doctype and a missing table means *not applicable*, not *failed migrate*.
5. If translation catalogs changed: `bench --site <s> clear-cache` on all seven
   sites and read a new key back through `_load_translations`.
6. Direct-URL refresh smoke test on a record form per module touched.
7. Check the relevant operational logs.

Antigravity never runs `deploy_stabler.sh`.

## Stabler invariants agy must be told, every time

Do not paraphrase these loosely into a prompt — quote them.

- The SPA never links to the Frappe Desk (`/app/...`) — no `<a href>`, no
  `window.open`, no router meta.
- Every monetary input uses `MoneyInput`; `qty` stays a plain number input.
- Every date input uses `DateInput`; every displayed date uses
  `formatDate` / `formatDateTime` from `composables/date.js`.
- Status badges resolve through `getStatusBadgeClass` in `composables/status.js`.
- Tables are striped globally — never add `table-striped`.
- One `.btn-primary` per visual region.
- Amounts render in their transaction currency only (the Sales Order footer
  `≈` line is the one documented exception).
- Lists use `ListToolbar.vue` with auto-apply filters and `SkeletonRows.vue`.
- Code is English-first; user-facing strings ship in all five catalogs before push.
- Never branch on tenant name — gate on module + `Stabler Company Modules`.
- Every module parent route carries `meta: { module: "<key>" }`; register the
  module in `_MODULE_ROLES` (`stabler/api/organization.py`). New modules default OFF.
- Patches are idempotent and guard with `has_column`. `patches.txt` carries a
  `[post_model_sync]` marker (line 41, added 2026-07-08 in 22f70e7; every patch from
  v81 on sits below it and runs AFTER the doctype sync). This line said "no marker"
  until 2026-09-03 and contradicted `.claude/rules/20-backend-migrations.md:15`; the
  rules file was right. Guard either way — the half a patch sits in is not a reason
  to skip `has_column`.
- Money maths is deterministic and tested; currency and allocation rules are
  enforced server-side.

`make guards` (`Makefile:216`) mechanically enforces the date, Desk-link,
striping, tenant-branching, `meta.module` and money-input rules. It is a floor,
not a substitute for reading the diff.
