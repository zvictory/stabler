from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
import frappe
from frappe import PermissionError
from stabler.api.manufacturing import work_order_detail

class TestManufacturingKiosk(unittest.TestCase):
	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	def test_operator_a_viewing_own_work_order(self, mock_session, mock_is_wh, mock_is_mgr, mock_get_doc, mock_exists, mock_assert_can_read, mock_require_mfg):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = False
		mock_session.user = "operator_a@example.com"
		
		# Mock required item
		mock_req_item = MagicMock()
		mock_req_item.item_code = "RAW-001"
		mock_req_item.item_name = "Raw Material 1"
		mock_req_item.required_qty = 5.0
		mock_req_item.transferred_qty = 2.0
		mock_req_item.consumed_qty = 1.0
		mock_req_item.source_warehouse = "Source Wh"
		mock_req_item.rate = 10.0
		mock_req_item.amount = 50.0
		
		mock_doc = MagicMock()
		mock_doc.name = "WO-00001"
		mock_doc.production_item = "FG-001"
		mock_doc.item_name = "Finished Good 1"
		mock_doc.qty = 10.0
		mock_doc.produced_qty = 0.0
		mock_doc.material_transferred_for_manufacturing = 2.0
		mock_doc.status = "Not Started"
		mock_doc.docstatus = 1
		mock_doc.planned_start_date = "2026-06-12"
		mock_doc.planned_end_date = "2026-06-13"
		mock_doc.fg_warehouse = "FG Wh"
		mock_doc.wip_warehouse = "WIP Wh"
		mock_doc.source_warehouse = "Source Wh"
		mock_doc.company = "Test Company"
		mock_doc.bom_no = "BOM-001"
		mock_doc.required_items = [mock_req_item]
		mock_doc.get.return_value = "operator_a@example.com" # for doc.get("operator")
		
		mock_get_doc.return_value = mock_doc
		
		# Call work_order_detail
		payload = work_order_detail("WO-00001")
		
		# Asserts for Operator A (non-manager, non-warehouse)
		self.assertEqual(payload["name"], "WO-00001")
		self.assertNotIn("bom_no", payload)
		self.assertNotIn("required_items", payload)
		self.assertNotIn("timeline", payload)
		mock_doc.get.assert_called_with("operator")

	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	def test_operator_a_viewing_operator_b_work_order_fails(self, mock_session, mock_is_wh, mock_is_mgr, mock_get_doc, mock_exists, mock_assert_can_read, mock_require_mfg):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = False
		mock_session.user = "operator_a@example.com" # current user is Operator A
		
		mock_doc = MagicMock()
		mock_doc.get.return_value = "operator_b@example.com" # operator assigned is Operator B
		mock_get_doc.return_value = mock_doc
		
		# Expect PermissionError (IDOR Guard)
		with self.assertRaises(PermissionError):
			work_order_detail("WO-00002")

	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	def test_warehouse_user_viewing_work_order(self, mock_session, mock_is_wh, mock_is_mgr, mock_get_doc, mock_exists, mock_assert_can_read, mock_require_mfg):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = True # User is in warehouse role
		mock_session.user = "warehouse@example.com"
		
		# Mock required item
		mock_req_item = MagicMock()
		mock_req_item.item_code = "RAW-001"
		mock_req_item.item_name = "Raw Material 1"
		mock_req_item.required_qty = 5.0
		mock_req_item.transferred_qty = 2.0
		mock_req_item.consumed_qty = 1.0
		mock_req_item.source_warehouse = "Source Wh"
		mock_req_item.rate = 10.0
		mock_req_item.amount = 50.0
		
		mock_doc = MagicMock()
		mock_doc.name = "WO-00001"
		mock_doc.bom_no = "BOM-001"
		mock_doc.required_items = [mock_req_item]
		mock_doc.get.return_value = "operator_a@example.com"
		mock_get_doc.return_value = mock_doc
		
		# Call work_order_detail
		payload = work_order_detail("WO-00001")
		
		# Asserts for Warehouse user: gets required_items but NOT bom_no or rates/amounts
		self.assertNotIn("bom_no", payload)
		self.assertIn("required_items", payload)
		self.assertNotIn("timeline", payload)
		
		req_items_payload = payload["required_items"]
		self.assertEqual(len(req_items_payload), 1)
		self.assertEqual(req_items_payload[0]["item_code"], "RAW-001")
		self.assertNotIn("rate", req_items_payload[0])
		self.assertNotIn("amount", req_items_payload[0])

	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	@patch("stabler.api.manufacturing.frappe.get_all")
	def test_manager_viewing_work_order(self, mock_get_all, mock_session, mock_is_wh, mock_is_mgr, mock_get_doc, mock_exists, mock_assert_can_read, mock_require_mfg):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = True # User is manager
		mock_is_wh.return_value = False
		mock_session.user = "manager@example.com"
		
		# Mock timeline comments
		mock_get_all.return_value = [
			{"name": "COMM-001", "content": "Started Work Order", "creation": "2026-06-12 10:00:00", "comment_by": "operator_a@example.com"}
		]
		
		# Mock required item
		mock_req_item = MagicMock()
		mock_req_item.item_code = "RAW-001"
		mock_req_item.item_name = "Raw Material 1"
		mock_req_item.required_qty = 5.0
		mock_req_item.transferred_qty = 2.0
		mock_req_item.consumed_qty = 1.0
		mock_req_item.source_warehouse = "Source Wh"
		mock_req_item.rate = 10.0
		mock_req_item.amount = 50.0
		
		mock_doc = MagicMock()
		mock_doc.name = "WO-00001"
		mock_doc.bom_no = "BOM-001"
		mock_doc.required_items = [mock_req_item]
		mock_doc.get.return_value = "operator_a@example.com"
		mock_get_doc.return_value = mock_doc
		
		# Call work_order_detail
		payload = work_order_detail("WO-00001")
		
		# Asserts for Manager: gets EVERYTHING (required_items with rates, bom_no, and timeline)
		self.assertEqual(payload["bom_no"], "BOM-001")
		self.assertIn("required_items", payload)
		self.assertIn("timeline", payload)
		
		req_items_payload = payload["required_items"]
		self.assertEqual(len(req_items_payload), 1)
		self.assertEqual(req_items_payload[0]["item_code"], "RAW-001")
		self.assertEqual(req_items_payload[0]["rate"], 10.0)
		self.assertEqual(req_items_payload[0]["amount"], 50.0)
		
		timeline_payload = payload["timeline"]
		self.assertEqual(len(timeline_payload), 1)
		self.assertEqual(timeline_payload[0]["name"], "COMM-001")

if __name__ == "__main__":
	unittest.main()
