"""ADR-609 P5a — the tender as an ERPNext Accounting Dimension.

WHY. Every profit-and-loss posting of a tender-enabled company has to name
exactly one tender, or general overhead ("GENEL GİDER"). That is QuickBooks
"Class" in ERPNext terms: an Accounting Dimension. Before P5a the tender link
was `custom_crm_deal`, a document-level Custom Field that never reached the
General Ledger, so a tender's P&L was assembled by walking documents — and
missed every posting with no tender-bearing document of its own: the COGS row a
Delivery Note writes, a Purchase Invoice booked without a Purchase Order, a
hand-written Journal Entry.

ALL P5a server logic lives in this module: the fieldname helper, the overhead
deal, the active-tender rule, the document hook, the GL hook, the company-modules
hook and the backfill the patch calls.

Two invariants run through every function here.

  * **The fieldname is read, never spelled.** `dimension_fieldname()` is the only
    place that knows it. A site whose dimension was created by hand under another
    fieldname keeps working, and a site that never ran v103 gets `None` — which
    turns every hook below into a no-op instead of a crash.
  * **The company flag is the gate.** Stabler is one app across seven tenants and
    one `bench restart` hits all of them. A company without `enable_tender` must
    see zero behaviour change: nothing stamped, nothing defaulted, no detail row,
    and GL rows byte-identical to what it posted yesterday.
"""

from __future__ import annotations

import frappe
from frappe import _

from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

DIMENSION_LABEL = "Tender"
DIMENSION_DOCTYPE = "CRM Deal"
OVERHEAD_DEAL_TYPE = "Overhead"
OVERHEAD_ORGANIZATION = "GENEL GİDER"

#: The document-level tender link that predates the dimension (patches v28/v34/v52…).
LEGACY_DEAL_FIELD = "custom_crm_deal"

_FIELDNAME_CACHE = "stabler_tender_dimension_fieldname"
_SOURCE_CACHE = "stabler_tender_dimension_sources"
_VOUCHER_CACHE = "stabler_tender_dimension_vouchers"
_MISS = object()

#: How a voucher's rows name the document the tender came from. Delivery Note
#: items carry `against_sales_order`, not `sales_order` — measured, and the whole
#: reason a DN's COGS row can be attributed at all.
_ITEM_SOURCES = {
	"Sales Invoice": ("items", "sales_order", "Sales Order"),
	"Delivery Note": ("items", "against_sales_order", "Sales Order"),
	"Purchase Invoice": ("items", "purchase_order", "Purchase Order"),
	"Purchase Receipt": ("items", "purchase_order", "Purchase Order"),
}


# ---------------------------------------------------------------------------
# B1 — names and helpers
# ---------------------------------------------------------------------------


def _cache(name: str) -> dict:
	store = getattr(frappe.local, name, None)
	if store is None:
		store = {}
		setattr(frappe.local, name, store)
	return store


def dimension_fieldname() -> str | None:
	"""The fieldname of the enabled CRM Deal Accounting Dimension, or None.

	Cached per request: `stamp_tender` runs on every save of every voucher and
	`default_gl_tender` on every GL row, so this must not be a query per row.
	"""
	cached = getattr(frappe.local, _FIELDNAME_CACHE, _MISS)
	if cached is not _MISS:
		return cached
	value = (
		frappe.db.get_value(
			"Accounting Dimension",
			{"document_type": DIMENSION_DOCTYPE, "disabled": 0},
			"fieldname",
		)
		or None
	)
	setattr(frappe.local, _FIELDNAME_CACHE, value)
	return value


def clear_dimension_cache() -> None:
	"""Forget the per-request caches.

	The patch creates the dimension in the middle of a process that has already
	asked for the fieldname and been told None. Without this it would then set up
	every company against a dimension it believes does not exist.
	"""
	for key in (_FIELDNAME_CACHE, _SOURCE_CACHE, _VOUCHER_CACHE):
		try:
			delattr(frappe.local, key)
		except AttributeError:
			pass


def tender_enabled(company: str) -> bool:
	"""The per-company module flag — never a tenant or site name."""
	if not company:
		return False
	return bool(module_map_for(company).get("tender"))


def _first_deal_status() -> str | None:
	rows = frappe.get_all("CRM Deal Status", fields=["name"], order_by="position asc", limit=1)
	return rows[0]["name"] if rows else None


def overhead_deal(company: str, create: bool = False) -> str | None:
	"""The company's one "GENEL GİDER" deal, queried — never a hardcoded name.

	The name is whatever CRM Deal autoname produced on that site; only the
	`deal_type` marker identifies it, which is what keeps a renamed or re-imported
	deal working.
	"""
	if not company:
		return None
	name = frappe.db.get_value(
		DIMENSION_DOCTYPE, {"company": company, "deal_type": OVERHEAD_DEAL_TYPE}, "name"
	)
	if name or not create:
		return name or None
	doc = frappe.get_doc(
		{
			"doctype": DIMENSION_DOCTYPE,
			"organization": OVERHEAD_ORGANIZATION,
			"deal_type": OVERHEAD_DEAL_TYPE,
			"company": company,
			"status": _first_deal_status(),
			"deal_owner": "Administrator",
		}
	)
	doc.flags.ignore_permissions = 1
	# Every tender field is left empty on purpose: this deal is a ledger bucket,
	# not a bid, and a stage or a parent tender would put it on the tender boards.
	doc.insert(ignore_mandatory=True)
	return doc.name


def ensure_company_setup(company: str) -> dict:
	"""The overhead deal and the company's Accounting Dimension Detail row.

	`mandatory_for_pl` is never turned off once on: it is the only thing that makes
	"no P&L row is unattributed" true rather than aspirational.
	"""
	created = {"overhead_deal": False, "detail_row": False, "default_dimension": False}
	fieldname = dimension_fieldname()
	if not fieldname or not tender_enabled(company):
		return created

	found = overhead_deal(company)
	deal = found or overhead_deal(company, create=True)
	created["overhead_deal"] = not found

	dim_name = frappe.db.get_value(
		"Accounting Dimension", {"document_type": DIMENSION_DOCTYPE, "disabled": 0}, "name"
	)
	if not dim_name:
		return created
	dim = frappe.get_doc("Accounting Dimension", dim_name)
	row = next((d for d in (dim.get("dimension_defaults") or []) if d.company == company), None)
	if row is None:
		dim.append(
			"dimension_defaults",
			{
				"company": company,
				"reference_document": DIMENSION_DOCTYPE,
				"default_dimension": deal,
				"mandatory_for_pl": 1,
				"mandatory_for_bs": 0,
			},
		)
		created["detail_row"] = True
	elif not row.default_dimension:
		row.default_dimension = deal
		created["default_dimension"] = True
	if created["detail_row"] or created["default_dimension"]:
		dim.flags.ignore_permissions = 1
		dim.save()
	return created


# ---------------------------------------------------------------------------
# B3 — the active-tender rule
# ---------------------------------------------------------------------------


def is_active_tender(deal: str, company: str) -> bool:
	"""Whether `deal` is a tender of `company` that may still receive cost.

	Mirrors the tender board, which hides Closed and Cancelled Sales Orders: a won
	tender whose every submitted order is closed is finished, and anything posted
	against it now is almost certainly a mis-tag. A won tender with NO order at all
	is still active — "every order is closed" is vacuously true over an empty list,
	and that reading would refuse a tender won this morning.
	"""
	if not deal or not company:
		return False
	fields = ["company", "deal_type"]
	has_stage = frappe.db.has_column(DIMENSION_DOCTYPE, "custom_tender_stage")
	if has_stage:
		fields.append("custom_tender_stage")
	row = frappe.db.get_value(DIMENSION_DOCTYPE, deal, fields, as_dict=True)
	if not row:
		return False
	if row.get("company") != company or row.get("deal_type") != "Tender":
		return False
	stage = (row.get("custom_tender_stage") or "").strip()
	if stage == "lost":
		return False
	if stage == "won" and frappe.db.has_column("Sales Order", LEGACY_DEAL_FIELD):
		orders = frappe.get_all(
			"Sales Order",
			filters={LEGACY_DEAL_FIELD: deal, "docstatus": 1},
			fields=["status"],
			limit_page_length=0,
		)
		if orders and all((o.get("status") in ("Closed", "Cancelled")) for o in orders):
			return False
	return True


def assert_selectable_tender(deal: str, company: str) -> None:
	"""Refuse a value a writer may not CHOOSE today.

	Deliberately not a read-time or save-time re-validation: a document that already
	carries a tender which has since been lost stays readable and savable. The check
	runs only where a caller SENDS a value.
	"""
	if not deal:
		return
	if deal == overhead_deal(company):
		return
	if is_active_tender(deal, company):
		return
	frappe.throw(_("Only an active tender or GENEL GİDER can be selected."))


def tender_label(deal: str, company: str) -> str:
	"""What a screen shows for a stored value — never the CRM autoname."""
	if not deal:
		return ""
	if deal == overhead_deal(company):
		return OVERHEAD_ORGANIZATION
	return frappe.db.get_value(DIMENSION_DOCTYPE, deal, "organization") or deal


def list_active_tenders(
	company: str, fields: list[str], search: str = "", page_length: int = 50, start: int = 0
) -> list[dict]:
	"""What a tender picker may offer: GENEL GİDER first, then live tenders.

	The overhead deal leads and is offered unconditionally — including when the
	search matches nothing and when no tender is running at all — because every
	expense needs SOME value and this is the honest one. `fields` is passed in by
	the caller so the row shape stays defined in `api/crm.py` beside the board
	that already reads it, and the RULE for which deals qualify stays here.
	"""
	rows: list[dict] = []
	overhead = overhead_deal(company)
	if overhead:
		row = frappe.db.get_value(DIMENSION_DOCTYPE, overhead, fields, as_dict=True) or {}
		row = dict(row)
		row["name"] = overhead
		row["organization"] = OVERHEAD_ORGANIZATION
		row["is_overhead"] = 1
		rows.append(row)
	if not frappe.db.has_column(DIMENSION_DOCTYPE, "deal_type"):
		return rows

	kwargs = {
		"filters": {"company": company, "deal_type": "Tender"},
		"fields": fields,
		"order_by": "modified desc",
		"limit_page_length": min(max(int(page_length or 50), 1), 500),
		"start": max(int(start or 0), 0),
	}
	if search:
		kwargs["or_filters"] = [[field, "like", f"%{search}%"] for field in ("organization", "lead_name")]
	# `get_list`, not `get_all`: role and user permissions belong inside the query.
	for row in frappe.get_list(DIMENSION_DOCTYPE, **kwargs):
		if not is_active_tender(row["name"], company):
			continue
		row = dict(row)
		row["is_overhead"] = 0
		rows.append(row)
	return rows


# ---------------------------------------------------------------------------
# B4 — the document hook
# ---------------------------------------------------------------------------


def _child_meta(doc, table: str):
	field = frappe.get_meta(doc.doctype).get_field(table)
	return frappe.get_meta(field.options) if field and field.options else None


def _legacy_deal(doc) -> str | None:
	if not frappe.get_meta(doc.doctype).has_field(LEGACY_DEAL_FIELD):
		return None
	return doc.get(LEGACY_DEAL_FIELD) or None


def _source_tender(doctype: str, name: str, fieldname: str) -> str | None:
	"""The tender a source document carries — its dimension field, else its deal.

	Cached per request: ten invoice lines off one order must be one read, not ten.
	"""
	if not doctype or not name:
		return None
	cache = _cache(_SOURCE_CACHE)
	key = (doctype, name)
	if key in cache:
		return cache[key]
	meta = frappe.get_meta(doctype)
	fields = [f for f in (fieldname, LEGACY_DEAL_FIELD) if meta.has_field(f)]
	value = None
	if fields:
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
		for field in fields:
			if row.get(field):
				value = row[field]
				break
	cache[key] = value
	return value


def _agreed_source_value(rows, source_field: str, source_doctype: str, fieldname: str) -> str | None:
	values = set()
	for row in rows:
		source = row.get(source_field)
		if not source:
			continue
		value = _source_tender(source_doctype, source, fieldname)
		if value:
			values.add(value)
	return values.pop() if len(values) == 1 else None


def _stamp_journal_entry(doc, fieldname: str) -> None:
	"""The Journal Entry PARENT is not a dimension doctype; its account rows are.

	`get_gl_dict` builds a JE's ledger rows one per `Journal Entry Account`, so the
	row is the only place a value can reach the ledger from.
	"""
	rows = doc.get("accounts") or []
	if not rows:
		return
	meta = _child_meta(doc, "accounts")
	if not meta or not meta.has_field(fieldname):
		return
	value = _legacy_deal(doc)
	if not value:
		return
	for row in rows:
		if not row.get(fieldname):
			row.set(fieldname, value)


def stamp_tender(doc, method=None):
	"""`before_validate`: carry the tender from the document onto the dimension.

	Never overwrites a value the caller already chose, and never writes the
	overhead deal at document level — GENEL GİDER is a LEDGER default applied per
	GL row by `default_gl_tender`. Writing it here would make an untagged invoice
	look like a deliberate overhead decision.
	"""
	company = doc.get("company")
	if not company or not tender_enabled(company):
		return
	fieldname = dimension_fieldname()
	if not fieldname:
		return

	if doc.doctype == "Journal Entry":
		_stamp_journal_entry(doc, fieldname)
		return

	parent_has = frappe.get_meta(doc.doctype).has_field(fieldname)
	table, source_field, source_doctype = _ITEM_SOURCES.get(doc.doctype, ("items", None, None))
	child_meta = _child_meta(doc, table)
	rows_have = bool(child_meta and child_meta.has_field(fieldname))
	if not parent_has and not rows_have:
		return
	rows = list(doc.get(table) or [])

	if parent_has and not doc.get(fieldname):
		value = _legacy_deal(doc)
		if not value and rows and source_field:
			# Two source orders naming two tenders have no honest parent value: one
			# would attribute BOTH lines to one of them. Leave the parent empty and
			# let the rows carry the truth.
			value = _agreed_source_value(rows, source_field, source_doctype, fieldname)
		if value:
			doc.set(fieldname, value)

	if not rows_have:
		return
	parent_value = doc.get(fieldname) if parent_has else None
	for row in rows:
		if row.get(fieldname):
			continue
		value = parent_value
		if not value and source_field:
			value = _source_tender(source_doctype, row.get(source_field), fieldname)
		if value:
			row.set(fieldname, value)


# ---------------------------------------------------------------------------
# B5 — the GL safety net
# ---------------------------------------------------------------------------


def _voucher_tender(voucher_type: str, voucher_no: str, fieldname: str) -> str | None:
	"""The voucher's own value, else the one value its item rows agree on.

	Guarded with `has_field` before any row read: Period Closing Voucher has no
	item table at all, and an exception here fails the POSTING, not the tag.
	"""
	if not voucher_type or not voucher_no:
		return None
	cache = _cache(_VOUCHER_CACHE)
	key = (voucher_type, voucher_no)
	if key in cache:
		return cache[key]
	value = None
	meta = frappe.get_meta(voucher_type)
	if meta.has_field(fieldname):
		value = frappe.db.get_value(voucher_type, voucher_no, fieldname) or None
	if not value:
		table = meta.get_field("items")
		child = frappe.get_meta(table.options) if table and table.options else None
		if child and child.has_field(fieldname):
			values = {
				row
				for row in frappe.get_all(
					table.options,
					filters={"parent": voucher_no, "parenttype": voucher_type},
					pluck=fieldname,
					limit_page_length=0,
				)
				if row
			}
			if len(values) == 1:
				value = values.pop()
	cache[key] = value
	return value


def default_gl_tender(doc, method=None):
	"""`before_validate` on GL Entry: no P&L row of a tender company stays empty.

	This is the safety net for every writer P5a does not touch — Stock Entry,
	Landed Cost Voucher, Payment Entry, Expense Claim, a repost — and the reason
	`mandatory_for_pl` can be switched on without taking the ledger down.

	Balance-sheet rows are left alone (decision 2): the cash leg of an expense is
	not a tender cost, and filling it would double every tender's figure the moment
	P5b sums the dimension.
	"""
	company = doc.get("company")
	if not company or not tender_enabled(company):
		return
	fieldname = dimension_fieldname()
	if not fieldname or doc.get(fieldname) or doc.get("is_cancelled"):
		return
	if not frappe.get_meta("GL Entry").has_field(fieldname):
		return
	if frappe.get_cached_value("Account", doc.get("account"), "report_type") != "Profit and Loss":
		return

	value = _voucher_tender(doc.get("voucher_type"), doc.get("voucher_no"), fieldname)
	if not value:
		value = overhead_deal(company)
	if not value:
		# Never create a CRM Deal inside a GL transaction: an insert here runs
		# inside somebody's submit, and a half-written deal would outlive a rolled
		# back posting. Name the company and the action that repairs it instead.
		frappe.throw(
			_("GENEL GİDER deal is missing for {0}; save Stabler Company Modules or run patch v103.").format(
				company
			)
		)
	doc.set(fieldname, value)


# ---------------------------------------------------------------------------
# B6 — the backfill the patch calls
# ---------------------------------------------------------------------------

#: `custom_crm_deal` already lives on these parents (patches v28/v30/v34/v68), so
#: their dimension value is a straight copy and their rows follow the parent.
_LEGACY_PARENTS = (
	("Sales Order", "Sales Order Item"),
	("Purchase Order", "Purchase Order Item"),
	("Supplier Quotation", "Supplier Quotation Item"),
	("Request for Quotation", "Request for Quotation Item"),
)

#: These never carried `custom_crm_deal`, so their value is DERIVED from the
#: document each line came from — and only when the lines agree on one tender.
_DERIVED_PARENTS = (
	("Sales Invoice", "Sales Invoice Item", "sales_order", "Sales Order"),
	("Delivery Note", "Delivery Note Item", "against_sales_order", "Sales Order"),
	("Purchase Invoice", "Purchase Invoice Item", "purchase_order", "Purchase Order"),
)

_GL_VOUCHERS = ("Journal Entry", "Sales Invoice", "Purchase Invoice", "Delivery Note")


def _column_exists(doctype: str, column: str) -> bool:
	"""`has_column` RAISES on a doctype whose table does not exist — probe first."""
	try:
		if not frappe.db.table_exists(doctype):
			return False
		return bool(frappe.db.has_column(doctype, column))
	except Exception:
		return False


def _fill(results: dict, label: str, source: str, set_expr: str, where: str, params: dict) -> None:
	"""Count first, then update the SAME rows.

	The count is what the patch prints, so it has to be the number of rows that
	actually changed — hence one WHERE, used twice — and a zero count issues no
	UPDATE at all, which is what makes a re-run provably a no-op.
	"""
	rows = frappe.db.sql(f"SELECT COUNT(*) FROM {source} WHERE {where}", params)
	found = int(rows[0][0]) if rows and rows[0] and rows[0][0] else 0
	if found:
		frappe.db.sql(f"UPDATE {source} SET {set_expr} WHERE {where}", params)
	results[label] = found


def backfill(companies: list[str], fieldname: str) -> dict:
	"""Give history the dimension its documents already implied.

	Raw SQL on purpose: this touches every Sales Order and GL row a tenant has
	ever written, and running it through the document API would fire every hook,
	re-validate every submitted voucher and bump `modified` on documents nobody
	edited — which breaks the SPA's concurrency checks and rewrites their audit
	trail. Nothing here is a decision: every value copied is one the document
	already stated. Pre-P5 rows with no stated tender stay EMPTY rather than being
	given GENEL GİDER, so P5b can report them honestly as unassigned.

	Returns `{table: rows_updated}`; a second run returns zeros.
	"""
	results: dict = {}
	if not companies or not fieldname:
		return results
	# The fieldname cannot be bound as a parameter — it is an identifier. ERPNext
	# validates it on the Accounting Dimension, but this module is what would
	# carry the injection if that ever stopped being true.
	if not all(part.isidentifier() for part in [fieldname]) or not fieldname.islower():
		frappe.throw(_("Refusing to build SQL for dimension fieldname {0}.").format(fieldname))

	params = {"companies": tuple(companies)}
	deal = LEGACY_DEAL_FIELD

	for parent, child in _LEGACY_PARENTS:
		if not _column_exists(parent, fieldname) or not _column_exists(parent, deal):
			continue
		_fill(
			results,
			parent,
			f"`tab{parent}`",
			f"`{fieldname}` = `{deal}`",
			f"company IN %(companies)s AND COALESCE(`{fieldname}`, '') = '' AND COALESCE(`{deal}`, '') <> ''",
			params,
		)
		if _column_exists(child, fieldname):
			_fill(results, child, *_from_parent(parent, child, fieldname, fieldname), params)

	if _column_exists("Journal Entry", deal) and _column_exists("Journal Entry Account", fieldname):
		_fill(
			results,
			"Journal Entry Account",
			*_from_parent("Journal Entry", "Journal Entry Account", fieldname, deal),
			params,
		)

	for parent, child, link, source in _DERIVED_PARENTS:
		if not _column_exists(parent, fieldname) or not _column_exists(source, fieldname):
			continue
		if not _column_exists(child, link):
			continue
		agreed = (
			f"(SELECT ci.parent AS doc, MIN(s.`{fieldname}`) AS val, "
			f"COUNT(DISTINCT s.`{fieldname}`) AS n FROM `tab{child}` ci "
			f"JOIN `tab{source}` s ON s.name = ci.`{link}` "
			f"WHERE ci.parenttype = '{parent}' AND COALESCE(s.`{fieldname}`, '') <> '' "
			f"GROUP BY ci.parent)"
		)
		_fill(
			results,
			parent,
			f"`tab{parent}` p JOIN {agreed} d ON d.doc = p.name AND d.n = 1",
			f"p.`{fieldname}` = d.val",
			f"p.company IN %(companies)s AND COALESCE(p.`{fieldname}`, '') = ''",
			params,
		)
		if _column_exists(child, fieldname):
			_fill(results, child, *_from_parent(parent, child, fieldname, fieldname), params)

	if _column_exists("GL Entry", fieldname):
		for voucher in _GL_VOUCHERS:
			# A Journal Entry's document-level tender IS `custom_crm_deal`: its
			# parent is not one of the 52 dimension doctypes, only its rows are.
			source_field = deal if voucher == "Journal Entry" else fieldname
			if not _column_exists(voucher, source_field):
				continue
			_fill(
				results,
				f"GL Entry ({voucher})",
				f"`tabGL Entry` g JOIN `tab{voucher}` p ON p.name = g.voucher_no",
				f"g.`{fieldname}` = p.`{source_field}`",
				f"g.voucher_type = '{voucher}' AND g.company IN %(companies)s "
				f"AND COALESCE(g.`{fieldname}`, '') = '' AND COALESCE(p.`{source_field}`, '') <> ''",
				params,
			)
	return results


def _from_parent(parent: str, child: str, fieldname: str, source_field: str) -> tuple[str, str, str]:
	"""The (source, SET, WHERE) that copies a parent's value onto its own rows."""
	return (
		f"`tab{child}` c JOIN `tab{parent}` p ON p.name = c.parent AND c.parenttype = '{parent}'",
		f"c.`{fieldname}` = p.`{source_field}`",
		f"p.company IN %(companies)s AND COALESCE(c.`{fieldname}`, '') = '' "
		f"AND COALESCE(p.`{source_field}`, '') <> ''",
	)


# ---------------------------------------------------------------------------
# B7 — Stabler Company Modules
# ---------------------------------------------------------------------------


def on_company_modules_update(doc, method=None):
	"""Turning the tender module on sets the company up; turning it off removes nothing.

	Deleting the detail row would leave the company's historical GL rows carrying a
	dimension nothing declares any more, and re-enabling would not bring them back.
	"""
	if not doc.get("enable_tender") or not dimension_fieldname():
		return
	ensure_company_setup(doc.get("company"))
