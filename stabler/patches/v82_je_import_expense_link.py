"""Back-link a Journal Entry to the Import Expense it belongs to (C1).

Adds two Journal Entry custom fields:

* ``custom_import_expense`` — set when the JE was posted *by* an Import Expense
  (the cash-desk path, ``imports._post_expense_kasa_entry``). It is the marker
  that stops ``imports_module.hooks.on_journal_entry_submit`` from spawning a
  second, duplicate Import Expense for a voucher that already has a parent, and
  it keeps the cancel cleanup from deleting an imports-side record it does not own.
* ``custom_import_expense_category`` — the category chosen on /money/expenses,
  mirroring ``Import Expense.category``. It decides the prefilled cost component
  of the spawned expense.

Idempotent: guarded by Custom Field existence checks. Post-model-sync safe.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

#: Mirrors Import Expense.category exactly, with a leading blank so the field
#: may legitimately stay empty on the vast majority of Journal Entries.
_CATEGORY_OPTIONS = (
	"\nBorder Crossing\nTransport\nHandling\nStorage\nInsurance\nDocumentation\nCustoms\nOther"
)


def execute():
	fields_to_create = []

	if not frappe.db.exists(
		"Custom Field", {"dt": "Journal Entry", "fieldname": "custom_import_expense_category"}
	):
		fields_to_create.append(
			{
				"fieldname": "custom_import_expense_category",
				"label": "Import Expense Category",
				"fieldtype": "Select",
				"options": _CATEGORY_OPTIONS,
				"insert_after": "custom_import_container",
			}
		)

	if not frappe.db.exists("Custom Field", {"dt": "Journal Entry", "fieldname": "custom_import_expense"}):
		fields_to_create.append(
			{
				"fieldname": "custom_import_expense",
				"label": "Import Expense",
				"fieldtype": "Link",
				"options": "Import Expense",
				"read_only": 1,
				"insert_after": "custom_import_expense_category",
			}
		)

	if fields_to_create:
		create_custom_fields({"Journal Entry": fields_to_create}, ignore_validate=True)
