"""Clear the broken ``:Company`` default on the CRM Deal company field.

``v56_crm_deal_company_scope`` created the field with ``default = ":Company"``.
Frappe treats a default starting with ``:`` as "read ``df.fieldname`` off that
doctype" (``frappe/model/create_new.py:get_default_based_on_another_field``), so
it issued ``get_value("Company", <default company>, "company")`` and every
``frappe.new_doc("CRM Deal")`` raised ``OperationalError 1054: Unknown column
'company'``. That broke SPA deal creation (``stabler/api/crm.py``) and the UZEX
tender poller (``stabler/tasks/uzex_poll.py``) on every site that had migrated.

v56 guards its field creation with ``has_column``, so re-running it repairs
nothing on an already-migrated site — hence this separate patch.
"""

import frappe


def execute():
	name = frappe.db.get_value(
		"Custom Field",
		{"dt": "CRM Deal", "fieldname": "company"},
		"name",
	)
	if not name:
		return

	if frappe.db.get_value("Custom Field", name, "default") != ":Company":
		return

	frappe.db.set_value("Custom Field", name, "default", None, update_modified=False)
	frappe.clear_cache(doctype="CRM Deal")
