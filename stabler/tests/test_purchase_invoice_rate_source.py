"""The Purchase Invoice form's exchange-rate wiring — read out of the source.

What is protected: the form must decide whether to re-fetch the rate through
`planRateRefresh()` in `composables/purchaseInvoiceRate.js`, and must not carry
a second copy of that policy in its own branches.

Why that matters, measured: the form fetched the rate for the new posting date
and then applied it only to an empty field —

    if (!Number(form.value.conversion_rate)) form.value.conversion_rate = ...

so backdating an invoice that already had a rate fetched the right rate for the
new date and discarded it. The invoice kept the rate of a date it no longer had.
On msa.erpstable.com 675 submitted purchase invoices carry a rate that is not
the Central Bank rate for their own posting date — 363 at rate 0 and 312 at a
hardcoded 12 800 — hundreds of billions of so'm of error in the UZS ledger.

Both halves are load-bearing, and the second is the one that bites back: a form
that refreshes unconditionally wipes the contract rate the user typed on
purpose, and rewrites the rate a saved draft was stored with the moment it is
opened. `purchaseInvoiceRate.spec.js` covers the decision itself; this file
covers the wiring that must keep reaching it.

A Vue component cannot be mounted (@vue/test-utils is not a dependency here), so
the test reads the source. That is weak verification, but what it guards is a
small set of structural facts, and the edit that breaks any of them changes
exactly this text.
"""

import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "pages" / "purchasing" / "PurchaseInvoiceForm.vue"
COMPOSABLE = Path(__file__).parents[1] / "public" / "js" / "composables" / "purchaseInvoiceRate.js"


class TestPurchaseInvoiceRateWiring(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")
		cls.composable = COMPOSABLE.read_text(encoding="utf-8")

	def test_the_test_reads_the_form(self):
		"""Anchor: if the path drifts, every assertion below verifies empty text."""
		self.assertIn("get_purchase_exchange_rate", self.body)
		self.assertIn("export function planRateRefresh", self.composable)

	def test_the_watcher_asks_the_planner_instead_of_deciding_for_itself(self):
		"""The date/currency watcher must route through `planRateRefresh` — that
		is what puts the decision somewhere `make test-js` can reach it. A
		watcher that calls `fetchRateHint()` directly has taken the policy back
		into the component, where the last version of it went unnoticed for
		675 invoices."""
		self.assertIn("planRateRefresh", self.body)
		self.assertIn('from "../../composables/purchaseInvoiceRate.js"', self.body)
		self.assertIn("if (plan.refresh) fetchRateHint();", self.body)

	def test_the_empty_field_guard_is_gone(self):
		"""The whole defect in one line. `!Number(conversion_rate)` means "apply
		the new date's rate only if there is no rate yet", i.e. never, on any
		invoice that already has one."""
		self.assertNotIn("if (!Number(form.value.conversion_rate))", self.body)

	def test_a_typed_rate_is_marked_and_survives(self):
		"""A rate the user typed is a decision — the contract's rate, the bank's
		rate. The input must mark it, and the fetch must honour the mark;
		dropping either end silently re-arms the overwrite."""
		self.assertIn('@update:model-value="onRateTyped"', self.body)
		self.assertIn("rateSeen.rateTouched = true", self.body)
		self.assertIn("if (!rateSeen.rateTouched) form.value.conversion_rate", self.body)

	def test_the_planner_is_told_which_document_is_on_screen(self):
		"""How an install is told apart from an edit. Without `docName`, loading
		a saved draft looks exactly like the user moving the date, and the form
		would rewrite the rate the draft was saved with before the user had
		touched anything."""
		self.assertIn("docName: docName.value", self.body)
		self.assertIn("editable: editable.value", self.body)
		self.assertIn("isForeign: isForeign.value", self.body)


if __name__ == "__main__":
	unittest.main()
