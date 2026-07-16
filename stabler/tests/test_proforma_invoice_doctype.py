"""Structural guard for the Proforma Invoice doctype (WP-I1).

Validates the JSON schema without a bench: field_order consistency, module,
the cash/bank earmark fields, the PI status flow, and the child-table wiring.
Locks the shape so a later edit cannot silently break it.
"""

from __future__ import annotations

import json
import os
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DT = os.path.join(_APP_ROOT, "stabler", "doctype")


def _load(name: str) -> dict:
	with open(os.path.join(_DT, name, f"{name}.json"), encoding="utf-8") as fh:
		return json.load(fh)


class TestProformaInvoiceDoctype(unittest.TestCase):
	def setUp(self):
		self.pi = _load("proforma_invoice")
		self.item = _load("proforma_invoice_item")

	def test_field_order_matches_fields(self):
		for d in (self.pi, self.item):
			fns = {f["fieldname"] for f in d["fields"]}
			missing = [x for x in d.get("field_order", []) if x not in fns]
			self.assertEqual(missing, [], f"{d['name']}: field_order refers to unknown fields {missing}")

	def test_module_and_names(self):
		self.assertEqual(self.pi["module"], "Stabler")
		self.assertEqual(self.pi["name"], "Proforma Invoice")
		self.assertEqual(self.item["module"], "Stabler")
		self.assertEqual(self.item["name"], "Proforma Invoice Item")
		self.assertEqual(self.item.get("istable"), 1)

	def test_required_fields_present(self):
		fns = {f["fieldname"]: f for f in self.pi["fields"]}
		for req in ("supplier", "company", "agreed_total", "bank_agreed", "cash_agreed", "status", "items", "commercial_invoice"):
			self.assertIn(req, fns, f"Proforma Invoice missing field {req}")
		# earmark currency fields
		self.assertEqual(fns["bank_agreed"]["fieldtype"], "Currency")
		self.assertEqual(fns["cash_agreed"]["fieldtype"], "Currency")

	def test_status_flow(self):
		opts = {f["fieldname"]: f for f in self.pi["fields"]}["status"]["options"].split("\n")
		self.assertEqual(opts, ["DRAFT", "CONFIRMED", "SUPERSEDED_BY_CI", "CANCELLED"])

	def test_items_link_to_child(self):
		items = {f["fieldname"]: f for f in self.pi["fields"]}["items"]
		self.assertEqual(items["fieldtype"], "Table")
		self.assertEqual(items["options"], "Proforma Invoice Item")

	def test_imports_permissions(self):
		roles = {p["role"] for p in self.pi["permissions"]}
		self.assertIn("Imports Manager", roles)
		self.assertIn("Imports User", roles)
		self.assertIn("System Manager", roles)


if __name__ == "__main__":
	unittest.main()
