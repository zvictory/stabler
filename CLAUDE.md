# Stabler SPA — Project Rules

**This file is the repository constitution.** On conflict, this file wins.
`AGENTS.md` and `project-rules.md` are subsets and carry no independent authority.

Domain rules are **not** in this file. They load automatically when you touch the
matching files, or on demand as skills. Do not restate them here — every line in
this file is paid for in every session.

| Where the rules live | Loads when |
|---|---|
| `.claude/rules/00-context-budget.md` | always — session protocol |
| `.claude/rules/10-frontend.md` | you touch `*.vue`, `*.js`, `public/`, `www/` |
| `.claude/rules/20-backend-migrations.md` | you touch `*.py`, `patches.txt`, doctype JSON |
| `.claude/rules/30-tenant-modules.md` | you touch routes, APIs, doctypes, patches |
| `.claude/skills/stabler-deploy/` | you deploy, or work "disappeared" |
| `.claude/skills/stabler-i18n/` | you add or land user-facing strings |
| `.claude/skills/stabler-orchestrator/` | you delegate implementation to `agy` |

## Hard rules (never violate)

### Verification — Definition of Done
- `make check` = `lint-changed lint-js-changed compile guards test test-js` — the push gate.
- `make test` = the 84 frappe-free unit modules (fast; no bench, no DB).
- `make test-bench` = the other 15 modules — **not part of `check`**; needs a live bench.
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
- Five languages ship: **en, ru, uz, uzc, tr**. Full workflow: `stabler-i18n` skill.

### Production
- **Production deploy always requires explicit approval from Zafar** — one
  `bench restart` blips all seven tenants. Never infer approval.
- Deploy only from a clean tree.
- Procedure, prod topology, rollback and smoke checks: `stabler-deploy` skill.

### Delegation
- Implementation delegated to Antigravity (`agy`) follows one canonical workflow:
  `.claude/skills/stabler-orchestrator/SKILL.md` (what Claude executes) and
  `docs/runbooks/claude-antigravity-orchestration.md` (the human-facing runbook).
- `agy` works only inside `.worktrees/agy-<bead-id>` on a feature branch, leaves its
  changes uncommitted, and **never** merges, pushes, deploys, touches production or
  closes the parent bead. Claude reviews the full diff independently before accepting it.
- Pre-merge review: the read-only `stabler-diff-reviewer` agent (`.claude/agents/`).

## Work queue
Single source of truth: **beads (`bd`)**. No markdown TODO lists.

    bd ready  →  /mt <id>  →  make check  →  /mt-done <id>  →  /clear

One micro-task per session. See `.claude/rules/00-context-budget.md`.
