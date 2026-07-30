"""Contract guards for the Tender Master schema and CRM Deal lot link."""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
TENDER_MASTER_JSON = _ROOT / "stabler" / "doctype" / "tender_master" / "tender_master.json"
PATCH = _ROOT / "patches" / "v61_tender_master_link.py"
PATCHES = _ROOT / "patches.txt"


class _Document:
	def __init__(self, **values):
		self.__dict__.update(values)


def _load_tender_master_controller():
	for name in (
		"stabler.stabler.doctype.tender_master.tender_master",
		"frappe",
		"frappe.model",
		"frappe.model.document",
		"frappe.utils",
	):
		sys.modules.pop(name, None)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.throw = lambda message: (_ for _ in ()).throw(Exception(message))
	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")
	document.Document = _Document
	utils = types.ModuleType("frappe.utils")
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	sys.modules.update(
		{
			"frappe": frappe,
			"frappe.model": model,
			"frappe.model.document": document,
			"frappe.utils": utils,
		}
	)
	module = importlib.import_module("stabler.stabler.doctype.tender_master.tender_master")
	return module.TenderMaster


class TestTenderMasterSchema(unittest.TestCase):
	def test_parent_schema_and_lot_link_patch_are_registered(self):
		schema = json.loads(TENDER_MASTER_JSON.read_text())
		fields = {field["fieldname"]: field for field in schema["fields"]}
		self.assertEqual(fields["company"]["options"], "Company")
		self.assertEqual(fields["company"]["reqd"], 1)
		self.assertEqual(schema["autoname"], "naming_series:")
		self.assertEqual(schema["track_changes"], 1)
		self.assertEqual(fields["title"]["reqd"], 1)
		self.assertEqual(fields["buyer_name"]["reqd"], 1)
		self.assertEqual(fields["estimated_total"]["options"], "currency")
		self.assertEqual(
			fields["status"]["options"], "New\nSourcing\nBid Preparation\nSubmitted\nWon\nLost\nCancelled"
		)
		patch_source = PATCH.read_text()
		self.assertIn('"custom_parent_tender"', patch_source)
		self.assertIn('"options": "Tender Master"', patch_source)
		self.assertIn("stabler.patches.v61_tender_master_link.execute", PATCHES.read_text())
		hooks = (_ROOT / "hooks.py").read_text()
		self.assertIn('"Tender Master": "stabler.api.permissions.tender_master_query"', hooks)
		self.assertIn('"Tender Master": "stabler.api.permissions.company_has_permission"', hooks)

	def test_parent_status_is_a_read_only_note_and_never_required(self):
		"""`status` must stay read-only and optional.

		The board lane is derived from the child CRM Deal lots
		(`api/_tender_master_state.derive`). A REQUIRED, WRITABLE status field
		re-creates exactly the drift that decision removed: it forces whoever
		creates a tender to assert a lifecycle position before any lot exists,
		and then nobody re-types it when a lot is submitted or won — so the
		stored value contradicts the lots it is supposed to summarise. The field
		survives only as a manual note and as the audit trail `track_changes`
		keeps, which is why the options list stays intact.
		"""
		schema = json.loads(TENDER_MASTER_JSON.read_text())
		status = {field["fieldname"]: field for field in schema["fields"]}["status"]
		self.assertEqual(status["read_only"], 1)
		self.assertNotIn("reqd", status)

	def test_validate_rejects_deadline_before_publication(self):
		tender = _load_tender_master_controller()(
			publication_date="2026-07-31",
			submission_deadline="2026-07-30 09:00:00",
		)

		with self.assertRaisesRegex(Exception, "Submission deadline cannot be before publication date"):
			tender.validate()

	def test_validate_accepts_deadline_on_or_after_publication(self):
		TenderMaster = _load_tender_master_controller()
		TenderMaster(
			publication_date="2026-07-31",
			submission_deadline="2026-07-31 09:00:00",
		).validate()
		TenderMaster(
			publication_date="2026-07-31",
			submission_deadline="2026-08-01 09:00:00",
		).validate()


if __name__ == "__main__":
	unittest.main()
