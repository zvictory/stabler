"""Unit tests for Item update/disabled CRUD and Price List APIs."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock


# This module replaces `frappe` (and erpnext, and three stabler.api modules) with
# MagicMocks so `stabler.api.inventory` can be imported without a bench. That is
# fine on its own -- but it used to install the fakes unconditionally at module
# level and never take them back out.
#
# `bench run-tests --module X` still IMPORTS every test_*.py during discovery, so
# the fake `frappe` was left in sys.modules for the whole bench run. Modules that
# had already bound the real frappe kept working, which is why this went unnoticed;
# what broke was any FRESH submodule import at runtime. frappe.get_doc({"doctype":
# "User"}) imports frappe/core/doctype/user/user.py, which does
# `from frappe.auth import ...` -- the import machinery consults
# sys.modules['frappe'], finds a MagicMock with no __path__, and raises
# "No module named 'frappe.auth'; 'frappe' is not a package", which frappe then
# re-wraps as the very misleading "Module import failed for User, the DocType
# you're trying to open might be deleted." That was the whole of
# test_approvals_integration's 2 errors.
#
# Two guards below. First: under a live bench this module has nothing to prove --
# it is in .github/frappe-free-tests.txt and runs in its own process via
# `make test` -- so it installs nothing and its tests are skipped. The
# discriminator is frappe.local.site (None outside a bench, the site name inside
# one); `frappe.db` does NOT work, outside a bench it is a LocalProxy instance,
# not None. Nor does `"frappe" in sys.modules`: stabler/__init__.py imports the
# real frappe to patch get_doc for the `uzc` language, so frappe is always
# present. Second: in the frappe-free path the fakes are removed again as soon as
# the import that needs them is done.
#
# The skip is a class decorator, not a module-level `raise SkipTest`: frappe's
# runner imports test modules through frappe.get_module() rather than
# unittest's loader, so a SkipTest raised at import time is not caught as a skip
# -- it aborts the whole run with a traceback.
def _under_bench() -> bool:
	try:
		import frappe

		return frappe.local.site is not None
	except Exception:
		return False


_UNDER_BENCH = _under_bench()

mock_frappe = MagicMock()
mock_frappe._ = lambda s: s
def _passthrough_whitelist(*args, **kwargs):
	if len(args) == 1 and callable(args[0]):
		return args[0]
	return lambda fn: fn
mock_frappe.whitelist = _passthrough_whitelist
mock_utils = MagicMock()
mock_utils.flt = lambda v, p=None: float(v or 0)
mock_utils.cint = lambda v, p=None: int(v or 0)
mock_common = MagicMock()
mock_appr = MagicMock()
mock_recon = MagicMock()
mock_erpnext = MagicMock()

_FAKES = {
	'frappe': mock_frappe,
	'frappe.utils': mock_utils,
	'stabler.api._common': mock_common,
	'stabler.api.approvals': mock_appr,
	'stabler.api._stock_recon': mock_recon,
	'erpnext': mock_erpnext,
	'erpnext.stock': mock_erpnext,
	'erpnext.stock.get_item_details': mock_erpnext,
}
inventory = None
if not _UNDER_BENCH:
	_SAVED = {name: sys.modules.get(name) for name in _FAKES}
	sys.modules.update(_FAKES)

	# inventory binds these names into its own globals here; the fakes only have
	# to survive this one import, which is why putting sys.modules back below is
	# safe. Under a bench we must not do even that: the import would cache a
	# MagicMock-bound stabler.api.inventory in sys.modules for every later test.
	from stabler.api import inventory

	for _name, _saved in _SAVED.items():
		if _saved is None:
			sys.modules.pop(_name, None)
		else:
			sys.modules[_name] = _saved


@unittest.skipIf(_UNDER_BENCH, "frappe-free module: runs in its own process via `make test`")
class TestItemCrudAndPrices(unittest.TestCase):
	def test_update_item_modifies_doc_and_saves(self):
		mock_frappe.db.exists.return_value = True
		item_doc = MagicMock()
		item_doc.name = "TEST-ITEM-1"
		item_doc.item_code = "TEST-ITEM-1"
		item_doc.item_name = "Old Name"
		item_doc.disabled = 0
		mock_frappe.get_doc.return_value = item_doc

		res = inventory.update_item(
			name="TEST-ITEM-1",
			item_name="New Updated Name",
			standard_rate=150.0,
			disabled=1,
		)

		self.assertEqual(item_doc.item_name, "New Updated Name")
		self.assertEqual(item_doc.standard_rate, 150.0)
		self.assertEqual(item_doc.disabled, 1)
		item_doc.save.assert_called_once()
		self.assertEqual(res["name"], "TEST-ITEM-1")
		self.assertEqual(res["disabled"], 1)

	def test_list_price_lists(self):
		mock_frappe.db.sql.return_value = [
			{"name": "Standard Selling", "currency": "USD", "buying": 0, "selling": 1},
			{"name": "Standard Buying", "currency": "USD", "buying": 1, "selling": 0},
		]

		pls = inventory.list_price_lists(selling=1)
		self.assertEqual(len(pls), 2)
		self.assertEqual(pls[0]["name"], "Standard Selling")

	def test_create_price_list(self):
		mock_frappe.db.exists.return_value = False
		pl_doc = MagicMock()
		pl_doc.name = "VIP Wholesale"
		pl_doc.price_list_name = "VIP Wholesale"
		pl_doc.currency = "USD"
		mock_frappe.new_doc.return_value = pl_doc

		res = inventory.create_price_list("VIP Wholesale", currency="USD", selling=1)
		pl_doc.insert.assert_called_once()
		self.assertEqual(res["name"], "VIP Wholesale")

	def test_save_item_price_new(self):
		mock_frappe.db.exists.return_value = True
		mock_frappe.db.get_value.return_value = None

		pl_doc = MagicMock()
		pl_doc.currency = "USD"
		mock_frappe.get_doc.return_value = pl_doc

		ip_doc = MagicMock()
		ip_doc.name = "IP-001"
		ip_doc.item_code = "ITEM-1"
		ip_doc.price_list = "Standard Selling"
		ip_doc.price_list_rate = 120.0
		ip_doc.currency = "USD"
		mock_frappe.new_doc.return_value = ip_doc

		res = inventory.save_item_price("ITEM-1", "Standard Selling", 120.0)
		ip_doc.save.assert_called_once()
		self.assertEqual(res["price_list_rate"], 120.0)

	def test_delete_item_price(self):
		mock_frappe.db.exists.return_value = True
		mock_frappe.delete_doc.reset_mock()
		res = inventory.delete_item_price("IP-001")
		mock_frappe.delete_doc.assert_called_once_with("Item Price", "IP-001", ignore_permissions=False)
		self.assertEqual(res["status"], "ok")


if __name__ == "__main__":
	unittest.main()
