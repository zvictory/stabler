from __future__ import annotations

import unittest

import frappe
from frappe import ValidationError

from stabler.api.sales import _normalize_direct_return_items


class DirectSalesReturnHelperTest(unittest.TestCase):
	def test_rejects_empty_direct_return_items(self):
		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([])

	def test_normalizes_positive_return_items(self):
		items = _normalize_direct_return_items(
			[
				{"item_code": "ITEM-1", "qty": "2", "uom": "Box", "rate": "12000"},
				{"item_code": "ITEM-2", "qty": 1, "rate": 5000},
			]
		)

		self.assertEqual(
			items,
			[
				{"item_code": "ITEM-1", "qty": 2.0, "rate": 12000.0, "uom": "Box"},
				{"item_code": "ITEM-2", "qty": 1.0, "rate": 5000.0, "uom": None},
			],
		)

	def test_rejects_zero_qty_and_non_positive_rate(self):
		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 0, "rate": 1}])

		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 1, "rate": -1}])

		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 1, "rate": 0}])

	def test_the_refusal_reaches_the_browser(self):
		"""A rejected line must arrive as TEXT, not as a bare status code.

		The three assertions above stayed green through the production bug and
		that is the point of this one: they prove the helper refuses, never that
		the operator can read the refusal. `frappe.throw` routes through msgprint
		and fills frappe.local.message_log; the response layer emits
		_server_messages only when that log is non-empty, and the SPA has nothing
		else to show — production strips exception/traceback. Measured on anjan
		2026-09-02, a bare `raise` here produced http 417 with message_log == [],
		and the operator read "Request failed: 417" on a credit note that was one
		keystroke from correct.
		"""
		frappe.clear_messages()

		with self.assertRaises(ValidationError):
			_normalize_direct_return_items([{"item_code": "ITEM-1", "qty": 1, "rate": 0}])

		log = frappe.get_message_log()
		self.assertTrue(
			log,
			"empty message_log -> no _server_messages -> the user reads 'Request failed: 417'",
		)
		self.assertIn("ITEM-1", str(log[-1]), "the refusal must name the line it refused")


if __name__ == "__main__":
	unittest.main()
