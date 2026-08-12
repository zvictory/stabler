"""Cancelling a Purchase Invoice must give the PI advance back.

The PI Advance Ledger promises that an advance consumed by a Purchase Invoice
becomes re-allocatable the moment that invoice is cancelled. Stabler ships **no
code** for this — no `on_cancel` hook, no restore routine. The promise rests
entirely on ERPNext's native unlink path, and that path is switched by a single
site setting:

    Accounts Settings.unlink_payment_on_cancellation_of_invoice

With the flag on, `AccountsController.on_cancel` calls
`unlink_ref_doc_from_payment_entries`, which zeroes the reference row, re-runs
`set_amounts()` and writes `unallocated_amount` back to the Payment Entry. With
the flag off nothing at all happens: the invoice cancels, the ledger keeps
showing the advance as spent, and the money is stranded with no error anywhere.
That is a silent failure of a money feature, so the flag is asserted here rather
than skipped over — a future site that flips it must break loudly in CI, not in
production.

Deliberately NOT asserted: that the `Purchase Invoice Advance` child rows are
deleted. ERPNext's `remove_ref_from_advance_section` is called from the cancel
path with `payment_name=None`, so its `adv.reference_name == payment_name`
comparison never matches and the rows survive. Stabler is insulated because
`_ci_vendor_settlement` filters `docstatus < 2`; asserting on the child rows
would paint an upstream quirk as our regression.

Fixtures are built by the test on whatever Company the site carries and rolled
back in `tearDown`; `frappe.db.commit()` is never called. When the accounting
defaults of a bare site cannot produce a submittable invoice the tests skip with
the reason instead of failing.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, today

from stabler.api._ci_to_pinv import plan_advance_allocation

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


# One PI worth 300k with 30% advance terms — the cap the ledger enforces is 90k.
CI_AMOUNT = 300_000.0
ADVANCE_PCT = 30.0
ADVANCE_AMOUNT = 90_000.0


def _account(company: str, currency: str, **filters) -> str | None:
	return frappe.db.get_value(
		"Account",
		dict(company=company, is_group=0, disabled=0, account_currency=currency, **filters),
		"name",
	)


class PiAdvanceCancelRestoreTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.currency = (
			frappe.db.get_value("Company", cls.company, "default_currency") if cls.company else None
		)

	def setUp(self):
		if not (self.company and self.currency):
			self.skipTest("no Company fixture available")
		if not frappe.db.exists("DocType", "Proforma Invoice"):
			self.skipTest("Proforma Invoice doctype not present")
		self.bank = _account(self.company, self.currency, account_type="Bank") or _account(
			self.company, self.currency, account_type="Cash"
		)
		self.payable = _account(self.company, self.currency, account_type="Payable")
		self.expense = frappe.db.get_value(
			"Account",
			{"company": self.company, "root_type": "Expense", "is_group": 0, "disabled": 0},
			"name",
		)
		self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")
		if not (self.bank and self.payable and self.expense):
			self.skipTest("company has no bank / payable / expense account to post against")

	def tearDown(self):
		frappe.db.rollback()

	# --- fixtures -----------------------------------------------------------

	def _supplier(self) -> str:
		"""A brand-new supplier, so the only advance in play is the one we create."""
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "PiAdv_" + frappe.generate_hash(length=8),
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _item(self) -> str:
		"""Non-stock: a stock item would drag warehouse and perpetual-inventory setup in."""
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "PiAdvSvc_" + frappe.generate_hash(length=8),
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": frappe.db.get_value("UOM", {}, "name"),
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _proforma_invoice(self, supplier: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Proforma Invoice",
					"company": self.company,
					"supplier": supplier,
					"supplier_pi_ref": "PI-ADV-" + frappe.generate_hash(length=8),
					"pi_date": today(),
					"currency": self.currency,
					"agreed_total": CI_AMOUNT,
					"advance_pct": ADVANCE_PCT,
					"status": "CONFIRMED",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _advance_payment(self, supplier: str, pi: str, amount: float) -> str:
		"""A submitted Pay entry with no references — i.e. a pure advance."""
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Pay"
		pe.company = self.company
		pe.posting_date = today()
		pe.party_type = "Supplier"
		pe.party = supplier
		pe.paid_from = self.bank
		pe.paid_to = self.payable
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.source_exchange_rate = 1.0
		pe.target_exchange_rate = 1.0
		pe.reference_no = "ADV-" + frappe.generate_hash(length=6)
		pe.reference_date = today()
		if frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
			pe.custom_proforma_invoice = pi
		try:
			pe.insert(ignore_permissions=True)
			pe.submit()
		except Exception as exc:  # accounting defaults vary per site
			self.skipTest(f"advance Payment Entry could not be submitted: {exc}")
		return pe.name

	def _purchase_invoice(self, supplier: str, item: str, total: float):
		pinv = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"posting_date": today(),
				"due_date": today(),
				"currency": self.currency,
				"conversion_rate": 1.0,
				"credit_to": self.payable,
				"items": [
					{
						"item_code": item,
						"qty": 1,
						"rate": total,
						"expense_account": self.expense,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		try:
			pinv.insert(ignore_permissions=True)
		except Exception as exc:
			self.skipTest(f"Purchase Invoice fixture could not be built: {exc}")
		return pinv

	def _unallocated(self, pe: str) -> float:
		return flt(frappe.db.get_value("Payment Entry", pe, "unallocated_amount"))

	def _plan_from_db(self, pe: str, pi: str, invoice_total: float) -> dict:
		"""Feed the planner exactly what the endpoint feeds it: live DB numbers."""
		return plan_advance_allocation(
			invoice_total,
			[
				{
					"name": pe,
					"unallocated_amount": self._unallocated(pe),
					"proforma_invoice": pi,
					"ci_amount": CI_AMOUNT,
					"advance_percentage": ADVANCE_PCT,
				}
			],
		)

	# --- tests --------------------------------------------------------------

	def test_unlink_on_cancel_must_be_enabled(self):
		"""The whole restore is this one flag. Off = advances stranded, silently."""
		self.assertTrue(
			frappe.db.get_single_value("Accounts Settings", "unlink_payment_on_cancellation_of_invoice"),
			"Accounts Settings.unlink_payment_on_cancellation_of_invoice is OFF: cancelling a "
			"Purchase Invoice will NOT return the advance, and the PI Advance Ledger will keep "
			"reporting it as spent. Either turn it back on or give Stabler its own on_cancel hook.",
		)

	def test_submit_consumes_the_advance_and_cancel_gives_it_back(self):
		supplier = self._supplier()
		pi = self._proforma_invoice(supplier)
		pe = self._advance_payment(supplier, pi, ADVANCE_AMOUNT)
		before = self._unallocated(pe)
		self.assertEqual(before, ADVANCE_AMOUNT, "a referenceless Pay entry is fully unallocated")

		pinv = self._purchase_invoice(supplier, self._item(), CI_AMOUNT)
		pinv.set_advances()
		self.assertTrue(pinv.advances, "the advance did not surface for its own supplier")
		try:
			pinv.submit()
		except Exception as exc:
			self.skipTest(f"Purchase Invoice could not be submitted on this site: {exc}")

		self.assertEqual(
			self._unallocated(pe),
			before - ADVANCE_AMOUNT,
			"submitting the invoice must consume the advance",
		)

		pinv.reload()
		pinv.cancel()

		self.assertEqual(
			self._unallocated(pe),
			before,
			"cancelling the invoice must return the advance to its pre-invoice balance",
		)

	def test_the_advance_is_allocatable_again_after_the_cancel(self):
		"""Restoring the number is not enough — the planner must re-offer it, capped."""
		supplier = self._supplier()
		pi = self._proforma_invoice(supplier)
		pe = self._advance_payment(supplier, pi, ADVANCE_AMOUNT)
		plan_before = self._plan_from_db(pe, pi, CI_AMOUNT)
		self.assertEqual(plan_before["total_allocated"], ADVANCE_AMOUNT)

		pinv = self._purchase_invoice(supplier, self._item(), CI_AMOUNT)
		pinv.set_advances()
		try:
			pinv.submit()
		except Exception as exc:
			self.skipTest(f"Purchase Invoice could not be submitted on this site: {exc}")

		self.assertEqual(
			self._plan_from_db(pe, pi, CI_AMOUNT)["total_allocated"],
			0.0,
			"while the invoice stands the advance must not be offered twice",
		)

		pinv.reload()
		pinv.cancel()

		self.assertEqual(
			self._plan_from_db(pe, pi, CI_AMOUNT),
			plan_before,
			"after the cancel the planner must produce the same plan as before the invoice",
		)


if __name__ == "__main__":
	unittest.main()
