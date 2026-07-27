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
"""

from __future__ import annotations

import datetime

# ---------------------------------------------------------------------------
# Cost masking — the named field sets stripped for users lacking cost visibility
# ---------------------------------------------------------------------------

#: Commercial Invoice header fields that carry docs/cash-difference pricing.
CI_MASK_FIELDS: tuple[str, ...] = ("docs_total", "cash_difference")

#: Commercial Invoice list-endpoint derived cost columns.
CI_LIST_MASK_FIELDS: tuple[str, ...] = ("docs_total", "cash_difference")

#: Import Container header cost fields (all permlevel 1 in the doctype).
CONTAINER_MASK_FIELDS: tuple[str, ...] = (
	"total_amount",
	"allocated_deposit_amount",
	"balance_due_amount",
	"payment_70_amount",
)

#: Import Container list-endpoint derived cost column.
CONTAINER_LIST_MASK_FIELDS: tuple[str, ...] = ("total_amount", "cost_lines_total")

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


def ci_filter_clauses(search=None, status=None, supplier=None):
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
	except TypeError, ValueError:
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
		except TypeError, ValueError:
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


def per_kg(total, total_kg) -> float:
	"""Cost per kilogram, zero-guarded (returns 0.0 when *total_kg* <= 0)."""
	tk = float(total_kg or 0)
	if tk <= 0:
		return 0.0
	return round(float(total or 0) / tk, 4)


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
