"""Set perm_level=1 on cost/valuation fields of Item (gap #45).

ERPNext uses permission levels to omit fields from API responses for roles
that lack level-1 read permission.  Setting these fields to perm_level=1
means ERPNext will automatically exclude them from REST responses for any
role without level-1 read on Item — no custom Python masking needed for
standard endpoints.

Fields targeted (must exist on Item):
  valuation_rate, last_purchase_rate, standard_rate

Idempotent: checks for an existing Property Setter before creating.
"""

import frappe

_ITEM_COST_FIELDS = (
	"valuation_rate",
	"last_purchase_rate",
	"standard_rate",
)


def _upsert_property_setter(doctype: str, fieldname: str, prop: str, value):
	"""Create a Property Setter if one doesn't already exist for this field+prop."""
	existing = frappe.db.get_value(
		"Property Setter",
		{
			"doc_type": doctype,
			"field_name": fieldname,
			"property": prop,
		},
		"name",
	)
	if existing:
		# Already set — update only if the value differs.
		current = frappe.db.get_value("Property Setter", existing, "value")
		if str(current) == str(value):
			return
		frappe.db.set_value("Property Setter", existing, "value", str(value))
		return

	ps = frappe.new_doc("Property Setter")
	ps.doctype_or_field = "DocField"
	ps.doc_type = doctype
	ps.field_name = fieldname
	ps.property = prop
	ps.property_type = "Int"
	ps.value = str(value)
	ps.insert(ignore_permissions=True)


def execute():
	for fieldname in _ITEM_COST_FIELDS:
		# Guard: only set perm_level if the field actually exists on Item.
		if not frappe.db.exists("DocField", {"parent": "Item", "fieldname": fieldname}):
			continue
		_upsert_property_setter("Item", fieldname, "perm_level", 1)

	frappe.db.commit()
