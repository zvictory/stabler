"""Guarantee the permlevel-1 write grant that `pickup_code_hash` now depends on.

v87 shipped the four remittance roles; the digest field sat at permlevel 0 beside
them, which meant every role holding `read` on Remittance Transfer — Viewer and
Auditor included, whose entire permission set is `{read: 1}` — could pull
`pickup_code_hash` off `/api/resource` or `frappe.client.get_list`. `hidden` does
not help: `frappe/model/meta.py:677 get_permitted_fieldnames` builds its list from
permlevel access and never consults it. The digest is a salted SHA-256 over an
8-character draw from a 32-glyph alphabet, so one record is a bounded offline
crack, and the code it yields is the bearer token for the cash.

The doctype JSON now carries `"permlevel": 1` on the field, which closes the read.
It also carries three permlevel-1 rows granting `write` (and NOT `read`) to the
roles that register a transfer, and those rows are load-bearing in a way that is
easy to miss: `Document.validate_higher_perm_levels` (frappe/model/document.py:946)
silently RESETS a permlevel field the saving user cannot write. Without the grant,
`_new_transfer` would insert NULL, `register_remittance` would still hand the
cashier a plaintext code, and the transfer would be unpayable forever — the failure
would surface days later at the counter, with the money already taken.

Why this patch exists when the JSON should be enough: measured on this bench,
`import_file.delete_old_doc` clears the permissions child table only when
`reset_permissions` is set, and `ignore_doctypes` is empty, so a normal
`bench migrate` DOES rebuild DocPerm from the JSON. This is the belt to that
braces, for the same reason v87 revoked the delete right in a patch as well as in
the JSON: DocPerm rows have survived a sync in this repo before (v75), and the cost
of this one not landing is a dead remittance desk rather than a cosmetic drift.

Idempotent and duplicate-safe: each role is inserted only when no permlevel-1 row
for it exists, so a second run — or a run after the sync already did the work —
touches nothing.
"""

import frappe

TRANSFER = "Remittance Transfer"

#: The roles that insert a Remittance Transfer, and therefore the only ones that
#: need to write the digest. Deliberately not Viewer or Auditor: they never
#: register, and a write grant they cannot use is a grant somebody has to explain
#: later. None of these rows carries `read` — nobody reads this field, ever.
_WRITERS = (
	"Remittance Cashier",
	"Remittance Finance Manager",
	"System Manager",
)


def execute():
	if not frappe.db.table_exists("DocPerm"):
		return
	if not frappe.db.exists("DocType", TRANSFER):
		# Tenant does not carry the remittance doctype — nothing to grant.
		return

	for role in _WRITERS:
		if not frappe.db.exists("Role", role):
			# v87 creates the three remittance roles and System Manager is core, so
			# this only skips a site where v87 has not run yet. That site has no
			# transfers either, and v87 runs before this patch.
			continue
		if frappe.db.exists("DocPerm", {"parent": TRANSFER, "role": role, "permlevel": 1}):
			continue
		_insert_permlevel_one_write(role)

	frappe.clear_cache(doctype=TRANSFER)


def _insert_permlevel_one_write(role: str) -> None:
	"""One DocPerm row, written the way v87 writes DocPerm: directly.

	Not `frappe.permissions.add_permission` — that calls `setup_custom_perms`,
	which copies the whole permission set into Custom DocPerm, and from then on
	`meta.py:628` reads Custom DocPerm *instead of* the doctype JSON. Every future
	edit to the permissions block in `remittance_transfer.json` would then be
	silently ignored on this site. The read grant is not worth trading the JSON's
	authority for.
	"""
	next_idx = (
		frappe.db.sql(
			"select ifnull(max(idx), 0) + 1 from `tabDocPerm` where parent = %s and parenttype = 'DocType'",
			(TRANSFER,),
		)[0][0]
		or 1
	)
	frappe.db.sql(
		"""
		insert into `tabDocPerm`
			(name, creation, modified, owner, modified_by, docstatus, idx,
			 parent, parentfield, parenttype, permlevel, role, `write`)
		values
			(%s, now(), now(), 'Administrator', 'Administrator', 0, %s,
			 %s, 'permissions', 'DocType', 1, %s, 1)
		""",
		(frappe.generate_hash(length=10), next_idx, TRANSFER, role),
	)
