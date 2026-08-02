"""Contract & unit tests for Two-Way Email and Triage Queue (stabler/api/crm_email.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_crm_email -v
"""

from __future__ import annotations

import sys
import unittest

from stabler.tests.test_sourcing_api import _Doc, _FakeFrappe, _load_api


class TestCrmEmail(unittest.TestCase):
	def setUp(self):
		self.fake = _FakeFrappe()
		self.sourcing_api = _load_api(self.fake)
		self.frappe = sys.modules["frappe"]

		# Add CRM Deal fixtures
		self.fake.docs[("CRM Deal", "DEAL-100")] = _Doc(
			name="DEAL-100",
			company="ACME",
			organization="Alfa Corp",
			lead_name="John Doe",
			email_id="john@alfa.com",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-FOREIGN")] = _Doc(
			name="DEAL-FOREIGN",
			company="OTHER_CO",
			organization="Beta Corp",
			lead_name="Jane Smith",
			email_id="jane@beta.com",
			docstatus=0,
		)

	def test_send_deal_email_creates_communication_and_dedupes(self):
		from stabler.api import crm_email

		# Send first email with idempotency key
		res1 = crm_email.send_deal_email(
			deal="DEAL-100",
			subject="Quotation Request for Rail",
			content="Hello John, please see attached RFQ.",
			company="ACME",
			idempotency_key="email_send_100_01",
		)
		self.assertIn("name", res1)
		self.assertFalse(res1.get("deduped", False))

		# Resend with same idempotency key -> deduped
		res2 = crm_email.send_deal_email(
			deal="DEAL-100",
			subject="Quotation Request for Rail",
			content="Hello John, please see attached RFQ.",
			company="ACME",
			idempotency_key="email_send_100_01",
		)
		self.assertTrue(res2.get("deduped", False))
		self.assertEqual(res1["name"], res2["name"])

	def test_send_deal_email_rejects_foreign_company(self):
		from stabler.api import crm_email

		with self.assertRaises(self.frappe.PermissionError):
			crm_email.send_deal_email(
				deal="DEAL-FOREIGN",
				subject="Test",
				content="Test",
				company="ACME",
			)

	def test_incoming_email_thread_matching_and_triage_queue(self):
		from stabler.api import crm_email

		# Add unmatched communication
		comm = _Doc(
			name="COMM-901",
			doctype="Communication",
			company="ACME",
			subject="Re: Quotation Request [DEAL-100]",
			sender="john@alfa.com",
			recipients="sourcing@acme.com",
			content="Here is our price list.",
			custom_triage_status="Pending",
			reference_doctype=None,
			reference_name=None,
		)
		self.fake.docs[("Communication", "COMM-901")] = comm

		# Match incoming email
		match_res = crm_email.match_incoming_email_to_deal("COMM-901")
		self.assertEqual(match_res["deal"], "DEAL-100")
		self.assertEqual(comm["reference_name"], "DEAL-100")

		# Add ambiguous communication without matching deal
		comm_amb = _Doc(
			name="COMM-902",
			doctype="Communication",
			company="ACME",
			subject="Inquiry about products",
			sender="unknown@stranger.com",
			recipients="sales@acme.com",
			content="Hello I need info.",
			custom_triage_status="Pending",
			reference_doctype=None,
			reference_name=None,
		)
		self.fake.docs[("Communication", "COMM-902")] = comm_amb

		# Match ambiguous email -> routed to triage queue
		amb_res = crm_email.match_incoming_email_to_deal("COMM-902")
		self.assertTrue(amb_res.get("triage_required"))
		self.assertEqual(comm_amb["custom_triage_status"], "Unmatched")

		# List triage queue
		triage_list = crm_email.list_email_triage_queue(company="ACME")
		self.assertEqual(len(triage_list["rows"]), 1)
		self.assertEqual(triage_list["rows"][0]["name"], "COMM-902")

		# Manually link triage email
		linked = crm_email.link_triage_email("COMM-902", deal="DEAL-100", company="ACME")
		self.assertEqual(linked["deal"], "DEAL-100")
		self.assertEqual(comm_amb["custom_triage_status"], "Linked")


if __name__ == "__main__":
	unittest.main()
