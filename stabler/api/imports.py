"""Imports module — Commercial Invoices, Containers, Trucks, customs fee.

The SPA surface for the WP1-4 imports pipeline. Every endpoint:

1. Requires a ``company`` arg and gates on it — ``_assert_imports_access``
   rejects a foreign company (tenant isolation), a company with the imports
   module disabled, and users lacking an imports role (mirrors
   ``organization._MODULE_ROLES["imports"]``); admins bypass.
2. Applies **cost masking** (K3, migration plan §2) — docs/cash-difference,
   landed-cost and transport figures are stripped for users who lack cost
   visibility (Imports Manager / Director / System Manager, or a role listed in
   Stabler Settings ``cost_visible_roles``). The masked field sets and the
   pure list/window helpers live in ``stabler.api._imports_rules``.

Financial documents (advance PEs, transport PIs, LCVs, Purchase Receipts) are
created by the ``imports_module`` hooks, never here — this layer is read/CRUD
over the operational doctypes plus the status-pipeline transition surface.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, getdate, today

from stabler.api import (
	_advance_aging,
	_ci_to_pinv,
	_customs_estimate,
	_fx_reval,
	_imports_delete,
	_kts_amendment,
	_proforma,
)
from stabler.api import _imports_rules as rules
from stabler.api._accounts import _cbu_rate_on_or_before
from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.organization import _ADMIN_ROLES, _MODULE_ROLES
from stabler.api.permissions import cost_visible_for
from stabler.stabler.doctype.stabler_settings.stabler_settings import (
	imports_transport_supplier_groups_for,
	module_map_for,
)
from stabler.stabler.imports_module import packing_service

_IMPORTS_ROLES = tuple(_MODULE_ROLES["imports"])


# ---------------------------------------------------------------------------
# Access + cost-visibility gates
# ---------------------------------------------------------------------------


def _assert_imports_access(company: str) -> None:
	"""Gate an imports endpoint: company valid + enabled + user has a role."""
	_require_company(company)
	# Tenant isolation: reject a company the user is not allowed to touch.
	from stabler.api.approvals import _assert_company_scope

	_assert_company_scope(company)
	if not module_map_for(company).get("imports"):
		frappe.throw(
			_("The imports module is not enabled for this company."),
			frappe.PermissionError,
		)
	roles = set(frappe.get_roles())
	if roles.intersection(_ADMIN_ROLES):
		return
	if not roles.intersection(_IMPORTS_ROLES):
		frappe.throw(_("You are not permitted to access imports."), frappe.PermissionError)


_INVENTORY_ROLES = tuple(_MODULE_ROLES["inventory"])


def _assert_inventory_access(company: str) -> None:
	"""Gate an inventory endpoint: company valid + inventory enabled + user role.

	Vendor categories are a purchasing/inventory template (items + boxes per
	container), NOT import-specific — so they live behind the inventory module,
	available on every inventory tenant, not only the MSA imports tenant.
	"""
	_require_company(company)
	from stabler.api.approvals import _assert_company_scope

	_assert_company_scope(company)
	if not module_map_for(company).get("inventory"):
		frappe.throw(
			_("The inventory module is not enabled for this company."),
			frappe.PermissionError,
		)
	roles = set(frappe.get_roles())
	if roles.intersection(_ADMIN_ROLES):
		return
	if not roles.intersection(_INVENTORY_ROLES):
		frappe.throw(_("You are not permitted to access inventory."), frappe.PermissionError)


def _assert_vendor_category_read(company: str) -> None:
	"""Read gate for vendor categories: allow EITHER inventory or imports access.

	The management page is under Inventory, but the imports PI 'fill from
	category' flow also reads categories — an MSA importer may hold an imports
	role without a stock role, so accept either.
	"""
	try:
		_assert_inventory_access(company)
	except frappe.PermissionError:
		_assert_imports_access(company)


def _cost_visible() -> bool:
	"""True when the session user may see landed-cost / dual-pricing figures.

	Delegates to ``stabler.api.permissions.cost_visible_for`` — the single source
	of truth shared with the SPA boot payload so the frontend flag and this gate
	never diverge (WP6b).
	"""
	return cost_visible_for()


def _assert_cost_visible() -> None:
	"""Reject a write of cost-sensitive data by a user lacking cost visibility."""
	if not _cost_visible():
		frappe.throw(
			_("You are not permitted to edit landed-cost figures."),
			frappe.PermissionError,
		)


def _count(sql: str, params: dict) -> int:
	"""Run a COUNT(*) query (built by ``rules.count_query``) and return the total.

	The list queries pass their full param dict (incl. the unused ``limit_*``
	keys); extra named params are harmless to ``frappe.db.sql``.
	"""
	row = frappe.db.sql(sql, params, as_dict=True)
	return cint(row[0]["total"]) if row else 0


def _company_of(doctype: str, name: str) -> str:
	company = frappe.db.get_value(doctype, name, "company")
	if not company:
		frappe.throw(_("Unknown {0}: {1}").format(_(doctype), name))
	return company


# ---------------------------------------------------------------------------
# Home dashboard
# ---------------------------------------------------------------------------


@frappe.whitelist()
def imports_home(company: str):
	"""KPI payload for the imports dashboard."""
	_assert_imports_access(company)
	today_d = today()

	ci_rows = frappe.db.sql(
		"SELECT status, COUNT(*) AS count FROM `tabCommercial Invoice` "
		"WHERE company = %(company)s GROUP BY status",
		{"company": company},
		as_dict=True,
	)
	ci_by_status = rules.status_counts(ci_rows)

	container_rows = frappe.db.sql(
		"SELECT status, COUNT(*) AS count FROM `tabImport Container` "
		"WHERE company = %(company)s GROUP BY status",
		{"company": company},
		as_dict=True,
	)
	containers_by_status = rules.status_counts(container_rows)

	trucks_in_transit = frappe.db.count(
		"Import Truck",
		{"company": company, "status": ["in", list(rules.TRUCK_IN_TRANSIT_STATUSES)]},
	)

	grns_open = frappe.db.count("GRN Checklist", {"company": company, "docstatus": 0})
	grns_variance = frappe.db.count(
		"GRN Checklist",
		{"company": company, "variance_category": ["in", ["CRITICAL", "MAJOR"]]},
	)

	# Import orders = POs carrying a custom_advance_percentage (guard the column).
	import_orders_count = 0
	advance_paid_total = 0.0
	if frappe.db.has_column("Purchase Order", "custom_advance_percentage"):
		row = frappe.db.sql(
			"""
            SELECT COUNT(*) AS c, COALESCE(SUM(advance_paid), 0) AS adv
            FROM `tabPurchase Order`
            WHERE company = %(company)s AND docstatus < 2
              AND custom_advance_percentage IS NOT NULL
              AND custom_advance_percentage > 0
            """,
			{"company": company},
			as_dict=True,
		)
		if row:
			import_orders_count = cint(row[0]["c"])
			advance_paid_total = flt(row[0]["adv"])

	# Payments due: CIs whose Iran-transit ETA falls within the next 7 days and
	# are not yet delivered/cancelled (70% balance due 7 days before arrival).
	upper = rules.eta_upper_bound(today_d, 7)
	due_rows = frappe.db.sql(
		"""
        SELECT ci.name, ci.ci_number, ci.supplier, s.supplier_name,
               ci.eta_transit_port, ci.status
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
        WHERE ci.company = %(company)s
          AND ci.eta_transit_port IS NOT NULL
          AND ci.eta_transit_port <= %(upper)s
          AND ci.status NOT IN ('DELIVERED_TO_UZBEKISTAN', 'Cancelled')
        ORDER BY ci.eta_transit_port ASC
        LIMIT 25
        """,
		{"company": company, "upper": upper},
		as_dict=True,
	)
	payments_due = [
		{
			"name": r["name"],
			"ci_number": r["ci_number"],
			"supplier": r["supplier"],
			"supplier_name": r["supplier_name"] or r["supplier"],
			"eta_transit_port": str(r["eta_transit_port"]) if r["eta_transit_port"] else None,
			"status": r["status"],
			"days_left": rules.days_left(r["eta_transit_port"], today_d),
		}
		for r in due_rows
	]

	pending_vet_certs = frappe.db.count("Vet Certificate", {"company": company, "status": "Pending"})
	gtds_pending = frappe.db.count(
		"Customs Declaration",
		{"company": company, "status": ["!=", "Approved"]},
	)

	# Pending landed-cost bills: import PIs (any v46 ref) with an outstanding
	# balance. Outstanding is cost-sensitive → masked for non-cost users (K3).
	pending_bills_count = 0
	pending_bills_outstanding = 0.0
	ref_cols = _existing_pi_ref_columns()
	if ref_cols:
		ors = " OR ".join(f"(pi.{c} IS NOT NULL AND pi.{c} != '')" for c in ref_cols)
		bill_row = frappe.db.sql(
			f"""
            SELECT COUNT(*) AS c, COALESCE(SUM(pi.outstanding_amount), 0) AS o
            FROM `tabPurchase Invoice` pi
            WHERE pi.company = %(company)s AND pi.docstatus < 2
              AND pi.outstanding_amount > 0 AND ({ors})
            """,
			{"company": company},
			as_dict=True,
		)
		if bill_row:
			pending_bills_count = cint(bill_row[0]["c"])
			pending_bills_outstanding = flt(bill_row[0]["o"])
	if not _cost_visible():
		pending_bills_outstanding = None

	return {
		"company": company,
		"ci_by_status": ci_by_status,
		"containers_by_status": containers_by_status,
		"open_ci_count": sum(
			v for k, v in ci_by_status.items() if k not in ("DELIVERED_TO_UZBEKISTAN", "Cancelled")
		),
		"trucks_in_transit": trucks_in_transit,
		"grns_open": grns_open,
		"grns_variance": grns_variance,
		"import_orders_count": import_orders_count,
		"advance_paid_total": advance_paid_total,
		"payments_due": payments_due,
		"payments_due_count": len(payments_due),
		"pending_vet_certs": pending_vet_certs,
		"gtds_pending": gtds_pending,
		"pending_bills_count": pending_bills_count,
		"pending_bills_outstanding": pending_bills_outstanding,
	}


# ---------------------------------------------------------------------------
# Commercial Invoices
# ---------------------------------------------------------------------------


#: Columns the CI list may be ordered by. The key is what the SPA sends; the
#: value is spliced into ORDER BY, so this whitelist is the injection guard —
#: never interpolate a caller-supplied string here.
_CI_SORT_COLUMNS = {
	"ci_date": "ci.ci_date",
	"ci_number": "ci.ci_number",
	"supplier": "s.supplier_name",
	"eta": "ci.eta_transit_port",
	"total_boxes": "ci.total_boxes",
	"total_kg": "ci.total_kg",
	"agreed_total": "ci.agreed_total",
	"cash_difference": "ci.cash_difference",
	"container_count": "container_count",
	"status": "ci.status",
}


@frappe.whitelist()
def list_commercial_invoices(
	company: str,
	search: str | None = None,
	status: str | None = None,
	supplier: str | None = None,
	group: str | None = None,
	pi_match: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
	sort_by: str | None = None,
	sort_dir: str | None = None,
):
	"""Commercial Invoice list rows (docs/cash masked for non-cost users).

	Sorting is server-side on purpose: the list is paginated, so sorting only
	the rows already on screen would silently reorder a slice and read as the
	full ordering.
	"""
	_assert_imports_access(company)
	# The proforma link is a custom field, so it may be absent on a site that
	# has not carried the imports work — fall back to NULL rather than failing
	# the whole list. Resolved up here because the filter clauses need it too.
	has_pi_link = frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice")
	clauses, params = rules.ci_filter_clauses(search, status, supplier, group, has_pi_link, pi_match)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["ci.company = %(company)s", *clauses])

	order_col = _CI_SORT_COLUMNS.get(sort_by or "", "ci.ci_date")
	order_dir = "ASC" if str(sort_dir or "").lower() == "asc" else "DESC"
	order_by = f"{order_col} {order_dir}, ci.name DESC"

	eff_group = rules.ci_effective_group_expr(has_pi_link)
	pi_select = (
		"""ci.custom_proforma_invoice AS proforma_invoice,
          COALESCE(pi.supplier_pi_ref, ci.custom_proforma_invoice) AS proforma_ref,"""
		if has_pi_link
		else "NULL AS proforma_invoice, NULL AS proforma_ref,"
	)
	pi_join = (
		"LEFT JOIN `tabProforma Invoice` pi ON pi.name = ci.custom_proforma_invoice" if has_pi_link else ""
	)

	rows = frappe.db.sql(
		f"""
        SELECT
          ci.name, ci.ci_number, ci.supplier, s.supplier_name, ci.ci_date,
          ci.status, ci.incoterm, ci.eta_transit_port,
          COALESCE(NULLIF(ci.total_kg, 0), (SELECT SUM(qty) FROM `tabCommercial Invoice Item` ii WHERE ii.parent = ci.name), 0) AS total_kg,
          COALESCE(NULLIF(ci.total_boxes, 0), (SELECT SUM(boxes) FROM `tabCommercial Invoice Item` ii WHERE ii.parent = ci.name), 0) AS total_boxes,
          COALESCE(NULLIF(ci.agreed_total, 0), (SELECT SUM(amount) FROM `tabCommercial Invoice Item` ii WHERE ii.parent = ci.name), 0) AS agreed_total,
          COALESCE(NULLIF(ci.docs_total, 0), (SELECT SUM(docs_amount) FROM `tabCommercial Invoice Item` ii WHERE ii.parent = ci.name), 0) AS docs_total,
          COALESCE(
            NULLIF(ci.cash_difference, 0),
            (SELECT (SUM(amount) - SUM(docs_amount)) FROM `tabCommercial Invoice Item` ii WHERE ii.parent = ci.name),
            0
          ) AS cash_difference,
          ci.currency,
          ci.import_pi_group,
          {eff_group} AS effective_pi_group,
          pig.code AS pi_group_code,
          pig.title AS pi_group_title,
          {pi_select}
          (SELECT COUNT(*) FROM `tabImport Container` c
             WHERE c.commercial_invoice = ci.name) AS container_count,
          (SELECT COUNT(*) FROM `tabImport Truck` tr
             WHERE tr.commercial_invoice = ci.name) AS truck_count,
          EXISTS(SELECT 1 FROM `tabGRN Checklist` g
             WHERE g.commercial_invoice = ci.name) AS has_grn
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
        LEFT JOIN `tabImport PI Group` pig ON pig.name = {eff_group}
        {pi_join}
        WHERE {where}
        ORDER BY {order_by}
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		r["eta_transit_port"] = str(r["eta_transit_port"]) if r["eta_transit_port"] else None
		r["ci_date"] = str(r["ci_date"]) if r["ci_date"] else None
		r["has_grn"] = bool(r["has_grn"])
	rules.mask_named(rows, rules.CI_LIST_MASK_FIELDS, _cost_visible())
	total = _count(rules.count_query("`tabCommercial Invoice` ci", where), params)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def get_commercial_invoice(name: str):
	"""Full Commercial Invoice payload: header, items, PO links, linked docs."""
	if not name or not frappe.db.exists("Commercial Invoice", name):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(name))
	_assert_imports_access(_company_of("Commercial Invoice", name))
	_assert_can_read("Commercial Invoice", name)
	doc = frappe.get_doc("Commercial Invoice", name)
	grn_fields = ["name", "docstatus", "receipt_status"]
	if frappe.db.has_column("GRN Checklist", "expected_snapshot_locked"):
		grn_fields.append("expected_snapshot_locked")
	grn_rows = frappe.get_list(
		"GRN Checklist",
		filters={"commercial_invoice": name, "company": doc.company},
		fields=grn_fields,
		limit=1,
	)

	payload = {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"import_pi_group": doc.import_pi_group,
		"custom_proforma_invoice": doc.get("custom_proforma_invoice"),
		"supplier": doc.supplier,
		"supplier_name": frappe.db.get_value("Supplier", doc.supplier, "supplier_name")
		if doc.supplier
		else None,
		"ci_number": doc.ci_number,
		"ci_date": str(doc.ci_date) if doc.ci_date else None,
		"currency": doc.currency,
		"status": doc.status,
		"incoterm": doc.incoterm,
		"incoterm_location": doc.incoterm_location,
		"vessel": doc.vessel,
		"voyage": doc.voyage,
		"bl_number": doc.bl_number,
		"port_of_loading": doc.port_of_loading,
		"port_of_discharge": doc.port_of_discharge,
		"eta_transit_port": str(doc.eta_transit_port) if doc.eta_transit_port else None,
		"etd": str(doc.etd) if doc.etd else None,
		"eta": str(doc.eta) if doc.eta else None,
		"atd": str(doc.atd) if doc.atd else None,
		"ata": str(doc.ata) if doc.ata else None,
		"total_boxes": cint(doc.total_boxes),
		"total_kg": flt(doc.total_kg),
		"agreed_total": flt(doc.agreed_total),
		"docs_total": flt(doc.docs_total),
		"cash_difference": flt(doc.cash_difference),
		"customs_fee": flt(doc.customs_fee),
		"customs_fee_override": flt(doc.customs_fee_override),
		"customs_fee_off_hours": cint(doc.customs_fee_off_hours),
		"customs_fee_brv_used": flt(doc.customs_fee_brv_used),
		"customs_fee_multiplier": flt(doc.customs_fee_multiplier),
		"allowed_transitions": _ci_next_statuses(doc.status),
		"items": [
			{
				"name": it.name,
				# The row's own link, never the header's: the form sends these back
				# verbatim, so coalescing here would pin every line of an old CI to
				# whatever the header names the next time it is saved.
				"custom_proforma_invoice": it.get("custom_proforma_invoice"),
				"category": it.category,
				"item": it.item,
				"description": it.description,
				"hs_code": it.hs_code,
				"boxes": cint(it.boxes),
				"box_weight_kg": flt(it.box_weight_kg),
				"qty": flt(it.qty),
				"uom": it.uom,
				"rate": flt(it.rate),
				"docs_price": flt(it.docs_price),
				"amount": flt(it.amount),
				"docs_amount": flt(it.docs_amount),
			}
			for it in (doc.items or [])
		],
		"po_links": frappe.get_all(
			"Commercial Invoice PO Link",
			filters={"commercial_invoice": name},
			fields=[
				"name",
				"purchase_order",
				"purchase_order_item",
				"item",
				"allocated_qty",
				"allocated_amount",
			],
			order_by="creation asc",
		),
		"containers": frappe.get_all(
			"Import Container",
			filters={"commercial_invoice": name},
			fields=["name", "container_number", "status", "total_kg", "total_boxes"],
			order_by="creation asc",
		),
		"trucks": frappe.get_all(
			"Import Truck",
			filters={"commercial_invoice": name},
			fields=[
				"name",
				"truck_number",
				"driver_name",
				"driver_phone",
				"trucking_company",
				"status",
				"total_kg",
				"total_boxes",
				"transport_cost",
				"transport_currency",
			],
			order_by="creation asc",
		),
		"customs_declarations": frappe.get_all(
			"Customs Declaration",
			filters={"commercial_invoice": name},
			fields=["name", "gtd_number", "status", "cleared_date", "total_duties"],
			order_by="creation asc",
		),
		"vet_certificates": frappe.get_all(
			"Vet Certificate",
			filters={"commercial_invoice": name},
			fields=["name", "certificate_number", "status", "expiry_date"],
			order_by="creation asc",
		),
		"packing_summary": _safe_packing_summary(name, doc.company),
		"grn": grn_rows[0] if grn_rows else None,
		"customs_fee_breakdown": _safe_customs_breakdown(name),
		"pi_tracking": get_pi_tracking_for_ci(doc),
		"ci_advance_share": _ci_advance_share(doc) if _cost_visible() else None,
		"transport_invoices": _get_ci_transport_invoices(doc) if _cost_visible() else None,
	}
	rules.mask_named(payload, rules.CI_MASK_FIELDS, _cost_visible())
	return payload


def _ci_next_statuses(status: str) -> list[str]:
	from stabler.stabler.doctype.commercial_invoice.commercial_invoice import (
		_ALLOWED_TRANSITIONS,
	)

	return sorted(_ALLOWED_TRANSITIONS.get(status, set()))


def _safe_customs_breakdown(name: str):
	"""Best-effort customs-fee breakdown; None when BRV/tier config is missing."""
	try:
		return compute_customs_fee(name)
	except Exception:
		return None


def _safe_packing_summary(name: str, company: str):
	"""Best-effort container-packing summary for the CI detail payload.

	summary_for_ci() deliberately throws when the caller cannot see every
	container on the CI (partial permissions) or when the container scope
	shifts mid-read. That guard is correct for the write paths that freeze the
	GRN snapshot, but on a read-only detail page it would take down the entire
	CI screen. Degrade to an explicit "unavailable" marker instead so the rest
	of the payload still renders — same contract as _safe_customs_breakdown.
	"""
	try:
		return packing_service.summary_for_ci(name, company)
	except Exception:
		frappe.log_error(
			title="CI packing summary unavailable",
			message=frappe.get_traceback(),
		)
		# Keep the full key contract — the SPA reads .reconciliation.length and
		# .containers_with_items unguarded.
		return {
			"status": "Unavailable",
			"container_count": 0,
			"containers_with_items": 0,
			"expected_items": [],
			"reconciliation": [],
		}


_CI_HEADER_FIELDS = (
	"import_pi_group",
	"custom_proforma_invoice",
	"ci_number",
	"ci_date",
	"currency",
	"incoterm",
	"incoterm_location",
	"vessel",
	"voyage",
	"bl_number",
	"port_of_loading",
	"port_of_discharge",
	"eta_transit_port",
	"etd",
	"eta",
	"atd",
	"ata",
	"customs_fee_override",
	"customs_fee_off_hours",
)
_CI_DATE_FIELDS = ("ci_date", "eta_transit_port", "etd", "eta", "atd", "ata")


def _clean_ci_items(items):
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw(_("Invalid items payload."))
	if not isinstance(items, list) or not items:
		frappe.throw(_("At least one item is required."))
	cleaned = []
	for idx, row in enumerate(items, start=1):
		item = (row or {}).get("item")
		if not item:
			frappe.throw(_("Row {0}: item is required.").format(idx))
		if not frappe.db.exists("Item", item):
			frappe.throw(_("Row {0}: unknown item '{1}'.").format(idx, item))
		qty = flt(row.get("qty"))
		rate = flt(row.get("rate"))
		docs_price = flt(row.get("docs_price"))
		boxes = cint(row.get("boxes"))
		box_weight_kg = flt(row.get("box_weight_kg"))
		cleaned.append(
			{
				"custom_proforma_invoice": row.get("custom_proforma_invoice") or None,
				"category": row.get("category") or None,
				"item": item,
				"description": row.get("description") or None,
				"hs_code": row.get("hs_code") or None,
				"boxes": boxes,
				"box_weight_kg": box_weight_kg,
				"qty": qty,
				"uom": row.get("uom") or None,
				"rate": rate,
				"docs_price": docs_price,
				"amount": qty * rate,
				"docs_amount": qty * docs_price if docs_price else 0.0,
			}
		)
	return cleaned


def _clean_po_links(po_links, company: str):
	if po_links in (None, ""):
		return []
	if isinstance(po_links, str):
		try:
			po_links = json.loads(po_links)
		except Exception:
			frappe.throw(_("Invalid PO links payload."))
	cleaned = []
	for row in po_links or []:
		po = (row or {}).get("purchase_order")
		if not po:
			continue
		if not frappe.db.exists("Purchase Order", {"name": po, "company": company}):
			frappe.throw(_("Unknown Purchase Order for this company: {0}").format(po))
		cleaned.append(po)
	return cleaned


def _sync_po_links(ci_name: str, company: str, po_links):
	"""Replace the standalone Commercial Invoice PO Link rows for a CI."""
	for link_name in frappe.get_all(
		"Commercial Invoice PO Link",
		filters={"commercial_invoice": ci_name},
		pluck="name",
	):
		frappe.delete_doc("Commercial Invoice PO Link", link_name, ignore_permissions=True)
	for po in _clean_po_links(po_links, company):
		frappe.get_doc(
			{
				"doctype": "Commercial Invoice PO Link",
				"commercial_invoice": ci_name,
				"company": company,
				"purchase_order": po,
			}
		).insert(ignore_permissions=True)


def _assert_row_proformas(cleaned, supplier: str, company: str) -> None:
	"""Every row-level PI must belong to this CI's supplier and company.

	The header link is validated by ``link_proforma_to_ci``; the row link never
	passed through it, yet it feeds the very same shipped/remaining arithmetic
	(``_shipped_pi``) and wins over the header. An unchecked one would move a
	container's boxes onto a stranger's contract.
	"""
	for proforma in sorted({(row.get("custom_proforma_invoice") or "") for row in cleaned} - {""}):
		if not frappe.db.exists(
			"Proforma Invoice", {"name": proforma, "company": company, "supplier": supplier}
		):
			frappe.throw(_("Row proforma {0} does not belong to this supplier and company.").format(proforma))


def _apply_ci_payload(doc, values: dict, items, company: str):
	for field in _CI_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _CI_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		elif field == "customs_fee_off_hours":
			doc.set(field, 1 if cint(val) else 0)
		else:
			doc.set(field, val)
	# Cost-visible users may also set the docs/cash figures directly.
	if _cost_visible():
		for field in ("docs_total", "cash_difference"):
			if field in values and values[field] not in (None, ""):
				doc.set(field, flt(values[field]))

	cleaned = _clean_ci_items(items)
	_assert_row_proformas(cleaned, doc.supplier, company)
	doc.set("items", [])
	total_boxes = 0
	total_kg = 0.0
	agreed_total = 0.0
	for row in cleaned:
		line = doc.append("items", {})
		# The row link is half of the two-level attribution the rules layer reads
		# (_shipped_pi / _ci_item_effective_pi_expr): the row wins, the header answers
		# for rows that carry none. Dropping it here made every line of a container
		# count against whichever PI the header happened to name.
		line.custom_proforma_invoice = row["custom_proforma_invoice"]
		line.category = row["category"]
		line.item = row["item"]
		line.description = row["description"]
		line.hs_code = row["hs_code"]
		line.boxes = row["boxes"]
		line.box_weight_kg = row["box_weight_kg"]
		line.qty = row["qty"]
		line.uom = row["uom"]
		line.rate = row["rate"]
		line.docs_price = row["docs_price"]
		line.amount = row["amount"]
		line.docs_amount = row["docs_amount"]
		total_boxes += row["boxes"]
		total_kg += row["qty"]
		agreed_total += row["amount"]
	doc.total_boxes = total_boxes
	doc.total_kg = total_kg
	doc.agreed_total = agreed_total


def _proforma_has_open_balance(proforma: str, supplier: str, company: str, exclude_ci: str) -> bool:
	"""True when ``proforma`` still has boxes to ship, ignoring ``exclude_ci``.

	Answered by the very function the Smart Fill picker reads — same (PI, category)
	key, same exclusion — so the guard below can never refuse a shipment the picker
	had just offered. ``exclude_ci`` is the CI being saved: it is already in the
	database by the time this runs, and counting it would make the container that
	consumes the last boxes look like it had none to take.
	"""
	res = get_vendor_available_pi_lines(
		company=company,
		supplier=supplier,
		exclude_ci=exclude_ci,
		selected_pis=[proforma],
	)
	return any(flt(line.get("remaining_boxes")) > 0 for line in res.get("lines") or [])


def _link_proforma_if_set(doc, company: str) -> None:
	"""Supersede the CI's Proforma Invoice when the payload named one.

	Deliberately NOT wrapped in try/except. Every exception reachable from here
	is a validation error the user must see: the PI belongs to another company
	or supplier, or it is already superseded and has nothing left to ship.
	Swallowing it saved the CI, silently skipped the PI link, and still reported
	success. Letting it propagate rolls the request back, so the CI and its link
	land together or neither does.

	The early return keeps re-saves editable: `save_proforma` accepts a `status`
	in its payload, so a linked PI can later be moved to CANCELLED. Without this
	check `can_supersede` would then reject every subsequent CI edit.
	"""
	proforma = doc.get("custom_proforma_invoice")
	if not proforma or not frappe.db.exists("Proforma Invoice", proforma):
		return
	if frappe.db.get_value("Proforma Invoice", proforma, "commercial_invoice") == doc.name:
		return
	# One PI ships in several containers and each container is its own CI, so the
	# second one must not try to claim a link the first one already holds. Refusing
	# it is what threw "cannot be superseded from status SUPERSEDED_BY_CI" while
	# the picker was still offering the PI's open boxes.
	status = frappe.db.get_value("Proforma Invoice", proforma, "status")
	# The balance only decides anything for an already-superseded PI; every other
	# status is answered by can_supersede, so the query stays off the normal path.
	open_balance = status == _proforma.SUPERSEDED and _proforma_has_open_balance(
		proforma, doc.supplier, company, doc.name
	)
	if _proforma.accepts_another_ci(status, open_balance):
		return
	link_proforma_to_ci(proforma, doc.name, company)


@frappe.whitelist()
def create_commercial_invoice(
	company: str,
	supplier: str,
	values=None,
	items=None,
	po_links=None,
):
	"""Create a Commercial Invoice (status starts at BOOKED)."""
	_assert_imports_access(company)
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("A valid supplier is required."))
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}

	doc = frappe.new_doc("Commercial Invoice")
	doc.company = company
	doc.supplier = supplier
	doc.status = "BOOKED"
	_apply_ci_payload(doc, values, items, company)
	doc.insert(ignore_permissions=False)
	_sync_po_links(doc.name, company, po_links)
	_link_proforma_if_set(doc, company)
	return {"name": doc.name}


@frappe.whitelist()
def update_commercial_invoice(
	name: str,
	supplier: str,
	values=None,
	items=None,
	po_links=None,
	modified: str | None = None,
):
	"""Update a Commercial Invoice header + items + PO links (status unchanged)."""
	if not name or not frappe.db.exists("Commercial Invoice", name):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(name))
	company = _company_of("Commercial Invoice", name)
	_assert_imports_access(company)
	from stabler.api._common import check_concurrency

	check_concurrency("Commercial Invoice", name, modified)
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("A valid supplier is required."))
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}

	doc = frappe.get_doc("Commercial Invoice", name)
	doc.supplier = supplier
	_apply_ci_payload(doc, values, items, company)
	doc.save(ignore_permissions=False)
	_sync_po_links(doc.name, company, po_links)
	_link_proforma_if_set(doc, company)
	return {"name": doc.name}


@frappe.whitelist()
def set_ci_status(name: str, status: str, reason: str | None = None):
	"""Move a Commercial Invoice along its status pipeline.

	Relies on the doctype's ``validate`` guard (``assert_transition``) to reject
	illegal moves and to require a reason + privileged role for a backward
	correction; that throw is surfaced verbatim to the caller.
	"""
	if not name or not frappe.db.exists("Commercial Invoice", name):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(name))
	_assert_imports_access(_company_of("Commercial Invoice", name))
	doc = frappe.get_doc("Commercial Invoice", name)
	if reason:
		doc.status_correction_reason = reason
	doc.status = status
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# Import Containers
# ---------------------------------------------------------------------------

# Which Freight Booking belongs to a container. Written once because the list
# and the detail view both ask it, and a container whose row says $4,200 must
# not open on a form that says $3,100.
#
# The third leg is the one that carries risk: a booking may be filed against
# the Commercial Invoice rather than a container. Left open it also matched
# bookings that name a DIFFERENT container of the same CI -- with the freight
# amount now on the row, the newest such booking's cost was charged to every
# sibling container. So the CI leg is restricted to bookings that name no
# container at all, which is what "filed against the CI" actually means.
_FREIGHT_MATCH = (
	"fb.container = {name}"
	" OR fb.container = {number}"
	" OR (COALESCE(fb.container, '') = ''"
	" AND fb.commercial_invoice = {ci} AND {ci} IS NOT NULL)"
)
#: Correlated form, for a subquery sitting inside the container list query.
_FREIGHT_FOR_CONTAINER = _FREIGHT_MATCH.format(
	name="c.name", number="c.container_number", ci="c.commercial_invoice"
)
#: Parameterised form: name, container_number, commercial_invoice, again.
_FREIGHT_FOR_ONE = _FREIGHT_MATCH.format(name="%s", number="%s", ci="%s")

#: The booking columns both endpoints read. `amount`, `cash_payment` and
#: `bank_payment` are permlevel 1 on Freight Booking; raw SQL does not honour
#: permlevel, so they are masked by name on the way out.
_FREIGHT_FIELDS = """
		SELECT fb.name, fb.transporter, s_tr.supplier_name AS transporter_name,
		       COALESCE(fb.amount, 0) AS transport_cost,
		       COALESCE(fb.cash_payment, 0) AS paid_cash,
		       COALESCE(fb.bank_payment, 0) AS paid_bank,
		       fb.currency AS transport_currency, fb.vehicle_number
		FROM `tabFreight Booking` fb
		LEFT JOIN `tabSupplier` s_tr ON s_tr.name = fb.transporter
"""


@frappe.whitelist()
def list_import_containers(
	company: str,
	search: str | None = None,
	status: str | None = None,
	commercial_invoice: str | None = None,
	bl_type: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Import Container list rows (cost total masked for non-cost users)."""
	_assert_imports_access(company)
	clauses, params = rules.container_filter_clauses(search, status, commercial_invoice, bl_type)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["c.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT
          c.name, c.container_number, c.container_type, c.container_size, c.bl_type, c.seal_number,
          c.commercial_invoice, c.supplier, s.supplier_name, c.status, c.total_kg, c.total_boxes,
          c.total_amount, c.currency, c.advance_70_payment_entry,
          c.cut_off, c.gate_open, c.gate_close, c.gate_in_date,
          ci.ci_number, ci.vessel, ci.voyage, ci.bl_number, ci.port_of_loading, ci.port_of_discharge,
          ci.etd, ci.eta, ci.eta_transit_port, ci.custom_proforma_invoice AS proforma_invoice,
          (SELECT fb.name
           FROM `tabFreight Booking` fb
           WHERE {_FREIGHT_FOR_CONTAINER}
           ORDER BY fb.creation DESC LIMIT 1) AS freight_booking_name,
          (SELECT COALESCE(SUM(cl.amount), 0) FROM `tabContainer Cost Line` cl
             WHERE cl.parent = c.name) AS cost_lines_total
        FROM `tabImport Container` c
        LEFT JOIN `tabCommercial Invoice` ci ON ci.name = c.commercial_invoice
        LEFT JOIN `tabSupplier` s ON s.name = c.supplier
        WHERE {where}
        ORDER BY c.creation DESC, c.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	# One subquery names the booking; its columns come from a single batched
	# fetch. Asking each column with its own `ORDER BY creation DESC LIMIT 1`
	# let two bookings created in the same second answer different columns, so
	# a row could show one transporter beside another one's cash figure.
	booking_of = _freight_bookings({r["freight_booking_name"] for r in rows if r.get("freight_booking_name")})
	for r in rows:
		r["cost_lines_total"] = flt(r["cost_lines_total"])
		fb = booking_of.get(r.pop("freight_booking_name", None)) or {}
		r["transporter"] = fb.get("transporter_name") or fb.get("transporter") or ""
		r["vehicle_number"] = fb.get("vehicle_number") or ""
		r["transport_cost"] = flt(fb.get("transport_cost"))
		r["paid_cash"] = flt(fb.get("paid_cash"))
		r["paid_bank"] = flt(fb.get("paid_bank"))
		r["transport_currency"] = fb.get("transport_currency") or ""

	rules.mask_named(rows, rules.CONTAINER_LIST_MASK_FIELDS, _cost_visible())
	total = _count(
		rules.count_query(
			"`tabImport Container` c LEFT JOIN `tabCommercial Invoice` ci ON ci.name = c.commercial_invoice LEFT JOIN `tabSupplier` s ON s.name = c.supplier",
			where,
		),
		params,
	)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def get_import_container(name: str):
	"""Full Import Container payload: header, items, cost lines (masked)."""
	if not name or not frappe.db.exists("Import Container", name):
		frappe.throw(_("Unknown Import Container: {0}").format(name))
	_assert_imports_access(_company_of("Import Container", name))
	_assert_can_read("Import Container", name)
	doc = frappe.get_doc("Import Container", name)
	visible = _cost_visible()

	items = [
		{
			"item_code": it.item_code,
			"item_name": it.item_name,
			"category": it.category,
			"box_qty": cint(it.box_qty),
			"box_kg": flt(it.box_kg),
			"total_kg": flt(it.total_kg),
			"rate": flt(it.rate),
			"amount": flt(it.amount),
		}
		for it in (doc.items or [])
	]
	cost_lines = [
		{
			"cost_component": cl.cost_component,
			"description": cl.description,
			"currency": cl.currency,
			"amount": flt(cl.amount),
			"amount_uzs": flt(cl.amount_uzs),
			"include_in_landed_cost": cint(cl.include_in_landed_cost),
			"lcv_ref": cl.lcv_ref,
		}
		for cl in (doc.cost_lines or [])
	]
	rules.mask_named(items, rules.CONTAINER_ITEM_MASK_FIELDS, visible)
	rules.mask_named(cost_lines, rules.CONTAINER_COST_LINE_MASK_FIELDS, visible)

	payload = {
		"name": doc.name,
		"container_number": doc.container_number,
		"commercial_invoice": doc.commercial_invoice,
		"supplier": doc.supplier,
		"company": doc.company,
		"currency": doc.currency,
		"container_type": doc.container_type,
		"container_size": doc.container_size,
		"bl_type": doc.bl_type,
		"seal_number": doc.seal_number,
		"gross_weight": flt(doc.gross_weight),
		"vgm": flt(doc.vgm),
		"status": doc.status,
		"total_boxes": cint(doc.total_boxes),
		"total_kg": flt(doc.total_kg),
		"total_amount": flt(doc.total_amount),
		"advance_70_payment_entry": doc.advance_70_payment_entry,
		"gate_in_date": str(doc.gate_in_date) if doc.gate_in_date else None,
		"customs_clearance_date": str(doc.customs_clearance_date) if doc.customs_clearance_date else None,
		"telex_release_date": str(doc.telex_release_date) if doc.telex_release_date else None,
		"allocated_deposit_amount": flt(doc.allocated_deposit_amount),
		"balance_due_amount": flt(doc.balance_due_amount),
		"payment_70_status": doc.payment_70_status,
		"payment_70_date": str(doc.payment_70_date) if doc.payment_70_date else None,
		"payment_70_amount": flt(doc.payment_70_amount),
		"cut_off": str(doc.cut_off) if doc.cut_off else None,
		"gate_open": str(doc.gate_open) if doc.gate_open else None,
		"gate_close": str(doc.gate_close) if doc.gate_close else None,
		"allowed_transitions": _container_next_statuses(doc.status),
		"cost_visible": visible,
		"items": items,
		"cost_lines": cost_lines,
	}

	fb_res = frappe.db.sql(
		f"""{_FREIGHT_FIELDS}
		WHERE {_FREIGHT_FOR_ONE}
		ORDER BY fb.creation DESC LIMIT 1
		""",
		(doc.name, doc.container_number, doc.commercial_invoice, doc.commercial_invoice),
		as_dict=True,
	)
	fb_data = fb_res[0] if fb_res else {}
	payload["transporter"] = fb_data.get("transporter") or ""
	payload["transporter_name"] = fb_data.get("transporter_name") or fb_data.get("transporter") or ""
	payload["transport_cost"] = flt(fb_data.get("transport_cost"))
	payload["paid_cash"] = flt(fb_data.get("paid_cash"))
	payload["paid_bank"] = flt(fb_data.get("paid_bank"))
	payload["transport_currency"] = fb_data.get("transport_currency") or ""
	payload["vehicle_number"] = fb_data.get("vehicle_number") or ""
	payload["freight_booking"] = fb_data.get("name") or ""

	rules.mask_named(payload, rules.CONTAINER_MASK_FIELDS, visible)
	return payload


def _freight_bookings(names: set[str]) -> dict[str, dict]:
	"""Freight Booking rows keyed by name, for a page of containers."""
	if not names:
		return {}
	rows = frappe.db.sql(
		f"""{_FREIGHT_FIELDS}
		WHERE fb.name IN %(names)s
		""",
		{"names": tuple(names)},
		as_dict=True,
	)
	return {r["name"]: r for r in rows}


def _container_next_statuses(status: str) -> list[str]:
	from stabler.stabler.doctype.import_container.import_container import _ALLOWED_TRANSITIONS

	return sorted(_ALLOWED_TRANSITIONS.get(status, set()))


def _truck_next_statuses(status: str) -> list[str]:
	from stabler.stabler.doctype.import_truck.import_truck import _ALLOWED_TRANSITIONS

	return sorted(_ALLOWED_TRANSITIONS.get(status, set()))


# ---------------------------------------------------------------------------
# Import Trucks
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_import_trucks(
	company: str,
	search: str | None = None,
	status: str | None = None,
	commercial_invoice: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Import Truck list rows (transport cost masked for non-cost users)."""
	_assert_imports_access(company)
	clauses, params = rules.truck_filter_clauses(search, status, commercial_invoice)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["tr.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT
          tr.name, tr.truck_number, tr.status, tr.trucking_company,
          tr.destination_warehouse, tr.total_kg, tr.total_boxes,
          tr.departure_date, tr.estimated_arrival, tr.actual_arrival,
          tr.transport_cost, tr.transport_currency, tr.transport_purchase_invoice,
          (SELECT COUNT(*) FROM `tabTruck Receipt` r
             WHERE r.truck = tr.name AND r.docstatus < 2) AS receipt_count
        FROM `tabImport Truck` tr
        WHERE {where}
        ORDER BY tr.creation DESC, tr.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		for f in ("departure_date", "estimated_arrival", "actual_arrival"):
			r[f] = str(r[f]) if r[f] else None
	rules.mask_named(rows, rules.TRUCK_MASK_FIELDS, _cost_visible())
	total = _count(rules.count_query("`tabImport Truck` tr", where), params)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def get_import_truck(name: str):
	"""Full Import Truck payload incl. cold-chain + linked truck receipts."""
	if not name or not frappe.db.exists("Import Truck", name):
		frappe.throw(_("Unknown Import Truck: {0}").format(name))
	_assert_imports_access(_company_of("Import Truck", name))
	_assert_can_read("Import Truck", name)
	doc = frappe.get_doc("Import Truck", name)

	payload = {
		"name": doc.name,
		"truck_number": doc.truck_number,
		"commercial_invoice": doc.commercial_invoice,
		"trucking_company": doc.trucking_company,
		"company": doc.company,
		"driver_name": doc.driver_name,
		"driver_phone": doc.driver_phone,
		"destination_warehouse": doc.destination_warehouse,
		"status": doc.status,
		"departure_date": str(doc.departure_date) if doc.departure_date else None,
		"border_crossing_date": str(doc.border_crossing_date) if doc.border_crossing_date else None,
		"estimated_arrival": str(doc.estimated_arrival) if doc.estimated_arrival else None,
		"actual_arrival": str(doc.actual_arrival) if doc.actual_arrival else None,
		"target_temp_min": flt(doc.target_temp_min),
		"target_temp_max": flt(doc.target_temp_max),
		"total_boxes": cint(doc.total_boxes),
		"total_kg": flt(doc.total_kg),
		"transport_cost": flt(doc.transport_cost),
		"transport_currency": doc.transport_currency,
		"transport_payment_status": doc.transport_payment_status,
		"transport_purchase_invoice": doc.transport_purchase_invoice,
		# Departure-gate override — absent on a tenant that has not run v55 yet,
		# so read through .get() rather than assuming the field exists.
		"departure_override": cint(doc.get("departure_override")),
		"departure_override_reason": doc.get("departure_override_reason") or None,
		"allowed_transitions": _truck_next_statuses(doc.status),
		"cost_visible": _cost_visible(),
		"receipts": frappe.get_all(
			"Truck Receipt",
			filters={"truck": name, "docstatus": ["<", 2]},
			fields=["name", "arrival_date", "received_by", "purchase_receipt", "docstatus"],
			order_by="creation asc",
		),
	}
	rules.mask_named(payload, rules.TRUCK_MASK_FIELDS, _cost_visible())
	return payload


# ---------------------------------------------------------------------------
# BRV customs-clearance fee — SPA wrapper over the imports_module hook
# ---------------------------------------------------------------------------


@frappe.whitelist()
def compute_customs_fee(commercial_invoice: str, off_hours=None, on_date=None, apply=0):
	"""Compute (and optionally write) the BRV customs-clearance fee for a CI.

	Thin wrapper over ``imports_module.hooks.compute_customs_fee`` so the SPA
	has a single ``stabler.api.imports`` entry point; the access gate here is
	the imports-role check, the hook itself re-checks the company toggle.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	_assert_imports_access(_company_of("Commercial Invoice", commercial_invoice))
	from stabler.stabler.imports_module.hooks import compute_customs_fee as _compute

	return _compute(commercial_invoice, off_hours=off_hours, on_date=on_date, apply=apply)


# ---------------------------------------------------------------------------
# GRN Checklists — the progressive-acceptance receiving hub (WP6a)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_grn_checklists(
	company: str,
	search: str | None = None,
	status: str | None = None,
	variance_category: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""GRN Checklist list rows — completion, variance and receiving progress.

	None of the receiving figures (kg/boxes) are cost-sensitive, so no masking
	is applied here (K3 covers landed-cost / dual-pricing money only).
	"""
	_assert_imports_access(company)
	clauses, params = rules.grn_filter_clauses(search, status, variance_category)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["g.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT
          g.name, g.commercial_invoice, g.supplier, s.supplier_name, g.warehouse,
          g.receipt_status, g.docstatus, g.expected_arrival_date,
          g.expected_total_kg, g.received_total_kg, g.pending_total_kg,
          g.expected_total_boxes, g.received_total_boxes, g.pending_total_boxes,
          g.completion_percentage, g.variance_percentage, g.variance_category,
          g.trucks_received_count, g.claim_required,
          (SELECT COUNT(*) FROM `tabGRN LCV Ref` l WHERE l.parent = g.name) AS lcv_count
        FROM `tabGRN Checklist` g
        LEFT JOIN `tabSupplier` s ON s.name = g.supplier
        WHERE {where}
        ORDER BY g.creation DESC, g.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		r["expected_arrival_date"] = str(r["expected_arrival_date"]) if r["expected_arrival_date"] else None
		r["docstatus"] = cint(r["docstatus"])
		r["claim_required"] = bool(r["claim_required"])
		r["lcv_count"] = cint(r["lcv_count"])
	total = _count(rules.count_query("`tabGRN Checklist` g", where), params)
	return {"rows": rows, "total_count": total}


def _po_rate_map(commercial_invoice, item_codes) -> dict:
	"""Resolved Purchase Order rate per item code — ``None`` where there is none.

	The receiving form warns about a line that would enter stock unpriced *before*
	the operator clicks Submit, which it can only do if it is told the Purchase
	Order side of the price. It is resolved here exactly the way the build path
	resolves it (``hooks._po_item_rows_for_ci`` + ``receipt_math.resolve_po_rate``),
	so the form and the submit block cannot disagree about which line has no price.
	``_po_item_rows_for_ci`` queries, so it runs once per request, never per row.

	Anything that does not resolve to a positive rate comes back as ``None``, not
	0. The form reads ``null`` as "unknown — do not accuse this line"; a 0 would
	mark every line of every receipt whose Commercial Invoice has no linked
	Purchase Order as unpriced, which is a false alarm on the common case here (PO
	creation is manual and linkage is routinely missing). A missing Commercial
	Invoice or no linked POs degrade to the same "unknown" — this is a hint for the
	operator, never a gate; the gate is on submit.
	"""
	from stabler.stabler.imports_module import receipt_math
	from stabler.stabler.imports_module.hooks import _po_item_rows_for_ci

	if not commercial_invoice:
		return {}
	po_rows = _po_item_rows_for_ci(commercial_invoice)
	if not po_rows:
		return {}
	rates: dict[str, float | None] = {}
	for code in {c for c in (item_codes or []) if c}:
		rate = flt(receipt_math.resolve_po_rate(code, po_rows)["rate"])
		rates[code] = rate if rate > 0 else None
	return rates


@frappe.whitelist()
def get_grn_checklist(name: str):
	"""Full GRN Checklist payload: header, items, truck receipts, LCVs, vet cert."""
	if not name or not frappe.db.exists("GRN Checklist", name):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(name))
	_assert_imports_access(_company_of("GRN Checklist", name))
	_assert_can_read("GRN Checklist", name)
	doc = frappe.get_doc("GRN Checklist", name)

	from stabler.stabler.doctype.vet_certificate.vet_certificate import has_valid_vet_cert

	truck_receipts = frappe.db.sql(
		"""
        SELECT r.name, r.truck, tr.truck_number, r.arrival_date, r.docstatus,
               r.total_boxes_this_truck, r.total_kg_this_truck, r.purchase_receipt,
               r.temperature_check_passed
        FROM `tabTruck Receipt` r
        LEFT JOIN `tabImport Truck` tr ON tr.name = r.truck
        WHERE r.grn_checklist = %(grn)s AND r.docstatus < 2
        ORDER BY r.arrival_date ASC, r.creation ASC
        """,
		{"grn": name},
		as_dict=True,
	)
	for r in truck_receipts:
		r["arrival_date"] = str(r["arrival_date"]) if r["arrival_date"] else None
		r["docstatus"] = cint(r["docstatus"])

	lcv_names = [lc.lcv for lc in (doc.landed_cost_vouchers or []) if lc.lcv]
	lcv_docstatus = {}
	if lcv_names:
		lcv_docstatus = {
			r.name: cint(r.docstatus)
			for r in frappe.get_all(
				"Landed Cost Voucher", filters={"name": ["in", lcv_names]}, fields=["name", "docstatus"]
			)
		}

	po_rates = _po_rate_map(doc.commercial_invoice, [it.item_code for it in (doc.grn_items or [])])

	payload = {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"commercial_invoice": doc.commercial_invoice,
		"supplier": doc.supplier,
		"supplier_name": frappe.db.get_value("Supplier", doc.supplier, "supplier_name")
		if doc.supplier
		else None,
		"warehouse": doc.warehouse,
		"receipt_status": doc.receipt_status,
		"docstatus": cint(doc.docstatus),
		"expected_arrival_date": str(doc.expected_arrival_date) if doc.expected_arrival_date else None,
		"first_receipt_date": str(doc.first_receipt_date) if doc.first_receipt_date else None,
		"completion_date": str(doc.completion_date) if doc.completion_date else None,
		"expected_total_boxes": cint(doc.expected_total_boxes),
		"expected_total_kg": flt(doc.expected_total_kg),
		"received_total_boxes": cint(doc.received_total_boxes),
		"received_total_kg": flt(doc.received_total_kg),
		"pending_total_boxes": cint(doc.pending_total_boxes),
		"pending_total_kg": flt(doc.pending_total_kg),
		"completion_percentage": flt(doc.completion_percentage),
		"variance_boxes": cint(doc.variance_boxes),
		"variance_kg": flt(doc.variance_kg),
		"variance_percentage": flt(doc.variance_percentage),
		"variance_category": doc.variance_category,
		"trucks_received_count": cint(doc.trucks_received_count),
		"claim_required": bool(doc.claim_required),
		"claim_reference": doc.claim_reference,
		"vet_cert_override": bool(doc.vet_cert_override),
		"notes": doc.notes,
		"has_valid_vet_cert": has_valid_vet_cert(doc.commercial_invoice),
		"items": [
			{
				"name": it.name,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"expected_boxes": cint(it.expected_boxes),
				"expected_box_kg": flt(it.expected_box_kg),
				"expected_total_kg": flt(it.expected_total_kg),
				"received_boxes": cint(it.received_boxes),
				"received_kg": flt(it.received_kg),
				"pending_boxes": cint(it.pending_boxes),
				"pending_kg": flt(it.pending_kg),
				"variance_kg": flt(it.variance_kg),
				"variance_percentage": flt(it.variance_percentage),
				"status": it.status,
				# The rate the Purchase Receipt would take off the linked Purchase
				# Order, or None when it does not resolve to one. This is the *create*
				# path — there is no Truck Receipt yet, so the form has no other way to
				# tell the operator a line has no price until submit refuses it.
				"po_rate": po_rates.get(it.item_code),
			}
			for it in (doc.grn_items or [])
		],
		"truck_receipts": truck_receipts,
		"landed_cost_vouchers": [
			{
				"lcv": lc.lcv,
				"posted_on": str(lc.posted_on) if lc.posted_on else None,
				"note": lc.note,
				"docstatus": lcv_docstatus.get(lc.lcv) if lc.lcv else None,
			}
			for lc in (doc.landed_cost_vouchers or [])
		],
		"vet_certificates": frappe.get_all(
			"Vet Certificate",
			filters={"commercial_invoice": doc.commercial_invoice},
			fields=["name", "certificate_number", "status", "expiry_date", "issue_date"],
			order_by="creation desc",
		),
	}
	for vc in payload["vet_certificates"]:
		vc["expiry_date"] = str(vc["expiry_date"]) if vc["expiry_date"] else None
		vc["issue_date"] = str(vc["issue_date"]) if vc["issue_date"] else None
	return payload


@frappe.whitelist()
def create_grn_for_ci(commercial_invoice: str):
	"""Create a GRN Checklist from a Commercial Invoice (idempotent).

	Expected quantities are a snapshot of the current packing aggregate. An
	incomplete aggregate still creates a refreshable shell and never falls back
	to commercial invoice lines. Existing GRNs are returned after a read check.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	_assert_can_read("Commercial Invoice", commercial_invoice)
	company = _company_of("Commercial Invoice", commercial_invoice)
	_assert_imports_access(company)

	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	result = packing_service.create_or_get_grn(ci, ignore_permissions=False)
	if result["created"]:
		return result
	_assert_can_read("GRN Checklist", result["name"])
	summary = packing_service.summary_for_ci(commercial_invoice, company)
	locked = bool(frappe.db.get_value("GRN Checklist", result["name"], "expected_snapshot_locked"))
	return {
		**result,
		"packing_status": summary["status"],
		"expected_snapshot_locked": locked,
	}


@frappe.whitelist()
def refresh_grn_expected_quantities(name: str):
	if not name or not frappe.db.exists("GRN Checklist", name):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(name))
	company = _company_of("GRN Checklist", name)
	_assert_imports_access(company)
	_assert_can_write("GRN Checklist", name)
	commercial_invoice = frappe.db.get_value("GRN Checklist", name, "commercial_invoice")
	packing_service.lock_commercial_invoices([commercial_invoice])
	grn_state = frappe.db.get_value(
		"GRN Checklist",
		name,
		["docstatus", "expected_snapshot_locked"],
		as_dict=True,
		for_update=True,
	)
	grn = frappe.get_doc("GRN Checklist", name)
	submitted_receipt = frappe.db.sql(
		"""SELECT name
        FROM `tabTruck Receipt`
        WHERE grn_checklist = %s AND docstatus = 1
        LIMIT 1
        FOR UPDATE SKIP LOCKED""",
		name,
	)
	if cint(grn_state.docstatus) != 0 or cint(grn_state.expected_snapshot_locked) or submitted_receipt:
		frappe.throw(_("Expected quantities are locked after the first submitted Truck Receipt."))
	summary = packing_service.summary_for_ci(grn.commercial_invoice, company, for_update=True)
	packing_service.replace_grn_expected_rows(grn, summary["expected_items"])
	with packing_service.allow_expected_snapshot_update():
		grn.save(ignore_permissions=False)
	return {
		"name": grn.name,
		"packing_status": summary["status"],
		"expected_snapshot_locked": False,
	}


@frappe.whitelist()
def submit_grn_checklist(name: str):
	"""Submit a GRN Checklist (triggers the DRAFT Landed Cost Voucher build).

	The received-kg and veterinary-certificate gates live in the doctype's
	``before_submit`` hook; their ``frappe.throw`` messages are surfaced verbatim
	so the SPA can, e.g., point the user at the vet-certificate card.
	"""
	if not name or not frappe.db.exists("GRN Checklist", name):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(name))
	_assert_imports_access(_company_of("GRN Checklist", name))
	doc = frappe.get_doc("GRN Checklist", name)
	if doc.docstatus != 0:
		frappe.throw(_("This GRN Checklist is not in a draft state."))
	doc.submit()
	return {"name": doc.name, "docstatus": cint(doc.docstatus), "receipt_status": doc.receipt_status}


@frappe.whitelist()
def create_additional_lcv(grn_name: str):
	"""Build an additional DRAFT Landed Cost Voucher for late costs (Imports Manager).

	Thin SPA wrapper over the imports_module hook so the front-end has a single
	``stabler.api.imports`` entry point; the hook re-checks the company toggle.
	"""
	if not grn_name or not frappe.db.exists("GRN Checklist", grn_name):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(grn_name))
	_assert_imports_access(_company_of("GRN Checklist", grn_name))
	if not set(frappe.get_roles()).intersection(("Imports Manager", "System Manager")):
		frappe.throw(
			_("Only an Imports Manager can add a Landed Cost Voucher."),
			frappe.PermissionError,
		)
	from stabler.stabler.imports_module.hooks import create_additional_lcv as _create

	return {"lcv": _create(grn_name)}


# ---------------------------------------------------------------------------
# Truck Receipts — the tablet warehouse-floor receiving surface (WP6a)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_truck_receipts(
	company: str,
	grn: str | None = None,
	search: str | None = None,
	status: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Truck Receipt list rows (``status`` filters docstatus 0/1/2)."""
	_assert_imports_access(company)
	clauses, params = rules.truck_receipt_filter_clauses(search, grn, status)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["r.company = %(company)s", "r.docstatus < 2", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT
          r.name, r.grn_checklist, r.truck, tr.truck_number, r.arrival_date,
          r.received_by, r.docstatus, r.total_boxes_this_truck, r.total_kg_this_truck,
          r.temperature_at_arrival, r.temperature_check_passed, r.purchase_receipt
        FROM `tabTruck Receipt` r
        LEFT JOIN `tabImport Truck` tr ON tr.name = r.truck
        WHERE {where}
        ORDER BY r.creation DESC, r.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		r["arrival_date"] = str(r["arrival_date"]) if r["arrival_date"] else None
		r["docstatus"] = cint(r["docstatus"])
	return rows


@frappe.whitelist()
def get_truck_receipt(name: str):
	"""Full Truck Receipt payload: header, QC panel, item lines."""
	if not name or not frappe.db.exists("Truck Receipt", name):
		frappe.throw(_("Unknown Truck Receipt: {0}").format(name))
	_assert_imports_access(_company_of("Truck Receipt", name))
	_assert_can_read("Truck Receipt", name)
	doc = frappe.get_doc("Truck Receipt", name)
	grn_ci = (
		frappe.db.get_value("GRN Checklist", doc.grn_checklist, "commercial_invoice")
		if doc.grn_checklist
		else None
	)
	po_rates = _po_rate_map(grn_ci, [it.grn_item_code for it in (doc.items or [])])
	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"grn_checklist": doc.grn_checklist,
		"truck": doc.truck,
		"truck_number": frappe.db.get_value("Import Truck", doc.truck, "truck_number") if doc.truck else None,
		"docstatus": cint(doc.docstatus),
		"arrival_date": str(doc.arrival_date) if doc.arrival_date else None,
		"arrival_time": str(doc.arrival_time) if doc.arrival_time else None,
		"received_by": doc.received_by,
		"total_boxes_this_truck": cint(doc.total_boxes_this_truck),
		"total_kg_this_truck": flt(doc.total_kg_this_truck),
		"purchase_receipt": doc.purchase_receipt,
		"temperature_at_arrival": flt(doc.temperature_at_arrival)
		if doc.temperature_at_arrival not in (None, "")
		else None,
		"temperature_check_passed": bool(doc.temperature_check_passed),
		"packaging_check_passed": bool(doc.packaging_check_passed),
		"seal_intact": bool(doc.seal_intact),
		"seal_number": doc.seal_number,
		"qc_notes": doc.qc_notes,
		"items": [
			{
				"name": it.name,
				"grn_item_code": it.grn_item_code,
				"received_boxes": cint(it.received_boxes),
				"received_kg": flt(it.received_kg),
				"condition": it.condition,
				# Manual fallback price. Without it the form cannot show back what the
				# operator typed, and the escape hatch for an unpriced line looks empty
				# on every reload.
				"rate": flt(it.rate),
				# The Purchase Order side of the price, or None when it does not
				# resolve to a positive rate. The form needs both numbers to tell an
				# unpriced line (neither) from a line the PO already prices; None is
				# read as "unknown", so a receipt with no linked PO is not accused.
				"po_rate": po_rates.get(it.grn_item_code),
				"damaged_boxes": cint(it.damaged_boxes),
				"rejected_boxes": cint(it.rejected_boxes),
				"expiry_date": str(it.expiry_date) if it.expiry_date else None,
			}
			for it in (doc.items or [])
		],
	}


_TR_HEADER_FIELDS = (
	"arrival_date",
	"arrival_time",
	"received_by",
	"temperature_at_arrival",
	"temperature_check_passed",
	"packaging_check_passed",
	"seal_intact",
	"seal_number",
	"qc_notes",
)
_TR_CHECK_FIELDS = ("temperature_check_passed", "packaging_check_passed", "seal_intact")


def _clean_tr_items(items):
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw(_("Invalid items payload."))
	if not isinstance(items, list) or not items:
		frappe.throw(_("At least one received item line is required."))
	cleaned = []
	for idx, row in enumerate(items, start=1):
		item = (row or {}).get("grn_item_code")
		if not item:
			frappe.throw(_("Row {0}: item is required.").format(idx))
		if not frappe.db.exists("Item", item):
			frappe.throw(_("Row {0}: unknown item '{1}'.").format(idx, item))
		condition = (row.get("condition") or "Good").strip()
		if condition not in ("Good", "Damaged", "Rejected"):
			condition = "Good"
		cleaned.append(
			{
				"grn_item_code": item,
				"received_boxes": cint(row.get("received_boxes")),
				"received_kg": flt(row.get("received_kg")),
				"condition": condition,
				# Optional: the Purchase Order rate is the normal path. This is the only
				# way to price a line the PO does not cover, and _create_pr_for_truck_receipt
				# refuses to post an unpriced line -- so dropping it here would turn the
				# guard into a dead end at the receiving gate.
				"rate": flt(row.get("rate")),
				"damaged_boxes": cint(row.get("damaged_boxes")),
				"rejected_boxes": cint(row.get("rejected_boxes")),
				"expiry_date": getdate(row["expiry_date"]) if row.get("expiry_date") else None,
			}
		)
	return cleaned


def _apply_tr_payload(doc, values: dict, items):
	for field in _TR_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field == "arrival_date":
			doc.set(field, getdate(val) if val else None)
		elif field == "temperature_at_arrival":
			doc.set(field, flt(val) if val not in (None, "") else None)
		elif field in _TR_CHECK_FIELDS:
			doc.set(field, 1 if cint(val) else 0)
		else:
			doc.set(field, val)
	doc.set("items", [])
	for row in _clean_tr_items(items):
		line = doc.append("items", {})
		for key, value in row.items():
			line.set(key, value)


@frappe.whitelist()
def create_truck_receipt(grn_checklist: str, truck: str, values=None, items=None):
	"""Create a DRAFT Truck Receipt against a GRN Checklist for one truck."""
	if not grn_checklist or not frappe.db.exists("GRN Checklist", grn_checklist):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(grn_checklist))
	company = _company_of("GRN Checklist", grn_checklist)
	_assert_imports_access(company)
	if not truck or not frappe.db.exists("Import Truck", {"name": truck, "company": company}):
		frappe.throw(_("A valid truck for this company is required."))
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}

	doc = frappe.new_doc("Truck Receipt")
	doc.company = company
	doc.grn_checklist = grn_checklist
	doc.truck = truck
	if not values.get("arrival_date"):
		values["arrival_date"] = today()
	_apply_tr_payload(doc, values, items)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def update_truck_receipt(name: str, values=None, items=None, modified: str | None = None):
	"""Update a DRAFT Truck Receipt (submitted receipts are immutable)."""
	if not name or not frappe.db.exists("Truck Receipt", name):
		frappe.throw(_("Unknown Truck Receipt: {0}").format(name))
	_assert_imports_access(_company_of("Truck Receipt", name))
	doc = frappe.get_doc("Truck Receipt", name)
	if doc.docstatus != 0:
		frappe.throw(_("A submitted truck receipt can no longer be edited."))
	from stabler.api._common import check_concurrency

	check_concurrency("Truck Receipt", name, modified)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	_apply_tr_payload(doc, values, items)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


def _truck_receipt_po_warnings(doc) -> list[str]:
	"""Re-derive the PO-rate resolution warnings for a Truck Receipt's lines.

	The submit hook logs these to ``stabler.imports`` but does not return them; we
	recompute the same ``receipt_math.resolve_po_rate`` decision so the SPA can
	show the warehouse what the Purchase Order side of the price looked like.

	A warning is dropped when the rate typed on the line is what priced it *and*
	the Purchase Order resolved no rate at all: those messages end "rate set to 0",
	which stopped being true the moment the manual rate became the escape hatch for
	exactly this case. Shown on a receipt that posted correctly, the message
	describes the defect the operator just avoided — and invites them to cancel a
	good Purchase Receipt over it.

	Every other warning stays, including the ambiguous-linkage one on a line a
	manual rate priced: that fires when several Purchase Order lines agree on a
	rate, and what it reports is the row linkage the Purchase Receipt had to omit.
	That is true whoever set the price, and it is why the Purchase Order stays
	"not received" — a real thing to chase, and no accusation about valuation.
	"""
	from stabler.stabler.imports_module import receipt_math
	from stabler.stabler.imports_module.hooks import _po_item_rows_for_ci

	grn_ci = frappe.db.get_value("GRN Checklist", doc.grn_checklist, "commercial_invoice")
	po_rows = _po_item_rows_for_ci(grn_ci) if grn_ci else []
	warnings: list[str] = []
	for it in doc.items or []:
		if receipt_math.good_qty(it.received_kg, it.condition) <= 0:
			continue
		res = receipt_math.resolve_po_rate(it.grn_item_code, po_rows)
		if not res["warning"]:
			continue
		_rate, source = receipt_math.effective_rate(it.get("rate"), res["rate"])
		# The zero this warning complains about was replaced by the rate typed on
		# the line, so the receipt posted at the operator's price, not at 0.
		if source == receipt_math.RATE_SOURCE_MANUAL and res["rate"] <= 0:
			continue
		warnings.append(res["warning"])
	return warnings


@frappe.whitelist()
def submit_truck_receipt(name: str):
	"""Submit a Truck Receipt (creates + submits the partial Purchase Receipt).

	Returns the created Purchase Receipt name and a ``warnings`` array (PO-rate
	resolution notes). The cold-chain temperature gate lives in the doctype
	``validate`` — its ``frappe.throw`` is surfaced verbatim to the caller.
	"""
	if not name or not frappe.db.exists("Truck Receipt", name):
		frappe.throw(_("Unknown Truck Receipt: {0}").format(name))
	_assert_imports_access(_company_of("Truck Receipt", name))
	doc = frappe.get_doc("Truck Receipt", name)
	if doc.docstatus != 0:
		frappe.throw(_("This truck receipt is not in a draft state."))
	warnings = _truck_receipt_po_warnings(doc)
	doc.submit()
	doc.reload()
	return {
		"name": doc.name,
		"docstatus": cint(doc.docstatus),
		"purchase_receipt": doc.purchase_receipt,
		"warnings": warnings,
	}


@frappe.whitelist()
def trucks_pending_receipt(company: str, grn: str):
	"""Trucks of the GRN's CI that have arrived and have no submitted receipt yet."""
	_assert_imports_access(company)
	if not grn or not frappe.db.exists("GRN Checklist", grn):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(grn))
	ci = frappe.db.get_value("GRN Checklist", grn, "commercial_invoice")
	if not ci:
		return []
	clauses, params = rules.trucks_pending_filter_clauses(ci)
	where = " AND ".join(["t.company = %(company)s", *clauses])
	params["company"] = company
	rows = frappe.db.sql(
		f"""
        SELECT t.name, t.truck_number, t.driver_name, t.driver_phone, t.status,
               t.total_boxes, t.total_kg, t.destination_warehouse,
               t.target_temp_min, t.target_temp_max, t.estimated_arrival, t.actual_arrival
        FROM `tabImport Truck` t
        WHERE {where}
        ORDER BY t.actual_arrival ASC, t.creation ASC
        """,
		params,
		as_dict=True,
	)
	# Exclude trucks that already have a submitted Truck Receipt for this GRN.
	received = set(
		frappe.get_all(
			"Truck Receipt",
			filters={"grn_checklist": grn, "docstatus": 1},
			pluck="truck",
		)
	)
	out = []
	for r in rows:
		if r["name"] in received:
			continue
		for f in ("estimated_arrival", "actual_arrival"):
			r[f] = str(r[f]) if r[f] else None
		r["target_temp_min"] = flt(r["target_temp_min"])
		r["target_temp_max"] = flt(r["target_temp_max"])
		out.append(r)
	return out


# ---------------------------------------------------------------------------
# Vet Certificates — the meat-import regulatory gate (WP6a)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_vet_certificates(
	company: str,
	commercial_invoice: str | None = None,
	status: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Vet Certificate list rows for a company (optionally scoped to a CI)."""
	_assert_imports_access(company)
	filters = {"company": company}
	if commercial_invoice:
		filters["commercial_invoice"] = commercial_invoice
	if status:
		filters["status"] = status
	rows = frappe.get_all(
		"Vet Certificate",
		filters=filters,
		fields=[
			"name",
			"certificate_number",
			"commercial_invoice",
			"issuing_authority",
			"issue_date",
			"expiry_date",
			"status",
			"reviewed_by",
		],
		order_by="creation desc",
		limit_start=max(0, cint(limit_start)),
		limit_page_length=rules.clamp_page_length(limit_page_length),
	)
	for r in rows:
		r["issue_date"] = str(r["issue_date"]) if r["issue_date"] else None
		r["expiry_date"] = str(r["expiry_date"]) if r["expiry_date"] else None
	return rows


@frappe.whitelist()
def create_vet_certificate(company: str, values=None):
	"""Create a Vet Certificate for a Commercial Invoice (status starts Pending)."""
	_assert_imports_access(company)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	ci = values.get("commercial_invoice")
	if not ci or not frappe.db.exists("Commercial Invoice", {"name": ci, "company": company}):
		frappe.throw(_("A valid commercial invoice for this company is required."))
	if not values.get("certificate_number"):
		frappe.throw(_("A certificate number is required."))
	doc = frappe.new_doc("Vet Certificate")
	doc.company = company
	doc.commercial_invoice = ci
	doc.certificate_number = values.get("certificate_number")
	doc.issuing_authority = values.get("issuing_authority")
	doc.issue_date = getdate(values["issue_date"]) if values.get("issue_date") else None
	doc.expiry_date = getdate(values["expiry_date"]) if values.get("expiry_date") else None
	doc.status = values.get("status") or "Pending"
	doc.notes = values.get("notes")
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def set_vet_certificate_status(name: str, status: str, reason: str | None = None):
	"""Approve / Reject / re-open a Vet Certificate (records the reviewer)."""
	if not name or not frappe.db.exists("Vet Certificate", name):
		frappe.throw(_("Unknown Vet Certificate: {0}").format(name))
	_assert_imports_access(_company_of("Vet Certificate", name))
	if status not in rules.VET_CERT_STATUSES:
		frappe.throw(_("Unknown veterinary certificate status: {0}").format(status))
	doc = frappe.get_doc("Vet Certificate", name)
	doc.status = status
	if status == "Rejected":
		if not reason:
			frappe.throw(_("A rejection reason is required."))
		doc.rejection_reason = reason
	doc.reviewed_by = frappe.session.user
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


# ===========================================================================
# WP6b — Import Container CRUD + status pipeline + cost-line include toggle
# ===========================================================================

_CONTAINER_HEADER_FIELDS = (
	"container_number",
	"commercial_invoice",
	"supplier",
	"currency",
	"container_type",
	"container_size",
	"bl_type",
	"seal_number",
	"gross_weight",
	"vgm",
	"total_boxes",
	"total_kg",
	"cut_off",
	"gate_open",
	"gate_close",
	"gate_in_date",
	"customs_clearance_date",
	"telex_release_date",
	"payment_70_status",
	"payment_70_date",
)
_CONTAINER_DATE_FIELDS = (
	"cut_off",
	"gate_open",
	"gate_close",
	"gate_in_date",
	"customs_clearance_date",
	"telex_release_date",
	"payment_70_date",
)
#: Import Container cost header fields — writable only by cost-visible users (PL1).
_CONTAINER_COST_HEADER_FIELDS = (
	"total_amount",
	"allocated_deposit_amount",
	"balance_due_amount",
	"payment_70_amount",
)


def _clean_container_items(items):
	if items in (None, ""):
		return []
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw(_("Invalid container items payload."))
	cleaned = []
	for idx, row in enumerate(items or [], start=1):
		item_code = (row or {}).get("item_code")
		if not item_code:
			continue
		if not frappe.db.exists("Item", item_code):
			frappe.throw(_("Row {0}: unknown item '{1}'.").format(idx, item_code))
		box_qty = cint(row.get("box_qty"))
		box_kg = flt(row.get("box_kg"))
		cleaned.append(
			{
				"item_code": item_code,
				"item_name": row.get("item_name")
				or frappe.db.get_value("Item", item_code, "item_name")
				or item_code,
				"category": row.get("category") or None,
				"box_qty": box_qty,
				"box_kg": box_kg,
				"total_kg": flt(row.get("total_kg")) or round(box_qty * box_kg, 3),
				"rate": flt(row.get("rate")),
				"amount": flt(row.get("amount")),
			}
		)
	return cleaned


def _clean_container_cost_lines(cost_lines):
	"""Validate cost-line rows.

	``lcv_ref`` and ``purchase_invoice`` are server-owned and never taken from the
	client: a browser must not be able to claim a line was already vouchered, nor
	to attach it to a bill that was never linked through the guarded API.
	"""
	if isinstance(cost_lines, str):
		try:
			cost_lines = json.loads(cost_lines)
		except Exception:
			frappe.throw(_("Invalid cost lines payload."))
	cleaned = []
	for row in cost_lines or []:
		component = (row or {}).get("cost_component")
		if not component:
			continue
		cleaned.append(
			{
				"cost_component": component,
				"description": row.get("description") or None,
				"currency": row.get("currency") or "USD",
				"amount": flt(row.get("amount")),
				"amount_uzs": flt(row.get("amount_uzs")),
				"include_in_landed_cost": 1 if cint(row.get("include_in_landed_cost")) else 0,
			}
		)
	return cleaned


def _apply_container_payload(doc, values: dict, items, cost_lines, cost_lines_provided: bool):
	for field in _CONTAINER_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _CONTAINER_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		elif field in ("total_boxes",):
			doc.set(field, cint(val))
		elif field in ("gross_weight", "vgm", "total_kg"):
			doc.set(field, flt(val))
		else:
			doc.set(field, val)
	# Cost header fields (PL1) — cost-visible users only.
	if _cost_visible():
		for field in _CONTAINER_COST_HEADER_FIELDS:
			if field in values and values[field] not in (None, ""):
				doc.set(field, flt(values[field]))

	visible = _cost_visible()
	cleaned_items = _clean_container_items(items)
	doc.set("items", [])
	for row in cleaned_items:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.item_name = row["item_name"]
		line.category = row["category"]
		line.box_qty = row["box_qty"]
		line.box_kg = row["box_kg"]
		line.total_kg = row["total_kg"]
		if visible:
			line.rate = row["rate"]
			line.amount = row["amount"]

	# Cost lines are landed-cost data: writing them REQUIRES cost visibility.
	if cost_lines_provided:
		_assert_cost_visible()
		# Both markers are server-owned and absent from the client payload, so the
		# rewrite below would wipe them: ``lcv_ref`` (this line was already
		# vouchered) and ``purchase_invoice`` (this line came from a carrier's
		# bill). Losing lcv_ref re-vouchers a consumed line; losing
		# purchase_invoice silently detaches the bill and lets the hand-typed
		# figure be capitalized alongside it — the double count this whole feature
		# exists to prevent. Matched on component+amount, queued rather than keyed
		# so two bills with identical component and amount each keep their OWN link
		# instead of collapsing onto one.
		existing_refs: dict[tuple, list] = {}
		for cl in doc.cost_lines or []:
			existing_refs.setdefault((cl.cost_component, flt(cl.amount)), []).append(
				(cl.lcv_ref, cl.get("purchase_invoice"))
			)
		doc.set("cost_lines", [])
		for row in _clean_container_cost_lines(cost_lines):
			line = doc.append("cost_lines", {})
			for key, value in row.items():
				line.set(key, value)
			queue = existing_refs.get((row["cost_component"], flt(row["amount"])))
			lcv_ref, purchase_invoice = queue.pop(0) if queue else (None, None)
			line.lcv_ref = lcv_ref
			line.purchase_invoice = purchase_invoice


@frappe.whitelist()
def create_import_container(company: str, values=None, items=None, cost_lines=None):
	"""Create an Import Container (status starts at BOOKED)."""
	_assert_imports_access(company)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	ci = values.get("commercial_invoice")
	if ci and not frappe.db.exists("Commercial Invoice", {"name": ci, "company": company}):
		frappe.throw(_("Unknown commercial invoice for this company: {0}").format(ci))
	doc = frappe.new_doc("Import Container")
	doc.company = company
	doc.status = "BOOKED"
	_apply_container_payload(doc, values, items, cost_lines, cost_lines is not None)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def update_import_container(name: str, values=None, items=None, cost_lines=None, modified: str | None = None):
	"""Update an Import Container header + items + cost lines (status unchanged)."""
	if not name or not frappe.db.exists("Import Container", name):
		frappe.throw(_("Unknown Import Container: {0}").format(name))
	company = _company_of("Import Container", name)
	_assert_imports_access(company)
	from stabler.api._common import check_concurrency

	check_concurrency("Import Container", name, modified)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	doc = frappe.get_doc("Import Container", name)
	_apply_container_payload(doc, values, items, cost_lines, cost_lines is not None)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def set_container_status(name: str, status: str, reason: str | None = None):
	"""Move an Import Container along its logistics pipeline (validate enforces)."""
	if not name or not frappe.db.exists("Import Container", name):
		frappe.throw(_("Unknown Import Container: {0}").format(name))
	_assert_imports_access(_company_of("Import Container", name))
	doc = frappe.get_doc("Import Container", name)
	if reason:
		doc.status_correction_reason = reason
	doc.status = status
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def toggle_cost_line_include(container: str, row_name: str, include=1):
	"""Flip ``include_in_landed_cost`` on one Container Cost Line (cost-visible only)."""
	if not container or not frappe.db.exists("Import Container", container):
		frappe.throw(_("Unknown Import Container: {0}").format(container))
	_assert_imports_access(_company_of("Import Container", container))
	_assert_cost_visible()
	doc = frappe.get_doc("Import Container", container)
	target = None
	for cl in doc.cost_lines or []:
		if cl.name == row_name:
			target = cl
			break
	if target is None:
		frappe.throw(_("Unknown cost line: {0}").format(row_name))
	if (target.lcv_ref or "").strip():
		frappe.throw(
			_("This cost line is already vouchered ({0}) and can no longer be toggled.").format(
				target.lcv_ref
			)
		)
	target.include_in_landed_cost = 1 if cint(include) else 0
	doc.save(ignore_permissions=False)
	return {
		"name": container,
		"row_name": row_name,
		"include_in_landed_cost": cint(target.include_in_landed_cost),
	}


# ===========================================================================
# WP6b — Import Truck CRUD + status pipeline
# ===========================================================================

_TRUCK_HEADER_FIELDS = (
	"truck_number",
	"commercial_invoice",
	"trucking_company",
	"driver_name",
	"driver_phone",
	"destination_warehouse",
	"departure_date",
	"border_crossing_date",
	"estimated_arrival",
	"actual_arrival",
	"target_temp_min",
	"target_temp_max",
	"total_boxes",
	"total_kg",
	"transport_currency",
	"transport_payment_status",
)
_TRUCK_DATE_FIELDS = ("departure_date", "border_crossing_date", "estimated_arrival", "actual_arrival")


def _apply_truck_payload(doc, values: dict):
	for field in _TRUCK_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _TRUCK_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		elif field in ("total_boxes",):
			doc.set(field, cint(val))
		elif field in ("target_temp_min", "target_temp_max", "total_kg"):
			doc.set(field, flt(val) if val not in (None, "") else None)
		else:
			doc.set(field, val)
	# Transport cost (PL1) — cost-visible users only.
	if _cost_visible() and "transport_cost" in values and values["transport_cost"] not in (None, ""):
		doc.set("transport_cost", flt(values["transport_cost"]))


@frappe.whitelist()
def create_import_truck(company: str, values=None):
	"""Create an Import Truck (status starts at PENDING)."""
	_assert_imports_access(company)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	ci = values.get("commercial_invoice")
	if ci and not frappe.db.exists("Commercial Invoice", {"name": ci, "company": company}):
		frappe.throw(_("Unknown commercial invoice for this company: {0}").format(ci))
	doc = frappe.new_doc("Import Truck")
	doc.company = company
	doc.status = "PENDING"
	_apply_truck_payload(doc, values)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def update_import_truck(name: str, values=None, modified: str | None = None):
	"""Update an Import Truck header (status unchanged)."""
	if not name or not frappe.db.exists("Import Truck", name):
		frappe.throw(_("Unknown Import Truck: {0}").format(name))
	_assert_imports_access(_company_of("Import Truck", name))
	from stabler.api._common import check_concurrency

	check_concurrency("Import Truck", name, modified)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	doc = frappe.get_doc("Import Truck", name)
	_apply_truck_payload(doc, values)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def set_truck_status(name: str, status: str, reason: str | None = None):
	"""Move an Import Truck along its road-leg pipeline (validate enforces)."""
	if not name or not frappe.db.exists("Import Truck", name):
		frappe.throw(_("Unknown Import Truck: {0}").format(name))
	_assert_imports_access(_company_of("Import Truck", name))
	doc = frappe.get_doc("Import Truck", name)
	if reason:
		doc.status_correction_reason = reason
	doc.status = status
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


# ===========================================================================
# WP6b — Customs Declarations (GTD)
# ===========================================================================

_CD_HEADER_FIELDS = (
	"gtd_number",
	"commercial_invoice",
	"container",
	"declaration_date",
	"customs_office",
	"cleared_date",
	"customs_value_usd",
	"customs_value_uzs",
	"duty_amount",
	"vat_amount",
	"excise_amount",
	"document",
	"notes",
)
_CD_DATE_FIELDS = ("declaration_date", "cleared_date")
_CD_MONEY_FIELDS = (
	"customs_value_usd",
	"customs_value_uzs",
	"duty_amount",
	"vat_amount",
	"excise_amount",
)


def _clean_cd_lines(lines):
	if isinstance(lines, str):
		try:
			lines = json.loads(lines)
		except Exception:
			frappe.throw(_("Invalid declaration lines payload."))
	cleaned = []
	for row in lines or []:
		item_code = (row or {}).get("item_code")
		if item_code and not frappe.db.exists("Item", item_code):
			frappe.throw(_("Unknown item on declaration line: {0}").format(item_code))
		cleaned.append(
			{
				"item_code": item_code or None,
				"description": row.get("description") or None,
				"hs_code": row.get("hs_code") or None,
				"country_of_origin": row.get("country_of_origin") or None,
				"gross_weight_kg": flt(row.get("gross_weight_kg")),
				"net_weight_kg": flt(row.get("net_weight_kg")),
				"box_qty": cint(row.get("box_qty")),
				"statistical_value_usd": flt(row.get("statistical_value_usd")),
				"duty_rate_pct": flt(row.get("duty_rate_pct")),
				"excise_rate_pct": flt(row.get("excise_rate_pct")),
				"vat_rate_pct": flt(row.get("vat_rate_pct")),
			}
		)
	return cleaned


def _apply_cd_payload(doc, values: dict, lines):
	for field in _CD_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _CD_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		elif field in _CD_MONEY_FIELDS:
			doc.set(field, flt(val))
		else:
			doc.set(field, val)
	if lines is not None:
		doc.set("lines", [])
		for row in _clean_cd_lines(lines):
			line = doc.append("lines", {})
			for key, value in row.items():
				line.set(key, value)


def _cd_next_statuses(status: str) -> list[str]:
	from stabler.stabler.doctype.customs_declaration.customs_declaration import _ALLOWED_TRANSITIONS

	return sorted(_ALLOWED_TRANSITIONS.get(status, set()))


@frappe.whitelist()
def list_customs_declarations(
	company: str,
	search: str | None = None,
	status: str | None = None,
	commercial_invoice: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Customs Declaration list rows (GTD no, CI, status, duties)."""
	_assert_imports_access(company)
	clauses, params = rules.customs_declaration_filter_clauses(search, status, commercial_invoice)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["cd.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT cd.name, cd.gtd_number, cd.commercial_invoice, cd.container,
               cd.declaration_date, cd.cleared_date, cd.customs_office, cd.status,
               cd.duty_amount, cd.vat_amount, cd.excise_amount, cd.total_duties,
               cd.customs_value_usd
        FROM `tabCustoms Declaration` cd
        WHERE {where}
        ORDER BY cd.creation DESC, cd.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		for f in ("declaration_date", "cleared_date"):
			r[f] = str(r[f]) if r[f] else None
	total = _count(rules.count_query("`tabCustoms Declaration` cd", where), params)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def get_customs_declaration(name: str):
	"""Full Customs Declaration payload: header + lines + allowed transitions."""
	if not name or not frappe.db.exists("Customs Declaration", name):
		frappe.throw(_("Unknown Customs Declaration: {0}").format(name))
	_assert_imports_access(_company_of("Customs Declaration", name))
	_assert_can_read("Customs Declaration", name)
	doc = frappe.get_doc("Customs Declaration", name)
	return {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"gtd_number": doc.gtd_number,
		"commercial_invoice": doc.commercial_invoice,
		"container": doc.container,
		"declaration_date": str(doc.declaration_date) if doc.declaration_date else None,
		"cleared_date": str(doc.cleared_date) if doc.cleared_date else None,
		"customs_office": doc.customs_office,
		"status": doc.status,
		"customs_value_usd": flt(doc.customs_value_usd),
		"customs_value_uzs": flt(doc.customs_value_uzs),
		"duty_amount": flt(doc.duty_amount),
		"vat_amount": flt(doc.vat_amount),
		"excise_amount": flt(doc.excise_amount),
		"total_duties": flt(doc.total_duties),
		"document": doc.document,
		"notes": doc.notes,
		"allowed_transitions": _cd_next_statuses(doc.status),
		"lines": [
			{
				"name": ln.name,
				"item_code": ln.item_code,
				"description": ln.description,
				"hs_code": ln.hs_code,
				"country_of_origin": ln.country_of_origin,
				"gross_weight_kg": flt(ln.gross_weight_kg),
				"net_weight_kg": flt(ln.net_weight_kg),
				"box_qty": cint(ln.box_qty),
				"statistical_value_usd": flt(ln.statistical_value_usd),
				"duty_rate_pct": flt(ln.duty_rate_pct),
				"excise_rate_pct": flt(ln.excise_rate_pct),
				"vat_rate_pct": flt(ln.vat_rate_pct),
			}
			for ln in (doc.lines or [])
		],
	}


@frappe.whitelist()
def create_customs_declaration(company: str, values=None, lines=None):
	"""Create a Customs Declaration (status starts at Draft)."""
	_assert_imports_access(company)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	ci = values.get("commercial_invoice")
	if ci and not frappe.db.exists("Commercial Invoice", {"name": ci, "company": company}):
		frappe.throw(_("Unknown commercial invoice for this company: {0}").format(ci))
	doc = frappe.new_doc("Customs Declaration")
	doc.company = company
	doc.status = "Draft"
	_apply_cd_payload(doc, values, lines)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def update_customs_declaration(name: str, values=None, lines=None, modified: str | None = None):
	"""Update a Customs Declaration header + lines (status via set_customs_declaration_status)."""
	if not name or not frappe.db.exists("Customs Declaration", name):
		frappe.throw(_("Unknown Customs Declaration: {0}").format(name))
	_assert_imports_access(_company_of("Customs Declaration", name))
	from stabler.api._common import check_concurrency

	check_concurrency("Customs Declaration", name, modified)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	doc = frappe.get_doc("Customs Declaration", name)
	_apply_cd_payload(doc, values, lines)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def set_customs_declaration_status(name: str, status: str, reason: str | None = None):
	"""Move a Customs Declaration along its clearance pipeline (validate enforces)."""
	if not name or not frappe.db.exists("Customs Declaration", name):
		frappe.throw(_("Unknown Customs Declaration: {0}").format(name))
	_assert_imports_access(_company_of("Customs Declaration", name))
	if status not in rules.CUSTOMS_DECLARATION_STATUSES:
		frappe.throw(_("Unknown customs declaration status: {0}").format(status))
	doc = frappe.get_doc("Customs Declaration", name)
	if reason:
		doc.status_correction_reason = reason
	doc.status = status
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


# ===========================================================================
# WP6b — Freight Bookings (cost split masked per K3)
# ===========================================================================

_FB_HEADER_FIELDS = (
	"transporter",
	"commercial_invoice",
	"container",
	"booking_date",
	"booking_reference",
	"pickup_date",
	"pickup_location",
	"delivery_date",
	"delivery_location",
	"route",
	"vehicle_number",
	"driver_name",
	"driver_phone",
	"currency",
)
_FB_DATE_FIELDS = ("booking_date", "pickup_date", "delivery_date")
_FB_COST_FIELDS = ("amount", "bank_payment", "cash_payment")


def _fb_next_statuses(status: str) -> list[str]:
	from stabler.stabler.doctype.freight_booking.freight_booking import _ALLOWED_TRANSITIONS

	return sorted(_ALLOWED_TRANSITIONS.get(status, set()))


def _apply_fb_payload(doc, values: dict):
	for field in _FB_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _FB_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		else:
			doc.set(field, val)
	# Amount + payment split (PL1) — cost-visible users only.
	if any(f in values for f in _FB_COST_FIELDS):
		_assert_cost_visible()
		for field in _FB_COST_FIELDS:
			if field in values and values[field] not in (None, ""):
				doc.set(field, flt(values[field]))


@frappe.whitelist()
def list_freight_bookings(
	company: str,
	search: str | None = None,
	status: str | None = None,
	commercial_invoice: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Freight Booking list rows (amount masked for non-cost users)."""
	_assert_imports_access(company)
	clauses, params = rules.freight_booking_filter_clauses(search, status, commercial_invoice)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["fb.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT fb.name, fb.transporter, fb.commercial_invoice, fb.container,
               fb.booking_date, fb.booking_reference, fb.status,
               fb.pickup_location, fb.delivery_location, fb.delivery_date,
               fb.vehicle_number, fb.amount, fb.currency
        FROM `tabFreight Booking` fb
        WHERE {where}
        ORDER BY fb.creation DESC, fb.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		for f in ("booking_date", "delivery_date"):
			r[f] = str(r[f]) if r[f] else None
	rules.mask_named(rows, ("amount",), _cost_visible())
	total = _count(rules.count_query("`tabFreight Booking` fb", where), params)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def get_freight_booking(name: str):
	"""Full Freight Booking payload (amount + payment split masked per K3)."""
	if not name or not frappe.db.exists("Freight Booking", name):
		frappe.throw(_("Unknown Freight Booking: {0}").format(name))
	_assert_imports_access(_company_of("Freight Booking", name))
	_assert_can_read("Freight Booking", name)
	doc = frappe.get_doc("Freight Booking", name)
	payload = {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"transporter": doc.transporter,
		"commercial_invoice": doc.commercial_invoice,
		"container": doc.container,
		"booking_date": str(doc.booking_date) if doc.booking_date else None,
		"booking_reference": doc.booking_reference,
		"status": doc.status,
		"pickup_date": str(doc.pickup_date) if doc.pickup_date else None,
		"pickup_location": doc.pickup_location,
		"delivery_date": str(doc.delivery_date) if doc.delivery_date else None,
		"delivery_location": doc.delivery_location,
		"route": doc.route,
		"vehicle_number": doc.vehicle_number,
		"driver_name": doc.driver_name,
		"driver_phone": doc.driver_phone,
		"amount": flt(doc.amount),
		"currency": doc.currency,
		"bank_payment": flt(doc.bank_payment),
		"cash_payment": flt(doc.cash_payment),
		"allowed_transitions": _fb_next_statuses(doc.status),
	}
	rules.mask_named(payload, rules.FREIGHT_MASK_FIELDS, _cost_visible())
	return payload


@frappe.whitelist()
def create_freight_booking(company: str, values=None):
	"""Create a Freight Booking (status starts at Pending; XOR CI/container enforced)."""
	_assert_imports_access(company)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	doc = frappe.new_doc("Freight Booking")
	doc.company = company
	doc.status = "Pending"
	_apply_fb_payload(doc, values)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def update_freight_booking(name: str, values=None, modified: str | None = None):
	"""Update a Freight Booking header (status via set_freight_booking_status)."""
	if not name or not frappe.db.exists("Freight Booking", name):
		frappe.throw(_("Unknown Freight Booking: {0}").format(name))
	_assert_imports_access(_company_of("Freight Booking", name))
	from stabler.api._common import check_concurrency

	check_concurrency("Freight Booking", name, modified)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	doc = frappe.get_doc("Freight Booking", name)
	_apply_fb_payload(doc, values)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def set_freight_booking_status(name: str, status: str, reason: str | None = None):
	"""Move a Freight Booking along its pipeline (validate enforces)."""
	if not name or not frappe.db.exists("Freight Booking", name):
		frappe.throw(_("Unknown Freight Booking: {0}").format(name))
	_assert_imports_access(_company_of("Freight Booking", name))
	if status not in rules.FREIGHT_BOOKING_STATUSES:
		frappe.throw(_("Unknown freight booking status: {0}").format(status))
	doc = frappe.get_doc("Freight Booking", name)
	if reason:
		doc.status_correction_reason = reason
	doc.status = status
	doc.save(ignore_permissions=False)
	return {"name": doc.name, "status": doc.status}


# ===========================================================================
# WP6b — Import Expenses (bank/cash split masked per K3)
# ===========================================================================

_IE_HEADER_FIELDS = (
	"commercial_invoice",
	"container",
	"truck",
	"category",
	"expense_date",
	"supplier",
	"invoice_reference",
	"description",
	"amount",
	"currency",
)
_IE_DATE_FIELDS = ("expense_date",)
#: Cash-desk fields. Writing them means "this expense leaves a real kassa", so
#: they carry the same cost-visibility gate as the bank/cash split.
_IE_KASA_FIELDS = ("expense_account", "paid_from_account")


def _apply_ie_payload(doc, values: dict):
	for field in _IE_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _IE_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		elif field == "amount":
			doc.set(field, flt(val))
		else:
			doc.set(field, val)
	# Bank / cash split (PL1) — cost-visible users only.
	if any(f in values for f in ("bank_payment", "cash_payment")):
		_assert_cost_visible()
		for field in ("bank_payment", "cash_payment"):
			if field in values and values[field] not in (None, ""):
				doc.set(field, flt(values[field]))
	# Cash-desk (kassa) pair — cost-visible users only.
	if any(f in values for f in _IE_KASA_FIELDS):
		_assert_cost_visible()
		for field in _IE_KASA_FIELDS:
			if field in values:
				doc.set(field, values[field] or None)


def _assert_ie_payment_route(doc) -> None:
	"""One expense, one settlement route.

	A supplier means the expense is billed — ``imports_module.hooks`` opens a draft
	service Purchase Invoice for it. A cash desk means the money leaves a kassa now.
	Accepting both would debit the same cost twice, so the pair is rejected here
	instead of being left to whoever reconciles the ledger later.
	"""
	kasa = doc.get("paid_from_account")
	if not kasa:
		if doc.get("expense_account"):
			frappe.throw(_("Select the cash desk this expense is paid from, or clear the expense account."))
		return
	if doc.get("supplier"):
		frappe.throw(
			_(
				"An expense is either billed to a supplier or paid from a cash desk, not both. "
				"Clear the supplier to pay this expense in cash."
			)
		)
	if not doc.get("expense_account"):
		frappe.throw(_("Select the expense account to debit for the cash-desk payment."))
	kasa_currency = frappe.db.get_value("Account", kasa, "account_currency")
	if doc.get("currency") and kasa_currency and doc.currency != kasa_currency:
		# money.submit_expense_entry throws on this too; catching it here keeps the
		# error on the field the user can actually fix.
		frappe.throw(
			_("Expense currency ({0}) must match the cash desk currency ({1}).").format(
				doc.currency, kasa_currency
			)
		)


def _post_expense_kasa_entry(doc) -> dict:
	"""Post the real Bank Entry behind a cash-desk-paid Import Expense.

	Returns the money-layer result (it carries ``pending_approval``) or ``{}`` when
	the expense is not a cash payment. ``journal_entry`` doubles as the idempotency
	key: a second save never posts a second voucher.
	"""
	if doc.get("journal_entry") or not doc.get("paid_from_account"):
		return {}
	amount = flt(doc.amount)
	if amount <= 0:
		return {}
	_assert_cost_visible()

	from stabler.api.money import submit_expense_entry
	from stabler.stabler.imports_module import payment_math as pm

	posting_date = str(doc.expense_date or today())
	base_currency = frappe.db.get_value("Company", doc.company, "default_currency")
	kasa_currency = frappe.db.get_value("Account", doc.paid_from_account, "account_currency")
	rate = 1.0
	if kasa_currency and base_currency and kasa_currency != base_currency:
		rate = flt(_latest_exchange_rate(kasa_currency, base_currency, posting_date)[0])
		if rate <= 0 or rate == 1.0:
			# _latest_exchange_rate falls back to 1.0 when it finds nothing, which for
			# two different currencies means "no rate", not "parity".
			frappe.throw(
				_(
					"No exchange rate found for {0} to {1} on {2}. Add one before paying from this cash desk."
				).format(kasa_currency, base_currency, posting_date)
			)

	res = (
		submit_expense_entry(
			company=doc.company,
			posting_date=posting_date,
			payment_from=doc.paid_from_account,
			lines=[
				{
					"account": doc.expense_account,
					"amount": amount,
					"memo": doc.get("description") or doc.name,
				}
			],
			exchange_rate=rate,
			commercial_invoice=doc.get("commercial_invoice"),
			import_container=doc.get("container"),
			import_truck=doc.get("truck"),
			import_category=doc.get("category"),
			# Back-link: this voucher belongs to an Import Expense that already
			# exists, so the JE on_submit hook must not mirror a second one.
			import_expense=doc.name,
		)
		or {}
	)
	journal_entry = res.get("name")
	if not journal_entry:
		return res

	updates = {"journal_entry": journal_entry}
	if not res.get("pending_approval"):
		# Only a submitted voucher means the money actually left the desk; an entry
		# waiting for approval leaves the expense Pending on purpose.
		account_type = frappe.db.get_value("Account", doc.paid_from_account, "account_type")
		is_cash = account_type == "Cash"
		updates["cash_payment"] = amount if is_cash else 0.0
		updates["bank_payment"] = 0.0 if is_cash else amount
		updates["status"] = pm.expense_status(amount, updates["bank_payment"], updates["cash_payment"])
	# db_set, not save(): bank/cash are permlevel-1 on a doctype that carries no
	# permlevel-1 permission row, so a normal save would reset them; and `status`
	# is only derived inside validate(), which has already run.
	doc.db_set(updates)
	return res


def _ie_result(doc, posted: dict) -> dict:
	"""Save response — the caller has to know whether a voucher was actually posted."""
	out = {"name": doc.name, "status": doc.status}
	if doc.get("journal_entry"):
		out["journal_entry"] = doc.journal_entry
	if posted.get("pending_approval"):
		out["pending_approval"] = True
		out["approval_request"] = posted.get("approval_request")
	return out


@frappe.whitelist()
def list_import_expenses(
	company: str,
	search: str | None = None,
	category: str | None = None,
	status: str | None = None,
	commercial_invoice: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Import Expense list rows (bank/cash split masked for non-cost users)."""
	_assert_imports_access(company)
	clauses, params = rules.import_expense_filter_clauses(search, category, status, commercial_invoice)
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["ie.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT ie.name, ie.commercial_invoice, ie.container, ie.truck, ie.category,
               ie.expense_date, ie.supplier, ie.invoice_reference, ie.description,
               ie.amount, ie.currency, ie.bank_payment, ie.cash_payment, ie.status,
               ie.purchase_invoice, ie.expense_account, ie.paid_from_account,
               ie.journal_entry, ie.include_in_landed_cost, ie.cost_component
        FROM `tabImport Expense` ie
        WHERE {where}
        ORDER BY ie.creation DESC, ie.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		r["expense_date"] = str(r["expense_date"]) if r["expense_date"] else None
	rules.mask_named(rows, rules.EXPENSE_MASK_FIELDS, _cost_visible())
	total = _count(rules.count_query("`tabImport Expense` ie", where), params)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def ci_transport_costs(commercial_invoice: str) -> dict:
	"""Transport cost allocation across containers, vendor totals, and landed cost for a CI."""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))

	ci_doc = frappe.get_doc("Commercial Invoice", commercial_invoice)
	_assert_imports_access(ci_doc.company)
	_assert_can_read("Commercial Invoice", commercial_invoice)

	expenses = frappe.db.sql(
		"""
        SELECT ie.name, ie.commercial_invoice, ie.container, ie.truck, ie.category,
               ie.expense_date, ie.supplier, s.supplier_name, ie.invoice_reference,
               ie.description, ie.amount, ie.currency, ie.bank_payment, ie.cash_payment,
               ie.status, ie.purchase_invoice
        FROM `tabImport Expense` ie
        LEFT JOIN `tabSupplier` s ON s.name = ie.supplier
        WHERE ie.commercial_invoice = %(ci)s
        ORDER BY ie.creation DESC, ie.name DESC
        """,
		{"ci": commercial_invoice},
		as_dict=True,
	)
	for r in expenses:
		r["expense_date"] = str(r["expense_date"]) if r.get("expense_date") else None
		r["amount"] = flt(r.get("amount"))
		if r.get("bank_payment") is not None:
			r["bank_payment"] = flt(r["bank_payment"])
		if r.get("cash_payment") is not None:
			r["cash_payment"] = flt(r["cash_payment"])

	rules.mask_named(expenses, rules.EXPENSE_MASK_FIELDS, _cost_visible())

	containers = frappe.db.sql(
		"""
        SELECT c.name, c.total_kg
        FROM `tabImport Container` c
        WHERE c.commercial_invoice = %(ci)s
        ORDER BY c.creation ASC
        """,
		{"ci": commercial_invoice},
		as_dict=True,
	)
	for c in containers:
		c["total_kg"] = flt(c.get("total_kg"))

	return rules.calculate_ci_transport_costs(
		raw_expenses=expenses,
		containers=containers,
		ci_total_kg=flt(ci_doc.total_kg),
		ci_agreed_total=flt(ci_doc.agreed_total),
		currency=ci_doc.currency or "USD",
	)


# ---------------------------------------------------------------------------
# Transport Purchase Invoices (Linked to CI and Landed Cost)
# ---------------------------------------------------------------------------


def _get_ci_transport_invoices(ci_doc) -> dict:
	"""Fetch all Purchase Invoices linked to this Commercial Invoice.

	Returns invoice list, aggregated totals, and per-kg transport rate.
	"""
	from stabler.stabler.imports_module import hooks as imports_hooks

	company = ci_doc.company
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "UZS"
	configured_lcv_account = imports_hooks.resolve_lcv_expense_account(company)

	invoices = frappe.db.sql(
		"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.posting_date, pi.bill_no,
               pi.grand_total, pi.outstanding_amount, pi.currency, pi.conversion_rate, pi.status, pi.docstatus,
               pi.custom_import_truck,
               (SELECT pii.expense_account FROM `tabPurchase Invoice Item` pii WHERE pii.parent = pi.name LIMIT 1) as expense_account,
               (SELECT pii.item_code FROM `tabPurchase Invoice Item` pii WHERE pii.parent = pi.name LIMIT 1) as item_code
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.custom_commercial_invoice = %(ci)s AND pi.docstatus < 2
        ORDER BY pi.posting_date DESC, pi.creation DESC
        """,
		{"ci": ci_doc.name},
		as_dict=True,
	)

	total_usd = 0.0
	total_company_currency = 0.0
	total_kg = flt(ci_doc.total_kg)

	rows = []
	for inv in invoices:
		amt = flt(inv.get("grand_total"))
		curr = inv.get("currency") or "USD"
		exp_acc = inv.get("expense_account") or ""

		# Check if expense account routes to Balance Sheet (Landed Cost / Valuation Clearing)
		is_landed_cost = False
		if exp_acc:
			if exp_acc == configured_lcv_account:
				is_landed_cost = True
			else:
				acc_type = frappe.db.get_value("Account", exp_acc, "account_type")
				if acc_type == "Expenses Included In Valuation":
					is_landed_cost = True

		rate = flt(inv.get("conversion_rate"))
		if curr != company_currency and (not rate or rate <= 1.0):
			try:
				from stabler.api._accounts import _cbu_rate_on_or_before

				cbu_rate, _ = _cbu_rate_on_or_before(
					curr, company_currency, inv.get("posting_date") or ci_doc.ci_date or today()
				)
				if cbu_rate:
					rate = flt(cbu_rate)
				else:
					rate_val, _, _ = _ci_landed_cost_rate(ci_doc)
					rate = rate_val or 1.0
			except Exception:
				rate_val, _, _ = _ci_landed_cost_rate(ci_doc)
				rate = rate_val or 1.0
		elif curr == company_currency:
			rate = 1.0

		amt_company = amt * rate if curr != company_currency else amt
		if curr == "USD":
			total_usd += amt
		elif company_currency == "USD":
			total_usd += amt_company
		else:
			total_usd += (amt / rate) if rate > 0 else amt

		total_company_currency += amt_company

		rows.append(
			{
				"name": inv.get("name"),
				"supplier": inv.get("supplier"),
				"supplier_name": inv.get("supplier_name") or inv.get("supplier"),
				"bill_no": inv.get("bill_no"),
				"posting_date": str(inv.get("posting_date")) if inv.get("posting_date") else None,
				"grand_total": amt,
				"outstanding_amount": flt(inv.get("outstanding_amount")),
				"currency": curr,
				"status": inv.get("status"),
				"docstatus": cint(inv.get("docstatus")),
				"custom_import_truck": inv.get("custom_import_truck"),
				"expense_account": exp_acc,
				"is_landed_cost_account": is_landed_cost,
				"item_code": inv.get("item_code"),
			}
		)

	rate_per_kg_usd = round(total_usd / total_kg, 4) if total_kg > 0 else 0.0
	rate_per_kg_company = round(total_company_currency / total_kg, 2) if total_kg > 0 else 0.0

	return {
		"invoices": rows,
		"invoice_count": len(rows),
		"total_usd": round(total_usd, 2),
		"total_company_currency": round(total_company_currency, 2),
		"company_currency": company_currency,
		"rate_per_kg_usd": rate_per_kg_usd,
		"rate_per_kg_company": rate_per_kg_company,
		"total_kg": total_kg,
	}


@frappe.whitelist()
def get_ci_transport_invoices(commercial_invoice: str) -> dict:
	"""Public endpoint to get all linked transport invoices and metrics for a CI."""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	_assert_imports_access(ci.company)
	_assert_can_read("Commercial Invoice", commercial_invoice)
	return _get_ci_transport_invoices(ci)


@frappe.whitelist()
def list_linkable_transport_invoices(
	company: str,
	commercial_invoice: str | None = None,
	search: str | None = None,
	limit_page_length: int = 50,
) -> list[dict]:
	"""List Purchase Invoices eligible to be linked to a Commercial Invoice as transport bills.

	Includes unlinked invoices and invoices currently linked to ``commercial_invoice``.
	"""
	if not company:
		frappe.throw(_("Company is required"))
	_assert_imports_access(company)
	_assert_cost_visible()

	from stabler.stabler.imports_module import hooks as imports_hooks

	configured_lcv_account = imports_hooks.resolve_lcv_expense_account(company)

	conditions = ["pi.company = %(company)s", "pi.docstatus < 2"]
	params = {"company": company, "limit": min(100, max(1, cint(limit_page_length)))}

	if commercial_invoice:
		conditions.append(
			"(pi.custom_commercial_invoice IS NULL OR pi.custom_commercial_invoice = '' OR pi.custom_commercial_invoice = %(ci)s)"
		)
		params["ci"] = commercial_invoice
	else:
		conditions.append("(pi.custom_commercial_invoice IS NULL OR pi.custom_commercial_invoice = '')")

	if search and search.strip():
		conditions.append(
			"(pi.name LIKE %(search)s OR pi.bill_no LIKE %(search)s OR pi.supplier LIKE %(search)s OR s.supplier_name LIKE %(search)s)"
		)
		params["search"] = f"%{search.strip()}%"

	where_clause = " AND ".join(conditions)

	invoices = frappe.db.sql(
		f"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.posting_date, pi.bill_no,
               pi.grand_total, pi.outstanding_amount, pi.currency, pi.status, pi.docstatus,
               pi.custom_commercial_invoice, pi.custom_import_truck,
               (SELECT pii.expense_account FROM `tabPurchase Invoice Item` pii WHERE pii.parent = pi.name LIMIT 1) as expense_account,
               (SELECT pii.item_code FROM `tabPurchase Invoice Item` pii WHERE pii.parent = pi.name LIMIT 1) as item_code
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE {where_clause}
        ORDER BY (CASE WHEN pi.custom_commercial_invoice = %(ci_sort)s THEN 0 ELSE 1 END), pi.posting_date DESC, pi.creation DESC
        LIMIT %(limit)s
        """,
		{**params, "ci_sort": commercial_invoice or ""},
		as_dict=True,
	)

	out = []
	for inv in invoices:
		exp_acc = inv.get("expense_account") or ""
		is_landed_cost = False
		if exp_acc:
			if exp_acc == configured_lcv_account:
				is_landed_cost = True
			else:
				acc_type = frappe.db.get_value("Account", exp_acc, "account_type")
				if acc_type == "Expenses Included In Valuation":
					is_landed_cost = True

		out.append(
			{
				"name": inv.get("name"),
				"supplier": inv.get("supplier"),
				"supplier_name": inv.get("supplier_name") or inv.get("supplier"),
				"bill_no": inv.get("bill_no"),
				"posting_date": str(inv.get("posting_date")) if inv.get("posting_date") else None,
				"grand_total": flt(inv.get("grand_total")),
				"outstanding_amount": flt(inv.get("outstanding_amount")),
				"currency": inv.get("currency") or "USD",
				"status": inv.get("status"),
				"docstatus": cint(inv.get("docstatus")),
				"custom_commercial_invoice": inv.get("custom_commercial_invoice"),
				"is_linked": bool(
					commercial_invoice and inv.get("custom_commercial_invoice") == commercial_invoice
				),
				"custom_import_truck": inv.get("custom_import_truck"),
				"expense_account": exp_acc,
				"is_landed_cost_account": is_landed_cost,
				"item_code": inv.get("item_code"),
			}
		)
	return out


@frappe.whitelist()
def link_transport_purchase_invoice(commercial_invoice: str, purchase_invoice: str) -> dict:
	"""Link a Purchase Invoice to a Commercial Invoice as a transport bill.

	Ensures the invoice belongs to the same company and sets the Landed Cost clearing account if draft.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))

	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	_assert_imports_access(ci.company)
	_assert_can_write("Commercial Invoice", commercial_invoice)
	_assert_cost_visible()

	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if pi.company != ci.company:
		frappe.throw(
			_("Purchase Invoice company ({0}) does not match Commercial Invoice company ({1})").format(
				pi.company, ci.company
			)
		)
	if pi.docstatus == 2:
		frappe.throw(_("Cannot link a cancelled Purchase Invoice."))

	from stabler.stabler.imports_module import hooks as imports_hooks

	lcv_account = imports_hooks.resolve_lcv_expense_account(ci.company)

	if pi.docstatus == 0 and lcv_account:
		for itm in pi.items:
			if itm.expense_account != lcv_account:
				itm.expense_account = lcv_account
		pi.custom_commercial_invoice = commercial_invoice
		pi.save(ignore_permissions=True)
	else:
		frappe.db.set_value(
			"Purchase Invoice", purchase_invoice, "custom_commercial_invoice", commercial_invoice
		)

	return {"success": True, "commercial_invoice": commercial_invoice, "purchase_invoice": purchase_invoice}


@frappe.whitelist()
def unlink_transport_purchase_invoice(commercial_invoice: str, purchase_invoice: str) -> dict:
	"""Unlink a Purchase Invoice from a Commercial Invoice."""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))

	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	_assert_imports_access(ci.company)
	_assert_can_write("Commercial Invoice", commercial_invoice)

	current_ci = frappe.db.get_value("Purchase Invoice", purchase_invoice, "custom_commercial_invoice")
	if current_ci == commercial_invoice:
		frappe.db.set_value("Purchase Invoice", purchase_invoice, "custom_commercial_invoice", None)

	return {"success": True, "purchase_invoice": purchase_invoice}


@frappe.whitelist()
def create_transport_purchase_invoice(
	commercial_invoice: str,
	supplier: str,
	amount: float,
	currency: str = "USD",
	bill_no: str | None = None,
	posting_date: str | None = None,
) -> dict:
	"""Create a new DRAFT Transport Purchase Invoice linked to Commercial Invoice.

	Uses the Landed Cost clearing expense account (Balance Sheet) by default.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Unknown Supplier: {0}").format(supplier))

	amt = flt(amount)
	if amt <= 0:
		frappe.throw(_("Amount must be greater than 0"))

	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	_assert_imports_access(ci.company)
	_assert_can_write("Commercial Invoice", commercial_invoice)
	_assert_cost_visible()

	from stabler.stabler.imports_module import hooks as imports_hooks
	from stabler.stabler.imports_module import payment_math as pm

	imports_hooks._ensure_import_service_item()
	lcv_account = imports_hooks.resolve_lcv_expense_account(ci.company)

	item_code = (
		pm.XBORDER_ITEM_CODE
		if frappe.db.exists("Item", pm.XBORDER_ITEM_CODE)
		else pm.IMPORT_SERVICE_ITEM_CODE
	)
	if not frappe.db.exists("Item", item_code):
		imports_hooks._ensure_import_service_item()
		item_code = pm.IMPORT_SERVICE_ITEM_CODE

	ref_bill_no = (
		bill_no.strip()
		if (bill_no and bill_no.strip())
		else f"TRK-{frappe.utils.today()}-{frappe.generate_hash(length=4).upper()}"
	)

	curr = currency or ci.currency or "USD"
	company_currency = frappe.get_cached_value("Company", ci.company, "default_currency") or "UZS"
	conversion_rate = 1.0
	if curr != company_currency:
		from stabler.api._accounts import _cbu_rate_on_or_before

		post_d = posting_date or frappe.utils.today()
		cbu_rate, _ = _cbu_rate_on_or_before(curr, company_currency, post_d)
		if not cbu_rate:
			rate_val, _, _ = _ci_landed_cost_rate(ci)
			cbu_rate = rate_val
		conversion_rate = flt(cbu_rate) or 1.0

	payload = {
		"doctype": "Purchase Invoice",
		"company": ci.company,
		"supplier": supplier,
		"currency": curr,
		"conversion_rate": conversion_rate,
		"bill_no": ref_bill_no,
		"posting_date": posting_date or frappe.utils.today(),
		"custom_commercial_invoice": commercial_invoice,
		"remarks": f"Transport invoice for Commercial Invoice {ci.ci_number or commercial_invoice}",
		"items": [
			{
				"item_code": item_code,
				"qty": 1,
				"rate": amt,
				"amount": amt,
				"expense_account": lcv_account,
				"description": f"Cross-border transport for {ci.ci_number or commercial_invoice}",
			}
		],
	}

	pi = frappe.get_doc(payload)
	pi.insert(ignore_permissions=True)

	return {
		"name": pi.name,
		"bill_no": pi.bill_no,
		"supplier": pi.supplier,
		"amount": pi.grand_total,
		"currency": pi.currency,
	}


def _ci_landed_cost_rate(ci_doc, exchange_rate=None) -> tuple:
	"""Resolve the rate that converts CI currency into company currency.

	Returns ``(rate, source, rate_date)``. ``rate`` is None when no rate can be
	established — the caller must then report "no rate" rather than invent one.
	The old code defaulted to a hardcoded 12800 here, which made every landed
	cost figure on the screen look like a real amount while being derived from a
	number that came from nowhere. Same decision as ``reports.py:2420``.

	No currency name is hardcoded: the pair is the CI's own currency against the
	company's default currency, so this works for a UZS-book and a USD-book
	tenant alike.
	"""
	manual = flt(exchange_rate)
	if manual > 0:
		return manual, "manual", None

	doc_currency = ci_doc.currency or "USD"
	company_currency = frappe.get_cached_value("Company", ci_doc.company, "default_currency")
	if not company_currency:
		return None, "missing", None
	if doc_currency == company_currency:
		return 1.0, "same_currency", None

	rate, rate_date = _cbu_rate_on_or_before(doc_currency, company_currency, ci_doc.ci_date or today())
	if not rate:
		return None, "missing", None
	return flt(rate), "cbu", str(rate_date) if rate_date else None


@frappe.whitelist()
def calculate_ci_landed_cost_uzs(
	commercial_invoice: str, exchange_rate: float | None = None, allocation_method: str = "By Weight"
) -> dict:
	"""Calculate company-currency Landed Cost allocation per CI product line.

	The ``_uzs`` suffixes are kept for API compatibility; the actual currency is
	the company's default currency. When no exchange rate can be resolved the
	response carries ``exchange_rate: None`` and an empty ``items`` list — every
	figure below depends on the rate, so a fabricated rate would poison all of
	them.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))

	ci_doc = frappe.get_doc("Commercial Invoice", commercial_invoice)
	_assert_imports_access(ci_doc.company)
	_assert_can_read("Commercial Invoice", commercial_invoice)

	rate, rate_source, rate_date = _ci_landed_cost_rate(ci_doc, exchange_rate)
	if rate is None:
		return {
			"commercial_invoice": commercial_invoice,
			"exchange_rate": None,
			"rate_source": rate_source,
			"rate_date": None,
			"allocation_method": allocation_method,
			"total_extra_uzs": None,
			"total_landed_uzs": None,
			"items": [],
		}

	ci_items = ci_doc.items or []

	total_weight_kg = flt(ci_doc.total_kg) or sum(flt(it.qty) for it in ci_items) or 1.0
	total_boxes = cint(ci_doc.total_boxes) or sum(cint(it.boxes) for it in ci_items) or 1
	total_agreed_usd = flt(ci_doc.agreed_total) or sum(flt(it.amount) for it in ci_items) or 1.0

	try:
		overview = ci_cost_overview(commercial_invoice)
		operational_transport_usd = flt(overview.get("operational", {}).get("transport", 0))
		operational_duties_uzs = flt(overview.get("operational", {}).get("duties", 0))
		other_expenses_uzs = flt(overview.get("operational", {}).get("other", 0))
	except Exception:
		operational_transport_usd = 0.0
		operational_duties_uzs = 0.0
		other_expenses_uzs = 0.0

	transport_invoices = _get_ci_transport_invoices(ci_doc)
	direct_transport_company = flt(transport_invoices.get("total_company_currency", 0.0))
	direct_transport_usd = flt(transport_invoices.get("total_usd", 0.0))

	if direct_transport_company > 0 and operational_transport_usd == 0:
		transport_extra_company = direct_transport_company
	else:
		total_trans_usd = max(operational_transport_usd, direct_transport_usd)
		transport_extra_company = total_trans_usd * rate

	total_extra_uzs = transport_extra_company + operational_duties_uzs + other_expenses_uzs

	items_result = []
	for it in ci_items:
		item_qty_kg = flt(it.qty) or (flt(it.boxes) * flt(it.box_weight_kg)) or 1.0
		item_boxes = cint(it.boxes) or 1
		item_amount_usd = flt(it.amount)
		item_rate_usd = flt(it.rate)
		item_base_uzs = item_rate_usd * rate

		if allocation_method == "By Value":
			factor = item_amount_usd / total_agreed_usd if total_agreed_usd else 0
		elif allocation_method == "By Quantity":
			factor = item_boxes / total_boxes if total_boxes else 0
		elif allocation_method == "Equal":
			factor = 1.0 / len(ci_items) if ci_items else 0
		else:  # Default "By Weight"
			factor = item_qty_kg / total_weight_kg if total_weight_kg else 0

		allocated_extra_uzs = total_extra_uzs * factor
		allocated_extra_per_kg_uzs = allocated_extra_uzs / item_qty_kg if item_qty_kg else 0

		final_landed_rate_per_kg_uzs = item_base_uzs + allocated_extra_per_kg_uzs
		line_total_landed_uzs = final_landed_rate_per_kg_uzs * item_qty_kg

		items_result.append(
			{
				"item": it.item,
				"description": it.description or it.item,
				"category": it.category,
				"boxes": item_boxes,
				"qty_kg": item_qty_kg,
				"rate_usd": item_rate_usd,
				"amount_usd": item_amount_usd,
				"base_rate_uzs": item_base_uzs,
				"allocated_extra_uzs": allocated_extra_uzs,
				"allocated_extra_per_kg_uzs": allocated_extra_per_kg_uzs,
				"final_landed_rate_per_kg_uzs": final_landed_rate_per_kg_uzs,
				"line_total_landed_uzs": line_total_landed_uzs,
			}
		)

	return {
		"commercial_invoice": commercial_invoice,
		"exchange_rate": rate,
		"rate_source": rate_source,
		"rate_date": rate_date,
		"allocation_method": allocation_method,
		"total_extra_uzs": total_extra_uzs,
		"total_landed_uzs": (total_agreed_usd * rate) + total_extra_uzs,
		"items": items_result,
	}


@frappe.whitelist()
def ci_cost_overview(commercial_invoice: str) -> dict:
	"""Single-source overview endpoint for Blocks 5 & 6 of CI Form v4."""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))

	ci_doc = frappe.get_doc("Commercial Invoice", commercial_invoice)
	company = ci_doc.company
	_assert_imports_access(company)
	_assert_can_read("Commercial Invoice", commercial_invoice)
	cost_visible = _cost_visible()

	containers = frappe.db.sql(
		"""
        SELECT c.name, c.total_kg, c.total_boxes, c.status
        FROM `tabImport Container` c
        WHERE c.commercial_invoice = %(ci)s
        ORDER BY c.creation ASC
        """,
		{"ci": commercial_invoice},
		as_dict=True,
	)
	for c in containers:
		c["total_kg"] = flt(c.get("total_kg"))
		c["total_boxes"] = cint(c.get("total_boxes"))

	container_names = [c["name"] for c in containers]
	trucks = frappe.get_all("Import Truck", filters={"commercial_invoice": commercial_invoice}, pluck="name")

	# Fetch expenses matching CI, container list, or truck list
	where_clause = ["ie.commercial_invoice = %(ci)s"]
	params: dict = {"ci": commercial_invoice, "company": company}

	if container_names:
		cnt_placeholders = [f"%(cnt_{i})s" for i in range(len(container_names))]
		for i, name in enumerate(container_names):
			params[f"cnt_{i}"] = name
		where_clause.append(f"ie.container IN ({', '.join(cnt_placeholders)})")

	if trucks:
		trk_placeholders = [f"%(trk_{i})s" for i in range(len(trucks))]
		for i, trk in enumerate(trucks):
			params[f"trk_{i}"] = trk
		where_clause.append(f"ie.truck IN ({', '.join(trk_placeholders)})")

	expenses = frappe.db.sql(
		f"""
        SELECT ie.name, ie.commercial_invoice, ie.container, ie.truck, ie.category,
               ie.expense_date, ie.supplier, s.supplier_name, ie.invoice_reference,
               ie.description, ie.amount, ie.currency, ie.bank_payment, ie.cash_payment,
               ie.status, ie.purchase_invoice
        FROM `tabImport Expense` ie
        LEFT JOIN `tabSupplier` s ON s.name = ie.supplier
        WHERE ie.company = %(company)s AND ie.docstatus < 2 AND ({" OR ".join(where_clause)})
        ORDER BY ie.creation DESC, ie.name DESC
        """,
		params,
		as_dict=True,
	)
	for r in expenses:
		r["expense_date"] = str(r["expense_date"]) if r.get("expense_date") else None
		r["amount"] = flt(r.get("amount"))
		if r.get("bank_payment") is not None:
			r["bank_payment"] = flt(r["bank_payment"])
		if r.get("cash_payment") is not None:
			r["cash_payment"] = flt(r["cash_payment"])

	today_d = rules.today_date()
	ref_cols = _existing_pi_ref_columns()
	bills = _related_import_bills(
		company,
		containers=container_names,
		ci=commercial_invoice,
		trucks=trucks,
		ref_cols=ref_cols,
		today_d=today_d,
	)

	lcvs = _ci_landed_cost_vouchers(commercial_invoice)
	lcv_total = sum(flt(l.get("total") or 0.0) for l in lcvs if l.get("docstatus") == 1)

	declarations = frappe.get_all(
		"Customs Declaration",
		filters={"commercial_invoice": commercial_invoice, "docstatus": ["<", 2]},
		fields=["name", "total_duties", "declaration_date", "cleared_date", "status"],
	)
	customs_duties = sum(flt(d.get("total_duties") or 0.0) for d in declarations)
	# "Released" is not a field on the doctype: a declaration counts as final
	# once customs cleared it (cleared_date set). Anything short of that leaves
	# the duty figure an estimate, and the UI says so.
	duties_estimated = not declarations or any(not d.get("cleared_date") for d in declarations)

	items_agreed_total = flt(ci_doc.agreed_total)
	items_docs_total = flt(ci_doc.docs_total)
	cargo_kg = flt(ci_doc.total_kg)

	return rules.calculate_ci_cost_overview(
		ci_name=commercial_invoice,
		items_agreed_total=items_agreed_total,
		items_docs_total=items_docs_total,
		cargo_kg=cargo_kg,
		containers=containers,
		expenses=expenses,
		bills=bills,
		lcv_total=lcv_total,
		customs_duties=customs_duties,
		duties_estimated=duties_estimated,
		currency=ci_doc.currency or "USD",
		cost_visible=cost_visible,
	)


@frappe.whitelist()
def get_import_expense(name: str):
	"""Full Import Expense payload (bank/cash split masked per K3)."""
	if not name or not frappe.db.exists("Import Expense", name):
		frappe.throw(_("Unknown Import Expense: {0}").format(name))
	_assert_imports_access(_company_of("Import Expense", name))
	_assert_can_read("Import Expense", name)
	doc = frappe.get_doc("Import Expense", name)
	payload = {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"commercial_invoice": doc.commercial_invoice,
		"container": doc.container,
		"truck": doc.truck,
		"category": doc.category,
		"expense_date": str(doc.expense_date) if doc.expense_date else None,
		"supplier": doc.supplier,
		"invoice_reference": doc.invoice_reference,
		"description": doc.description,
		"amount": flt(doc.amount),
		"currency": doc.currency,
		"bank_payment": flt(doc.bank_payment),
		"cash_payment": flt(doc.cash_payment),
		"expense_account": doc.expense_account,
		"paid_from_account": doc.paid_from_account,
		"status": doc.status,
		"purchase_invoice": doc.purchase_invoice,
		"journal_entry": doc.journal_entry,
	}
	rules.mask_named(payload, rules.EXPENSE_MASK_FIELDS, _cost_visible())
	return payload


@frappe.whitelist()
def create_import_expense(company: str, values=None):
	"""Create an Import Expense (status derived from the payment split)."""
	_assert_imports_access(company)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	if not values.get("category"):
		frappe.throw(_("An expense category is required."))
	doc = frappe.new_doc("Import Expense")
	doc.company = company
	_apply_ie_payload(doc, values)
	_assert_ie_payment_route(doc)
	doc.insert(ignore_permissions=False)
	return _ie_result(doc, _post_expense_kasa_entry(doc))


@frappe.whitelist()
def update_import_expense(name: str, values=None, modified: str | None = None):
	"""Update an Import Expense (status re-derived on save)."""
	if not name or not frappe.db.exists("Import Expense", name):
		frappe.throw(_("Unknown Import Expense: {0}").format(name))
	_assert_imports_access(_company_of("Import Expense", name))
	from stabler.api._common import check_concurrency

	check_concurrency("Import Expense", name, modified)
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	doc = frappe.get_doc("Import Expense", name)
	_apply_ie_payload(doc, values)
	_assert_ie_payment_route(doc)
	doc.save(ignore_permissions=False)
	return _ie_result(doc, _post_expense_kasa_entry(doc))


# ===========================================================================
# WP6b — Landed Cost Review (the accountant's single-payload LCV workbench)
# ===========================================================================


def _latest_exchange_rate(from_currency: str, to_currency: str, on_date=None):
	"""Latest Currency Exchange rate on/before *on_date*; ``(rate, as_of|None)``.

	Falls back to ERPNext's ``get_exchange_rate`` when no stored row exists, then
	to 1.0 so a preview never crashes on a missing rate.
	"""
	if not from_currency or from_currency == to_currency:
		return 1.0, None
	on_date = getdate(on_date or today())
	row = frappe.db.sql(
		"""
        SELECT exchange_rate, `date` FROM `tabCurrency Exchange`
        WHERE from_currency = %(f)s AND to_currency = %(t)s AND `date` <= %(d)s
        ORDER BY `date` DESC LIMIT 1
        """,
		{"f": from_currency, "t": to_currency, "d": on_date},
		as_dict=True,
	)
	if row:
		return flt(row[0]["exchange_rate"]) or 1.0, str(row[0]["date"])
	try:
		from erpnext.setup.utils import get_exchange_rate

		return flt(get_exchange_rate(from_currency, to_currency, on_date)) or 1.0, None
	except Exception:
		return 1.0, None


@frappe.whitelist()
def get_landed_cost_review(grn_checklist: str, rate=None):
	"""One payload for the accountant's Landed Cost Voucher workbench (cost-visible only).

	Returns the GRN header + its submitted Purchase Receipts, existing LCVs, every
	Container Cost Line of the CI (consumed + pending), the cleared GTD (if any)
	with its precedence note, and a computed preview of the NEXT LCV (aggregated
	components, the USD→base rate used, converted total, warnings). ``rate`` (a
	positive number) overrides the fetched exchange rate for the preview only.
	"""
	if not grn_checklist or not frappe.db.exists("GRN Checklist", grn_checklist):
		frappe.throw(_("Unknown GRN Checklist: {0}").format(grn_checklist))
	_assert_imports_access(_company_of("GRN Checklist", grn_checklist))
	_assert_cost_visible()

	from stabler.stabler.doctype.customs_declaration.customs_declaration import approved_gtd_for_ci
	from stabler.stabler.imports_module import hooks as imports_hooks
	from stabler.stabler.imports_module import lcv_math

	grn = frappe.get_doc("GRN Checklist", grn_checklist)
	company_currency = frappe.get_cached_value("Company", grn.company, "default_currency") or "UZS"

	# Purchase Receipts booked from this GRN's submitted Truck Receipts.
	pr_names = imports_hooks._submitted_prs_for_grn(grn.name)

	# The weight each receipt's money was actually booked against. Only Good-condition
	# weight ever reaches a Purchase Receipt (receipt_math.good_qty returns 0 for any
	# other condition and the zero-qty line is then dropped), whereas the GRN's
	# ``received_total_kg`` counts every condition, damaged included. Dividing one by
	# the other is not a cost per kg — the damaged kilos' money is not in the numerator
	# at all. Ship the costed weight on the *same rows* the totals come from so a client
	# cannot pair a receipt total with a weight that receipt never paid for.
	# ``stock_qty`` is stock UOM, which is Kg on this route (receipt_math.STOCK_UOM,
	# conversion_factor 1).
	# One query for every receipt, tallied in Python: Frappe v16 refuses an SQL
	# function spelled as a string in SELECT, so `sum(stock_qty) as ...` parses
	# fine here and 500s on the live site (test_imports_flow_source guards it).
	costed_kg: dict = {}
	if pr_names:
		for row in frappe.get_all(
			"Purchase Receipt Item",
			filters={"parent": ["in", pr_names], "parenttype": "Purchase Receipt"},
			fields=["parent", "stock_qty"],
		):
			costed_kg[row.parent] = costed_kg.get(row.parent, 0.0) + flt(row.stock_qty)

	purchase_receipts = []
	for pr in pr_names:
		prd = frappe.db.get_value(
			"Purchase Receipt",
			pr,
			["supplier", "posting_date", "grand_total", "base_grand_total", "currency", "docstatus"],
			as_dict=True,
		)
		if prd:
			purchase_receipts.append(
				{
					"name": pr,
					"supplier": prd.supplier,
					"posting_date": str(prd.posting_date) if prd.posting_date else None,
					"grand_total": flt(prd.grand_total),
					# Company-currency twin. Imports receipts are created in USD
					# (imports_module/hooks.py) while voucher totals are already base
					# amounts, so the per-kg card must not add the two raw figures.
					"base_grand_total": flt(prd.base_grand_total),
					"costed_qty_kg": flt(costed_kg.get(pr, 0.0)),
					"currency": prd.currency,
					"docstatus": cint(prd.docstatus),
				}
			)

	# Existing Landed Cost Vouchers (from the GRN child table).
	existing_lcvs = []
	for lc in grn.landed_cost_vouchers or []:
		lcd = frappe.db.get_value(
			"Landed Cost Voucher",
			lc.lcv,
			["docstatus", "total_taxes_and_charges", "posting_date"],
			as_dict=True,
		)
		existing_lcvs.append(
			{
				"lcv": lc.lcv,
				"note": lc.note,
				"posted_on": str(lc.posted_on) if lc.posted_on else None,
				"docstatus": cint(lcd.docstatus) if lcd else None,
				"total": flt(lcd.total_taxes_and_charges) if lcd else None,
				"posting_date": str(lcd.posting_date) if lcd and lcd.posting_date else None,
			}
		)

	# Every cost line of the CI's containers (consumed + pending), grouped by container.
	containers = []
	for cname in frappe.get_all(
		"Import Container", filters={"commercial_invoice": grn.commercial_invoice}, pluck="name"
	):
		cdoc = frappe.get_doc("Import Container", cname)
		lines = [
			{
				"row_name": cl.name,
				"cost_component": cl.cost_component,
				"description": cl.description,
				"currency": cl.currency,
				"amount": flt(cl.amount),
				"amount_uzs": flt(cl.amount_uzs),
				"include_in_landed_cost": cint(cl.include_in_landed_cost),
				"lcv_ref": cl.lcv_ref,
				"consumed": bool((cl.lcv_ref or "").strip()),
			}
			for cl in (cdoc.cost_lines or [])
		]
		if lines:
			containers.append(
				{"container": cname, "container_number": cdoc.container_number, "cost_lines": lines}
			)

	# Cleared GTD (Approved + cleared_date) supersedes cost-line Uzbek duty.
	gtd = approved_gtd_for_ci(grn.commercial_invoice)
	gtd_row = frappe.get_all(
		"Customs Declaration",
		filters={"commercial_invoice": grn.commercial_invoice},
		fields=[
			"name",
			"gtd_number",
			"status",
			"cleared_date",
			"duty_amount",
			"vat_amount",
			"excise_amount",
		],
		order_by="creation desc",
		limit=1,
	)
	gtd_payload = None
	if gtd_row:
		g = gtd_row[0]
		gtd_payload = {
			"name": g.name,
			"gtd_number": g.gtd_number,
			"status": g.status,
			"cleared_date": str(g.cleared_date) if g.cleared_date else None,
			"duty_amount": flt(g.duty_amount),
			"vat_amount": flt(g.vat_amount),
			"excise_amount": flt(g.excise_amount),
			"active": gtd is not None,
			"precedence_note": _(
				"A cleared customs declaration is active: its duty and excise replace any "
				"Uzbekistan Customs Duty cost line in the next voucher (VAT is never capitalized)."
			)
			if gtd is not None
			else None,
		}

	# Preview: what the NEXT LCV would carry (unconsumed, included lines).
	override = None
	if rate not in (None, ""):
		try:
			override = flt(rate)
		except Exception:
			override = None
	rate_overridden = bool(override and override > 0)

	# One implementation, shared with ``_build_and_save_lcv``. This screen is where
	# the accountant decides, and a preview computed by a second copy of the
	# precedence chain is a preview of a document that does not exist: the two
	# copies drift, and the drift is capitalized into stock valuation.
	computed = imports_hooks.compute_next_lcv(grn, rate_override=override, translate=_)
	warnings = computed["warnings"]
	components = computed["components"]
	pending = computed["pending"]

	# What the resolver honestly found for USD; 0/absent when it found nothing.
	# ``_latest_exchange_rate`` must never supply this number: it degrades to 1.0 on
	# a miss, the SPA seeds its rate box from whatever we return here, and the next
	# Recompute posts that 1.0 straight back as a hand-entered rate — which clears
	# the override gate and values a USD 100 freight line at 100 UZS. A missing rate
	# has to read as missing all the way out to the input. It is still consulted for
	# the as-of date, which is only shown when a real rate was found.
	resolved_usd = flt((computed["resolved_rates"] or {}).get("USD") or 0)
	usd_rate = None
	rate_as_of = None
	if rate_overridden:
		# A hand-entered rate is an instruction, so it wins for USD lines here.
		usd_rate = override
	elif resolved_usd:
		usd_rate = resolved_usd
		_unused, rate_as_of = _latest_exchange_rate("USD", company_currency, grn.completion_date)

	# ``_build_and_save_lcv`` takes no rate argument: it always re-resolves from
	# Currency Exchange. So the moment an override actually touches a USD line, this
	# total is money the create path would not post — either a different figure or
	# none at all. Show it (that is what the box is for), but do not let the button
	# promise it.
	override_changes_the_build = rate_overridden and any(
		(ln.get("currency") == "USD" != company_currency)
		and not lcv_math.is_vat_component(ln.get("cost_component") or "Other")
		for ln in pending
	)
	if override_changes_the_build:
		warnings.append(
			_(
				"This total uses the rate you typed. Creating the voucher does not — it "
				"reads the stored Currency Exchange rate. Record the USD rate for {0} "
				"first, then create the voucher."
			).format(str(grn.completion_date or today()))
		)

	preview_components = [{"component": k, "amount": round(v, 2)} for k, v in sorted(components.items())]
	preview_total = round(sum(components.values()), 2)
	if not pr_names:
		warnings.append(_("No submitted Purchase Receipts yet — a voucher cannot be created."))
	if not preview_components:
		warnings.append(_("No unconsumed landed-cost lines to voucher."))

	return {
		"grn": {
			"name": grn.name,
			"company": grn.company,
			"company_currency": company_currency,
			"commercial_invoice": grn.commercial_invoice,
			"supplier": grn.supplier,
			"warehouse": grn.warehouse,
			"docstatus": cint(grn.docstatus),
			"receipt_status": grn.receipt_status,
			"completion_date": str(grn.completion_date) if grn.completion_date else None,
			"received_total_kg": flt(grn.received_total_kg),
			"received_total_boxes": cint(grn.received_total_boxes),
		},
		"purchase_receipts": purchase_receipts,
		"existing_lcvs": existing_lcvs,
		"containers": containers,
		"gtd": gtd_payload,
		"preview": {
			"components": preview_components,
			"total": preview_total,
			"currency": company_currency,
			"exchange_rate": usd_rate,
			"rate_as_of": rate_as_of,
			"rate_overridden": rate_overridden,
			"warnings": warnings,
			"can_create": bool(pr_names and preview_components and not override_changes_the_build),
		},
	}


# ===========================================================================
# WP7 — Container cost ledger + landed-cost bills (vendor traceability)
# ===========================================================================


def _existing_pi_ref_columns() -> list[str]:
	"""The v46 traceability Link columns that actually exist on Purchase Invoice."""
	return [c for c in rules.PI_REF_COLUMNS if frappe.db.has_column("Purchase Invoice", c)]


def _pi_ref_select(ref_cols) -> str:
	"""SELECT fragment for the four v46 ref columns (NULL alias for absent ones)."""
	parts = []
	for c in rules.PI_REF_COLUMNS:
		parts.append(f"pi.{c}" if c in ref_cols else f"NULL AS {c}")
	return ", ".join(parts)


def _pi_item_codes(names) -> dict:
	"""Map ``{purchase_invoice: [item_code, ...]}`` for a set of PIs (one query)."""
	if not names:
		return {}
	out: dict[str, list] = {}
	for r in frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", list(names)]},
		fields=["parent", "item_code"],
	):
		out.setdefault(r["parent"], []).append(r["item_code"])
	return out


def _transport_group_suppliers(company: str | None, suppliers) -> set:
	"""Which of *suppliers* sit in this company's configured transport groups.

	One query for the whole page rather than one per row. An unconfigured
	company returns the empty set, which is the same answer the link gate gives:
	the feature is off, so no bill is categorized by supplier group.
	"""
	names = {s for s in suppliers if s}
	if not company or not names:
		return set()
	groups = imports_transport_supplier_groups_for(company)
	if not groups:
		return set()
	return {
		r["name"]
		for r in frappe.get_all(
			"Supplier",
			filters={"name": ["in", list(names)], "supplier_group": ["in", groups]},
			fields=["name"],
		)
	}


def _enrich_bill_rows(rows, today_d, company: str | None = None) -> None:
	"""In-place: derive category, overdue flag, stringify due_date on bill rows."""
	codes_by_pi = _pi_item_codes([r["name"] for r in rows])
	carriers = _transport_group_suppliers(company, [r.get("supplier") for r in rows])
	for r in rows:
		r["category"] = rules.derive_bill_category(
			truck_ref=r.get("custom_import_truck"),
			expense_ref=r.get("custom_import_expense"),
			item_codes=codes_by_pi.get(r["name"], []),
			bill_no=r.get("bill_no"),
			transport_supplier=r.get("supplier") in carriers,
		)
		r["grand_total"] = flt(r.get("grand_total"))
		r["outstanding_amount"] = flt(r.get("outstanding_amount"))
		r["overdue"] = rules.is_overdue(r.get("due_date"), today_d, r["outstanding_amount"])
		r["due_date"] = str(r["due_date"]) if r.get("due_date") else None
		r["supplier_name"] = r.get("supplier_name") or r.get("supplier")


def _related_import_bills(company, *, containers, ci, trucks, ref_cols, today_d):
	"""Purchase Invoices referencing these containers OR their CI OR its trucks (v46).

	``containers`` is a list: a commercial invoice carries several containers and
	a bill raised against any one of them belongs to the invoice's cost picture.
	"""
	container_list = [c for c in ([containers] if isinstance(containers, str) else (containers or [])) if c]
	match: list[str] = []
	params: dict = {"company": company}
	if "custom_import_container" in ref_cols and container_list:
		placeholders = []
		for idx, cnt in enumerate(container_list):
			key = f"cnt{idx}"
			params[key] = cnt
			placeholders.append(f"%({key})s")
		match.append(f"pi.custom_import_container IN ({', '.join(placeholders)})")
	if "custom_commercial_invoice" in ref_cols and ci:
		match.append("pi.custom_commercial_invoice = %(ci)s")
		params["ci"] = ci
	if "custom_import_truck" in ref_cols and trucks:
		placeholders = []
		for idx, trk in enumerate(trucks):
			key = f"trk{idx}"
			params[key] = trk
			placeholders.append(f"%({key})s")
		match.append(f"pi.custom_import_truck IN ({', '.join(placeholders)})")
	if not match:
		return []
	where = "pi.company = %(company)s AND pi.docstatus < 2 AND (" + " OR ".join(match) + ")"
	rows = frappe.db.sql(
		f"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.bill_no, pi.grand_total,
               pi.outstanding_amount, pi.status, pi.due_date, {_pi_ref_select(ref_cols)}
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE {where}
        ORDER BY pi.posting_date DESC, pi.name DESC
        """,
		params,
		as_dict=True,
	)
	_enrich_bill_rows(rows, today_d, company)
	return rows


def _container_advances(company, container, stored_pe):
	"""Advance Payment Entries for a container (v46 ref match OR the stored link)."""
	names: set[str] = set()
	if stored_pe:
		names.add(stored_pe)
	if frappe.db.has_column("Payment Entry", "custom_import_container") and container:
		for pe in frappe.get_all(
			"Payment Entry",
			filters={"company": company, "custom_import_container": container, "docstatus": ["<", 2]},
			pluck="name",
		):
			names.add(pe)
	out = []
	for name in sorted(names):
		d = frappe.db.get_value(
			"Payment Entry",
			name,
			["paid_amount", "unallocated_amount", "docstatus", "posting_date", "party"],
			as_dict=True,
		)
		if not d:
			continue
		out.append(
			{
				"name": name,
				"paid_amount": flt(d.paid_amount),
				"unallocated_amount": flt(d.unallocated_amount),
				"docstatus": cint(d.docstatus),
				"posting_date": str(d.posting_date) if d.posting_date else None,
				"party": d.party,
			}
		)
	return out


def _ci_landed_cost_vouchers(ci):
	"""LCVs recorded on the CI's GRN Checklist (name, docstatus, total, posted_on)."""
	if not ci:
		return []
	grn = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci}, "name")
	if not grn:
		return []
	out = []
	for lc in frappe.get_all(
		"GRN LCV Ref",
		filters={"parent": grn},
		fields=["lcv", "posted_on", "note"],
		order_by="creation asc",
	):
		lcd = frappe.db.get_value(
			"Landed Cost Voucher",
			lc["lcv"],
			["docstatus", "total_taxes_and_charges", "posting_date"],
			as_dict=True,
		)
		out.append(
			{
				"lcv": lc["lcv"],
				"note": lc.get("note"),
				"posted_on": str(lc["posted_on"]) if lc.get("posted_on") else None,
				"docstatus": cint(lcd.docstatus) if lcd else None,
				"total": flt(lcd.total_taxes_and_charges) if lcd else None,
				"posting_date": str(lcd.posting_date) if lcd and lcd.posting_date else None,
			}
		)
	return out


@frappe.whitelist()
def container_cost_ledger(container: str):
	"""Vendor-traceability ledger for one Import Container (money masked per K3).

	Answers "which bill belongs to which container, is it paid, what does the
	container really cost per kg": the header + cost lines, the related bills
	(PIs referencing the container / its CI / its trucks via the v46 fields, with
	a derived category and an overdue flag), the advance Payment Entries, the CI's
	Landed Cost Vouchers, and a cost summary (product / landed / grand / per-kg /
	paid / outstanding). All money is nulled for users lacking cost visibility.
	"""
	if not container or not frappe.db.exists("Import Container", container):
		frappe.throw(_("Unknown Import Container: {0}").format(container))
	company = _company_of("Import Container", container)
	_assert_imports_access(company)
	_assert_can_read("Import Container", container)
	visible = _cost_visible()

	doc = frappe.get_doc("Import Container", container)
	ci = doc.commercial_invoice
	total_kg = flt(doc.total_kg)
	today_d = today()
	ref_cols = _existing_pi_ref_columns()

	trucks = frappe.get_all("Import Truck", filters={"commercial_invoice": ci}, pluck="name") if ci else []
	bills = _related_import_bills(
		company, containers=[container], ci=ci, trucks=trucks, ref_cols=ref_cols, today_d=today_d
	)
	advances = _container_advances(company, container, doc.get("advance_70_payment_entry"))
	lcvs = _ci_landed_cost_vouchers(ci)

	# Summary is computed from raw (unmasked) figures, then masked as a block.
	raw_cost_lines = [
		{"amount": flt(cl.amount), "include_in_landed_cost": cint(cl.include_in_landed_cost)}
		for cl in (doc.cost_lines or [])
	]
	summary = rules.container_cost_summary(
		product_cost=flt(doc.total_amount),
		cost_lines=raw_cost_lines,
		bills=bills,
		advances=advances,
	)
	summary["per_kg"] = rules.per_kg(summary["grand_total"], total_kg)

	cost_lines = [
		{
			"cost_component": cl.cost_component,
			"description": cl.description,
			"currency": cl.currency,
			"amount": flt(cl.amount),
			"amount_uzs": flt(cl.amount_uzs),
			"include_in_landed_cost": cint(cl.include_in_landed_cost),
			"lcv_ref": cl.lcv_ref,
			"consumed": bool((cl.lcv_ref or "").strip()),
		}
		for cl in (doc.cost_lines or [])
	]

	rules.mask_named(cost_lines, rules.CONTAINER_COST_LINE_MASK_FIELDS, visible)
	rules.mask_named(bills, rules.LANDED_BILL_MASK_FIELDS, visible)
	rules.mask_named(advances, ("paid_amount", "unallocated_amount"), visible)
	if not visible:
		for key in rules.LEDGER_SUMMARY_MASK_FIELDS:
			summary[key] = None

	return {
		"header": {
			"name": doc.name,
			"container_number": doc.container_number,
			"commercial_invoice": ci,
			"supplier": doc.supplier,
			"supplier_name": frappe.db.get_value("Supplier", doc.supplier, "supplier_name")
			if doc.supplier
			else None,
			"currency": doc.currency,
			"status": doc.status,
			"total_kg": total_kg,
			"total_boxes": cint(doc.total_boxes),
		},
		"cost_visible": visible,
		"cost_lines": cost_lines,
		"bills": bills,
		"advances": advances,
		"landed_cost_vouchers": lcvs,
		"summary": summary,
	}


@frappe.whitelist()
def list_landed_cost_bills(
	company: str,
	supplier: str | None = None,
	status: str | None = None,
	commercial_invoice: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Purchase Invoices carrying any v46 import ref (amounts masked per K3)."""
	_assert_imports_access(company)
	ref_cols = _existing_pi_ref_columns()
	if not ref_cols:
		return {"rows": [], "total_count": 0}
	ci_filter = commercial_invoice if "custom_commercial_invoice" in ref_cols else None
	clauses, params = rules.landed_cost_bill_clauses(
		ref_cols, supplier=supplier, status=status, commercial_invoice=ci_filter
	)
	if not clauses:
		return {"rows": [], "total_count": 0}
	params["company"] = company
	params["limit_start"] = max(0, cint(limit_start))
	params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
	where = " AND ".join(["pi.company = %(company)s", "pi.docstatus < 2", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.bill_no, pi.grand_total,
               pi.outstanding_amount, pi.status, pi.due_date, pi.currency,
               {_pi_ref_select(ref_cols)}
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE {where}
        ORDER BY pi.posting_date DESC, pi.name DESC
        LIMIT %(limit_start)s, %(limit_page_length)s
        """,
		params,
		as_dict=True,
	)
	_enrich_bill_rows(rows, today(), company)
	rules.mask_named(rows, rules.LANDED_BILL_MASK_FIELDS, _cost_visible())
	total = _count(rules.count_query("`tabPurchase Invoice` pi", where), params)
	return {"rows": rows, "total_count": total}


@frappe.whitelist()
def supplier_landed_cost_summary(company: str):
	"""Per-supplier roll-up of import bills: count, total, outstanding, overdue (K3)."""
	_assert_imports_access(company)
	ref_cols = _existing_pi_ref_columns()
	if not ref_cols:
		return {"rows": [], "cost_visible": _cost_visible()}
	ors = " OR ".join(f"(pi.{c} IS NOT NULL AND pi.{c} != '')" for c in ref_cols)
	rows = frappe.db.sql(
		f"""
        SELECT pi.supplier, s.supplier_name,
               COUNT(*) AS bill_count,
               COALESCE(SUM(pi.grand_total), 0) AS total,
               COALESCE(SUM(pi.outstanding_amount), 0) AS outstanding,
               COALESCE(SUM(CASE WHEN pi.outstanding_amount > 0 AND pi.due_date IS NOT NULL
                                  AND pi.due_date < %(today)s THEN 1 ELSE 0 END), 0) AS overdue_count
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.company = %(company)s AND pi.docstatus < 2 AND ({ors})
        GROUP BY pi.supplier, s.supplier_name
        ORDER BY outstanding DESC, total DESC
        """,
		{"company": company, "today": today()},
		as_dict=True,
	)
	visible = _cost_visible()
	for r in rows:
		r["bill_count"] = cint(r["bill_count"])
		r["overdue_count"] = cint(r["overdue_count"])
		r["total"] = flt(r["total"])
		r["outstanding"] = flt(r["outstanding"])
		r["supplier_name"] = r.get("supplier_name") or r.get("supplier")
	rules.mask_named(rows, ("total", "outstanding"), visible)
	return {"rows": rows, "cost_visible": visible}


# ===========================================================================
# WP8 — Import Orders (native Purchase Order + v41/v42 custom fields)
# ===========================================================================
#
# A PI is a native Purchase Order carrying the imports custom fields (plan §3.1,
# K1); its lifecycle is derived, never stored (rules.derive_po_lifecycle). An
# "import order" is any PO whose ``custom_prepayment_type`` OR
# ``custom_import_pi_group`` is set — the marker rule the ETL applies to every
# migrated PI. Docs/cash figures are masked per K3; agreed (native ``rate``) is
# not (it is the real GL obligation, visible to Accounts).


def _import_order_cols() -> dict:
	"""Which v41/v42 imports custom columns actually exist (patch-order safety)."""
	po = "Purchase Order"
	poi = "Purchase Order Item"
	return {
		"pi_group": frappe.db.has_column(po, "custom_import_pi_group"),
		"advance_percentage": frappe.db.has_column(po, "custom_advance_percentage"),
		"prepayment_type": frappe.db.has_column(po, "custom_prepayment_type"),
		"docs_total": frappe.db.has_column(po, "custom_docs_total"),
		"cash_difference": frappe.db.has_column(po, "custom_cash_difference"),
		"stage": frappe.db.has_column(po, "custom_stage"),
		"boxes": frappe.db.has_column(poi, "custom_boxes"),
		"box_kg": frappe.db.has_column(poi, "custom_box_weight_kg"),
		"docs_rate": frappe.db.has_column(poi, "custom_docs_rate"),
		"docs_amount": frappe.db.has_column(poi, "custom_docs_amount"),
	}


def _po_custom_select(cols: dict) -> str:
	"""SELECT fragment for the PO header custom columns (NULL alias when absent)."""

	def c(flag, name):
		return f"po.{name}" if flag else f"NULL AS {name}"

	return ", ".join(
		[
			c(cols["pi_group"], "custom_import_pi_group"),
			c(cols["advance_percentage"], "custom_advance_percentage"),
			c(cols["prepayment_type"], "custom_prepayment_type"),
			c(cols["docs_total"], "custom_docs_total"),
			c(cols["cash_difference"], "custom_cash_difference"),
			c(cols["stage"], "custom_stage"),
		]
	)


def _in_placeholders(names, prefix: str):
	"""``("%(n0)s, %(n1)s", {"n0": .., "n1": ..})`` for a variable-length IN list."""
	ph: list[str] = []
	params: dict = {}
	for idx, name in enumerate(names):
		key = f"{prefix}{idx}"
		ph.append(f"%({key})s")
		params[key] = name
	return ", ".join(ph), params


@frappe.whitelist()
def list_import_orders(
	company: str,
	search: str | None = None,
	vendor: str | None = None,
	status: str | None = None,
	pi_group: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
):
	"""Import-Order (PO) list rows + KPI strip (docs/cash masked per K3).

	The derived lifecycle has no SQL column, so the base set is fetched once, the
	lifecycle/advance/invoiced figures are derived in Python, the ``status`` filter
	and KPI aggregates run over that derived set (not per-row), and pagination is
	applied last — keeping the KPI numbers exactly consistent with the filter.
	"""
	_assert_imports_access(company)
	cols = _import_order_cols()
	empty = {"rows": [], "total_count": 0, "kpis": rules.import_order_kpis([])}

	markers: list[str] = []
	if cols["prepayment_type"]:
		markers.append("(po.custom_prepayment_type IS NOT NULL AND po.custom_prepayment_type != '')")
	if cols["pi_group"]:
		markers.append("(po.custom_import_pi_group IS NOT NULL AND po.custom_import_pi_group != '')")
	if not markers:
		return empty  # imports custom fields not synced yet — nothing to show

	clauses, params = rules.import_order_filter_clauses(
		search, vendor, pi_group, has_pi_group_col=cols["pi_group"]
	)
	params["company"] = company
	where = " AND ".join(["po.company = %(company)s", "(" + " OR ".join(markers) + ")", *clauses])
	base = frappe.db.sql(
		f"""
        SELECT po.name, po.supplier, po.supplier_name, po.transaction_date, po.currency,
               po.grand_total, po.advance_paid, po.per_received, po.docstatus,
               {_po_custom_select(cols)}
        FROM `tabPurchase Order` po
        WHERE {where}
        ORDER BY po.transaction_date DESC, po.name DESC
        LIMIT 5000
        """,
		params,
		as_dict=True,
	)
	if not base:
		return empty

	names = [r["name"] for r in base]
	in_sql, in_params = _in_placeholders(names, "po")

	# Per-PO line aggregates: item count, total kg (native qty), total boxes.
	boxes_expr = "COALESCE(SUM(poi.custom_boxes), 0)" if cols["boxes"] else "0"
	item_rows = frappe.db.sql(
		f"""
        SELECT poi.parent AS po, COUNT(*) AS item_count,
               COALESCE(SUM(poi.qty), 0) AS total_kg, {boxes_expr} AS total_boxes
        FROM `tabPurchase Order Item` poi
        WHERE poi.parent IN ({in_sql})
        GROUP BY poi.parent
        """,
		in_params,
		as_dict=True,
	)
	items_by_po = {r["po"]: r for r in item_rows}

	# Per-PO CI-link aggregates: allocated kg + CI count.
	alloc_rows = frappe.db.sql(
		f"""
        SELECT l.purchase_order AS po,
               COUNT(DISTINCT l.commercial_invoice) AS ci_count,
               COALESCE(SUM(l.allocated_qty), 0) AS allocated_kg
        FROM `tabCommercial Invoice PO Link` l
        WHERE l.purchase_order IN ({in_sql})
        GROUP BY l.purchase_order
        """,
		in_params,
		as_dict=True,
	)
	alloc_by_po = {r["po"]: r for r in alloc_rows}

	# Per-PO CI statuses (for the SHIPPING/COMPLETED derivation) + a distinct
	# CI→status map for the invoices KPI (a CI may span several POs).
	ci_link_rows = frappe.db.sql(
		f"""
        SELECT DISTINCT l.purchase_order AS po, l.commercial_invoice AS ci, ci.status AS status
        FROM `tabCommercial Invoice PO Link` l
        JOIN `tabCommercial Invoice` ci ON ci.name = l.commercial_invoice
        WHERE l.purchase_order IN ({in_sql})
        """,
		in_params,
		as_dict=True,
	)
	statuses_by_po: dict[str, list[str]] = {}
	cis_by_po: dict[str, list[str]] = {}
	for r in ci_link_rows:
		statuses_by_po.setdefault(r["po"], []).append(r["status"])
		cis_by_po.setdefault(r["po"], []).append(r["ci"])

	full: list[dict] = []
	for r in base:
		agg = items_by_po.get(r["name"], {})
		alloc = alloc_by_po.get(r["name"], {})
		ci_statuses = statuses_by_po.get(r["name"], [])
		total_kg = flt(agg.get("total_kg"))
		allocated_kg = flt(alloc.get("allocated_kg"))
		adv = rules.advance_summary(
			prepayment_type=r.get("custom_prepayment_type"),
			advance_percentage=flt(r.get("custom_advance_percentage")),
			agreed_total=flt(r.get("grand_total")),
			docs_total=flt(r.get("custom_docs_total")),
			cash_difference=flt(r.get("custom_cash_difference")),
			advance_paid=flt(r.get("advance_paid")),
		)
		full.append(
			{
				"name": r["name"],
				"supplier": r["supplier"],
				"supplier_name": r.get("supplier_name") or r["supplier"],
				"transaction_date": str(r["transaction_date"]) if r["transaction_date"] else None,
				"currency": r["currency"],
				"docstatus": cint(r["docstatus"]),
				"pi_group": r.get("custom_import_pi_group"),
				"stage": r.get("custom_stage"),
				"item_count": cint(agg.get("item_count")),
				"total_boxes": cint(agg.get("total_boxes")),
				"total_kg": total_kg,
				"agreed_total": flt(r.get("grand_total")),
				"docs_total": flt(r.get("custom_docs_total")),
				"cash_difference": flt(r.get("custom_cash_difference")),
				"ci_count": cint(alloc.get("ci_count")),
				"allocated_kg": allocated_kg,
				"invoiced_pct": rules.invoiced_pct(allocated_kg, total_kg),
				"payment_badge": adv["badge"],
				"payment_pct": adv["pct_paid"],
				"payment_amount": adv["paid"],
				"advance_percentage": flt(r.get("custom_advance_percentage")),
				"lifecycle": rules.derive_po_lifecycle(
					docstatus=r["docstatus"],
					advance_paid=flt(r.get("advance_paid")),
					per_received=flt(r.get("per_received")),
					ci_statuses=ci_statuses,
				),
			}
		)

	if status:
		full = [r for r in full if r["lifecycle"] == status]

	# Invoices KPI over the FILTERED set: distinct CIs, split pending vs done.
	filtered_names = {r["name"] for r in full}
	ci_status: dict[str, str] = {}
	for r in ci_link_rows:
		if r["po"] in filtered_names:
			ci_status[r["ci"]] = r["status"]
	done = sum(1 for s in ci_status.values() if s == "DELIVERED_TO_UZBEKISTAN")
	pending = sum(1 for s in ci_status.values() if s not in ("DELIVERED_TO_UZBEKISTAN", "Cancelled"))
	kpis = rules.import_order_kpis(
		full, invoices_total=len(ci_status), invoices_pending=pending, invoices_done=done
	)

	total = len(full)
	start = max(0, cint(limit_start))
	page = rules.clamp_page_length(limit_page_length)
	rows = full[start : start + page]

	visible = _cost_visible()
	rules.mask_named(rows, rules.IMPORT_ORDER_LIST_MASK_FIELDS, visible)
	if not visible:
		for key in rules.IMPORT_ORDER_KPI_MASK_FIELDS:
			kpis[key] = None
	return {"rows": rows, "total_count": total, "kpis": kpis}


def _po_advance_payment_entries(po_name: str, company: str):
	"""Advance Payment Entries linked to a PO/PI, split bank/cash.

	Bank vs cash comes from ``custom_payment_stream`` when that field exists;
	otherwise it is inferred from the mode-of-payment / paid-from account name.
	Only submitted rows contribute to the paid totals; drafts remain visible as
	pending approval.
	"""
	has_stream = frappe.db.has_column("Payment Entry", "custom_payment_stream")
	stream_col = "pe.custom_payment_stream" if has_stream else "NULL"
	has_pi_ref = frappe.db.has_column("Payment Entry", "custom_proforma_invoice")
	pi_match = " OR pe.custom_proforma_invoice = %(po)s" if has_pi_ref else ""
	rows = frappe.db.sql(
		f"""
        SELECT pe.name, pe.paid_amount, pe.unallocated_amount, pe.posting_date,
               pe.docstatus, pe.mode_of_payment,
               pe.paid_from, pe.reference_no, {stream_col} AS payment_stream,
               COALESCE(SUM(CASE
                 WHEN per.reference_doctype IN ('Purchase Order', 'Proforma Invoice')
                  AND per.reference_name = %(po)s THEN per.allocated_amount ELSE 0 END), 0)
                 AS allocated_to_po
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        WHERE pe.company = %(company)s AND pe.docstatus < 2
          AND ((per.reference_doctype IN ('Purchase Order', 'Proforma Invoice')
                AND per.reference_name = %(po)s){pi_match})
        GROUP BY pe.name
        ORDER BY pe.posting_date ASC, pe.name ASC
        """,
		{"company": company, "po": po_name},
		as_dict=True,
	)
	out = []
	paid_bank = 0.0
	paid_cash = 0.0
	for r in rows:
		stream = (r.get("payment_stream") or "").strip()
		if not stream:
			hint = f"{r.get('mode_of_payment') or ''} {r.get('paid_from') or ''}".lower()
			stream = "Cash" if "cash" in hint else "Bank"
		amt = flt(r["paid_amount"])
		if cint(r["docstatus"]) == 1:
			if stream == "Cash":
				paid_cash += amt
			else:
				paid_bank += amt
		out.append(
			{
				"name": r["name"],
				"paid_amount": flt(r["paid_amount"]),
				"unallocated_amount": flt(r["unallocated_amount"]),
				"allocated_to_po": flt(r["allocated_to_po"]),
				"usable_amount": 0.0
				if cint(r["docstatus"]) == 1 and flt(r["allocated_to_po"]) > 0
				else flt(r["paid_amount"]),
				"ledger_status": "Migration Required"
				if cint(r["docstatus"]) == 1 and flt(r["allocated_to_po"]) > 0
				else None,
				"posting_date": str(r["posting_date"]) if r["posting_date"] else None,
				"docstatus": cint(r["docstatus"]),
				"mode_of_payment": r.get("mode_of_payment"),
				"reference_no": r.get("reference_no"),
				"payment_stream": stream,
			}
		)
	return out, round(paid_bank, 2), round(paid_cash, 2)


@frappe.whitelist()
def get_import_order(name: str):
	"""Full Import-Order payload: PO header + items (docs masked), linked CIs,
	advance Payment Entries, derived lifecycle and advance summary (K3)."""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(_("Unknown Purchase Order: {0}").format(name))
	_assert_imports_access(_company_of("Purchase Order", name))
	_assert_can_read("Purchase Order", name)
	doc = frappe.get_doc("Purchase Order", name)
	visible = _cost_visible()

	items = [
		{
			"name": it.name,
			"item_code": it.item_code,
			"item_name": it.item_name,
			"qty": flt(it.qty),
			"uom": it.uom,
			"rate": flt(it.rate),
			"amount": flt(it.amount),
			"boxes": cint(it.get("custom_boxes")),
			"box_weight_kg": flt(it.get("custom_box_weight_kg")),
			"docs_rate": flt(it.get("custom_docs_rate")),
			"docs_amount": flt(it.get("custom_docs_amount")),
		}
		for it in (doc.items or [])
	]
	rules.mask_named(items, ("docs_rate", "docs_amount"), visible)

	# Linked Commercial Invoices (through the CI PO Link table): status + kg.
	ci_rows = frappe.db.sql(
		"""
        SELECT l.commercial_invoice AS name, ci.ci_number, ci.status,
               ci.supplier, COALESCE(SUM(l.allocated_qty), 0) AS allocated_kg,
               COALESCE(SUM(l.allocated_amount), 0) AS allocated_amount
        FROM `tabCommercial Invoice PO Link` l
        JOIN `tabCommercial Invoice` ci ON ci.name = l.commercial_invoice
        WHERE l.purchase_order = %(po)s
        GROUP BY l.commercial_invoice, ci.ci_number, ci.status, ci.supplier
        ORDER BY ci.ci_date DESC, l.commercial_invoice DESC
        """,
		{"po": name},
		as_dict=True,
	)
	for r in ci_rows:
		r["allocated_kg"] = flt(r["allocated_kg"])
		r["allocated_amount"] = flt(r["allocated_amount"])
	ci_statuses = [r["status"] for r in ci_rows]

	total_kg = flt(sum(flt(it.qty) for it in (doc.items or [])))
	allocated_kg = flt(sum(r["allocated_kg"] for r in ci_rows))

	advances, paid_bank, paid_cash = _po_advance_payment_entries(name, doc.company)
	adv = rules.advance_summary(
		prepayment_type=doc.get("custom_prepayment_type"),
		advance_percentage=flt(doc.get("custom_advance_percentage")),
		agreed_total=flt(doc.grand_total),
		docs_total=flt(doc.get("custom_docs_total")),
		cash_difference=flt(doc.get("custom_cash_difference")),
		advance_paid=flt(doc.get("advance_paid")),
		paid_bank=paid_bank if advances else None,
		paid_cash=paid_cash if advances else None,
	)
	if not visible:
		rules.mask_named(advances, ("paid_amount", "allocated_to_po"), visible)
		for key in ("base", "expected", "expected_bank", "expected_cash", "paid", "remaining"):
			adv[key] = None
		adv["paid_bank"] = adv["paid_cash"] = None

	payload = {
		"name": doc.name,
		"modified": str(doc.modified),
		"company": doc.company,
		"supplier": doc.supplier,
		"supplier_name": frappe.db.get_value("Supplier", doc.supplier, "supplier_name")
		if doc.supplier
		else None,
		"transaction_date": str(doc.transaction_date) if doc.transaction_date else None,
		"schedule_date": str(doc.schedule_date) if doc.schedule_date else None,
		"currency": doc.currency,
		"status": doc.status,
		"docstatus": cint(doc.docstatus),
		"per_received": flt(doc.per_received),
		"per_billed": flt(doc.per_billed),
		"advance_paid": flt(doc.get("advance_paid")),
		"pi_group": doc.get("custom_import_pi_group"),
		"advance_percentage": flt(doc.get("custom_advance_percentage")),
		"prepayment_type": doc.get("custom_prepayment_type"),
		"docs_total": flt(doc.get("custom_docs_total")),
		"cash_difference": flt(doc.get("custom_cash_difference")),
		"stage": doc.get("custom_stage"),
		"agreed_total": flt(doc.grand_total),
		"total_kg": total_kg,
		"total_boxes": cint(sum(cint(it.get("custom_boxes")) for it in (doc.items or []))),
		"invoiced_pct": rules.invoiced_pct(allocated_kg, total_kg),
		"lifecycle": rules.derive_po_lifecycle(
			docstatus=doc.docstatus,
			advance_paid=flt(doc.get("advance_paid")),
			per_received=flt(doc.per_received),
			ci_statuses=ci_statuses,
		),
		"cost_visible": visible,
		"items": items,
		"commercial_invoices": ci_rows,
		"advances": advances,
		"advance_summary": adv,
	}
	rules.mask_named(payload, ("docs_total", "cash_difference"), visible)
	return payload


_IO_HEADER_FIELDS = (
	"transaction_date",
	"schedule_date",
	"currency",
	"custom_import_pi_group",
	"custom_advance_percentage",
	"custom_prepayment_type",
	"custom_stage",
)
_IO_DATE_FIELDS = ("transaction_date", "schedule_date")
_IO_COST_HEADER_FIELDS = ("custom_docs_total", "custom_cash_difference")


def _clean_io_items(items):
	"""Validate Import-Order item rows: boxes x box_weight = qty (kg)."""
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except Exception:
			frappe.throw(_("Invalid items payload."))
	if not isinstance(items, list) or not items:
		frappe.throw(_("At least one item is required."))
	cleaned = []
	for idx, row in enumerate(items, start=1):
		item = (row or {}).get("item_code") or (row or {}).get("item")
		if not item:
			frappe.throw(_("Row {0}: item is required.").format(idx))
		if not frappe.db.exists("Item", item):
			frappe.throw(_("Row {0}: unknown item '{1}'.").format(idx, item))
		boxes = cint(row.get("boxes"))
		box_kg = flt(row.get("box_weight_kg"))
		qty = flt(row.get("qty"))
		derived = round(boxes * box_kg, 3)
		# boxes x box_weight is the source of truth when both are given.
		if boxes and box_kg:
			if qty and abs(qty - derived) > 0.5:
				frappe.throw(
					_("Row {0}: quantity {1} kg does not match boxes x box weight ({2} kg).").format(
						idx, qty, derived
					)
				)
			qty = derived
		if qty <= 0:
			frappe.throw(_("Row {0}: a positive quantity (kg) is required.").format(idx))
		cleaned.append(
			{
				"item_code": item,
				"qty": qty,
				"uom": row.get("uom") or "Kg",
				"rate": flt(row.get("rate")),
				"boxes": boxes,
				"box_weight_kg": box_kg,
				"docs_rate": flt(row.get("docs_rate")),
				"docs_amount": flt(row.get("docs_amount")),
			}
		)
	return cleaned


def _apply_import_order_payload(doc, values: dict, items, cols: dict):
	for field in _IO_HEADER_FIELDS:
		if field not in values:
			continue
		val = values[field]
		if field in _IO_DATE_FIELDS:
			doc.set(field, getdate(val) if val else None)
		elif field == "custom_advance_percentage":
			doc.set(field, flt(val))
		else:
			doc.set(field, val or None)
	# Docs cost header (PL1) — cost-visible users only.
	if _cost_visible():
		for field in _IO_COST_HEADER_FIELDS:
			if field in values and values[field] not in (None, ""):
				doc.set(field, flt(values[field]))

	if not doc.get("schedule_date"):
		base = doc.get("transaction_date") or today()
		doc.schedule_date = add_days(getdate(base), 30)

	visible = _cost_visible()
	cleaned = _clean_io_items(items)
	doc.set("items", [])
	for row in cleaned:
		line = doc.append("items", {})
		line.item_code = row["item_code"]
		line.qty = row["qty"]
		line.uom = row["uom"]
		line.rate = row["rate"]
		line.schedule_date = doc.schedule_date
		if cols["boxes"]:
			line.custom_boxes = row["boxes"]
		if cols["box_kg"]:
			line.custom_box_weight_kg = row["box_weight_kg"]
		if visible:
			if cols["docs_rate"]:
				line.custom_docs_rate = row["docs_rate"]
			if cols["docs_amount"]:
				line.custom_docs_amount = row["docs_amount"] or round(row["qty"] * row["docs_rate"], 2)


@frappe.whitelist()
def create_import_order(company: str, supplier: str, values=None, items=None):
	"""Create a DRAFT import order (native Purchase Order + imports custom fields)."""
	_assert_imports_access(company)
	cols = _import_order_cols()
	if not (cols["prepayment_type"] or cols["pi_group"]):
		frappe.throw(_("The imports order fields are not available yet."))
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("A valid supplier is required."))
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	# Mark this PO as an import order so the list picks it up even without a group.
	if cols["prepayment_type"] and not values.get("custom_prepayment_type"):
		values["custom_prepayment_type"] = "Agreed Total"

	doc = frappe.new_doc("Purchase Order")
	doc.company = company
	doc.supplier = supplier
	if not values.get("transaction_date"):
		values["transaction_date"] = today()
	_apply_import_order_payload(doc, values, items, cols)
	doc.insert(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def update_import_order(name: str, supplier: str, values=None, items=None, modified: str | None = None):
	"""Update a DRAFT import order (submitted orders are edited via native flows)."""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(_("Unknown Purchase Order: {0}").format(name))
	company = _company_of("Purchase Order", name)
	_assert_imports_access(company)
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 0:
		frappe.throw(_("A submitted import order can no longer be edited here."))
	from stabler.api._common import check_concurrency

	check_concurrency("Purchase Order", name, modified)
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("A valid supplier is required."))
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}
	cols = _import_order_cols()
	doc.supplier = supplier
	_apply_import_order_payload(doc, values, items, cols)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def submit_import_order(name: str):
	"""Submit (confirm) a DRAFT import order — native PO submit."""
	if not name or not frappe.db.exists("Purchase Order", name):
		frappe.throw(_("Unknown Purchase Order: {0}").format(name))
	_assert_imports_access(_company_of("Purchase Order", name))
	doc = frappe.get_doc("Purchase Order", name)
	if doc.docstatus != 0:
		frappe.throw(_("This import order is not in a draft state."))
	doc.submit()
	return {"name": doc.name, "docstatus": cint(doc.docstatus), "status": doc.status}


# ---------------------------------------------------------------------------
# Import PI Groups (Django PIGroup — a supplier-scoped PI cluster)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_pi_groups(company: str, search: str | None = None):
	"""PI Groups for a company + counts and total amounts.

	Keeps pre-existing keys (name/title/status/remarks/order_count) used by
	Import Orders' quick-create picker, and adds code/pi_vendor/pi_count/agreed_sum
	for the PI Group management page."""
	_assert_imports_access(company)
	clauses = ["company = %(company)s"]
	params: dict = {"company": company}
	if search:
		clauses.append("(title LIKE %(q)s OR code LIKE %(q)s)")
		params["q"] = f"%{search}%"
	where = " AND ".join(clauses)
	groups = frappe.db.sql(
		f"""
        SELECT name, title, code, pi_vendor, status, remarks, creation, modified
        FROM `tabImport PI Group`
        WHERE {where}
        ORDER BY creation DESC
        """,
		params,
		as_dict=True,
	)
	by_grp: dict = {}
	if groups and frappe.db.has_column("Purchase Order", "custom_import_pi_group"):
		counts = frappe.db.sql(
			"""
            SELECT custom_import_pi_group AS grp, COUNT(*) AS c
            FROM `tabPurchase Order`
            WHERE company = %(company)s AND docstatus < 2
              AND custom_import_pi_group IS NOT NULL AND custom_import_pi_group != ''
            GROUP BY custom_import_pi_group
            """,
			{"company": company},
			as_dict=True,
		)
		by_grp = {r["grp"]: cint(r["c"]) for r in counts}
	pi_stats: dict = {}
	if groups:
		pi_rows = frappe.db.sql(
			"""
            SELECT import_pi_group AS grp, COUNT(*) AS c, SUM(agreed_total) AS total_agreed
            FROM `tabProforma Invoice`
            WHERE company = %(company)s
              AND import_pi_group IS NOT NULL AND import_pi_group != ''
            GROUP BY import_pi_group
            """,
			{"company": company},
			as_dict=True,
		)
		pi_stats = {
			r["grp"]: {"count": cint(r["c"]), "total_agreed": flt(r["total_agreed"])} for r in pi_rows
		}
	vendor_ids = {g["pi_vendor"] for g in groups if g.get("pi_vendor")}
	vendor_names: dict = {}
	if vendor_ids:
		vn = frappe.db.sql(
			"SELECT name, supplier_name FROM `tabSupplier` WHERE name IN %(ids)s",
			{"ids": tuple(vendor_ids)},
			as_dict=True,
		)
		vendor_names = {r["name"]: r["supplier_name"] for r in vn}
	for g in groups:
		g["order_count"] = by_grp.get(g["name"], 0)
		st = pi_stats.get(g["name"], {"count": 0, "total_agreed": 0.0})
		g["pi_count"] = st["count"]
		g["agreed_total"] = st["total_agreed"]
		# Aliases the PI-Group management page reads (title == group_name).
		g["group_name"] = g["title"]
		g["notes"] = g["remarks"]
		g["pi_vendor_name"] = vendor_names.get(g.get("pi_vendor")) or g.get("pi_vendor")
	return groups


@frappe.whitelist()
def create_pi_group(company: str, title: str, remarks: str | None = None):
	"""Create an Import PI Group (quick-create from the order form)."""
	_assert_imports_access(company)
	if not title or not title.strip():
		frappe.throw(_("A group title is required."))
	doc = frappe.new_doc("Import PI Group")
	doc.company = company
	doc.title = title.strip()
	doc.status = "Open"
	doc.remarks = remarks or None
	doc.insert(ignore_permissions=False)
	return {"name": doc.name, "title": doc.title}


@frappe.whitelist()
def pi_group_detail(name: str) -> dict:
	"""One Import PI Group + its linked PIs, Commercial Invoices, Containers & POs."""
	if not name or not frappe.db.exists("Import PI Group", name):
		frappe.throw(_("Unknown Import PI Group: {0}").format(name))
	doc = frappe.get_doc("Import PI Group", name)
	_assert_imports_access(doc.company)

	pis = frappe.db.sql(
		"""
        SELECT pi.name, pi.supplier_pi_ref, pi.pi_date, pi.supplier, s.supplier_name, pi.status,
               pi.agreed_total, pi.docs_total, pi.cash_difference, pi.currency,
               pi.incoterm, pi.incoterm_location, pi.port_of_loading, pi.port_of_discharge,
               pi.creation, pi.modified
        FROM `tabProforma Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.import_pi_group = %(group)s
        ORDER BY pi.creation DESC
        """,
		{"group": name},
		as_dict=True,
	)
	for p in pis:
		p["supplier_name"] = p.get("supplier_name") or p.get("supplier") or ""

	cis = frappe.db.sql(
		"""
        SELECT ci.name, ci.ci_number, ci.ci_date, ci.supplier, s.supplier_name, ci.status,
               ci.incoterm, ci.incoterm_location, ci.etd, ci.eta, ci.atd, ci.ata,
               ci.agreed_total, ci.docs_total, ci.cash_difference, ci.currency,
               ci.import_pi_group
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
        WHERE ci.import_pi_group = %(group)s
        ORDER BY ci.creation DESC
        """,
		{"group": name},
		as_dict=True,
	)
	for c in cis:
		c["supplier_name"] = c.get("supplier_name") or c.get("supplier") or ""

	ci_names = [c["name"] for c in cis]
	containers_by_ci: dict[str, list[dict]] = {}
	all_containers = []
	if ci_names:
		containers = frappe.db.sql(
			"""
            SELECT cnt.name, cnt.container_number, cnt.container_type, cnt.container_size,
                   cnt.status, cnt.commercial_invoice, cnt.total_boxes, cnt.total_kg, cnt.total_amount
            FROM `tabImport Container` cnt
            WHERE cnt.commercial_invoice IN %(ci_names)s
            ORDER BY cnt.creation DESC
            """,
			{"ci_names": tuple(ci_names)},
			as_dict=True,
		)
		all_containers = containers
		for cnt in containers:
			ci_ref = cnt.get("commercial_invoice")
			if ci_ref:
				containers_by_ci.setdefault(ci_ref, []).append(cnt)

	for c in cis:
		c["containers"] = containers_by_ci.get(c["name"], [])

	for p in pis:
		p_cis = [c for c in cis if c.get("supplier") == p.get("supplier")]
		p["linked_cis"] = p_cis

	pos = []
	if frappe.db.has_column("Purchase Order", "custom_import_pi_group"):
		pos = frappe.db.sql(
			"""
            SELECT po.name, po.transaction_date, po.supplier, s.supplier_name,
                   po.grand_total, po.currency, po.status, po.docstatus
            FROM `tabPurchase Order` po
            LEFT JOIN `tabSupplier` s ON s.name = po.supplier
            WHERE po.custom_import_pi_group = %(group)s AND po.docstatus < 2
            ORDER BY po.creation DESC
            """,
			{"group": name},
			as_dict=True,
		)
		for po in pos:
			po["supplier_name"] = po.get("supplier_name") or po.get("supplier") or ""

	vendor_name = frappe.db.get_value("Supplier", doc.pi_vendor, "supplier_name") if doc.pi_vendor else None

	grp_dict = {
		"name": doc.name,
		"title": doc.title,
		"group_name": doc.title,
		"code": doc.code,
		"pi_vendor": doc.pi_vendor,
		"pi_vendor_name": vendor_name or doc.pi_vendor or None,
		"notes": doc.remarks,
		"remarks": doc.remarks,
		"status": doc.status,
		"company": doc.company,
		"creation": str(doc.creation),
		"modified": str(doc.modified),
	}

	agreed_sum = sum(flt(p.get("agreed_total")) for p in pis)
	docs_sum = sum(flt(p.get("docs_total")) for p in pis)
	cash_diff_sum = sum(flt(p.get("cash_difference")) for p in pis)

	return {
		"group": grp_dict,
		"name": doc.name,
		"title": doc.title,
		"group_name": doc.title,
		"code": doc.code,
		"pi_vendor": doc.pi_vendor,
		"pi_vendor_name": vendor_name or doc.pi_vendor or None,
		"notes": doc.remarks,
		"remarks": doc.remarks,
		"status": doc.status,
		"company": doc.company,
		"creation": str(doc.creation),
		"modified": str(doc.modified),
		"pi_count": len(pis),
		"pis": pis,
		"cis": cis,
		"containers": all_containers,
		"purchase_orders": pos,
		"totals": {
			"pi_count": len(pis),
			"ci_count": len(cis),
			"container_count": len(all_containers),
			"po_count": len(pos),
			"agreed_total": agreed_sum,
			"docs_total": docs_sum,
			"cash_difference": cash_diff_sum,
		},
	}


@frappe.whitelist()
def save_pi_group(payload, company: str) -> dict:
	"""Create or update an Import PI Group (management page; mirrors
	save_vendor_category). Concurrency-checked on update; no child rows."""
	_assert_imports_access(company)
	data = frappe.parse_json(payload) if isinstance(payload, str) else payload
	# The management page sends group_name/notes; the quick-create sends title/remarks.
	title = (data.get("title") or data.get("group_name") or "").strip()
	if not title:
		frappe.throw(_("A group title is required."))
	if data.get("pi_vendor") and not frappe.db.exists("Supplier", data.get("pi_vendor")):
		frappe.throw(_("Unknown supplier: {0}").format(data.get("pi_vendor")))

	if data.get("name") and frappe.db.exists("Import PI Group", data["name"]):
		doc = frappe.get_doc("Import PI Group", data["name"])
		if doc.company != company:
			frappe.throw(_("Cannot move a PI group to another company."))
		from stabler.api._common import check_concurrency

		check_concurrency("Import PI Group", data["name"], data.get("modified"))
	else:
		doc = frappe.new_doc("Import PI Group")
		doc.company = company

	new_vendor = data.get("pi_vendor") or None
	if doc.name and new_vendor and new_vendor != doc.pi_vendor:
		# Tightening/changing the vendor restriction must not silently strand
		# members of a different supplier — require they be unlinked first.
		conflicts = frappe.db.sql_list(
			"""
            SELECT name FROM `tabProforma Invoice`
            WHERE import_pi_group = %(group)s AND supplier != %(vendor)s
            """,
			{"group": doc.name, "vendor": new_vendor},
		)
		if conflicts:
			frappe.throw(
				_(
					"Cannot set vendor restriction to {0}: PI(s) {1} in this group "
					"belong to a different supplier. Unlink them first."
				).format(new_vendor, ", ".join(conflicts))
			)

	doc.title = title
	doc.code = (data.get("code") or "").strip() or None
	doc.pi_vendor = new_vendor
	doc.status = data.get("status") or doc.status or "Open"
	doc.remarks = data.get("remarks") or data.get("notes")
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def delete_pi_group(name: str, company: str) -> dict:
	"""Delete an Import PI Group. Member PIs are UNLINKED (import_pi_group set
	to null), never deleted — mirrors MSA group-delete semantics."""
	_assert_imports_access(company)
	if not name or not frappe.db.exists("Import PI Group", name):
		frappe.throw(_("Unknown Import PI Group: {0}").format(name))
	grp_company = frappe.db.get_value("Import PI Group", name, "company")
	if grp_company != company:
		frappe.throw(_("PI Group does not belong to this company."))
	try:
		frappe.db.sql(
			"UPDATE `tabProforma Invoice` SET import_pi_group = NULL WHERE import_pi_group = %(name)s",
			{"name": name},
		)
		frappe.delete_doc("Import PI Group", name, ignore_permissions=False)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	return {"ok": True, "deleted": name}


@frappe.whitelist()
def list_group_eligible_pis(group: str, company: str) -> list[dict]:
	"""PIs eligible for assignment to ``group``: already members of it, or
	unlinked from any group (and — if the group restricts by vendor —
	matching that supplier). Powers the assign-PIs picker."""
	_assert_imports_access(company)
	if not group or not frappe.db.exists("Import PI Group", group):
		frappe.throw(_("Unknown Import PI Group: {0}").format(group))
	grp = frappe.db.get_value("Import PI Group", group, ["company", "pi_vendor"], as_dict=True)
	if grp.company != company:
		frappe.throw(_("PI Group does not belong to this company."))
	rows = frappe.db.sql(
		"""
        SELECT pi.name, pi.pi_date, pi.supplier, s.supplier_name, pi.status,
               pi.agreed_total, pi.currency, pi.import_pi_group
        FROM `tabProforma Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.company = %(company)s
          AND (pi.import_pi_group = %(group)s OR pi.import_pi_group IS NULL OR pi.import_pi_group = '')
        ORDER BY pi.creation DESC
        """,
		{"company": company, "group": group},
		as_dict=True,
	)
	out = []
	for r in rows:
		if not _proforma.is_group_eligible(r.get("import_pi_group"), r.get("supplier"), group, grp.pi_vendor):
			continue
		r["linked"] = (r.get("import_pi_group") or None) == group
		out.append(r)
	return out


@frappe.whitelist()
def assign_pis_to_group(group: str, pi_names, company: str) -> dict:
	"""Bulk-set the membership of ``group`` to exactly ``pi_names``: link the
	selected PIs, unlink any previously-linked PI that is not in the new
	selection. Every requested PI is re-validated server-side against the
	eligible set (incl. the vendor restriction) before anything is written."""
	_assert_imports_access(company)
	if not group or not frappe.db.exists("Import PI Group", group):
		frappe.throw(_("Unknown Import PI Group: {0}").format(group))
	grp = frappe.db.get_value("Import PI Group", group, ["company", "pi_vendor"], as_dict=True)
	if grp.company != company:
		frappe.throw(_("PI Group does not belong to this company."))

	names = frappe.parse_json(pi_names) if isinstance(pi_names, str) else (pi_names or [])
	names = [n for n in names if n]

	if names:
		candidates = frappe.db.sql(
			"""
            SELECT name, supplier, import_pi_group
            FROM `tabProforma Invoice`
            WHERE company = %(company)s AND name IN %(names)s
            """,
			{"company": company, "names": tuple(names)},
			as_dict=True,
		)
		found = {c["name"] for c in candidates}
		missing = [n for n in names if n not in found]
		if missing:
			frappe.throw(_("Unknown Proforma Invoice(s): {0}").format(", ".join(missing)))
		bad = _proforma.validate_assignment(candidates, group, grp.pi_vendor)
		if bad:
			frappe.throw(
				_("Not eligible for this group (vendor restriction or already in another group): {0}").format(
					", ".join(bad)
				)
			)

	try:
		currently_linked = set(
			frappe.db.sql_list(
				"""
                SELECT name FROM `tabProforma Invoice`
                WHERE company = %(company)s AND import_pi_group = %(group)s
                """,
				{"company": company, "group": group},
			)
		)
		selected = set(names)
		to_link = selected - currently_linked
		to_unlink = currently_linked - selected
		for n in to_unlink:
			frappe.db.set_value("Proforma Invoice", n, "import_pi_group", None, update_modified=False)
		for n in to_link:
			frappe.db.set_value("Proforma Invoice", n, "import_pi_group", group, update_modified=False)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	return {"linked": len(to_link), "unlinked": len(to_unlink)}


# ---------------------------------------------------------------------------
# Advance payment — 1-2 SUBMITTED Payment Entries against the PO (Bank / Cash)
# ---------------------------------------------------------------------------


def _assert_advance_postable(pe, *, company: str, stream: str) -> None:
	"""Refuse to submit an advance whose posting would be blank or wrongly valued.

	`_apply_pay_accounts` fills the accounts best-effort and is deliberately
	defensive — that was safe only while the Payment Entry stayed a draft. A
	submitted entry writes GL, so a missing account or a missing exchange rate
	stops being cosmetic: it becomes an opaque ERPNext error or, worse, base
	amounts computed at rate 0. Fail here with a message that names the fix.

	Call this **before** `insert()`. `paid_from` and `paid_to` are `reqd` on the
	Payment Entry doctype and both exchange rates go through ERPNext's own
	`validate_mandatory`, so every branch below is pre-empted by a generic
	"<Field> is mandatory" the moment the document is inserted. The caller
	therefore runs `setup_party_account_field()`, `set_missing_values()` and
	`set_exchange_rate()` by hand first — the same three steps `validate()`
	would run — so the values read here are the values ERPNext would post.
	"""
	if not pe.paid_from:
		frappe.throw(
			_("No {0} account is set for this advance. Choose one before recording it.").format(
				_(stream).lower()
			)
		)
	if not pe.paid_to:
		frappe.throw(
			_("{0} has no payable account for {1}. Set the supplier's default payable account first.").format(
				pe.party, company
			)
		)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	for account_currency, rate, account in (
		(pe.paid_from_account_currency, pe.source_exchange_rate, pe.paid_from),
		(pe.paid_to_account_currency, pe.target_exchange_rate, pe.paid_to),
	):
		if account_currency and account_currency != company_currency and not flt(rate):
			frappe.throw(
				_("No usable {0} to {1} exchange rate on {2}, so {3} cannot be posted.").format(
					account_currency, company_currency, formatdate(pe.posting_date), account
				)
			)


def _validate_advance_source_account(account: str | None, *, company: str, currency: str, stream: str):
	"""Require the selected bank/cash account to match the PI currency."""
	if not account:
		return
	row = frappe.db.get_value(
		"Account", account, ["company", "account_currency", "account_type"], as_dict=True
	)
	if not row or row.company != company:
		frappe.throw(_("Unknown payment account for this company: {0}").format(account))
	if row.account_type != stream:
		frappe.throw(_("{0} must be a {1} account.").format(account, stream))
	if currency and row.account_currency != currency:
		frappe.throw(
			_("{0} uses {1}; this {2} advance must be paid from a {2} account.").format(
				account, row.account_currency, currency
			)
		)


@frappe.whitelist()
def create_advance_payment(
	purchase_order: str,
	bank_amount=0,
	cash_amount=0,
	payment_date: str | None = None,
	reference_no: str | None = None,
	prepayment_basis: str | None = None,
	bank_account: str | None = None,
	cash_account: str | None = None,
):
	"""Record an advance against an import order or proforma as 1-2 SUBMITTED Payment Entries.

	Mirrors the Django record-advance flow (financial_ops): one PE for the bank
	stream, one for the cash stream, each a Pay to the supplier referencing the
	PO/PI. The entries are submitted here, so the advance is real money the moment
	it is recorded: a draft contributes advance_in = 0 to the PI advance ledger, so
	leaving them unposted made every running balance read zero. Cost-visible only
	(bank/cash split is dual-pricing data, K3). Equal split is not enforced; an
	unequal bank/cash split returns a soft warning.

	Atomicity: both streams submit inside the request transaction and nothing here
	commits, so a failure on the second stream rolls the first one back with it.
	"""
	if not purchase_order:
		frappe.throw(_("Missing Purchase Order / Proforma reference."))

	ref_doctype = None
	if frappe.db.exists("Purchase Order", purchase_order):
		ref_doctype = "Purchase Order"
	elif frappe.db.exists("Proforma Invoice", purchase_order):
		ref_doctype = "Proforma Invoice"
	else:
		frappe.throw(_("Unknown Purchase Order or Proforma Invoice: {0}").format(purchase_order))

	company = _company_of(ref_doctype, purchase_order)
	_assert_imports_access(company)
	_assert_cost_visible()
	doc = frappe.get_doc(ref_doctype, purchase_order)
	if ref_doctype == "Purchase Order" and doc.docstatus != 1:
		frappe.throw(_("Confirm (submit) the import order before recording an advance."))
	if not doc.supplier:
		frappe.throw(_("The document has no supplier."))

	bank = round(flt(bank_amount), 2)
	cash = round(flt(cash_amount), 2)
	if bank <= 0 and cash <= 0:
		frappe.throw(_("Enter a bank and/or cash amount."))
	on_date = getdate(payment_date) if payment_date else getdate(today())

	from stabler.stabler.imports_module.hooks import _apply_pay_accounts, patch_payment_entry_references

	patch_payment_entry_references()  # Legacy PI-reference rows remain readable.
	if ref_doctype == "Proforma Invoice" and not frappe.db.has_column(
		"Payment Entry", "custom_proforma_invoice"
	):
		frappe.throw(
			_(
				"PI advance traceability is not installed yet. Run the Stabler migration before recording this advance."
			)
		)

	has_stream = frappe.db.has_column("Payment Entry", "custom_payment_stream")
	created = []
	for stream, amount in (("Bank", bank), ("Cash", cash)):
		if amount <= 0:
			continue
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Pay"
		pe.company = company
		pe.party_type = "Supplier"
		pe.party = doc.supplier
		pe.posting_date = on_date
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.reference_no = reference_no or f"ADV-{purchase_order}-{stream.upper()}"
		pe.reference_date = on_date
		if has_stream:
			pe.custom_payment_stream = stream
		# Purchase Orders are native ERPNext advance references. A Stabler
		# Proforma is not: attaching an allocated reference would make the whole
		# payment look consumed before a Purchase Invoice exists. Keep it as an
		# unallocated supplier advance and retain the PI through a durable link.
		if ref_doctype == "Purchase Order":
			pe.append(
				"references",
				{
					"reference_doctype": ref_doctype,
					"reference_name": purchase_order,
					"allocated_amount": amount,
				},
			)
		elif frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
			pe.custom_proforma_invoice = purchase_order
		_apply_pay_accounts(pe, company, doc.supplier)
		if stream == "Bank" and bank_account:
			pe.paid_from = bank_account
		elif stream == "Cash" and cash_account:
			pe.paid_from = cash_account

		pe.setup_party_account_field()
		pe.set_missing_values()
		pe.set_exchange_rate()
		_validate_advance_source_account(
			pe.paid_from,
			company=company,
			currency=doc.currency or pe.paid_from_account_currency,
			stream=stream,
		)
		# Before insert(), not after: `paid_from` / `paid_to` are reqd on the
		# Payment Entry doctype, so insert() raises Frappe's generic mandatory
		# error first and these purpose-built messages would never be seen.
		_assert_advance_postable(pe, company=company, stream=stream)
		pe.insert(ignore_permissions=False)
		pe.submit()  # Posted on creation — a draft buys no advance credit.
		created.append({"name": pe.name, "stream": stream, "amount": amount, "docstatus": pe.docstatus})

	warning = None
	if bank > 0 and cash > 0 and abs(bank - cash) > 0.01:
		warning = _("Bank and cash amounts are not equal — recorded as entered.")
	return {"payment_entries": created, "warning": warning}


@frappe.whitelist()
def link_proforma_to_ci(proforma: str, commercial_invoice: str, company: str) -> dict:
	"""Supersede a Proforma Invoice with a Commercial Invoice (bidirectional link).

	Sets PI.status = SUPERSEDED_BY_CI + PI.commercial_invoice, and stamps
	CI.custom_proforma_invoice. Idempotent: re-linking the same pair is a no-op.
	Imports-gated; both documents must share the company and supplier.
	"""
	_assert_imports_access(company)
	if not frappe.db.exists("Proforma Invoice", proforma):
		frappe.throw(_("Unknown Proforma Invoice: {0}").format(proforma))
	if not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))

	pi = frappe.get_doc("Proforma Invoice", proforma)
	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	if pi.company != company or ci.company != company:
		frappe.throw(_("Documents belong to a different company."))
	if (pi.supplier or "") != (ci.supplier or ""):
		frappe.throw(_("Proforma and Commercial Invoice have different suppliers."))

	if _proforma.is_already_linked(pi.status, pi.get("commercial_invoice"), commercial_invoice):
		return {
			"proforma": pi.name,
			"status": pi.status,
			"commercial_invoice": commercial_invoice,
			"changed": False,
		}

	if not _proforma.can_supersede(pi.status):
		frappe.throw(_("Proforma {0} cannot be superseded from status {1}.").format(pi.name, pi.status))

	pi.status = _proforma.SUPERSEDED
	pi.commercial_invoice = commercial_invoice
	pi.save(ignore_permissions=True)
	if frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice"):
		ci.db_set("custom_proforma_invoice", proforma, update_modified=False)

	return {
		"proforma": pi.name,
		"status": pi.status,
		"commercial_invoice": commercial_invoice,
		"changed": True,
	}


def _proforma_list_filters(
	company: str, status: str | None, supplier: str | None, group: str | None, search: str | None
) -> tuple[list[str], dict]:
	"""Shared WHERE-clause builder for list_proformas + proforma_list_stats
	(kept in sync so the stats always describe the same set the list shows)."""
	clauses = ["pi.company = %(company)s"]
	params: dict = {"company": company}
	if status:
		clauses.append("pi.status = %(status)s")
		params["status"] = status
	if supplier:
		clauses.append("pi.supplier = %(supplier)s")
		params["supplier"] = supplier
	if group:
		clause, gparams = rules.group_clause("pi.import_pi_group", group)
		clauses.append(clause)
		params.update(gparams)
	if search:
		clauses.append("(pi.name LIKE %(q)s OR s.supplier_name LIKE %(q)s OR pi.supplier_pi_ref LIKE %(q)s)")
		params["q"] = f"%{search}%"
	return clauses, params


@frappe.whitelist()
def import_suppliers(company: str):
	"""Only the suppliers that actually appear on this company's Proforma or
	Commercial Invoices (the import/meat vendors) — so the imports list filters
	don't offer the entire Supplier master."""
	_assert_imports_access(company)
	return frappe.db.sql(
		"""
		SELECT s.name, s.supplier_name
		FROM `tabSupplier` s
		WHERE s.name IN (
			SELECT supplier FROM `tabProforma Invoice`
			WHERE company = %(c)s AND supplier IS NOT NULL AND supplier != ''
			UNION
			SELECT supplier FROM `tabCommercial Invoice`
			WHERE company = %(c)s AND supplier IS NOT NULL AND supplier != ''
		)
		ORDER BY s.supplier_name ASC
		""",
		{"c": company},
		as_dict=True,
	)


@frappe.whitelist()
def list_proformas(
	company: str,
	status: str | None = None,
	supplier: str | None = None,
	search: str | None = None,
	group: str | None = None,
	limit: int = 100,
) -> list[dict]:
	"""Proforma Invoice list rows for the imports SPA (imports-gated).

	``group`` filters to one Import PI Group; every row also carries the PI's
	group code (``import_pi_group_code``) via a LEFT JOIN, alongside the
	pre-existing ``import_pi_group`` name key."""
	_assert_imports_access(company)
	clauses, params = _proforma_list_filters(company, status, supplier, group, search)
	params["limit"] = int(limit)
	where = " AND ".join(clauses)
	rows = frappe.db.sql(
		f"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.pi_date, pi.supplier_pi_ref,
               pi.currency, pi.incoterm, pi.port_of_loading, pi.port_of_discharge,
               pi.advance_pct, pi.prepayment_type,
               pi.agreed_total, pi.docs_total, pi.cash_difference,
               pi.bank_agreed, pi.cash_agreed,
               pi.status, pi.commercial_invoice, pi.import_pi_group,
               g.code AS import_pi_group_code, g.code AS pi_group_code, g.title AS pi_group_title
        FROM `tabProforma Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        LEFT JOIN `tabImport PI Group` g ON g.name = pi.import_pi_group
        WHERE {where}
        ORDER BY pi.creation DESC
        LIMIT %(limit)s
        """,
		params,
		as_dict=True,
	)
	_attach_proforma_rollups(rows)
	_attach_proforma_match_rollups(rows)
	return rows


def _attach_proforma_rollups(rows: list[dict]) -> None:
	"""Smart-list aggregates per PI: item count + physical totals (boxes/kg/FCL)
	from the item child, and CI count + invoiced amount/qty from linked Commercial
	Invoices (child custom_proforma_invoice or header custom_proforma_invoice)."""
	if not rows:
		return
	names = [r["name"] for r in rows]
	phys = {
		d["parent"]: d
		for d in frappe.db.sql(
			"""SELECT parent, COUNT(*) AS item_count, COALESCE(SUM(boxes),0) AS boxes,
                      COALESCE(SUM(qty),0) AS kg, COALESCE(SUM(fcl),0) AS fcl
               FROM `tabProforma Invoice Item`
               WHERE parenttype='Proforma Invoice' AND parent IN %(names)s
               GROUP BY parent""",
			{"names": names},
			as_dict=True,
		)
	}

	ci_rollups = {}
	ci_data = frappe.db.sql(
		"""
        SELECT
            COALESCE(NULLIF(cii.custom_proforma_invoice, ''), ci.custom_proforma_invoice) AS pi_name,
            COUNT(DISTINCT ci.name) AS ci_count,
            COALESCE(SUM(cii.qty), 0) AS invoiced_kg,
            COALESCE(SUM(cii.amount), 0) AS invoiced_total
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        WHERE (cii.custom_proforma_invoice IN %(names)s OR (COALESCE(cii.custom_proforma_invoice, '') = '' AND ci.custom_proforma_invoice IN %(names)s))
          AND ci.status != 'Cancelled'
          AND ci.docstatus < 2
        GROUP BY COALESCE(NULLIF(cii.custom_proforma_invoice, ''), ci.custom_proforma_invoice)
        """,
		{"names": names},
		as_dict=True,
	)
	for d in ci_data:
		if d.get("pi_name"):
			ci_rollups[d["pi_name"]] = d

	for r in rows:
		p = phys.get(r["name"]) or {}
		c = ci_rollups.get(r["name"]) or {}
		r["item_count"] = cint(p.get("item_count"))
		r["total_boxes"] = cint(p.get("boxes"))
		total_kg = flt(p.get("kg"))
		r["total_kg"] = total_kg
		r["total_fcl"] = flt(p.get("fcl"))

		r["ci_count"] = cint(c.get("ci_count"))
		r["invoiced_total"] = flt(c.get("invoiced_total"))
		invoiced_kg = flt(c.get("invoiced_kg"))
		r["invoiced_kg"] = invoiced_kg

		agreed = flt(r.get("agreed_total"))
		if total_kg > 0:
			r["invoiced_pct"] = round(min(100.0, (invoiced_kg / total_kg) * 100.0), 1)
		elif agreed > 0:
			r["invoiced_pct"] = round(min(100.0, (r["invoiced_total"] / agreed) * 100.0), 1)
		else:
			r["invoiced_pct"] = 0.0


def _attach_proforma_match_rollups(rows: list[dict]) -> None:
	"""Sandbox-proven shipment math per PI: shipped/remaining boxes and
	over-shipment through the (proforma, category) match key.

	The existing ``invoiced_pct`` is an AMOUNT ratio; these columns are the
	BOX balance the sandbox settled: over-shipment is its own figure, never
	folded into the remainder, and a CI line on no PI never nets a balance.
	All math delegates to _imports_rules — no re-derivation.
	"""
	if not rows:
		return
	names = [r["name"] for r in rows]
	# Column aliases matter: _imports_rules reads ``pi_name`` (contract side)
	# and ``pi_name``/``custom_proforma_invoice`` (shipped side). Any other
	# alias silently yields an empty key and every balance reads zero.
	pi_items = frappe.db.sql(
		"""SELECT parent AS pi_name, category, boxes, qty, amount, rate
           FROM `tabProforma Invoice Item`
           WHERE parenttype='Proforma Invoice' AND parent IN %(names)s""",
		{"names": names},
		as_dict=True,
	)
	eff_pi = _ci_item_effective_pi_expr()
	ci_items = frappe.db.sql(
		f"""SELECT {eff_pi} AS pi_name, cii.category, cii.boxes,
                   cii.qty, cii.parent AS ci_name
            FROM `tabCommercial Invoice Item` cii
            JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
            WHERE ci.status != 'Cancelled' AND ci.docstatus < 2
              AND {eff_pi} IN %(names)s""",
		{"names": names},
		as_dict=True,
	)
	pi_rows_by_name: dict[str, list] = {}
	for it in pi_items:
		pi_rows_by_name.setdefault(it["pi_name"], []).append(it)
	ci_rows_by_name: dict[str, list] = {}
	for it in ci_items:
		ci_rows_by_name.setdefault(it["pi_name"], []).append(it)

	for r in rows:
		contract = rules.contract_index(pi_rows_by_name.get(r["name"], []))
		shipped = rules.shipped_index(ci_rows_by_name.get(r["name"], []))
		remaining = over = shipped_boxes = 0.0
		over_keys = 0
		for key, entry in contract.items():
			rem = rules.remaining_for(entry, shipped.get(key))
			if rem["over_shipped"]:
				over_keys += 1
				over += rem["over_boxes"]
			else:
				remaining += rem["remaining_boxes"]
		for entry in shipped.values():
			shipped_boxes += entry.get("boxes", 0)
		# CI lines whose key is on no PI line: reported, never netted.
		unattributable = sum(
			1
			for it in ci_rows_by_name.get(r["name"], [])
			if not rules.is_keyed(rules.match_key(it["pi_name"], it.get("category")))
			or rules.match_key(it["pi_name"], it.get("category")) not in contract
		)
		planned = flt(r.get("total_boxes"))
		r["shipped_boxes"] = shipped_boxes
		r["remaining_boxes"] = remaining
		r["over_boxes"] = over
		r["over_keys"] = over_keys
		r["unattributable_lines"] = unattributable
		r["shipped_pct"] = round(min(999.0, (shipped_boxes / planned) * 100.0), 1) if planned > 0 else 0.0


@frappe.whitelist()
def proforma_list_stats(
	company: str,
	status: str | None = None,
	supplier: str | None = None,
	group: str | None = None,
	search: str | None = None,
) -> dict:
	"""Aggregate totals over the same filter set as list_proformas (no LIMIT) —
	for the list header/summary strip. docs_total_sum/cash_difference_sum are
	cost-masked (K3): null when the caller lacks cost visibility."""
	_assert_imports_access(company)
	clauses, params = _proforma_list_filters(company, status, supplier, group, search)
	where = " AND ".join(clauses)
	rows = frappe.db.sql(
		f"""
        SELECT
            COALESCE(SUM(pi.agreed_total), 0) AS agreed_total_sum,
            COALESCE(SUM(pi.docs_total), 0) AS docs_total_sum,
            COALESCE(SUM(pi.cash_difference), 0) AS cash_difference_sum,
            COUNT(*) AS cnt,
            SUM(CASE WHEN pi.status = 'DRAFT' THEN 1 ELSE 0 END) AS draft_count,
            SUM(CASE WHEN pi.status = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed_count
        FROM `tabProforma Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE {where}
        """,
		params,
		as_dict=True,
	)
	r = rows[0] if rows else {}
	visible = _cost_visible()
	return {
		"agreed_total_sum": flt(r.get("agreed_total_sum")),
		"docs_total_sum": flt(r.get("docs_total_sum")) if visible else None,
		"cash_difference_sum": flt(r.get("cash_difference_sum")) if visible else None,
		"count": cint(r.get("cnt")),
		"draft_count": cint(r.get("draft_count")),
		"confirmed_count": cint(r.get("confirmed_count")),
	}


@frappe.whitelist()
def commercial_invoice_list_stats(
	company: str,
	status: str | None = None,
	supplier: str | None = None,
	search: str | None = None,
	group: str | None = None,
	pi_match: str | None = None,
) -> dict:
	"""Aggregate totals over the same filter set as list_commercial_invoices for top metric strip."""
	_assert_imports_access(company)
	clauses = ["ci.company = %(company)s"]
	params = {"company": company}
	if pi_match:
		# The strip must count exactly the set the table shows, so the PI-link
		# filter is applied here too — a total that ignored it would read as the
		# unfiltered book while the rows below showed a subset.
		match_clause = rules.ci_pi_match_clause(
			pi_match, frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice")
		)
		if match_clause:
			clauses.append(match_clause)
	if status:
		clauses.append("ci.status = %(status)s")
		params["status"] = status
	if supplier:
		clauses.append("ci.supplier = %(supplier)s")
		params["supplier"] = supplier
	if group:
		# Same derived expression the list rows and their badge use, so the
		# metric strip never counts a different set than the table shows.
		has_pi_link = frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice")
		clause, gparams = rules.group_clause(f"({rules.ci_effective_group_expr(has_pi_link)})", group)
		clauses.append(clause)
		params.update(gparams)
	if search:
		clauses.append("(ci.name LIKE %(q)s OR ci.ci_number LIKE %(q)s OR s.supplier_name LIKE %(q)s)")
		params["q"] = f"%{search}%"
	where = " AND ".join(clauses)
	rows = frappe.db.sql(
		f"""
        SELECT
            COALESCE(SUM(ci.agreed_total), 0) AS agreed_total_sum,
            COALESCE(SUM(ci.docs_total), 0) AS docs_total_sum,
            COALESCE(SUM(ci.cash_difference), 0) AS cash_difference_sum,
            COALESCE(SUM(ci.total_boxes), 0) AS total_boxes_sum,
            COALESCE(SUM(ci.total_kg), 0) AS total_kg_sum,
            COUNT(*) AS cnt,
            SUM(CASE WHEN ci.status = 'BOOKED' THEN 1 ELSE 0 END) AS booked_count,
            SUM(CASE WHEN ci.status IN ('IN_TRANSIT', 'GATE_IN', 'ON_BOARD', 'STUFFED') THEN 1 ELSE 0 END) AS in_transit_count,
            SUM(CASE WHEN ci.status = 'DELIVERED_TO_UZBEKISTAN' THEN 1 ELSE 0 END) AS delivered_count
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
        WHERE {where}
        """,
		params,
		as_dict=True,
	)
	r = rows[0] if rows else {}
	visible = _cost_visible()
	return {
		"agreed_total_sum": flt(r.get("agreed_total_sum")),
		"docs_total_sum": flt(r.get("docs_total_sum")) if visible else None,
		"cash_difference_sum": flt(r.get("cash_difference_sum")) if visible else None,
		"total_boxes_sum": cint(r.get("total_boxes_sum")),
		"total_kg_sum": flt(r.get("total_kg_sum")),
		"count": cint(r.get("cnt")),
		"booked_count": cint(r.get("booked_count")),
		"in_transit_count": cint(r.get("in_transit_count")),
		"delivered_count": cint(r.get("delivered_count")),
	}


@frappe.whitelist()
def container_list_stats(
	company: str,
	status: str | None = None,
	commercial_invoice: str | None = None,
	search: str | None = None,
	bl_type: str | None = None,
) -> dict:
	"""Aggregate totals for Import Containers list metric strip."""
	_assert_imports_access(company)
	clauses, params = rules.container_filter_clauses(search, status, commercial_invoice, bl_type)
	params["company"] = company
	where = " AND ".join(["c.company = %(company)s", *clauses])
	rows = frappe.db.sql(
		f"""
        SELECT
            COALESCE(SUM(c.total_boxes), 0) AS total_boxes_sum,
            COALESCE(SUM(c.total_kg), 0) AS total_kg_sum,
            COALESCE(SUM(c.total_amount), 0) AS total_amount_sum,
            COUNT(*) AS cnt,
            SUM(CASE WHEN c.status IN ('IN_TRANSIT', 'GATE_IN', 'ON_BOARD', 'STUFFED', 'ARRIVED_AT_IRAN') THEN 1 ELSE 0 END) AS in_transit_count,
            SUM(CASE WHEN c.status = 'DELIVERED_TO_UZBEKISTAN' THEN 1 ELSE 0 END) AS delivered_count
        FROM `tabImport Container` c
        LEFT JOIN `tabCommercial Invoice` ci ON ci.name = c.commercial_invoice
        LEFT JOIN `tabSupplier` s ON s.name = c.supplier
        WHERE {where}
        """,
		params,
		as_dict=True,
	)
	r = rows[0] if rows else {}
	visible = _cost_visible()
	return {
		"total_boxes_sum": cint(r.get("total_boxes_sum")),
		"total_kg_sum": flt(r.get("total_kg_sum")),
		"total_amount_sum": flt(r.get("total_amount_sum")) if visible else None,
		"count": cint(r.get("cnt")),
		"in_transit_count": cint(r.get("in_transit_count")),
		"delivered_count": cint(r.get("delivered_count")),
	}


@frappe.whitelist()
def truck_list_stats(company: str, status: str | None = None, search: str | None = None) -> dict:
	"""Aggregate totals for Import Trucks list metric strip."""
	_assert_imports_access(company)
	clauses = ["t.company = %(company)s"]
	params = {"company": company}
	if status:
		clauses.append("t.status = %(status)s")
		params["status"] = status
	if search:
		clauses.append(
			"(t.name LIKE %(q)s OR t.truck_number LIKE %(q)s OR t.driver_name LIKE %(q)s OR t.commercial_invoice LIKE %(q)s)"
		)
		params["q"] = f"%{search}%"
	where = " AND ".join(clauses)
	rows = frappe.db.sql(
		f"""
        SELECT
            COALESCE(SUM(t.total_kg), 0) AS total_kg_sum,
            COALESCE(SUM(t.transport_cost), 0) AS transport_cost_sum,
            COUNT(*) AS cnt,
            SUM(CASE WHEN t.status IN ('DEPARTED_IRAN', 'AT_BORDER', 'CROSSED_BORDER', 'IN_TRANSIT') THEN 1 ELSE 0 END) AS in_transit_count,
            SUM(CASE WHEN t.status IN ('ARRIVED', 'UNLOADING', 'GRN_CREATED', 'COMPLETED') THEN 1 ELSE 0 END) AS completed_count
        FROM `tabImport Truck` t
        WHERE {where}
        """,
		params,
		as_dict=True,
	)
	r = rows[0] if rows else {}
	visible = _cost_visible()
	return {
		"total_kg_sum": flt(r.get("total_kg_sum")),
		"transport_cost_sum": flt(r.get("transport_cost_sum")) if visible else None,
		"count": cint(r.get("cnt")),
		"in_transit_count": cint(r.get("in_transit_count")),
		"completed_count": cint(r.get("completed_count")),
	}


@frappe.whitelist()
def proforma_detail(name: str) -> dict:
	"""Full Proforma Invoice doc + linked CIs, containers, and advances."""
	if not name or not frappe.db.exists("Proforma Invoice", name):
		frappe.throw(_("Unknown Proforma Invoice: {0}").format(name))
	doc = frappe.get_doc("Proforma Invoice", name)
	_assert_imports_access(doc.company)
	data = doc.as_dict()

	cis = frappe.db.sql(
		"""
        SELECT ci.name, ci.ci_number, ci.ci_date, ci.supplier, s.supplier_name, ci.status,
               ci.incoterm, ci.etd, ci.eta, ci.agreed_total, ci.currency
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
        WHERE (%(group)s != '' AND ci.import_pi_group = %(group)s)
           OR (ci.supplier = %(supplier)s AND ci.creation >= %(creation)s)
        ORDER BY ci.creation DESC
        LIMIT 50
        """,
		{
			"group": doc.import_pi_group or "",
			"supplier": doc.supplier,
			"creation": doc.creation,
		},
		as_dict=True,
	)
	ci_names = [c["name"] for c in cis]
	containers_by_ci: dict[str, list[dict]] = {}
	if ci_names:
		containers = frappe.db.sql(
			"""
            SELECT cnt.name, cnt.container_number, cnt.container_type, cnt.container_size,
                   cnt.status, cnt.commercial_invoice
            FROM `tabImport Container` cnt
            WHERE cnt.commercial_invoice IN %(ci_names)s
            ORDER BY cnt.creation DESC
            """,
			{"ci_names": tuple(ci_names)},
			as_dict=True,
		)
		for cnt in containers:
			containers_by_ci.setdefault(cnt.commercial_invoice, []).append(cnt)

	for c in cis:
		c["containers"] = containers_by_ci.get(c["name"], [])

	data["linked_cis"] = cis

	advances, paid_bank, paid_cash = _po_advance_payment_entries(name, doc.company)
	data["advance_payments"] = advances
	data["advance_summary"] = {
		"paid_bank": paid_bank,
		"paid_cash": paid_cash,
		"paid_total": round(paid_bank + paid_cash, 2),
		"pending_approval": round(
			sum(flt(row["paid_amount"]) for row in advances if cint(row["docstatus"]) == 0), 2
		),
		"available_credit": round(
			sum(flt(row["unallocated_amount"]) for row in advances if cint(row["docstatus"]) == 1), 2
		),
	}
	data["advance_ledger"] = _build_proforma_advance_ledger(doc, advances) if _cost_visible() else None
	data["invoiced_summary"] = get_pi_invoiced_summary(name)

	return data


def _proforma_ci_movements(pi_name: str, supplier: str) -> list[dict]:
	"""CI rows charged to one PI, enriched with their goods Purchase Invoice."""
	effective_pi = _ci_item_effective_pi_expr()
	ci_rows = frappe.db.sql(
		f"""
		SELECT ci.name AS ci_name, ci.ci_date, ci.creation,
		       ROUND(COALESCE(SUM(cii.amount), 0), 2) AS ci_amount
		FROM `tabCommercial Invoice Item` cii
		JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
		WHERE {effective_pi} = %(pi)s AND ci.status != 'Cancelled'
		GROUP BY ci.name, ci.ci_date, ci.creation
		ORDER BY COALESCE(ci.ci_date, DATE(ci.creation)), ci.name
		""",
		{"pi": pi_name},
		as_dict=True,
	)
	has_ci_ref = frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")
	has_pe_pi_ref = frappe.db.has_column("Payment Entry", "custom_proforma_invoice")
	movements: list[dict] = []
	for row in ci_rows:
		invoice = None
		if has_ci_ref:
			invoices = frappe.get_all(
				"Purchase Invoice",
				filters={
					"custom_commercial_invoice": row["ci_name"],
					"supplier": supplier,
					"docstatus": ["<", 2],
				},
				fields=["name", "docstatus", "posting_date", "outstanding_amount"],
				order_by="docstatus desc, creation desc",
				limit=1,
			)
			invoice = invoices[0] if invoices else None
		status = "Unallocated"
		advance_out = 0.0
		if invoice:
			status = "Posted" if cint(invoice["docstatus"]) == 1 else "Planned"
			if has_pe_pi_ref:
				advance_out = flt(
					frappe.db.sql(
						"""
						SELECT COALESCE(SUM(pia.allocated_amount), 0)
						FROM `tabPurchase Invoice Advance` pia
						JOIN `tabPayment Entry` pe
						  ON pe.name = pia.reference_name
						 AND pia.reference_type = 'Payment Entry'
						WHERE pia.parent = %(pinv)s
						  AND pe.custom_proforma_invoice = %(pi)s
						""",
						{"pinv": invoice["name"], "pi": pi_name},
					)[0][0]
				)
		movements.append(
			{
				"ci_name": row["ci_name"],
				"posting_date": str(
					invoice["posting_date"] if invoice else row["ci_date"] or row["creation"]
				),
				"ci_amount": flt(row["ci_amount"]),
				"status": status,
				"purchase_invoice": invoice["name"] if invoice else None,
				"purchase_invoice_outstanding": flt(invoice["outstanding_amount"]) if invoice else None,
				"advance_out": advance_out,
			}
		)
	return movements


def _build_proforma_advance_ledger(doc, advances: list[dict]) -> dict:
	ledger = _ci_to_pinv.build_pi_advance_ledger(
		pi_total=flt(doc.agreed_total),
		advance_percentage=flt(doc.advance_pct),
		payments=advances,
		ci_movements=_proforma_ci_movements(doc.name, doc.supplier),
	)
	ledger["proforma_invoice"] = doc.name
	ledger["supplier_pi_ref"] = doc.supplier_pi_ref
	ledger["currency"] = doc.currency
	ledger["docs_total"] = flt(doc.docs_total)
	ledger["cash_difference"] = flt(doc.cash_difference)
	return ledger


@frappe.whitelist()
def pi_advance_ledger(name: str) -> dict:
	"""Cost-visible PI advance ledger for the Stabler SPA."""
	if not name or not frappe.db.exists("Proforma Invoice", name):
		frappe.throw(_("Unknown Proforma Invoice: {0}").format(name))
	doc = frappe.get_doc("Proforma Invoice", name)
	_assert_imports_access(doc.company)
	_assert_cost_visible()
	advances, _paid_bank, _paid_cash = _po_advance_payment_entries(name, doc.company)
	return _build_proforma_advance_ledger(doc, advances)


def get_pi_invoiced_summary(name: str) -> dict:
	"""Returns total ordered, invoiced, and remaining quantities per Vendor Category & Item Cut for a PI."""
	if not name or not frappe.db.exists("Proforma Invoice", name):
		return {
			"items": [],
			"total_ordered_kg": 0.0,
			"total_invoiced_kg": 0.0,
			"total_remaining_kg": 0.0,
			"pct": 0.0,
		}

	pi_doc = frappe.get_doc("Proforma Invoice", name)

	ci_rows = frappe.db.sql(
		"""
        SELECT cii.category, cii.item, cii.boxes, cii.qty, cii.parent AS ci_name, ci.ci_number
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        WHERE (cii.custom_proforma_invoice = %(pi)s OR (COALESCE(cii.custom_proforma_invoice, '') = '' AND ci.custom_proforma_invoice = %(pi)s))
          AND ci.status != 'Cancelled'
        """,
		{"pi": name},
		as_dict=True,
	)

	invoiced_map = {}
	by_code_map = {}
	for r in ci_rows:
		key = (r["category"] or "", r["item"])
		if key not in invoiced_map:
			invoiced_map[key] = {"boxes": 0, "qty": 0.0}
		invoiced_map[key]["boxes"] += cint(r["boxes"])
		invoiced_map[key]["qty"] += flt(r["qty"])

		code = r["item"]
		if code not in by_code_map:
			by_code_map[code] = {"boxes": 0, "qty": 0.0}
		by_code_map[code]["boxes"] += cint(r["boxes"])
		by_code_map[code]["qty"] += flt(r["qty"])

	summary_items = []
	tot_ordered_kg = 0.0
	tot_invoiced_kg = 0.0

	for it in pi_doc.items:
		cat = it.category or ""
		code = it.item
		pi_b = cint(it.boxes)
		pi_q = flt(it.qty)

		inv_data = invoiced_map.get((cat, code)) or by_code_map.get(code, {"boxes": 0, "qty": 0.0})
		inv_b = inv_data["boxes"]
		inv_q = inv_data["qty"]

		rem_b = pi_b - inv_b
		rem_q = flt(pi_q - inv_q, 2)
		pct = flt((inv_q / pi_q) * 100, 1) if pi_q > 0 else (100.0 if inv_q > 0 else 0.0)

		tot_ordered_kg += pi_q
		tot_invoiced_kg += inv_q

		summary_items.append(
			{
				"proforma_invoice": name,
				"supplier_pi_ref": pi_doc.supplier_pi_ref or name,
				"category": cat,
				"item": code,
				"description": it.description or code,
				"pi_boxes": pi_b,
				"pi_qty": pi_q,
				"invoiced_boxes": inv_b,
				"invoiced_qty": inv_q,
				"remaining_boxes": rem_b,
				"remaining_qty": rem_q,
				"pct": pct,
			}
		)

	tot_remaining_kg = max(0.0, flt(tot_ordered_kg - tot_invoiced_kg, 2))
	overall_pct = flt((tot_invoiced_kg / tot_ordered_kg) * 100, 1) if tot_ordered_kg > 0 else 0.0

	return {
		"items": summary_items,
		"total_ordered_kg": tot_ordered_kg,
		"total_invoiced_kg": tot_invoiced_kg,
		"total_remaining_kg": tot_remaining_kg,
		"pct": overall_pct,
	}


def _ci_item_effective_pi_expr() -> str:
	"""SQL for the PI a CI **row** belongs to: its own link, else the header's.

	``custom_proforma_invoice`` on the Commercial Invoice header is a Custom Field,
	so a site that never carried the imports work has no such column and naming it
	would break the query — there we fall back to the row link alone.
	"""
	if frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice"):
		return "COALESCE(NULLIF(cii.custom_proforma_invoice, ''), ci.custom_proforma_invoice)"
	return "cii.custom_proforma_invoice"


def _sub_cut_breakdown(shipped_entry) -> list[dict]:
	"""Per-item split of what shipped against one contract key, heaviest first.

	This is what makes a compensated bundle legible: one PI line of 16 800 boxes
	shows up as ``41 TOPSIDE`` / ``44 SILVER SIDE`` / ``45 RUMP STEAK``.
	"""
	if not shipped_entry:
		return []
	agg: dict = {}
	for line in shipped_entry["lines"]:
		code = line.get("item") or ""
		row = agg.setdefault(code, {"item": code, "boxes": 0.0, "qty": 0.0})
		row["boxes"] += flt(line.get("boxes"))
		row["qty"] += flt(line.get("qty"))
	return sorted(agg.values(), key=lambda r: -r["boxes"])


@frappe.whitelist()
def get_vendor_available_pi_lines(
	company: str,
	supplier: str,
	exclude_ci: str | None = None,
	selected_pis=None,
	include_lines=True,
) -> dict:
	"""Open Proforma Invoices for a supplier with their unshipped balance.

	The balance is keyed by ``(PI, category)`` — deliberately **not** by ``item``.
	A PI line is usually a compensated bundle (``CM60/40 = BUFFALO COMPENSATED``,
	16 800 boxes) that the CI ships broken into sub-cuts (``41 TOPSIDE``,
	``44 SILVER SIDE``…). Keying on the item made those shipments invisible, so
	every bundle looked 100% unshipped: on the msa data set item-keying matched
	19.5% of CI lines against 98.3% for category-keying.

	Shipments are attributed two ways — the row's own PI, else the CI header's —
	because ~2 127 CI rows carry the link only on the header. ``remaining_boxes``
	may be **negative**: over-shipment is real (21 keys / 25 959 boxes) and is
	reported through ``over_shipped``, never clamped away. See the invariants at
	the bottom of ``_imports_rules``.

	The Smart Fill modal is two-step and both steps read THIS one response, so:
	``selected_pis`` scopes the **lines** only — ``proformas`` always carries the
	supplier's full open list, or a narrowed load would blank step 1's picker.
	``include_lines=False`` is step 1's cheap open: the PI list without the line
	arithmetic. Both arguments are trailing and defaulted, so the two-argument
	call sites are byte-for-byte the call they have always been.
	"""
	_assert_imports_access(company)
	if not supplier:
		return {"proformas": [], "lines": []}

	pis = frappe.db.get_all(
		"Proforma Invoice",
		filters={
			"company": company,
			"supplier": supplier,
			"docstatus": ["<", 2],
			"status": ["!=", "CANCELLED"],
		},
		fields=["name", "supplier_pi_ref", "pi_date", "currency", "incoterm", "import_pi_group"],
		order_by="pi_date desc, name desc",
	)

	if not pis:
		return {"proformas": [], "lines": []}

	# Whitelisted arguments arrive as strings over HTTP: a JSON list for
	# selected_pis, and "0"/"false" (both truthy strings!) for include_lines.
	if isinstance(include_lines, str):
		include_lines = include_lines.strip().lower() not in ("", "0", "false", "no", "none")
	if not include_lines:
		return {"proformas": pis, "lines": []}

	selected = frappe.parse_json(selected_pis) if isinstance(selected_pis, str) else (selected_pis or [])
	selected = {n for n in selected if n}

	# The intersection, never the caller's raw list: an unknown name must not
	# widen the query, and a selection that matches nothing means "no lines" —
	# falling through to the full list would silently ignore step 1's choice.
	pi_names = [p.name for p in pis if not selected or p.name in selected]
	if not pi_names:
		return {"proformas": pis, "lines": []}

	pi_items = frappe.db.sql(
		"""
        SELECT name, parent, item, description, category, '' AS hs_code, boxes, box_weight_kg,
               qty, rate, docs_price, amount, docs_amount
        FROM `tabProforma Invoice Item`
        WHERE parent IN %(pi_names)s
        ORDER BY parent ASC, idx ASC
        """,
		{"pi_names": tuple(pi_names)},
		as_dict=True,
	)

	if not pi_items:
		return {"proformas": pis, "lines": []}

	eff_pi = _ci_item_effective_pi_expr()
	ci_conds = [
		"ci.company = %(company)s",
		"ci.status != 'Cancelled'",
		f"{eff_pi} IN %(pi_names)s",
	]
	params = {"company": company, "pi_names": tuple(pi_names)}
	if exclude_ci:
		ci_conds.append("ci.name != %(exclude_ci)s")
		params["exclude_ci"] = exclude_ci

	ci_where = " AND ".join(ci_conds)
	shipped_rows = frappe.db.sql(
		f"""
        SELECT {eff_pi} AS pi_name, cii.category, cii.item, cii.parent AS ci_name,
               SUM(cii.boxes) AS boxes, SUM(cii.qty) AS qty
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        WHERE {ci_where}
        GROUP BY {eff_pi}, cii.category, cii.item, cii.parent
        """,
		params,
		as_dict=True,
	)

	shipped = rules.shipped_index(shipped_rows)
	# K4 — the PI list already carries supplier_pi_ref; querying it per line was
	# one round-trip per contract row.
	pi_ref_by_name = {p.name: (p.supplier_pi_ref or p.name) for p in pis}

	available_lines = []
	for entry in rules.contract_index(pi_items).values():
		ship = shipped.get(entry["key"])
		bal = rules.remaining_for(entry, ship)
		first = entry["lines"][0]

		# Raw item codes, in contract order — contract_index upper-cases them for
		# the key, and an item code must round-trip verbatim into the CI row.
		items = []
		for ln in entry["lines"]:
			if ln.get("item") and ln["item"] not in items:
				items.append(ln["item"])

		available_lines.append(
			{
				"pi_name": entry["pi_name"],
				"pi_ref": pi_ref_by_name.get(entry["pi_name"], entry["pi_name"]),
				# A bundle has no single item; the modal offers `items` instead.
				"item": items[0] if len(items) == 1 else "",
				"items": items,
				"description": first.get("description") or "",
				"category": first.get("category") or "",
				"hs_code": first.get("hs_code") or "",
				"contract_boxes": bal["contract_boxes"],
				"contract_qty": bal["contract_qty"],
				"shipped_boxes": bal["shipped_boxes"],
				"shipped_qty": bal["shipped_qty"],
				"remaining_boxes": bal["remaining_boxes"],
				"remaining_qty": bal["remaining_qty"],
				"pct": bal["pct"],
				"over_shipped": bal["over_shipped"],
				"over_boxes": bal["over_boxes"],
				"ci_count": bal["ci_count"],
				"box_weight_kg": flt(first.get("box_weight_kg")),
				"agreed_rate": flt(first.get("rate")),
				"docs_price": flt(first.get("docs_price")),
				"agreed_prices": sorted(entry["agreed_prices"]),
				"docs_prices": sorted(entry["docs_prices"]),
				"sub_cuts": _sub_cut_breakdown(ship),
				# The bundle's own PI lines, so the picker can offer the thirteen
				# cuts a compensated line was booked as. Presentation only: the
				# balance above is still the whole category, which is what the
				# server guard enforces.
				"contract_lines": rules.contract_line_breakdown(entry),
			}
		)

	return {
		"proformas": pis,
		"lines": available_lines,
	}


def get_pi_tracking_for_ci(ci_doc) -> list[dict]:
	"""PI tracking for a Commercial Invoice, one row per ``(PI, category)``.

	Same key as ``get_vendor_available_pi_lines``: the item is a sub-cut of a
	compensated bundle, so it may never be part of the key. The old code fell back
	to matching on the bare item code (``prior_by_code`` / ``this_by_code``), which
	attributed a sub-cut to whichever contract line happened to share its code —
	across categories, and even across PIs.
	"""
	ref_pis = set()
	if ci_doc.get("custom_proforma_invoice"):
		ref_pis.add(ci_doc.custom_proforma_invoice)
	for it in ci_doc.items or []:
		if it.get("custom_proforma_invoice"):
			ref_pis.add(it.custom_proforma_invoice)

	tracking_results = []
	for pi_name in sorted(ref_pis):
		if not frappe.db.exists("Proforma Invoice", pi_name):
			continue
		pi_doc = frappe.get_doc("Proforma Invoice", pi_name)

		contract = rules.contract_index(
			[
				{
					"pi_name": pi_name,
					"category": it.category,
					"item": it.item,
					"description": it.description,
					"boxes": it.boxes,
					"qty": it.qty,
					"amount": it.amount,
					"rate": it.rate,
					"docs_price": it.docs_price,
					"box_weight_kg": it.box_weight_kg,
				}
				for it in pi_doc.items or []
			]
		)

		prior_rows = frappe.db.sql(
			"""
            SELECT cii.category, cii.item, cii.boxes, cii.qty, cii.parent AS ci_name
            FROM `tabCommercial Invoice Item` cii
            JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
            WHERE (cii.custom_proforma_invoice = %(pi)s OR (COALESCE(cii.custom_proforma_invoice, '') = '' AND ci.custom_proforma_invoice = %(pi)s))
              AND ci.status != 'Cancelled'
              AND ci.name != %(this_ci)s
            """,
			{"pi": pi_name, "this_ci": ci_doc.name},
			as_dict=True,
		)
		for r in prior_rows:
			r["pi_name"] = pi_name

		this_rows = [
			{
				"pi_name": pi_name,
				"category": r.category,
				"item": r.item,
				"boxes": r.boxes,
				"qty": r.qty,
				"ci_name": ci_doc.name,
			}
			for r in ci_doc.items or []
			if (r.get("custom_proforma_invoice") or ci_doc.get("custom_proforma_invoice")) == pi_name
		]

		prior = rules.shipped_index(prior_rows)
		this_ci = rules.shipped_index(this_rows)
		combined = rules.shipped_index(prior_rows + this_rows)

		for key, entry in contract.items():
			bal = rules.remaining_for(entry, combined.get(key))
			pr = prior.get(key)
			tc = this_ci.get(key)
			first = entry["lines"][0]
			items = []
			for ln in entry["lines"]:
				if ln.get("item") and ln["item"] not in items:
					items.append(ln["item"])

			tracking_results.append(
				{
					"proforma_invoice": pi_name,
					"supplier_pi_ref": pi_doc.supplier_pi_ref or pi_name,
					"category": first.get("category") or "",
					# A compensated bundle has no single item — `items` carries all of them.
					"item": items[0] if len(items) == 1 else "",
					"items": items,
					"description": first.get("description") or first.get("category") or "",
					"pi_boxes": bal["contract_boxes"],
					"pi_qty": bal["contract_qty"],
					"prior_invoiced_boxes": (pr or {}).get("boxes", 0.0),
					"prior_invoiced_qty": (pr or {}).get("qty", 0.0),
					"this_ci_boxes": (tc or {}).get("boxes", 0.0),
					"this_ci_qty": (tc or {}).get("qty", 0.0),
					"total_invoiced_boxes": bal["shipped_boxes"],
					"total_invoiced_qty": bal["shipped_qty"],
					"remaining_boxes": bal["remaining_boxes"],
					"remaining_qty": bal["remaining_qty"],
					"pct": bal["pct"],
					"over_shipped": bal["over_shipped"],
					"over_boxes": bal["over_boxes"],
					"sub_cuts": _sub_cut_breakdown(combined.get(key)),
				}
			)

	return tracking_results


@frappe.whitelist()
def get_ci_pi_discrepancies(
	company: str, ci: str | None = None, pi: str | None = None, limit: int = 500
) -> dict:
	"""Report every CI line that disagrees with the PI it was shipped against.

	The scope directive is "each CI line must trace to a PI line, and any column
	that disagrees must be flagged" — this is the read side of that. Comparison
	is keyed on ``(proforma, category)``, never on ``item``: a PI line such as
	``BUFFALO COMPENSATED`` is a *bundle* that a CI breaks into sub-cuts
	(``41 TOPSIDE``, ``44 SILVER SIDE``…), so an item-keyed comparison declares
	98% of the book unmatched. See ``_imports_rules`` for the rules themselves.

	``rows`` carries only ``error``/``warn`` lines. ``info``-level ``sub_cut``
	rows are the normal case (5 695 of them across msa) and would drown the
	payload; they are still counted in ``summary``.

	Balances (``remaining_boxes``, over-shipment) always span **every** CI booked
	against the PIs in scope, even when ``ci`` narrows the row list to one
	invoice — a remaining figure computed from a single CI would be a fiction.

	No new cost exposure: ``rate``/``docs_price`` on a CI line are already
	returned unmasked by ``get_commercial_invoice``; this endpoint reads the same
	child rows behind the same ``_assert_imports_access`` gate.
	"""
	_assert_imports_access(company)
	limit = min(cint(limit) or 500, 2000)

	eff_pi = _ci_item_effective_pi_expr()
	# No "has a PI" filter on purpose: a CI line with no proforma at all is the
	# worst case the report exists to surface, and it reaches `unattributable`
	# through the empty match key.
	conds = ["ci.company = %(company)s", "ci.status != 'Cancelled'"]
	params: dict = {"company": company}
	if ci:
		conds.append("cii.parent = %(ci)s")
		params["ci"] = ci
	if pi:
		conds.append(f"{eff_pi} = %(pi)s")
		params["pi"] = pi

	scope_rows = frappe.db.sql(
		f"""
        SELECT cii.name AS row_name, cii.idx, cii.parent AS ci_name, ci.ci_number, ci.ci_date,
               {eff_pi} AS pi_name, cii.custom_proforma_invoice AS row_pi,
               cii.category, cii.item, cii.description,
               cii.boxes, cii.box_weight_kg, cii.qty, cii.rate, cii.docs_price, cii.amount
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        WHERE {" AND ".join(conds)}
        ORDER BY ci.ci_date DESC, cii.parent DESC, cii.idx ASC
        """,
		params,
		as_dict=True,
	)

	if not scope_rows:
		return {"rows": [], "summary": rules.reconcile([], []), "truncated": False}

	pi_names = sorted({r.pi_name for r in scope_rows if r.pi_name})
	pi_items = (
		frappe.db.sql(
			"""
            SELECT parent AS pi_name, item, category, description,
                   boxes, box_weight_kg, qty, rate, docs_price, amount
            FROM `tabProforma Invoice Item`
            WHERE parent IN %(pi_names)s
            """,
			{"pi_names": tuple(pi_names)},
			as_dict=True,
		)
		if pi_names
		else []
	)

	summary = rules.reconcile(pi_items, scope_rows)

	# Balances must see every shipment against these PIs, not just the scoped CI.
	balance_rows = scope_rows
	if ci and pi_names:
		balance_rows = frappe.db.sql(
			f"""
            SELECT {eff_pi} AS pi_name, cii.category, cii.item, cii.parent AS ci_name,
                   cii.boxes, cii.qty
            FROM `tabCommercial Invoice Item` cii
            JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
            WHERE ci.company = %(company)s AND ci.status != 'Cancelled'
              AND {eff_pi} IN %(pi_names)s
            """,
			{"company": company, "pi_names": tuple(pi_names)},
			as_dict=True,
		)

	contract = rules.contract_index(pi_items)
	shipped = rules.shipped_index(balance_rows)
	over_keys, over_boxes, remaining = 0, 0.0, 0.0
	for key, entry in contract.items():
		bal = rules.remaining_for(entry, shipped.get(key))
		if bal["over_shipped"]:
			over_keys += 1
			over_boxes += bal["over_boxes"]
		else:
			remaining += bal["remaining_boxes"]
	summary["over_keys"] = over_keys
	summary["over_boxes"] = over_boxes
	summary["remaining_boxes"] = remaining

	flagged = []
	for row in scope_rows:
		key = rules.match_key(row.pi_name, row.category)
		entry = contract.get(key) if rules.is_keyed(key) else None
		diffs = rules.diff_ci_line(row, entry)
		level = rules.worst_level(diffs)
		# Whole-book calls keep the payload to error/warn (info sub_cut rows are
		# the normal case and would drown it). A single-PI call IS the sub-cut
		# breakdown view, so info rows ride along there.
		if level not in ("error", "warn") and not (pi and level == "info"):
			continue
		flagged.append(
			{
				"row_name": row.row_name,
				"idx": row.idx,
				"ci_name": row.ci_name,
				"ci_number": row.ci_number or row.ci_name,
				"ci_date": row.ci_date,
				"proforma_invoice": row.pi_name,
				# Empty ``row_pi`` means the line inherits the header's PI — the
				# form shows that as "via invoice" rather than as a row link.
				"pi_inherited": not (row.row_pi or ""),
				"category": row.category or "",
				"item": row.item or "",
				"description": row.description or "",
				"boxes": flt(row.boxes),
				"qty": flt(row.qty),
				"rate": flt(row.rate),
				"docs_price": flt(row.docs_price),
				"level": level,
				"diffs": [d for d in diffs if d["level"] in ("error", "warn")],
			}
		)

	return {
		"rows": flagged[:limit],
		"summary": summary,
		"truncated": len(flagged) > limit,
	}


@frappe.whitelist()
def save_proforma(payload) -> dict:
	"""Create or update a Proforma Invoice (imports-gated). Controller enforces
	the bank+cash == agreed_total earmark identity on validate."""
	data = frappe.parse_json(payload) if isinstance(payload, str) else payload
	company = data.get("company")
	_assert_imports_access(company)

	if data.get("name") and frappe.db.exists("Proforma Invoice", data["name"]):
		doc = frappe.get_doc("Proforma Invoice", data["name"])
		if doc.company != company:
			frappe.throw(_("Cannot move a proforma to another company."))
	else:
		doc = frappe.new_doc("Proforma Invoice")

	for field in (
		"supplier",
		"company",
		"pi_date",
		"supplier_pi_ref",
		"import_pi_group",
		"currency",
		"incoterm",
		"incoterm_location",
		"port_of_loading",
		"port_of_discharge",
		"prepayment_type",
		"agreed_total",
		"advance_pct",
		"expected_payment_date",
		"bank_agreed",
		"cash_agreed",
		"status",
		"remarks",
	):
		if field in data:
			doc.set(field, data.get(field))

	doc.set("items", [])
	for row in data.get("items") or []:
		if not (row or {}).get("item"):
			continue
		doc.append(
			"items",
			{
				"item": row.get("item"),
				"category": row.get("category"),
				"description": row.get("description"),
				"fcl": flt(row.get("fcl")),
				"boxes": cint(row.get("boxes")),
				"box_weight_kg": flt(row.get("box_weight_kg")),
				"qty": flt(row.get("qty")),
				"uom": row.get("uom"),
				"rate": flt(row.get("rate")),
				"docs_price": flt(row.get("docs_price")),
			},
		)

	doc.save(ignore_permissions=False)
	return {
		"name": doc.name,
		"status": doc.status,
		"agreed_total": flt(doc.agreed_total),
		"docs_total": flt(doc.docs_total),
		"cash_difference": flt(doc.cash_difference),
	}


# ---------------------------------------------------------------------------
# WP-I17 — Vendor Category management (MSA /products/vendor-categories/ parity)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_vendor_categories(company: str, vendor: str | None = None) -> list[dict]:
	"""Vendor categories grouped for the management page.

	A category is a purchasing/inventory TEMPLATE — which items + boxes-per-
	container — prices are entered per-PI (MSA model: categories store no prices).
	Lives under the inventory module; the read is also reachable from the imports
	PI 'fill from category' flow, so either module's access is accepted.
	"""
	_assert_vendor_category_read(company)
	clauses = "1 = 1"
	params: dict = {}
	if vendor:
		clauses = "vc.vendor = %(vendor)s"
		params["vendor"] = vendor
	rows = frappe.db.sql(
		f"""
        SELECT vc.name, vc.vendor, s.supplier_name, vc.category_name,
               vc.display_name, vc.description, vc.is_active
        FROM `tabStabler Vendor Category` vc
        LEFT JOIN `tabSupplier` s ON s.name = vc.vendor
        WHERE {clauses}
        ORDER BY s.supplier_name ASC, vc.category_name ASC
        LIMIT 500
        """,
		params,
		as_dict=True,
	)
	# Boxes and kg travel with the count: the list is where "does this category
	# fill a container?" gets answered, and opening 20 modals to add up 20 rows
	# is the same question asked the slow way.
	totals = {
		r[0]: r
		for r in frappe.db.sql(
			"""
            SELECT parent, COUNT(*), SUM(boxes_per_container),
                   SUM(boxes_per_container * COALESCE(box_kg, 0))
            FROM `tabStabler Vendor Category Item`
            GROUP BY parent
            """
		)
	}
	for r in rows:
		row_totals = totals.get(r["name"])
		r["item_count"] = cint(row_totals[1]) if row_totals else 0
		r["total_boxes"] = cint(row_totals[2]) if row_totals else 0
		r["total_kg"] = flt(row_totals[3], 2) if row_totals else 0.0
	return rows


@frappe.whitelist()
def vendor_category_detail(name: str) -> dict:
	"""One category with its item rows (for the edit modal + PI category fill)."""
	if not name or not frappe.db.exists("Stabler Vendor Category", name):
		frappe.throw(_("Unknown vendor category: {0}").format(name))
	doc = frappe.get_doc("Stabler Vendor Category", name)
	items = []
	for it in doc.items or []:
		meta = frappe.db.get_value("Item", it.item_code, ["item_name", "stock_uom"], as_dict=True) or {}
		items.append(
			{
				"item_code": it.item_code,
				"item_name": meta.get("item_name"),
				"stock_uom": meta.get("stock_uom"),
				"boxes_per_container": cint(it.boxes_per_container),
				"box_kg": flt(it.box_kg, 2),
			}
		)
	return {
		"name": doc.name,
		"vendor": doc.vendor,
		"category_name": doc.category_name,
		"display_name": doc.display_name,
		"description": doc.get("description"),
		"is_active": cint(doc.is_active),
		"items": items,
		"total_boxes_per_container": sum(i["boxes_per_container"] for i in items),
		# Never stored — the row total is boxes × box_kg, derived wherever it is shown.
		"total_kg": flt(sum(i["boxes_per_container"] * i["box_kg"] for i in items), 2),
	}


@frappe.whitelist()
def save_vendor_category(payload, company: str) -> dict:
	"""Create/update a vendor category with its item rows (imports-gated)."""
	_assert_inventory_access(company)
	data = frappe.parse_json(payload) if isinstance(payload, str) else payload
	if not data.get("vendor") or not frappe.db.exists("Supplier", data.get("vendor")):
		frappe.throw(_("A valid supplier is required."))
	if not (data.get("category_name") or "").strip():
		frappe.throw(_("Category name is required."))

	if data.get("name") and frappe.db.exists("Stabler Vendor Category", data["name"]):
		doc = frappe.get_doc("Stabler Vendor Category", data["name"])
	else:
		# MSA parity: (vendor, name) unique — reuse an existing pair instead of duplicating.
		existing = frappe.db.get_value(
			"Stabler Vendor Category",
			{"vendor": data["vendor"], "category_name": data["category_name"].strip()},
			"name",
		)
		doc = (
			frappe.get_doc("Stabler Vendor Category", existing)
			if existing
			else frappe.new_doc("Stabler Vendor Category")
		)
	doc.vendor = data["vendor"]
	doc.category_name = data["category_name"].strip()
	doc.display_name = (data.get("display_name") or data["category_name"]).strip()
	doc.description = data.get("description")
	doc.is_active = cint(data.get("is_active", 1))
	doc.set("items", [])
	for row in data.get("items") or []:
		if not (row or {}).get("item_code"):
			continue
		doc.append(
			"items",
			{
				"item_code": row["item_code"],
				"boxes_per_container": cint(row.get("boxes_per_container")),
				"box_kg": flt(row.get("box_kg")),
			},
		)
	doc.save(ignore_permissions=False)
	return {"name": doc.name}


@frappe.whitelist()
def delete_vendor_category(name: str, company: str) -> dict:
	"""Delete a vendor category (imports-gated; MSA list-page action parity)."""
	_assert_inventory_access(company)
	if not name or not frappe.db.exists("Stabler Vendor Category", name):
		frappe.throw(_("Unknown vendor category: {0}").format(name))
	frappe.delete_doc("Stabler Vendor Category", name, ignore_permissions=False)
	return {"deleted": name}


# ---------------------------------------------------------------------------
# WP-I5 — CI → Purchase Invoice conversion + advance allocation
#
# The seam where virtual import exposure (design doc §3 layer C) becomes real GL
# A/P (layer A). A delivered Commercial Invoice opens a DRAFT Purchase Invoice at
# agreed_total; the advance Payment Entries already paid to the supplier are
# allocated against it (via ERPNext's own set_advances, restricted to this CI's
# import advances). Once the PInv links the CI, supplier_import_exposure stops
# counting the CI's agreed_total in open_commitment — so the same money never
# appears in both exposure and A/P. docs_total (customs) never enters the PInv.
# ---------------------------------------------------------------------------


def _single_container_of(ci_name: str) -> str | None:
	"""The Import Container name when a CI maps to exactly one, else None."""
	names = frappe.get_all("Import Container", filters={"commercial_invoice": ci_name}, pluck="name")
	return names[0] if len(names) == 1 else None


def _ci_conversion_rate(company: str, doc_currency: str, posting_date) -> float:
	"""The rate a Commercial Invoice's bill must carry, for its own posting date.

	The converter used to set `currency` and leave `conversion_rate` to ERPNext,
	which does not fill it server-side — so `validate_purchase_invoice` refused
	the None it was handed: "Conversion rate for USD to UZS cannot be less than
	1000 (got None)". Measured on msa.erpstable.com 2026-08-20: every day from
	the 10th to the 19th carried a CBU rate and the 20th did not, because the
	feed lands during the day. Until it landed, no foreign-currency Commercial
	Invoice could be turned into a bill at all — from the API or the screen.

	Resolved through the validator's own lookup, so the document cannot be built
	carrying a rate its own validation would then reject, and so it inherits the
	same on-or-before fallback. That fallback is what closes the morning window;
	a CI's date is normally weeks in the past, where the feed is complete anyway.

	A missing rate throws rather than defaulting to 1.0, which would post
	380 420 USD into the ledger as 380 420 UZS.
	"""
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or ""
	if not doc_currency or doc_currency == company_currency:
		return 1.0
	rate, _rate_date = _cbu_rate_on_or_before(doc_currency, company_currency, posting_date)
	if not rate:
		frappe.throw(
			_("No exchange rate for {0} to {1} on or before {2}.").format(
				doc_currency, company_currency, formatdate(posting_date)
			)
		)
	return flt(rate)


def _ci_pi_amounts(ci) -> dict[str, float]:
	"""Agreed CI amount attributed to each source Proforma Invoice."""
	amounts: dict[str, float] = {}
	for item in ci.items or []:
		pi_name = item.get("custom_proforma_invoice") or ci.get("custom_proforma_invoice")
		if not pi_name:
			continue
		amounts[pi_name] = round(amounts.get(pi_name, 0.0) + flt(item.amount), 2)
	if not amounts and ci.get("custom_proforma_invoice"):
		amounts[ci.custom_proforma_invoice] = round(flt(ci.agreed_total), 2)
	return amounts


def _draft_advance_reservations(payment_entries: list[str]) -> dict[str, float]:
	"""Amounts already reserved by non-cancelled draft Purchase Invoices."""
	if not payment_entries:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT pia.reference_name, COALESCE(SUM(pia.allocated_amount), 0) AS reserved
		FROM `tabPurchase Invoice Advance` pia
		JOIN `tabPurchase Invoice` pi ON pi.name = pia.parent
		WHERE pi.docstatus = 0
		  AND pia.reference_type = 'Payment Entry'
		  AND pia.reference_name IN %(payments)s
		GROUP BY pia.reference_name
		""",
		{"payments": tuple(payment_entries)},
		as_dict=True,
	)
	return {row["reference_name"]: flt(row["reserved"]) for row in rows}


def _lock_ci_pi_advances(company: str, ci) -> None:
	"""Serialize draft reservations across different CIs sharing one PI credit."""
	pi_names = sorted(_ci_pi_amounts(ci))
	if not pi_names or not frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
		return
	frappe.db.sql(
		"""
		SELECT name
		FROM `tabPayment Entry`
		WHERE company = %(company)s
		  AND party_type = 'Supplier'
		  AND party = %(supplier)s
		  AND custom_proforma_invoice IN %(proformas)s
		  AND docstatus = 1
		FOR UPDATE
		""",
		{"company": company, "supplier": ci.supplier, "proformas": tuple(pi_names)},
	)


def _ci_import_advances(company: str, ci) -> list[dict]:
	"""Submitted supplier advances eligible for one CI.

	PI-linked advances carry their attributed CI amount and contractual percent
	so allocation is capped independently per PI. Container advances remain a
	legacy fallback. Only submitted, unallocated, same-supplier rows qualify.
	"""
	seen: dict[str, dict] = {}
	pi_amounts = _ci_pi_amounts(ci)
	if pi_amounts and frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
		pi_docs = {
			row["name"]: row
			for row in frappe.get_all(
				"Proforma Invoice",
				filters={"name": ["in", list(pi_amounts)]},
				fields=["name", "advance_pct"],
			)
		}
		payment_rows = frappe.get_all(
			"Payment Entry",
			filters={
				"company": company,
				"party_type": "Supplier",
				"party": ci.supplier,
				"custom_proforma_invoice": ["in", list(pi_amounts)],
				"docstatus": 1,
				"unallocated_amount": [">", 0],
			},
			fields=[
				"name",
				"unallocated_amount",
				"party",
				"posting_date",
				"custom_proforma_invoice",
			],
			order_by="posting_date asc, name asc",
		)
		for adv in payment_rows:
			pi_name = adv["custom_proforma_invoice"]
			seen[adv["name"]] = {
				"name": adv["name"],
				"unallocated_amount": flt(adv["unallocated_amount"]),
				"party": adv["party"],
				"proforma_invoice": pi_name,
				"ci_amount": flt(pi_amounts[pi_name]),
				"advance_percentage": flt((pi_docs.get(pi_name) or {}).get("advance_pct")),
				"posting_date": str(adv["posting_date"]) if adv["posting_date"] else None,
			}
	containers = frappe.get_all(
		"Import Container",
		filters={"commercial_invoice": ci.name},
		fields=["name", "advance_70_payment_entry"],
	)
	for c in containers:
		for adv in _container_advances(company, c["name"], c.get("advance_70_payment_entry")):
			if cint(adv.get("docstatus")) != 1:
				continue
			if flt(adv.get("unallocated_amount")) <= 0:
				continue
			if (adv.get("party") or "") != (ci.supplier or ""):
				continue
			# A PI-linked advance may also be the container's legacy advance.
			# Preserve the PI metadata in that case: replacing it with the generic
			# fallback would remove the contractual proportional-allocation cap.
			seen.setdefault(
				adv["name"],
				{
					"name": adv["name"],
					"unallocated_amount": flt(adv.get("unallocated_amount")),
					"party": adv.get("party"),
				},
			)
	reservations = _draft_advance_reservations(list(seen))
	for name, row in seen.items():
		row["reserved_amount"] = flt(reservations.get(name))
	return sorted(seen.values(), key=lambda row: (row.get("posting_date") or "", row["name"]))


def _restrict_advances_to_import(doc, import_allocations) -> float:
	"""Populate the PInv's advances via ERPNext, then keep only this CI's import
	advances and cap them to the reviewed plan. ``set`` input is retained for
	the re-book path; conversion passes ``[{payment_entry, amount}]``. Returns
	the total allocated. Degrades safely when ERPNext cannot load advances."""
	if isinstance(import_allocations, set):
		wanted = import_allocations
		caps = None
	else:
		caps = {
			row["payment_entry"]: flt(row["amount"])
			for row in (import_allocations or [])
			if row.get("payment_entry")
		}
		wanted = set(caps)
	try:
		doc.set_advances()
	except Exception:
		doc.set("advances", [])
		return 0.0
	kept = []
	total = 0.0
	for row in doc.get("advances") or []:
		if row.reference_type == "Payment Entry" and row.reference_name in wanted:
			if caps is not None:
				row.allocated_amount = min(flt(row.allocated_amount), caps[row.reference_name])
			kept.append(row)
			total += flt(row.allocated_amount)
	doc.set("advances", kept)
	return round(total, 2)


def _ci_advance_share(ci) -> dict:
	"""How much of the PI advance belongs to THIS Commercial Invoice.

	Read-only and deliberately narrow: one row per source Proforma Invoice, the
	PI's other CIs never appear, and no action is offered here (the CI → Purchase
	Invoice conversion lives on the Suppliers page). Three honest states:

	  * ``planned``  — no Purchase Invoice yet; the share is proportional only
	    (``ci_amount × advance_pct``) and has touched no ledger.
	  * ``reserved`` — a draft Purchase Invoice holds the allocation.
	  * ``posted``   — a submitted Purchase Invoice has it in the GL.

	The word "applied" belongs to the ``posted`` branch alone — reading a planned
	figure as booked money is the only real risk this card carries.

	Each row also carries three **PI-level** facts the user asked for next to the
	share: how much advance the supplier has actually been paid against that
	Proforma (``pi_advance_paid``), how much of it any Purchase Invoice has taken
	(``pi_advance_allocated``), and when the payment is expected
	(``expected_payment_date``). They are single aggregates about the source PI —
	the PI's other Commercial Invoices are still never listed here.

	All three PI links are keyed on ``Payment Entry.custom_proforma_invoice``, the
	same field the booked figure above uses. ``_po_advance_payment_entries`` also
	honours ``Payment Entry Reference`` rows; matching that here would make the two
	halves of this one card key on different links, which is the worse divergence.
	"""
	pi_amounts = _ci_pi_amounts(ci)
	pi_names = sorted(pi_amounts)

	invoice = None
	if frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice"):
		rows = frappe.get_all(
			"Purchase Invoice",
			filters={
				"custom_commercial_invoice": ci.name,
				"supplier": ci.supplier,
				"docstatus": ["<", 2],
			},
			fields=["name", "docstatus"],
			order_by="docstatus desc, creation desc",
			limit=1,
		)
		invoice = rows[0] if rows else None

	booked: dict[str, float] = {}
	if invoice and pi_names and frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
		# Submitted Payment Entries no longer have an unallocated balance, so
		# deriving this from `_ci_import_advances` would make a real $90k
		# allocation disappear from the card after Accounts posts it. Grouping
		# the existing scalar sum by PI keeps that total identical.
		for pi_name, amount in frappe.db.sql(
			"""
			SELECT pe.custom_proforma_invoice, COALESCE(SUM(pia.allocated_amount), 0)
			FROM `tabPurchase Invoice Advance` pia
			JOIN `tabPayment Entry` pe
			  ON pe.name = pia.reference_name
			 AND pia.reference_type = 'Payment Entry'
			WHERE pia.parent = %(purchase_invoice)s
			  AND pe.custom_proforma_invoice IN %(proformas)s
			GROUP BY pe.custom_proforma_invoice
			""",
			{"purchase_invoice": invoice["name"], "proformas": tuple(pi_names)},
		):
			booked[pi_name] = flt(amount)

	pi_paid: dict[str, float] = {}
	pi_allocated: dict[str, float] = {}
	if pi_names and frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
		for pi_name, amount in frappe.db.sql(
			"""
			SELECT pe.custom_proforma_invoice, COALESCE(SUM(pe.paid_amount), 0)
			FROM `tabPayment Entry` pe
			WHERE pe.company = %(company)s
			  AND pe.docstatus = 1
			  AND pe.custom_proforma_invoice IN %(proformas)s
			GROUP BY pe.custom_proforma_invoice
			""",
			{"company": ci.company, "proformas": tuple(pi_names)},
		):
			pi_paid[pi_name] = flt(amount)

		# Allocation lives in the child table, not in `unallocated_amount`: Frappe
		# only rewrites that on submit, so a draft Purchase Invoice's reservation
		# would read as unallocated. `docstatus < 2` drops cancelled invoices.
		for pi_name, amount in frappe.db.sql(
			"""
			SELECT pe.custom_proforma_invoice, COALESCE(SUM(pia.allocated_amount), 0)
			FROM `tabPurchase Invoice Advance` pia
			JOIN `tabPayment Entry` pe
			  ON pe.name = pia.reference_name
			 AND pia.reference_type = 'Payment Entry'
			JOIN `tabPurchase Invoice` pinv
			  ON pinv.name = pia.parent
			 AND pinv.docstatus < 2
			WHERE pe.custom_proforma_invoice IN %(proformas)s
			GROUP BY pe.custom_proforma_invoice
			""",
			{"proformas": tuple(pi_names)},
		):
			pi_allocated[pi_name] = flt(amount)

	planned: dict[str, float] = {}
	if not invoice:
		advances = _ci_import_advances(ci.company, ci)
		plan = _ci_to_pinv.plan_advance_allocation(flt(ci.agreed_total), advances)
		planned = _ci_to_pinv.allocation_by_proforma(plan["allocations"], advances)

	is_posted = bool(invoice) and cint(invoice["docstatus"]) == 1
	# The date field ships with this card; a site whose migrate has not run yet
	# must still render the rest of the row instead of throwing on the column.
	meta_fields = ["name", "advance_pct", "supplier_pi_ref"]
	if frappe.db.has_column("Proforma Invoice", "expected_payment_date"):
		meta_fields.append("expected_payment_date")
	meta_rows = (
		frappe.get_all(
			"Proforma Invoice",
			filters={"name": ["in", pi_names]},
			fields=meta_fields,
		)
		if pi_names
		else []
	)
	pi_meta = {row["name"]: row for row in meta_rows}

	sources = []
	for pi_name in pi_names:
		meta = pi_meta.get(pi_name) or {}
		amount = flt(booked.get(pi_name)) if invoice else flt(planned.get(pi_name))
		sources.append(
			{
				"proforma_invoice": pi_name,
				"supplier_pi_ref": meta.get("supplier_pi_ref"),
				"ci_amount": flt(pi_amounts[pi_name]),
				"advance_pct": flt(meta.get("advance_pct")),
				"expected_payment_date": meta.get("expected_payment_date"),
				"pi_advance_paid": flt(pi_paid.get(pi_name)),
				"pi_advance_allocated": flt(pi_allocated.get(pi_name)),
				"planned": 0.0 if invoice else amount,
				"reserved": amount if invoice and not is_posted else 0.0,
				"posted": amount if is_posted else 0.0,
			}
		)

	def _total(key: str) -> float:
		return round(sum(flt(row[key]) for row in sources), 2)

	return {
		"state": "posted" if is_posted else ("reserved" if invoice else "planned"),
		"currency": ci.get("currency"),
		"ci_total": flt(ci.agreed_total),
		"advance_planned": _total("planned"),
		"advance_reserved": _total("reserved"),
		"advance_posted": _total("posted"),
		"purchase_invoice": invoice["name"] if invoice else None,
		"sources": sources,
	}


@frappe.whitelist()
def convert_ci_to_purchase_invoice(commercial_invoice: str, company: str, dry_run: int = 1) -> dict:
	"""Convert a Commercial Invoice into a DRAFT Purchase Invoice at agreed_total.

	``dry_run`` (default 1): compute and return the plan — invoice lines, grand
	total, agreed_total reconciliation, the import advances found and how they
	would allocate — WITHOUT writing anything. ``dry_run=0`` creates the DRAFT
	Purchase Invoice (NEVER submitted here: Accounts reviews and posts to GL, at
	which point the CI leaves virtual exposure). ``docs_total`` (customs) is
	reported for transparency but never enters the invoice.

	Idempotent: if a non-cancelled Purchase Invoice already links this CI, it is
	returned unchanged. Imports-gated + cost-visible (agreed/advance are K3).
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	if ci.company != company:
		frappe.throw(_("Commercial Invoice belongs to a different company."))
	if not ci.supplier:
		frappe.throw(_("The Commercial Invoice has no supplier."))
	if (ci.status or "") == "Cancelled":
		frappe.throw(_("A cancelled Commercial Invoice cannot be invoiced."))

	has_pi_ref = frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")
	if has_pi_ref:
		# WP-I9 — serialize concurrent converts. Two users clicking Confirm at
		# the same moment would both pass the duplicate check below and create
		# two draft invoices for one CI. Locking the CI row (SELECT … FOR
		# UPDATE) makes the second transaction wait; when it proceeds it sees
		# the first one's Purchase Invoice and returns it instead. Previews
		# (dry_run) stay lock-free — they never write.
		if not cint(dry_run):
			frappe.db.get_value("Commercial Invoice", commercial_invoice, "name", for_update=True)
		# The CI ref alone no longer identifies THE goods invoice: a transporter's
		# or a service provider's bill can be attributed to the same Commercial
		# Invoice, and the truck-transport automation already books such a PI
		# against the trucking company. Only the invoice raised by the CI's own
		# supplier is the one this endpoint would otherwise duplicate — without
		# the supplier filter a freight bill would be returned as "already
		# linked" and the goods payable would never be opened at all.
		existing = frappe.db.get_value(
			"Purchase Invoice",
			{
				"custom_commercial_invoice": commercial_invoice,
				"supplier": ci.supplier,
				"docstatus": ["<", 2],
			},
			"name",
		)
		if existing:
			return {"purchase_invoice": existing, "created": False, "already_linked": True}

	lines = _ci_to_pinv.pinv_lines_from_ci_items(
		[
			{"item": it.item, "qty": flt(it.qty), "rate": flt(it.rate), "amount": flt(it.amount)}
			for it in (ci.items or [])
		]
	)
	total = _ci_to_pinv.lines_total(lines)
	agreed = flt(ci.agreed_total)
	reconciled = _ci_to_pinv.reconciles(total, agreed)

	if not cint(dry_run):
		_lock_ci_pi_advances(company, ci)
	advances = _ci_import_advances(company, ci)
	plan = _ci_to_pinv.plan_advance_allocation(agreed if reconciled else total, advances)

	preview = {
		"commercial_invoice": commercial_invoice,
		"supplier": ci.supplier,
		"currency": ci.currency,
		"agreed_total": agreed,
		"lines_total": total,
		"reconciles_agreed": reconciled,
		"lines": lines,
		"advances_found": advances,
		"advance_plan": plan,
		"docs_total_excluded": flt(ci.docs_total),
	}
	if not reconciled:
		preview["warning"] = _(
			"CI line total {0} does not match agreed_total {1}; resolve before invoicing."
		).format(total, agreed)

	if cint(dry_run):
		preview["created"] = False
		preview["dry_run"] = True
		return preview

	if not lines:
		frappe.throw(_("The Commercial Invoice has no invoiceable item lines."))
	if not reconciled:
		frappe.throw(preview["warning"])

	doc = frappe.new_doc("Purchase Invoice")
	doc.company = company
	doc.supplier = ci.supplier
	# The CI's own date, not the clock. `getdate(today())` dated a six-month-old
	# import bill today, which is wrong twice over: the payable belongs to the
	# month the supplier invoiced, and once the bill updates stock its posting
	# date IS the day the goods enter the ledger — so today's date also valued
	# them at today's rate. `set_posting_time` is what makes the date stick;
	# without it ERPNext overwrites it with now (transaction_base.py).
	doc.set_posting_time = 1
	doc.posting_date = getdate(ci.ci_date or today())
	if ci.currency:
		doc.currency = ci.currency
		doc.conversion_rate = _ci_conversion_rate(company, ci.currency, doc.posting_date)
	if has_pi_ref:
		doc.custom_commercial_invoice = commercial_invoice
	container = _single_container_of(commercial_invoice)
	if container and frappe.db.has_column("Purchase Invoice", "custom_import_container"):
		doc.custom_import_container = container
	for ln in lines:
		doc.append(
			"items",
			{"item_code": ln["item_code"], "qty": ln["qty"] or 1, "rate": ln["rate"]},
		)
	doc.insert(ignore_permissions=False)

	# Guard: the A/P we open MUST equal the agreed payable. If ERPNext's
	# qty×rate recompute drifts beyond a kuruş, refuse — never post a silently
	# wrong A/P (weak-currency truncation, multi-currency rules).
	if not _ci_to_pinv.reconciles(flt(doc.grand_total), agreed):
		frappe.db.rollback()
		frappe.throw(
			_("Purchase Invoice total {0} drifted from agreed_total {1}; not created.").format(
				flt(doc.grand_total), agreed
			)
		)

	allocated = _restrict_advances_to_import(doc, plan["allocations"])
	doc.save(ignore_permissions=False)

	return {
		"purchase_invoice": doc.name,
		"created": True,
		"grand_total": flt(doc.grand_total),
		"agreed_total": agreed,
		"reconciles_agreed": True,
		"advance_allocated": allocated,
		"advances_found": [a["name"] for a in advances],
	}


@frappe.whitelist()
def ci_invoice_drift(company: str, commercial_invoice: str | None = None) -> dict:
	"""Where a Commercial Invoice and its booked Purchase Invoice disagree.

	A submitted Purchase Invoice is immutable, but the CI behind it keeps being
	corrected — a rate is fixed, a line is added, quantities are re-counted.
	The A/P then describes a deal nobody agreed to any more. This reports every
	such divergence; it repairs nothing (re-booking cancels GL vouchers and
	un-allocates payments — that is an explicit, approved action, never a
	side effect of opening a screen).

	The Purchase Invoice IS the snapshot of what was booked, so nothing is
	fingerprinted or cached: the comparison is always against live GL truth,
	which also makes historically imported invoices comparable.

	``commercial_invoice`` narrows to one CI; otherwise the whole book.
	Read-only, imports-gated, cost-visible (agreed figures are K3).
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	if not frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice"):
		return {"rows": [], "summary": {"checked": 0, "drifting": 0, "delta_total": 0.0}, "available": False}
	return _ci_invoice_drift(company, commercial_invoice)


def _ci_invoice_drift(company: str, commercial_invoice: str | None = None) -> dict:
	"""Unwhitelisted core of ci_invoice_drift (callers have already gated)."""

	filters = {"company": company, "docstatus": ["<", 2], "custom_commercial_invoice": ["!=", ""]}
	if commercial_invoice:
		filters["custom_commercial_invoice"] = commercial_invoice
	invoices = frappe.get_all(
		"Purchase Invoice",
		filters=filters,
		fields=["name", "custom_commercial_invoice", "grand_total", "docstatus", "posting_date", "supplier"],
		limit_page_length=0,
	)
	if not invoices:
		return {"rows": [], "summary": {"checked": 0, "drifting": 0, "delta_total": 0.0}, "available": True}

	ci_names = [inv["custom_commercial_invoice"] for inv in invoices]
	ci_rows = frappe.get_all(
		"Commercial Invoice",
		filters={"name": ["in", ci_names]},
		fields=["name", "agreed_total", "ci_number", "ci_date", "supplier"],
		limit_page_length=0,
	)
	agreed_of = {
		row["name"]: (flt(row["agreed_total"]), row.get("ci_number"), row.get("ci_date")) for row in ci_rows
	}

	# A Commercial Invoice can now carry bills raised by OTHER parties — a
	# transporter's freight invoice, a service provider's fee — attributed to
	# the same CI. Only the invoice from the CI's own supplier is the booked
	# snapshot of the agreed deal, so only that one may be compared against
	# agreed_total: a freight bill measured against the goods total reads as
	# drifting by its entire value. This report is not merely cosmetic —
	# rebook_ci_invoice acts on exactly these rows and would CANCEL that
	# transporter's invoice and re-book it with the goods lines. Rows whose CI
	# carries no supplier at all are kept: that is a separate defect, and
	# dropping them would hide drift the report exists to surface.
	ci_supplier_of = {row["name"]: row.get("supplier") for row in ci_rows}
	kept = []
	for inv in invoices:
		ci_supplier = ci_supplier_of.get(inv["custom_commercial_invoice"])
		if ci_supplier and inv.get("supplier") != ci_supplier:
			continue
		kept.append(inv)
	invoices = kept
	if not invoices:
		return {"rows": [], "summary": {"checked": 0, "drifting": 0, "delta_total": 0.0}, "available": True}

	# Line rows for both sides, one query each — never per invoice.
	ci_lines: dict[str, list] = {}
	for row in frappe.get_all(
		"Commercial Invoice Item",
		filters={"parent": ["in", ci_names]},
		fields=["parent", "item", "qty", "amount"],
		limit_page_length=0,
	):
		ci_lines.setdefault(row["parent"], []).append(
			{"item_code": row.get("item"), "qty": flt(row.get("qty")), "amount": flt(row.get("amount"))}
		)
	pinv_lines: dict[str, list] = {}
	for row in frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", [inv["name"] for inv in invoices]]},
		fields=["parent", "item_code", "qty", "amount"],
		limit_page_length=0,
	):
		pinv_lines.setdefault(row["parent"], []).append(
			{"item_code": row.get("item_code"), "qty": flt(row.get("qty")), "amount": flt(row.get("amount"))}
		)

	rows = []
	delta_sum = 0.0
	for inv in invoices:
		ci = inv["custom_commercial_invoice"]
		agreed, ci_number, ci_date = agreed_of.get(ci, (0.0, None, None))
		drift = _ci_to_pinv.invoice_drift(
			agreed, ci_lines.get(ci, []), flt(inv["grand_total"]), pinv_lines.get(inv["name"], [])
		)
		if drift["in_sync"]:
			continue
		delta_sum += drift["delta_total"]
		rows.append(
			{
				"commercial_invoice": ci,
				"ci_number": ci_number or ci,
				"ci_date": str(ci_date) if ci_date else None,
				"purchase_invoice": inv["name"],
				"supplier": inv.get("supplier"),
				"posting_date": str(inv["posting_date"]) if inv.get("posting_date") else None,
				"submitted": cint(inv["docstatus"]) == 1,
				**drift,
			}
		)
	rows.sort(key=lambda r: abs(r["delta_total"]), reverse=True)
	return {
		"rows": rows,
		"summary": {
			"checked": len(invoices),
			"drifting": len(rows),
			"delta_total": round(delta_sum, 2),
		},
		"available": True,
	}


def _allocated_payments(purchase_invoice: str) -> list[dict]:
	"""Submitted Payment Entries currently allocated to an invoice.

	These are the payments a re-booking would knock loose; they must land on
	the replacement invoice or the supplier's balance jumps.
	"""
	return frappe.db.sql(
		"""
		SELECT per.parent AS name, per.allocated_amount
		FROM `tabPayment Entry Reference` per
		JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Purchase Invoice'
		  AND per.reference_name = %(inv)s
		  AND pe.docstatus = 1
		ORDER BY pe.posting_date ASC, pe.name ASC
		""",
		{"inv": purchase_invoice},
		as_dict=True,
	)


@frappe.whitelist()
def rebook_ci_invoice(commercial_invoice: str, company: str, dry_run: int = 1) -> dict:
	"""Cancel a drifted Purchase Invoice and re-book it from the CI as it is now.

	``dry_run`` (default 1) returns the plan and writes NOTHING: what will be
	cancelled, which payments come loose, the new total and lines, and how those
	payments re-allocate. Only ``dry_run=0`` acts.

	The sequence, in one transaction:
	  1. re-check the drift (someone may have fixed it meanwhile)
	  2. cancel the old invoice — its GL reverses, its payments go unallocated
	  3. create the replacement from the CI's CURRENT lines, dated ci_date,
	     ``amended_from`` the cancelled one so the audit trail survives
	  4. guard: the new A/P must equal agreed_total, else roll the whole thing
	     back — a hole in the ledger is worse than a stale invoice
	  5. re-allocate exactly the payments that were on the old invoice
	  6. submit only if the old one was submitted (never leave the supplier
	     with no payable where one existed)

	Refuses rather than guesses: lines that don't reconcile to agreed_total, a
	CI without ci_date, or ERPNext configured to block payment unlinking all
	stop the operation with a named reason.
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	if not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
	if ci.company != company:
		frappe.throw(_("Commercial Invoice belongs to a different company."))

	report = _ci_invoice_drift(company, commercial_invoice)
	row = (report.get("rows") or [None])[0]
	if not row:
		return {"changed": False, "reason": "in_sync", "commercial_invoice": commercial_invoice}

	old_name = row["purchase_invoice"]
	old = frappe.get_doc("Purchase Invoice", old_name)
	agreed = flt(ci.agreed_total)
	lines = _ci_to_pinv.pinv_lines_from_ci_items(
		[
			{"item": it.item, "qty": flt(it.qty), "rate": flt(it.rate), "amount": flt(it.amount)}
			for it in (ci.items or [])
		]
	)
	blockers = []
	if not lines:
		blockers.append(_("The Commercial Invoice has no invoiceable item lines."))
	if not _ci_to_pinv.reconciles(_ci_to_pinv.lines_total(lines), agreed):
		blockers.append(
			_("CI line total {0} does not match agreed_total {1}; fix the invoice first.").format(
				_ci_to_pinv.lines_total(lines), agreed
			)
		)
	if not ci.ci_date:
		blockers.append(_("The Commercial Invoice has no date; the replacement cannot be dated."))
	payments = _allocated_payments(old_name)
	if payments and not cint(
		frappe.db.get_single_value("Accounts Settings", "unlink_payment_on_cancellation_of_invoice")
	):
		blockers.append(
			_("Accounts Settings blocks unlinking payments on cancellation; enable it or unallocate first.")
		)

	plan = {
		"commercial_invoice": commercial_invoice,
		"old_invoice": old_name,
		"old_total": flt(old.grand_total),
		"old_submitted": cint(old.docstatus) == 1,
		"new_total": agreed,
		"delta_total": row["delta_total"],
		"lines": lines,
		"payments_to_reallocate": payments,
		"payments_total": round(sum(flt(p["allocated_amount"]) for p in payments), 2),
		"posting_date": str(ci.ci_date) if ci.ci_date else None,
		"blockers": blockers,
	}
	if cint(dry_run):
		plan["changed"] = False
		plan["dry_run"] = True
		return plan
	if blockers:
		frappe.throw(blockers[0])

	_assert_can_write("Purchase Invoice", old_name, "cancel")
	# Serialize against a concurrent convert/rebook on the same CI.
	frappe.db.get_value("Commercial Invoice", commercial_invoice, "name", for_update=True)

	old.cancel()
	doc = frappe.new_doc("Purchase Invoice")
	doc.company = company
	doc.supplier = ci.supplier
	if ci.currency:
		doc.currency = ci.currency
	doc.set_posting_time = 1
	doc.posting_date = getdate(ci.ci_date)
	doc.bill_date = getdate(ci.ci_date)
	doc.bill_no = old.bill_no or commercial_invoice
	doc.amended_from = old_name
	if frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice"):
		doc.custom_commercial_invoice = commercial_invoice
	container = _single_container_of(commercial_invoice)
	if container and frappe.db.has_column("Purchase Invoice", "custom_import_container"):
		doc.custom_import_container = container
	for ln in lines:
		doc.append("items", {"item_code": ln["item_code"], "qty": ln["qty"] or 1, "rate": ln["rate"]})
	doc.insert(ignore_permissions=False)

	if not _ci_to_pinv.reconciles(flt(doc.grand_total), agreed):
		frappe.db.rollback()
		frappe.throw(
			_("Replacement invoice total {0} drifted from agreed_total {1}; nothing was changed.").format(
				flt(doc.grand_total), agreed
			)
		)

	# The payments that were on the old invoice come first; whatever import
	# advances remain may top up the rest.
	wanted = {p["name"] for p in payments} | {a["name"] for a in _ci_import_advances(company, ci)}
	allocated = _restrict_advances_to_import(doc, wanted)
	doc.save(ignore_permissions=False)
	if plan["old_submitted"]:
		doc.submit()  # the ledger must not be left without the payable it had

	plan.update(
		{
			"changed": True,
			"dry_run": False,
			"new_invoice": doc.name,
			"new_grand_total": flt(doc.grand_total),
			"reallocated": allocated,
			"submitted": plan["old_submitted"],
		}
	)
	return plan


@frappe.whitelist()
def import_advance_aging(company: str) -> dict:
	"""Unallocated supplier advances aged against the repatriation horizon (WP-I10).

	Uzbek currency control expects an import advance to be closed (goods arrive /
	money returns) within the contract term — commonly 180 days. Rows are the
	submitted supplier Payment Entries whose ``unallocated_amount`` is still
	positive, annotated OK / WARN (>=150d) / BREACH (>=180d), oldest first.
	Imports-gated + cost-visible (advance figures are K3).
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	rows = frappe.db.sql(
		"""
        SELECT pe.name, pe.party, s.supplier_name, pe.posting_date,
               pe.paid_amount, pe.unallocated_amount,
               pe.paid_to_account_currency AS currency, pe.reference_no
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabSupplier` s ON s.name = pe.party
        WHERE pe.company = %(company)s AND pe.party_type = 'Supplier'
          AND pe.docstatus = 1 AND pe.payment_type = 'Pay'
          AND pe.unallocated_amount > 0
        ORDER BY pe.posting_date ASC
        LIMIT 500
        """,
		{"company": company},
		as_dict=True,
	)
	for r in rows:
		r["posting_date"] = str(r["posting_date"]) if r.get("posting_date") else None
		r["paid_amount"] = flt(r.get("paid_amount"))
		r["unallocated_amount"] = flt(r.get("unallocated_amount"))
	annotated = _advance_aging.aging_rows(rows, today())
	return {
		"rows": annotated,
		"summary": _advance_aging.aging_summary(annotated),
		"warn_days": _advance_aging.WARN_DAYS,
		"breach_days": _advance_aging.BREACH_DAYS,
	}


@frappe.whitelist()
def fx_revaluation_preview(company: str, closing_rate=None) -> dict:
	"""Period-end unrealized-FX preview on open foreign-currency payables (WP-I11).

	IAS 21: only MONETARY items are retranslated — open Purchase Invoice
	balances. Advances paid for goods are non-monetary (their rate froze on
	payment day) and are deliberately absent from this query. Preview only:
	nothing is posted; the accountant books the revaluation JE after review.
	``closing_rate`` (company currency per 1 foreign unit) may be passed; when
	omitted, each currency's latest rate is resolved via ERPNext.
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	company_ccy = frappe.get_cached_value("Company", company, "default_currency")
	rows = frappe.db.sql(
		"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.currency,
               pi.outstanding_amount AS outstanding_foreign,
               pi.conversion_rate AS booked_rate, pi.posting_date, pi.due_date
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.company = %(company)s AND pi.docstatus = 1
          AND pi.outstanding_amount > 0 AND pi.currency != %(ccy)s
        ORDER BY pi.posting_date ASC
        LIMIT 500
        """,
		{"company": company, "ccy": company_ccy},
		as_dict=True,
	)
	rates: dict[str, float] = {}
	override = flt(closing_rate) if closing_rate else 0.0
	for r in rows:
		ccy = r.get("currency")
		if override:
			rates[ccy] = override
		elif ccy not in rates:
			try:
				from erpnext.setup.utils import get_exchange_rate

				rates[ccy] = flt(get_exchange_rate(ccy, company_ccy))
			except Exception:
				rates[ccy] = 0.0
		r["posting_date"] = str(r["posting_date"]) if r.get("posting_date") else None
		r["due_date"] = str(r["due_date"]) if r.get("due_date") else None

	annotated: list[dict] = []
	for ccy, rate in rates.items():
		bucket = [r for r in rows if r.get("currency") == ccy]
		if rate <= 0:
			for r in bucket:
				r.update({"closing_rate": 0, "unrealized_loss": 0, "rate_missing": True})
			annotated.extend(bucket)
		else:
			annotated.extend(_fx_reval.reval_rows(bucket, rate))

	return {
		"company_currency": company_ccy,
		"closing_rates": rates,
		"rows": annotated,
		"summary": _fx_reval.reval_summary([r for r in annotated if not r.get("rate_missing")]),
		"note": "Advances excluded (IAS 21 non-monetary); preview only — no GL posting.",
	}


@frappe.whitelist()
def customs_cost_estimate(commercial_invoice: str) -> dict:
	"""Pre-declaration boj/excise/VAT estimate from the HS Duty Rate table (WP-I13).

	Planning number only — once the GTD clears, its figures are authoritative
	(the LCV already prefers GTD amounts). Customs value = declared (bank) goods
	value scaled onto items + the transport bank leg when earmarked. Unrated HS
	codes are reported so the rate table can be completed.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	company = _company_of("Commercial Invoice", commercial_invoice)
	_assert_imports_access(company)
	_assert_cost_visible()
	ci = frappe.get_doc("Commercial Invoice", commercial_invoice)

	declared = flt(ci.docs_total) or flt(ci.get("custom_bank_agreed"))
	items = _customs_estimate.scale_to_declared(
		[{"item": it.item, "hs_code": it.hs_code, "amount": flt(it.amount)} for it in (ci.items or [])],
		declared,
	)

	rates: dict[str, dict] = {}
	if frappe.db.exists("DocType", "HS Duty Rate"):
		for r in frappe.get_all(
			"HS Duty Rate",
			filters={"effective_from": ["<=", today()]},
			fields=["hs_code", "duty_pct", "excise_pct", "vat_pct", "effective_from"],
			order_by="effective_from asc",
		):
			rates[(r.hs_code or "").strip()] = r  # later effective_from wins

	vat_pct = 12.0
	for r in rates.values():
		if flt(r.get("vat_pct")):
			vat_pct = flt(r.get("vat_pct"))
			break

	est = _customs_estimate.estimate(items, rates, transport_bank=0, default_vat_pct=vat_pct)
	est.update(
		{
			"commercial_invoice": commercial_invoice,
			"declared_total": flt(declared),
			"declared_source": "docs_total" if flt(ci.docs_total) else "custom_bank_agreed",
			"authoritative": False,
			"note": _("Estimate from the HS rate table; the cleared GTD remains authoritative."),
		}
	)
	return est


@frappe.whitelist()
def customs_amendment_preview(amendment: str) -> dict:
	"""Route a KTS post-clearance customs amendment into its GL buckets (WP-I15).

	``amendment`` is a Customs Declaration whose ``custom_amendment_of`` points
	at the original cleared GTD. Compares the two and splits the delta: extra
	duty + excise capitalize into stock (delta LCV), extra VAT to Input VAT
	(asset), penalty to P&L (IAS 2 — abnormal cost, never stock). Preview only:
	nothing posts and the original GTD is never edited (audit trail). The
	accountant books the delta LCV + JE after review. Imports-gated + cost-visible.
	"""
	if not amendment or not frappe.db.exists("Customs Declaration", amendment):
		frappe.throw(_("Unknown Customs Declaration: {0}").format(amendment))
	company = _company_of("Customs Declaration", amendment)
	_assert_imports_access(company)
	_assert_cost_visible()
	amd = frappe.get_doc("Customs Declaration", amendment)
	original_name = amd.get("custom_amendment_of")
	if not original_name:
		frappe.throw(_("This declaration is not an amendment (no original GTD linked)."))
	if not frappe.db.exists("Customs Declaration", original_name):
		frappe.throw(_("Original GTD {0} not found.").format(original_name))
	orig = frappe.get_doc("Customs Declaration", original_name)

	delta = _kts_amendment.amendment_delta(
		{
			"duty_amount": flt(orig.duty_amount),
			"excise_amount": flt(orig.excise_amount),
			"vat_amount": flt(orig.vat_amount),
		},
		{
			"duty_amount": flt(amd.duty_amount),
			"excise_amount": flt(amd.excise_amount),
			"vat_amount": flt(amd.vat_amount),
		},
		penalty=flt(amd.get("custom_penalty_amount")),
	)
	return {
		"amendment": amendment,
		"original_gtd": original_name,
		"commercial_invoice": amd.get("commercial_invoice"),
		"reason": amd.get("custom_amendment_reason"),
		"delta": delta,
		"routing": _kts_amendment.gl_routing(delta),
		"authoritative": False,
		"note": _(
			"Preview only. Book the capitalized delta via an additional Landed "
			"Cost Voucher, the VAT delta to Input VAT, and any penalty to P&L."
		),
	}


# ---------------------------------------------------------------------------
# WP-I14 — Unbilled landed-cost accrual report
# ---------------------------------------------------------------------------


@frappe.whitelist()
def unbilled_landed_costs(company: str) -> dict:
	"""Month-end accrual candidates — costs known but not yet in an LCV/GL.

	Container Cost Line rows flagged ``include_in_landed_cost`` with an empty
	``lcv_ref`` are costs the business has already agreed to (freight, customs,
	demurrage, ...) but that have not yet been capitalized into a Landed Cost
	Voucher. At month-end close these are the accrual candidates: costs known
	but not yet posted to the GL. Mirrors the ``container_cost_summary``
	convention of summing ``amount`` as-is (single-currency, USD-dominant, no
	FX conversion).
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	rows = frappe.db.sql(
		"""
        SELECT cl.name, cl.parent AS container, c.container_number,
               c.commercial_invoice, cl.cost_component, cl.description,
               cl.currency, cl.amount, cl.amount_uzs
        FROM `tabContainer Cost Line` cl
        INNER JOIN `tabImport Container` c ON c.name = cl.parent
        WHERE c.company = %(company)s
          AND cl.include_in_landed_cost = 1
          AND (cl.lcv_ref IS NULL OR cl.lcv_ref = '')
        ORDER BY c.container_number ASC, cl.idx ASC
        LIMIT 500
        """,
		{"company": company},
		as_dict=True,
	)
	total_unbilled = 0.0
	for r in rows:
		r["amount"] = flt(r["amount"])
		r["amount_uzs"] = flt(r["amount_uzs"])
		total_unbilled += r["amount"]
	return {
		"rows": rows,
		"summary": {"total_unbilled": round(total_unbilled, 2), "rows": len(rows)},
	}


# ---------------------------------------------------------------------------
# WP-I16 — Channel payment calendar (bank vs cash settlement split)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def payment_calendar(company: str, days: int = 30) -> dict:
	"""Upcoming + overdue supplier bills, split by settlement channel (WP-I16).

	Submitted Purchase Invoices with an outstanding balance due within the next
	``days`` (or already overdue) form the payment calendar. Each bill is then
	split into a bank-settled and cash-settled share by looking up its earmarked
	Commercial Invoice (v46 ``custom_commercial_invoice`` ref) and that CI's
	cash/bank agreement (WP-I3b ``custom_bank_agreed`` / ``custom_cash_agreed``).
	A bill with no CI ref cannot be split — it is reported ``unsplit`` and
	counted entirely against the bank channel (the conservative assumption).
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	today_d = today()
	upper = add_days(today_d, cint(days))

	has_ci_ref = frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")
	has_bank = frappe.db.has_column("Commercial Invoice", "custom_bank_agreed")
	has_cash = frappe.db.has_column("Commercial Invoice", "custom_cash_agreed")

	ci_col = "pi.custom_commercial_invoice" if has_ci_ref else "NULL"
	rows = frappe.db.sql(
		f"""
        SELECT pi.name, pi.supplier, s.supplier_name, pi.due_date,
               pi.outstanding_amount, pi.currency, {ci_col} AS commercial_invoice
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE pi.company = %(company)s AND pi.docstatus = 1
          AND pi.outstanding_amount > 0
          AND (pi.due_date <= %(upper)s OR pi.due_date < %(today)s)
        ORDER BY pi.due_date ASC
        LIMIT 500
        """,
		{"company": company, "upper": upper, "today": today_d},
		as_dict=True,
	)

	ci_names = {r["commercial_invoice"] for r in rows if r.get("commercial_invoice")}
	ci_split: dict[str, dict] = {}
	if ci_names and has_bank and has_cash:
		for ci in frappe.get_all(
			"Commercial Invoice",
			filters={"name": ["in", list(ci_names)]},
			fields=["name", "agreed_total", "custom_bank_agreed", "custom_cash_agreed"],
		):
			ci_split[ci["name"]] = ci

	total_due = 0.0
	bank_due_total = 0.0
	cash_due_total = 0.0
	overdue_amount = 0.0
	for r in rows:
		outstanding = flt(r["outstanding_amount"])
		r["outstanding_amount"] = outstanding
		r["due_date"] = str(r["due_date"]) if r.get("due_date") else None
		r["supplier_name"] = r.get("supplier_name") or r.get("supplier")
		r["overdue"] = bool(r.get("due_date") and getdate(r["due_date"]) < today_d)

		ci = r.pop("commercial_invoice", None)
		split = ci_split.get(ci) if ci else None
		if split:
			agreed_total = flt(split.get("agreed_total"))
			bank_agreed = flt(split.get("custom_bank_agreed"))
			bank_share = (bank_agreed / agreed_total) if agreed_total > 0 else 0.0
			bank_due = round(outstanding * bank_share, 2)
			r.update(
				{
					"channel": "split",
					"bank_due": bank_due,
					"cash_due": round(outstanding - bank_due, 2),
					"unsplit": False,
				}
			)
		else:
			r.update({"channel": "unsplit", "bank_due": outstanding, "cash_due": 0.0, "unsplit": True})

		total_due += outstanding
		bank_due_total += r["bank_due"]
		cash_due_total += r["cash_due"]
		if r["overdue"]:
			overdue_amount += outstanding

	return {
		"rows": rows,
		"summary": {
			"total_due": round(total_due, 2),
			"bank_due": round(bank_due_total, 2),
			"cash_due": round(cash_due_total, 2),
			"overdue_amount": round(overdue_amount, 2),
			"count": len(rows),
		},
	}


@frappe.whitelist()
def truck_departure_status(truck: str):
	"""Why a truck can or cannot leave Iran yet — read-only.

	The UI calls this to explain a disabled "Depart" action instead of letting
	the user press it and read a stack of errors. Same rule the Import Truck
	controller enforces, evaluated through the same pure function, so the
	preview cannot drift from the gate.
	"""
	if not truck or not frappe.db.exists("Import Truck", truck):
		frappe.throw(_("Unknown Import Truck: {0}").format(truck))
	_assert_can_read("Import Truck", truck)
	company = _company_of("Import Truck", truck)
	_assert_imports_access(company)

	from stabler.stabler.doctype.vet_certificate.vet_certificate import has_valid_vet_cert
	from stabler.stabler.imports_module import departure_math

	doc = frappe.get_doc("Import Truck", truck)
	has_flag = frappe.db.has_column("Customs Declaration", "required_for_departure")
	declarations = frappe.get_all(
		"Customs Declaration",
		filters={"commercial_invoice": doc.commercial_invoice},
		fields=["name", "gtd_number", "status", "cleared_date"]
		+ (["required_for_departure"] if has_flag else []),
		order_by="declaration_date asc",
	)
	if not has_flag:
		for d in declarations:
			d["required_for_departure"] = 1

	vet_valid = has_valid_vet_cert(doc.commercial_invoice)
	verdict = departure_math.may_depart(
		declarations,
		vet_valid=vet_valid,
		override=bool(doc.get("departure_override")),
		override_reason=doc.get("departure_override_reason") or "",
	)
	return {
		"truck": truck,
		"status": doc.status,
		"gated": departure_math.gates_this_transition("PENDING", "DEPARTED_IRAN") and doc.status == "PENDING",
		"allowed": verdict["allowed"],
		"via_override": verdict["via_override"],
		"blockers": verdict["blockers"],
		"vet_valid": vet_valid,
		"declarations": declarations,
	}


# ---------------------------------------------------------------------------
# Shared sea lifecycle: the CI owns the voyage, containers follow it.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def ci_sea_lifecycle(commercial_invoice: str):
	"""How far each container has drifted from its invoice's sea status.

	Read-only. CI and Import Container carry the same pipeline and are kept by
	hand, so they drift silently; this makes the gap visible before anyone is
	asked to close it.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	_assert_can_read("Commercial Invoice", commercial_invoice)
	company = _company_of("Commercial Invoice", commercial_invoice)
	_assert_imports_access(company)

	from stabler.stabler.imports_module import sea_lifecycle

	ci = frappe.db.get_value(
		"Commercial Invoice",
		commercial_invoice,
		["status", "vessel", "voyage", "eta", "eta_transit_port"],
		as_dict=True,
	)
	containers = frappe.get_all(
		"Import Container",
		filters={"commercial_invoice": commercial_invoice, "company": company},
		fields=["name", "container_number", "status"],
		order_by="creation asc",
	)
	payload = sea_lifecycle.summarise(ci.status, containers)
	payload["voyage"] = {
		"vessel": ci.vessel,
		"voyage": ci.voyage,
		"eta": str(ci.eta) if ci.eta else None,
		"eta_transit_port": str(ci.eta_transit_port) if ci.eta_transit_port else None,
	}
	return payload


@frappe.whitelist()
def sync_containers_to_ci(commercial_invoice: str, dry_run: int = 1):
	"""Advance every lagging container to its invoice's sea status.

	Deliberately an explicit action, not a hook: an automatic sync would erase
	the evidence of how far the two copies had drifted, and drift is exactly
	what needs measuring before the duplicate status field can be retired.

	Only containers that are *behind* move, and each one walks the pipeline one
	station at a time so the Import Container controller's own transition rules
	still apply. A container that is ahead of its invoice is reported, never
	corrected — moving it backwards needs a reason and belongs to the
	correction workflow.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
	company = _company_of("Commercial Invoice", commercial_invoice)
	_assert_imports_access(company)
	_assert_can_write("Commercial Invoice", commercial_invoice)

	from stabler.stabler.imports_module import sea_lifecycle

	dry_run = cint(dry_run)
	ci_status = frappe.db.get_value("Commercial Invoice", commercial_invoice, "status")
	containers = frappe.get_all(
		"Import Container",
		filters={"commercial_invoice": commercial_invoice, "company": company},
		fields=["name", "container_number", "status"],
		order_by="creation asc",
	)

	planned, skipped, failed = [], [], []
	for c in containers:
		if not sea_lifecycle.syncable(ci_status, c.status):
			skipped.append(
				{
					"container": c.name,
					"container_number": c.container_number,
					"status": c.status,
					"state": sea_lifecycle.drift(ci_status, c.status)["state"],
				}
			)
			continue
		steps = sea_lifecycle.path(c.status, ci_status)
		planned.append(
			{
				"container": c.name,
				"container_number": c.container_number,
				"from": c.status,
				"to": ci_status,
				"steps": steps,
			}
		)
		if dry_run:
			continue
		try:
			doc = frappe.get_doc("Import Container", c.name)
			for step in steps:
				doc.status = step
				doc.save()
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			failed.append({"container": c.name, "error": str(e)[:200]})

	return {
		"commercial_invoice": commercial_invoice,
		"ci_status": ci_status,
		"dry_run": bool(dry_run),
		"planned": planned,
		"skipped": skipped,
		"failed": failed,
	}


@frappe.whitelist()
def recalculate_all_ci_totals():
	"""Recalculate parent totals (total_boxes, total_kg, agreed_total, docs_total, cash_difference)
	from child items for all Commercial Invoices."""
	cis = frappe.get_all("Commercial Invoice", fields=["name"])
	updated_count = 0
	for ci in cis:
		doc = frappe.get_doc("Commercial Invoice", ci.name)
		total_boxes = 0
		total_kg = 0.0
		agreed_total = 0.0
		docs_total = 0.0

		for item in doc.items or []:
			b = int(item.boxes or 0)
			q = float(item.qty or 0.0)
			a = float(item.amount or (q * float(item.rate or 0.0)))
			da = float(item.docs_amount or (q * float(item.docs_price or 0.0)))

			total_boxes += b
			total_kg += q
			agreed_total += a
			docs_total += da

		cash_diff = agreed_total - docs_total

		frappe.db.set_value(
			"Commercial Invoice",
			doc.name,
			{
				"total_boxes": total_boxes,
				"total_kg": total_kg,
				"agreed_total": agreed_total,
				"docs_total": docs_total,
				"cash_difference": cash_diff,
			},
			update_modified=False,
		)
		updated_count += 1

	frappe.db.commit()
	return {"updated": updated_count}


# --------------------------------------------------------------------------- #
# Imports workflow flow-board: every document of the chain, counted by status,
# in ONE read-only pass per doctype. Each count deep-links to the document's
# own list page filtered to exactly that status — the number and the list
# share the same GROUP BY, so they cannot disagree.
# --------------------------------------------------------------------------- #


def _status_counts(doctype: str, company: str, docstatus_lt: int = 2) -> dict:
	"""One query per doctype — never one query per status.

	Counted in Python, not with a SQL COUNT: Frappe v16 rejects a function in a
	string SELECT ("SQL functions are not allowed as strings in SELECT"), and the
	dict form's result alias is version-dependent. The chain's four doctypes are
	~1.4k rows of a single column, so the trade is free — and the count still
	comes from the SAME filter the list page uses, which is the point.
	"""
	rows = frappe.get_all(
		doctype,
		filters={"company": company, "docstatus": ["<", docstatus_lt]},
		fields=["status"],
		limit_page_length=0,
	)
	counts: dict[str, int] = {}
	for row in rows:
		key = str(row.status or "")
		counts[key] = counts.get(key, 0) + 1
	return counts


@frappe.whitelist()
def imports_flow(company: str):
	"""Status counters for the whole import chain: PI, CI, containers (with sea
	drift), the departure gate, trucks, GRN and draft LCVs. Read-only."""
	_assert_imports_access(company)

	from stabler.stabler.doctype.vet_certificate.vet_certificate import has_valid_vet_cert
	from stabler.stabler.imports_module import departure_math, sea_lifecycle

	pi = _status_counts("Proforma Invoice", company)
	ci = _status_counts("Commercial Invoice", company)
	containers = _status_counts("Import Container", company)
	trucks = _status_counts("Import Truck", company)

	# Sea drift: CI owns the voyage, containers follow. Same rule as the CI
	# panel (sea_lifecycle), aggregated over the fleet.
	drift = {"behind": 0, "ahead": 0, "cis_out_of_sync": 0}
	ci_status_map = {
		r.name: r.status
		for r in frappe.get_all(
			"Commercial Invoice",
			filters={"company": company},
			fields=["name", "status"],
			limit_page_length=0,
		)
	}
	fleet: dict[str, list] = {}
	for r in frappe.get_all(
		"Import Container",
		filters={"company": company, "commercial_invoice": ["is", "set"]},
		fields=["name", "container_number", "status", "commercial_invoice"],
		limit_page_length=0,
	):
		fleet.setdefault(r.commercial_invoice, []).append(r)
	for ci_name, cnts in fleet.items():
		s = sea_lifecycle.summarise(ci_status_map.get(ci_name), cnts)
		drift["behind"] += s["behind"]
		drift["ahead"] += s["ahead"]
		if not s["in_sync"]:
			drift["cis_out_of_sync"] += 1

	# Departure gate: PENDING trucks whose CI is not cleared to leave Iran.
	# Blockers are per-CI (all-or-nothing), so evaluate each CI once.
	has_required_flag = frappe.db.has_column("Customs Declaration", "required_for_departure")
	pending_by_ci: dict[str, int] = {}
	for r in frappe.get_all(
		"Import Truck",
		filters={"company": company, "status": "PENDING"},
		fields=["commercial_invoice"],
		limit_page_length=0,
	):
		if r.commercial_invoice:
			pending_by_ci[r.commercial_invoice] = pending_by_ci.get(r.commercial_invoice, 0) + 1
	gate = {"pending": sum(pending_by_ci.values()), "blocked": 0}
	for ci_name, n in pending_by_ci.items():
		declarations = frappe.get_all(
			"Customs Declaration",
			filters={"commercial_invoice": ci_name},
			fields=["gtd_number", "status", "cleared_date"]
			+ (["required_for_departure"] if has_required_flag else []),
		)
		if not has_required_flag:
			for d in declarations:
				d["required_for_departure"] = 1
		verdict = departure_math.may_depart(declarations, vet_valid=has_valid_vet_cert(ci_name))
		if not verdict["allowed"]:
			gate["blocked"] += n

	grn = {
		"open": cint(frappe.db.count("GRN Checklist", {"company": company, "docstatus": 0})),
		"submitted": cint(frappe.db.count("GRN Checklist", {"company": company, "docstatus": 1})),
	}
	lcv_draft = cint(frappe.db.count("Landed Cost Voucher", {"company": company, "docstatus": 0}))

	at_sea = sum(ci.get(k, 0) for k in ("ON_BOARD", "IN_TRANSIT"))
	on_road = sum(trucks.get(k, 0) for k in ("DEPARTED_IRAN", "AT_BORDER", "CROSSED_BORDER", "IN_TRANSIT"))
	# Invoices whose CI was corrected after the payable was booked. Same rule
	# module as the CI form's banner — the board never re-derives it.
	try:
		book = _ci_invoice_drift(company)["summary"]
	except Exception:
		book = {"drifting": 0}  # a diagnostic must never take the board down
	return {
		"pi": pi,
		"ci": ci,
		"containers": containers,
		"trucks": trucks,
		"drift": drift,
		"gate": gate,
		"grn": grn,
		"invoice_drift": {"count": cint(book.get("drifting"))},
		"lcv": {"draft": lcv_draft},
		"kpi": {
			"open_pi": pi.get("DRAFT", 0) + pi.get("CONFIRMED", 0),
			"at_sea": at_sea,
			"on_road": on_road,
			"gate_blocked": gate["blocked"],
		},
	}


# ---------------------------------------------------------------------------
# Delete + unlink — PI/CI full CRUD (plan first, then act)
#
# Nothing here deletes silently: every endpoint defaults to ``dry_run=1`` and
# returns the impact report from ``_imports_delete.classify_impact`` — blockers
# the owner must resolve (live payable, payment, landed cost, received stock,
# customs declaration) and the operational children that ride along only with
# an explicit ``cascade=1``. See docs/plans/2026-07-29-pi-ci-full-crud.md.
# ---------------------------------------------------------------------------

# Doctypes reaching a Commercial Invoice through a plain ``commercial_invoice``
# Link field. One query each — the reference scan never queries inside a loop.
_CI_LINK_DOCTYPES = (
	"Import Container",
	"Import Truck",
	"Freight Booking",
	"Vet Certificate",
	"Commercial Invoice PO Link",
	"GRN Checklist",
	"Customs Declaration",
	"Import Expense",
	"Proforma Invoice",
)

# Children before parents: a container cannot go before the truck that carries it.
_CI_CASCADE_ORDER = (
	"GRN Checklist",
	"Commercial Invoice PO Link",
	"Vet Certificate",
	"Freight Booking",
	"Import Truck",
	"Import Container",
)

# "detach" rows keep the record and lose the reference (deleting a Proforma must
# not destroy shipment history — the CI line just loses its agreement link).
_DETACH_FIELD = {
	"Commercial Invoice": "custom_proforma_invoice",
	"Commercial Invoice Item": "custom_proforma_invoice",
}


def _add_refs(refs: dict, doctype: str, rows) -> None:
	"""Collect reference rows, de-duplicated by name."""
	seen = {r["name"] for r in refs.get(doctype) or []}
	for row in rows or []:
		if row.get("name") and row["name"] not in seen:
			seen.add(row["name"])
			refs.setdefault(doctype, []).append(
				{"name": row["name"], "docstatus": cint(row.get("docstatus"))}
			)


def _ci_reference_rows(company: str, ci: str) -> dict:
	"""Everything pointing at this Commercial Invoice, one query per doctype."""
	refs: dict = {}
	for doctype in _CI_LINK_DOCTYPES:
		_add_refs(
			refs,
			doctype,
			frappe.get_all(doctype, filters={"commercial_invoice": ci}, fields=["name", "docstatus"]),
		)

	# The live payable. ``custom_commercial_invoice`` does not exist on every
	# site, and ``convert_ci_to_purchase_invoice`` also writes the CI name into
	# ``bill_no`` — matching both is what makes the blocker fire everywhere.
	where = ["pi.bill_no = %(ci)s"]
	if frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice"):
		where.append("pi.custom_commercial_invoice = %(ci)s")
	_add_refs(
		refs,
		"Purchase Invoice",
		frappe.db.sql(
			"""SELECT pi.name, pi.docstatus FROM `tabPurchase Invoice` pi
			   WHERE pi.company = %(company)s AND pi.docstatus < 2 AND ({0})""".format(" OR ".join(where)),
			{"ci": ci, "company": company},
			as_dict=True,
		),
	)

	# Container advances sit on the Payment Entry, not on the CI.
	containers = [r["name"] for r in refs.get("Import Container") or []]
	if containers and frappe.db.has_column("Payment Entry", "custom_import_container"):
		_add_refs(
			refs,
			"Payment Entry",
			frappe.get_all(
				"Payment Entry",
				filters={
					"company": company,
					"docstatus": ["<", 2],
					"custom_import_container": ["in", containers],
				},
				fields=["name", "docstatus"],
			),
		)

	# Landed cost hangs off the GRN checklist (GRN → GRN LCV Ref → LCV).
	grns = [r["name"] for r in refs.get("GRN Checklist") or []]
	if grns:
		lcvs = [
			r["lcv"]
			for r in frappe.get_all("GRN LCV Ref", filters={"parent": ["in", grns]}, fields=["lcv"])
			if r.get("lcv")
		]
		if lcvs:
			_add_refs(
				refs,
				"Landed Cost Voucher",
				frappe.get_all(
					"Landed Cost Voucher",
					filters={"name": ["in", lcvs], "docstatus": ["<", 2]},
					fields=["name", "docstatus"],
				),
			)
	return refs


def _proforma_reference_rows(company: str, proforma: str, linked_ci: str | None) -> dict:
	"""Everything pointing at this Proforma Invoice — CI header + CI lines."""
	refs: dict = {}
	if frappe.db.has_column("Commercial Invoice Item", "custom_proforma_invoice"):
		_add_refs(
			refs,
			"Commercial Invoice Item",
			frappe.get_all(
				"Commercial Invoice Item",
				filters={"custom_proforma_invoice": proforma},
				fields=["name", "docstatus"],
			),
		)
	if frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice"):
		_add_refs(
			refs,
			"Commercial Invoice",
			frappe.get_all(
				"Commercial Invoice",
				filters={"company": company, "custom_proforma_invoice": proforma},
				fields=["name", "docstatus"],
			),
		)
	# The supersede link lives on the Proforma too — on a site without the
	# custom column that is the only trace of it.
	if linked_ci and frappe.db.exists("Commercial Invoice", linked_ci):
		_add_refs(refs, "Commercial Invoice", [{"name": linked_ci, "docstatus": 0}])
	return refs


def _cascade_order(cascade: dict) -> list[str]:
	known = [dt for dt in _CI_CASCADE_ORDER if dt in cascade]
	return known + [dt for dt in sorted(cascade) if dt not in _CI_CASCADE_ORDER]


def _apply_cascade(cascade: dict) -> list[dict]:
	"""Remove (or detach) the operational children. Caller owns the transaction."""
	applied = []
	for doctype in _cascade_order(cascade):
		mode = _imports_delete.cascade_mode(doctype)
		if mode == "ignore":
			continue
		for name in cascade[doctype] or []:
			if mode == "detach":
				field = _DETACH_FIELD.get(doctype)
				if not field or not frappe.db.has_column(doctype, field):
					continue
				frappe.db.set_value(doctype, name, field, None, update_modified=False)
			else:
				frappe.delete_doc(doctype, name, ignore_permissions=True)
			applied.append({"doctype": doctype, "name": name, "mode": mode})
	return applied


def _cascade_count(cascade: dict) -> int:
	return sum(len(v or []) for v in (cascade or {}).values())


def _cascade_modes(cascade: dict) -> dict:
	"""How each cascade doctype is applied, so the impact report can say it.

	A screen that promises "this will be deleted" where the row is only
	detached would be lying to the owner at the exact moment they decide.
	"""
	return {dt: _imports_delete.cascade_mode(dt) for dt in (cascade or {})}


def _assert_cascade_allowed(plan: dict, cascade: int) -> None:
	if plan["cascade"] and not cint(cascade):
		frappe.throw(
			_(
				"{0} linked record(s) still hang off this document — confirm “delete linked records” first."
			).format(_cascade_count(plan["cascade"]))
		)


@frappe.whitelist()
def delete_commercial_invoice(company: str, name: str, cascade: int = 0, dry_run: int = 1) -> dict:
	"""Delete a Commercial Invoice — impact report first, deletion only on demand.

	``dry_run`` (default 1) writes NOTHING and returns
	``{blockers, cascade, deletable, dry_run: True}``: the accounting documents
	that stop the deletion (each with a named reason) and the operational
	children that would be removed. Only ``dry_run=0`` acts, and only with
	``cascade=1`` when children exist. Children go first, then the invoice, in
	one transaction — any failure rolls the whole thing back.
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	if not frappe.db.exists("Commercial Invoice", name):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(name))
	if frappe.db.get_value("Commercial Invoice", name, "company") != company:
		frappe.throw(_("Commercial Invoice belongs to a different company."))
	_assert_can_write("Commercial Invoice", name, "delete")

	plan = _imports_delete.classify_impact(_ci_reference_rows(company, name))
	plan["commercial_invoice"] = name
	plan["cascade_count"] = _cascade_count(plan["cascade"])
	plan["cascade_modes"] = _cascade_modes(plan["cascade"])
	if cint(dry_run):
		plan["dry_run"] = True
		plan["changed"] = False
		return plan

	if plan["blockers"]:
		frappe.throw(plan["blockers"][0]["reason"])
	_assert_cascade_allowed(plan, cascade)

	try:
		frappe.db.get_value("Commercial Invoice", name, "name", for_update=True)
		applied = _apply_cascade(plan["cascade"])
		frappe.delete_doc("Commercial Invoice", name, ignore_permissions=True)
	except Exception as exc:
		frappe.db.rollback()
		frappe.throw(_("Deletion was rolled back: {0}").format(str(exc)))

	plan.update({"dry_run": False, "changed": True, "deleted": name, "applied": applied})
	return plan


@frappe.whitelist()
def delete_proforma_invoice(company: str, name: str, cascade: int = 0, dry_run: int = 1) -> dict:
	"""Delete a Proforma Invoice — impact report first, deletion only on demand.

	Same contract as :func:`delete_commercial_invoice`, with one difference that
	matters: a Commercial Invoice that quotes this proforma is **detached, not
	deleted** — the shipment stays, it simply loses its agreement link (the
	discrepancies screen already reports those as shipped-without-a-PI).
	"""
	_assert_imports_access(company)
	_assert_cost_visible()
	if not frappe.db.exists("Proforma Invoice", name):
		frappe.throw(_("Unknown Proforma Invoice: {0}").format(name))
	row = frappe.db.get_value("Proforma Invoice", name, ["company", "commercial_invoice"], as_dict=True)
	if (row or {}).get("company") != company:
		frappe.throw(_("Proforma Invoice belongs to a different company."))
	_assert_can_write("Proforma Invoice", name, "delete")

	plan = _imports_delete.classify_impact(
		_proforma_reference_rows(company, name, (row or {}).get("commercial_invoice"))
	)
	plan["proforma"] = name
	plan["cascade_count"] = _cascade_count(plan["cascade"])
	plan["cascade_modes"] = _cascade_modes(plan["cascade"])
	if cint(dry_run):
		plan["dry_run"] = True
		plan["changed"] = False
		return plan

	if plan["blockers"]:
		frappe.throw(plan["blockers"][0]["reason"])
	_assert_cascade_allowed(plan, cascade)

	try:
		frappe.db.get_value("Proforma Invoice", name, "name", for_update=True)
		applied = _apply_cascade(plan["cascade"])
		frappe.delete_doc("Proforma Invoice", name, ignore_permissions=True)
	except Exception as exc:
		frappe.db.rollback()
		frappe.throw(_("Deletion was rolled back: {0}").format(str(exc)))

	plan.update({"dry_run": False, "changed": True, "deleted": name, "applied": applied})
	return plan


@frappe.whitelist()
def unlink_proforma_from_ci(company: str, proforma: str, commercial_invoice: str) -> dict:
	"""Undo a supersede link — the exact inverse of :func:`link_proforma_to_ci`.

	Clears ``PI.commercial_invoice``, rolls ``SUPERSEDED_BY_CI`` back to
	``CONFIRMED`` and blanks ``CI.custom_proforma_invoice``. Idempotent: an
	already-unlinked proforma returns ``changed: False`` instead of throwing.
	Unlike the CI, the Proforma has no transition guard in ``validate`` — so
	this sets the status the same way the link endpoint does, and invents no
	new bypass.
	"""
	_assert_imports_access(company)
	if not frappe.db.exists("Proforma Invoice", proforma):
		frappe.throw(_("Unknown Proforma Invoice: {0}").format(proforma))
	pi = frappe.get_doc("Proforma Invoice", proforma)
	if pi.company != company:
		frappe.throw(_("Proforma Invoice belongs to a different company."))
	_assert_can_write("Proforma Invoice", proforma, "write")

	linked = pi.get("commercial_invoice") or ""
	if linked and commercial_invoice and linked != commercial_invoice:
		frappe.throw(
			_("Proforma {0} is linked to {1}, not to {2}.").format(proforma, linked, commercial_invoice)
		)
	if not linked and pi.status != _proforma.SUPERSEDED:
		return {"proforma": proforma, "status": pi.status, "commercial_invoice": None, "changed": False}

	target = linked or commercial_invoice
	pi.commercial_invoice = None
	if pi.status == _proforma.SUPERSEDED:
		pi.status = _proforma.CONFIRMED
	pi.save(ignore_permissions=True)
	if (
		target
		and frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice")
		and frappe.db.get_value("Commercial Invoice", target, "custom_proforma_invoice") == proforma
	):
		frappe.db.set_value(
			"Commercial Invoice", target, "custom_proforma_invoice", None, update_modified=False
		)

	return {"proforma": proforma, "status": pi.status, "commercial_invoice": None, "changed": True}


# ---------------------------------------------------------------------------
# Transporter & Land Freight Management Center (WP-I7)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def transporter_dashboard(
	company: str,
	search: str | None = None,
	transporter: str | None = None,
	page: int = 1,
	page_length: int = 25,
) -> dict:
	"""Operational dashboard for Transporters, Land Freight, Containers and Payments.

	Groups Freight Bookings / Containers by Commercial Invoice, Transporter,
	Container/Truck number, Agreed Transport Cost, Cash/Bank Payments, and
	Outstanding Balance per transporter.
	"""
	_assert_imports_access(company)
	page = max(1, cint(page or 1))
	page_length = min(100, max(1, cint(page_length or 25)))
	offset = (page - 1) * page_length

	# 1. Fetch available Transporters for dropdown filter
	transporters_raw = frappe.get_all(
		"Supplier",
		filters=[["disabled", "=", 0]],
		fields=["name", "supplier_name"],
		order_by="supplier_name asc",
	)
	transporters = [{"name": s.name, "supplier_name": s.supplier_name or s.name} for s in transporters_raw]

	# 2. Build SQL query filters. `fb.company` is NOT optional: _assert_imports_access
	#    only proves the caller may read *this* company's imports, so an unscoped
	#    WHERE hands back every other company's freight cost and payment split on the
	#    same site. Every other query in this module scopes the same way.
	where_clauses = ["fb.docstatus < 2", "fb.company = %(company)s"]
	query_params: dict = {"company": company}

	if transporter:
		where_clauses.append(
			"(fb.transporter = %(transporter)s OR s.supplier_name LIKE %(transporter_like)s)"
		)
		query_params["transporter"] = transporter
		query_params["transporter_like"] = f"%{transporter}%"

	if search:
		where_clauses.append(
			"(fb.name LIKE %(search)s OR fb.commercial_invoice LIKE %(search)s OR ci.ci_number LIKE %(search)s OR fb.container LIKE %(search)s OR fb.vehicle_number LIKE %(search)s OR s.supplier_name LIKE %(search)s OR fb.transporter LIKE %(search)s)"
		)
		query_params["search"] = f"%{search}%"
	where_sql = " AND ".join(where_clauses)

	# 3. Count total matching rows
	count_sql = f"""
		SELECT COUNT(*)
		FROM `tabFreight Booking` fb
		LEFT JOIN `tabCommercial Invoice` ci ON ci.name = fb.commercial_invoice
		LEFT JOIN `tabSupplier` s ON s.name = fb.transporter
		WHERE {where_sql}
	"""
	count_res = frappe.db.sql(count_sql, query_params)
	total_count = cint(count_res[0][0] if count_res else 0)

	# 4. Query paginated rows
	rows_sql = f"""
		SELECT

			fb.name,
			fb.commercial_invoice,
			COALESCE(ci.ci_number, fb.commercial_invoice) AS ci_number,
			fb.container,
			fb.vehicle_number,
			fb.transporter,
			COALESCE(s.supplier_name, fb.transporter) AS transporter_name,
			COALESCE(fb.amount, 0.0) AS transport_cost,
			COALESCE(fb.currency, 'USD') AS currency,
			COALESCE(fb.cash_payment, 0.0) AS paid_cash,
			COALESCE(fb.bank_payment, 0.0) AS paid_bank,
			fb.status,
			fb.booking_date,
			fb.route AS notes
		FROM `tabFreight Booking` fb
		LEFT JOIN `tabCommercial Invoice` ci ON ci.name = fb.commercial_invoice
		LEFT JOIN `tabSupplier` s ON s.name = fb.transporter
		WHERE {where_sql}
		ORDER BY fb.creation DESC
		LIMIT {page_length} OFFSET {offset}
	"""
	db_rows = frappe.db.sql(rows_sql, query_params, as_dict=True)

	formatted_rows = []
	for r in db_rows:
		cost = flt(r.transport_cost)
		p_cash = flt(r.paid_cash)
		p_bank = flt(r.paid_bank)
		tot_paid = p_cash + p_bank
		bal = round(max(0.0, cost - tot_paid), 2)
		formatted_rows.append(
			{
				"name": r.name,
				"commercial_invoice": r.commercial_invoice or "",
				"ci_number": r.ci_number or r.commercial_invoice or "",
				"container": r.container or "",
				"vehicle_number": r.vehicle_number or "",
				"transporter": r.transporter or "",
				"transporter_name": r.transporter_name or r.transporter or "—",
				"transport_cost": cost,
				"paid_cash": p_cash,
				"paid_bank": p_bank,
				"total_paid": tot_paid,
				"balance": bal,
				"currency": r.currency or "USD",
				"status": r.status or "Confirmed",
				"booking_date": str(r.booking_date or ""),
				"notes": r.notes or "",
			}
		)

	# 5. Aggregate summary stats, GROUPED BY currency. `fb.currency` is a Link that
	#    merely defaults to USD, so a single SUM adds UZS to USD and prints the
	#    result as USD in the largest text on the page. CLAUDE.md forbids exactly
	#    that: amounts render in their own currency, totals are never converted.
	summary_sql = f"""
		SELECT
			COALESCE(fb.currency, 'USD') AS currency,
			SUM(COALESCE(fb.amount, 0.0)) AS total_cost,
			SUM(COALESCE(fb.cash_payment, 0.0)) AS total_cash,
			SUM(COALESCE(fb.bank_payment, 0.0)) AS total_bank,
			COUNT(*) AS bookings_count
		FROM `tabFreight Booking` fb
		LEFT JOIN `tabCommercial Invoice` ci ON ci.name = fb.commercial_invoice
		LEFT JOIN `tabSupplier` s ON s.name = fb.transporter
		WHERE {where_sql}
		GROUP BY COALESCE(fb.currency, 'USD')
		ORDER BY SUM(COALESCE(fb.amount, 0.0)) DESC
	"""
	summary = []
	for s in frappe.db.sql(summary_sql, query_params, as_dict=True):
		s_cost = flt(s.total_cost)
		s_cash = flt(s.total_cash)
		s_bank = flt(s.total_bank)
		s_paid = s_cash + s_bank
		summary.append(
			{
				"currency": s.currency or "USD",
				"total_freight_cost": s_cost,
				"total_paid_cash": s_cash,
				"total_paid_bank": s_bank,
				"total_paid": s_paid,
				"total_outstanding": round(max(0.0, s_cost - s_paid), 2),
				"bookings_count": cint(s.bookings_count),
			}
		)

	# 6. Cost gate. `amount`, `cash_payment` and `bank_payment` are permlevel 1 on
	#    Freight Booking and every other reader of this doctype masks them
	#    (FREIGHT_MASK_FIELDS, ~line 2430). This endpoint projects them under new
	#    aliases, which is precisely how they escaped the gate: the columns are the
	#    same permlevel-1 figures, only renamed. Summary too — masking rows alone
	#    would hand back every hidden number as a total.
	visible = _cost_visible()
	rules.mask_named(formatted_rows, rules.TRANSPORTER_ROW_MASK_FIELDS, visible)
	rules.mask_named(summary, rules.TRANSPORTER_SUMMARY_MASK_FIELDS, visible)

	return {
		"summary": summary,
		"rows": formatted_rows,
		"transporters": transporters,
		"total_count": total_count,
		"cost_visible": visible,
		"page": page,
		"page_length": page_length,
	}


@frappe.whitelist()
def save_container_transport_cost(
	company: str,
	name: str,
	transporter: str | None = None,
	transport_cost: float = 0.0,
	currency: str = "USD",
	paid_cash: float = 0.0,
	paid_bank: float = 0.0,
	notes: str | None = None,
) -> dict:
	"""Update transport cost, assigned transporter vendor, and payments for a freight booking."""
	_assert_imports_access(company)
	if not frappe.db.exists("Freight Booking", name):
		frappe.throw(_("Freight Booking {0} not found.").format(name))

	# `company` is the caller's claim, `name` is what actually gets written — pass a
	# company you may access plus another company's booking name and the access
	# check passes while the write lands elsewhere. Bind the two together.
	if frappe.db.get_value("Freight Booking", name, "company") != company:
		frappe.throw(_("Freight Booking {0} belongs to another company.").format(name))

	_assert_can_write("Freight Booking", name, "write")
	# Every field this writes is permlevel 1. Writing costs the caller is not
	# allowed to read would otherwise be a way to probe them.
	_assert_cost_visible()

	cost = round(flt(transport_cost), 2)
	cash = round(flt(paid_cash), 2)
	bank = round(flt(paid_bank), 2)

	updates = {
		"amount": cost,
		"currency": currency or "USD",
		"cash_payment": cash,
		"bank_payment": bank,
	}

	if transporter is not None:
		updates["transporter"] = transporter
	if notes is not None:
		updates["route"] = notes

	frappe.db.set_value("Freight Booking", name, updates, update_modified=True)

	return {
		"name": name,
		"transporter": transporter,
		"transport_cost": cost,
		"paid_cash": cash,
		"paid_bank": bank,
		"changed": True,
	}


# ---------------------------------------------------------------------------
# W1/W2 — hand-linking a transport / service bill to a Commercial Invoice
#
# A carrier's or a broker's Purchase Invoice belongs to an import's cost picture,
# but nothing ever put the v46 ref on it: the automations stamp only the bills
# they themselves raise, so a manually entered freight bill stayed anonymous and
# people typed the CI number into the item description instead. These three
# endpoints are the missing hand-link, and nothing more.
#
# Linking does two things. It makes the bill visible in the CI's cost overview and
# its carriers-outstanding figure — both of which already read the v46 refs via
# ``_related_import_bills`` — and, since W3, it CAPITALIZES: the bill's net total
# is written onto the import's containers as a ``Container Cost Line``, so it
# reaches the Landed Cost Voucher and therefore stock valuation. Unlinking removes
# those lines again, and is refused once a voucher has consumed them.
#
# That second half is where the double-count lives. The same freight can be typed
# in by hand AND billed by the carrier, so a linked bill SUPERSEDES the hand-typed
# line of the same component on the same container — see ``supersede_billed`` in
# ``lcv_math``, which mirrors how a cleared GTD supersedes the hand-typed duty.
# The supersede is computed at build time, never stored, so unlinking a bill
# brings the hand-typed line straight back into the next voucher.
#
# The four v46 Link fields carry ``read_only: 1``, which is a Desk UI hint and
# blocks nothing on the server. Every rule below is therefore enforced here, and
# the client-side equivalents are decoration.
# ---------------------------------------------------------------------------

#: The three refs a human may set. ``custom_import_expense`` is deliberately
#: absent: it is stamped by the Import Expense automation and identifies the
#: bill as automation-owned, which is exactly what gate 4 refuses to overwrite.
_HAND_LINKABLE_REFS: tuple[tuple[str, str], ...] = (
	("custom_commercial_invoice", "Commercial Invoice"),
	("custom_import_container", "Import Container"),
	("custom_import_truck", "Import Truck"),
)

#: Fieldname -> the doctype it links to, for all four refs (error messages).
_PI_REF_DOCTYPES: dict[str, str] = {
	"custom_commercial_invoice": "Commercial Invoice",
	"custom_import_container": "Import Container",
	"custom_import_truck": "Import Truck",
	"custom_import_expense": "Import Expense",
}


def _bill_import_refs(purchase_invoice: str) -> dict:
	"""Current value of all four v46 refs on a bill; "" for absent columns.

	A column that does not exist on this site is reported as empty rather than
	omitted: the callers ask "is any ref set?", and a missing column can never
	hold one.
	"""
	cols = _existing_pi_ref_columns()
	values = (
		frappe.db.get_value("Purchase Invoice", purchase_invoice, cols, as_dict=True) or {} if cols else {}
	)
	return {col: (values.get(col) or "") for col in rules.PI_REF_COLUMNS}


def _ci_behind(refs: dict) -> str | None:
	"""The Commercial Invoice these refs point at, directly or through a ref that implies one.

	A container or a truck implies its CI just as directly as the CI ref does, so
	every rule that is really about the invoice must resolve through them too —
	otherwise the rule is bypassed by linking to the container instead.
	"""
	ci = refs.get("custom_commercial_invoice") or ""
	if not ci and refs.get("custom_import_container"):
		ci = frappe.db.get_value("Import Container", refs["custom_import_container"], "commercial_invoice")
	if not ci and refs.get("custom_import_truck"):
		ci = frappe.db.get_value("Import Truck", refs["custom_import_truck"], "commercial_invoice")
	return ci or None


def _ci_supplier_behind(refs: dict) -> str | None:
	"""The goods supplier of the Commercial Invoice these refs point at.

	Resolves through a container or truck ref for the reason in ``_ci_behind``:
	otherwise the same-supplier guard is bypassed by linking a CIF freight bill to
	the container instead of to the invoice.
	"""
	ci = _ci_behind(refs)
	if not ci:
		return None
	return frappe.db.get_value("Commercial Invoice", ci, "supplier")


def _assert_hand_linkable_supplier(company: str, supplier: str) -> None:
	"""Gate 5 — the bill's supplier must be a configured transport/service vendor.

	Unset => the feature is OFF for this company. There is no default list and
	no fallback: this predicate is the only thing standing between the import
	cost picture and an arbitrary payable, so "not configured" must mean "not
	permitted", never "anything goes".
	"""
	groups = imports_transport_supplier_groups_for(company)
	if not groups:
		frappe.throw(
			_(
				"Linking a bill to an import is not configured for this company. "
				"Set the transport/service supplier groups in Stabler Settings first."
			)
		)
	supplier_group = frappe.db.get_value("Supplier", supplier, "supplier_group")
	if supplier_group not in groups:
		frappe.throw(
			_(
				"Supplier {0} belongs to group {1}, which is not one of the "
				"transport/service groups whose bills may be linked to an import."
			).format(supplier, supplier_group or _("(none)"))
		)


def _assert_not_ci_supplier(supplier: str, ci_supplier: str | None) -> None:
	"""Gate 6 — a freight bill from the goods vendor is CIF and already paid for.

	When the carrier IS the seller, the transport is inside the agreed goods
	price. Attributing the bill to the CI would count that transport a second
	time in the cost picture, and it would collide with the supplier-scoped
	reads that decide which Purchase Invoice is THE goods invoice of the CI —
	one of which cancels the invoice it picks.
	"""
	if ci_supplier and supplier == ci_supplier:
		frappe.throw(
			_(
				"{0} is the Commercial Invoice's own supplier. Freight billed by the "
				"seller is already inside the agreed goods price (CIF); linking it "
				"would count that cost twice."
			).format(supplier)
		)


def _assert_capitalizable_currency(purchase_invoice: str, currency: str, company_currency: str) -> None:
	"""Gate 8 — refuse a bill in a currency the landed cost cannot value correctly.

	``lcv_math.line_company_amount`` has exactly two branches: the company currency
	passes through, and EVERYTHING else is multiplied by the USD rate. A EUR or RUB
	bill would therefore be capitalized at the dollar rate and be wrong by the whole
	cross rate (``stabler-oe3``). Refusing is the honest answer until that is fixed:
	a refused link is a message on screen, a wrong valuation is permanent the moment
	an accountant submits the voucher.
	"""
	if currency and currency not in (company_currency, "USD"):
		frappe.throw(
			_(
				"{0} is in {1}. Only bills in {2} or USD can be added to an import's landed cost today."
			).format(purchase_invoice, currency, company_currency)
		)


def _containers_behind_refs(refs: dict) -> list[dict]:
	"""Containers a linked bill's cost is spread over, each with its ``total_kg``.

	A container ref is the whole answer — the operator said which one. A CI ref, or
	a truck ref (Import Truck carries a CI and no container), means the bill covers
	the whole invoice, which is exactly the case the weight split exists for.
	"""
	container = refs.get("custom_import_container")
	if container:
		row = frappe.db.get_value("Import Container", container, ["name", "total_kg"], as_dict=True)
		return [row] if row else []
	ci = _ci_behind(refs)
	if not ci:
		return []
	return frappe.get_all(
		"Import Container",
		filters={"commercial_invoice": ci},
		fields=["name", "total_kg"],
		order_by="name",
	)


def _capitalize_linked_bill(
	purchase_invoice: str, company: str, refs: dict, bill: dict
) -> tuple[list[str], list[str]]:
	"""Write a linked bill's cost onto the containers it paid for.

	Returns ``(row_names, warnings)`` — the rows written, and one message per
	container where the cost was deliberately NOT written.

	Silent no-op, deliberately, whenever the bill has no business in the valuation:
	an unclassifiable category (``bill_cost_component`` returns ``None``), no
	container behind the refs, or nothing to charge. The link itself is still worth
	having in those cases — it is what makes the bill visible in the cost overview —
	so a missing cost line must not undo an otherwise legitimate attribution.

	``net_total`` and not ``grand_total``: the VAT on a carrier's bill is a
	recoverable input credit, and it is excluded from the landed cost everywhere
	else in this module (``aggregate_components`` drops VAT components outright).
	Capitalizing it would inflate the cost of goods by the VAT rate.

	The account gate runs LAST, after the three no-op returns, and that placement is
	the point: it must refuse exactly the bills whose cost is about to be written,
	and stay out of the way of a link that was never going to write one. The other
	gates in ``set_bill_import_refs`` run before the ref write because they can be
	decided from the bill alone; this one cannot — whether a cost is written at all
	depends on the component and the containers resolved here, and duplicating that
	resolution upstream would give the two copies room to disagree. The throw
	unwinds the ref write with the request's transaction.
	"""
	component = rules.bill_cost_component(
		rules.derive_bill_category(
			truck_ref=refs.get("custom_import_truck"),
			expense_ref=refs.get("custom_import_expense"),
			item_codes=_pi_item_codes([purchase_invoice]).get(purchase_invoice, []),
			bill_no=bill.get("bill_no"),
			transport_supplier=bool(_transport_group_suppliers(company, [bill.get("supplier")])),
		)
	)
	if not component:
		return [], []

	containers = _containers_behind_refs(refs)
	if not containers:
		return [], []

	amount = flt(bill.get("net_total"))
	if amount <= 0:
		return [], []

	if cint(bill.get("docstatus")) == 0:
		from stabler.stabler.imports_module import hooks as imports_hooks

		lcv_account = imports_hooks.resolve_lcv_expense_account(company)
		if lcv_account:
			pi_doc = frappe.get_doc("Purchase Invoice", purchase_invoice)
			modified = False
			for it in pi_doc.items:
				acc_type = frappe.db.get_value("Account", it.expense_account, "account_type")
				if acc_type != _VALUATION_ACCOUNT_TYPE:
					it.expense_account = lcv_account
					modified = True
			if modified:
				pi_doc.save(ignore_permissions=True)

	_assert_bill_valuation_accounts(purchase_invoice)

	currency = bill.get("currency") or frappe.get_cached_value("Company", company, "default_currency")

	row_names, skipped = _capitalize_import_cost(
		refs=refs,
		component=component,
		amount=amount,
		base_amount=flt(bill.get("base_net_total")),
		currency=currency,
		description=_("Bill {0}").format(bill.get("bill_no") or purchase_invoice),
		source_field="purchase_invoice",
		source_name=purchase_invoice,
	)
	warnings = [
		_(
			"A hand-entered {0} cost on container {1} is already capitalized by {2}. "
			"The bill was linked, but its cost was not added a second time."
		).format(_(skip["cost_component"]), skip["container"], skip["vouchered_by"])
		for skip in skipped
	]
	return row_names, warnings


def _capitalize_import_cost(
	refs: dict,
	component: str,
	amount: float,
	base_amount: float,
	currency: str,
	description: str,
	source_field: str,
	source_name: str,
) -> tuple[list[str], list[dict]]:
	"""Spread one document's cost over the containers behind ``refs``.

	Shared by every path that turns a real document into landed cost — a linked
	carrier's bill today, an Import Expense paid in cash or from the bank next to
	it. ``source_field`` says which Link column on the cost line names that
	document, and it MUST be one of ``lcv_math.SOURCE_FIELDS``: a line whose source
	field is unknown to that tuple reads as an operator's hand-typed estimate, so a
	later bill would supersede it and the real spend would silently vanish.

	Returns ``(row_names, skipped)``. ``skipped`` carries one dict per container
	where the cost was deliberately NOT written, so each caller words its own
	message — the wording is the only thing the two paths do not share.

	Silent no-op whenever there is nothing to capitalize: no component, no
	container behind the refs, or nothing to charge. The attribution itself is
	still worth having in those cases — it is what makes the document visible in
	the cost overview — so a missing cost line must not undo it.
	"""
	from stabler.stabler.imports_module import lcv_math

	if source_field not in lcv_math.SOURCE_FIELDS:
		frappe.throw(_("Unknown cost source field {0}.").format(source_field))
	if not component:
		return [], []

	containers = _containers_behind_refs(refs)
	if not containers:
		return [], []

	if flt(amount) <= 0:
		return [], []

	# Both splits conserve their own total (the last container absorbs the
	# remainder), so the transaction figure and the company figure each still sum
	# back to the document even when they round apart on an individual container.
	parts = rules.allocate_by_weight(flt(amount), containers)
	base_parts = rules.allocate_by_weight(flt(base_amount), containers)

	# Read through ``has_column`` because a deploy copies the code before
	# ``bench migrate`` adds the column: between those two steps an unconditional
	# field list would make every link attempt fail. The unlink cleanup below
	# guards the same way.
	source_columns = [
		field for field in lcv_math.SOURCE_FIELDS if frappe.db.has_column("Container Cost Line", field)
	]

	row_names = []
	skipped: list[dict] = []
	for part, base_part in zip(parts, base_parts, strict=True):
		# Inserted as a child document rather than through ``doc.save()`` on the
		# container, for the same reason the ref write uses db.set_value: a full
		# save re-runs the container's validation over a document somebody may be
		# editing, to add one row that carries no business logic of its own.
		existing = frappe.get_all(
			"Container Cost Line",
			filters={"parent": part["container"], "parenttype": "Import Container"},
			fields=[
				"idx",
				"parent as container",
				"cost_component",
				"lcv_ref",
				"include_in_landed_cost",
				*source_columns,
			],
		)
		used = [row["idx"] for row in existing]

		# The operator's own estimate for this component is already inside a
		# Landed Cost Voucher, so ``supersede_billed`` can no longer drop it —
		# it is not a candidate any more. Writing this document's line here would
		# put the same money into stock valuation a second time (stabler-wen). The
		# attribution itself still goes through: it is what makes the document
		# visible in the cost overview, and it is worth having even when the
		# valuation is already carried. Reversing the posted voucher is the
		# accountant's call, not this endpoint's.
		already = lcv_math.vouchered_hand_line(existing, part["container"], component)
		if already:
			skipped.append(
				{
					"container": part["container"],
					"cost_component": component,
					"vouchered_by": already,
				}
			)
			continue

		row = frappe.get_doc(
			{
				"doctype": "Container Cost Line",
				"parenttype": "Import Container",
				"parentfield": "cost_lines",
				"parent": part["container"],
				"idx": max(used or [0]) + 1,
				"cost_component": component,
				"description": description,
				"currency": currency,
				"amount": part["amount"],
				"amount_uzs": base_part["amount"],
				"include_in_landed_cost": 1,
				source_field: source_name,
			}
		)
		row.insert(ignore_permissions=True)
		row_names.append(row.name)
	return row_names, skipped


@frappe.whitelist()
def set_bill_import_refs(
	purchase_invoice: str,
	commercial_invoice: str | None = None,
	import_container: str | None = None,
	import_truck: str | None = None,
) -> dict:
	"""Attribute a transport/service bill to an import, and capitalize it (W1/W3).

	Nine gates, in this order — the list is the control, the UI's version of it
	is decoration:

	1. imports module access for the bill's company
	2. record-level write permission on the bill
	3. the bill is not cancelled
	4. all four v46 refs are currently empty (automation-owned bills stay locked)
	5. the supplier is in a configured transport/service group
	6. the supplier is not the Commercial Invoice's own supplier (CIF)
	7. every passed target exists, is in the same company, and is readable
	8. the session user may see cost figures
	9. the bill's currency is one the landed cost can value

	Gates 8 and 9 arrived with W3 and exist because linking stopped being pure
	metadata: it now writes a money figure into the container cost book. Gate 8 is
	the same masking the cost fields already carry — a user who may not see a
	landed cost must not be able to author one. Both run BEFORE the ref write, so
	a refusal leaves the bill exactly as it was rather than linked-but-uncosted.

	Writes with ``frappe.db.set_value`` rather than ``doc.save()`` on purpose:
	saving re-runs full Purchase Invoice validation over a draft the user is
	still editing, which can fail on unrelated grounds or silently recompute
	amounts. Setting a traceability Link touches no money field ON THE BILL — the
	money this endpoint does write lands on the container, never on the payable.
	"""
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))

	# Gate 1 — the module gate runs before anything else. A tenant with imports
	# off must not be able to probe, let alone write, through this endpoint.
	company = _company_of("Purchase Invoice", purchase_invoice)
	_assert_imports_access(company)

	# Gate 2 — @frappe.whitelist() gates the method, not the record.
	_assert_can_write("Purchase Invoice", purchase_invoice)

	# Gate 8 — linking authors a landed-cost figure, so it needs the same
	# visibility the cost fields themselves are masked by (the bill picker already
	# asserts this). Placed with the other permission checks, before any write.
	_assert_cost_visible()

	targets = {
		"custom_commercial_invoice": (commercial_invoice or "").strip(),
		"custom_import_container": (import_container or "").strip(),
		"custom_import_truck": (import_truck or "").strip(),
	}
	if not any(targets.values()):
		frappe.throw(_("Nothing to link: pass a Commercial Invoice, a container or a truck."))

	bill = frappe.db.get_value(
		"Purchase Invoice",
		purchase_invoice,
		["docstatus", "supplier", "currency", "net_total", "base_net_total", "bill_no"],
		as_dict=True,
	)

	# Gate 3 — cancelled bills only are refused. Draft-only was the original rule
	# and it was wrong in practice: a transporter's bill is routinely submitted
	# and paid before anyone gets round to attributing it, and there was then no
	# way back. Submitting changes nothing this endpoint cares about — the write
	# sets a traceability Link with db.set_value and moves no GL or valuation
	# figure (see the write's own note below), so the bill's accounting standing
	# is not what makes attribution legitimate.
	#
	# Cancelled is a different case and stays refused: every read that consumes
	# these refs filters `docstatus < 2` (_related_import_bills, the cost
	# overview, the landed-cost lists), so a cancelled bill's link would be
	# invisible everywhere while gate 4 below locked the bill against ever being
	# linked again — a silent no-op that cannot be undone.
	if cint(bill.docstatus) == 2:
		frappe.throw(_("A cancelled bill cannot be linked to an import: {0}.").format(purchase_invoice))

	# Gate 4 — ANY ref already set means some other path owns this bill: the
	# import-expense automation, the truck-transport automation, the CI->PInv
	# conversion or the rebook path. Those refs are that path's bookkeeping;
	# hand-relinking would detach the bill from the document that created it.
	for col, value in _bill_import_refs(purchase_invoice).items():
		if value:
			frappe.throw(
				_("{0} is already linked to {1} {2} and cannot be re-linked by hand.").format(
					purchase_invoice, _(_PI_REF_DOCTYPES[col]), value
				)
			)

	# Gate 5 — configured transport/service supplier group (unset => feature off).
	_assert_hand_linkable_supplier(company, bill.supplier)

	# Gate 6 — never the CI's own supplier.
	_assert_not_ci_supplier(bill.supplier, _ci_supplier_behind(targets))

	# Gate 7 — each target must exist, live in the SAME company as the bill, and
	# be readable. The company check is what stops a valid name from one tenant
	# being attached to another tenant's payable.
	updates = {}
	for col, doctype in _HAND_LINKABLE_REFS:
		value = targets[col]
		if not value:
			continue
		if not frappe.db.exists(doctype, value):
			frappe.throw(_("Unknown {0}: {1}").format(_(doctype), value))
		if _company_of(doctype, value) != company:
			frappe.throw(_("{0} {1} belongs to another company.").format(_(doctype), value))
		_assert_can_read(doctype, value)
		updates[col] = value

	# Gate 9 — the currency the cost book can actually value. Before the write, so
	# a refused bill stays unlinked instead of relying on the transaction rollback.
	_assert_capitalizable_currency(
		purchase_invoice,
		bill.get("currency"),
		frappe.get_cached_value("Company", company, "default_currency"),
	)

	# update_modified=False, deliberately. This is an attribution stamp on ref
	# columns the bill's own form never sends, but the form DOES send `modified`
	# to `check_concurrency` (`purchasing.py`) when the user saves. Bumping the
	# timestamp under an open draft turns the next Save into a concurrency
	# failure whose only offered exit is Reload — discarding whatever the user
	# had typed into a money document. The link is visible through
	# `bill_import_link_state`, which the form refetches after this call.
	frappe.db.set_value("Purchase Invoice", purchase_invoice, updates, update_modified=False)

	# The refs are re-read rather than reused from ``updates``: a container ref
	# resolves its CI through the database, and reading back is also what proves
	# the write landed on this site's columns.
	refs = _bill_import_refs(purchase_invoice)
	cost_lines, warnings = _capitalize_linked_bill(purchase_invoice, company, refs, bill)

	return {
		"name": purchase_invoice,
		"refs": refs,
		"linked": True,
		"cost_lines": cost_lines,
		"warnings": warnings,
	}


# Every doctype in the imports tree that raises a Purchase Invoice and keeps a
# back-pointer to it. Measured across the doctype JSON: these two are the whole
# set of ``*purchase_invoice`` Link fields pointing at Purchase Invoice.
_AUTOMATION_BACK_REFS = (
	("Import Truck", "transport_purchase_invoice"),
	("Import Expense", "purchase_invoice"),
)


def _automation_owner_of_bill(purchase_invoice: str):
	"""Which automation document, if any, raised this bill and still points at it.

	An empty ``custom_import_expense`` does NOT prove the bill is hand-made: the
	truck-transport automation raises tier-3 bills with no expense to consume
	(``imports_module/hooks.py``, ``import_expense=None``). Ownership is whoever
	holds the back-pointer, so that is what gets asked.
	"""
	for doctype, back_ref in _AUTOMATION_BACK_REFS:
		owner = frappe.db.get_value(doctype, {back_ref: purchase_invoice}, "name")
		if owner:
			return doctype, owner
	return None


@frappe.whitelist()
def clear_bill_import_refs(purchase_invoice: str) -> dict:
	"""Undo a hand-link (W2) — only for bills ``set_bill_import_refs`` could have made.

	Two rules beyond the module + write gates keep this off automation-owned
	bills: a non-empty ``custom_import_expense`` means the Import Expense
	automation raised it, and a supplier equal to the CI's supplier means it is
	the goods invoice. Neither may be unlinked here.

	The third rule is about money rather than ownership: once the cost has been
	pulled into a Landed Cost Voucher, unlinking would leave a capitalized cost
	whose source bill is no longer attributable to the import.

	There is deliberately NO docstatus gate here at all — not even the cancelled
	refusal ``set_bill_import_refs`` carries. Linking is the act that creates an
	attribution, unlinking is the escape hatch that corrects a wrong one, and an
	escape hatch that can itself be locked is not one: a bill mis-attributed and
	then cancelled must still be clearable. The gate that actually protects money
	is the voucher check below, which does not care about docstatus either.
	"""
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))

	company = _company_of("Purchase Invoice", purchase_invoice)
	_assert_imports_access(company)
	_assert_can_write("Purchase Invoice", purchase_invoice)

	refs = _bill_import_refs(purchase_invoice)
	if refs["custom_import_expense"]:
		frappe.throw(
			_("{0} was raised by the Import Expense automation ({1}) and cannot be unlinked here.").format(
				purchase_invoice, refs["custom_import_expense"]
			)
		)
	if not any(refs[col] for col, _dt in _HAND_LINKABLE_REFS):
		frappe.throw(_("{0} is not linked to an import.").format(purchase_invoice))

	# The two rules above pass for a tier-3 automation transport bill: it carries
	# no expense to consume, and its supplier is the carrier rather than the CI's.
	# One click would then orphan a bill that `Import Truck` still points at.
	owned_by = _automation_owner_of_bill(purchase_invoice)
	if owned_by:
		frappe.throw(
			_("{0} was raised for {1} {2} and its link is owned there, not here.").format(
				purchase_invoice, _(owned_by[0]), owned_by[1]
			)
		)

	supplier = frappe.db.get_value("Purchase Invoice", purchase_invoice, "supplier")
	ci_supplier = _ci_supplier_behind(refs)
	if ci_supplier and supplier == ci_supplier:
		frappe.throw(
			_(
				"{0} is the goods invoice of this Commercial Invoice — its link is owned "
				"by the conversion that created it and cannot be cleared here."
			).format(purchase_invoice)
		)

	# The cost has already been capitalized — linking wrote it (W3). Once a Landed
	# Cost Voucher has consumed those lines the money is in stock valuation, and
	# unlinking would leave a capitalized cost whose source bill is no longer
	# attributable to the import; the voucher is the accountant's to reverse, not
	# this endpoint's. The column is probed rather than assumed so a site that has
	# not run the migrate yet gets "nothing capitalized" instead of a SQL error.
	if frappe.db.has_column("Container Cost Line", "purchase_invoice"):
		vouchered = frappe.db.sql(
			"""
            SELECT cl.lcv_ref
            FROM `tabContainer Cost Line` cl
            WHERE cl.purchase_invoice = %(pi)s
              AND cl.lcv_ref IS NOT NULL AND cl.lcv_ref != ''
            LIMIT 1
            """,
			{"pi": purchase_invoice},
			as_dict=True,
		)
		if vouchered:
			frappe.throw(
				_("This bill is already vouchered ({0}) and can no longer be unlinked.").format(
					vouchered[0]["lcv_ref"]
				)
			)

		# Un-do exactly what the link wrote. The guard above proved none of these
		# rows reached a voucher, so nothing is being taken out of a valuation that
		# has already been posted. Any hand-typed line this bill superseded comes
		# back on its own: the supersede is computed when the voucher is built,
		# never stored, so the operator's figure is still sitting there untouched.
		frappe.db.delete("Container Cost Line", {"purchase_invoice": purchase_invoice})

	# update_modified=False for the same reason as the link write above: these
	# ref columns are not part of what the bill's form submits, but `modified`
	# is, and bumping it under an open draft turns the user's next Save into a
	# concurrency failure whose only exit is Reload.
	frappe.db.set_value(
		"Purchase Invoice",
		purchase_invoice,
		{col: None for col, _dt in _HAND_LINKABLE_REFS},
		update_modified=False,
	)

	return {
		"name": purchase_invoice,
		"refs": _bill_import_refs(purchase_invoice),
		"linked": False,
	}


#: The ERPNext ``Account.account_type`` that means "money spent on this account is
#: already destined for stock value". Read verbatim off the Account doctype's own
#: Select options rather than written from memory, because the list contains a
#: near-miss sibling — "Expenses Included In Asset Valuation" — which is the
#: FIXED-ASSET variant and capitalizes into an asset, not into stock. The two are
#: not interchangeable and a typo between them is a silent wrong valuation.
_VALUATION_ACCOUNT_TYPE = "Expenses Included In Valuation"


def _assert_valuation_account(import_expense: str, expense_account: str | None) -> None:
	"""The expense's debit account must be one stock valuation already expects.

	This is the expense path's replacement for the bill path's supplier-group gate
	(gate 5), and it guards a bigger hole than that one does. An Import Expense
	paid from a cash desk posts a Journal Entry that debits ``expense_account``.
	If that account is an ordinary P&L expense, the cost has ALREADY hit the
	income statement; capitalizing it a second time through a Landed Cost Voucher
	debits stock for the same money, and the business pays for one truckload of
	transport twice — once as expense, once inside the cost of the goods.

	"Expenses Included In Valuation" is ERPNext's own name for the account that
	exists precisely to be relieved by the LCV, so it is the one account type
	where both legs are the same money rather than two.

	The message names the account, because the operator's next move is to change
	it and they cannot do that from "the account is wrong".

	An empty account is refused separately and deliberately: it means the expense
	is billed through a supplier Purchase Invoice instead of paid in cash (see the
	field's own description), and THAT invoice — not this document — is what the
	landed cost has to be built from, via ``set_bill_import_refs``. Capitalizing
	here as well would be the same double count from the other direction.
	"""
	if not expense_account:
		frappe.throw(
			_(
				"{0} has no Expense Account, so it is billed through a supplier invoice. "
				"Add that Purchase Invoice to the import instead — capitalizing both would "
				"count the cost twice."
			).format(import_expense)
		)

	account_type = frappe.db.get_value("Account", expense_account, "account_type")
	if account_type != _VALUATION_ACCOUNT_TYPE:
		frappe.throw(
			_(
				"{0} is not an '{1}' account. Its cost is already in the income statement, "
				"so adding it to the landed cost would charge the goods for it a second "
				"time. Post the expense to a valuation account first."
			).format(expense_account, _VALUATION_ACCOUNT_TYPE)
		)


def _assert_bill_valuation_accounts(purchase_invoice: str) -> None:
	"""Every item on a capitalized bill must debit a stock-valuation account.

	The bill path's version of ``_assert_valuation_account``, and it closes the same
	hole from the other side. A Purchase Invoice debits ``expense_account`` per item
	the moment it is submitted. When that account is an ordinary P&L expense — a
	plain "Freight Expenses" — the carrier's money is ALREADY in the income
	statement; capitalizing the same bill through a Landed Cost Voucher debits stock
	for it as well, and the business pays for one truckload twice, once as expense
	and once inside the cost of the goods it moved. Only on an
	'Expenses Included In Valuation' account are the two legs the same money: that
	account exists precisely to be relieved by the LCV.

	ALL items, not the first or the biggest one. The whole ``net_total`` is what
	gets capitalized, so a single non-valuation line means part of that total is
	double counted — and a mixed bill is the case most likely to slip past a human
	reading the voucher.

	An item with no expense account fails the same way, deliberately. It is not a
	bill we can prove anything about, and the honest answer to "which account did
	this debit" being unknown is a refusal, not a guess in the direction that costs
	money.

	Refusing rather than warning, because the operator has to see it. The bulk
	linker on the Commercial Invoice form reports per-bill success and failure and
	discards ``warnings`` — a warning-only design would be invisible on exactly the
	screen where bills are linked in batches. The message names the offending
	accounts, because the operator's next move is to correct them.
	"""
	rows = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": purchase_invoice},
		fields=["expense_account"],
	)
	accounts = {(r.get("expense_account") or "").strip() for r in rows}

	if not accounts or "" in accounts:
		frappe.throw(
			_(
				"{0} has an item with no Expense Account, so there is no way to tell whether "
				"its cost is already in the income statement. Set the account before adding "
				"the bill to the import."
			).format(purchase_invoice)
		)

	types = frappe.get_all(
		"Account",
		filters={"name": ["in", sorted(accounts)]},
		fields=["name", "account_type"],
	)
	offenders = sorted(a["name"] for a in types if a["account_type"] != _VALUATION_ACCOUNT_TYPE)
	if offenders:
		frappe.throw(
			_(
				"{0} posts to {1}, which is not an '{2}' account. Its cost is already in the "
				"income statement, so capitalizing the bill would charge the goods for it a "
				"second time. Move the bill to a valuation account first."
			).format(purchase_invoice, ", ".join(offenders), _VALUATION_ACCOUNT_TYPE)
		)


def _expense_import_refs(expense: dict) -> dict:
	"""The expense's own targets, shaped like a bill's ``custom_*`` ref dict.

	Everything downstream of the link — ``_ci_behind``, ``_ci_supplier_behind``,
	``_containers_behind_refs``, ``_capitalize_import_cost`` — reads that shape.
	Reusing it is what makes the expense route land on exactly the same containers,
	with exactly the same weight split, as a bill pointed at the same invoice.
	"""
	return {
		"custom_commercial_invoice": expense.get("commercial_invoice"),
		"custom_import_container": expense.get("container"),
		"custom_import_truck": expense.get("truck"),
	}


def _resolve_expense_cost_component(expense: dict, requested: str | None) -> str:
	"""Operator's choice first, then the stored field, then the category prefill.

	Validated against ``Container Cost Line``'s own Select options instead of a
	copy of that list: the component decides what supersedes what, and a value the
	child table does not know would be written straight through
	``insert(ignore_permissions=True)`` and then never match anything.
	"""
	component = (requested or "").strip() or (expense.get("cost_component") or "").strip()
	if not component:
		component = rules.expense_cost_component(expense.get("category"))

	field = frappe.get_meta("Container Cost Line").get_field("cost_component")
	allowed = [opt.strip() for opt in (field.options or "").split("\n") if opt.strip()]
	if component not in allowed:
		frappe.throw(_("Unknown cost component: {0}").format(component))
	return component


@frappe.whitelist()
def set_expense_landed_cost(import_expense: str, cost_component: str | None = None) -> dict:
	"""Capitalize a cash-paid Import Expense onto the containers of its invoice.

	The second source of a landed cost, alongside a linked bill. The gates mirror
	``set_bill_import_refs`` one for one, with two deliberate differences:

	* there is no docstatus gate, because Import Expense is not a submittable
	  doctype at all. That is a fact about the doctype, not a relaxation: writing
	  a ``docstatus`` check here would be dead code that reads like protection.
	* gate 5 is not a supplier group but ``_assert_valuation_account``. A bill's
	  risk is *which* import it belongs to; a cash expense's risk is that its
	  money has already been expensed once (see that helper).

	Unlike the bill path, a no-op is never silent here. Linking a bill has value
	on its own — it is what makes the bill visible in the cost overview — so a
	bill that cannot be costed is still worth linking. This endpoint does nothing
	*but* capitalize, so anything that prevents the write is reported, not
	swallowed, and the ``include_in_landed_cost`` flag is set only when rows
	really exist to back it.
	"""
	if not import_expense or not frappe.db.exists("Import Expense", import_expense):
		frappe.throw(_("Unknown Import Expense: {0}").format(import_expense))

	# Gate 1 — module access for the expense's company, before anything else.
	company = _company_of("Import Expense", import_expense)
	_assert_imports_access(company)

	# Gate 2 — record-level write; @frappe.whitelist() gates the method, not the row.
	_assert_can_write("Import Expense", import_expense)

	# Gate 3 — authoring a landed-cost figure needs the same visibility the cost
	# fields are masked by.
	_assert_cost_visible()

	# Gate 4 — the column this whole feature writes its provenance into. Deploy
	# copies code with rsync and runs `bench migrate` afterwards, so there is a
	# window where this endpoint exists and `Container Cost Line.import_expense`
	# does not. Frappe would silently DROP the unknown field from the insert and
	# leave a cost line with no source — which reads as hand-typed, which means a
	# later bill for the same component supersedes it and takes real spend back
	# out of the valuation. Refusing for a few minutes is the cheap failure.
	if not frappe.db.has_column("Container Cost Line", "import_expense"):
		frappe.throw(_("Landed cost from expenses is not available yet on this site (migration pending)."))

	expense = frappe.db.get_value(
		"Import Expense",
		import_expense,
		[
			"commercial_invoice",
			"container",
			"truck",
			"category",
			"cost_component",
			"supplier",
			"currency",
			"amount",
			"expense_date",
			"expense_account",
			"invoice_reference",
			"include_in_landed_cost",
		],
		as_dict=True,
	)

	# Gate 5 — already capitalized. The flag and the rows are checked separately
	# because either one alone can be the truth: the flag survives a hand-deleted
	# row, and rows survive a hand-cleared flag. Re-running would duplicate cost.
	if cint(expense.include_in_landed_cost):
		frappe.throw(_("{0} is already included in the landed cost.").format(import_expense))
	if frappe.db.count("Container Cost Line", {"import_expense": import_expense}):
		frappe.throw(
			_("{0} already has landed-cost lines. Remove them before adding it again.").format(import_expense)
		)

	# Gate 6 — the account gate that replaces the bill path's supplier group.
	_assert_valuation_account(import_expense, expense.expense_account)

	refs = _expense_import_refs(expense)

	# Gate 7 — never the goods supplier's own money (CIF, same reason as a bill).
	if expense.supplier:
		_assert_not_ci_supplier(expense.supplier, _ci_supplier_behind(refs))

	# Gate 8 — every target exists, lives in the SAME company, and is readable.
	# The expense's links are plain Links with no company filter of their own, so
	# without this a name from another tenant's company would be charged here.
	for col, doctype in _HAND_LINKABLE_REFS:
		value = refs.get(col)
		if not value:
			continue
		if not frappe.db.exists(doctype, value):
			frappe.throw(_("Unknown {0}: {1}").format(_(doctype), value))
		if _company_of(doctype, value) != company:
			frappe.throw(_("{0} {1} belongs to another company.").format(_(doctype), value))
		_assert_can_read(doctype, value)

	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	currency = expense.currency or company_currency

	# Gate 9 — a currency the cost book can actually value (see the helper).
	_assert_capitalizable_currency(import_expense, currency, company_currency)

	amount = flt(expense.amount)
	if amount <= 0:
		frappe.throw(_("{0} has no amount to add to the landed cost.").format(import_expense))

	if not _containers_behind_refs(refs):
		frappe.throw(
			_("{0} has no containers yet, so there is nothing to charge the cost to.").format(
				expense.commercial_invoice or import_expense
			)
		)

	component = _resolve_expense_cost_component(expense, cost_component)

	# The company-currency figure. A Purchase Invoice stores its own
	# `base_net_total`; an Import Expense stores nothing of the kind, so it is
	# converted here at the expense date. Be clear about what this number is and
	# is not: it feeds `Container Cost Line.amount_uzs`, which is DISPLAY ONLY —
	# `lcv_math.line_company_amount` re-converts from the GRN-date rate when the
	# voucher is built. So the 1.0 fallback inside `_latest_exchange_rate` can
	# make this column approximate on a site with no stored rate; it cannot make
	# the valuation wrong.
	if currency == company_currency:
		base_amount = amount
	else:
		rate, _as_of = _latest_exchange_rate(currency, company_currency, expense.expense_date)
		base_amount = flt(amount) * flt(rate)

	row_names, skipped = _capitalize_import_cost(
		refs=refs,
		component=component,
		amount=amount,
		base_amount=base_amount,
		currency=currency,
		description=_("Expense {0}").format(expense.invoice_reference or import_expense),
		source_field="import_expense",
		source_name=import_expense,
	)

	warnings = [
		_(
			"A hand-entered {0} cost on container {1} is already capitalized by {2}. "
			"The expense was not added a second time there."
		).format(_(skip["cost_component"]), skip["container"], skip["vouchered_by"])
		for skip in skipped
	]

	if not row_names:
		# Every container refused the line. Nothing was written, so the flag would
		# be a receipt for rows that do not exist — and the operator would be told
		# the cost is in the valuation when it is not.
		frappe.throw(
			" ".join(warnings) or _("{0} could not be added to the landed cost.").format(import_expense)
		)

	# update_modified=False for the reason the bill path documents: this stamp is
	# not part of what the expense form submits, but `modified` is, and bumping it
	# under an open form turns the user's next Save into a concurrency failure.
	frappe.db.set_value(
		"Import Expense",
		import_expense,
		{"include_in_landed_cost": 1, "cost_component": component},
		update_modified=False,
	)

	return {
		"name": import_expense,
		"include_in_landed_cost": True,
		"cost_component": component,
		"cost_lines": row_names,
		"warnings": warnings,
	}


@frappe.whitelist()
def clear_expense_landed_cost(import_expense: str) -> dict:
	"""Undo ``set_expense_landed_cost`` — the escape hatch for a wrong capitalization.

	Mirrors ``clear_bill_import_refs``: no docstatus gate (there is none to have),
	and the one rule that actually protects money is the voucher check. Once a
	Landed Cost Voucher has consumed these lines the cost is inside stock
	valuation, and taking it back out is the accountant's reversal to make, not
	this endpoint's.

	``cost_component`` is deliberately left on the expense. It is the operator's
	classification of what this money is, not a by-product of the link, and it is
	still right if they capitalize the expense again.
	"""
	if not import_expense or not frappe.db.exists("Import Expense", import_expense):
		frappe.throw(_("Unknown Import Expense: {0}").format(import_expense))

	company = _company_of("Import Expense", import_expense)
	_assert_imports_access(company)
	_assert_can_write("Import Expense", import_expense)
	_assert_cost_visible()

	if not frappe.db.has_column("Container Cost Line", "import_expense"):
		frappe.throw(_("Landed cost from expenses is not available yet on this site (migration pending)."))

	flagged = cint(frappe.db.get_value("Import Expense", import_expense, "include_in_landed_cost"))
	rows = frappe.db.count("Container Cost Line", {"import_expense": import_expense})
	if not flagged and not rows:
		frappe.throw(_("{0} is not included in the landed cost.").format(import_expense))

	vouchered = frappe.db.sql(
		"""
        SELECT cl.lcv_ref
        FROM `tabContainer Cost Line` cl
        WHERE cl.import_expense = %(expense)s
          AND cl.lcv_ref IS NOT NULL AND cl.lcv_ref != ''
        LIMIT 1
        """,
		{"expense": import_expense},
		as_dict=True,
	)
	if vouchered:
		frappe.throw(
			_("This expense is already vouchered ({0}) and can no longer be removed.").format(
				vouchered[0]["lcv_ref"]
			)
		)

	# Nothing here reached a voucher, so no posted valuation is being altered. Any
	# hand-typed line this expense superseded comes back on its own: the supersede
	# is computed when the voucher is built and never stored.
	frappe.db.delete("Container Cost Line", {"import_expense": import_expense})
	frappe.db.set_value(
		"Import Expense",
		import_expense,
		{"include_in_landed_cost": 0},
		update_modified=False,
	)

	return {
		"name": import_expense,
		"include_in_landed_cost": False,
		"cost_lines_removed": rows,
	}


#: Roles that can actually act on a "not configured" hint. The fix lives in
#: `Stabler Settings`, an admin-only surface, so naming a missing setting to
#: anyone else is noise they cannot clear — for them the silent hide stays.
_IMPORTS_CONFIG_ROLES = frozenset(_ADMIN_ROLES) | {"Imports Manager"}


def _not_configured_reason() -> str:
	"""One line for users who can fix the gap; "" — total silence — for everyone else.

	Silence was the original behaviour on every surface, and it is still right
	for an operator: a setting they cannot reach is not actionable. It is wrong
	for an administrator, because "this tenant does not use imports" and "one
	field in Stabler Settings was never filled in" look identical from the UI —
	which is precisely how msa ran for months with the whole hand-link feature
	dark and nobody noticing.
	"""
	if not set(frappe.get_roles()).intersection(_IMPORTS_CONFIG_ROLES):
		return ""
	return _(
		"Linking bills to an import is not configured for this company. Set the transport/service supplier groups in Stabler Settings."
	)


@frappe.whitelist()
def bill_import_link_state(purchase_invoice: str) -> dict:
	"""Read state for the PI-form picker (W1) — the server decides eligibility.

	The picker must never offer an action the write path would then refuse: a
	row that fails on click is the failure mode this endpoint exists to avoid.
	So this mirrors every non-target-dependent gate of ``set_bill_import_refs``
	and ``clear_bill_import_refs`` and returns a verdict instead of a guess.

	Never throws when the imports module is off — the Purchase Invoice form
	ships to tenants without imports, and an exception there would be a console
	error on every bill. Only an unknown Purchase Invoice name is an error.

	Returns no monetary amount: cost figures in this module are permission-
	masked, and this state probe must not become a new amount surface.
	"""
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Unknown Purchase Invoice: {0}").format(purchase_invoice))

	_assert_can_read("Purchase Invoice", purchase_invoice)

	company = _company_of("Purchase Invoice", purchase_invoice)

	# Imports off, or the user has no imports role => the feature does not exist
	# for this bill. Silent (no reason), and linked/can_unlink both stay False so
	# the picker renders nothing at all rather than a summary of a module the
	# user cannot act on. The role half mirrors `_assert_imports_access`, which
	# the write path calls: without it a purchasing-only user is offered a Link
	# button whose click then throws — the exact mismatch this endpoint exists
	# to prevent. It is mirrored rather than called because that helper raises,
	# and this endpoint must stay quiet on the tenants that have no imports.
	roles = set(frappe.get_roles())
	has_imports_role = bool(roles.intersection(_ADMIN_ROLES) or roles.intersection(_IMPORTS_ROLES))
	if not module_map_for(company).get("imports") or not has_imports_role:
		return {
			"eligible": False,
			"reason": "",
			"not_configured": False,
			"refs": dict.fromkeys(rules.PI_REF_COLUMNS, ""),
			"linked": False,
			"can_unlink": False,
			"company": company,
		}

	refs = _bill_import_refs(purchase_invoice)
	linked = any(refs[col] for col, _dt in _HAND_LINKABLE_REFS)
	# Mirrors both refusals of `clear_bill_import_refs`: an automation-owned ref
	# and an automation-owned bill (the back-pointer) each make Unlink throw.
	can_unlink = (
		linked and not refs["custom_import_expense"] and not _automation_owner_of_bill(purchase_invoice)
	)

	def _not_eligible(reason: str, *, not_configured: bool = False) -> dict:
		# ``not_configured`` is a UI signal, not a fact about the company: it is
		# raised only together with a reason the caller is allowed to read, so a
		# client can render the hint without second-guessing an empty string.
		return {
			"eligible": False,
			"reason": reason,
			"not_configured": not_configured,
			"refs": refs,
			"linked": linked,
			"can_unlink": can_unlink,
			"company": company,
		}

	bill = frappe.db.get_value("Purchase Invoice", purchase_invoice, ["docstatus", "supplier"], as_dict=True)

	# Mirrors gate 3: cancelled only. A submitted bill is eligible.
	if cint(bill.docstatus) == 2:
		return _not_eligible(
			_("A cancelled bill cannot be linked to an import: {0}.").format(purchase_invoice)
		)

	groups = imports_transport_supplier_groups_for(company)
	if not groups:
		# Unconfigured => the hand-link feature is off for this company. Same
		# silent polarity as the module-off branch above for anyone who cannot
		# fix it; an administrator is told, because "this tenant does not use
		# imports" and "one field was never filled in" are otherwise identical
		# from the UI — which is how msa ran with the feature dark for months.
		reason = _not_configured_reason()
		return _not_eligible(reason, not_configured=bool(reason))

	supplier_group = frappe.db.get_value("Supplier", bill.supplier, "supplier_group")
	if supplier_group not in groups:
		return _not_eligible(
			_(
				"Supplier {0} belongs to group {1}, which is not one of the "
				"transport/service groups whose bills may be linked to an import."
			).format(bill.supplier, supplier_group or _("(none)"))
		)

	# Any of the four refs already set — including custom_import_expense, which
	# is automation-owned and not one of the three "linked" refs above. Naming
	# the first one set is enough: gate 4 of set_bill_import_refs refuses on the
	# same condition regardless of which ref it is.
	for col in rules.PI_REF_COLUMNS:
		if refs[col]:
			return _not_eligible(
				_("{0} is already linked to {1} {2}.").format(
					purchase_invoice, _(_PI_REF_DOCTYPES[col]), refs[col]
				)
			)

	return {
		"eligible": True,
		"reason": "",
		"not_configured": False,
		"refs": refs,
		"linked": False,
		"can_unlink": False,
		"company": company,
	}


#: Same cap as ``unbilled_landed_costs``. Reported in the response rather than
#: applied silently — a truncated picker that looks complete is how a bill goes
#: missing.
_UNLINKED_BILL_LIMIT = 500


@frappe.whitelist()
def unlinked_transport_bills(commercial_invoice: str) -> dict:
	"""Bills that ``set_bill_import_refs`` would accept for this CI (W2's panel).

	Deliberately company-wide rather than CI-specific: an unlinked bill carries
	no ref by definition, so nothing ties it to one import yet — that is the
	choice the user is about to make. The CI is what supplies the company and
	the supplier to exclude.

	Every gate of ``set_bill_import_refs`` that can be expressed as a filter is
	one here, so the panel cannot offer a row the write path would refuse.
	"""
	if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
		frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))

	ci = frappe.db.get_value("Commercial Invoice", commercial_invoice, ["company", "supplier"], as_dict=True)
	_assert_imports_access(ci.company)
	_assert_can_read("Commercial Invoice", commercial_invoice)
	# This panel reports each candidate's grand total and outstanding amount.
	# Cost figures in this module are permission-masked; a new picker must not
	# become the one place a user without cost visibility can read them.
	_assert_cost_visible()

	groups = imports_transport_supplier_groups_for(ci.company)
	if not groups:
		# Not configured => the feature is off; there are no candidates at all.
		# ``reason`` is non-empty only for a user who can open Stabler Settings,
		# so the panel keeps hiding silently for everyone else exactly as before.
		return {
			"rows": [],
			"summary": {"rows": 0, "limit": _UNLINKED_BILL_LIMIT, "capped": False},
			"configured": False,
			"reason": _not_configured_reason(),
		}

	conds = [
		"pi.company = %(company)s",
		# Drafts and submitted bills, to match gate 3 of ``set_bill_import_refs``
		# exactly — the two surfaces must move together, or the picker offers a
		# row whose click the write path then refuses. Cancelled (2) is excluded
		# for the same reason gate 3 refuses it: every read of these refs filters
		# `docstatus < 2`, so such a link would be invisible everywhere.
		"pi.docstatus < 2",
		"s.supplier_group IN %(groups)s",
	]
	params: dict = {
		"company": ci.company,
		"groups": groups,
		# One more than the cap: the extra row is how truncation is detected.
		"limit": _UNLINKED_BILL_LIMIT + 1,
	}
	# All four refs empty — a bill already attributed to ANY import (including
	# another CI) is not a candidate. A column absent on this site holds no ref.
	for col in _existing_pi_ref_columns():
		conds.append(f"(pi.{col} IS NULL OR pi.{col} = '')")
	if ci.supplier:
		conds.append("pi.supplier != %(ci_supplier)s")
		params["ci_supplier"] = ci.supplier

	rows = frappe.db.sql(
		f"""
        SELECT pi.name, pi.supplier, s.supplier_name, s.supplier_group, pi.bill_no,
               pi.posting_date, pi.due_date, pi.currency, pi.grand_total,
               pi.outstanding_amount, pi.status, pi.docstatus
        FROM `tabPurchase Invoice` pi
        INNER JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE {" AND ".join(conds)}
        ORDER BY pi.posting_date DESC, pi.name DESC
        LIMIT %(limit)s
        """,
		params,
		as_dict=True,
	)
	capped = len(rows) > _UNLINKED_BILL_LIMIT
	rows = rows[:_UNLINKED_BILL_LIMIT]
	for r in rows:
		r["grand_total"] = flt(r.get("grand_total"))
		r["outstanding_amount"] = flt(r.get("outstanding_amount"))
		r["posting_date"] = str(r["posting_date"]) if r.get("posting_date") else None
		r["due_date"] = str(r["due_date"]) if r.get("due_date") else None
		r["supplier_name"] = r.get("supplier_name") or r.get("supplier")
		r["docstatus"] = cint(r.get("docstatus"))

	return {
		"rows": rows,
		"summary": {"rows": len(rows), "limit": _UNLINKED_BILL_LIMIT, "capped": capped},
		"configured": True,
	}


#: How many advance-carrying PIs list_pi_advances() may examine before it stops.
#: Only reached by scope="open", where openness is computed per PI in Python.
_ADVANCE_SCAN_LIMIT = 2000


@frappe.whitelist()
def list_pi_advances(
	company: str,
	scope: str = "open",
	supplier: str | None = None,
	search: str | None = None,
	limit: int = 200,
) -> list[dict]:
	"""Advance ledgers for every PI that carries at least one advance Payment Entry.

	One row per PI, each row being exactly what :func:`pi_advance_ledger` returns for
	that PI plus the list columns (``supplier``, ``supplier_name``, ``pi_date``,
	``status``). ``scope="open"`` keeps only PIs that still hold advance credit —
	``advance_available > 0`` or an unapproved (draft) payment pending — which is the
	whole point of the page: a PI drops off the list once its advance is consumed.

	``advance_available`` is derived, not a column, so the scope filter cannot run in
	SQL. The candidate scan is therefore bounded by ``_ADVANCE_SCAN_LIMIT`` and
	``limit`` is applied to the *filtered* rows; applying it to the candidates instead
	would silently hide open advances behind newer, already-consumed ones.
	"""
	_assert_imports_access(company)
	_assert_cost_visible()

	has_pe_pi_ref = frappe.db.has_column("Payment Entry", "custom_proforma_invoice")
	pi_match = " OR pe.custom_proforma_invoice = pi.name" if has_pe_pi_ref else ""

	query = f"""
		SELECT pi.name, pi.supplier, pi.pi_date, pi.status, pi.currency,
		       pi.supplier_pi_ref, pi.agreed_total, pi.advance_pct,
		       pi.docs_total, pi.cash_difference, s.supplier_name
		FROM `tabProforma Invoice` pi
		LEFT JOIN `tabSupplier` s ON s.name = pi.supplier
		WHERE pi.company = %(company)s
		  AND EXISTS (
		      SELECT 1
		      FROM `tabPayment Entry` pe
		      LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		      WHERE pe.company = %(company)s AND pe.docstatus < 2
		        AND ((per.reference_doctype IN ('Purchase Order', 'Proforma Invoice')
		              AND per.reference_name = pi.name){pi_match})
		  )
	"""

	filters = {"company": company}

	if supplier:
		query += " AND pi.supplier = %(supplier)s"
		filters["supplier"] = supplier

	if search:
		query += (
			" AND (pi.name LIKE %(search)s OR pi.supplier_pi_ref LIKE %(search)s"
			" OR s.supplier_name LIKE %(search)s)"
		)
		filters["search"] = f"%{search}%"

	limit = max(1, int(limit))
	# scope="all" needs no post-filter, so the SQL LIMIT is exact. scope="open" is
	# decided per PI in Python, so scan wider and cut afterwards.
	query += " ORDER BY pi.creation DESC LIMIT %(scan)s"
	filters["scan"] = limit if scope == "all" else _ADVANCE_SCAN_LIMIT

	candidates = frappe.db.sql(query, filters, as_dict=True)
	if scope != "all" and len(candidates) >= _ADVANCE_SCAN_LIMIT:
		# Silent truncation on a money list is how a "paid" advance goes missing.
		# The UI warns when it receives a full page; this makes the harder case —
		# the scan cap, which the row count alone cannot reveal — observable too.
		frappe.logger("stabler.imports").warning(
			f"list_pi_advances hit the candidate scan cap ({_ADVANCE_SCAN_LIMIT}) "
			f"for company={company}; older advances may be missing from the result."
		)

	results = []
	for row in candidates:
		# Parent fields only — _build_proforma_advance_ledger reads no child table,
		# so a full get_doc per PI would load items/containers for nothing. The
		# list-vs-single identity test guards this equivalence.
		advances, _paid_bank, _paid_cash = _po_advance_payment_entries(row.name, company)
		ledger = _build_proforma_advance_ledger(row, advances)

		ledger["supplier"] = row.supplier
		ledger["supplier_name"] = row.supplier_name
		ledger["pi_date"] = str(row.pi_date) if row.pi_date else None
		ledger["status"] = row.status

		if scope != "all" and not (
			flt(ledger["summary"].get("advance_available")) > 0
			or flt(ledger["summary"].get("advance_pending_approval")) > 0
		):
			continue

		results.append(ledger)
		if len(results) >= limit:
			break

	return results
