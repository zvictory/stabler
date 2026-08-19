"""Give Journal Entry and Payment Entry an identity carrier for retried writes.

An operator submits an expense, the shared bench times out, `Expenses.vue`
leaves the filled form on screen and the operator clicks Submit again. The
second click posts a second Journal Entry with the same lines and the same
`cheque_no = f"Exp-{posting_date}"` — a value every expense that day shares, so
it identifies nothing. The ledger now carries the expense twice and the only
difference between the two vouchers is a serial number.

The fix that was rejected: refuse a second write whose payload fingerprint
(company, posting_date, payment_from, base_total, payee) matches a recent one.
Two identical cash expenses in a day are legitimate — the guard would refuse
real work, and operators would learn to defeat it by nudging an amount.

The fix that was taken: the caller supplies an identity for the *intent*, once,
and repeats it verbatim on retry. `stabler/api/money.py::_insert_idempotent`
writes it here; the unique index is what makes the second insert lose.

No `default`, deliberately, and the reason is the migration rather than the
inserts. A `default` reaches the DDL as `ADD COLUMN ... DEFAULT ''`
(`frappe/database/schema.py:255-256`), which stamps every EXISTING row with the
empty string; the `ADD UNIQUE INDEX` that follows then dies with a 1062 on the
second row. Measured on this engine: three NULLs coexist under a unique key,
the second empty string does not. With no default the column is added nullable
with no DEFAULT clause and existing rows stay NULL, so the index builds.

Day-to-day inserts are safe either way — frappe converts a blank value on a
unique field to None before writing (`frappe/model/base_document.py:555-558`),
so a writer that passes "" cannot collide. That protection does not extend
backwards over rows the ALTER itself filled in, which is the whole hazard here.

Idempotent: guarded by a Custom Field existence check, per doctype, so a
half-applied run finishes on the next migrate. Post-model-sync.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_FIELD = {
	"fieldname": "custom_idempotency_key",
	"label": "Idempotency Key",
	"fieldtype": "Data",
	"unique": 1,
	"read_only": 1,
	# `no_copy` is load-bearing, not tidiness: amend copies every field it is not
	# told to drop, and an amendment carrying the original's key would be refused
	# by the very index this patch installs.
	"no_copy": 1,
	"print_hide": 1,
}

_FIELDS = {
	"Journal Entry": [{**_FIELD, "insert_after": "cheque_date"}],
	"Payment Entry": [{**_FIELD, "insert_after": "reference_no"}],
}


def execute():
	todo = {
		doctype: fields
		for doctype, fields in _FIELDS.items()
		if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": _FIELD["fieldname"]})
	}
	if todo:
		create_custom_fields(todo, ignore_validate=True)
