from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

import frappe
from frappe import PermissionError

from stabler.api.manufacturing import (
	_SE_CONSUMPTION,
	SweepNotAcknowledged,
	_assert_may_consume,
	_assert_roles_are_both_or_neither,
	_clear_finish_draft,
	_require_wo_draft_columns,
	_sweep_risk_rows,
	make_work_order_stock_entry,
	wo_consumption_preview,
	work_order_detail,
)


class TestManufacturingKiosk(unittest.TestCase):
	@patch("stabler.api.manufacturing._item_roles")
	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	def test_operator_a_viewing_own_work_order(
		self,
		mock_session,
		mock_is_wh,
		mock_is_mgr,
		mock_get_doc,
		mock_exists,
		mock_assert_can_read,
		mock_require_mfg,
		mock_item_roles,
	):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = False
		mock_session.user = "operator_a@example.com"
		mock_item_roles.return_value = {"RAW-001": "Production"}

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
		# A real Work Order always has one, and work_order_detail reads it to name
		# the currency the per-role deviation totals are in.
		mock_doc.company = "_Test Company"
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
		mock_doc.get.return_value = "operator_a@example.com"  # for doc.get("operator")

		mock_get_doc.return_value = mock_doc

		# Call work_order_detail
		payload = work_order_detail("WO-00001")

		# Asserts for Operator A (non-manager, non-warehouse)
		self.assertEqual(payload["name"], "WO-00001")
		self.assertNotIn("bom_no", payload)
		# This assertion used to read `assertNotIn("required_items", payload)`. What it
		# was really guarding is named in its own comment: those rows carry rate and
		# amount, i.e. BOM cost data. Withholding the whole key was how that was
		# enforced, because before role-scoped consumption there was no subset worth
		# handing over — operators rebuilt their list from wo_transfer_preview.
		# Now each role writes off its own lines, so the subset is the point. The
		# cost guard is unchanged and asserted directly instead of by omission.
		self.assertEqual([r["item_code"] for r in payload["required_items"]], ["RAW-001"])
		for row in payload["required_items"]:
			self.assertNotIn("rate", row, "operator payload leaked BOM cost data")
			self.assertNotIn("amount", row, "operator payload leaked BOM cost data")
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
	def test_operator_a_viewing_operator_b_work_order_fails(
		self,
		mock_session,
		mock_is_wh,
		mock_is_mgr,
		mock_get_doc,
		mock_exists,
		mock_assert_can_read,
		mock_require_mfg,
	):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = False
		mock_session.user = "operator_a@example.com"  # current user is Operator A

		mock_doc = MagicMock()
		mock_doc.get.return_value = "operator_b@example.com"  # operator assigned is Operator B
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
	def test_warehouse_user_viewing_work_order(
		self,
		mock_session,
		mock_is_wh,
		mock_is_mgr,
		mock_get_doc,
		mock_exists,
		mock_assert_can_read,
		mock_require_mfg,
	):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = True  # User is in warehouse role
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
		# A real Work Order always has one, and work_order_detail reads it to name
		# the currency the per-role deviation totals are in.
		mock_doc.company = "_Test Company"
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
	def test_manager_viewing_work_order(
		self,
		mock_get_all,
		mock_session,
		mock_is_wh,
		mock_is_mgr,
		mock_get_doc,
		mock_exists,
		mock_assert_can_read,
		mock_require_mfg,
	):
		# Setup
		mock_exists.return_value = True
		mock_is_mgr.return_value = True  # User is manager
		mock_is_wh.return_value = False
		mock_session.user = "manager@example.com"

		# Mock timeline comments
		mock_get_all.return_value = [
			{
				"name": "COMM-001",
				"content": "Started Work Order",
				"creation": "2026-06-12 10:00:00",
				"comment_by": "operator_a@example.com",
			}
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
		# A real Work Order always has one, and work_order_detail reads it to name
		# the currency the per-role deviation totals are in.
		mock_doc.company = "_Test Company"
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

		with (
			patch(
				"erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", return_value=mock_se
			),
			patch("stabler.api.manufacturing.frappe.get_doc", return_value=mock_se),
			patch("stabler.api.manufacturing._require_mfg"),
		):
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

		mock_exists.return_value = False  # no existing MR

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
		mock_mr.append.assert_called_with(
			"items",
			{
				"item_code": "RAW-01",
				"qty": 60.0,
				"warehouse": "WIP Wh",
				"schedule_date": mock_wo.planned_start_date,
			},
		)
		self.assertTrue(mock_mr.insert.called)
		self.assertTrue(mock_mr.submit.called)

	@patch("stabler.api.inventory.frappe.session")
	@patch("stabler.api.inventory.frappe.get_roles")
	@patch("stabler.api.inventory.frappe.db.sql")
	@patch("stabler.api.inventory.frappe.db.get_all")
	@patch("stabler.api.inventory.frappe.db.exists")
	@patch("stabler.api.inventory.frappe.db.get_value")
	@patch("frappe.permissions.get_user_permissions")
	def test_restricted_operator_warehouse_filters(
		self,
		mock_get_user_perms,
		mock_get_value,
		mock_exists,
		mock_get_all,
		mock_sql,
		mock_get_roles,
		mock_session,
	):
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
					{
						"name": "WIP-4",
						"warehouse_name": "WIP-4",
						"parent_warehouse": "All Warehouses",
						"is_group": 0,
						"warehouse_type": "WIP",
						"disabled": 0,
						"lft": 2,
						"rgt": 3,
					},
					{
						"name": "WIP-5",
						"warehouse_name": "WIP-5",
						"parent_warehouse": "All Warehouses",
						"is_group": 0,
						"warehouse_type": "WIP",
						"disabled": 0,
						"lft": 4,
						"rgt": 5,
					},
					{
						"name": "All Warehouses",
						"warehouse_name": "All Warehouses",
						"parent_warehouse": None,
						"is_group": 1,
						"warehouse_type": None,
						"disabled": 0,
						"lft": 1,
						"rgt": 6,
					},
				]
			if "tabBin" in query:
				if "item_code" in query:
					return [
						{
							"item_code": "ITEM-1",
							"item_name": "Item 1",
							"item_group": "Group 1",
							"stock_uom": "Nos",
							"actual_qty": 10.0,
							"reserved_qty": 2.0,
							"ordered_qty": 0.0,
							"projected_qty": 8.0,
							"valuation_rate": 10.0,
						}
					]
				else:
					return [("WIP-4", 100.0), ("WIP-5", 200.0)]
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


class TestWorkOrderTwoOperatorRoles(unittest.TestCase):
	"""One order, two operators — the access gate has to admit both (patch v97).

	Before v97 a Work Order named one `operator`, and that field was also the IDOR
	guard. On anjan's floor the same order is poured by one person and packed by
	another, so under the old rule whichever of the two was not named in that single
	field could not open the order at all: not the detail, not the transfer preview,
	not the finish. Naming the packer instead simply moved the blindness onto the
	pourer. These tests hold the gate open for both roles and shut for everyone else.
	"""

	@staticmethod
	def _doc(production, packaging):
		"""A Work Order mock whose custom fields answer per fieldname.

		The older cases in this file set a single `get.return_value`, which cannot
		express "A pours, B packs" — the shape the whole feature is about.
		"""
		doc = MagicMock()
		doc.name = "WO-00003"
		doc.company = "_Test Company"
		doc.required_items = []
		values = {"operator": production, "packaging_operator": packaging}
		doc.get.side_effect = lambda field, *a: values.get(field)
		return doc

	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	def test_packaging_operator_may_open_the_order_they_pack(
		self,
		mock_session,
		mock_is_wh,
		mock_is_mgr,
		mock_get_doc,
		mock_exists,
		mock_assert_can_read,
		mock_require_mfg,
	):
		"""The packer is an assignee of the order, not a stranger to it.

		This is the case the single-field guard got wrong: production is someone
		else's name, so the old comparison refused the person actually holding the
		packing station.
		"""
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = False
		mock_session.user = "packer@example.com"
		mock_get_doc.return_value = self._doc("pourer@example.com", "packer@example.com")

		payload = work_order_detail("WO-00003")

		self.assertEqual(payload["packaging_operator"], "packer@example.com")
		self.assertEqual(payload["operator"], "pourer@example.com")

	@patch("stabler.api.manufacturing._require_mfg")
	@patch("stabler.api.manufacturing._assert_can_read")
	@patch("stabler.api.manufacturing.frappe.db.exists")
	@patch("stabler.api.manufacturing.frappe.get_doc")
	@patch("stabler.api.manufacturing._is_mfg_manager")
	@patch("stabler.api.manufacturing._is_warehouse_role")
	@patch("stabler.api.manufacturing.frappe.session")
	def test_second_role_does_not_open_the_order_to_everyone_else(
		self,
		mock_session,
		mock_is_wh,
		mock_is_mgr,
		mock_get_doc,
		mock_exists,
		mock_assert_can_read,
		mock_require_mfg,
	):
		"""Widening the gate from one name to two must not widen it to any name.

		`any(doc.get(f) == user ...)` fails open the moment an unassigned role and
		an unknown caller are both falsy, so this asserts the negative directly
		with the packing slot deliberately empty.
		"""
		mock_exists.return_value = True
		mock_is_mgr.return_value = False
		mock_is_wh.return_value = False
		mock_session.user = "stranger@example.com"
		mock_get_doc.return_value = self._doc("pourer@example.com", None)

		with self.assertRaises(PermissionError):
			work_order_detail("WO-00003")

	@patch("stabler.api.manufacturing.frappe.db.has_column")
	def test_assigning_a_packer_before_migrate_fails_loudly(self, mock_has_column):
		"""A site missing the column must refuse the write, not swallow it.

		Reads degrade on purpose in that window so the floor keeps working. Writes
		must not: Frappe drops an unknown key before `get_valid_dict()` sees it, so
		without this guard the packer is simply not recorded, `set_value` reports
		success, and the manager re-assigns the same person forever with no error
		anywhere. Silent is the one outcome worse than broken.
		"""
		from stabler.api.manufacturing import _require_wo_operator_column

		mock_has_column.side_effect = lambda _dt, col: col == "operator"

		with self.assertRaises(Exception):
			_require_wo_operator_column("packaging_operator")

		# The production role predates v97, so it stays writable on such a site.
		_require_wo_operator_column("operator")

	def test_one_person_cannot_hold_both_roles_on_one_order(self):
		"""Pouring and packing are counted separately per person.

		Both slots on one name makes material use, rejects and minutes
		indistinguishable between the two stations — which is exactly the
		measurement the split was made to produce.
		"""
		from stabler.api.manufacturing import _assert_distinct_operators

		with self.assertRaises(Exception):
			_assert_distinct_operators("same@example.com", "same@example.com")

		# The legitimate shapes stay legal: two people, or a role left unfilled.
		_assert_distinct_operators("pourer@example.com", "packer@example.com")
		_assert_distinct_operators("pourer@example.com", None)
		_assert_distinct_operators(None, None)


class TestOperatorSeesOnlyTheirOwnMaterials(unittest.TestCase):
	"""One order, two sheets. The packer must not be able to write off cream.

	Until now the API handed operators no material list at all — `required_items`
	went to managers and warehouse staff only, and the kiosk worked around it by
	asking for the whole transfer preview, both roles included. That was survivable
	while transfer was the only stock document an operator posted, because transfer
	is genuinely one document for the whole order. It stops being survivable the
	moment each role posts its own consumption entry: hand a pourer the label lines
	and the loss lands on the wrong person's KPI, silently and permanently.
	"""

	ROLES: ClassVar = {"RAW-MLK": "Production", "PKG-LBL": "Packaging", "RAW-NEW": ""}

	@staticmethod
	def _item(code):
		it = MagicMock()
		it.item_code = code
		it.item_name = code
		it.required_qty = 10.0
		it.transferred_qty = 10.0
		it.consumed_qty = 0.0
		it.source_warehouse = "Stores - X"
		it.rate = 1.0
		it.amount = 10.0
		return it

	@classmethod
	def _doc(cls, production, packaging):
		doc = MagicMock()
		doc.name = "WO-00009"
		doc.company = "_Test Company"
		doc.required_items = [cls._item(c) for c in cls.ROLES]
		values = {"operator": production, "packaging_operator": packaging}
		doc.get.side_effect = lambda field, *a: values.get(field)
		return doc

	def _detail(self, user, is_mgr=False):
		"""Call work_order_detail as `user`, with the item role map stubbed."""
		stack = [
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._assert_can_read"),
			patch("stabler.api.manufacturing.frappe.db.exists", return_value=True),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=is_mgr),
			patch("stabler.api.manufacturing._is_warehouse_role", return_value=False),
			patch("stabler.api.manufacturing._item_roles", return_value=self.ROLES),
			patch(
				"stabler.api.manufacturing.frappe.get_doc",
				return_value=self._doc("pourer@x.uz", "packer@x.uz"),
			),
			patch("stabler.api.manufacturing.frappe.session"),
		]
		started = [c.start() for c in stack]
		started[-1].user = user
		try:
			return work_order_detail("WO-00009")
		finally:
			for c in reversed(stack):
				c.stop()

	def test_pourer_gets_the_raw_material_and_not_the_label(self):
		out = self._detail("pourer@x.uz")
		self.assertEqual(out["my_role"], "Production")
		codes = [r["item_code"] for r in out["required_items"]]
		self.assertEqual(codes, ["RAW-MLK"])

	def test_packer_gets_the_label_and_not_the_cream(self):
		out = self._detail("packer@x.uz")
		self.assertEqual(out["my_role"], "Packaging")
		codes = [r["item_code"] for r in out["required_items"]]
		self.assertEqual(codes, ["PKG-LBL"])

	def test_an_undecided_line_is_counted_out_loud_and_given_to_neither(self):
		"""v98 ships every Item with an empty role on purpose, so this is the
		common case on day one, not an edge case. It must be visible rather than
		quietly folded into one of the two sheets."""
		for user in ("pourer@x.uz", "packer@x.uz"):
			out = self._detail(user)
			self.assertNotIn("RAW-NEW", [r["item_code"] for r in out["required_items"]])
			self.assertEqual(out["unassigned_item_count"], 1)

	def test_the_manager_still_sees_every_line(self):
		"""The shift lead is who an undecided line belongs to, so their list cannot
		shrink — this is the half that makes the counter actionable."""
		out = self._detail("nodira@x.uz", is_mgr=True)
		self.assertEqual([r["item_code"] for r in out["required_items"]], ["RAW-MLK", "PKG-LBL", "RAW-NEW"])
		self.assertIsNone(out["my_role"])

	def test_every_row_carries_the_role_that_decided_it(self):
		"""So the manager screen can show responsibility per line rather than
		leaving the reader to infer it from the unit of measure."""
		out = self._detail("nodira@x.uz", is_mgr=True)
		by_code = {r["item_code"]: r["operator_role"] for r in out["required_items"]}
		self.assertEqual(by_code, {"RAW-MLK": "Production", "PKG-LBL": "Packaging", "RAW-NEW": None})


if __name__ == "__main__":
	unittest.main()


class TestOnlyYourOwnMaterialsCanBeWrittenOff(unittest.TestCase):
	"""The write-off is the moment the split stops being cosmetic.

	ERPNext does not enforce any of this. `Work Order Item.consumed_qty` accumulates
	whatever quantity any submitted entry happens to name, so a pourer who taps
	through the packer's label rolls moves that loss onto their own document and out
	of the packer's — both KPIs wrong, both wrong quietly, and nothing in the
	stock ledger recording that the two people were ever different. The guard is the
	only thing standing there.
	"""

	ROLES: ClassVar = {"RAW-MLK": "Production", "PKG-LBL": "Packaging", "RAW-NEW": ""}
	WO: ClassVar = {"operator": "pourer@x.uz", "packaging_operator": "packer@x.uz"}

	def _guard(self, codes, user="pourer@x.uz", role_scoped=True, enabled=True):
		stack = [
			patch("stabler.api.manufacturing._material_consumption_enabled", return_value=enabled),
			patch("stabler.api.manufacturing._item_roles", return_value=self.ROLES),
			patch("stabler.api.manufacturing._wo_operator_columns", return_value=tuple(self.WO)),
			patch("stabler.api.manufacturing.frappe.db.get_value", return_value=dict(self.WO)),
			patch("stabler.api.manufacturing.frappe.session"),
		]
		started = [c.start() for c in stack]
		started[-1].user = user
		try:
			_assert_may_consume("WO-00009", [{"item_code": c, "qty": 1} for c in codes], role_scoped)
		finally:
			for c in reversed(stack):
				c.stop()

	def test_the_setting_being_off_is_refused_rather_than_miscounted(self):
		"""`material_consumption` ships off, so this is what an un-migrated site hits
		first — and ERPNext does not stop it.

		Measured on genesis-test 2026-08-25 against a fully-consumed Work Order: with
		the setting on the pending list came back empty, with it off it came back as
		the full BOM. So the failure is not a confusing error, it is a write-off of
		material that was already written off, counted onto `consumed_qty` twice.
		There is nothing to translate or re-word downstream; the refusal has to
		originate here, and name the setting so someone can go and switch it on.
		"""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._guard(["RAW-MLK"], enabled=False)
		self.assertIn("Allow Continuous Material Consumption", str(cm.exception))

	def test_an_empty_selection_is_refused(self):
		"""Not pedantry: `make_work_order_stock_entry` only overrides `se.items` when
		the caller sends some. An empty list falls through to ERPNext's own BOM
		expansion, which writes off the whole order — both roles — under one name.
		"""
		with self.assertRaises(frappe.ValidationError):
			self._guard([])

	def test_the_other_operators_material_is_refused_by_name(self):
		"""The item code is in the message because the operator can act on it: it
		tells them they are on the wrong sheet, not that the system is broken."""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._guard(["RAW-MLK", "PKG-LBL"])
		self.assertIn("PKG-LBL", str(cm.exception))

	def test_material_nobody_has_assigned_is_refused_as_undecided(self):
		"""A separate message from the wrong-role one, because the remedy is
		different and belongs to someone else. Nobody has decided this line's role —
		v98 leaves it empty rather than guessing — so it is the shift lead's to
		settle, and an operator told "not yours" would go looking for a colleague who
		does not exist.
		"""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._guard(["RAW-NEW"])
		self.assertIn("RAW-NEW", str(cm.exception))
		self.assertNotIn("other operator", str(cm.exception))

	def test_your_own_material_passes(self):
		self._guard(["RAW-MLK"])

	def test_a_manager_writes_off_whatever_they_choose(self):
		"""Deciding on behalf of the floor is the manager's job — a line nobody has
		classified still has to be written off by someone before the order closes."""
		self._guard(["RAW-MLK", "PKG-LBL", "RAW-NEW"], user="boss@x.uz", role_scoped=False)

	def test_the_endpoint_refuses_before_it_builds_anything(self):
		"""The guard has to run ahead of ERPNext, not alongside it.

		`make_stock_entry` reads the BOM, prices every row and reserves batches. If
		the refusal came after that, a rejected write-off would still have done all
		of it — and any later reordering of this function would move the guard behind
		an `insert()` with no test noticing. So this asserts the order, not just the
		refusal.
		"""
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=False),
			patch("stabler.api.manufacturing._require_own_work_order"),
			patch(
				"stabler.api.manufacturing._assert_may_consume", side_effect=frappe.ValidationError("nope")
			) as guard,
			patch("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry") as build,
		):
			with self.assertRaises(frappe.ValidationError):
				make_work_order_stock_entry(
					"WO-00009", _SE_CONSUMPTION, items='[{"item_code": "PKG-LBL", "qty": 1}]'
				)
		guard.assert_called_once()
		build.assert_not_called()


class _FakeStockEntry:
	"""Just enough Stock Entry for `make_work_order_stock_entry` to fill in.

	A MagicMock cannot stand in here: the assertion is about which attributes end
	up set to what, and a mock answers every attribute with a new mock, so every
	assertion about a warehouse would pass whatever the code did.
	"""

	def __init__(self, stub):
		self.__dict__.update(stub)
		self.items = []
		self.name = "STE-FAKE"
		self.docstatus = 0
		self.inserted = False

	def append(self, key, _value):
		row = SimpleNamespace()
		getattr(self, key).append(row)
		return row

	def set(self, key, value):
		setattr(self, key, value)

	def set_missing_values(self):
		pass

	def insert(self, **_kw):
		self.inserted = True

	def submit(self):
		self.docstatus = 1


class TestConsumedMaterialDoesNotArriveAnywhere(unittest.TestCase):
	"""A consumption entry has a source and no target: the material leaves WIP and
	is gone. ERPNext's own rows get this right — measured on genesis-test 2026-08-25,
	`make_stock_entry` returns rows with an empty `t_warehouse`.

	What it also does is put `fg_warehouse` on the *header*, because its
	`make_stock_entry` treats every non-transfer purpose as one that receipts
	something. Harmless while ERPNext builds the rows; not harmless here, where the
	kiosk sends its own rows and each one inherits `se.to_warehouse`. That would
	receipt raw milk into finished goods — stock the floor never made, at a
	valuation nobody chose, on the same order that is about to receipt the real
	output.
	"""

	STUB: ClassVar = {
		"purpose": _SE_CONSUMPTION,
		"work_order": "WO-00009",
		"from_warehouse": "WIP - X",
		"to_warehouse": "Finished Goods - X",  # ERPNext's doing, and the whole problem
	}

	def _post(self, items):
		se_holder = {}

		def _get_doc(stub):
			se_holder["se"] = _FakeStockEntry(stub)
			return se_holder["se"]

		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch("stabler.api.manufacturing._assert_may_consume"),
			patch("stabler.api.manufacturing.assert_stock_entry_valuation_sane"),
			patch("stabler.api.manufacturing._log_wo_event"),
			patch("stabler.api.manufacturing.frappe.get_doc", side_effect=_get_doc),
			patch("stabler.api.manufacturing.frappe.session"),
			patch(
				"erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				return_value=dict(self.STUB),
			),
			patch(
				"erpnext.stock.get_item_details.get_conversion_factor",
				return_value={"conversion_factor": 1.0},
			),
		):
			make_work_order_stock_entry("WO-00009", _SE_CONSUMPTION, items=items)
		return se_holder["se"]

	def test_caller_supplied_rows_get_no_target_warehouse(self):
		se = self._post('[{"item_code": "RAW-MLK", "qty": 5}]')
		self.assertEqual([r.s_warehouse for r in se.items], ["WIP - X"])
		self.assertEqual(
			[r.t_warehouse for r in se.items],
			[None],
			"consumed material was given somewhere to arrive",
		)

	def test_the_header_target_is_cleared_too(self):
		"""Clearing only the rows would leave the document itself claiming a
		destination, and ERPNext re-derives row warehouses from the header in more
		than one place — `set_missing_values` among them."""
		se = self._post('[{"item_code": "RAW-MLK", "qty": 5}]')
		self.assertIsNone(se.to_warehouse)


class TestAHalfAssignedOrderCannotStart(unittest.TestCase):
	"""One role filled and the other empty is not a partial setup — it is a silent
	miscount waiting to happen.

	`list_work_orders` filters an operator's list by the assignee columns, so the
	person who was never named cannot see the order at all. They never write off
	their own materials, and ERPNext's Manufacture entry sweeps every unconsumed
	line into whoever presses finish. The order completes, the numbers look
	plausible, and the packer's kilograms are on the pourer's document — which is
	the exact number the split was created to separate.

	An order with *neither* role filled is a different thing: a site that is not
	using the split. Refusing those would stop every shop floor on the day this
	deploys, for orders that were never half-anything.
	"""

	@staticmethod
	def _wo(production, packaging):
		return {"operator": production, "packaging_operator": packaging}

	def _assert(self, production, packaging, purpose="Material Transfer for Manufacture"):
		with (
			patch(
				"stabler.api.manufacturing._wo_operator_columns",
				return_value=("operator", "packaging_operator"),
			),
			patch(
				"stabler.api.manufacturing.frappe.db.get_value",
				return_value=self._wo(production, packaging),
			),
		):
			_assert_roles_are_both_or_neither("WO-00009", purpose)

	def _refusal(self, purpose):
		"""The message an operator would read, or "" if the call was allowed."""
		try:
			self._assert("pourer@x.uz", "", purpose)
		except frappe.ValidationError as exc:
			return str(exc)
		return ""

	def test_the_refusal_names_the_gesture_the_operator_actually_performed(self):
		"""One guard now serves two buttons, and the first version of that reused
		one sentence for both — so an operator who pressed Finish was told that
		materials "cannot be transferred", naming a gesture they had not performed.
		On a kiosk with no Desk access that sends them hunting for a transfer screen
		that is not the problem.

		The half that must survive verbatim in both is "Missing: <role>". Naming the
		absent role is what turns a refusal into an instruction.
		"""
		finish = self._refusal("Manufacture")
		transfer = self._refusal("Material Transfer for Manufacture")

		self.assertNotEqual(finish, transfer, "both buttons still read the same sentence")
		self.assertNotIn("transferred", finish.lower(), "Finish still talks about transferring")
		self.assertIn("finish", finish.lower(), "Finish's refusal does not name finishing")
		self.assertIn("transferred", transfer.lower())
		for message in (finish, transfer):
			self.assertIn("Packaging", message, "the refusal stopped naming the missing role")

	def test_both_roles_assigned_passes(self):
		self._assert("pourer@x.uz", "packer@x.uz")

	def test_neither_role_assigned_passes(self):
		"""The site is not using the split. Nothing to be half of."""
		self._assert(None, None)

	def test_a_missing_packer_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as cm:
			self._assert("pourer@x.uz", None)
		self.assertIn("packaging", str(cm.exception).lower())

	def test_a_missing_pourer_is_refused(self):
		"""Symmetric on purpose: the packer is not the junior role, and an order run
		by a packer alone loses the raw material side the same way."""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._assert(None, "packer@x.uz")
		self.assertIn("production", str(cm.exception).lower())

	def test_a_blank_string_counts_as_unassigned(self):
		"""A cleared role and a never-set one are the same state.

		`assign_work_order_operator` clears a role by writing "" — the
		"- Remove operator -" option in the SPA — while a column nobody has touched
		is NULL. The guard reads emptiness, so both land together. Written as
		`is not None` it would pass every order a manager had explicitly emptied,
		which is the one case where somebody made the decision on purpose.
		"""
		with self.assertRaises(frappe.ValidationError):
			self._assert("pourer@x.uz", "")

	def test_the_transfer_endpoint_refuses_before_it_builds_anything(self):
		"""Same ordering requirement as the consumption guard: `make_stock_entry`
		reads the BOM and prices every row, and a refusal after that has already
		done the work it was meant to prevent."""
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch(
				"stabler.api.manufacturing._assert_roles_are_both_or_neither",
				side_effect=frappe.ValidationError("half-assigned"),
			) as guard,
			patch("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry") as build,
		):
			with self.assertRaises(frappe.ValidationError):
				make_work_order_stock_entry(
					"WO-00009",
					"Material Transfer for Manufacture",
					items='[{"item_code": "RAW-MLK", "qty": 1}]',
				)
		guard.assert_called_once()
		build.assert_not_called()

	def test_the_manufacture_endpoint_also_refuses_before_it_builds_anything(self):
		"""D1 (P0): until now `_assert_roles_are_both_or_neither` ran only on the
		transfer branch. A half-assigned order that skipped straight to Finish (the
		packer never wrote anything off because they could never open the order)
		reached ERPNext's Manufacture entry unchecked, which sweeps the packer's
		unconsumed lines onto the pourer's document — the exact misattribution the
		split exists to prevent, at the one moment (order close) it can no longer be
		corrected. Same ordering requirement as the transfer branch: refused before
		`make_stock_entry` builds anything, not after.

		The downstream Manufacture machinery (`frappe.get_doc`, valuation, event log)
		is mocked well enough to run to completion so that, without the fix, this
		fails on `assertRaises` itself ("ValidationError not raised") rather than on
		an unrelated mock-shape crash — red for the right reason, not an artifact of
		under-mocking.
		"""
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch(
				"stabler.api.manufacturing._assert_roles_are_both_or_neither",
				side_effect=frappe.ValidationError("half-assigned"),
			) as guard,
			patch("stabler.api.manufacturing.assert_stock_entry_valuation_sane"),
			patch("stabler.api.manufacturing._log_wo_event"),
			patch("stabler.api.manufacturing._clear_finish_draft"),
			patch("stabler.api.manufacturing.frappe.session"),
			patch("stabler.api.manufacturing.frappe.get_doc", side_effect=lambda stub: _FakeStockEntry(stub)),
			patch(
				"erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				return_value={"purpose": "Manufacture", "work_order": "WO-00009"},
			) as build,
		):
			with self.assertRaises(frappe.ValidationError):
				make_work_order_stock_entry("WO-00009", "Manufacture", qty=5)
		guard.assert_called_once()
		build.assert_not_called()


class TestFinishingDoesNotSweepTheOtherRole(unittest.TestCase):
	"""Failure B (P0, Part 3) — not the half-assigned order
	`_assert_roles_are_both_or_neither` already refuses. Both roles are
	legitimately on this order; one of them simply has not written their
	material off yet, which is the ordinary state of an order mid-shift, not a
	misconfiguration. ERPNext's Manufacture entry cannot tell the difference —
	`Work Order Item.consumed_qty` accumulates whatever entry names it, so it
	sweeps every line nobody has written off onto whoever posts the document.

	Measured live, genesis-test 2026-08-25: a fully assigned order, consumption
	on, the pourer wrote off his milk and the packer wrote off nothing. The
	pourer pressed Finish. It succeeded — MAT-STE-2026-00037 carries
	PROBE-LABEL, consumed_qty 0.0 -> 10.0, on the pourer's document. The
	deviation panel then scored the packer a clean on-plan shift for an order he
	never touched, and nothing in the timeline says any of this happened.
	"""

	ROWS: ClassVar = [
		{
			"item_code": "RAW-MLK",
			"item_name": "Milk",
			"qty": 20.0,
			"uom": "Litre",
			"s_warehouse": "WIP - X",
			"is_finished_item": 0,
		},
		{
			"item_code": "PKG-LBL",
			"item_name": "Label",
			"qty": 10.0,
			"uom": "Nos",
			"s_warehouse": "WIP - X",
			"is_finished_item": 0,
		},
	]
	ROLES: ClassVar = {"RAW-MLK": "Production", "PKG-LBL": "Packaging"}

	def _sweep(self, my_role, acknowledge_sweep=False, enabled=True, stub=None):
		from stabler.api.manufacturing import _assert_sweep_is_acknowledged

		with (
			patch("stabler.api.manufacturing._material_consumption_enabled", return_value=enabled),
			patch("stabler.api.manufacturing._item_roles", return_value=self.ROLES),
			patch(
				"erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				return_value={"items": self.ROWS if stub is None else stub},
			),
		):
			_assert_sweep_is_acknowledged("WO-00009", my_role, acknowledge_sweep)

	def test_the_pourer_is_refused_while_the_packer_has_not_written_off(self):
		"""The name, not the code: this reaches an operator on the kiosk, where
		item_name is the label they actually read (item_code is the small
		reference underneath). A deliberate divergence from `_assert_may_consume`,
		whose refusals name item_code instead — noted where the message is built."""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._sweep(my_role="Production")
		self.assertIn("Label", str(cm.exception))

	def test_acknowledging_lets_the_pourer_finish_anyway(self):
		self._sweep(my_role="Production", acknowledge_sweep=True)  # must not raise

	def test_the_refusal_carries_a_class_the_kiosk_can_match_on(self):
		"""This is the one refusal with an exit, and the kiosk has to recognise it
		to offer that exit — the preview and the Finish are two round trips, and
		an operator who met the refusal without having been previewed would
		otherwise have a wall and no checkbox.

		It cannot be recognised by its message: that string is translated into
		five languages, so matching its text works for the Turkish shift and
		strands the other four. Frappe returns the exception CLASS name on V1
		(`utils/response.py:52`), which is why this one has its own.

		Asserted as a strict subclass, not `frappe.ValidationError`: raising the
		plain parent again would keep every other test in this class green while
		the kiosk silently lost its exit."""
		with self.assertRaises(SweepNotAcknowledged):
			self._sweep(my_role="Production")
		self.assertTrue(issubclass(SweepNotAcknowledged, frappe.ValidationError))

	def test_a_role_is_never_refused_for_its_own_unwritten_off_material(self):
		"""Only the OTHER role's leftovers are a sweep risk. Your own shortfall is
		something you could still fix yourself before posting — it is not a
		cross-attribution, so it must not block you the way the other role's
		does."""
		self._sweep(my_role="Production", stub=[self.ROWS[0]])  # only their own line pending

	def test_a_manager_is_refused_too_because_they_hold_no_role_of_their_own(self):
		"""`my_role=None` is how `make_work_order_stock_entry` calls this for a
		manager. Every role-owned row is "someone else's" to a person who is not
		claiming a role — the sweep is exactly as invisible to them as to the
		other operator."""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._sweep(my_role=None)
		message = str(cm.exception)
		self.assertIn("Milk", message)
		self.assertIn("Label", message)

	def test_an_unassigned_line_is_not_named_as_someone_elses_sweep(self):
		"""An item with no role belongs to nobody in particular — the shift lead's
		open question (`_unassigned_rows`'s territory), not a cross-role sweep."""
		self._sweep(my_role="Production", stub=[{**self.ROWS[1], "item_code": "RAW-NEW"}])

	def test_the_setting_being_off_is_not_treated_as_a_sweep_risk(self):
		"""Same reasoning as `_assert_may_consume`: with the setting off there is no
		reliable "what is left" answer to give (`_material_consumption_enabled`),
		so there is nothing here to warn about either — D2 is the guard for that
		state, not this one."""
		self._sweep(my_role="Production", enabled=False)  # must not raise

	def test_the_endpoint_wires_the_guard_on_the_manufacture_branch(self):
		"""Same ordering requirement as D1: the sweep question has to be asked
		before `make_stock_entry` builds anything, and `acknowledge_sweep` has to
		actually reach the guard, not just exist as an unused parameter."""
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch("stabler.api.manufacturing._assert_consumption_setting_still_holds"),
			patch("stabler.api.manufacturing._assert_roles_are_both_or_neither"),
			patch(
				"stabler.api.manufacturing._assert_sweep_is_acknowledged",
				side_effect=frappe.ValidationError("sweep"),
			) as guard,
			patch("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry") as build,
		):
			with self.assertRaises(frappe.ValidationError):
				make_work_order_stock_entry("WO-00009", "Manufacture", qty=5, acknowledge_sweep=False)
		guard.assert_called_once_with("WO-00009", None, False)
		build.assert_not_called()


class TestFinishingAfterTheSettingWasSwitchedOff(unittest.TestCase):
	"""D2 (P0) — the failure that needs nobody to do anything wrong.

	`Manufacturing Settings.material_consumption` decides which list ERPNext
	builds a Manufacture entry from: with it ON, `get_unconsumed_raw_materials`,
	which is empty once the operators have written their material off; with it
	OFF, `get_bom_raw_materials`, which is the whole BOM again. Nothing raises,
	and `Work Order Item.consumed_qty` just accumulates the second helping.

	Measured on genesis-test 2026-08-26, MFG-WO-2026-00009 — two submitted
	consumption entries against it, both lines already fully consumed:

	    material_consumption=1 -> Manufacture stub raw rows: []
	    material_consumption=0 -> Manufacture stub raw rows: [MILK 2.0, LABEL 1.0]

	The setting ships OFF. It is the one thing a new tenant has to switch on, and
	the shape of this failure — right answer, then a config change, then silently
	wrong answers — is exactly what nobody goes looking for.

	Refused rather than repaired: a site-level setting is wrong for every order
	on the site, so stripping the duplicate rows from this one document would
	hide it and leave the rest to rot. Turning the setting back on is one action
	and fixes all of them.
	"""

	def _finish(self, enabled, prior_entries):
		with (
			patch("stabler.api.manufacturing._material_consumption_enabled", return_value=enabled),
			patch(
				"stabler.api.manufacturing.frappe.db.exists",
				return_value="MAT-STE-2026-00031" if prior_entries else None,
			),
		):
			from stabler.api.manufacturing import _assert_consumption_setting_still_holds

			_assert_consumption_setting_still_holds("WO-00009")

	def test_an_order_already_written_off_per_role_is_refused_while_the_setting_is_off(self):
		with self.assertRaises(frappe.ValidationError) as cm:
			self._finish(enabled=False, prior_entries=True)
		# The message has to send somebody to the right switch. An operator on the
		# kiosk cannot act on "double counting"; they can act on "tell your manager
		# the setting is off", and the manager can act on the setting's own name.
		self.assertIn("Manufacturing Settings", str(cm.exception))

	def test_the_ordinary_case_is_not_touched(self):
		self._finish(enabled=True, prior_entries=True)  # must not raise

	def test_the_endpoint_asks_before_erpnext_builds_anything(self):
		"""A guard nothing calls is a comment. And it has to be asked before
		`make_stock_entry`: the duplicate rows are put there by the stub itself,
		so a check after the build is checking a document that is already wrong.
		"""
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch(
				"stabler.api.manufacturing._assert_consumption_setting_still_holds",
				side_effect=frappe.ValidationError("setting"),
			) as guard,
			patch("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry") as build,
		):
			with self.assertRaises(frappe.ValidationError):
				make_work_order_stock_entry("WO-00009", "Manufacture", qty=5)
		guard.assert_called_once_with("WO-00009")
		build.assert_not_called()

	def test_a_site_that_never_used_the_split_still_finishes(self):
		"""The setting being off is not itself the failure. With no per-role
		write-offs behind it, ERPNext lists the BOM once and counts it once —
		which is simply the single-document flow, and the way every tenant that
		has not adopted the split still works. Refusing here would take
		manufacturing away from all of them to fix a bug they cannot have."""
		self._finish(enabled=False, prior_entries=False)  # must not raise


class TestConsumptionPreviewNarrowsToOwnRole(unittest.TestCase):
	"""`wo_consumption_preview` and `_assert_sweep_is_acknowledged` both read
	`_unconsumed_material_rows`, but must not read it the same way: the preview
	narrows to the caller's OWN role (an operator must not be offered the other
	role's material to write off), while the sweep guard narrows to every OTHER
	role. Mocking `_unconsumed_material_rows` directly isolates that per-role
	filter — added because the extraction that created the shared helper moved
	this exact filter, and the one test that already covered it end to end
	(`test_wo_role_scoping_integration.py`) self-skips whenever the site's real
	fixture Work Order has nothing left pending, which it does right now."""

	ROWS: ClassVar = [
		{
			"item_code": "RAW-MLK",
			"item_name": "Milk",
			"qty": 20.0,
			"s_warehouse": "WIP - X",
			"operator_role": "Production",
		},
		{
			"item_code": "PKG-LBL",
			"item_name": "Label",
			"qty": 10.0,
			"s_warehouse": "WIP - X",
			"operator_role": "Packaging",
		},
		# Nobody has said whose this is. Present in the fixture because it is the
		# row the two filters disagree about: it belongs to neither operator, so
		# a naive "not mine" reads it as the other operator's and a sweep warning
		# tells the pourer to go wait for a colleague who does not exist. It is
		# `unassigned_item_count`'s problem — the shift lead fills the role in —
		# and the manager, who holds no role, still has to be able to write it off.
		{
			"item_code": "MISC-XX",
			"item_name": "Unfiled thing",
			"qty": 1.0,
			"s_warehouse": "WIP - X",
			"operator_role": None,
		},
	]
	WO: ClassVar = {"operator": "pourer@x.uz", "packaging_operator": "packer@x.uz"}

	def _preview(self, user, is_manager=False):
		with (
			patch("stabler.api.manufacturing._assert_can_read"),
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing.frappe.db.exists", return_value=True),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=is_manager),
			patch("stabler.api.manufacturing._require_own_work_order"),
			patch("stabler.api.manufacturing._wo_operator_columns", return_value=tuple(self.WO)),
			patch("stabler.api.manufacturing.frappe.db.get_value", return_value=dict(self.WO)),
			patch(
				"stabler.api.manufacturing._unconsumed_material_rows",
				return_value=[dict(r) for r in self.ROWS],
			),
			patch("stabler.api.manufacturing.frappe.session") as session,
		):
			session.user = user
			return wo_consumption_preview("WO-00009")

	def test_the_pourer_sees_only_the_production_line(self):
		out = self._preview("pourer@x.uz")
		self.assertEqual([r["item_code"] for r in out["items"]], ["RAW-MLK"])

	def test_the_packer_sees_only_the_packaging_line(self):
		out = self._preview("packer@x.uz")
		self.assertEqual([r["item_code"] for r in out["items"]], ["PKG-LBL"])

	def test_the_manager_sees_both(self):
		out = self._preview("boss@x.uz", is_manager=True)
		self.assertEqual([r["item_code"] for r in out["items"]], ["RAW-MLK", "PKG-LBL", "MISC-XX"])
		self.assertEqual(out["unassigned_item_count"], 1)

	# --- the same payload, read the other way ------------------------------
	#
	# `sweep_risk` is the complement of `items` and rides the same response on
	# purpose. The operator must be shown what finishing would drag onto their
	# document BEFORE they type a count — `_assert_sweep_is_acknowledged` names
	# the same rows, but only on the way out, after the walk of the pallet is
	# already done. A refusal at that point is a wall, not a warning.

	def test_the_pourer_is_warned_about_the_packers_untouched_lines(self):
		out = self._preview("pourer@x.uz")
		self.assertEqual([r["item_code"] for r in out["sweep_risk"]], ["PKG-LBL"])

	def test_the_warning_stays_silent_about_lines_nobody_owns(self):
		"""An unfiled row is not the other operator's — it is nobody's. Named in
		the sweep warning it reads as "wait for your colleague to write this
		off", and the colleague it points at does not exist: the row is waiting
		on the shift lead, and the operator can wait out the whole shift for it.
		The two are counted separately on this very payload for that reason."""
		out = self._preview("pourer@x.uz")
		self.assertNotIn("MISC-XX", [r["item_code"] for r in out["sweep_risk"]])
		self.assertEqual(out["unassigned_item_count"], 1)

	def test_the_packer_is_warned_about_the_pourers_untouched_lines(self):
		out = self._preview("packer@x.uz")
		self.assertEqual([r["item_code"] for r in out["sweep_risk"]], ["RAW-MLK"])

	def test_the_manager_is_warned_about_both_because_neither_line_is_theirs(self):
		"""A manager holds no role of their own, so every role-owned row is
		somebody else's. Posting on the floor's behalf sweeps exactly as
		invisibly as the other operator posting first would."""
		out = self._preview("boss@x.uz", is_manager=True)
		self.assertEqual([r["item_code"] for r in out["sweep_risk"]], ["RAW-MLK", "PKG-LBL"])
		self.assertNotIn("MISC-XX", [r["item_code"] for r in out["sweep_risk"]])

	def test_what_the_kiosk_warns_about_is_what_the_server_refuses_over(self):
		"""The one that matters. Two filters over the same rows, written in two
		places, drift: the kiosk lists the label rolls, the server refuses over
		the milk, and the operator ticks a box that does not unblock them. Tie
		them together here so the drift fails a test instead of a shift."""
		for user, is_manager, role in (
			("pourer@x.uz", False, "Production"),
			("packer@x.uz", False, "Packaging"),
			("boss@x.uz", True, None),
		):
			with self.subTest(user=user):
				previewed = self._preview(user, is_manager=is_manager)["sweep_risk"]
				with patch(
					"stabler.api.manufacturing._unconsumed_material_rows",
					return_value=[dict(r) for r in self.ROWS],
				):
					refused = _sweep_risk_rows("WO-00009", role)
				self.assertEqual(previewed, refused)

	def test_an_unset_up_site_still_answers_the_question_it_was_asked(self):
		"""`enabled: False` is the site without continuous consumption, where
		ERPNext hands back the whole BOM and "what is left" has no trustworthy
		answer. The key must still be present and empty: a kiosk reading
		`undefined.length` on the one payload that says "not applicable" would
		break the finish dialog on exactly the sites that never had the split."""
		with (
			patch("stabler.api.manufacturing._assert_can_read"),
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing.frappe.db.exists", return_value=True),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=False),
			patch("stabler.api.manufacturing._require_own_work_order"),
			patch("stabler.api.manufacturing._wo_operator_columns", return_value=tuple(self.WO)),
			patch("stabler.api.manufacturing.frappe.db.get_value", return_value=dict(self.WO)),
			patch("stabler.api.manufacturing._unconsumed_material_rows", return_value=None),
			patch("stabler.api.manufacturing.frappe.session") as session,
		):
			session.user = "pourer@x.uz"
			out = wo_consumption_preview("WO-00009")
		self.assertEqual(out["enabled"], False)
		self.assertEqual(out["sweep_risk"], [])


class TestTheDraftIsClearedWhenTheOrderCloses(unittest.TestCase):
	"""A confirmed order must not still be showing an unconfirmed count.

	The draft exists so a walked-and-counted pallet survives a badge-out. The
	moment the Manufacture entry posts, that count is no longer unconfirmed — it is
	on a submitted stock document. Leaving the draft behind puts a "somebody has an
	unconfirmed finish here" banner on a finished order, and the next operator to
	open it re-enters numbers that are already posted.
	"""

	def test_finishing_clears_the_draft(self):
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch("stabler.api.manufacturing.assert_stock_entry_valuation_sane"),
			patch("stabler.api.manufacturing._log_wo_event"),
			patch("stabler.api.manufacturing.frappe.session"),
			patch("stabler.api.manufacturing.frappe.get_doc", side_effect=lambda stub: _FakeStockEntry(stub)),
			patch(
				"erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				return_value={"purpose": "Manufacture", "work_order": "WO-00009"},
			),
			patch("stabler.api.manufacturing._clear_finish_draft") as clear,
		):
			make_work_order_stock_entry("WO-00009", "Manufacture", qty=100)
		clear.assert_called_once_with("WO-00009")

	def test_transferring_does_not_clear_it(self):
		"""The transfer happens at the *start* of the order. A draft cannot exist yet,
		and clearing on every stock document would wipe one written between a partial
		consumption and the finish."""
		with (
			patch("stabler.api.manufacturing._require_mfg"),
			patch("stabler.api.manufacturing._is_mfg_manager", return_value=True),
			patch("stabler.api.manufacturing._assert_roles_are_both_or_neither"),
			patch("stabler.api.manufacturing.assert_stock_entry_valuation_sane"),
			patch("stabler.api.manufacturing._log_wo_event"),
			patch("stabler.api.manufacturing.frappe.session"),
			patch("stabler.api.manufacturing.frappe.get_doc", side_effect=lambda stub: _FakeStockEntry(stub)),
			patch(
				"erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				return_value={"purpose": "Material Transfer for Manufacture", "work_order": "WO-00009"},
			),
			patch("stabler.api.manufacturing._clear_finish_draft") as clear,
		):
			make_work_order_stock_entry("WO-00009", "Material Transfer for Manufacture", qty=100)
		clear.assert_not_called()

	def test_clearing_on_an_unmigrated_site_is_a_no_op_not_a_crash(self):
		"""v99 may not have run. A finish must still post — the draft feature being
		absent is not a reason to refuse the document that closes the order."""
		with (
			patch("stabler.api.manufacturing._wo_draft_columns", return_value=()),
			patch("stabler.api.manufacturing.frappe.db.set_value") as write,
		):
			_clear_finish_draft("WO-00009")
		write.assert_not_called()


class TestSavingADraftOnAnUnmigratedSite(unittest.TestCase):
	"""Refuse loudly rather than accept and discard.

	This is the v94 lesson, and v97 restated it for the packaging operator: a write
	that goes nowhere and reports success is worse than an error, because the
	operator walks away believing the count is stored. They find out at the end of
	the next shift, when it is gone and the pallet has moved.
	"""

	def test_a_missing_column_is_an_error_the_operator_can_read(self):
		with patch("stabler.api.manufacturing._wo_draft_columns", return_value=()):
			with self.assertRaises(frappe.ValidationError) as cm:
				_require_wo_draft_columns()
		self.assertIn("migrated", str(cm.exception).lower())

	def test_with_the_columns_present_it_says_nothing(self):
		with patch(
			"stabler.api.manufacturing._wo_draft_columns",
			return_value=("custom_finish_draft", "custom_finish_draft_at", "custom_finish_draft_by"),
		):
			_require_wo_draft_columns()
