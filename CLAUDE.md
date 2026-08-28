# Stabler SPA — Project Rules

**This file is the repository constitution.** On conflict, this file wins.
`AGENTS.md` and `project-rules.md` are subsets and carry no independent authority.

Domain rules are **not** in this file. They load automatically when you touch the
matching files, or on demand as skills. Do not restate them here — every line in
this file is paid for in every session.

| Where the rules live | Loads when |
|---|---|
| `.claude/rules/10-frontend.md` | you touch `*.vue`, `*.js`, `public/`, `www/` |
| `.claude/rules/20-backend-migrations.md` | you touch `*.py`, `patches.txt`, doctype JSON |
| `.claude/rules/30-tenant-modules.md` | you touch routes, APIs, doctypes, patches |
| `.claude/skills/stabler-deploy/` | you deploy, or work "disappeared" |
| `.claude/skills/stabler-i18n/` | you add or land user-facing strings |
| `.claude/skills/stabler-orchestrator/` | you delegate implementation to `agy` |

## Hard rules (never violate)

### Verification — Definition of Done
- `make check` = `lint-changed lint-js-changed compile guards test test-js` — the push gate.
- `make test` = the modules listed in `.github/frappe-free-tests.txt` (fast; no bench, no DB).
- `make test-bench` = the rest, derived by `BENCH_TESTS` — **not part of `check`**; needs a
  live bench.
- **Never quote a test count, in this file least of all.** `make test` and `make test-bench`
  each echo the live one. `84` and `15` sat in the two lines above until 2026-08-17 and both
  were wrong; because this file says *on conflict, this file wins*, a stale count here
  outranks the correct one the Makefile prints.
- For DB-dependent changes `make check` alone is **not** sufficient proof. Say so
  explicitly and request `make test-bench` rather than declaring the task done.

### Git discipline
- **Never `git add -A`.** Stage explicit paths only.
- Never stage dev/build junk: `graphify-out/`, `stabler/translations/.tx_*.json`,
  `.smoke/`, `tests/` (untracked scratch), stray heredoc files. `dist/` is gitignored.
- Stage translations as the five CSVs explicitly (`en/ru/uz/uzc/tr.csv`), never the
  whole `translations/` dir (it pulls the `.tx_*.json` caches).
- Commit message trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`.
  Deliberately unversioned — a pinned model name (`Opus 4.8`, `(1M context)`) goes
  stale and silently conflicts with whatever the harness injects, producing
  trailers that match neither convention.
- `main` is the single source of truth; prod is fed from `main`, never from a working tree:
  - Every agent works on its own branch and **merges to `main` when the work is done**.
  - **Pushing is part of merging** — a merge that is not pushed means "the work does not exist".
  - Deploy only from a clean tree; leave `git status --porcelain` empty at the end of the day.
  - Keep `make check` green **per commit**, not per 172 commits.
- Why any of this matters — the five gates between a saved file and a running
  feature, and how work reaches prod without existing in git: `stabler-deploy` skill.

### Language
- Mockups, drafts (e.g. `docs/uat/...`) and discussion may be Turkish or English.
  **Implementation code is English-first** — Vue components, Python backend, error
  messages, docstrings, UI labels, `t("...")` keys.
- **Four languages are offered: en, ru, uz, tr.** A fifth catalogue, `uzc`
  (Ўзбекча, Uzbek Cyrillic), is still shipped and still translated — it was
  removed from the pickers on 2026-08-28, not deleted. Keep staging it with the
  others. Why, and how to undo it: `docs/plans/2026-08-28-uzc-secenekten-cikarildi.md`.
  Full workflow: `stabler-i18n` skill.

### Production
- **Production deploy always requires explicit approval from Zafar** — one
  `bench restart` blips every stabler tenant at once. Never infer approval.
- Deploy only from a clean tree.
- Procedure, prod topology, rollback and smoke checks: `stabler-deploy` skill.

### Delegation
- Implementation delegated to Antigravity (`agy`) follows one canonical workflow:
  `.claude/skills/stabler-orchestrator/SKILL.md` (what Claude executes) and
  `docs/runbooks/claude-antigravity-orchestration.md` (the human-facing runbook).
- `agy` works only inside `.worktrees/agy-<task>` on a feature branch, leaves its
  changes uncommitted, and **never** merges, pushes, deploys or touches production.
  Claude reviews the full diff independently before accepting it.
- Pre-merge review: the read-only `stabler-diff-reviewer` agent (`.claude/agents/`).

## How work is done
Test first. There is no tracker, no ticket ceremony, no micro-task protocol —
those were removed on 2026-08-18 because they cost more than they returned.

    failing test  →  code  →  make check  →  commit

- **Write the test before the code, and prove it red for the right reason.** Mutate
  the fix away and watch that exact test fail. A test never seen red proves nothing —
  it is the only check that catches a test which passes for the wrong reason.
- A test must encode WHY the behaviour matters, not just what it does.
- One commit per coherent change, explicit paths, `make check` green **per commit**.
- Touches the DB? `make check` is not proof. Say so, and run `make test-bench`.
- **What to work on next comes from Zafar.** `docs/backlog.md` is an archive of
  findings already measured (file:line, reproduction) — read it when it is relevant,
  do not treat it as a queue to burn down.
