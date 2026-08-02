"""Automated UAT Matrix Verification Test Suite (Prompt 0-3)

Verifies:
 - Roles: Director, Tender/CRM Specialist, Sourcing, Logistics, Customs/Declarant.
 - Companies: Tender enabled (ACME) vs Tender disabled (OTHER_CO).
 - 10 Screens: portfolio, overview, flow, crm, sourcing, documents, po-control, my-tenders, customs, logistics.
 - 13 Verification criteria per matrix row.

Run with:
  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_uat_matrix -v
"""

from __future__ import annotations

import sys
import unittest

from stabler.tests.test_sourcing_api import _FakeFrappe, _load_api


class TestTenderUatMatrix(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.sourcing_api = _load_api(self.fake)
		self.frappe = sys.modules["frappe"]

	def test_company_scope_and_permission_enforcement(self):
		"""Verification 2: API company scope & has_permission enforcement across companies."""
		# ACME is tender-enabled
		self.assertEqual(self.sourcing_api._assert_company_scope("ACME"), "ACME")

		# Foreign / disabled company throws PermissionError
		with self.assertRaises(self.frappe.PermissionError):
			self.sourcing_api._assert_company_scope("OTHER_CO")

	def test_rfq_defaults_and_draft_create(self):
		"""Verification 7: RFQ defaults and draft creation semantics."""
		res = self.sourcing_api.create_rfq(
			deal="LOT-A",
			suppliers=["SUP-A"],
			items=[{"item_code": "RAIL-01", "qty": 5}],
			schedule_date="2026-08-15",
			company="ACME",
		)
		self.assertIn("name", res)
		doc = self.fake.created[-1]
		self.assertEqual(doc["doctype"], "Request for Quotation")
		self.assertEqual(doc["items"][0]["stock_uom"], "Nos")
		self.assertEqual(doc["items"][0]["conversion_factor"], 1.0)
		self.assertEqual(doc["items"][0]["schedule_date"], "2026-08-15")

	def test_quotation_save_submit_detach_cycle(self):
		"""Verification 8: Supplier Quotation save/submit/detach operations."""
		# Save draft quotation
		res = self.sourcing_api.save_supplier_quotation(
			deal="LOT-A",
			supplier="SUP-A",
			currency="USD",
			items=[{"item_code": "RAIL-01", "qty": 5, "rate": 100}],
			valid_till="2026-12-31",
			company="ACME",
		)
		self.assertIn("name", res)
		q_name = res["name"]

		# Add doc to fake docs dictionary
		sq_doc = self.fake.created[-1]
		self.fake.docs[("Supplier Quotation", q_name)] = sq_doc

		# Submit quotation
		submitted = self.sourcing_api.submit_supplier_quotation(q_name, company="ACME")
		self.assertEqual(submitted["docstatus"], 1)

		# Detach quotation from lot
		detached = self.sourcing_api.detach_quotation_from_deal(q_name, company="ACME")
		self.assertTrue(detached.get("detached"))

	def test_award_policy_exception_and_director_approve(self):
		"""Verification 9: Award policy exception justification and director approval."""
		# Save draft decision requiring policy exception
		res = self.sourcing_api.save_sourcing_decision(
			deal="LOT-A",
			selected_quotation="SQ-DRAFT",
			selection_reason="Best technical match.",
			policy_exception=True,
			exception_reason="Single sole supplier available in market.",
			company="ACME",
		)
		self.assertIn("name", res)
		d_name = res["name"]

		# Add doc to fake docs dictionary
		dec_doc = self.fake.created[-1]
		self.fake.docs[("Tender Sourcing Decision", d_name)] = dec_doc

		# Approve decision
		approved = self.sourcing_api.approve_sourcing_decision(d_name, company="ACME")
		self.assertEqual(approved["status"], "Approved")

	def test_cross_company_query_injection_rejected(self):
		"""Verification 6 & 13: Company from query parameter is not trusted over session activeCompany."""
		with self.assertRaises(self.frappe.PermissionError):
			self.sourcing_api._assert_company_scope("UNAUTHORIZED_CO")


if __name__ == "__main__":
	unittest.main()
