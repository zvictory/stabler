"""Pure, frappe-free rules for the imports SPA API (``stabler.api.imports``).

Everything here is I/O-free so it unit-tests in milliseconds without a bench:

* **Cost masking** — the K3 decision (migration plan §2) hides landed-cost /
  dual-pricing figures (``docs_total``, ``cash_difference``, container item
  rate/amount, container cost-line amounts, truck transport cost, import-expense
  and freight payment splits) from users who lack cost visibility. The visible
  set of roles is resolved in the Frappe layer; here we only strip a named set
  of keys out of a payload dict / list-of-dicts.
* **KPI date window** — the "payment due" rule keys off ``eta_transit_port``:
  the 70% balance is due 7 days before arrival at the Iran transit port, so the
  home dashboard surfaces CIs whose ETA falls inside the next N days.
* **List filter builders** — the WHERE-clause fragments + bound params for the
  Commercial Invoice / Import Container / Import Truck list endpoints, built as
  parametrised SQL (``%(name)s``) so the Frappe layer passes them straight to
  ``frappe.db.sql`` without string interpolation of user input.
* **PI ↔ CI matching** — the contract/shipment reconciliation math (see the
  section header near the bottom of this file for the invariants).
"""

from __future__ import annotations

import datetime
import math
import re

# ---------------------------------------------------------------------------
# Cost masking — the named field sets stripped for users lacking cost visibility
# ---------------------------------------------------------------------------

#: Commercial Invoice header fields that carry docs/cash-difference pricing.
CI_MASK_FIELDS: tuple[str, ...] = ("docs_total", "cash_difference")

#: Commercial Invoice list-endpoint derived cost columns.
CI_LIST_MASK_FIELDS: tuple[str, ...] = ("docs_total", "cash_difference")

#: Freight Booking money joined onto a container. `amount`, `cash_payment` and
#: `bank_payment` are permlevel 1 on their own doctype, and the container
#: endpoints read them through raw SQL, which does not honour permlevel -- so
#: the same figures must be masked by name here or the join is a way around it.
FREIGHT_MASK_FIELDS: tuple[str, ...] = ("transport_cost", "paid_cash", "paid_bank")

#: Import Container header cost fields (all permlevel 1 in the doctype).
CONTAINER_MASK_FIELDS: tuple[str, ...] = (
	"total_amount",
	"allocated_deposit_amount",
	"balance_due_amount",
	"payment_70_amount",
	*FREIGHT_MASK_FIELDS,
)

#: Import Container list-endpoint derived cost column.
CONTAINER_LIST_MASK_FIELDS: tuple[str, ...] = (
	"total_amount",
	"cost_lines_total",
	*FREIGHT_MASK_FIELDS,
)

#: Import Container Item cost fields (permlevel 1).
CONTAINER_ITEM_MASK_FIELDS: tuple[str, ...] = ("rate", "amount")

#: Container Cost Line amounts (landed-cost components — managers only).
CONTAINER_COST_LINE_MASK_FIELDS: tuple[str, ...] = ("amount", "amount_uzs")

#: Import Truck transport cost (permlevel 1).
TRUCK_MASK_FIELDS: tuple[str, ...] = ("transport_cost",)

#: Import Expense payment split (permlevel 1).
EXPENSE_MASK_FIELDS: tuple[str, ...] = ("bank_payment", "cash_payment")

#: Freight Booking amount + payment split (permlevel 1).
FREIGHT_MASK_FIELDS: tuple[str, ...] = ("amount", "bank_payment", "cash_payment")

#: Transporter-desk row money. The SAME permlevel-1 Freight Booking columns as
#: FREIGHT_MASK_FIELDS, under the aliases the dashboard projects them to, plus
#: the two figures it derives from them. A separate tuple because an alias makes
#: the mask silently miss: `mask_named` matches keys literally, so reusing
#: FREIGHT_MASK_FIELDS here would null nothing and read as masked.
TRANSPORTER_ROW_MASK_FIELDS: tuple[str, ...] = (
	"transport_cost",
	"paid_cash",
	"paid_bank",
	"total_paid",
	"balance",
)

#: Transporter-desk per-currency summary money — the same block, aggregated.
#: Masking rows but not the totals would hand back every hidden figure summed.
TRANSPORTER_SUMMARY_MASK_FIELDS: tuple[str, ...] = (
	"total_freight_cost",
	"total_paid_cash",
	"total_paid_bank",
	"total_paid",
	"total_outstanding",
)


def mask_named(payload, fields, visible: bool):
	"""Null-out every key in *fields* on *payload* unless *visible*.

	*payload* is a single ``dict`` or a ``list`` of dicts, mutated in place and
	also returned. ``visible=True`` is a no-op (the user may see cost data).
	Missing keys and non-dict list items are ignored.
	"""
	if visible:
		return payload
	rows = payload if isinstance(payload, list) else [payload]
	for row in rows:
		if isinstance(row, dict):
			for field in fields:
				if field in row:
					row[field] = None
	return payload


# ---------------------------------------------------------------------------
# The 9-status Commercial Invoice / Container logistics pipeline (KPI buckets)
# ---------------------------------------------------------------------------

CI_STATUSES: tuple[str, ...] = (
	"BOOKED",
	"STUFFED",
	"GATE_IN",
	"ON_BOARD",
	"IN_TRANSIT",
	"DISCHARGED",
	"AVAILABLE",
	"ARRIVED_AT_IRAN",
	"DELIVERED_TO_UZBEKISTAN",
)

#: Import Truck statuses that count as "on the road" for the home KPI.
TRUCK_IN_TRANSIT_STATUSES: tuple[str, ...] = (
	"DEPARTED_IRAN",
	"AT_BORDER",
	"CROSSED_BORDER",
	"IN_TRANSIT",
)


def status_counts(rows, statuses=CI_STATUSES) -> dict[str, int]:
	"""Fold ``[{"status": s, "count": n}, ...]`` into a full bucket dict.

	Every status in *statuses* is present (0 when absent); any extra status
	seen in *rows* (e.g. ``Cancelled``) is kept too.
	"""
	out: dict[str, int] = {s: 0 for s in statuses}
	for row in rows or []:
		status = (row or {}).get("status")
		if status is None:
			continue
		out[status] = out.get(status, 0) + int(row.get("count") or 0)
	return out


# ---------------------------------------------------------------------------
# KPI date window — "payment due" keys off eta_transit_port
# ---------------------------------------------------------------------------


def _as_date(value):
	"""Coerce a date / ISO ``yyyy-mm-dd`` string to ``datetime.date`` or None."""
	if value is None or value == "":
		return None
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	return datetime.date.fromisoformat(str(value)[:10])


def days_left(eta, today) -> int | None:
	"""Whole days from *today* to *eta* (negative when overdue), or None."""
	eta_d = _as_date(eta)
	today_d = _as_date(today)
	if eta_d is None or today_d is None:
		return None
	return (eta_d - today_d).days


def eta_upper_bound(today, window_days: int = 7):
	"""The inclusive upper ETA date for the "due within N days" window."""
	today_d = _as_date(today)
	if today_d is None:
		return None
	return today_d + datetime.timedelta(days=window_days)


def is_due_soon(eta, today, window_days: int = 7) -> bool:
	"""True when *eta* is set and falls on/before ``today + window_days``.

	Overdue ETAs (negative ``days_left``) also count — the balance is still due.
	"""
	dl = days_left(eta, today)
	return dl is not None and dl <= window_days


# ---------------------------------------------------------------------------
# List filter builders — parametrised WHERE fragments + bound params
# ---------------------------------------------------------------------------


#: Filter value meaning "rows that belong to no PI Group at all". Cannot collide
#: with a real group — ``Import PI Group`` autonames as ``IPG-{YYYY}-{#####}``.
UNGROUPED = "__none__"


def group_clause(column_expr: str, group: str, param: str = "group") -> tuple[str, dict]:
	"""WHERE fragment for a named PI Group *or* for "has no group".

	The sentinel never reaches SQL as a **value** — picking "ungrouped" turns into
	a NULL test instead. ``NULLIF`` folds the empty string in with NULL because the
	two lists disagree on how "no group" is stored: the PI column can hold an empty
	string, while the CI's derived expression yields NULL.
	"""
	if group == UNGROUPED:
		return f"NULLIF({column_expr}, '') IS NULL", {}
	return f"{column_expr} = %({param})s", {param: group}


def ci_effective_group_expr(has_pi_link: bool = True) -> str:
	"""SQL for a CI's *effective* PI Group (alias ``ci``).

	A CI only carries its own ``import_pi_group`` when someone picked it — either
	a proforma was selected on the form (which copies the group down) or the CI
	was created after its PI had already been grouped. Grouping a PI later never
	reaches the CIs raised from it, so the badge stayed blank for invoices that
	plainly belong to a group. This derives it instead of storing it: group the
	proforma and its CIs light up on the next read, with no write and nothing to
	backfill.

	Precedence: the CI's own link wins (20 msa CIs deliberately sit in a
	different group than their proforma), then the header PI, then the items —
	and only when every item's PI agrees on one group, so a multi-PI invoice
	spanning groups shows nothing rather than an arbitrary pick.

	``count_query`` builds a FROM with **no joins**, so every reference here must
	be on ``ci`` or inside a correlated subquery — never a join alias.
	``ci.custom_proforma_invoice`` is a Custom Field, hence the ``has_pi_link``
	guard; the child table's column ships in the doctype and needs none.
	"""
	branches = ["NULLIF(ci.import_pi_group, '')"]
	if has_pi_link:
		branches.append(
			"NULLIF((SELECT pi2.import_pi_group FROM `tabProforma Invoice` pi2 "
			"WHERE pi2.name = ci.custom_proforma_invoice), '')"
		)
	branches.append(
		"(SELECT MIN(pi3.import_pi_group) FROM `tabCommercial Invoice Item` cii3 "
		"JOIN `tabProforma Invoice` pi3 ON pi3.name = cii3.custom_proforma_invoice "
		"WHERE cii3.parent = ci.name AND IFNULL(pi3.import_pi_group, '') <> '' "
		"HAVING COUNT(DISTINCT pi3.import_pi_group) = 1)"
	)
	return "COALESCE(" + ", ".join(branches) + ")"


#: A CI line is traceable when it names a proforma itself or inherits one from
#: the invoice header. An invoice counts as *unlinked* the moment a single line
#: is untraceable — a partly-linked invoice is exactly the case the scope
#: directive ("every CI must be linked to its PI") exists to surface, so folding
#: it in with the clean ones would hide it.
#:
#: Column-only, no joins: ``count_query`` builds a FROM without any, so every
#: reference is on ``ci`` or inside a correlated subquery.
_CI_UNLINKED_EXPR = """(
    COALESCE(ci.custom_proforma_invoice, '') = ''
    AND (
      NOT EXISTS (SELECT 1 FROM `tabCommercial Invoice Item` cim WHERE cim.parent = ci.name)
      OR EXISTS (
        SELECT 1 FROM `tabCommercial Invoice Item` cim
        WHERE cim.parent = ci.name AND COALESCE(cim.custom_proforma_invoice, '') = ''
      )
    )
  )"""


def ci_pi_match_clause(pi_match, has_pi_link: bool = True) -> str | None:
	"""SQL fragment for the CI list's PI-link filter, or ``None`` for "any".

	Deliberately link-status only. Price / quantity compliance needs the
	per-key contract index (see ``reconcile``), which cannot be expressed as a
	WHERE fragment on a paginated list without a per-row subquery per column;
	that report lives in ``get_ci_pi_discrepancies``.

	Without the header Custom Field (``has_pi_link`` false) nothing is linked,
	so the filter degrades to all-or-nothing rather than lying.
	"""
	if pi_match not in ("linked", "unlinked"):
		return None
	if not has_pi_link:
		return "1=1" if pi_match == "unlinked" else "1=0"
	return _CI_UNLINKED_EXPR if pi_match == "unlinked" else f"NOT {_CI_UNLINKED_EXPR}"


def ci_filter_clauses(
	search=None, status=None, supplier=None, group=None, has_pi_link: bool = True, pi_match=None
):
	"""WHERE fragments + params for ``list_commercial_invoices`` (alias ``ci``)."""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(ci.ci_number LIKE %(search)s OR ci.name LIKE %(search)s "
			"OR ci.supplier LIKE %(search)s OR ci.custom_proforma_invoice LIKE %(search)s "
			"OR EXISTS (SELECT 1 FROM `tabCommercial Invoice Item` cii WHERE cii.parent = ci.name AND cii.custom_proforma_invoice LIKE %(search)s))"
		)
		params["search"] = f"%{search}%"
	if status:
		clauses.append("ci.status = %(status)s")
		params["status"] = status
	if supplier:
		clauses.append("ci.supplier = %(supplier)s")
		params["supplier"] = supplier
	if group:
		# Filter on the same expression the badge renders, so the two can never
		# disagree — a CI showing a group must be reachable by filtering on it,
		# and one showing the "no group" badge must land under the same filter.
		clause, gparams = group_clause(f"({ci_effective_group_expr(has_pi_link)})", group)
		clauses.append(clause)
		params.update(gparams)
	match_clause = ci_pi_match_clause(pi_match, has_pi_link)
	if match_clause:
		clauses.append(match_clause)
	return clauses, params


def container_filter_clauses(search=None, status=None, commercial_invoice=None, bl_type=None):
	"""WHERE fragments + params for ``list_import_containers`` (alias ``c``)."""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(c.container_number LIKE %(search)s OR c.name LIKE %(search)s OR c.seal_number LIKE %(search)s "
			"OR c.commercial_invoice LIKE %(search)s OR ci.ci_number LIKE %(search)s "
			"OR ci.vessel LIKE %(search)s OR ci.bl_number LIKE %(search)s OR s.supplier_name LIKE %(search)s "
			"OR ci.custom_proforma_invoice LIKE %(search)s)"
		)
		params["search"] = f"%{search}%"
	if status:
		clauses.append("c.status = %(status)s")
		params["status"] = status
	if bl_type:
		clauses.append("c.bl_type = %(bl_type)s")
		params["bl_type"] = bl_type
	if commercial_invoice:
		clauses.append("c.commercial_invoice = %(commercial_invoice)s")
		params["commercial_invoice"] = commercial_invoice
	return clauses, params


def truck_filter_clauses(search=None, status=None, commercial_invoice=None):
	"""WHERE fragments + params for ``list_import_trucks`` (alias ``tr``)."""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(tr.truck_number LIKE %(search)s OR tr.name LIKE %(search)s OR tr.driver_name LIKE %(search)s)"
		)
		params["search"] = f"%{search}%"
	if status:
		clauses.append("tr.status = %(status)s")
		params["status"] = status
	if commercial_invoice:
		clauses.append("tr.commercial_invoice = %(commercial_invoice)s")
		params["commercial_invoice"] = commercial_invoice
	return clauses, params


def clamp_page_length(limit, default: int = 50, maximum: int = 200) -> int:
	"""Normalise an SPA page-length arg into a safe 1..maximum int."""
	try:
		n = int(limit)
	except (TypeError, ValueError):
		return default
	if n <= 0:
		return default
	return min(n, maximum)


# ---------------------------------------------------------------------------
# WP6a — GRN Checklist / Truck Receipt / Vet Certificate receiving surface
# ---------------------------------------------------------------------------

#: GRN Checklist header progress statuses (the ``receipt_status`` field).
GRN_RECEIPT_STATUSES: tuple[str, ...] = ("Pending", "Receiving", "Complete", "Discrepancy")

#: GRN variance categories, worst → best, keyed by |variance %| thresholds
#: (2/5/10 — see ``imports_module.grn_math.variance_category``).
GRN_VARIANCE_CATEGORIES: tuple[str, ...] = ("NORMAL", "MINOR", "MAJOR", "CRITICAL")

#: Import Truck statuses at which a truck is physically present to be received
#: (arrived / being unloaded) — the source pool for ``trucks_pending_receipt``.
TRUCK_RECEIVABLE_STATUSES: tuple[str, ...] = ("ARRIVED", "UNLOADING")

#: Vet Certificate review states.
VET_CERT_STATUSES: tuple[str, ...] = ("Pending", "Approved", "Rejected", "Expired")


def grn_filter_clauses(search=None, status=None, variance_category=None):
	"""WHERE fragments + params for ``list_grn_checklists`` (alias ``g``).

	``status`` filters the header ``receipt_status``; ``variance_category`` the
	NORMAL/MINOR/MAJOR/CRITICAL band.
	"""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(g.name LIKE %(search)s OR g.commercial_invoice LIKE %(search)s OR g.supplier LIKE %(search)s)"
		)
		params["search"] = f"%{search}%"
	if status:
		clauses.append("g.receipt_status = %(status)s")
		params["status"] = status
	if variance_category:
		clauses.append("g.variance_category = %(variance_category)s")
		params["variance_category"] = variance_category
	return clauses, params


def truck_receipt_filter_clauses(search=None, grn=None, docstatus=None):
	"""WHERE fragments + params for ``list_truck_receipts`` (alias ``r``).

	``grn`` pins the parent GRN Checklist; ``docstatus`` (0/1/2, or a digit-ish
	string) filters draft/submitted/cancelled. A non-numeric ``docstatus`` is
	ignored rather than throwing.
	"""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append("(r.name LIKE %(search)s OR r.truck LIKE %(search)s)")
		params["search"] = f"%{search}%"
	if grn:
		clauses.append("r.grn_checklist = %(grn)s")
		params["grn"] = grn
	if docstatus is not None and str(docstatus).strip() != "":
		try:
			params["docstatus"] = int(docstatus)
			clauses.append("r.docstatus = %(docstatus)s")
		except (TypeError, ValueError):
			pass
	return clauses, params


# ---------------------------------------------------------------------------
# WP6b — Customs Declaration / Freight Booking / Import Expense surfaces
# ---------------------------------------------------------------------------

#: Customs Declaration (GTD) clearance pipeline (the ``status`` field).
CUSTOMS_DECLARATION_STATUSES: tuple[str, ...] = (
	"Draft",
	"Submitted",
	"Under Review",
	"Approved",
	"Rejected",
)

#: Freight Booking land-freight pipeline (the ``status`` field).
FREIGHT_BOOKING_STATUSES: tuple[str, ...] = (
	"Pending",
	"Booked",
	"In Transit",
	"Delivered",
	"Cancelled",
)

#: Import Expense payment states (derived, not a manual pipeline).
IMPORT_EXPENSE_STATUSES: tuple[str, ...] = ("Pending", "Partial", "Paid")

#: Import Expense categories (mirrors the doctype Select).
IMPORT_EXPENSE_CATEGORIES: tuple[str, ...] = (
	"Border Crossing",
	"Transport",
	"Handling",
	"Storage",
	"Insurance",
	"Documentation",
	"Customs",
	"Other",
)


def customs_declaration_filter_clauses(search=None, status=None, commercial_invoice=None):
	"""WHERE fragments + params for ``list_customs_declarations`` (alias ``cd``)."""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(cd.gtd_number LIKE %(search)s OR cd.name LIKE %(search)s "
			"OR cd.commercial_invoice LIKE %(search)s OR cd.customs_office LIKE %(search)s)"
		)
		params["search"] = f"%{search}%"
	if status:
		clauses.append("cd.status = %(status)s")
		params["status"] = status
	if commercial_invoice:
		clauses.append("cd.commercial_invoice = %(commercial_invoice)s")
		params["commercial_invoice"] = commercial_invoice
	return clauses, params


def freight_booking_filter_clauses(search=None, status=None, commercial_invoice=None):
	"""WHERE fragments + params for ``list_freight_bookings`` (alias ``fb``)."""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(fb.booking_reference LIKE %(search)s OR fb.name LIKE %(search)s "
			"OR fb.transporter LIKE %(search)s OR fb.vehicle_number LIKE %(search)s)"
		)
		params["search"] = f"%{search}%"
	if status:
		clauses.append("fb.status = %(status)s")
		params["status"] = status
	if commercial_invoice:
		clauses.append("fb.commercial_invoice = %(commercial_invoice)s")
		params["commercial_invoice"] = commercial_invoice
	return clauses, params


def import_expense_filter_clauses(search=None, category=None, status=None, commercial_invoice=None):
	"""WHERE fragments + params for ``list_import_expenses`` (alias ``ie``)."""
	clauses: list[str] = []
	params: dict = {}
	if search:
		clauses.append(
			"(ie.name LIKE %(search)s OR ie.invoice_reference LIKE %(search)s "
			"OR ie.supplier LIKE %(search)s OR ie.commercial_invoice LIKE %(search)s)"
		)
		params["search"] = f"%{search}%"
	if category:
		clauses.append("ie.category = %(category)s")
		params["category"] = category
	if status:
		clauses.append("ie.status = %(status)s")
		params["status"] = status
	if commercial_invoice:
		clauses.append("ie.commercial_invoice = %(commercial_invoice)s")
		params["commercial_invoice"] = commercial_invoice
	return clauses, params


def count_query(from_clause: str, where: str) -> str:
	"""Build a cheap ``SELECT COUNT(*)`` mirroring a list query's FROM + WHERE.

	``from_clause`` is the table + alias (e.g. ``\\`tabImport Container\\` c``);
	``where`` is the already-joined WHERE body (without the ``WHERE`` keyword).
	Pure string assembly so the Frappe layer reuses the exact filter params.
	"""
	return f"SELECT COUNT(*) AS total FROM {from_clause} WHERE {where}"


def is_expiring_soon(expiry, today, window_days: int = 14) -> bool:
	"""True when *expiry* is set and falls on/before ``today + window_days``.

	Used to highlight veterinary certificates about to lapse. Already-expired
	dates (negative ``days_left``) also count as needing attention.
	"""
	dl = days_left(expiry, today)
	return dl is not None and dl <= window_days


# ---------------------------------------------------------------------------
# WP7 — Container cost ledger + landed-cost bills (vendor traceability)
# ---------------------------------------------------------------------------

#: The v46 vendor-traceability Link columns on Purchase Invoice, in the order the
#: category is derived from them (truck → transport, expense → expense).
PI_REF_COLUMNS: tuple[str, ...] = (
	"custom_commercial_invoice",
	"custom_import_container",
	"custom_import_truck",
	"custom_import_expense",
)

#: Derived bill categories (a PI is bucketed by which pipeline raised it).
BILL_CATEGORIES: tuple[str, ...] = ("product", "transport", "expense", "freight")

#: Landed-cost bill money columns masked for users lacking cost visibility (K3).
LANDED_BILL_MASK_FIELDS: tuple[str, ...] = ("grand_total", "outstanding_amount")

#: Container-cost-ledger summary money keys — all masked as one block (K3).
LEDGER_SUMMARY_MASK_FIELDS: tuple[str, ...] = (
	"product_cost",
	"landed_total",
	"grand_total",
	"billed_total",
	"paid",
	"outstanding",
	"per_kg",
)


def today_date():
	from datetime import date

	return date.today()


def per_kg(amount: float, total_kg: float) -> float:
	"""Cost per kilogram, zero-guarded (returns 0.0 when *total_kg* <= 0)."""
	tk = float(total_kg or 0)
	if tk <= 0:
		return 0.0
	return round(float(amount or 0) / tk, 4)


def derive_bill_category(*, truck_ref=None, expense_ref=None, item_codes=(), bill_no=None) -> str:
	"""Bucket a Purchase Invoice into product / transport / expense / freight.

	Transport wins first (a truck ref, the Cross-Border Transport item, or the
	``XBORDER-`` bill marker), then expense (an expense ref, the Import Service
	item, or the ``IMPEXP-`` marker), then an explicit ``FREIGHT-`` marker; a bill
	with none of these — the goods invoice against the CI — is ``product``.
	"""
	codes = {c for c in (item_codes or []) if c}
	bill = (bill_no or "").upper()
	if truck_ref or "Cross-Border Transport" in codes or bill.startswith("XBORDER-"):
		return "transport"
	if expense_ref or "Import Service" in codes or bill.startswith("IMPEXP-"):
		return "expense"
	if bill.startswith("FREIGHT-"):
		return "freight"
	return "product"


def container_cost_summary(*, product_cost, cost_lines, bills, advances) -> dict:
	"""Aggregate one container's cost picture (single-currency, no FX conversion).

	Mirrors the existing ``list_import_containers`` precedent of summing cost-line
	``amount`` as-is (the import book is USD-dominant). ``product_cost`` is the
	container goods value; ``landed_total`` adds only cost lines flagged into the
	landed cost; ``grand_total`` adds every cost line. ``paid`` folds the advance
	Payment Entries' ``paid_amount``; ``billed_total`` / ``outstanding`` fold the
	related bills' ``grand_total`` / ``outstanding_amount``. Pure — the frappe
	layer does the ``per_kg`` division so the zero-guard stays in one place.
	"""
	product = round(float(product_cost or 0), 2)
	included = 0.0
	all_lines = 0.0
	for line in cost_lines or []:
		amt = float(line.get("amount") or 0)
		all_lines += amt
		if line.get("include_in_landed_cost"):
			included += amt
	paid = round(sum(float(a.get("paid_amount") or 0) for a in (advances or [])), 2)
	billed = round(sum(float(b.get("grand_total") or 0) for b in (bills or [])), 2)
	outstanding = round(sum(float(b.get("outstanding_amount") or 0) for b in (bills or [])), 2)
	return {
		"product_cost": product,
		"landed_total": round(product + included, 2),
		"grand_total": round(product + all_lines, 2),
		"billed_total": billed,
		"paid": paid,
		"outstanding": outstanding,
	}


def landed_cost_bill_clauses(ref_columns, *, supplier=None, status=None, commercial_invoice=None):
	"""WHERE fragments + params for ``list_landed_cost_bills`` (alias ``pi``).

	*ref_columns* is the subset of ``PI_REF_COLUMNS`` that actually exist on
	Purchase Invoice (guarded via ``has_column`` in the frappe layer). The core
	clause requires at least one of those Link columns to be non-empty — that is
	what makes a PI an "import bill". When no ref column exists the ledger cannot
	run, so ``clauses`` is empty and the caller must short-circuit.
	"""
	clauses: list[str] = []
	params: dict = {}
	cols = [c for c in (ref_columns or []) if c]
	if cols:
		ors = " OR ".join(f"(pi.{c} IS NOT NULL AND pi.{c} != '')" for c in cols)
		clauses.append(f"({ors})")
	if supplier:
		clauses.append("pi.supplier = %(supplier)s")
		params["supplier"] = supplier
	if status:
		clauses.append("pi.status = %(status)s")
		params["status"] = status
	if commercial_invoice:
		clauses.append("pi.custom_commercial_invoice = %(commercial_invoice)s")
		params["commercial_invoice"] = commercial_invoice
	return clauses, params


def is_overdue(due_date, today, outstanding) -> bool:
	"""True when a bill has a past-due date and still carries an outstanding balance."""
	if float(outstanding or 0) <= 0:
		return False
	dl = days_left(due_date, today)
	return dl is not None and dl < 0


def trucks_pending_filter_clauses(commercial_invoice, statuses=TRUCK_RECEIVABLE_STATUSES):
	"""WHERE fragments + params for the ``trucks_pending_receipt`` pool (alias ``t``).

	Selects the trucks of one Commercial Invoice whose status says they have
	physically arrived (ARRIVED / UNLOADING). The "no submitted receipt yet"
	exclusion is applied in the Frappe layer (variable-length NOT IN) so this
	stays a pure, parametrised fragment builder.
	"""
	clauses: list[str] = ["t.commercial_invoice = %(commercial_invoice)s"]
	params: dict = {"commercial_invoice": commercial_invoice}
	placeholders: list[str] = []
	for idx, status in enumerate(statuses):
		key = f"pending_status_{idx}"
		placeholders.append(f"%({key})s")
		params[key] = status
	if placeholders:
		clauses.append(f"t.status IN ({', '.join(placeholders)})")
	return clauses, params


# ===========================================================================
# WP8 — Import Orders (Proforma / Purchase Order) list + form rules
# ===========================================================================
#
# A PI in the MSAERP model is a *native* Purchase Order carrying the v41/v42
# custom fields; there is no separate proforma doctype (plan §3.1, K1). The
# business lifecycle is **never stored** — it is derived here from the native
# ``docstatus`` / ``advance_paid`` / ``per_received`` plus the statuses of the
# Commercial Invoices linked through the ``Commercial Invoice PO Link`` table.

#: The six-state derived Import-Order lifecycle (Django ProformaInvoice.status
#: minus the stored INVOICED bucket, which becomes the Invoiced-% progress bar).
PO_LIFECYCLE_STATUSES: tuple[str, ...] = (
	"DRAFT",
	"CONFIRMED",
	"ADVANCE_PAID",
	"SHIPPING",
	"COMPLETED",
	"CANCELLED",
)

#: The three advance-payment badges (Django FULLY/PARTIALLY/NOT PAID).
PO_PAYMENT_BADGES: tuple[str, ...] = ("NOT_PAID", "PARTIAL", "PAID")

#: Commercial-Invoice logistics statuses that put the PO "in shipping".
_CI_SHIPPING_STATUSES: frozenset[str] = frozenset(
	{"STUFFED", "GATE_IN", "ON_BOARD", "IN_TRANSIT", "DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN"}
)
_CI_DELIVERED_STATUS = "DELIVERED_TO_UZBEKISTAN"

#: Import-Order list rows: cost-sensitive money nulled for non-cost users (K3).
#: ``agreed_total`` stays visible — native ``rate`` is the real GL obligation and
#: is never masked (K3 owner decision); only the declared docs figure, the
#: cash-difference and the advance $ amount are dual-pricing data.
IMPORT_ORDER_LIST_MASK_FIELDS: tuple[str, ...] = (
	"docs_total",
	"cash_difference",
	"payment_amount",
)

#: Import-Order KPI-strip money nulled for non-cost users (agreed stays; K3).
IMPORT_ORDER_KPI_MASK_FIELDS: tuple[str, ...] = ("docs_total", "diff")


def derive_po_lifecycle(*, docstatus, advance_paid=0, per_received=0, ci_statuses=()):
	"""Derive the never-stored Import-Order lifecycle badge (plan §3.1).

	* CANCELLED — ``docstatus == 2``.
	* DRAFT — ``docstatus == 0``.
	* COMPLETED — submitted and ``per_received >= 100`` **or** at least one linked
	  CI and every non-cancelled CI is ``DELIVERED_TO_UZBEKISTAN``.
	* SHIPPING — submitted and any linked CI is in a transit-ish/delivered state
	  (partial delivery still counts as shipping).
	* ADVANCE_PAID — submitted and ``advance_paid > 0``.
	* CONFIRMED — submitted, none of the above.

	Pure and Frappe-free. ``ci_statuses`` is any iterable of CI status strings.
	"""
	ds = int(docstatus or 0)
	if ds == 2:
		return "CANCELLED"
	if ds == 0:
		return "DRAFT"
	active = [s for s in (ci_statuses or []) if s and s != "Cancelled"]
	if float(per_received or 0) >= 100:
		return "COMPLETED"
	if active and all(s == _CI_DELIVERED_STATUS for s in active):
		return "COMPLETED"
	if any(s in _CI_SHIPPING_STATUSES or s == _CI_DELIVERED_STATUS for s in active):
		return "SHIPPING"
	if float(advance_paid or 0) > 0:
		return "ADVANCE_PAID"
	return "CONFIRMED"


def advance_base(prepayment_type, agreed_total, docs_total, cash_difference):
	"""The base the advance percentage applies to (Django prepayment_base).

	``Docs Total`` → the declared docs figure; anything else (incl. the default
	``Agreed Total``) → the real agreed total. ``cash_difference`` is accepted for
	signature symmetry with ``advance_summary`` but is not needed for the base.
	"""
	if (prepayment_type or "").strip() == "Docs Total":
		return float(docs_total or 0)
	return float(agreed_total or 0)


def po_payment_badge(expected, paid):
	"""PAID / PARTIAL / NOT_PAID from the paid advance vs the expected advance.

	A 1-cent tolerance absorbs rounding on the "fully paid" boundary. When no
	advance is expected (``expected <= 0``) a positive payment still reads as
	PARTIAL rather than PAID, so an over-payment never masquerades as complete.
	"""
	e = round(float(expected or 0), 2)
	p = round(float(paid or 0), 2)
	if e > 0 and p + 0.01 >= e:
		return "PAID"
	if p > 0:
		return "PARTIAL"
	return "NOT_PAID"


def advance_summary(
	*,
	prepayment_type,
	advance_percentage,
	agreed_total,
	docs_total,
	cash_difference,
	advance_paid=0,
	paid_bank=None,
	paid_cash=None,
):
	"""Advance picture for one Import Order (Django record-advance semantics).

	The expected advance is ``base x advance_percentage`` where the base is the
	docs total (``Docs Total``) or the agreed total (default). The expected split
	mirrors Django's UI prefill: bank = docs x pct, cash = cash-difference x pct
	(cash is always 0 for a Docs-Total base). When an explicit ``paid_bank`` /
	``paid_cash`` split is supplied (from the linked advance Payment Entries) it
	wins over the native ``advance_paid`` scalar. Returns base/expected/paid/
	remaining, the paid-% and the PAID/PARTIAL/NOT_PAID badge. Pure — no equal-
	split rule is enforced (that was an allocation-level concern; §3.1).
	"""
	pct = float(advance_percentage or 0)
	docs = float(docs_total or 0)
	cash = float(cash_difference or 0)
	base = advance_base(prepayment_type, agreed_total, docs_total, cash_difference)
	expected = round(base * pct / 100.0, 2)
	if (prepayment_type or "").strip() == "Docs Total":
		expected_bank = round(docs * pct / 100.0, 2)
		expected_cash = 0.0
	else:
		expected_bank = round(docs * pct / 100.0, 2)
		expected_cash = round(cash * pct / 100.0, 2)
	if paid_bank is not None or paid_cash is not None:
		pb = round(float(paid_bank or 0), 2)
		pc = round(float(paid_cash or 0), 2)
		paid = round(pb + pc, 2)
	else:
		pb = pc = None
		paid = round(float(advance_paid or 0), 2)
	remaining = round(max(expected - paid, 0.0), 2)
	pct_paid = round(paid / expected * 100.0, 1) if expected > 0 else 0.0
	return {
		"prepayment_type": prepayment_type or None,
		"advance_percentage": pct,
		"base": round(base, 2),
		"expected": expected,
		"expected_bank": expected_bank,
		"expected_cash": expected_cash,
		"paid": paid,
		"paid_bank": pb,
		"paid_cash": pc,
		"remaining": remaining,
		"pct_paid": pct_paid,
		"badge": po_payment_badge(expected, paid),
	}


def invoiced_pct(allocated_kg, total_kg):
	"""Percentage of an order's kg allocated to Commercial Invoices (zero-guarded).

	Returns 0.0 when ``total_kg <= 0`` so an order with no line weight never
	divides by zero. Capped at 100.0 — an over-allocation reads as fully invoiced.
	"""
	tk = float(total_kg or 0)
	if tk <= 0:
		return 0.0
	return round(min(float(allocated_kg or 0) / tk * 100.0, 100.0), 1)


def import_order_filter_clauses(search=None, vendor=None, pi_group=None, has_pi_group_col=True):
	"""WHERE fragments + params for ``list_import_orders`` (alias ``po``).

	The derived-lifecycle ``status`` filter is applied in Python (it has no SQL
	column), so only the search / vendor / PI-group predicates are built here.
	"""
	clauses: list[str] = []
	params: dict = {}
	if search:
		parts = [
			"po.name LIKE %(search)s",
			"po.supplier LIKE %(search)s",
			"po.supplier_name LIKE %(search)s",
		]
		if has_pi_group_col:
			parts.append("po.custom_import_pi_group LIKE %(search)s")
		clauses.append("(" + " OR ".join(parts) + ")")
		params["search"] = f"%{search}%"
	if vendor:
		clauses.append("po.supplier = %(vendor)s")
		params["vendor"] = vendor
	if pi_group and has_pi_group_col:
		clauses.append("po.custom_import_pi_group = %(pi_group)s")
		params["pi_group"] = pi_group
	return clauses, params


def import_order_kpis(rows, *, invoices_total=0, invoices_pending=0, invoices_done=0):
	"""KPI-strip aggregates over a set of already-derived Import-Order rows.

	Money is summed raw (single-currency import book, no FX conversion — the same
	precedent as ``container_cost_summary``); the Frappe layer masks the cost keys
	afterwards. FCL has no source field on PO Item (only ``custom_boxes`` /
	``custom_box_weight_kg`` exist), so it is reported as ``None`` and the SPA
	shows boxes·kg only. Invoice counts are passed in from the distinct-CI roll-up
	(a CI may span several POs, so per-row counts cannot simply be summed).
	"""
	agreed = round(sum(float(r.get("agreed_total") or 0) for r in rows), 2)
	docs = round(sum(float(r.get("docs_total") or 0) for r in rows), 2)
	diff = round(sum(float(r.get("cash_difference") or 0) for r in rows), 2)
	boxes = int(sum(int(r.get("total_boxes") or 0) for r in rows))
	kg = round(sum(float(r.get("total_kg") or 0) for r in rows), 2)
	return {
		"order_count": len(rows),
		"agreed_total": agreed,
		"docs_total": docs,
		"diff": diff,
		"total_boxes": boxes,
		"total_kg": kg,
		"fcl": None,
		"invoices_total": int(invoices_total),
		"invoices_pending": int(invoices_pending),
		"invoices_done": int(invoices_done),
	}


def get_7day_payment_deadline(eta_transit_port) -> str | None:
	"""Return the payment deadline (7 days before eta_transit_port) in ISO format."""
	if not eta_transit_port:
		return None
	from frappe.utils import add_days, getdate

	try:
		dt = getdate(eta_transit_port)
		return str(add_days(dt, -7))
	except Exception:
		return None


# ---------------------------------------------------------------------------
# PI ↔ CI matching — contract (Proforma Invoice) vs shipment (Commercial Invoice)
# ---------------------------------------------------------------------------
#
# Ported 1:1 from the ``~/msa-sandbox`` prototype (``lib/match.js``), which was
# validated against the real MSA book (59 PIs / 353 CIs / 6 223 CI lines) before
# any of this reached Stabler. The prototype settled four things the previous
# implementation got wrong:
#
# 1. **The match key is the category, not the item.** A PI line is often a
#    *compensated bundle* (``CM60/40 = BUFFALO COMPENSATED``, 16 800 boxes in one
#    line) that the CI ships broken into sub-cuts (``41 TOPSIDE``,
#    ``44 SILVER SIDE``, …). Matching on ``item`` therefore matches 19.5% of the
#    lines; matching on ``category`` matches 98.3%.
# 2. **Both sides of the key must be normalised.** The book writes the same
#    product as ``Whole leg`` and ``WHOLE LEG``. Raw-text matching invents 40
#    phantom "not on any PI" lines (144 instead of 104).
# 3. **Prices compare with a half-cent tolerance.** Raw float equality produced
#    273 phantom mismatches (``4.0999999999 != 4.1``) — IEEE-754 residue. Exact
#    4-decimal equality then produced 1 067 more on the live msa book, because a
#    PI is booked at 3 decimals (4.865) and its CI at 2 (4.86). See
#    ``PRICE_TOLERANCE``.
# 4. **One key can legitimately carry several contract prices.** e.g.
#    ``BUFFALO COMPENSATED_3`` is contracted at 4.05 / 4.15 / 4.10. A CI price
#    equal to *any* of them is compliant.
# 5. **A blank category is a hole, not a key.** ``(PI, "")`` matches every other
#    blank-category line on the same PI, so such a line would inherit a foreign
#    price and net out of a foreign balance. It is reported, never matched.
#
# Invariants — nothing is silently corrected:
#
# * ``remaining_boxes`` MAY BE NEGATIVE. ``max(0, …)`` is forbidden here: it hid
#   21 over-shipped keys / 25 959 boxes in the real book. Over-shipment comes
#   back as ``over_shipped=True``.
# * A CI line whose key is on no PI is NOT netted out of the remaining balance;
#   it is flagged ``unattributable`` and reported.
# * Price comparison is set membership, not equality against a single value.
# * Only the *key* is normalised. Raw text is preserved for display.

#: Severity ordering for a line-level difference — ``error`` beats ``warn``
#: beats ``info``. ``error`` means the line cannot enter the remaining-balance
#: math at all; ``warn`` means it can, but a column disagrees with the PI.
DIFF_LEVELS: tuple[str, ...] = ("error", "warn", "info")

#: Source strings for the difference codes. The SPA translates by ``code``; this
#: map is the single source of truth for anything rendering server-side (the
#: proof report, logs). Keep the wording in sync with the five translation CSVs.
DIFF_LABELS: dict[str, str] = {
	"unattributable": "Not on any PI",
	"missing_category": "No category on the line — it can match no PI line",
	"price_docs": "Invoice price differs from the PI docs price",
	"price_agreed": "Agreed price differs from the PI",
	"qty_arithmetic": "Boxes × box weight does not equal the total kg",
	"sub_cut": "Sub-cut — the PI line is a compensated bundle",
}

#: Tolerance (kg) for the ``boxes × box_weight_kg == qty`` check. Below this the
#: gap is rounding in the source book, not a data-entry error.
QTY_ARITHMETIC_TOLERANCE_KG = 0.5

#: Half a cent — the price tolerance. A Proforma books its prices at 3 decimals
#: (4.865) while the Commercial Invoice that ships against it stores 2 (4.86), so
#: exact equality called 816 of 818 agreed-price comparisons on the live msa book
#: a "difference" when the only difference was the stored precision. A genuine
#: pricing error is at least a whole cent; measured on that book there is nothing
#: at all between 0.005 and 0.05, so this threshold separates cleanly.
PRICE_TOLERANCE = 0.005

_WHITESPACE_RE = re.compile(r"\s+")


def norm_key(value) -> str:
	"""Normalise one side of a match key: collapse whitespace, upper-case.

	Cosmetic-looking but mandatory — see invariant 2 in the section header.
	Never use this for display; the raw value is what the user recognises.
	"""
	return _WHITESPACE_RE.sub(" ", str("" if value is None else value)).strip().upper()


def match_key(pi_name, category) -> tuple[str, str]:
	"""The PI ↔ CI match key: ``(normalised PI, normalised category)``.

	``category`` is the product as written on the invoice
	(``наименование по инвойс``) — NOT the item / Article, which is a sub-cut.
	"""
	return (norm_key(pi_name), norm_key(category))


def is_keyed(key) -> bool:
	"""True when both halves of a match key are filled — see invariant 5.

	``(PI, "")`` is not a key. On msa 29 CI lines carry no category, and 27 of
	them "matched" whichever other blank-category line sat on the same PI,
	inheriting its price and netting out of its remaining balance. Such rows are
	kept out of both indexes and reported as ``missing_category`` instead.
	"""
	return bool(key[0]) and bool(key[1])


def _num(value) -> float:
	try:
		out = float(value or 0)
	except (TypeError, ValueError):
		return 0.0
	return out if math.isfinite(out) else 0.0


def _round4(value) -> float:
	return round(_num(value), 4)


def _price_eq(a, b) -> bool:
	"""Two prices agree when they differ by at most ``PRICE_TOLERANCE``.

	Not exact equality: the PI and the CI store the same price at different
	precisions. The outer ``round`` keeps float residue from pushing an exact
	half-cent gap over the threshold.
	"""
	return round(abs(_round4(a) - _round4(b)), 4) <= PRICE_TOLERANCE


def _contract_pi(row) -> str:
	"""PI docname of a Proforma Invoice Item row — ``parent`` *is* the PI."""
	return row.get("pi_name") or row.get("parent") or ""


def _shipped_pi(row) -> str:
	"""PI docname of a Commercial Invoice Item row.

	Two-level link: the PI may sit on the row (``custom_proforma_invoice``) or
	only on the CI header (``header_proforma_invoice``, projected by the SQL
	join); the row wins when both are set. There is deliberately no ``parent``
	fallback here — ``parent`` is the *CI*, and defaulting to it would make every
	unlinked line look attributed to a PI named after its own invoice.
	"""
	for field in ("pi_name", "custom_proforma_invoice", "header_proforma_invoice"):
		value = row.get(field)
		if value:
			return value
	return ""


def contract_index(pi_item_rows) -> dict[tuple[str, str], dict]:
	"""Index Proforma Invoice Item rows by match key.

	Each row is a dict with ``pi_name`` (or ``parent``), ``category``, ``item``,
	``boxes``, ``qty``, ``amount``, ``rate``, ``docs_price``, ``box_weight_kg``.

	Prices accumulate into *sets* — one key may be contracted at several prices
	(invariant 4) and a CI matching any of them is compliant.

	Rows without a category are skipped: they carry no product identity, so
	indexing them would merge unrelated lines under ``(PI, "")``. ``reconcile``
	counts them as ``contract_unkeyed_lines`` so the omission is visible.
	"""
	index: dict[tuple[str, str], dict] = {}
	for row in pi_item_rows:
		pi_name = _contract_pi(row)
		key = match_key(pi_name, row.get("category"))
		if not is_keyed(key):
			continue
		entry = index.get(key)
		if entry is None:
			entry = {
				"key": key,
				"pi_name": pi_name,
				"label": row.get("category") or row.get("item") or "",
				"boxes": 0.0,
				"qty": 0.0,
				"amount": 0.0,
				"agreed_prices": set(),
				"docs_prices": set(),
				"box_weights": set(),
				"items": set(),
				"lines": [],
			}
			index[key] = entry
		entry["boxes"] += _num(row.get("boxes"))
		entry["qty"] += _num(row.get("qty"))
		entry["amount"] += _num(row.get("amount"))
		if row.get("rate") is not None:
			entry["agreed_prices"].add(_round4(row.get("rate")))
		if row.get("docs_price") is not None:
			entry["docs_prices"].add(_round4(row.get("docs_price")))
		if row.get("box_weight_kg"):
			entry["box_weights"].add(_round4(row.get("box_weight_kg")))
		if row.get("item"):
			entry["items"].add(norm_key(row.get("item")))
		entry["lines"].append(row)
	return index


def contract_line_breakdown(entry) -> list[dict]:
	"""Split one ``contract_index`` entry back into its individual PI lines.

	The match key stays ``(PI, category)`` — this is a *presentation* split, not a
	second index. A compensated bundle books thirteen cuts under one category, and
	the picker has to offer those thirteen; the balance the guard enforces is still
	the category total above them.

	Identity is the row's own ``name`` (the Proforma Invoice Item docname), never
	``item``: one PI may book the same code twice at different rates, and merging
	them would make two contract lines share one allocation box.

	No ``max(0, …)`` anywhere and ``entry`` is never mutated — a zero or negative
	``boxes`` in the source book travels through verbatim (invariant 1).
	"""
	out: list[dict] = []
	for idx, ln in enumerate(entry.get("lines") or []):
		out.append(
			{
				# Synthetic fallback only for rows that reached us without a docname
				# (hand-built dicts in tests); still unique inside the bundle.
				"row": str(ln.get("name") or "") or f"{entry['key'][0]}#{idx}",
				# Verbatim — this round-trips into the CI row as a Link value.
				"item": ln.get("item") or "",
				"description": ln.get("description") or "",
				"hs_code": ln.get("hs_code") or "",
				"boxes": _num(ln.get("boxes")),
				"qty": _num(ln.get("qty")),
				# Per line, not per bundle: a mixed bundle may weigh its cuts
				# differently, and the kg the CI books must follow the line.
				"box_weight_kg": _round4(ln.get("box_weight_kg")),
				"agreed_rate": _round4(ln.get("rate")),
				"docs_price": _round4(ln.get("docs_price")),
			}
		)
	return out


def shipped_index(ci_item_rows) -> dict[tuple[str, str], dict]:
	"""Index Commercial Invoice Item rows by the same match key.

	Each row is a dict with the PI (row-level or inherited from the header),
	``category``, ``item``, ``boxes``, ``qty``, ``amount`` and the CI docname in
	``ci_name`` (or ``parent``).

	Rows without a category are skipped for the same reason as on the contract
	side, and would otherwise be subtracted from a balance they have no claim on.
	"""
	index: dict[tuple[str, str], dict] = {}
	for row in ci_item_rows:
		key = match_key(_shipped_pi(row), row.get("category"))
		if not is_keyed(key):
			continue
		entry = index.get(key)
		if entry is None:
			entry = {
				"key": key,
				"boxes": 0.0,
				"qty": 0.0,
				"amount": 0.0,
				"ci_names": set(),
				"items": set(),
				"lines": [],
			}
			index[key] = entry
		entry["boxes"] += _num(row.get("boxes"))
		entry["qty"] += _num(row.get("qty"))
		entry["amount"] += _num(row.get("amount"))
		ci_name = row.get("ci_name") or row.get("parent")
		if ci_name:
			entry["ci_names"].add(ci_name)
		if row.get("item"):
			entry["items"].add(norm_key(row.get("item")))
		entry["lines"].append(row)
	return index


def remaining_for(contract, shipped) -> dict:
	"""Remaining balance for one match key. ``remaining_boxes`` may be negative.

	``max(0, …)`` is deliberately absent — see invariant 1. Both arguments may be
	``None``: no contract + shipment = ``unattributable``; contract + no shipment
	= nothing shipped yet.
	"""
	contract_boxes = _num(contract and contract.get("boxes"))
	shipped_boxes = _num(shipped and shipped.get("boxes"))
	contract_qty = _num(contract and contract.get("qty"))
	shipped_qty = _num(shipped and shipped.get("qty"))
	if contract_boxes > 0:
		pct = min(100.0, shipped_boxes / contract_boxes * 100.0)
	else:
		pct = 100.0 if shipped_boxes > 0 else 0.0
	return {
		"contract_boxes": contract_boxes,
		"shipped_boxes": shipped_boxes,
		"remaining_boxes": contract_boxes - shipped_boxes,
		"contract_qty": contract_qty,
		"shipped_qty": shipped_qty,
		"remaining_qty": contract_qty - shipped_qty,
		"pct": round(pct, 1),
		"over_shipped": shipped_boxes > contract_boxes,
		"over_boxes": shipped_boxes - contract_boxes if shipped_boxes > contract_boxes else 0.0,
		"ci_count": len(shipped["ci_names"]) if shipped else 0,
		"unattributable": contract is None and shipped is not None,
	}


def _allocation_by_key(ci_item_rows) -> dict[tuple[str, str], dict]:
	"""How many boxes / kg a set of CI rows allocates, per match key.

	Same keying and same drop rules as ``shipped_index`` (unkeyed rows carry no
	product identity and are skipped), but it accumulates nothing else — this is
	the "what does this document claim" side, not an index of the book.

	``boxes`` and ``qty`` accumulate INDEPENDENTLY; ``box_weight_kg`` is display
	only and never used to derive one from the other.
	"""
	out: dict[tuple[str, str], dict] = {}
	for row in ci_item_rows or ():
		key = match_key(_shipped_pi(row), row.get("category"))
		if not is_keyed(key):
			continue
		entry = out.setdefault(key, {"boxes": 0.0, "qty": 0.0})
		entry["boxes"] += _num(row.get("boxes"))
		entry["qty"] += _num(row.get("qty"))
	return out


def changed_allocation_keys(before_items, after_items) -> set[tuple[str, str]]:
	"""Match keys whose allocation this save CREATES or INCREASES.

	A key that is untouched, removed or REDUCED is not returned — only a bigger
	claim than the document already had can breach a remaining balance.

	This diff is what keeps the guard off historic data. The msa book carries 21
	keys / 25 959 boxes of real over-shipment; without it, every save that never
	looks at an item row (a status change, a customs-fee recompute) would throw
	on those documents and freeze them forever. It is also what lets an
	over-allocated CI be corrected downwards.

	``before_items`` is ``None``/empty on insert, so every allocating row of a new
	document counts as changed. A row claiming neither boxes nor kg allocates
	nothing and therefore never counts, on insert or otherwise.
	"""
	before = _allocation_by_key(before_items)
	after = _allocation_by_key(after_items)
	changed: set[tuple[str, str]] = set()
	for key, now in after.items():
		was = before.get(key) or {"boxes": 0.0, "qty": 0.0}
		if _round4(now["boxes"]) > _round4(was["boxes"]) or _round4(now["qty"]) > _round4(was["qty"]):
			changed.add(key)
	return changed


def over_allocations(contract_idx, shipped_idx, ci_lines, keys) -> list[dict]:
	"""Keys among ``keys`` where ``ci_lines`` claim more than the contract has left.

	``shipped_idx`` MUST exclude the document being saved, otherwise a CI
	cannibalises its own allocation and every edit of it looks like a breach.

	Invariant 1 holds here too: ``remaining_boxes`` / ``remaining_qty`` are
	reported RAW and may be negative. There is no ``max(0, …)`` — on a key that is
	already over-shipped, a fresh claim breaches by its own size plus the standing
	overage, and the report says so. ``over_boxes`` / ``over_qty`` are overage
	magnitudes and mirror ``remaining_for``'s field of the same name.

	Only the keys passed in are inspected, so a caller can check exactly what this
	save changed. A key with no contract line at all is skipped: there is no
	balance to cap against, and that defect is ``unattributable``, which
	``diff_ci_line`` already reports. ``level`` comes from ``DIFF_LEVELS``.
	"""
	allocation = _allocation_by_key(ci_lines)
	out: list[dict] = []
	for key in sorted(keys):
		if not is_keyed(key):
			continue
		alloc = allocation.get(key)
		contract = contract_idx.get(key)
		if not alloc or contract is None:
			continue
		bal = remaining_for(contract, shipped_idx.get(key))
		over_boxes = _round4(alloc["boxes"] - bal["remaining_boxes"])
		over_qty = _round4(alloc["qty"] - bal["remaining_qty"])
		if over_boxes <= 0 and over_qty <= 0:
			continue
		out.append(
			{
				"key": key,
				"code": "over_allocated",
				"level": "error",
				"pi_name": contract.get("pi_name") or key[0],
				"label": contract.get("label") or key[1],
				"allocated_boxes": _round4(alloc["boxes"]),
				"allocated_qty": _round4(alloc["qty"]),
				"remaining_boxes": bal["remaining_boxes"],
				"remaining_qty": bal["remaining_qty"],
				"over_boxes": over_boxes if over_boxes > 0 else 0.0,
				"over_qty": over_qty if over_qty > 0 else 0.0,
			}
		)
	return out


def diff_ci_line(ci_line, contract) -> list[dict]:
	"""Compare one CI line against its contract key. Empty list = fully compliant.

	``contract`` is the ``contract_index`` entry for the line's key, or ``None``
	when the key is on no PI at all.
	"""
	out: list[dict] = []

	if not contract:
		# Distinguish the two ways a line can be unmatched: the category is on no
		# PI (fix the PI link), or there is no category at all (fix the line).
		# Reporting the second as "not on any PI" sends the operator to the wrong
		# document.
		blank_category = not norm_key(ci_line.get("category"))
		out.append(
			{
				"code": "missing_category" if blank_category else "unattributable",
				"level": "error",
				"field": "category" if blank_category else "proforma_invoice",
				"ci_value": ci_line.get("category") or ci_line.get("item") or "",
				"pi_value": None,
			}
		)
		return out  # nothing to compare against; the rest would be noise

	docs_price = ci_line.get("docs_price")
	if docs_price is not None and contract["docs_prices"]:
		if not any(_price_eq(v, docs_price) for v in contract["docs_prices"]):
			out.append(
				{
					"code": "price_docs",
					"level": "warn",
					"field": "docs_price",
					"ci_value": _round4(docs_price),
					"pi_value": sorted(contract["docs_prices"]),
				}
			)

	rate = ci_line.get("rate")
	if rate is not None and contract["agreed_prices"]:
		if not any(_price_eq(v, rate) for v in contract["agreed_prices"]):
			out.append(
				{
					"code": "price_agreed",
					"level": "warn",
					"field": "rate",
					"ci_value": _round4(rate),
					"pi_value": sorted(contract["agreed_prices"]),
				}
			)

	boxes = _num(ci_line.get("boxes"))
	box_weight = _num(ci_line.get("box_weight_kg"))
	qty = _num(ci_line.get("qty"))
	if boxes and box_weight and qty:
		expected = boxes * box_weight
		if abs(expected - qty) > QTY_ARITHMETIC_TOLERANCE_KG:
			out.append(
				{
					"code": "qty_arithmetic",
					"level": "warn",
					"field": "qty",
					"ci_value": qty,
					"pi_value": round(expected, 3),
				}
			)

	# A CI item that is not one of the PI line's items is a sub-cut of a
	# compensated bundle — expected behaviour, so ``info``, never a failure.
	item = ci_line.get("item")
	if item and contract["items"] and norm_key(item) not in contract["items"]:
		out.append(
			{
				"code": "sub_cut",
				"level": "info",
				"field": "item",
				"ci_value": item,
				"pi_value": sorted(contract["items"]),
			}
		)

	return out


def worst_level(diffs) -> str | None:
	"""Heaviest severity in a diff list: ``error`` > ``warn`` > ``info`` > ``None``."""
	for level in DIFF_LEVELS:
		if any(d.get("level") == level for d in diffs):
			return level
	return None


def reconcile(pi_item_rows, ci_item_rows) -> dict:
	"""Whole-book reconciliation summary over contract + shipment rows.

	Returns the same figures the sandbox prints; the two implementations landing
	on identical numbers is what proves the port.
	"""
	contract = contract_index(pi_item_rows)
	shipped = shipped_index(ci_item_rows)

	contract_boxes = sum(_num(r.get("boxes")) for r in pi_item_rows)
	contract_amount = sum(_num(r.get("amount")) for r in pi_item_rows)

	remaining_boxes = 0.0
	over_keys = 0
	over_boxes = 0.0
	for key, entry in contract.items():
		rem = remaining_for(entry, shipped.get(key))
		if rem["over_shipped"]:
			over_keys += 1
			over_boxes += rem["over_boxes"]
		else:
			remaining_boxes += rem["remaining_boxes"]

	# Lines the indexes had to drop for want of a category. Counted, never hidden.
	contract_unkeyed_lines = 0
	contract_unkeyed_boxes = 0.0
	for row in pi_item_rows:
		if not is_keyed(match_key(_contract_pi(row), row.get("category"))):
			contract_unkeyed_lines += 1
			contract_unkeyed_boxes += _num(row.get("boxes"))

	orphan_lines = 0
	orphan_boxes = 0.0
	orphan_keys: set[tuple[str, str]] = set()
	counts = {
		"missing_category": 0,
		"price_docs": 0,
		"price_agreed": 0,
		"qty_arithmetic": 0,
		"sub_cut": 0,
	}
	matched_lines = 0
	pis_per_ci: dict[str, set[str]] = {}
	for row in ci_item_rows:
		pi_name = _shipped_pi(row)
		key = match_key(pi_name, row.get("category"))
		ci_name = row.get("ci_name") or row.get("parent")
		if ci_name:
			pis_per_ci.setdefault(ci_name, set()).add(norm_key(pi_name))
		entry = contract.get(key) if is_keyed(key) else None
		if entry is None:
			orphan_lines += 1
			orphan_boxes += _num(row.get("boxes"))
			orphan_keys.add(key)
			for diff in diff_ci_line(row, None):
				if diff["code"] in counts:
					counts[diff["code"]] += 1
			continue
		matched_lines += 1
		for diff in diff_ci_line(row, entry):
			if diff["code"] in counts:
				counts[diff["code"]] += 1

	return {
		"contract_lines": len(pi_item_rows),
		"contract_keys": len(contract),
		"contract_boxes": contract_boxes,
		"contract_amount": round(contract_amount, 2),
		"contract_unkeyed_lines": contract_unkeyed_lines,
		"contract_unkeyed_boxes": contract_unkeyed_boxes,
		"ci_count": len(pis_per_ci),
		"ci_lines": len(ci_item_rows),
		"shipped_keys": len(shipped),
		"matched_lines": matched_lines,
		"remaining_boxes": remaining_boxes,
		"over_keys": over_keys,
		"over_boxes": over_boxes,
		"orphan_lines": orphan_lines,
		"orphan_boxes": orphan_boxes,
		"orphan_keys": len(orphan_keys),
		"missing_category": counts["missing_category"],
		"price_docs": counts["price_docs"],
		"price_agreed": counts["price_agreed"],
		"qty_arithmetic": counts["qty_arithmetic"],
		"sub_cut": counts["sub_cut"],
		"multi_pi_cis": sum(1 for pis in pis_per_ci.values() if len(pis) > 1),
	}


# ---------------------------------------------------------------------------
# Transport Expense Allocation & Landed Cost Math
# ---------------------------------------------------------------------------

#: The transport chain categories.
TRANSPORT_CATEGORIES: tuple[str, ...] = (
	"Transport",
	"Border Crossing",
	"Handling",
	"Storage",
	"Insurance",
)


def calculate_ci_transport_costs(
	raw_expenses: list[dict],
	containers: list[dict],
	ci_total_kg: float,
	ci_agreed_total: float,
	currency: str = "USD",
) -> dict:
	"""Calculate transport cost allocation across containers, vendor totals, and landed cost.

	Pure math & classification, completely I/O free.

	:param raw_expenses: list of Import Expense dicts
	:param containers: list of dicts with {"name": str, "total_kg": float}
	:param ci_total_kg: Commercial Invoice total_kg
	:param ci_agreed_total: Commercial Invoice agreed_total
	:param currency: Currency code (default "USD")
	"""
	num_containers = len(containers)
	containers_total_kg = sum(float(c.get("total_kg") or 0.0) for c in containers)
	by_container_map = {str(c.get("name")): 0.0 for c in containers if c.get("name")}

	transport_rows = []
	other_rows = []

	for row in raw_expenses:
		r = dict(row)
		category = (r.get("category") or "").strip()
		is_transport = category in TRANSPORT_CATEGORIES
		r["is_transport"] = is_transport

		if is_transport:
			amt = float(r.get("amount") or 0.0)
			cnt = r.get("container")
			trk = r.get("truck")

			if cnt:
				r["allocation"] = "direct"
				cnt_str = str(cnt)
				if cnt_str in by_container_map:
					by_container_map[cnt_str] += amt
			elif trk:
				r["allocation"] = "truck"
			else:
				if num_containers > 0:
					if containers_total_kg > 0:
						r["allocation"] = "weight"
						for c in containers:
							c_name = str(c.get("name"))
							if c_name in by_container_map:
								c_kg = float(c.get("total_kg") or 0.0)
								by_container_map[c_name] += amt * (c_kg / containers_total_kg)
					else:
						r["allocation"] = "equal"
						for c in containers:
							c_name = str(c.get("name"))
							if c_name in by_container_map:
								by_container_map[c_name] += amt / num_containers
				else:
					r["allocation"] = "invoice"
			transport_rows.append(r)
		else:
			r["allocation"] = "invoice"
			other_rows.append(r)

	other_total = sum(float(r.get("amount") or 0.0) for r in other_rows)
	transport_total = sum(float(r.get("amount") or 0.0) for r in transport_rows)

	paid_total: float | None = 0.0
	for r in transport_rows:
		bp, cp = r.get("bank_payment"), r.get("cash_payment")
		if bp is None or cp is None:
			paid_total = None
			break
		paid_total += float(bp or 0.0) + float(cp or 0.0)

	outstanding_total = None if paid_total is None else transport_total - paid_total

	vendor_groups: dict[str, dict] = {}
	for r in transport_rows:
		supp = (r.get("supplier") or "").strip() or "unspecified"
		supp_name = (r.get("supplier_name") or supp).strip()
		amt = float(r.get("amount") or 0.0)
		inv_ref = (r.get("invoice_reference") or "").strip()

		if supp not in vendor_groups:
			vendor_groups[supp] = {
				"supplier": supp,
				"supplier_name": supp_name,
				"invoices": set(),
				"amount": 0.0,
				"bank": 0.0,
				"cash": 0.0,
				"masked": False,
			}

		group = vendor_groups[supp]
		if inv_ref:
			group["invoices"].add(inv_ref)
		else:
			group["invoices"].add(str(r.get("name")))
		group["amount"] += amt

		bp, cp = r.get("bank_payment"), r.get("cash_payment")
		if bp is None or cp is None:
			group["masked"] = True
		else:
			group["bank"] += float(bp or 0.0)
			group["cash"] += float(cp or 0.0)

	by_vendor = []
	for _supp, g in vendor_groups.items():
		amt = g["amount"]
		if g["masked"]:
			paid = None
			outstanding = None
		else:
			paid = g["bank"] + g["cash"]
			outstanding = amt - paid
		by_vendor.append(
			{
				"supplier": g["supplier"],
				"supplier_name": g["supplier_name"],
				"docs": len(g["invoices"]),
				"amount": round(amt, 2),
				"paid": round(paid, 2) if paid is not None else None,
				"outstanding": round(outstanding, 2) if outstanding is not None else None,
			}
		)

	cargo_kg = float(ci_total_kg or 0.0)
	per_container = transport_total / num_containers if num_containers > 0 else 0.0
	per_kg = transport_total / cargo_kg if cargo_kg > 0 else 0.0
	goods_per_kg = float(ci_agreed_total or 0.0) / cargo_kg if cargo_kg > 0 else 0.0
	landed_per_kg = goods_per_kg + per_kg

	by_container = [{"container": k, "amount": round(v, 2)} for k, v in by_container_map.items()]

	all_rows = transport_rows + other_rows

	return {
		"rows": all_rows,
		"by_vendor": by_vendor,
		"by_container": by_container,
		"other_rows": other_rows,
		"other_total": round(other_total, 2),
		"totals": {
			"transport": round(transport_total, 2),
			"paid": round(paid_total, 2) if paid_total is not None else None,
			"outstanding": round(outstanding_total, 2) if outstanding_total is not None else None,
			"per_container": round(per_container, 2),
			"per_kg": round(per_kg, 4),
			"containers": num_containers,
			"cargo_kg": round(cargo_kg, 2),
			"goods_per_kg": round(goods_per_kg, 4),
			"landed_per_kg": round(landed_per_kg, 4),
		},
		"currency": currency,
	}


def calculate_ci_cost_overview(
	*,
	ci_name: str,
	items_agreed_total: float,
	items_docs_total: float,
	cargo_kg: float,
	containers: list[dict],
	expenses: list[dict],
	bills: list[dict],
	lcv_total: float,
	customs_duties: float,
	duties_estimated: bool = True,
	currency: str = "USD",
	cost_visible: bool = True,
) -> dict:
	"""Single-source math engine for Blocks 5 & 6 of CI Form v4.

	Calculates transport allocation across containers, vendor summaries,
	unbilled expense reconciliation, operational vs accounting cost breakdown,
	and landed cost gap per kg.
	"""
	num_containers = len(containers)
	total_container_kg = sum(float(c.get("total_kg") or 0.0) for c in containers)
	if cargo_kg <= 0 and total_container_kg > 0:
		cargo_kg = total_container_kg

	container_weight_map = {c["name"]: float(c.get("total_kg") or 0.0) for c in containers}
	container_goods_map = {c["name"]: float(c.get("goods_amount") or 0.0) for c in containers}

	container_logistics_map = {c["name"]: 0.0 for c in containers}

	enriched_expenses = []
	for exp in expenses:
		cat = (exp.get("category") or "").strip()
		is_trans = cat in TRANSPORT_CATEGORIES
		amt = float(exp.get("amount") or 0.0)

		cnt = (exp.get("container") or "").strip()
		trk = (exp.get("truck") or "").strip()

		if cnt and cnt in container_weight_map:
			alloc = "direct"
			if is_trans:
				container_logistics_map[cnt] += amt
		elif trk:
			alloc = "truck"
			# Allocate among containers on this truck
			truck_cnts = [c["name"] for c in containers if c.get("truck") == trk]
			if not truck_cnts:
				truck_cnts = list(container_weight_map.keys())
			if truck_cnts and is_trans:
				share = amt / len(truck_cnts)
				for tc in truck_cnts:
					container_logistics_map[tc] += share
		elif num_containers > 0:
			if total_container_kg > 0:
				alloc = "weight"
				if is_trans:
					for c_name, c_kg in container_weight_map.items():
						container_logistics_map[c_name] += amt * (c_kg / total_container_kg)
			else:
				alloc = "equal"
				if is_trans:
					share = amt / num_containers
					for c_name in container_weight_map:
						container_logistics_map[c_name] += share
		else:
			alloc = "invoice"

		item = dict(exp)
		item["is_transport"] = is_trans
		item["allocation"] = alloc
		item["amount"] = round(amt, 2)
		item["bank_payment"] = (
			round(float(exp["bank_payment"]), 2) if exp.get("bank_payment") is not None else None
		)
		item["cash_payment"] = (
			round(float(exp["cash_payment"]), 2) if exp.get("cash_payment") is not None else None
		)
		enriched_expenses.append(item)

	transport_expenses = [e for e in enriched_expenses if e["is_transport"]]
	other_expenses = [e for e in enriched_expenses if not e["is_transport"]]
	unbilled_expenses = [e for e in enriched_expenses if not e.get("purchase_invoice")]

	vendor_groups: dict[str, dict] = {}
	for e in transport_expenses:
		supp = (e.get("supplier") or "").strip() or "unspecified"
		supp_name = (e.get("supplier_name") or supp).strip()
		amt = e["amount"]
		inv_ref = (e.get("invoice_reference") or "").strip()

		if supp not in vendor_groups:
			vendor_groups[supp] = {
				"supplier": supp,
				"supplier_name": supp_name,
				"invoices": set(),
				"amount": 0.0,
				"bank": 0.0,
				"cash": 0.0,
				"masked": False,
			}

		group = vendor_groups[supp]
		if inv_ref:
			group["invoices"].add(inv_ref)
		else:
			group["invoices"].add(str(e.get("name")))
		group["amount"] += amt

		bp, cp = e.get("bank_payment"), e.get("cash_payment")
		if bp is None or cp is None:
			group["masked"] = True
		else:
			group["bank"] += bp
			group["cash"] += cp

	by_vendor = []
	for _supp, g in vendor_groups.items():
		amt = g["amount"]
		if g["masked"]:
			paid = None
			outstanding = None
		else:
			paid = g["bank"] + g["cash"]
			outstanding = amt - paid
		by_vendor.append(
			{
				"supplier": g["supplier"],
				"supplier_name": g["supplier_name"],
				"docs": len(g["invoices"]),
				"amount": round(amt, 2),
				"paid": round(paid, 2) if paid is not None else None,
				"outstanding": round(outstanding, 2) if outstanding is not None else None,
			}
		)

	by_container = []
	for c in containers:
		c_name = c["name"]
		c_kg = float(c.get("total_kg") or 0.0)
		c_goods = container_goods_map.get(c_name, 0.0)
		c_log = container_logistics_map.get(c_name, 0.0)
		c_per_kg = per_kg(c_log, c_kg)
		c_landed_per_kg = per_kg(c_goods + c_log, c_kg)
		by_container.append(
			{
				"container": c_name,
				"logistics_amount": round(c_log, 2),
				"per_kg": c_per_kg,
				"landed_per_kg": c_landed_per_kg,
			}
		)

	op_goods = round(float(items_agreed_total or 0.0), 2)
	op_trans = round(sum(e["amount"] for e in transport_expenses), 2)
	op_other = round(sum(e["amount"] for e in other_expenses), 2)
	op_duties = round(float(customs_duties or 0.0), 2)
	op_total = round(op_goods + op_trans + op_other + op_duties, 2)
	op_per_kg = per_kg(op_total, cargo_kg)

	operational = {
		"goods": op_goods,
		"transport": op_trans,
		"other": op_other,
		"duties": op_duties,
		"total": op_total,
		"per_kg": op_per_kg,
		"duties_estimated": duties_estimated,
	}

	acc_goods = round(
		sum(float(b.get("grand_total") or 0.0) for b in bills if b.get("category") == "product"), 2
	)
	acc_lcv = round(float(lcv_total or 0.0), 2)
	acc_total = round(acc_goods + acc_lcv, 2)
	acc_per_kg = per_kg(acc_total, cargo_kg)

	accounting = {
		"billed_goods": acc_goods,
		"lcv_total": acc_lcv,
		"total": acc_total,
		"per_kg": acc_per_kg,
	}

	gap_amount = round(op_total - acc_total, 2)
	gap = {
		"amount": gap_amount,
		"per_kg": per_kg(gap_amount, cargo_kg),
	}

	bills_map = {str(b.get("name")): b for b in bills if b.get("name")}
	linked_pi_names = {
		str(e.get("purchase_invoice"))
		for e in transport_expenses
		if e.get("purchase_invoice") and str(e.get("purchase_invoice")) in bills_map
	}
	unlinked_non_product_pi_names = {
		str(b.get("name"))
		for b in bills
		if b.get("name") and str(b.get("name")) not in linked_pi_names and b.get("category") != "product"
	}
	billed_pi_names = linked_pi_names.union(unlinked_non_product_pi_names)
	billed_total = round(sum(float(bills_map[name].get("grand_total") or 0.0) for name in billed_pi_names), 2)

	unbilled_transport_expenses = [e for e in transport_expenses if not e.get("purchase_invoice")]
	unbilled_total = round(sum(float(e.get("amount") or 0.0) for e in unbilled_transport_expenses), 2)

	any_masked = any(
		e.get("bank_payment") is None or e.get("cash_payment") is None for e in transport_expenses
	)
	paid_total = (
		round(
			sum((e.get("bank_payment") or 0.0) + (e.get("cash_payment") or 0.0) for e in transport_expenses),
			2,
		)
		if not any_masked
		else None
	)
	outstanding_total = round(op_trans - paid_total, 2) if paid_total is not None else None

	totals = {
		"transport": op_trans,
		"billed": billed_total,
		"unbilled": unbilled_total,
		"paid": paid_total,
		"outstanding": outstanding_total,
		"containers": num_containers,
		"cargo_kg": round(cargo_kg, 2),
	}

	recon_diff = round(op_trans - (billed_total + unbilled_total), 2)
	if abs(recon_diff) > 0.01:
		totals["reconciliation_diff"] = recon_diff

	if not cost_visible:
		for e in enriched_expenses:
			e["amount"] = None
			e["bank_payment"] = None
			e["cash_payment"] = None
		for b in bills:
			b["grand_total"] = None
			b["outstanding_amount"] = None
		for v in by_vendor:
			v["amount"] = None
			v["paid"] = None
			v["outstanding"] = None
		operational = {k: (v if isinstance(v, bool) else None) for k, v in operational.items()}
		accounting = {k: None for k in accounting}
		gap = {k: None for k in gap}
		totals = {k: (v if k in ("containers", "cargo_kg") else None) for k, v in totals.items()}

	return {
		"expenses": enriched_expenses,
		"bills": bills,
		"unbilled": unbilled_expenses,
		"by_vendor": by_vendor,
		"by_container": by_container,
		"operational": operational,
		"accounting": accounting,
		"gap": gap,
		"totals": totals,
		"currency": currency,
	}
