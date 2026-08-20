"""Hash the remittance pickup codes that are sitting in plaintext on Journal Entry.

`create_remittance()` wrote the pickup code straight into the hidden
`stabler_pickup_code` custom field, so anyone who could open the register Journal
Entry could read the code that collects the cash. The field is now written as
`scheme$salt$digest` (see `stabler.api._remittance_pickup_code.store_pickup_code`) and payout
compares digests, so every pre-existing plaintext value has to be converted or the
transfer becomes unpayable.

The conversion is mechanical, not a judgement call: the stored value IS the code,
so hashing it in place preserves verification exactly. It is one-way by design —
after this runs, the plaintext exists nowhere.

Operational consequence, logged below rather than assumed away: for a transfer that
is registered but not yet paid out, the plaintext in this field was the only copy the
business still held (the legacy New Transfer form discarded the code the API
returned; both it and the engine behind it were retired on 2026-08-20). Those
receivers can no longer be verified by code and need a refund or a manager override.
The patch prints that count so the number is on the record.

Idempotent: rows already in `scheme$salt$digest` form are skipped, so a second run
converts nothing. Pre-sync safe: it touches the existing v33 custom field only.
"""

import secrets

import frappe

from stabler.api._remittance_pickup_code import hash_pickup_code, is_hashed_pickup_code

_SALT_BYTES = 16


def execute():
	# A site that never carried the remittance fields has nothing to convert.
	# Probe the table first — has_column raises TableMissingError rather than
	# returning False when the table is absent.
	if not frappe.db.table_exists("Journal Entry"):
		return
	if not frappe.db.has_column("Journal Entry", "stabler_pickup_code"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, stabler_pickup_code, stabler_remittance_id, stabler_remittance_stage
		FROM `tabJournal Entry`
		WHERE stabler_pickup_code IS NOT NULL AND stabler_pickup_code != ''
		""",
		as_dict=True,
	)

	converted = 0
	unpayable = 0
	for row in rows:
		stored = (row.stabler_pickup_code or "").strip()
		if is_hashed_pickup_code(stored):
			continue

		# Each row gets its own salt, so two transfers sharing a code do not share
		# a digest.
		frappe.db.set_value(
			"Journal Entry",
			row.name,
			"stabler_pickup_code",
			hash_pickup_code(stored, secrets.token_hex(_SALT_BYTES)),
			update_modified=False,
		)
		converted += 1

		if row.stabler_remittance_stage == "Register" and not frappe.db.exists(
			"Journal Entry",
			{
				"stabler_remittance_id": row.stabler_remittance_id,
				"stabler_remittance_stage": "Payout",
				"docstatus": 1,
			},
		):
			unpayable += 1

	if converted:
		print(
			f"v86: hashed {converted} plaintext remittance pickup code(s); "
			f"{unpayable} of them belong to a registered, not-yet-paid-out transfer "
			f"whose code is now unrecoverable and needs a refund or manager override."
		)
