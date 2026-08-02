"""Unit tests for Customs Role Queue (declarant_queue) — Task C2.

Verifies derived lane classification, single-pass lane counts, document intake integration,
permission gating, and backward compatibility.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from stabler.api import tender


class TestDeclarantQueueServer(unittest.TestCase):
	def setUp(self):
		self.po_base = {
			"name": "PO-2026-001",
			"supplier_name": "Alfa LLC",
			"custom_crm_deal": "CRM-DEAL-001",
			"custom_landed_charges": None,
			"per_received": 0,
			"schedule_date": "2026-09-01",
			"transaction_date": "2026-08-01",
		}

	def _run_queue(self, pos=None, reqs_json=None, cd_doc=None, view_allowed=True):
		pos_list = [MagicMock(**self.po_base)] if pos is None else pos

		def fake_require_view(view, company):
			if not view_allowed:
				raise PermissionError("Not permitted.")

		def fake_db_get_value(doctype, name, field=None, **_kwargs):
			if doctype == "Company":
				return "USD"
			if doctype == "CRM Deal" and field == "custom_document_intake":
				return reqs_json
			return None

		def fake_has_permission(doctype, ptype="read", doc=None):
			return True

		cd_rows = [cd_doc] if cd_doc else []

		fake_frappe = types.SimpleNamespace(
			PermissionError=PermissionError,
			db=types.SimpleNamespace(
				get_value=fake_db_get_value,
				exists=lambda dt, name: True,
				has_column=lambda dt, col: True,
			),
			get_all=lambda doctype, **_kwargs: cd_rows if doctype == "Customs Declaration" else [],
			has_permission=fake_has_permission,
		)

		with (
			patch.object(tender, "frappe", fake_frappe),
			patch.object(tender, "today", return_value="2026-08-02"),
			patch.object(tender, "_require_tender_view", side_effect=fake_require_view),
			patch.object(tender, "_po_rows_for_views", return_value=(pos_list, False)),
		):
			return tender.declarant_queue("ACME")

	def test_declarant_queue_returns_lanes_structure_with_counts_matching_items(self):
		res = self._run_queue()
		self.assertIn("lanes", res)
		self.assertIn("rows", res)
		self.assertEqual(res["currency"], "USD")
		expected_lanes = ("missing_docs", "ready", "declared", "inspection", "released")
		for key in expected_lanes:
			self.assertIn(key, res["lanes"])
			lane = res["lanes"][key]
			self.assertEqual(lane["count"], len(lane["items"]))

	def test_po_with_missing_customs_docs_lands_in_missing_docs_lane(self):
		reqs_json = '[{"key": "gtd", "label": "GTD", "required": true, "role": "customs"}]'
		res = self._run_queue(reqs_json=reqs_json)
		self.assertEqual(res["lanes"]["missing_docs"]["count"], 1)
		item = res["lanes"]["missing_docs"]["items"][0]
		self.assertEqual(item["stage"], "missing_docs")
		self.assertEqual(item["missing_customs_docs_count"], 1)

	def test_po_with_complete_customs_docs_and_no_declaration_lands_in_ready_lane(self):
		reqs_json = '[{"key": "gtd", "label": "GTD", "required": true, "role": "customs", "files": [{"file_name": "gtd.pdf"}]}]'
		res = self._run_queue(reqs_json=reqs_json)
		self.assertEqual(res["lanes"]["ready"]["count"], 1)
		item = res["lanes"]["ready"]["items"][0]
		self.assertEqual(item["stage"], "ready")
		self.assertEqual(item["missing_customs_docs_count"], 0)

	def test_po_with_draft_customs_declaration_lands_in_declared_lane(self):
		reqs_json = '[{"key": "gtd", "label": "GTD", "required": true, "role": "customs", "files": [{"file_name": "gtd.pdf"}]}]'
		cd_doc = {
			"name": "GTD-001",
			"status": "Draft",
			"purchase_order": "PO-2026-001",
			"custom_crm_deal": "CRM-DEAL-001",
		}
		res = self._run_queue(reqs_json=reqs_json, cd_doc=cd_doc)
		self.assertEqual(res["lanes"]["declared"]["count"], 1)
		item = res["lanes"]["declared"]["items"][0]
		self.assertEqual(item["stage"], "declared")
		self.assertEqual(item["customs_declaration"], "GTD-001")

	def test_po_with_inspection_customs_declaration_lands_in_inspection_lane(self):
		cd_doc = {
			"name": "GTD-002",
			"status": "Under Review",
			"purchase_order": "PO-2026-001",
			"custom_crm_deal": "CRM-DEAL-001",
		}
		res = self._run_queue(cd_doc=cd_doc)
		self.assertEqual(res["lanes"]["inspection"]["count"], 1)
		item = res["lanes"]["inspection"]["items"][0]
		self.assertEqual(item["stage"], "inspection")

	def test_po_cleared_or_released_lands_in_released_lane(self):
		po = MagicMock(**{**self.po_base, "per_received": 100})
		res = self._run_queue(pos=[po])
		self.assertEqual(res["lanes"]["released"]["count"], 1)
		item = res["lanes"]["released"]["items"][0]
		self.assertEqual(item["stage"], "released")

	def test_declarant_queue_rejects_without_view_permission(self):
		with self.assertRaises(PermissionError):
			self._run_queue(view_allowed=False)

	def test_empty_queue_returns_zero_counts_without_error(self):
		res = self._run_queue(pos=[])
		self.assertEqual(len(res["rows"]), 0)
		for lane in res["lanes"].values():
			self.assertEqual(lane["count"], 0)


if __name__ == "__main__":
	unittest.main()
