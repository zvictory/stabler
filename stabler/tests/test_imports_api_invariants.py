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
	supplier, or it is already superseded by a *different* CI -- so the CI saved,
	the link never happened, and the UI still reported success. The throw must
	propagate so Frappe rolls the request back.
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


if __name__ == "__main__":
	unittest.main()
