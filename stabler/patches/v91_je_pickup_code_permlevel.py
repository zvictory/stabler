"""Close the last readable copy of the pickup secret: `Journal Entry.stabler_pickup_code`.

v89 raised `Remittance Transfer.pickup_code_hash` to permlevel 1 and explained why.
The same secret has a third name, and that one was left at permlevel 0: the v33
Custom Field on Journal Entry, which the LEGACY register path still writes on every
transfer today (`stabler/api/remittance.py` — `store_pickup_code(code)`). Since v86
its value is `scheme$salt$digest`, and the digest is over an 8-character draw from a
32-glyph alphabet — about 2^40, a bounded offline crack for a single record. What
falls out is the bearer token that collects the cash at the counter.

`hidden: 1` was the only protection and it protects nothing:
`frappe/model/meta.py get_permitted_fieldnames` filters candidates by
`df.permlevel in permlevel_access`, and the candidate list from
`get_fieldnames_with_value` never looks at `hidden`. So

    GET /api/resource/Journal Entry
        ?filters=[["stabler_remittance_stage","=","Register"]]
        &fields=["name","stabler_remittance_id","stabler_pickup_code"]

answered for any role holding `read` on Journal Entry. On this bench that is core
ERPNext territory — Accounts User, Accounts Manager, Auditor — none of which is one
of the four remittance roles, so `permissions.remittance_transfer_query` never came
near it. `_remittance_actions.FORBIDDEN_READ_FIELDS` already names this field, but
that guard filters *projections in this app's endpoints*; it cannot reach
`/api/resource`.

**No permlevel-1 write grant is needed here, and that is measured, not assumed.**
The read side: `journal_entry.json` carries three permission rows and every one of
them is permlevel 0, so raising the field closes it for every role at once. The
write side: the only writer is `create_remittance`, which calls
`je.insert(ignore_permissions=True)`, and `Document.validate_higher_perm_levels`
returns immediately on `self.flags.ignore_permissions` — the silent-NULL trap v89
had to buy its way out of does not exist on this path. v86's backfill uses
`frappe.db.set_value`, which never runs document validation at all. And the payout
comparison reads the row with `frappe.get_doc` server-side;
`apply_fieldlevel_read_permissions` is called by the REST layer and
`frappe.client`, not by `get_doc`. So nothing that must keep working stops working.

Why a patch when v33 now carries `"permlevel": 1` in its field dict: v33's
`execute()` filters out fields that already exist, so on every site that has ever
run it the dict is dead letter. This is the only thing that moves an existing site.

Idempotent: reads the current value first and writes only on a change.
"""

import frappe

_DOCTYPE = "Journal Entry"
_FIELDNAME = "stabler_pickup_code"


def execute():
	if not frappe.db.table_exists("Custom Field"):
		return

	name = frappe.db.get_value("Custom Field", {"dt": _DOCTYPE, "fieldname": _FIELDNAME}, "name")
	if not name:
		# A site that never ran v33 has no field to close; when it does run v33 it
		# gets permlevel 1 from the field dict.
		return

	if frappe.db.get_value("Custom Field", name, "permlevel") == 1:
		return

	frappe.db.set_value("Custom Field", name, "permlevel", 1)
	frappe.clear_cache(doctype=_DOCTYPE)
