---
description: Stabler backend invariants — patches, migrations, idempotency, and how to actually verify a DDL landed.
paths:
  - "**/*.py"
  - "**/patches.txt"
  - "**/doctype/**/*.json"
---

# Migrations / patches

Moved verbatim out of CLAUDE.md on 2026-08-15.
Original: `docs/archive/CLAUDE.md.2026-08-15.bak`.

- `patches.txt` has **NO `[post_model_sync]` marker** → every patch runs BEFORE
  the doctype DDL sync. A patch that reads or writes a **new** column/field must
  guard with `frappe.db.has_column(...)` (or be placed under a `[post_model_sync]`
  line), otherwise migrate aborts on "unknown column".
- A new module's enable-default at go-live comes from the **doctype field
  `default`** (e.g. `enable_*` Check = `"1"`), NOT from a backfill patch — the
  backfill skips when it runs pre-sync. Set the field default to the intended state.
- Every patch must be **idempotent**: guard with `frappe.db.exists` /
  `has_column` / `db.exists("Custom Field", …)` so re-running is safe.
- **Verifying a DDL landed: `has_column` alone lies on sites without the app.**
  `frappe.db.has_column("<DT>", …)` raises `TableMissingError` — it does not return
  `False` — when the doctype's table does not exist at all. So "run has_column on
  every site; anything not `True` means migrate was skipped" reports a failure on
  every tenant that simply lacks the optional app. Measured 2026-08-01: `crm` is
  installed on 4 of the 7 stabler sites, so a v66 `CRM Deal` probe threw on dts,
  horeca and msa — where the patch had correctly guarded itself and skipped.
  Probe the table first, and read a missing table as *not applicable*, not as a
  failed migrate:
  `bench --site <s> execute frappe.db.table_exists --args '["<DT>"]'` → if `False`,
  the site does not carry that doctype and there is nothing to verify; only when
  it is `True` does `has_column` returning `False` mean the migrate really was missed.

## Verification note

`make check` does **not** run the bench-dependent test modules — everything
`.github/frappe-free-tests.txt` does not name (`make test-bench`,
slow, needs a live MariaDB/Redis). If the change touches DB-dependent code, `make check`
green is not sufficient proof — say so and request `make test-bench`.
