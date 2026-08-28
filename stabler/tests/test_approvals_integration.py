"""Integration tests for the maker-checker control.

These need a real site + database, so they run under `bench run-tests --app
stabler --module stabler.tests.test_approvals_integration` (and in CI), not
under plain `python -m unittest`. They exercise the full flow end-to-end:
create → blocked from self-submit → approved by a second user → posted.

If the test fixtures (a company with cash/bank accounts) are not present the
relevant tests skip rather than fail, so the suite stays green on a bare site.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager

import frappe

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


MAKER = "stabler-maker@test.local"
CHECKER = "stabler-checker@test.local"


@contextmanager
def _approval_gate_enabled_in_tests():
	was_in_test = bool(getattr(frappe.flags, "in_test", False))
	frappe.flags.in_test = False
	try:
		yield
	finally:
		frappe.flags.in_test = was_in_test


def _ensure_user(email: str, roles: list[str]) -> None:
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		)
		u.insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	existing = {r.role for r in user.roles}
	for role in roles:
		if role not in existing and frappe.db.exists("Role", role):
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)


def _first_company():
	return frappe.db.get_value("Company", {}, "name")


def _leaf_account(company: str, account_type: str):
	return frappe.db.get_value(
		"Account",
		{"company": company, "account_type": account_type, "is_group": 0, "disabled": 0},
		"name",
	)


class ApprovalGateIntegrationTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_user(MAKER, ["Accounts User"])
		_ensure_user(CHECKER, ["Accounts Manager", "Purchase Manager"])
		cls.company = _first_company()
		# Force approvals on, no threshold, for deterministic behaviour.
		if frappe.db.exists("DocType", "Stabler Settings"):
			frappe.db.set_single_value("Stabler Settings", "enable_payment_approvals", 1)
			frappe.db.set_single_value("Stabler Settings", "approval_threshold_base", 0)

	def setUp(self):
		_ensure_user(MAKER, ["Accounts User", "Accounts Manager"])
		_ensure_user(CHECKER, ["Accounts Manager", "Purchase Manager"])
		if frappe.db.exists("DocType", "Stabler Settings"):
			frappe.db.set_single_value("Stabler Settings", "enable_payment_approvals", 1)
			frappe.db.set_single_value("Stabler Settings", "approval_threshold_base", 0)
		if not self.company:
			self.skipTest("no Company fixture available")
		self.bank = _leaf_account(self.company, "Bank") or _leaf_account(self.company, "Cash")
		self.cash = _leaf_account(self.company, "Cash") or self.bank
		if not (self.bank and self.cash):
			self.skipTest("no cash/bank leaf accounts available")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _new_internal_transfer_pe(self):
		"""A bank→cash transfer Payment Entry, left as a Draft."""
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Internal Transfer"
		pe.company = self.company
		pe.paid_from = self.bank
		pe.paid_to = self.cash
		pe.paid_amount = 1000
		pe.received_amount = 1000
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.posting_date = frappe.utils.today()
		# ERPNext demands a cheque/transfer reference the moment either leg is a
		# Bank account, and `_leaf_account(..., "Bank")` picks one whenever the
		# site has one. Without these two fields the fixture never inserts, so
		# every test in this class errors before it reaches the approval gate.
		pe.reference_no = "TEST-TRANSFER-1"
		pe.reference_date = frappe.utils.today()
		pe.insert(ignore_permissions=True)
		return pe

	def test_maker_cannot_self_submit(self):
		from stabler.api.approvals import ensure_request_for_doc

		frappe.set_user(MAKER)
		pe = self._new_internal_transfer_pe()
		ensure_request_for_doc(pe)  # route to queue, as the API does
		pe.reload()
		with _approval_gate_enabled_in_tests():
			with self.assertRaises(frappe.ValidationError):
				pe.submit()  # before_submit gate must block: no approval yet

	def test_checker_can_approve_and_post(self):
		from stabler.api import approvals

		frappe.set_user(MAKER)
		pe = self._new_internal_transfer_pe()
		req = approvals.ensure_request_for_doc(pe)
		self.assertIsNotNone(req)

		# Maker cannot approve own request.
		with self.assertRaises(frappe.ValidationError):
			approvals.approve(req)

		# A different user with the approver role can.
		frappe.set_user(CHECKER)
		approvals.approve(req)

		pe.reload()
		self.assertEqual(pe.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Stabler Approval Request", req, "status"), "Approved")

	def test_system_flagged_doc_bypasses_gate(self):
		from stabler.api.approvals import assert_submit_allowed

		frappe.set_user(MAKER)
		pe = self._new_internal_transfer_pe()
		pe.flags.ignore_approval_gate = True
		# Should not raise even though no approval exists.
		assert_submit_allowed(pe)

	def test_rejected_request_leaves_draft(self):
		from stabler.api import approvals

		frappe.set_user(MAKER)
		pe = self._new_internal_transfer_pe()
		req = approvals.ensure_request_for_doc(pe)

		frappe.set_user(CHECKER)
		approvals.reject(req, note="not this month")

		self.assertEqual(frappe.db.get_value("Stabler Approval Request", req, "status"), "Rejected")
		pe.reload()
		self.assertEqual(pe.docstatus, 0)  # still a draft, untouched


class POApprovalGateIntegrationTest(FrappeTestCase):
	"""Purchase Order maker-checker. Skips unless a purchasable item + supplier
	exist, so the suite stays green on a bare site."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_user(MAKER, ["Purchase User"])
		_ensure_user(CHECKER, ["Accounts Manager", "Purchase Manager"])
		cls.company = _first_company()
		if frappe.db.exists("DocType", "Stabler Settings"):
			# PO approvals default OFF — turn them on for this test, no threshold.
			frappe.db.set_single_value("Stabler Settings", "enable_po_approvals", 1)
			frappe.db.set_single_value("Stabler Settings", "po_approval_threshold_base", 0)

	def setUp(self):
		_ensure_user(MAKER, ["Purchase User", "Accounts Manager"])
		_ensure_user(CHECKER, ["Accounts Manager", "Purchase Manager"])
		if frappe.db.exists("DocType", "Stabler Settings"):
			frappe.db.set_single_value("Stabler Settings", "enable_po_approvals", 1)
			frappe.db.set_single_value("Stabler Settings", "po_approval_threshold_base", 0)
		if not self.company:
			self.skipTest("no Company fixture available")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		self.item = frappe.db.get_value(
			"Item", {"is_purchase_item": 1, "disabled": 0}, "name"
		) or frappe.db.get_value("Item", {"disabled": 0}, "name")
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not (self.supplier and self.item):
			self.skipTest("no Supplier / Item fixtures available")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _new_po(self):
		po = frappe.new_doc("Purchase Order")
		po.company = self.company
		po.supplier = self.supplier
		po.transaction_date = frappe.utils.today()
		po.schedule_date = frappe.utils.today()
		row = po.append("items", {})
		row.item_code = self.item
		row.qty = 1
		row.rate = 1000
		row.schedule_date = frappe.utils.today()
		if self.warehouse:
			row.warehouse = self.warehouse
		po.insert(ignore_permissions=True)
		return po

	def test_po_requires_approval_and_blocks_self_submit(self):
		from stabler.api.approvals import ensure_request_for_doc, requires_approval

		frappe.set_user(MAKER)
		po = self._new_po()
		self.assertTrue(requires_approval(po))
		ensure_request_for_doc(po)
		po.reload()
		with _approval_gate_enabled_in_tests():
			with self.assertRaises(frappe.ValidationError):
				po.submit()  # gate blocks: no approval yet

	def test_po_checker_can_approve_and_post(self):
		from stabler.api import approvals

		frappe.set_user(MAKER)
		po = self._new_po()
		req = approvals.ensure_request_for_doc(po)
		self.assertIsNotNone(req)
		with self.assertRaises(frappe.ValidationError):
			approvals.approve(req)  # maker cannot approve own PO

		frappe.set_user(CHECKER)
		approvals.approve(req)
		po.reload()
		self.assertEqual(po.docstatus, 1)

	def test_po_not_gated_when_disabled(self):
		from stabler.api.approvals import requires_approval

		frappe.db.set_single_value("Stabler Settings", "enable_po_approvals", 0)
		frappe.set_user(MAKER)
		po = self._new_po()
		self.assertFalse(requires_approval(po))
		frappe.db.set_single_value("Stabler Settings", "enable_po_approvals", 1)


if __name__ == "__main__":
	unittest.main()
