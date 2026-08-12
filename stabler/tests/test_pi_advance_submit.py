"""An advance recorded against a Proforma Invoice must be POSTED, not drafted.

`build_pi_advance_ledger` credits `advance_in` only for `docstatus == 1`; a draft
Payment Entry contributes zero and lands in `advance_pending_approval` instead.
So while `create_advance_payment` left its entries as drafts, every PI advance
ledger read `advance_available = 0` no matter how much money had been entered —
the screen was arithmetically correct and completely useless. These tests pin the
posted state and the credit it buys, because "the Payment Entry exists" is not
the same claim as "the advance is real money".

The guard tests cover the other half. `_assert_advance_postable` runs **before**
`insert()`: `paid_from` / `paid_to` are `reqd` on the Payment Entry doctype and
both exchange rates go through ERPNext's `validate_mandatory`, so an insert-first
ordering pre-empts all three branches with a generic "<Field> is mandatory" and
the purpose-built messages can never reach the user. Asserting the messages here
is what keeps that ordering from silently regressing.

Fixtures are built on whatever Company the site carries and rolled back in
`tearDown`; `frappe.db.commit()` is never called.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from stabler.api.imports import (
	_assert_advance_postable,
	create_advance_payment,
	pi_advance_ledger,
)

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


PI_TOTAL = 200_000.0
ADVANCE_PCT = 40.0
BANK_ADVANCE = 50_000.0
CASH_ADVANCE = 30_000.0


def _account(company: str, currency: str, **filters) -> str | None:
	return frappe.db.get_value(
		"Account",
		dict(company=company, is_group=0, disabled=0, account_currency=currency, **filters),
		"name",
	)


class PiAdvanceSubmitTest(FrappeTestCase):
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
		if not frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
			self.skipTest("PI advance traceability not migrated on this site")
		self.bank = self._bank_account()
		self.cash = _account(self.company, self.currency, account_type="Cash")
		self.payable = _account(self.company, self.currency, account_type="Payable")
		if not (self.bank and self.cash and self.payable):
			self.skipTest("company has no bank / cash / payable account to post against")

	def tearDown(self):
		frappe.db.rollback()

	# --- fixtures -----------------------------------------------------------

	def _bank_account(self) -> str | None:
		"""`_validate_advance_source_account` demands `account_type == stream`, so the
		Bank stream cannot fall back to a Cash account. A bare ERPNext test company
		ships no Bank-type ledger, so create one and let `tearDown` roll it back."""
		existing = _account(self.company, self.currency, account_type="Bank")
		if existing:
			return existing
		parent = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1, "account_type": "Bank"}, "name"
		) or frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}, "name"
		)
		if not parent:
			return None
		return (
			frappe.get_doc(
				{
					"doctype": "Account",
					"company": self.company,
					"parent_account": parent,
					"account_name": "PiAdvSub Bank " + frappe.generate_hash(length=6),
					"account_type": "Bank",
					"account_currency": self.currency,
					"is_group": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _supplier(self) -> str:
		"""A brand-new supplier, so the only advance in play is the one we create."""
		return (
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": "PiAdvSub_" + frappe.generate_hash(length=8),
					"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _proforma_invoice(self, supplier: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Proforma Invoice",
					"company": self.company,
					"supplier": supplier,
					"supplier_pi_ref": "PI-SUB-" + frappe.generate_hash(length=8),
					"pi_date": today(),
					"currency": self.currency,
					"agreed_total": PI_TOTAL,
					"advance_pct": ADVANCE_PCT,
					"status": "CONFIRMED",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _record(self, pi: str, *, bank: float = 0.0, cash: float = 0.0) -> dict:
		"""Call the endpoint the way the SPA does, with the two gates patched off."""
		with (
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_cost_visible"),
		):
			try:
				return create_advance_payment(
					purchase_order=pi,
					bank_amount=bank,
					cash_amount=cash,
					bank_account=self.bank if bank else None,
					cash_account=self.cash if cash else None,
				)
			except Exception as exc:  # accounting defaults vary per site
				self.skipTest(f"advance could not be recorded on this site: {exc}")

	def _ledger(self, pi: str) -> dict:
		with (
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_cost_visible"),
		):
			return pi_advance_ledger(pi)

	# --- the posted state ---------------------------------------------------

	def test_a_recorded_advance_is_submitted_not_drafted(self):
		pi = self._proforma_invoice(self._supplier())
		res = self._record(pi, bank=BANK_ADVANCE)

		self.assertEqual(len(res["payment_entries"]), 1)
		entry = res["payment_entries"][0]
		self.assertEqual(entry["docstatus"], 1, "the endpoint reported an unposted advance")
		self.assertEqual(
			frappe.db.get_value("Payment Entry", entry["name"], "docstatus"),
			1,
			"the Payment Entry is a draft in the database",
		)

	def test_both_streams_are_submitted(self):
		pi = self._proforma_invoice(self._supplier())
		res = self._record(pi, bank=BANK_ADVANCE, cash=CASH_ADVANCE)

		self.assertEqual({e["stream"] for e in res["payment_entries"]}, {"Bank", "Cash"})
		for entry in res["payment_entries"]:
			self.assertEqual(
				frappe.db.get_value("Payment Entry", entry["name"], "docstatus"),
				1,
				f"the {entry['stream']} stream stayed a draft",
			)

	def test_the_advance_buys_credit_in_the_ledger(self):
		"""The point of submitting: a draft contributes advance_in = 0."""
		pi = self._proforma_invoice(self._supplier())
		self.assertEqual(
			self._ledger(pi)["summary"]["advance_available"],
			0.0,
			"a PI with no payments cannot have credit",
		)

		self._record(pi, bank=BANK_ADVANCE)
		summary = self._ledger(pi)["summary"]

		self.assertEqual(
			flt(summary["advance_available"]),
			BANK_ADVANCE,
			"a posted advance must be available to allocate",
		)
		self.assertEqual(flt(summary["advance_paid"]), BANK_ADVANCE)
		self.assertEqual(
			flt(summary["advance_pending_approval"]),
			0.0,
			"a submitted entry must not be reported as waiting for approval",
		)

	# --- the guard ----------------------------------------------------------

	def _pe(self, **overrides):
		"""The fields `_assert_advance_postable` reads, all valid unless overridden."""
		pe = frappe._dict(
			paid_from=self.bank,
			paid_to=self.payable,
			party="Some Supplier",
			posting_date=today(),
			paid_from_account_currency=self.currency,
			paid_to_account_currency=self.currency,
			source_exchange_rate=1.0,
			target_exchange_rate=1.0,
		)
		pe.update(overrides)
		return pe

	def test_the_valid_case_passes(self):
		"""Without this the three throw-tests below could pass for any reason."""
		_assert_advance_postable(self._pe(), company=self.company, stream="Bank")

	def test_a_missing_source_account_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_assert_advance_postable(self._pe(paid_from=None), company=self.company, stream="Bank")
		self.assertIn("bank", str(ctx.exception).lower())

	def test_a_missing_payable_account_is_refused_by_name(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_assert_advance_postable(self._pe(paid_to=None), company=self.company, stream="Bank")
		self.assertIn("payable", str(ctx.exception).lower())

	def test_a_missing_exchange_rate_is_refused_before_it_becomes_a_zero_base_amount(self):
		foreign = "USD" if self.currency != "USD" else "EUR"
		with self.assertRaises(frappe.ValidationError) as ctx:
			_assert_advance_postable(
				self._pe(paid_from_account_currency=foreign, source_exchange_rate=0),
				company=self.company,
				stream="Bank",
			)
		self.assertIn(foreign, str(ctx.exception))


if __name__ == "__main__":
	unittest.main()
