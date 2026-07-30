"""Contract guards for the Tender Master schema and CRM Deal lot link."""

from __future__ import annotations

import importlib
import json
import re
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
		self.assertIn("stabler.patches.v61_tender_master_link", PATCHES.read_text().split())
		hooks = (_ROOT / "hooks.py").read_text()
		self.assertIn('"Tender Master": "stabler.api.permissions.tender_master_query"', hooks)
		self.assertIn('"Tender Master": "stabler.api.permissions.company_has_permission"', hooks)

	def test_lot_link_patch_only_references_fields_that_actually_exist(self):
		"""Every fieldname v61 points at must be one v60 really creates.

		`create_custom_fields(..., ignore_validate=True)` skips
		`validate_insert_after`, so a misspelled reference does NOT abort migrate —
		it installs quietly. A wrong `insert_after` lands the field at an arbitrary
		idx, and a wrong `depends_on` yields `undefined == "Tender"`, hiding Parent
		Tender in the Desk form forever. Since the SPA has no editor for it, that is
		the only place a human can group an orphan lot — so the typo would silently
		disable the K2 migration queue's one repair path. Frappe only auto-prefixes
		`custom_` when `fieldname` is left empty, so v60's fields are unprefixed and
		must be referenced verbatim.
		"""
		v60 = (_ROOT / "patches" / "v60_crm_daily_work.py").read_text()
		created = set(re.findall(r'"fieldname": "([a-z0-9_]+)"', v60))
		self.assertIn("deal_type", created)

		v61 = PATCH.read_text()
		referenced = set(re.findall(r'"insert_after": "([a-z0-9_]+)"', v61))
		referenced |= set(re.findall(r"eval:doc\.([a-z0-9_]+)", v61))
		self.assertTrue(referenced, "the patch must anchor the field, not float")
		self.assertEqual(referenced - created, set())

	def test_api_reads_no_custom_field_that_no_patch_ever_creates(self):
		"""Every `custom_*` field the tender API reads must be one a patch installs.

		`frappe.get_list` silently DROPS a fieldname the doctype does not have —
		no error, no warning, just a missing key — so an invented custom field
		costs nothing at import or query time and everything at read time: it
		reads as 0.00 / blank forever. That is not a hypothetical. The board's
		money column shipped pointing at a `custom_…estimated_value` that no
		patch creates and no site has, so the card, the drill-down and
		`summary.estimated_total` were structurally zero on mikas — the only
		tenant with the tender module on (found in the 2026-07-30 post-deploy
		smoke run). The unit tests could not catch it: they build their lot rows
		by keyword argument, so the fake carried the same wrong name and agreed
		with the code. A schema-side check is the only kind that can disagree.

		Core CRM Deal columns (`deal_value`, `status`, `currency`) are out of
		scope here — they belong to the crm app, whose doctype JSON is not in
		this repo. This guards the half we own, which is also the half that has
		no schema to fall back on.
		"""
		api = (_ROOT / "api" / "tender_master.py").read_text()
		referenced = set(re.findall(r"custom_[a-z0-9_]+", api))
		created = set()
		for patch in sorted((_ROOT / "patches").glob("*.py")):
			created |= set(re.findall(r'"fieldname": "(custom_[a-z0-9_]+)"', patch.read_text()))
		self.assertTrue(referenced, "the tender API must still read its custom lot fields")
		self.assertEqual(sorted(referenced - created), [])

	def test_patch_entries_are_module_paths_never_dotted_execute_calls(self):
		"""A `patches.txt` entry names the module; frappe appends `.execute` itself.

		`patch_handler.execute_patch` builds `f"{entry.split()[0]}.execute"` before
		importing, so an entry that already ends in `.execute` resolves to
		`module.execute.execute` and raises ModuleNotFoundError. That aborts
		`bench migrate` — and it aborts it in the post_model_sync phase, i.e. AFTER
		the doctype DDL has been applied, so the site is left half-migrated: new
		tables present, patch unrun, and every remaining site in the deploy loop
		unmigrated. This cost a prod deploy (2026-07-30); the one entry with the
		suffix was the only one of 66 that had it, which is why nothing but a
		migrate caught it.
		"""
		offenders = []
		for line in PATCHES.read_text().splitlines():
			entry = line.strip()
			if not entry or entry.startswith(("#", "[", "execute:")):
				continue
			if entry.split()[0].endswith(".execute"):
				offenders.append(entry)
		self.assertEqual(offenders, [])

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
