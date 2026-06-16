# Stabler test suite

Two layers, by design:

| Layer | Files | Needs a bench? | Run with |
|---|---|---|---|
| **Pure unit** | `test_approval_rules.py`, `test_money_helpers.py`, `test_*_helpers.py` | No — they import frappe-free helpers and pass fakes | `python -m unittest stabler.tests.test_approval_rules` |
| **Integration** | `test_approvals_integration.py`, `test_compliance.py`, `test_concurrency.py` | Yes — real site + DB | `bench --site <site> run-tests --app stabler` |

The split is deliberate: the rules that money-movement safety depends on
(when approval is required, segregation of duties, audit-diff parsing) live in
`stabler/api/_approval_rules.py`, which imports nothing from Frappe. That makes
them testable in milliseconds with no database, and it keeps the decision logic
separate from the I/O.

## Run everything locally

```bash
# Fast layer (no bench needed), from the app root:
python -m unittest stabler.tests.test_approval_rules -v

# Full suite (from the bench root):
bench --site <your-test-site> set-config allow_tests true
bench --site <your-test-site> run-tests --app stabler

# A single module:
bench --site <your-test-site> run-tests --app stabler \
  --module stabler.tests.test_approvals_integration
```

## What the approval tests cover

- **`test_approval_rules.py`** (pure): threshold semantics (disabled / zero =
  every doc / inclusive boundary / string coercion / garbage input), self-approval
  detection, and Version-diff parsing (submit vs cancel vs edit, noise dropping,
  child-row counting).
- **`test_approvals_integration.py`** (bench): the end-to-end maker-checker flow —
  a maker cannot self-submit, a maker cannot approve their own request, a second
  approver can approve-and-post, a `ignore_approval_gate`-flagged system doc
  bypasses the gate, and a rejected request leaves the draft untouched.
  These **skip** (don't fail) on a bare site with no Company/account fixtures.

## CI

`.github/workflows/ci.yml`:

- **lint-and-unit** — ruff lint + format check, byte-compile, and the pure unit
  tests. Fast; treat as a required gate on every PR.
- **bench-tests** — provisions MariaDB + Redis, a throwaway Frappe site, installs
  ERPNext + stabler, runs `bench run-tests`, and builds the frontend.

## Adding tests

- New **pure** logic → put the decision function in a frappe-free module and add
  cases to a `test_*_rules.py` / `test_*_helpers.py`. Register the module in the
  CI `lint-and-unit` step so it runs without a bench.
- New **flows** that touch the DB → add a `FrappeTestCase` in a
  `test_*_integration.py`. Guard on missing fixtures with `self.skipTest(...)`.
