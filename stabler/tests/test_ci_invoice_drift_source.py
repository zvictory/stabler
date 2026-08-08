"""Structural guards for the CI ↔ booked-invoice drift report.

The rule the owner set: the CI's AGREED price is the basis, docs price never
reaches the GL, and when the CI changes after booking the difference must be
visible — but repairing it (cancel + re-book) is an explicit human action, not
something a screen does on load.
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
API = os.path.join(_ROOT, "api", "imports.py")
CONV = os.path.join(_ROOT, "api", "_ci_to_pinv.py")
FORM = os.path.join(_ROOT, "public", "js", "pages", "imports", "CommercialInvoiceForm.vue")
FLOW = os.path.join(_ROOT, "public", "js", "pages", "imports", "ImportsFlow.vue")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class AgreedPriceIsTheBasisTest(unittest.TestCase):
	"""The owner's standing rule, pinned where it is actually enforced."""

	def setUp(self):
		self.src = read(API)
		self.convert = body(self.src, "convert_ci_to_purchase_invoice")

	def test_invoice_is_anchored_on_agreed_total(self):
		self.assertIn("agreed = flt(ci.agreed_total)", self.convert)
		self.assertIn("_ci_to_pinv.reconciles(flt(doc.grand_total), agreed)", self.convert)

	def test_a_drifting_invoice_is_rolled_back_never_posted(self):
		# An A/P that silently disagrees with the agreed figure is worse than
		# no A/P at all.
		self.assertIn("frappe.db.rollback()", self.convert)

	def test_docs_price_never_enters_the_invoice(self):
		# docs_total is a customs figure; it is reported, never booked.
		self.assertIn("docs_total_excluded", self.convert)
		lines = body(read(CONV), "pinv_lines_from_ci_items")
		self.assertNotIn("docs_price", lines)
		self.assertNotIn("docs_amount", lines)

	def test_advances_are_allocated_against_the_agreed_figure(self):
		self.assertIn("plan_advance_allocation(agreed", self.convert)


class DriftEndpointTest(unittest.TestCase):
	def setUp(self):
		self.src = read(API)
		self.body = body(self.src, "_ci_invoice_drift")

	def test_whitelisted_and_gated(self):
		self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef ci_invoice_drift\(")
		gate = body(self.src, "ci_invoice_drift")
		self.assertIn("_assert_imports_access(company)", gate)
		self.assertIn("_assert_cost_visible()", gate)

	def test_reports_only_never_repairs(self):
		# Re-booking cancels GL vouchers and un-allocates payments. A report
		# must never do that as a side effect of being opened.
		for token in (".save(", ".insert(", ".submit(", ".cancel(", "db_set(", "db.set_value("):
			with self.subTest(token=token):
				self.assertNotIn(token, self.body)

	def test_delegates_to_the_shared_rule(self):
		self.assertIn("_ci_to_pinv.invoice_drift(", self.body)

	def test_batched_never_per_invoice(self):
		# Four queries total (invoices, CIs, CI lines, PInv lines) — none of
		# them inside the per-invoice loop. Anchored on the LAST such loop: the
		# supplier-scope filter walks the same list earlier, and it is the drift
		# loop (after the batched line queries) this guards.
		loop = self.body[self.body.rindex("for inv in invoices:") :]
		self.assertNotIn("frappe.get_all(", loop)
		self.assertNotIn("frappe.db.", loop)

	def test_pre_v46_sites_degrade_instead_of_crashing(self):
		gate = body(self.src, "ci_invoice_drift")
		self.assertIn('has_column("Purchase Invoice", "custom_commercial_invoice")', gate)
		self.assertIn('"available": False', gate)

	def test_board_reuses_the_same_rule(self):
		flow = body(self.src, "imports_flow")
		self.assertIn("_ci_invoice_drift(company)", flow)


class RebookTest(unittest.TestCase):
	"""Cancelling a GL voucher and re-booking it is the most destructive thing
	the imports module can do. Every guard around it is pinned here."""

	def setUp(self):
		self.src = read(API)
		self.body = body(self.src, "rebook_ci_invoice")

	def test_whitelisted_and_gated(self):
		self.assertRegex(self.src, r"@frappe\.whitelist\(\)\ndef rebook_ci_invoice\(")
		self.assertIn("_assert_imports_access(company)", self.body)
		self.assertIn("_assert_cost_visible()", self.body)
		self.assertIn('_assert_can_write("Purchase Invoice", old_name, "cancel")', self.body)

	def test_defaults_to_dry_run(self):
		self.assertRegex(self.src, r"def rebook_ci_invoice\([^)]*dry_run: int = 1")

	def test_dry_run_returns_before_any_write(self):
		plan_return = self.body.index("if cint(dry_run):")
		first_write = min(
			(
				self.body.index(tok)
				for tok in ("old.cancel()", "doc.insert(", "doc.submit()")
				if tok in self.body
			),
			default=len(self.body),
		)
		self.assertLess(plan_return, first_write, "dry_run must short-circuit before any mutation")

	def test_refuses_instead_of_guessing(self):
		# Each blocker is a named reason, not a silent best-effort.
		self.assertIn("blockers", self.body)
		self.assertIn("does not match agreed_total", self.body)
		self.assertIn("has no date", self.body)
		self.assertIn("unlink_payment_on_cancellation_of_invoice", self.body)
		self.assertIn("if blockers:", self.body)

	def test_the_replacement_is_anchored_on_agreed_and_rolled_back_otherwise(self):
		self.assertIn("_ci_to_pinv.reconciles(flt(doc.grand_total), agreed)", self.body)
		self.assertIn("frappe.db.rollback()", self.body)

	def test_replacement_keeps_the_audit_trail_and_the_real_date(self):
		self.assertIn("doc.amended_from = old_name", self.body)
		self.assertIn("doc.posting_date = getdate(ci.ci_date)", self.body)

	def test_loosened_payments_are_carried_over(self):
		# Cancelling frees the payments that were allocated; they must land on
		# the replacement or the supplier balance jumps.
		self.assertIn("_allocated_payments(old_name)", self.body)
		self.assertIn("payments_to_reallocate", self.body)
		self.assertIn("_restrict_advances_to_import(doc, wanted)", self.body)

	def test_never_leaves_the_ledger_without_the_payable_it_had(self):
		self.assertIn('if plan["old_submitted"]:', self.body)
		self.assertIn("doc.submit()", self.body)

	def test_serialises_against_a_concurrent_convert(self):
		self.assertIn("for_update=True", self.body)

	def test_in_sync_is_a_no_op(self):
		self.assertIn('"reason": "in_sync"', self.body)

	def test_ui_asks_before_it_acts(self):
		vue = read(FORM)
		# Scope to the re-book handler: the form has other confirms (status
		# changes), and a global index() would compare unrelated call sites.
		start = vue.index("async function rebookInvoice(")
		fn = vue[start : vue.index("\nonMounted(", start)]
		self.assertIn("dry_run: 1", fn)
		self.assertIn("dry_run: 0", fn)
		# The plan must be fetched and confirmed BEFORE the acting call.
		self.assertLess(fn.index("dry_run: 1"), fn.index("await confirm("))
		self.assertLess(fn.index("await confirm("), fn.index("dry_run: 0"))
		self.assertIn("danger: true", fn)


class SurfaceTest(unittest.TestCase):
	def test_ci_form_warns_and_links_to_the_booked_invoice(self):
		vue = read(FORM)
		self.assertIn('call("stabler.api.imports.ci_invoice_drift"', vue)
		self.assertIn("drift.delta_total", vue)
		self.assertIn("purchasing-invoice", vue)
		self.assertNotIn('"/app', vue)

	def test_form_never_blocks_on_the_diagnostic(self):
		# A failing drift check must not stop the invoice from opening.
		vue = read(FORM)
		self.assertRegex(vue, r"catch\s*\{\s*\n\s*drift\.value = null;")

	def test_flow_board_surfaces_the_count(self):
		flow = read(FLOW)
		self.assertIn("invoice_drift", flow)
		self.assertNotIn("<table", flow)  # the board stays graphics-only


if __name__ == "__main__":
	unittest.main()
