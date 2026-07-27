"""Fields for the port-transfer departure gate.

Adds:
  Customs Declaration.required_for_departure  — does this GTD block the trucks?
  Import Truck.departure_override             — manager release despite blockers
  Import Truck.departure_override_reason      — why, recorded

Idempotent: every field is guarded with db.exists, so re-running is safe. The
patch runs BEFORE the doctype DDL sync (patches.txt has no [post_model_sync]
marker), so it must not read or write the new columns — it only creates the
Custom Field definitions.

Default for required_for_departure is 1: a declaration that exists is assumed
to matter. Marking one as optional is a deliberate act; forgetting to mark one
as required must not silently open the gate.
"""

import frappe

CUSTOM_FIELDS = [
	{
		"dt": "Customs Declaration",
		"fieldname": "required_for_departure",
		"label": "Required for departure",
		"fieldtype": "Check",
		"default": "1",
		"insert_after": "status",
		"description": (
			"Trucks on this commercial invoice cannot leave Iran until this declaration is cleared."
		),
	},
	{
		"dt": "Import Truck",
		"fieldname": "departure_override",
		"label": "Departure override",
		"fieldtype": "Check",
		"default": "0",
		"insert_after": "status_correction_reason",
		"description": (
			"Release this truck despite unmet customs or veterinary "
			"requirements. Imports Manager only, and a reason is mandatory."
		),
	},
	{
		"dt": "Import Truck",
		"fieldname": "departure_override_reason",
		"label": "Departure override reason",
		"fieldtype": "Small Text",
		"insert_after": "departure_override",
		"depends_on": "eval:doc.departure_override",
	},
]


def execute():
	for spec in CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", {"dt": spec["dt"], "fieldname": spec["fieldname"]}):
			continue
		doc = frappe.new_doc("Custom Field")
		doc.update(spec)
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
