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

<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs via Dolt:

- Each write auto-commits to Dolt history
- Use `bd dolt push`/`bd dolt pull` for remote sync
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->
