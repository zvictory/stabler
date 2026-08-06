"""Add the tender-level document requirements JSON field to Tender Master.

The document center keeps two layers of requirements: per-lot requirements
carried on ``CRM Deal.custom_tender_intake.documents`` (added by v37) and
per-tender requirements shared across all lots of a Tender Master. This patch
creates the second layer — ``custom_tender_documents`` — a Long Text JSON blob
parsed by ``stabler.api._tender_documents.parse_doc_requirements``. It is
seeded with the standard import-tender document set on existing masters so the
tender level is not empty on upgrade.
"""
import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from stabler.api._tender_documents import default_doc_requirements


def execute():
	if not frappe.db.exists("DocType", "Tender Master"):
		return

	create_custom_fields(
		{
			"Tender Master": [
				{
					"fieldname": "custom_tender_documents",
					"label": "Tender Documents",
					"fieldtype": "Long Text",
					# JSON blob: list[dict] as produced by parse_doc_requirements.
					"hidden": 1,
					"no_copy": 1,
				}
			]
		},
		ignore_validate=True,
	)

	# Seed the standard document set on existing masters that have none yet, so the
	# tender level isn't blank after upgrade. `default_doc_requirements` returns the
	# cleaned/derived shape (no files, nothing satisfied) — the operator fills them in.
	seed = json.dumps(default_doc_requirements(), ensure_ascii=False)
	for name in frappe.get_all("Tender Master", pluck="name"):
		current = frappe.db.get_value("Tender Master", name, "custom_tender_documents")
		if not (current or "").strip():
			frappe.db.set_value("Tender Master", name, "custom_tender_documents", seed, update_modified=False)
