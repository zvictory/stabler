"""Unit tests for Logistics Role Queue (logist_board) — Task C4.

Verifies derived lane classification (planning, booking, transit, border, delivered, accepted),
single-pass lane counters, document intake integration, permission gating, and backward compatibility.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from stabler.api import tender


class TestLogistBoardServer(unittest.TestCase):
	def setUp(self):
		self.po_base = {
			"name": "PO-2026-002",
			"supplier_name": "Beta Transport",
			"custom_crm_deal": "CRM-DEAL-002",
			"custom_landed_charges": None,
			"per_received": 0,
			"schedule_date": "2026-09-10",
			"transaction_date": "2026-08-01",
		}

	def _run_queue(self, pos=None, reqs_json=None, fb_doc=None, view_allowed=True):
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

		fb_rows = [fb_doc] if fb_doc else []

		fake_frappe = types.SimpleNamespace(
			PermissionError=PermissionError,
			db=types.SimpleNamespace(
				get_value=fake_db_get_value,
				exists=lambda dt, name: True,
				has_column=lambda dt, col: True,
			),
			get_all=lambda doctype, **_kwargs: fb_rows if doctype == "Freight Booking" else [],
			get_list=lambda doctype, **_kwargs: [],
			has_permission=fake_has_permission,
		)

		with (
			patch.object(tender, "frappe", fake_frappe),
			patch.object(tender, "today", return_value="2026-08-02"),
			patch.object(tender, "_require_tender_view", side_effect=fake_require_view),
			patch.object(tender, "_po_rows_for_views", return_value=(pos_list, False)),
			patch.object(tender, "_read_intake", return_value={}),
		):
			return tender.logist_board("ACME")

	def test_logist_board_returns_lanes_structure_with_counts_matching_items(self):
		res = self._run_queue()
		self.assertIn("lanes", res)
		self.assertIn("rows", res)
		self.assertEqual(res["currency"], "USD")
		expected_lanes = ("planning", "booking", "transit", "border", "delivered", "accepted")
		for key in expected_lanes:
			self.assertIn(key, res["lanes"])
			lane = res["lanes"][key]
			self.assertEqual(lane["count"], len(lane["items"]))

	def test_po_with_missing_logistics_docs_lands_in_planning_lane(self):
		reqs_json = '[{"key": "cmr", "label": "CMR", "required": true, "role": "logistics"}]'
		res = self._run_queue(reqs_json=reqs_json)
		self.assertEqual(res["lanes"]["planning"]["count"], 1)
		item = res["lanes"]["planning"]["items"][0]
		self.assertEqual(item["stage"], "planning")
		self.assertEqual(item["missing_logistics_docs_count"], 1)

	def test_po_with_booked_freight_booking_lands_in_booking_lane(self):
		reqs_json = '[{"key": "cmr", "label": "CMR", "required": true, "role": "logistics", "files": [{"file_name": "cmr.pdf"}]}]'
		fb_doc = {
			"name": "FB-001",
			"status": "Booked",
			"purchase_order": "PO-2026-002",
			"custom_crm_deal": "CRM-DEAL-002",
		}
		res = self._run_queue(reqs_json=reqs_json, fb_doc=fb_doc)
		self.assertEqual(res["lanes"]["booking"]["count"], 1)
		item = res["lanes"]["booking"]["items"][0]
		self.assertEqual(item["stage"], "booking")
		self.assertEqual(item["freight_booking"], "FB-001")

	def test_po_in_transit_lands_in_transit_lane(self):
		fb_doc = {
			"name": "FB-002",
			"status": "In Transit",
			"purchase_order": "PO-2026-002",
			"custom_crm_deal": "CRM-DEAL-002",
		}
		res = self._run_queue(fb_doc=fb_doc)
		self.assertEqual(res["lanes"]["transit"]["count"], 1)
		item = res["lanes"]["transit"]["items"][0]
		self.assertEqual(item["stage"], "transit")

	def test_po_border_crossed_lands_in_border_lane(self):
		fb_doc = {
			"name": "FB-003",
			"status": "Border Crossed",
			"purchase_order": "PO-2026-002",
			"custom_crm_deal": "CRM-DEAL-002",
		}
		res = self._run_queue(fb_doc=fb_doc)
		self.assertEqual(res["lanes"]["border"]["count"], 1)
		item = res["lanes"]["border"]["items"][0]
		self.assertEqual(item["stage"], "border")

	def test_po_delivered_lands_in_delivered_lane(self):
		fb_doc = {
			"name": "FB-004",
			"status": "Delivered",
			"purchase_order": "PO-2026-002",
			"custom_crm_deal": "CRM-DEAL-002",
		}
		res = self._run_queue(fb_doc=fb_doc)
		self.assertEqual(res["lanes"]["delivered"]["count"], 1)
		item = res["lanes"]["delivered"]["items"][0]
		self.assertEqual(item["stage"], "delivered")

	def test_po_goods_received_lands_in_accepted_lane(self):
		po = MagicMock(**{**self.po_base, "per_received": 100})
		res = self._run_queue(pos=[po])
		self.assertEqual(res["lanes"]["accepted"]["count"], 1)
		item = res["lanes"]["accepted"]["items"][0]
		self.assertEqual(item["stage"], "accepted")

	def test_logist_board_rejects_without_view_permission(self):
		with self.assertRaises(PermissionError):
			self._run_queue(view_allowed=False)


if __name__ == "__main__":
	unittest.main()
