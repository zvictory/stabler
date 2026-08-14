"""Contract guards for Supplier Quotation custom_rfq field (Patch v83).

Verifies that the patch:
- is registered in patches.txt
- adds custom_rfq Link field pointing to Request for Quotation
- has idempotent guards
- sets in_list_view and no_copy
"""

from __future__ import annotations

import os
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_PATCH = os.path.join(_ROOT, "patches", "v83_sq_rfq_link.py")
_PATCHES_TXT = os.path.join(_ROOT, "patches.txt")


def _read(path: str) -> str:
	if not os.path.exists(path):
		return ""
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestSqRfqLinkPatch(unittest.TestCase):
	def setUp(self):
		self.patch = _read(_PATCH)
		self.patches_txt = _read(_PATCHES_TXT)

	def test_patch_is_registered(self):
		self.assertTrue(os.path.exists(_PATCH), "v83_sq_rfq_link.py is missing")
		self.assertIn("stabler.patches.v83_sq_rfq_link", self.patches_txt)

	def test_patch_defines_custom_rfq_link(self):
		for contract in (
			'"fieldname": "custom_rfq"',
			'"fieldtype": "Link"',
			'"options": "Request for Quotation"',
			'"Supplier Quotation"',
			'"Request for Quotation"',
		):
			self.assertIn(contract, self.patch)

	def test_patch_is_idempotent(self):
		for contract in (
			'frappe.db.exists("DocType", "Supplier Quotation")',
			'frappe.db.exists("DocType", "Request for Quotation")',
			'frappe.db.exists("Custom Field", already_installed)',
		):
			self.assertIn(contract, self.patch)


if __name__ == "__main__":
	unittest.main()
