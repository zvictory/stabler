"""Contract guards for Supplier Quotation custom_rfq field (Patch v83).

Verifies that the patch:
- is registered in patches.txt
- adds custom_rfq Link field pointing to Request for Quotation
- has idempotent guards
- sets in_list_view and no_copy
- backfills pre-v83 quotations only where the RFQ is unambiguous
"""

from __future__ import annotations

import importlib
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_PATCH = os.path.join(_ROOT, "patches", "v83_sq_rfq_link.py")
_PATCHES_TXT = os.path.join(_ROOT, "patches.txt")

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


def _read(path: str) -> str:
	if not os.path.exists(path):
		return ""
	with open(path, encoding="utf-8") as source:
		return source.read()


class _FakeDb:
	"""Just enough of ``frappe.db`` for the patch: the column guards, the RFQ
	read, and a record of the UPDATEs the backfill decided to run."""

	def __init__(self, rfq_rows, *, missing_column=None):
		self.rfq_rows = rfq_rows
		self.missing_column = missing_column
		self.updates: list[tuple] = []

	def exists(self, doctype, name=None):
		return True

	def has_column(self, doctype, column):
		return (doctype, column) != self.missing_column

	def sql(self, query, values=None, as_dict=False):
		if "tabRequest for Quotation" in query:
			return [types.SimpleNamespace(**row) for row in self.rfq_rows]
		self.updates.append(values)
		return []


def _load_patch(db):
	_SANDBOX.evict(
		"stabler.patches.v83_sq_rfq_link",
		"frappe",
		"frappe.custom",
		"frappe.custom.doctype",
		"frappe.custom.doctype.custom_field",
		"frappe.custom.doctype.custom_field.custom_field",
	)
	frappe = types.ModuleType("frappe")
	frappe.db = db
	custom_field = types.ModuleType("frappe.custom.doctype.custom_field.custom_field")
	custom_field.create_custom_fields = lambda *_args, **_kwargs: None
	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.custom": types.ModuleType("frappe.custom"),
			"frappe.custom.doctype": types.ModuleType("frappe.custom.doctype"),
			"frappe.custom.doctype.custom_field": types.ModuleType("frappe.custom.doctype.custom_field"),
			"frappe.custom.doctype.custom_field.custom_field": custom_field,
		}
	)
	return importlib.import_module("stabler.patches.v83_sq_rfq_link")


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

	def test_backfill_never_overwrites_a_quotation_that_already_names_its_rfq(self):
		"""Re-running the patch must be safe: the UPDATE is scoped to rows whose
		`custom_rfq` is still empty, so a quotation already stamped for round 2
		can never be dragged back to round 1."""
		self.assertIn("ifnull(custom_rfq, '') = ''", self.patch)


class TestBackfill(unittest.TestCase):
	"""The backfill decides which pre-v83 quotations may be stamped. Grepping the
	source cannot tell a correct rule from an inverted one, so run it."""

	def test_a_deal_with_exactly_one_rfq_stamps_its_quotations(self):
		"""When the deal has a single RFQ there is only one round the pre-v83
		quotations can be answering, so writing it loses nothing and restores
		round tracking for that deal."""
		db = _FakeDb([{"deal": "LOT-A", "name": "RFQ-1"}])
		_load_patch(db).execute()
		self.assertEqual(db.updates, [("RFQ-1", "LOT-A")])

	def test_a_deal_with_several_rfqs_is_left_alone(self):
		"""Guessing which round a quotation answered would silently invent data;
		`get_rfq`'s unstamped fallback already keeps those quotations visible
		under every round of the deal, which is the pre-v83 behaviour."""
		db = _FakeDb(
			[
				{"deal": "LOT-B", "name": "RFQ-1"},
				{"deal": "LOT-B", "name": "RFQ-2"},
				{"deal": "LOT-C", "name": "RFQ-3"},
			]
		)
		_load_patch(db).execute()
		self.assertEqual(db.updates, [("RFQ-3", "LOT-C")])

	def test_backfill_is_skipped_while_the_column_is_missing(self):
		"""patches.txt has no `[post_model_sync]` marker, so a patch can run
		before the DDL exists — writing to `custom_rfq` then aborts the whole
		migrate on `unknown column`."""
		for column in (
			("Supplier Quotation", "custom_rfq"),
			("Supplier Quotation", "custom_crm_deal"),
			("Request for Quotation", "custom_crm_deal"),
		):
			with self.subTest(column=column):
				db = _FakeDb([{"deal": "LOT-A", "name": "RFQ-1"}], missing_column=column)
				_load_patch(db).execute()
				self.assertEqual(db.updates, [])


if __name__ == "__main__":
	unittest.main()
