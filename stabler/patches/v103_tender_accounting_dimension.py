"""Install the Tender Accounting Dimension and give history its values (ADR-609).

WHY. Stabler's tender P&L was assembled from documents carrying `custom_crm_deal`,
a link that never reaches the General Ledger. Every posting without a
tender-bearing document of its own was therefore missing from it. This patch turns
the tender into an ERPNext Accounting Dimension over CRM Deal — QuickBooks "Class"
— so the attribution lives on the ledger row itself, and switches
`mandatory_for_pl` on for every tender-enabled company so no future P&L row can be
written without one.

Runs on all 8 sites and only does the tenant-visible half where it belongs:

  * Step 1 widens the `deal_type` Select to `Standard\\nTender\\nOverhead` and
    backfills NULLs to `Standard`. This happens EVERYWHERE, because
    `_crm_list` filters `deal_type != "Overhead"` and MariaDB's `!=` drops a NULL
    row — without the backfill, every deal predating v60 would vanish from the
    CRM board on a site that never sees a tender.
  * Step 2 stops there when no company on the site has `enable_tender`. The
    dimension puts a Link field on 52 doctypes; a tenant that runs no tenders must
    not grow 52 fields on its forms.

The dimension's fields are installed by calling
`make_dimension_in_accounting_doctypes` DIRECTLY. Measured in
`accounting_dimension.py:85-91`: `on_update` creates the fields synchronously only
under `frappe.in_test`, and otherwise `frappe.enqueue`s them after commit. A patch
that relied on that would finish, print success, and leave the site holding a
dimension whose columns do not exist yet — with `mandatory_for_pl` already on. The
six doctypes the ledger cannot work without are asserted afterwards and the patch
throws if any is missing: a half-installed dimension must fail loudly.

Idempotent. `has_column` / `exists` guards throughout, and `patches.txt` places
this entry in the post-model-sync half where every patch from v81 on lives — the
guards are the house style regardless of which half it sits in. A second run
reports zeros for every count and issues no UPDATE at all.

    cd /path/to/frappe-bench && PYTHONPATH=/path/to/stabler bench --site <site> \\
        execute stabler.patches.v103_tender_accounting_dimension.execute
"""

import frappe

from stabler.api.tender_dimension import (
	DIMENSION_DOCTYPE,
	DIMENSION_LABEL,
	OVERHEAD_DEAL_TYPE,
	backfill,
	clear_dimension_cache,
	ensure_company_setup,
	tender_enabled,
)

#: Only the name a NEWLY CREATED dimension gets. A site that already has a CRM
#: Deal dimension keeps its own fieldname — see `_ensure_dimension`.
DIMENSION_FIELDNAME = "tender"
DEAL_TYPE_OPTIONS = "Standard\nTender\nOverhead"

#: The doctypes whose ledger work is impossible without the field. Not the whole
#: 52 — these are the ones this feature reads and writes, so a missing one here is
#: a broken install rather than a cosmetic gap.
_REQUIRED_ON = (
	"GL Entry",
	"Journal Entry Account",
	"Sales Invoice",
	"Purchase Invoice",
	"Sales Order",
	"Purchase Order",
)


def execute():
	counts = {
		"deal_type_options_widened": 0,
		"deal_type_backfilled": 0,
		"dimension_created": 0,
		"custom_fields_created": 0,
		"overhead_deals_created": 0,
		"detail_rows_created": 0,
		"default_dimensions_filled": 0,
	}
	counts.update(_widen_deal_type())

	companies = _tender_companies()
	if not companies:
		_report(counts, "no tender-enabled company on this site — dimension not created")
		return counts

	created, fieldname = _ensure_dimension()
	counts.update(created)
	clear_dimension_cache()  # the fieldname was read (as None) before it existed
	_assert_fields_landed(fieldname)

	for company in companies:
		created = ensure_company_setup(company)
		counts["overhead_deals_created"] += int(bool(created["overhead_deal"]))
		counts["detail_rows_created"] += int(bool(created["detail_row"]))
		counts["default_dimensions_filled"] += int(bool(created["default_dimension"]))

	counts.update(backfill(companies, fieldname))
	frappe.db.commit()
	_report(counts, f"tender companies: {', '.join(companies)}")
	return counts


def _widen_deal_type() -> dict:
	"""Offer `Overhead` and leave no NULL `deal_type` behind."""
	out = {"deal_type_options_widened": 0, "deal_type_backfilled": 0}
	if not frappe.db.table_exists(DIMENSION_DOCTYPE):
		return out
	if not frappe.db.has_column(DIMENSION_DOCTYPE, "deal_type"):
		return out

	field = frappe.db.get_value(
		"Custom Field", {"dt": DIMENSION_DOCTYPE, "fieldname": "deal_type"}, ["name", "options"], as_dict=True
	)
	if field and OVERHEAD_DEAL_TYPE not in (field.get("options") or ""):
		frappe.db.set_value("Custom Field", field["name"], "options", DEAL_TYPE_OPTIONS)
		frappe.clear_cache(doctype=DIMENSION_DOCTYPE)
		out["deal_type_options_widened"] = 1

	# Raw SQL: this is a data repair on rows nobody edited, and `deal_type` is a
	# tag no hook reacts to.
	rows = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{DIMENSION_DOCTYPE}` WHERE COALESCE(deal_type, '') = ''")
	found = int(rows[0][0]) if rows and rows[0] and rows[0][0] else 0
	if found:
		frappe.db.sql(
			f"UPDATE `tab{DIMENSION_DOCTYPE}` SET deal_type = 'Standard' WHERE COALESCE(deal_type, '') = ''"
		)
	out["deal_type_backfilled"] = found
	return out


def _tender_companies() -> list[str]:
	if not frappe.db.table_exists("Stabler Company Modules"):
		return []
	return [
		row["name"]
		for row in frappe.get_all("Company", fields=["name"], limit_page_length=0)
		if tender_enabled(row["name"])
	]


def _ensure_dimension() -> tuple[dict, str]:
	"""Reuse the site's CRM Deal dimension, or create it, then install its fields.

	Returns the counts AND the fieldname that is actually in force.
	`make_dimension_in_accounting_doctypes` installs the 52 Link fields under the
	DIMENSION's own fieldname, so on a site whose dimension was created by hand
	under another name every later step — the landed-fields assertion and the
	backfill's SQL — has to use that name and not `DIMENSION_FIELDNAME`. Getting
	this wrong throws inside `bench migrate`, which writes no Patch Log row, so
	every subsequent migrate aborts in the same place.
	"""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		make_dimension_in_accounting_doctypes,
	)

	out = {"dimension_created": 0, "custom_fields_created": 0}
	existing = frappe.db.get_value("Accounting Dimension", {"document_type": DIMENSION_DOCTYPE}, "name")
	if existing:
		dimension = frappe.get_doc("Accounting Dimension", existing)
		if dimension.get("disabled"):
			# Every hook reads `dimension_fieldname()`, which filters `disabled: 0`,
			# so a disabled dimension leaves the whole feature inert while this patch
			# installs its fields and prints zeros. A second dimension is not an
			# option either — erpnext's `validate_doctype` refuses a duplicate
			# `document_type` — so the repair is a human decision, named here.
			frappe.throw(
				f"The CRM Deal Accounting Dimension `{existing}` is disabled. "
				"Enable it or delete it, then run this patch again: while it is "
				"disabled every tender hook reads no fieldname and does nothing."
			)
	else:
		dimension = frappe.get_doc(
			{
				"doctype": "Accounting Dimension",
				"document_type": DIMENSION_DOCTYPE,
				"label": DIMENSION_LABEL,
				"fieldname": DIMENSION_FIELDNAME,
			}
		)
		dimension.flags.ignore_permissions = 1
		dimension.insert()
		out["dimension_created"] = 1

	before = frappe.db.count("Custom Field", {"fieldname": dimension.fieldname, "options": DIMENSION_DOCTYPE})
	make_dimension_in_accounting_doctypes(doc=dimension)
	after = frappe.db.count("Custom Field", {"fieldname": dimension.fieldname, "options": DIMENSION_DOCTYPE})
	out["custom_fields_created"] = after - before
	return out, dimension.fieldname


def _assert_fields_landed(fieldname: str) -> None:
	missing = [
		doctype for doctype in _REQUIRED_ON if not frappe.get_meta(doctype, cached=False).has_field(fieldname)
	]
	if missing:
		frappe.throw(
			f"Tender dimension field `{fieldname}` is missing on: {', '.join(missing)}. "
			"The dimension is half-installed; do not leave it in this state."
		)


def _report(counts: dict, note: str) -> None:
	# Printed as well as logged: the deploy reads patch OUTPUT, and a count that
	# only reaches the log is a count nobody checks.
	line = f"v103 tender dimension — {note}; " + ", ".join(f"{k}={v}" for k, v in counts.items())
	frappe.logger("stabler").info(line)
	print(line)
