"""Frappe-free contract guards for the tender operations dashboard.

These checks keep the dashboard's lifecycle and aggregation boundary explicit:
submission and transition audit fields are server-owned, legacy results do not
become participation evidence, and finance is never emitted for an unauthorised
role.  They deliberately inspect the API source so they can run without a site.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TENDER = os.path.normpath(os.path.join(_HERE, "..", "api", "tender.py"))
_ORGANIZATION = os.path.normpath(os.path.join(_HERE, "..", "api", "organization.py"))


def _read(path: str) -> str:

	with open(path, encoding="utf-8") as f:
		return f.read()


def _func_body(src: str, name: str) -> str:

	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start():]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestTenderLifecycleContract(unittest.TestCase):

	def setUp(self):
		self.src = _read(_TENDER)

	def test_submission_is_whitelisted_and_server_audited(self):
		body = _func_body(self.src, "mark_tender_submitted")
		self.assertIn("@frappe.whitelist()", self.src[self.src.index(body) - 24:self.src.index(body)])
		self.assertIn("_deal_scope(deal, write=True)", body)
		self.assertIn("submitted_at", body)
		self.assertIn("submitted_by", body)
		self.assertIn("frappe.session.user", body)
		self.assertNotIn("data.get(\"submitted_at\")", body)

	def test_intake_transition_audit_cannot_be_client_supplied(self):
		body = _func_body(self.src, "_clean_intake")
		for key in ("go_no_go_at", "go_no_go_by", "result_at", "result_by"):
			self.assertIn(key, body)
		self.assertIn("frappe.session.user", body)
		self.assertNotIn("data.get(\"go_no_go_at\")", body)
		self.assertNotIn("data.get(\"result_at\")", body)

	def test_intake_save_preserves_existing_server_submission_audit(self):
		body = _func_body(self.src, "_clean_intake")
		for key in ("submitted_at", "submitted_by", "submission_reference"):
			self.assertIn(key, body)
		self.assertIn("prior.get(key)", body)


class TestTenderDashboardContract(unittest.TestCase):

	def setUp(self):
		self.src = _read(_TENDER)
		self.body = _func_body(self.src, "tender_dashboard")

	def test_dashboard_enforces_scope_module_permissions_and_role_window(self):
		for guard in ("_require_company(company)", "_require_tender(company)", "_assert_company_scope(company)"):
			self.assertIn(guard, self.body)
		self.assertIn("_tender_views()", self.body)
		self.assertIn("frappe.has_permission(\"CRM Deal\", \"read\"", self.body)

	def test_candidate_queries_apply_frappe_list_permissions_before_field_reads(self):
		candidates = _func_body(self.src, "_tender_deal_names")
		self.assertIn("frappe.get_list(", candidates)
		self.assertNotIn("frappe.get_all(", candidates)
		self.assertIn("frappe.get_list(", self.body)
		self.assertNotIn("frappe.get_all(", self.body)

	def test_dashboard_returns_role_adaptive_sections(self):
		for section in ("period", "role_scope", "acquisition", "execution", "attention", "my_work", "trend", "portfolio_preview"):
			self.assertIn(f'"{section}"', self.body)

	def test_dashboard_execution_includes_aggregate_invoice_status_only(self):
		self.assertIn('"invoice_status"', self.body)
		self.assertIn('"purchase_invoices"', self.body)
		self.assertIn('"sales_invoices"', self.body)

	def test_legacy_results_are_unverified_not_submitted(self):
		self.assertIn("unverified_history", self.body)
		evidence = _func_body(self.src, "_has_submission_evidence")
		self.assertIn("submitted_at", evidence)
		self.assertIn("submitted_by", evidence)

	def test_period_and_execution_use_erpnext_progress_fields(self):
		for field in ("from_date", "to_date", "per_received", "per_delivered"):
			self.assertIn(field, self.body)
		self.assertIn('"customs_proxy":', self.body)
		self.assertIn("planned_landed_customs_charge_not_clearance", self.body)
		self.assertIn('"logistics_status":', self.body)

	def test_finance_is_omitted_unless_finance_role_is_present(self):
		self.assertIn("_can_view_tender_finance", self.body)
		self.assertIn('out["finance"]', self.body)

	def test_declarant_and_logist_have_tender_module_access(self):
		roles = _read(_ORGANIZATION)
		self.assertIn('"tender": ["Sales User", "Sales Manager", "Stabler Declarant", "Stabler Logist"]', roles)


class TestTenderBoardFilterPayloadContract(unittest.TestCase):
	def test_lifecycle_boards_emit_stage_and_period_evidence(self):
		src = _read(_TENDER)
		for name in ("tender_director_board", "sourcing_my_tenders"):
			body = _func_body(src, name)
			for field in ('"event_date"', '"lifecycle"', '"status"', '"due"'):
				self.assertIn(field, body, f"{name} must return {field}")

	def test_execution_boards_emit_po_status_and_period_evidence(self):
		src = _read(_TENDER)
		for name in ("declarant_queue", "logist_board"):
			body = _func_body(src, name)
			for field in ('"event_date"', '"stage"', '"status"', '"risk"', '"due"'):
				self.assertIn(field, body, f"{name} must return {field}")


if __name__ == "__main__":
	unittest.main()
