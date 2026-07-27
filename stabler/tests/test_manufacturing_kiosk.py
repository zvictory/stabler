from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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
		# NOT required_items: those rows carry rate/amount, i.e. BOM cost data. The
		# same commit that wrote this assertion gated the payload to managers +
		# warehouse roles (api/manufacturing.py, "required_items visible to managers
		# and warehouse users"), so the assertion contradicted its own implementation
		# from day one. Operators get their transfer list from wo_transfer_preview,
		# which recomputes the rows without prices.
		self.assertNotIn("required_items", payload)
		self.assertNotIn("timeline", payload)
		# assert_ANY_call, not assert_called_with: the latter only inspects the LAST
		# call, and the payload reads three more custom fields (custom_batch_no /
		# _mfg_date / _expiry) after `operator`. The intent here is that `operator`
		# is read through .get() at all -- it is a custom field, so attribute access
		# would raise on a site that has not installed it.
		mock_doc.get.assert_any_call("operator")

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

	# Was two tests asserting that manufacturing.py rewrites the finished-goods
	# warehouse to "Tayyor mahsulot - <company abbr>". No such code has ever existed
	# (`git log -S "Tayyor mahsulot" -- stabler/api/manufacturing.py` is empty) --
	# they were written alongside the allow_zero_valuation_rate fix in c3d8475 and
	# were red from birth, which nobody saw because the bench-tests job has never
	# run. Deleted rather than implemented: a hardcoded Uzbek warehouse name is one
	# tenant's data leaking into shared code, exactly what CLAUDE.md's multi-tenant
	# rule forbids. If anjan really needs that override it belongs in
	# `Stabler Company Modules` as a setting, not in a constant.
	# What DID ship in c3d8475 is kept below.
	@patch("stabler.api.manufacturing._is_mfg_manager")
	def test_make_work_order_stock_entry_allows_zero_valuation_rate(self, mock_is_mgr):
		# Kiosk operators post Manufacture entries for items whose FG valuation is
		# still 0 (first run of a new product, or a BOM priced later). Without this
		# flag ERPNext refuses the entry and the shop floor is blocked mid-shift.
		mock_is_mgr.return_value = True

		mock_se = MagicMock()
		mock_se.company = "Test Company"
		mock_item = MagicMock()
		mock_se.items = [mock_item]

		with patch("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", return_value=mock_se), \
		     patch("stabler.api.manufacturing.frappe.get_doc", return_value=mock_se), \
		     patch("stabler.api.manufacturing._require_mfg"):
			from stabler.api.manufacturing import make_work_order_stock_entry
			make_work_order_stock_entry("WO-00001", "Manufacture", qty=5.0)

		self.assertEqual(mock_item.allow_zero_valuation_rate, 1)
		self.assertTrue(mock_se.insert.called)
		self.assertTrue(mock_se.submit.called)

	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.new_doc")
	def test_tomorrow_wo_material_request_creation(self, mock_new_doc, mock_exists):
		# Setup
		from frappe.utils import add_days, getdate, today
		mock_exists.return_value = False # no existing MR

		# Mock Work Order doc
		mock_wo = MagicMock()
		mock_wo.name = "WO-TOMORROW"
		mock_wo.company = "Test Company"
		mock_wo.wip_warehouse = "WIP Wh"
		# Set planned start date to tomorrow
		mock_wo.planned_start_date = str(add_days(getdate(today()), 1))

		mock_req_item = MagicMock()
		mock_req_item.item_code = "RAW-01"
		mock_req_item.required_qty = 100.0
		mock_wo.required_items = [mock_req_item]

		# Mock MR doc
		mock_mr = MagicMock()
		mock_new_doc.return_value = mock_mr

		orig_get_value = frappe.db.get_value
		def get_value_side_effect(*args, **kwargs):
			# Mock actual stock in WIP Wh as 40.0 (shortage = 60.0)
			if args and args[0] == "Bin":
				return 40.0
			return orig_get_value(*args, **kwargs)

		from stabler.api.manufacturing import create_material_request_for_tomorrow_wo

		with patch("stabler.api.manufacturing.frappe.db.get_value", side_effect=get_value_side_effect):
			create_material_request_for_tomorrow_wo(mock_wo)

		# Assert MR was created and submitted
		mock_new_doc.assert_called_with("Material Request")
		self.assertEqual(mock_mr.material_request_type, "Transfer")
		self.assertEqual(mock_mr.work_order, "WO-TOMORROW")
		self.assertTrue(mock_mr.append.called)
		# Assert shortage quantity (100.0 - 40.0 = 60.0) is appended
		mock_mr.append.assert_called_with("items", {
			"item_code": "RAW-01",
			"qty": 60.0,
			"warehouse": "WIP Wh",
			"schedule_date": mock_wo.planned_start_date
		})
		self.assertTrue(mock_mr.insert.called)
		self.assertTrue(mock_mr.submit.called)

	@patch("stabler.api.inventory.frappe.session")
	@patch("stabler.api.inventory.frappe.get_roles")
	@patch("stabler.api.inventory.frappe.db.sql")
	@patch("stabler.api.inventory.frappe.db.get_all")
	@patch("stabler.api.inventory.frappe.db.exists")
	@patch("stabler.api.inventory.frappe.db.get_value")
	@patch("frappe.permissions.get_user_permissions")
	def test_restricted_operator_warehouse_filters(self, mock_get_user_perms, mock_get_value, mock_exists, mock_get_all, mock_sql, mock_get_roles, mock_session):
		# Setup
		mock_session.user = "operator@example.com"
		mock_get_roles.return_value = ["Manufacturing User"]
		mock_exists.return_value = True
		mock_get_user_perms.return_value = {}

		def get_value_side_effect(dt, name, fieldname=None):
			if dt == "Warehouse" and name == "WIP-4":
				return "All Warehouses"
			return None
		mock_get_value.side_effect = get_value_side_effect

		# Mock Operator Work Order WIP Warehouse (only allowed to see "WIP-4")
		mock_get_all.return_value = ["WIP-4"]

		# Mock frappe.db.sql return for list_warehouses
		def sql_side_effect(query, *args, **kwargs):
			if "tabWarehouse" in query:
				return [
					{"name": "WIP-4", "warehouse_name": "WIP-4", "parent_warehouse": "All Warehouses", "is_group": 0, "warehouse_type": "WIP", "disabled": 0, "lft": 2, "rgt": 3},
					{"name": "WIP-5", "warehouse_name": "WIP-5", "parent_warehouse": "All Warehouses", "is_group": 0, "warehouse_type": "WIP", "disabled": 0, "lft": 4, "rgt": 5},
					{"name": "All Warehouses", "warehouse_name": "All Warehouses", "parent_warehouse": None, "is_group": 1, "warehouse_type": None, "disabled": 0, "lft": 1, "rgt": 6}
				]
			if "tabBin" in query:
				if "item_code" in query:
					return [
						{"item_code": "ITEM-1", "item_name": "Item 1", "item_group": "Group 1", "stock_uom": "Nos", "actual_qty": 10.0, "reserved_qty": 2.0, "ordered_qty": 0.0, "projected_qty": 8.0, "valuation_rate": 10.0}
					]
				else:
					return [
						("WIP-4", 100.0),
						("WIP-5", 200.0)
					]
			return []
		mock_sql.side_effect = sql_side_effect

		from stabler.api.inventory import list_warehouses, warehouse_stock

		# Call list_warehouses
		warehouses = list_warehouses("Test Company")

		# Operator should only see WIP-4 and All Warehouses (as parent), not WIP-5
		names = [w["name"] for w in warehouses]
		self.assertIn("WIP-4", names)
		self.assertIn("All Warehouses", names)
		self.assertNotIn("WIP-5", names)

		# Accessing WIP-4 stock should pass
		res = warehouse_stock("Test Company", "WIP-4")
		self.assertEqual(res["warehouse"], "WIP-4")

		# Accessing WIP-5 stock should raise PermissionError
		with self.assertRaises(PermissionError):
			warehouse_stock("Test Company", "WIP-5")

if __name__ == "__main__":
	unittest.main()
