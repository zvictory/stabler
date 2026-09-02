"""Default `Work Order.use_multi_level_bom` to 0 at record level.

WHY. anjan's ice-cream mix ("смесь") is a sub-assembly with a Work Order of its
own. ERPNext ships `use_multi_level_bom` defaulting to 1, and with 1
`work_order.py:1558-1560` passes `fetch_exploded=self.use_multi_level_bom` into
`get_bom_items_as_dict`, which at `bom.py:1427` (`if cint(fetch_exploded):`)
reads the `BOM Explosion Item` table instead of `BOM Item` — so the order that
should consume one line of mix is instead asked to issue the mix's flour, sugar
and milk, material that was already consumed by the mix's own order. Nothing
raises; the order simply lists the wrong things.

Measured on anjan, read-only, 2026-09-03: 197 of 4 271 Work Orders carry 1
(167 submitted, the most recent 2026-09-02 09:31), the two settings appear on
the same day in the same shift, 34 items had been produced both ways, and 130
of the 167 submitted mlb=1 orders sit on a BOM containing a sub-assembly, so
the flag really did change what was required. No stabler tenant carried a
Property Setter for this field.

Two creation paths produced 1 unless a person remembered to untick a box:

  * the Desk dialog on the BOM form, which reads exactly this Property Setter
    and falls back to 1 when it is absent (`bom.py:232-241`);
  * Stabler's `create_work_order`, which never wrote the flag, so
    `frappe.new_doc` handed it the meta default.

`frappe.new_doc` reads the same doctype meta the setter rewrites, so one row
closes both paths. Verified in FRESH bench processes (a same-process probe lies,
because meta is cached for the life of the worker): with this setter,
`frappe.new_doc("Work Order").use_multi_level_bom == 0` and
`get_meta("Work Order").get_field("use_multi_level_bom").default == "0"`;
delete it and 1 comes back. The API-side assignment in `create_work_order` ships
in this same commit — not as a second opinion on the same question, but because
this row is deletable by hand (below), and the API must keep behaving whether or
not it survives.

`property_type` is "Text" because that is what Customize Form writes for a
`default` property (`customize_form.py:800`). The `_upsert_property_setter`
helper in `v20_cost_field_perm_level.py` is deliberately NOT reused: it
hardcodes "Int", and it updates through `frappe.db.set_value`, which bypasses
`PropertySetter.validate` and therefore the `frappe.clear_cache(doctype)` that
makes the new default visible (`property_setter.py:39-45`). This patch writes
through the document API and clears the cache explicitly regardless of which
branch it took.

`doctype_or_field` is part of what gets compared and repaired, not just part of
what gets inserted. `meta.py:437-444` applies a Property Setter to a *field* only
when the row says `DocField`; a `DocType` row sets a property on the doctype
itself. Both shapes autoname into the same slot, so a pre-existing `DocType` row
here would be found by the lookup below, rewritten to value "0", and then ignored
by the meta — a repair that reports success and changes nothing.

Safe to run twice: the setter is looked up by its (doc_type, field_name,
property) key and only written when it is absent or when its value, type or
`doctype_or_field` differ. A second run over an unchanged setter writes nothing,
which is the property worth having — the alternative, an unconditional
`make_property_setter`, would rewrite the row on every migrate of every tenant.

Reversible by hand: delete the Property Setter and the ERPNext default of 1
returns — including via Customize Form's "Reset to defaults", which is why
`create_work_order` also sets the flag explicitly rather than trusting this row.
"""

import frappe

DOCTYPE = "Work Order"
FIELDNAME = "use_multi_level_bom"
PROPERTY = "default"
VALUE = "0"
PROPERTY_TYPE = "Text"
DOCTYPE_OR_FIELD = "DocField"


def execute():
	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": DOCTYPE, "field_name": FIELDNAME, "property": PROPERTY},
		"name",
	)

	if existing:
		setter = frappe.get_doc("Property Setter", existing)
		if (
			setter.value != VALUE
			or setter.property_type != PROPERTY_TYPE
			or setter.doctype_or_field != DOCTYPE_OR_FIELD
		):
			setter.value = VALUE
			setter.property_type = PROPERTY_TYPE
			setter.doctype_or_field = DOCTYPE_OR_FIELD
			setter.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": DOCTYPE_OR_FIELD,
				"doc_type": DOCTYPE,
				"field_name": FIELDNAME,
				"property": PROPERTY,
				"property_type": PROPERTY_TYPE,
				"value": VALUE,
			}
		).insert(ignore_permissions=True)

	# Unconditional, including on the no-op re-run: the branch above may have
	# written nothing, but a worker that cached the meta before this migrate is
	# still handing out the old default. Clearing here removes the dependency on
	# which path ran and on whether the document API happened to clear it for us.
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
