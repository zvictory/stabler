"""Customer parent/child hierarchy Custom Fields (QuickBooks-style, plan §2 K2).

Ensures two Custom Fields on Customer:
  - custom_parent_customer (Link → Customer) — the consolidation parent. A
    child's transactions stay on the child; the parent rolls up the balance.
  - custom_job_status (Select) — location/"job" lifecycle, only meaningful for
    children.

Field-by-field idempotent. On the live msa site `custom_parent_customer` ALREADY
exists (created by the old Django app, ~165 children under 5 parents), so this
patch must NOT touch it — we create each field only when it is missing and never
overwrite an existing field's properties. Listed under [post_model_sync] so the
Customer DDL is already in sync when this runs; still safe on every other tenant
(pure Custom Field upsert on a core doctype).
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

_FIELDS = [
	{
		"fieldname": "custom_parent_customer",
		"label": "Parent Customer",
		"fieldtype": "Link",
		"options": "Customer",
		"insert_after": "customer_name",
		"description": "Consolidation parent — this customer's balance rolls up here.",
	},
	{
		"fieldname": "custom_job_status",
		"label": "Job Status",
		"fieldtype": "Select",
		"options": "\nActive\nCompleted\nOn Hold\nCancelled",
		"insert_after": "custom_parent_customer",
		"description": "Location / job lifecycle status (children only).",
	},
]


def execute() -> None:
	for field in _FIELDS:
		# Leave any pre-existing field (e.g. msa's custom_parent_customer) exactly
		# as-is — do not re-run create_custom_field, which would rewrite props.
		if frappe.db.exists("Custom Field", f"Customer-{field['fieldname']}"):
			continue
		create_custom_field("Customer", field)
	frappe.db.commit()
