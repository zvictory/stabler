"""Contract & unit tests for Two-Way Email and Triage Queue (stabler/api/crm_email.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_crm_email -v
"""

from __future__ import annotations

import sys
import unittest

from stabler.tests.test_sourcing_api import _Doc, _FakeFrappe, _load_api


class TestCrmEmail(unittest.TestCase):
	fake = None
	frappe = None

	@classmethod
	def setUpClass(cls):
		cls.fake = _FakeFrappe()
		_load_api(cls.fake)
		cls.frappe = sys.modules["frappe"]

	def setUp(self):
		self.fake.docs.clear()
		self.fake.created.clear()
		self.frappe.session.user = "crm_user@acme.com"

		# Add CRM Deal fixtures
		self.fake.docs[("CRM Deal", "DEAL-100")] = _Doc(
			name="DEAL-100",
			doctype="CRM Deal",
			company="ACME",
			organization="Alfa Corp",
			lead_name="John Doe",
			email_id="john@alfa.com",
			docstatus=0,
		)
		self.fake.docs[("CRM Deal", "DEAL-FOREIGN")] = _Doc(
			name="DEAL-FOREIGN",
			doctype="CRM Deal",
			company="OTHER_CO",
			organization="Beta Corp",
			lead_name="Jane Smith",
			email_id="jane@beta.com",
			docstatus=0,
		)

	def test_send_deal_email_creates_communication_and_dedupes_in_db(self):
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

		# Resend with same idempotency key -> deduped via DB lookup
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

	def test_send_deal_email_fails_loud_on_sendmail_error(self):
		from stabler.api import crm_email

		# Inject sendmail failure
		def _failing_sendmail(*args, **kwargs):
			raise RuntimeError("SMTP Connection Timeout")

		original_sendmail = getattr(self.frappe, "sendmail", None)
		self.frappe.sendmail = _failing_sendmail

		try:
			with self.assertRaises(RuntimeError):
				crm_email.send_deal_email(
					deal="DEAL-100",
					subject="Failing Email",
					content="This delivery will fail",
					company="ACME",
				)
		finally:
			if original_sendmail:
				self.frappe.sendmail = original_sendmail

	def test_triage_queue_filters_by_company_no_cross_company_leak(self):
		from stabler.api import crm_email

		# Communication for ACME
		comm_acme = _Doc(
			name="COMM-ACME",
			doctype="Communication",
			company="ACME",
			subject="ACME Inquiry",
			sender="customer@acme-client.com",
			recipients="sales@acme.com",
			custom_triage_status="Unmatched",
		)
		# Communication for OTHER_CO
		comm_other = _Doc(
			name="COMM-OTHER",
			doctype="Communication",
			company="OTHER_CO",
			subject="Other Inquiry",
			sender="customer@other-client.com",
			recipients="sales@other.com",
			custom_triage_status="Unmatched",
		)
		self.fake.docs[("Communication", "COMM-ACME")] = comm_acme
		self.fake.docs[("Communication", "COMM-OTHER")] = comm_other

		triage_list = crm_email.list_email_triage_queue(company="ACME")
		names = [r["name"] for r in triage_list["rows"]]
		self.assertIn("COMM-ACME", names)
		self.assertNotIn("COMM-OTHER", names)

	def test_forged_deal_tag_does_not_cross_company(self):
		from stabler.api import crm_email

		# Incoming email forging [DEAL-FOREIGN] tag for ACME company
		comm_forged = _Doc(
			name="COMM-FORGED",
			doctype="Communication",
			company="ACME",
			subject="Re: Fake Quote [DEAL-FOREIGN]",
			sender="hacker@evil.com",
			custom_triage_status="Pending",
		)
		self.fake.docs[("Communication", "COMM-FORGED")] = comm_forged

		res = crm_email.match_incoming_email_to_deal("COMM-FORGED", company="ACME")
		# Foreign deal match must be rejected -> triage_required = True
		self.assertTrue(res.get("triage_required"))
		self.assertIsNone(res.get("deal"))

	def test_link_triage_email_checks_both_communication_and_deal_company(self):
		from stabler.api import crm_email

		comm_other = _Doc(
			name="COMM-OTHER-2",
			doctype="Communication",
			company="OTHER_CO",
			subject="Other Quote",
			custom_triage_status="Unmatched",
		)
		self.fake.docs[("Communication", "COMM-OTHER-2")] = comm_other

		# Linking foreign communication to ACME deal should fail with PermissionError
		with self.assertRaises(self.frappe.PermissionError):
			crm_email.link_triage_email("COMM-OTHER-2", deal="DEAL-100", company="ACME")


if __name__ == "__main__":
	unittest.main()
