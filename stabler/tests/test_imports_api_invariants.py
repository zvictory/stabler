"""Source-level guard tests for the imports API accounting invariants (WP-I8/I9).

These are Frappe-free: they assert structural properties of the API source that
protect money-correctness, so a refactor that silently drops a guard fails CI.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_imports_api_invariants -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_API = os.path.normpath(os.path.join(_HERE, "..", "api"))


def _read(name: str) -> str:
	with open(os.path.join(_API, name), encoding="utf-8") as f:
		return f.read()


def _func_body(src: str, name: str) -> str:
	"""Extract a top-level function body (up to the next top-level def/decorator)."""
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestConvertGuards(unittest.TestCase):
	"""convert_ci_to_purchase_invoice (WP-I5) money-safety guards."""

	def setUp(self):
		self.body = _func_body(_read("imports.py"), "convert_ci_to_purchase_invoice")

	def test_row_lock_serializes_concurrent_converts(self):
		# WP-I9: the write path must lock the CI row so two simultaneous
		# Confirms cannot both pass the duplicate check.
		self.assertIn("for_update=True", self.body)
		# The lock is conditional on the write path (previews stay lock-free).
		self.assertIn("if not cint(dry_run):", self.body)

	def test_lock_before_duplicate_check(self):
		# Order matters: lock first, then look for an existing Purchase Invoice.
		self.assertLess(
			self.body.index("for_update=True"),
			self.body.index('"custom_commercial_invoice": commercial_invoice'),
		)

	def test_dry_run_defaults_on(self):
		# Preview-by-default: calling without dry_run must never write.
		self.assertIn("dry_run: int = 1", self.body)

	def test_drift_rolls_back(self):
		# If ERPNext's recompute drifts from agreed_total, the invoice must be
		# rolled back — never post a silently wrong A/P.
		self.assertIn("frappe.db.rollback()", self.body)
		self.assertIn("agreed", self.body)

	def test_never_submits_the_invoice(self):
		# The draft is for Accounts to review; this endpoint must not submit.
		self.assertNotIn(".submit()", self.body)
		self.assertNotIn("docstatus = 1", self.body)

	def test_gated_and_cost_visible(self):
		self.assertIn("_assert_imports_access(company)", self.body)
		self.assertIn("_assert_cost_visible()", self.body)


class TestExposureExclusion(unittest.TestCase):
	"""supplier_import_exposure (WP-I4/I5) no-double-count wiring."""

	def setUp(self):
		self.body = _func_body(_read("purchasing.py"), "supplier_import_exposure")

	def test_converted_ci_flagged(self):
		# The CI query must mark rows that already have a Purchase Invoice …
		self.assertIn("has_purchase_invoice", self.body)
		self.assertIn("custom_commercial_invoice", self.body)

	def test_commitments_exclude_converted(self):
		# … and the commitments list must exclude them (the money is in A/P now).
		self.assertIn('not r.get("has_purchase_invoice")', self.body)

	def test_column_guarded_for_pre_v46_tenants(self):
		# EXISTS() must be guarded on the v46 column so pre-migration tenants
		# don't crash.
		self.assertIn("has_column", self.body)

	def test_tenant_gated(self):
		self.assertIn('module_map_for(company).get("imports")', self.body)
		self.assertIn('{"enabled": False}', self.body)


class TestDocsPriceNeverInGL(unittest.TestCase):
	"""docs_total is customs-only — it must never feed the Purchase Invoice."""

	def test_convert_never_uses_docs_total_for_amounts(self):
		body = _func_body(_read("imports.py"), "convert_ci_to_purchase_invoice")
		# docs_total may be REPORTED (transparency) but never assigned into the
		# invoice: no line rate/amount or doc field derives from it.
		for pat in (
			r"rate.*docs_total",
			r"docs_total.*rate",
			r"doc\.[a-z_]+\s*=\s*.*docs_total",
			r"amount.*=.*docs_total",
		):
			self.assertIsNone(re.search(pat, body), f"docs_total leaks into the invoice via /{pat}/")


class TestProformaLinkFailsLoud(unittest.TestCase):
	"""Saving a CI must never silently drop the PI -> CI supersede.

	Both endpoints used to call link_proforma_to_ci inside a bare
	`try: ... except Exception: pass`. Every failure reachable from there is a
	validation error the user has to see -- the PI belongs to another company or
	supplier, or it is already superseded with nothing left to ship -- so the CI
	saved, the link never happened, and the UI still reported success. The throw
	must propagate so Frappe rolls the request back.
	"""

	def setUp(self):
		self.src = _read("imports.py")

	def test_neither_ci_endpoint_swallows_the_link_error(self):
		for name in ("create_commercial_invoice", "update_commercial_invoice"):
			body = _func_body(self.src, name)
			self.assertIn("_link_proforma_if_set(doc, company)", body)
			self.assertNotIn("except Exception", body)

	def test_helper_propagates_and_stays_idempotent(self):
		body = _func_body(self.src, "_link_proforma_if_set")
		self.assertIn("link_proforma_to_ci(proforma, doc.name, company)", body)
		self.assertNotIn("except Exception", body)
		# A PI that already points at this CI is skipped. `save_proforma` accepts
		# a `status`, so a linked PI can later become CANCELLED; without the skip
		# can_supersede() would reject every subsequent CI edit forever.
		self.assertIn('frappe.db.get_value("Proforma Invoice", proforma, "commercial_invoice")', body)

	def test_a_further_container_skips_the_link_instead_of_throwing(self):
		# One PI ships in several CIs (HMA/PI/190/2026-27 carries three). The
		# supersede link is 1:1 and names the first of them, so the second CI must
		# skip it -- refusing was what threw 417 on a PI with 4 266 boxes still open.
		body = _func_body(self.src, "_link_proforma_if_set")
		self.assertIn("_proforma.accepts_another_ci(status, open_balance)", body)
		self.assertIn("_proforma_has_open_balance(", body)

	def test_the_balance_ignores_the_ci_being_saved(self):
		# The CI is already inserted when the helper runs. Counting it would make
		# the container that consumes the last boxes look like it had none to take,
		# and the picker -- which passes the same exclude_ci -- had just offered them.
		body = _func_body(self.src, "_proforma_has_open_balance")
		self.assertIn("exclude_ci=exclude_ci", body)
		self.assertIn("selected_pis=[proforma]", body)
		# Same (PI, category) arithmetic as the picker, not a second match key.
		self.assertIn("get_vendor_available_pi_lines(", body)
		self.assertIn('flt(line.get("remaining_boxes")) > 0', body)


class TestRowLevelProformaIsPersisted(unittest.TestCase):
	"""A CI row must record the PI its boxes were actually allocated from.

	_shipped_pi (_imports_rules.py) and _ci_item_effective_pi_expr both read a
	two-level link -- the row wins, the header answers for rows that carry none --
	but the write path never assigned the row half, so it was always NULL.
	Measured on prod (msa, 2026-08-07): all 4 items of CI-2026-04379 had no PI of
	their own, which is why unlinking the header would have erased 4 134 shipped
	boxes from the arithmetic with nothing to fall back on.
	"""

	def setUp(self):
		self.src = _read("imports.py")

	def test_the_item_loop_writes_the_row_link(self):
		body = _func_body(self.src, "_apply_ci_payload")
		self.assertIn('line.custom_proforma_invoice = row["custom_proforma_invoice"]', body)
		# _clean_ci_items has carried the value all along; only the assignment was missing.
		self.assertIn('"custom_proforma_invoice": row.get("custom_proforma_invoice") or None', self.src)

	def test_a_row_pi_is_checked_against_this_ci_supplier(self):
		# The header link is validated by link_proforma_to_ci. The row link wins over
		# it in the same arithmetic and used to reach the DB completely unchecked.
		self.assertIn(
			"_assert_row_proformas(cleaned, doc.supplier, company)", _func_body(self.src, "_apply_ci_payload")
		)
		guard = _func_body(self.src, "_assert_row_proformas")
		self.assertIn('"company": company, "supplier": supplier', guard)
		self.assertIn("frappe.throw(", guard)

	def test_the_reader_hands_back_the_row_link_alone(self):
		# get_commercial_invoice used to coalesce the header into every row. The form
		# posts those rows straight back, so an old CI opened and saved would have
		# pinned all of its lines to whatever the header named that day.
		body = _func_body(self.src, "get_commercial_invoice")
		self.assertIn('"custom_proforma_invoice": it.get("custom_proforma_invoice"),', body)
		self.assertNotIn('or doc.get("custom_proforma_invoice")', body)


class TestAdvanceIsPostedNotDrafted(unittest.TestCase):
	"""An advance must be submitted, and its guard must run early enough to speak.

	Two regressions live here, both invisible to a compiler:

	1. A draft Payment Entry contributes `advance_in = 0` to
	   `build_pi_advance_ledger`, so every PI advance ledger read
	   `advance_available = 0` however much money had been entered.
	2. `_assert_advance_postable` used to run *after* `insert()`. `paid_from` /
	   `paid_to` are `reqd` on the Payment Entry doctype and both exchange rates
	   go through ERPNext's `validate_mandatory`, so insert() pre-empted all three
	   branches with a generic "<Field> is mandatory" — the guard was decorative.
	   Moving it earlier only works because the caller now runs the same three
	   `validate()` steps by hand first; without `set_exchange_rate()` the rate
	   branch would fire on every single advance instead.

	Ordering is the whole fix, so it is asserted as ordering, not as presence.
	"""

	def setUp(self):
		self.body = _func_body(_read("imports.py"), "create_advance_payment")

	def test_the_entry_is_submitted(self):
		self.assertIn("pe.submit()", self.body)

	def test_the_guard_runs_before_insert(self):
		self.assertLess(
			self.body.index("_assert_advance_postable(pe, company=company, stream=stream)"),
			self.body.index("pe.insert("),
		)

	def test_the_exchange_rate_is_resolved_before_the_guard_reads_it(self):
		self.assertLess(
			self.body.index("pe.set_exchange_rate()"),
			self.body.index("_assert_advance_postable(pe, company=company, stream=stream)"),
		)
		# set_exchange_rate() needs the account currencies set_missing_values() fills in.
		self.assertLess(self.body.index("pe.set_missing_values()"), self.body.index("pe.set_exchange_rate()"))

	def test_the_reported_docstatus_is_read_after_submit(self):
		# The SPA trusts `docstatus` from the response; capturing it before submit()
		# would report 0 for a perfectly posted entry.
		self.assertLess(self.body.index("pe.submit()"), self.body.index('"docstatus": pe.docstatus'))


if __name__ == "__main__":
	unittest.main()
