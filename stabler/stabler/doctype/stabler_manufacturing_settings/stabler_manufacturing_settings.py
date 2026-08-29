"""Per-company manufacturing configuration. Today it holds one thing: where a
recorded loss goes.

One row per company, named after the company (`autoname: field:company` plus
`unique: 1`), so a second row for the same company collides on the primary key —
the same shape as `Vehicle Finance Settings` and `Remittance Settings`. No
`validate` check is needed for that and adding one would be a second, weaker copy
of a constraint the database already holds.

Why a settings doctype rather than a constant or a tenant name. Measured on anjan
2026-08-27: **two** scrap warehouses already exist there (`Yaroqsiz mahsulotlar
ombori - A`, live since 2026-05-02 with $719 standing in it, and `Ishlab
chiqarish yaroqsiz mahsulotlar ombori - A`, used once), and most of the seven
tenants have none at all. A constant would be wrong on the tenant that has two
and meaningless on the five that have none, and branching on the tenant's name is
forbidden outright (`.claude/rules/30-tenant-modules.md`) -- the repo's own
`guards` target refuses that pattern, including in a comment quoting it. Which of
the two anjan uses is a question only Zafar can answer, and this is the field he
answers it in.

Rows are created lazily — no seed patch. A patch cannot plant a row for a
doctype this same migrate is creating on a fresh install, and there is no
defensible default to plant anyway: guessing a scrap warehouse is exactly the
mistake this field exists to prevent.

Deliberately NOT carried here: a `accounting_policy_approved` / `_by` / `_on`
sign-off like `Vehicle Finance Settings`. That one gates a posting engine that
writes GL entries by itself, so somebody has to accept the policy once, in
advance. This module posts nothing: every scrap record produces a **draft**
Material Transfer that a human submits in the Desk. The sign-off already exists,
per document, and it is the submit. A checkbox asserting it in advance would be a
weaker copy of a control that already runs on every single record.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


def get_settings(company: str) -> Document | None:
	"""The settings row for a company, or None when it has never been configured."""
	if not company or not frappe.db.exists("Stabler Manufacturing Settings", company):
		return None
	return frappe.get_doc("Stabler Manufacturing Settings", company)


def get_scrap_warehouse(company: str) -> str:
	"""The warehouse a recorded loss is transferred into. Throws when unset.

	Throws rather than returning None, and the caller does not get to carry on
	without it. The whole reason the loss half of this feature was held back is
	that "5 kg lost" as a bare number contradicts the stock ledger — the 5 kg is
	still on hand. A scrap record that skipped its draft because nothing was
	configured would recreate exactly that split, and it would do it silently:
	later, a record with no draft is indistinguishable from one whose draft
	somebody deleted.

	The message names the doctype to configure and the company it is missing for.
	It does not explain which warehouse to pick — that is a question about this
	factory, not about this code.
	"""
	settings = get_settings(company)
	warehouse = settings.scrap_warehouse if settings else None
	if not warehouse:
		frappe.throw(
			_(
				"Scrap is not configured for {0}. Name the scrap warehouse in Stabler Manufacturing Settings."
			).format(company)
		)
	return warehouse


class StablerManufacturingSettings(Document):
	def validate(self) -> None:
		"""The scrap warehouse must belong to this company.

		A Link to Warehouse is site-wide and every tenant's warehouses exist on
		it, so nothing in the field itself says the two belong together — the same
		hole `log_line_stop` closed on its `line` argument. Mis-set, it would send
		one company's losses into another company's stock, and because the scrap
		record filters on `company`, the tenant that owns the warehouse would
		never see the arrival and the tenant that filed it could not tell it apart
		from its own.
		"""
		if not self.scrap_warehouse:
			return
		owner_company = frappe.db.get_value("Warehouse", self.scrap_warehouse, "company")
		if owner_company != self.company:
			frappe.throw(_("{0} is not a warehouse of {1}.").format(self.scrap_warehouse, self.company))
