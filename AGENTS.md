# Stabler SPA — Project Rules

## Hard rules (never violate)

### No Frappe Desk redirects, ever
- The Vue 3 SPA at `/stabler/#/...` must NEVER link out to the Frappe
  Desk (`/app/...`) — not via `<a href>`, not via `window.open`, not via
  router meta. Stabler is a fully self-contained UX; sending users to the
  Desk breaks that promise.
- If a CRUD action is missing in Stabler, build it inside Stabler. Do not
  paper over the gap with an "Open in Desk" link.
- Applies to: customers, suppliers, items, employees, accounts, invoices,
  payments — every doctype surfaced in the SPA.

### Striped tables
- Global rule shipped from `stabler/public/css/stabler.css` makes every
  `<table>` striped by default. Do NOT add `class="table-striped"`
  manually — it's already on. To opt out for a specific table, use
  `class="table-no-stripe"`.

### Money fields
- Every numeric monetary input MUST use the shared MoneyInput component.
  Never use bare `<input type="number">` for amounts, rates, or balances.

### Tables / lists
- Lists of records use `.table` (or list-group) — striped by default.
- Currency cells use `font-monospace` for alignment.

### Language & Translation Discipline (English-First Implementation)
- **Prototypes and Design**: Mockups, design drafts (e.g. `docs/uat/...`), requirements, and discussions may be in Turkish or English.
- **English-First Code**: All production code, Vue components, Python backend endpoints, error messages, docstrings, UI labels, and `t("...")` translation keys MUST be English-first. Never use Turkish or other non-English literals as canonical code identifiers or `t()` source keys.
- **Translation Timing**:
  1. During active development, update only `en.csv` if needed so that English unit tests and feature tests stay green. Do NOT spend time translating into `tr`, `ru`, `uz`, `uzc` while code and UI are still iterating.
  2. Once feature implementation and test logic are complete and passing, backfill the translations for the other 4 language catalogs (`tr.csv`, `ru.csv`, `uz.csv`, `uzc.csv`) before final `make check` and `git push`.

## Where the full rules live

- This file is a **subset**. The authoritative rule set — date fields, module gating,
  tenant ownership, button hierarchy, currency display, migrations, commit hygiene,
  deployment — is `CLAUDE.md`. Read it before changing code.
- Agent orchestration (Claude ⇄ Antigravity): `docs/runbooks/claude-antigravity-orchestration.md`.
- Branch, ownership and merge protocol: `docs/runbooks/parallel-development.md`.
- ⚠️ **This repository does not rebase.** CRLF translation CSVs re-conflict on every
  commit (23 consecutive, measured). Use `git fetch origin && git merge origin/main`,
  and `git merge --no-ff` to integrate into `main`.

## How work is done

Test first. There is no issue tracker — `bd` (beads) and the `/mt` micro-task
commands were removed on 2026-08-18. No markdown TODO lists either.

    failing test  →  code  →  make check  →  commit

- Write the failing test BEFORE the code, and prove it is red for the right reason
  by mutating the fix away. A test never seen red proves nothing.
- `make check` green per commit. Touches the DB? Also `make test-bench`.
- `docs/backlog.md` archives findings already measured — an archive, not a queue.
  What to work on next comes from Zafar.

## Landing the plane

Work is NOT complete until `git push` succeeds. A merge that is not pushed means
the work does not exist.

```bash
git fetch origin && git merge origin/main     # merge, NEVER rebase
make check                                    # green after the merge
git checkout main && git merge --no-ff <branch>
git push origin main
git rev-parse main origin/main                # must match
git status --porcelain                        # must be empty
```

Never stop before pushing, and never hand back a "ready to push when you are" —
if the push fails, resolve it and retry.
