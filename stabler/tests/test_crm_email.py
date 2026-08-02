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

		from stabler.api import crm, organization

		organization._user_allowed_companies = lambda _user: ["ACME"]
		crm._user_allowed_companies = lambda _user: ["ACME"]

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
			organization="Beta Inc",
			lead_name="Jane Smith",
			email_id="jane@beta.com",
			docstatus=0,
		)

		# Communication fixtures
		self.fake.docs[("Communication", "COMM-UNMATCHED-1")] = _Doc(
			name="COMM-UNMATCHED-1",
			doctype="Communication",
			company="ACME",
			subject="Question about quote [DEAL-100]",
			sender="john@alfa.com",
			custom_triage_status="Unmatched",
		)
		self.fake.docs[("Communication", "COMM-FOREIGN")] = _Doc(
			name="COMM-FOREIGN",
			doctype="Communication",
			company="OTHER_CO",
			subject="Foreign inquiry",
			sender="foreign@other.com",
			custom_triage_status="Unmatched",
		)

	def test_send_deal_email_creates_communication_and_dedupes_in_db(self):
		from stabler.api import crm_email

		# Send email
		res1 = crm_email.send_deal_email(
			deal="DEAL-100",
			subject="Tender Clarification",
			content="Please clarify specs.",
			company="ACME",
			idempotency_key="MSG-001",
		)

		self.assertEqual(res1["deal"], "DEAL-100")
		self.assertFalse(res1["deduped"])

		# Second call with same idempotency key -> deduped cleanly
		res2 = crm_email.send_deal_email(
			deal="DEAL-100",
			subject="Tender Clarification",
			content="Please clarify specs.",
			company="ACME",
			idempotency_key="MSG-001",
		)

		self.assertEqual(res2["name"], res1["name"])
		self.assertTrue(res2["deduped"])

	def test_send_deal_email_fails_loud_on_sendmail_error(self):
		from stabler.api import crm_email

		# Mock sendmail raising an exception
		def _fail_sendmail(**kwargs):
			raise RuntimeError("SMTP Gateway Timeout")

		sys.modules["frappe"].sendmail = _fail_sendmail

		with self.assertRaises(Exception):
			crm_email.send_deal_email(
				deal="DEAL-100",
				subject="Tender Clarification",
				content="Please clarify specs.",
				company="ACME",
			)

	def test_send_deal_email_rejects_foreign_company(self):
		from stabler.api import crm_email

		with self.assertRaises(PermissionError):
			crm_email.send_deal_email(
				deal="DEAL-FOREIGN",
				subject="Hacking Attempt",
				content="Cross-company email attempt.",
				company="ACME",
			)

	def test_triage_queue_filters_by_company_no_cross_company_leak(self):
		from stabler.api import crm_email

		res = crm_email.list_email_triage_queue(company="ACME")
		names = [row["name"] for row in res["rows"]]

		self.assertIn("COMM-UNMATCHED-1", names)
		self.assertNotIn("COMM-FOREIGN", names)

	def test_forged_deal_tag_does_not_cross_company(self):
		from stabler.api import crm_email

		# Communication in ACME trying to auto-match a deal in OTHER_CO via forged subject tag
		self.fake.docs[("Communication", "COMM-FORGED")] = _Doc(
			name="COMM-FORGED",
			doctype="Communication",
			company="ACME",
			subject="Fake subject [DEAL-FOREIGN]",
			sender="attacker@fake.com",
			custom_triage_status="Pending",
		)

		match_res = crm_email.match_incoming_email_to_deal(
			communication_name="COMM-FORGED",
			company="ACME",
		)

		self.assertTrue(match_res["triage_required"])
		self.assertIsNone(match_res["deal"])

	def test_link_triage_email_checks_both_communication_and_deal_company(self):
		from stabler.api import crm_email

		# Attempting to link ACME email to OTHER_CO deal -> rejected
		with self.assertRaises(PermissionError):
			crm_email.link_triage_email(
				communication_name="COMM-UNMATCHED-1",
				deal="DEAL-FOREIGN",
				company="ACME",
			)

	def test_communication_permission_missing_user_rejected(self):
		from stabler.api import crm_email

		def _no_permission(doctype, ptype="read", doc=None, user=None):
			return False

		sys.modules["frappe"].has_permission = _no_permission
		with self.assertRaises(PermissionError):
			crm_email.send_deal_email(
				deal="DEAL-100",
				subject="Subject",
				content="Content",
				company="ACME",
			)
		sys.modules["frappe"].has_permission = lambda doctype, ptype="read", doc=None, user=None: True


if __name__ == "__main__":
	unittest.main()
