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
from frappe.utils import add_days, cint, flt, getdate, today

from stabler.api import _advance_aging
from stabler.api import _ci_to_pinv
from stabler.api import _customs_estimate
from stabler.api import _fx_reval
from stabler.api import _kts_amendment
from stabler.api import _imports_rules as rules
from stabler.api import _proforma
from stabler.api._common import _assert_can_read, _assert_can_write, _require_company
from stabler.api.organization import _ADMIN_ROLES, _MODULE_ROLES
from stabler.api.permissions import cost_visible_for
from stabler.stabler.imports_module import packing_service
from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

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

    pending_vet_certs = frappe.db.count(
        "Vet Certificate", {"company": company, "status": "Pending"}
    )
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
            v
            for k, v in ci_by_status.items()
            if k not in ("DELIVERED_TO_UZBEKISTAN", "Cancelled")
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
    clauses, params = rules.ci_filter_clauses(search, status, supplier)
    params["company"] = company
    params["limit_start"] = max(0, cint(limit_start))
    params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
    where = " AND ".join(["ci.company = %(company)s", *clauses])

    order_col = _CI_SORT_COLUMNS.get(sort_by or "", "ci.ci_date")
    order_dir = "ASC" if str(sort_dir or "").lower() == "asc" else "DESC"
    order_by = f"{order_col} {order_dir}, ci.name DESC"

    # The proforma link is a custom field, so it may be absent on a site that
    # has not carried the imports work — fall back to NULL rather than failing
    # the whole list.
    has_pi_link = frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice")
    pi_select = (
        """ci.custom_proforma_invoice AS proforma_invoice,
          COALESCE(pi.supplier_pi_ref, ci.custom_proforma_invoice) AS proforma_ref,"""
        if has_pi_link
        else "NULL AS proforma_invoice, NULL AS proforma_ref,"
    )
    pi_join = (
        "LEFT JOIN `tabProforma Invoice` pi ON pi.name = ci.custom_proforma_invoice"
        if has_pi_link
        else ""
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
          {pi_select}
          (SELECT COUNT(*) FROM `tabImport Container` c
             WHERE c.commercial_invoice = ci.name) AS container_count,
          (SELECT COUNT(*) FROM `tabImport Truck` tr
             WHERE tr.commercial_invoice = ci.name) AS truck_count,
          EXISTS(SELECT 1 FROM `tabGRN Checklist` g
             WHERE g.commercial_invoice = ci.name) AS has_grn
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
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
                "custom_proforma_invoice": it.get("custom_proforma_invoice") or doc.get("custom_proforma_invoice"),
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
            fields=["name", "truck_number", "driver_name", "driver_phone", "trucking_company", "status", "total_kg", "total_boxes", "transport_cost"],
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
    doc.set("items", [])
    total_boxes = 0
    total_kg = 0.0
    agreed_total = 0.0
    for row in cleaned:
        line = doc.append("items", {})
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
    if doc.get("custom_proforma_invoice") and frappe.db.exists("Proforma Invoice", doc.custom_proforma_invoice):
        try:
            link_proforma_to_ci(doc.custom_proforma_invoice, doc.name, company)
        except Exception:
            pass
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
    if doc.get("custom_proforma_invoice") and frappe.db.exists("Proforma Invoice", doc.custom_proforma_invoice):
        try:
            link_proforma_to_ci(doc.custom_proforma_invoice, doc.name, company)
        except Exception:
            pass
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
          (SELECT COALESCE(s_tr.supplier_name, fb.transporter)
           FROM `tabFreight Booking` fb
           LEFT JOIN `tabSupplier` s_tr ON s_tr.name = fb.transporter
           WHERE fb.container = c.name OR (fb.commercial_invoice = c.commercial_invoice AND c.commercial_invoice IS NOT NULL)
           ORDER BY fb.creation DESC LIMIT 1) AS transporter,
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
    for r in rows:
        r["cost_lines_total"] = flt(r["cost_lines_total"])
    rules.mask_named(rows, rules.CONTAINER_LIST_MASK_FIELDS, _cost_visible())
    total = _count(rules.count_query("`tabImport Container` c LEFT JOIN `tabCommercial Invoice` ci ON ci.name = c.commercial_invoice LEFT JOIN `tabSupplier` s ON s.name = c.supplier", where), params)
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
        "customs_clearance_date": str(doc.customs_clearance_date)
        if doc.customs_clearance_date
        else None,
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
    rules.mask_named(payload, rules.CONTAINER_MASK_FIELDS, visible)
    return payload


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
        "border_crossing_date": str(doc.border_crossing_date)
        if doc.border_crossing_date
        else None,
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
        r["expected_arrival_date"] = (
            str(r["expected_arrival_date"]) if r["expected_arrival_date"] else None
        )
        r["docstatus"] = cint(r["docstatus"])
        r["claim_required"] = bool(r["claim_required"])
        r["lcv_count"] = cint(r["lcv_count"])
    total = _count(rules.count_query("`tabGRN Checklist` g", where), params)
    return {"rows": rows, "total_count": total}


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
        "expected_arrival_date": str(doc.expected_arrival_date)
        if doc.expected_arrival_date
        else None,
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
            }
            for it in (doc.grn_items or [])
        ],
        "truck_receipts": truck_receipts,
        "landed_cost_vouchers": [
            {
                "lcv": lc.lcv,
                "posted_on": str(lc.posted_on) if lc.posted_on else None,
                "note": lc.note,
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
    locked = bool(
        frappe.db.get_value("GRN Checklist", result["name"], "expected_snapshot_locked")
    )
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
    commercial_invoice = frappe.db.get_value(
        "GRN Checklist", name, "commercial_invoice"
    )
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
    if (
        cint(grn_state.docstatus) != 0
        or cint(grn_state.expected_snapshot_locked)
        or submitted_receipt
    ):
        frappe.throw(_("Expected quantities are locked after the first submitted Truck Receipt."))
    summary = packing_service.summary_for_ci(
        grn.commercial_invoice, company, for_update=True
    )
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
    return {
        "name": doc.name,
        "modified": str(doc.modified),
        "company": doc.company,
        "grn_checklist": doc.grn_checklist,
        "truck": doc.truck,
        "truck_number": frappe.db.get_value("Import Truck", doc.truck, "truck_number")
        if doc.truck
        else None,
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

    The submit hook logs these to ``stabler.imports`` but does not return them;
    we recompute the same ``receipt_math.resolve_po_rate`` decision so the SPA
    can show the warehouse why a line landed on the Purchase Receipt at rate 0.
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
        if res["warning"]:
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
    """Validate cost-line rows. ``lcv_ref`` is server-owned and never taken from the client."""
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
        existing_refs = {
            (cl.cost_component, flt(cl.amount)): cl.lcv_ref for cl in (doc.cost_lines or [])
        }
        doc.set("cost_lines", [])
        for row in _clean_container_cost_lines(cost_lines):
            line = doc.append("cost_lines", {})
            for key, value in row.items():
                line.set(key, value)
            # Preserve a consumed-marker for an unchanged component/amount pair so a
            # save from the form never silently re-vouchers an already-consumed line.
            line.lcv_ref = existing_refs.get((row["cost_component"], flt(row["amount"])))


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
    return {"name": container, "row_name": row_name, "include_in_landed_cost": cint(target.include_in_landed_cost)}


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
               ie.purchase_invoice
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
        "status": doc.status,
        "purchase_invoice": doc.purchase_invoice,
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
    doc.insert(ignore_permissions=False)
    return {"name": doc.name, "status": doc.status}


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
    doc.save(ignore_permissions=False)
    return {"name": doc.name, "status": doc.status}


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
    purchase_receipts = []
    for pr in pr_names:
        prd = frappe.db.get_value(
            "Purchase Receipt",
            pr,
            ["supplier", "posting_date", "grand_total", "currency", "docstatus"],
            as_dict=True,
        )
        if prd:
            purchase_receipts.append(
                {
                    "name": pr,
                    "supplier": prd.supplier,
                    "posting_date": str(prd.posting_date) if prd.posting_date else None,
                    "grand_total": flt(prd.grand_total),
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
    if override and override > 0:
        usd_rate, rate_as_of = override, None
        rate_overridden = True
    else:
        usd_rate, rate_as_of = _latest_exchange_rate("USD", company_currency, grn.completion_date)
        rate_overridden = False

    cost_lines, _rows = imports_hooks._collect_cost_lines(grn.commercial_invoice)
    components = lcv_math.aggregate_components(cost_lines, usd_rate, company_currency)
    warnings: list[str] = []
    if gtd is not None:
        components, warnings = lcv_math.apply_gtd_customs_precedence(
            components, gtd_duty=gtd[0], gtd_excise=gtd[1], gtd_present=True
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
            "can_create": bool(pr_names and preview_components),
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


def _enrich_bill_rows(rows, today_d) -> None:
    """In-place: derive category, overdue flag, stringify due_date on bill rows."""
    codes_by_pi = _pi_item_codes([r["name"] for r in rows])
    for r in rows:
        r["category"] = rules.derive_bill_category(
            truck_ref=r.get("custom_import_truck"),
            expense_ref=r.get("custom_import_expense"),
            item_codes=codes_by_pi.get(r["name"], []),
            bill_no=r.get("bill_no"),
        )
        r["grand_total"] = flt(r.get("grand_total"))
        r["outstanding_amount"] = flt(r.get("outstanding_amount"))
        r["overdue"] = rules.is_overdue(r.get("due_date"), today_d, r["outstanding_amount"])
        r["due_date"] = str(r["due_date"]) if r.get("due_date") else None
        r["supplier_name"] = r.get("supplier_name") or r.get("supplier")


def _related_import_bills(company, *, container, ci, trucks, ref_cols, today_d):
    """Purchase Invoices referencing this container OR its CI OR its trucks (v46)."""
    match: list[str] = []
    params: dict = {"company": company}
    if "custom_import_container" in ref_cols and container:
        match.append("pi.custom_import_container = %(container)s")
        params["container"] = container
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
    _enrich_bill_rows(rows, today_d)
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

    trucks = (
        frappe.get_all("Import Truck", filters={"commercial_invoice": ci}, pluck="name")
        if ci
        else []
    )
    bills = _related_import_bills(
        company, container=container, ci=ci, trucks=trucks, ref_cols=ref_cols, today_d=today_d
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
    _enrich_bill_rows(rows, today())
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
        markers.append(
            "(po.custom_prepayment_type IS NOT NULL AND po.custom_prepayment_type != '')"
        )
    if cols["pi_group"]:
        markers.append(
            "(po.custom_import_pi_group IS NOT NULL AND po.custom_import_pi_group != '')"
        )
    if not markers:
        return empty  # imports custom fields not synced yet — nothing to show

    clauses, params = rules.import_order_filter_clauses(
        search, vendor, pi_group, has_pi_group_col=cols["pi_group"]
    )
    params["company"] = company
    where = " AND ".join(
        ["po.company = %(company)s", "(" + " OR ".join(markers) + ")", *clauses]
    )
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
    pending = sum(
        1 for s in ci_status.values() if s not in ("DELIVERED_TO_UZBEKISTAN", "Cancelled")
    )
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
    """Advance Payment Entries referencing a PO, split bank/cash (allocated amounts).

    Bank vs cash comes from ``custom_payment_stream`` when that field exists;
    otherwise it is inferred from the mode-of-payment / paid-from account name.
    """
    has_stream = frappe.db.has_column("Payment Entry", "custom_payment_stream")
    stream_col = "pe.custom_payment_stream" if has_stream else "NULL"
    rows = frappe.db.sql(
        f"""
        SELECT pe.name, pe.paid_amount, pe.posting_date, pe.docstatus, pe.mode_of_payment,
               pe.paid_from, pe.reference_no, {stream_col} AS payment_stream,
               COALESCE(SUM(per.allocated_amount), 0) AS allocated_to_po
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        WHERE pe.company = %(company)s AND pe.docstatus < 2
          AND per.reference_doctype = 'Purchase Order'
          AND per.reference_name = %(po)s
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
        amt = flt(r["allocated_to_po"]) or flt(r["paid_amount"])
        if stream == "Cash":
            paid_cash += amt
        else:
            paid_bank += amt
        out.append(
            {
                "name": r["name"],
                "paid_amount": flt(r["paid_amount"]),
                "allocated_to_po": flt(r["allocated_to_po"]),
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
                line.custom_docs_amount = row["docs_amount"] or round(
                    row["qty"] * row["docs_rate"], 2
                )


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
        pi_stats = {r["grp"]: {"count": cint(r["c"]), "total_agreed": flt(r["total_agreed"])} for r in pi_rows}
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
                _(
                    "Not eligible for this group (vendor restriction or already in "
                    "another group): {0}"
                ).format(", ".join(bad))
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
# Advance payment — 1-2 DRAFT Payment Entries against the PO (Bank / Cash)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_advance_payment(
    purchase_order: str,
    bank_amount=0,
    cash_amount=0,
    payment_date: str | None = None,
    reference_no: str | None = None,
):
    """Record an advance against an import order as 1-2 DRAFT Payment Entries.

    Mirrors the Django record-advance flow (financial_ops): one PE for the bank
    stream, one for the cash stream, each a Pay to the supplier referencing the
    PO. Payment Entries are NEVER submitted here — they stay drafts for Accounts
    to post. Cost-visible only (bank/cash split is dual-pricing data, K3). Equal
    split is not enforced; an unequal bank/cash split returns a soft warning.
    """
    if not purchase_order or not frappe.db.exists("Purchase Order", purchase_order):
        frappe.throw(_("Unknown Purchase Order: {0}").format(purchase_order))
    company = _company_of("Purchase Order", purchase_order)
    _assert_imports_access(company)
    _assert_cost_visible()
    doc = frappe.get_doc("Purchase Order", purchase_order)
    if doc.docstatus != 1:
        frappe.throw(_("Confirm (submit) the import order before recording an advance."))
    if not doc.supplier:
        frappe.throw(_("The import order has no supplier."))

    bank = round(flt(bank_amount), 2)
    cash = round(flt(cash_amount), 2)
    if bank <= 0 and cash <= 0:
        frappe.throw(_("Enter a bank and/or cash amount."))
    on_date = getdate(payment_date) if payment_date else getdate(today())

    from stabler.stabler.imports_module.hooks import _apply_pay_accounts

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
        pe.append(
            "references",
            {
                "reference_doctype": "Purchase Order",
                "reference_name": purchase_order,
                "allocated_amount": amount,
            },
        )
        _apply_pay_accounts(pe, company, doc.supplier)
        pe.insert(ignore_permissions=False)  # DRAFT — never submitted here.
        created.append({"name": pe.name, "stream": stream, "amount": amount})

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
        return {"proforma": pi.name, "status": pi.status,
                "commercial_invoice": commercial_invoice, "changed": False}

    if not _proforma.can_supersede(pi.status):
        frappe.throw(
            _("Proforma {0} cannot be superseded from status {1}.").format(pi.name, pi.status)
        )

    pi.status = _proforma.SUPERSEDED
    pi.commercial_invoice = commercial_invoice
    pi.save(ignore_permissions=True)
    if frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice"):
        ci.db_set("custom_proforma_invoice", proforma, update_modified=False)

    return {"proforma": pi.name, "status": pi.status,
            "commercial_invoice": commercial_invoice, "changed": True}


def _proforma_list_filters(company: str, status: str | None, supplier: str | None,
                            group: str | None, search: str | None) -> tuple[list[str], dict]:
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
        clauses.append("pi.import_pi_group = %(group)s")
        params["group"] = group
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
def list_proformas(company: str, status: str | None = None, supplier: str | None = None,
                   search: str | None = None, group: str | None = None,
                   limit: int = 100) -> list[dict]:
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


@frappe.whitelist()
def proforma_list_stats(company: str, status: str | None = None, supplier: str | None = None,
                        group: str | None = None, search: str | None = None) -> dict:
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
def commercial_invoice_list_stats(company: str, status: str | None = None,
                                   supplier: str | None = None, search: str | None = None) -> dict:
    """Aggregate totals over the same filter set as list_commercial_invoices for top metric strip."""
    _assert_imports_access(company)
    clauses = ["ci.company = %(company)s"]
    params = {"company": company}
    if status:
        clauses.append("ci.status = %(status)s")
        params["status"] = status
    if supplier:
        clauses.append("ci.supplier = %(supplier)s")
        params["supplier"] = supplier
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
def container_list_stats(company: str, status: str | None = None,
                         commercial_invoice: str | None = None, search: str | None = None,
                         bl_type: str | None = None) -> dict:
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
        clauses.append("(t.name LIKE %(q)s OR t.truck_number LIKE %(q)s OR t.driver_name LIKE %(q)s OR t.commercial_invoice LIKE %(q)s)")
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

    advances = frappe.db.sql(
        """
        SELECT pe.name, pe.posting_date, pe.paid_amount, pe.paid_amount_after_tax, pe.mode_of_payment, pe.docstatus
        FROM `tabPayment Entry` pe
        WHERE pe.party_type = 'Supplier' AND pe.party = %(supplier)s AND pe.docstatus < 2
        ORDER BY pe.posting_date DESC
        LIMIT 20
        """,
        {"supplier": doc.supplier},
        as_dict=True,
    )
    data["advance_payments"] = advances
    data["invoiced_summary"] = get_pi_invoiced_summary(name)

    return data


def get_pi_invoiced_summary(name: str) -> dict:
    """Returns total ordered, invoiced, and remaining quantities per Vendor Category & Item Cut for a PI."""
    if not name or not frappe.db.exists("Proforma Invoice", name):
        return {"items": [], "total_ordered_kg": 0.0, "total_invoiced_kg": 0.0, "total_remaining_kg": 0.0, "pct": 0.0}

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

        rem_b = max(0, pi_b - inv_b)
        rem_q = max(0.0, flt(pi_q - inv_q, 2))
        pct = flt((inv_q / pi_q) * 100, 1) if pi_q > 0 else (100.0 if inv_q > 0 else 0.0)

        tot_ordered_kg += pi_q
        tot_invoiced_kg += inv_q

        summary_items.append({
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
        })

    tot_remaining_kg = max(0.0, flt(tot_ordered_kg - tot_invoiced_kg, 2))
    overall_pct = flt((tot_invoiced_kg / tot_ordered_kg) * 100, 1) if tot_ordered_kg > 0 else 0.0

    return {
        "items": summary_items,
        "total_ordered_kg": tot_ordered_kg,
        "total_invoiced_kg": tot_invoiced_kg,
        "total_remaining_kg": tot_remaining_kg,
        "pct": overall_pct,
    }


@frappe.whitelist()
def get_vendor_available_pi_lines(company: str, supplier: str, exclude_ci: str | None = None) -> dict:
    """Fetch all open Proforma Invoices for a supplier with remaining unshipped line items.
    Calculates remaining_boxes = PI_item.boxes - sum(shipped_boxes) across active CIs."""
    _assert_imports_access(company)
    if not supplier:
        return {"proformas": [], "lines": []}

    pis = frappe.db.get_all(
        "Proforma Invoice",
        filters={"company": company, "supplier": supplier, "docstatus": ["<", 2], "status": ["!=", "CANCELLED"]},
        fields=["name", "supplier_pi_ref", "pi_date", "currency", "incoterm", "import_pi_group"],
        order_by="pi_date desc, name desc",
    )

    if not pis:
        return {"proformas": [], "lines": []}

    pi_names = [p.name for p in pis]
    if not pi_names:
        return {"proformas": pis, "lines": []}

    pi_items = frappe.db.sql(
        """
        SELECT name, parent, item, description, category, '' AS hs_code, boxes, box_weight_kg,
               qty, rate AS agreed_rate, docs_price, amount AS agreed_amount, docs_amount
        FROM `tabProforma Invoice Item`
        WHERE parent IN %(pi_names)s
        ORDER BY idx ASC
        """,
        {"pi_names": tuple(pi_names)},
        as_dict=True,
    )

    if not pi_items:
        return {"proformas": pis, "lines": []}

    ci_conds = ["ci.company = %(company)s", "ci.status != 'Cancelled'", "cii.custom_proforma_invoice IN %(pi_names)s"]
    params = {"company": company, "pi_names": tuple(pi_names)}
    if exclude_ci:
        ci_conds.append("ci.name != %(exclude_ci)s")
        params["exclude_ci"] = exclude_ci

    ci_where = " AND ".join(ci_conds)
    shipped_rows = frappe.db.sql(
        f"""
        SELECT cii.custom_proforma_invoice AS pi_name, cii.item, cii.category,
               SUM(cii.boxes) AS shipped_boxes, SUM(cii.qty) AS shipped_qty
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        WHERE {ci_where}
        GROUP BY cii.custom_proforma_invoice, cii.item, cii.category
        """,
        params,
        as_dict=True,
    )

    shipped_map = {}
    for r in shipped_rows:
        key = (r["pi_name"], r["item"], r["category"] or "")
        shipped_map[key] = {
            "shipped_boxes": cint(r["shipped_boxes"]),
            "shipped_qty": flt(r["shipped_qty"]),
        }

    available_lines = []
    for it in pi_items:
        key = (it["parent"], it["item"], it["category"] or "")
        shipped = shipped_map.get(key, {"shipped_boxes": 0, "shipped_qty": 0.0})

        pi_boxes = cint(it["boxes"])
        shipped_boxes = shipped["shipped_boxes"]
        remaining_boxes = max(0, pi_boxes - shipped_boxes)

        available_lines.append({
            "pi_name": it["parent"],
            "pi_ref": frappe.db.get_value("Proforma Invoice", it["parent"], "supplier_pi_ref") or it["parent"],
            "item": it["item"],
            "description": it["description"] or "",
            "category": it["category"] or "",
            "hs_code": it["hs_code"] or "",
            "contract_boxes": pi_boxes,
            "shipped_boxes": shipped_boxes,
            "remaining_boxes": remaining_boxes,
            "box_weight_kg": flt(it["box_weight_kg"]),
            "agreed_rate": flt(it["agreed_rate"]),
            "docs_price": flt(it["docs_price"]),
        })

    return {
        "proformas": pis,
        "lines": available_lines,
    }


def get_pi_tracking_for_ci(ci_doc) -> list[dict]:
    """Returns row-level PI tracking for a Commercial Invoice."""
    ref_pis = set()
    if ci_doc.get("custom_proforma_invoice"):
        ref_pis.add(ci_doc.custom_proforma_invoice)
    for it in (ci_doc.items or []):
        if it.get("custom_proforma_invoice"):
            ref_pis.add(it.custom_proforma_invoice)

    tracking_results = []
    for pi_name in sorted(ref_pis):
        if not frappe.db.exists("Proforma Invoice", pi_name):
            continue
        pi_doc = frappe.get_doc("Proforma Invoice", pi_name)

        other_ci_rows = frappe.db.sql(
            """
            SELECT cii.category, cii.item, cii.boxes, cii.qty
            FROM `tabCommercial Invoice Item` cii
            JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
            WHERE (cii.custom_proforma_invoice = %(pi)s OR (COALESCE(cii.custom_proforma_invoice, '') = '' AND ci.custom_proforma_invoice = %(pi)s))
              AND ci.status != 'Cancelled'
              AND ci.name != %(this_ci)s
            """,
            {"pi": pi_name, "this_ci": ci_doc.name},
            as_dict=True,
        )

        prior_map = {}
        prior_by_code = {}
        for r in other_ci_rows:
            key = (r["category"] or "", r["item"])
            if key not in prior_map:
                prior_map[key] = {"boxes": 0, "qty": 0.0}
            prior_map[key]["boxes"] += cint(r["boxes"])
            prior_map[key]["qty"] += flt(r["qty"])

            code = r["item"]
            if code not in prior_by_code:
                prior_by_code[code] = {"boxes": 0, "qty": 0.0}
            prior_by_code[code]["boxes"] += cint(r["boxes"])
            prior_by_code[code]["qty"] += flt(r["qty"])

        this_ci_map = {}
        this_by_code = {}
        for r in (ci_doc.items or []):
            r_pi = r.get("custom_proforma_invoice") or ci_doc.get("custom_proforma_invoice")
            if r_pi == pi_name:
                key = (r.category or "", r.item)
                if key not in this_ci_map:
                    this_ci_map[key] = {"boxes": 0, "qty": 0.0}
                this_ci_map[key]["boxes"] += cint(r.boxes)
                this_ci_map[key]["qty"] += flt(r.qty)

                code = r.item
                if code not in this_by_code:
                    this_by_code[code] = {"boxes": 0, "qty": 0.0}
                this_by_code[code]["boxes"] += cint(r.boxes)
                this_by_code[code]["qty"] += flt(r.qty)

        for it in pi_doc.items:
            cat = it.category or ""
            code = it.item
            pi_b = cint(it.boxes)
            pi_q = flt(it.qty)

            pr_data = prior_map.get((cat, code)) or prior_by_code.get(code, {"boxes": 0, "qty": 0.0})
            pr_b = pr_data["boxes"]
            pr_q = pr_data["qty"]

            tc_data = this_ci_map.get((cat, code)) or this_by_code.get(code, {"boxes": 0, "qty": 0.0})
            tc_b = tc_data["boxes"]
            tc_q = tc_data["qty"]

            tot_inv_b = pr_b + tc_b
            tot_inv_q = pr_q + tc_q
            rem_b = max(0, pi_b - tot_inv_b)
            rem_q = max(0.0, flt(pi_q - tot_inv_q, 2))
            pct = flt((tot_inv_q / pi_q) * 100, 1) if pi_q > 0 else (100.0 if tot_inv_q > 0 else 0.0)

            tracking_results.append({
                "proforma_invoice": pi_name,
                "supplier_pi_ref": pi_doc.supplier_pi_ref or pi_name,
                "category": cat,
                "item": code,
                "description": it.description or code,
                "pi_boxes": pi_b,
                "pi_qty": pi_q,
                "prior_invoiced_boxes": pr_b,
                "prior_invoiced_qty": pr_q,
                "this_ci_boxes": tc_b,
                "this_ci_qty": tc_q,
                "total_invoiced_boxes": tot_inv_b,
                "total_invoiced_qty": tot_inv_q,
                "remaining_boxes": rem_b,
                "remaining_qty": rem_q,
                "pct": pct,
            })

    return tracking_results


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

    for field in ("supplier", "company", "pi_date", "supplier_pi_ref", "import_pi_group",
                  "currency", "incoterm", "incoterm_location", "port_of_loading",
                  "port_of_discharge", "prepayment_type", "agreed_total", "advance_pct",
                  "bank_agreed", "cash_agreed", "status", "remarks"):
        if field in data:
            doc.set(field, data.get(field))

    doc.set("items", [])
    for row in (data.get("items") or []):
        if not (row or {}).get("item"):
            continue
        doc.append("items", {
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
        })

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
    counts = dict(
        frappe.db.sql(
            """
            SELECT parent, COUNT(*) FROM `tabStabler Vendor Category Item`
            GROUP BY parent
            """
        )
    )
    for r in rows:
        r["item_count"] = cint(counts.get(r["name"], 0))
    return rows


@frappe.whitelist()
def vendor_category_detail(name: str) -> dict:
    """One category with its item rows (for the edit modal + PI category fill)."""
    if not name or not frappe.db.exists("Stabler Vendor Category", name):
        frappe.throw(_("Unknown vendor category: {0}").format(name))
    doc = frappe.get_doc("Stabler Vendor Category", name)
    items = []
    for it in doc.items or []:
        meta = frappe.db.get_value(
            "Item", it.item_code, ["item_name", "stock_uom"], as_dict=True
        ) or {}
        items.append({
            "item_code": it.item_code,
            "item_name": meta.get("item_name"),
            "stock_uom": meta.get("stock_uom"),
            "boxes_per_container": cint(it.boxes_per_container),
        })
    return {
        "name": doc.name,
        "vendor": doc.vendor,
        "category_name": doc.category_name,
        "display_name": doc.display_name,
        "description": doc.get("description"),
        "is_active": cint(doc.is_active),
        "items": items,
        "total_boxes_per_container": sum(i["boxes_per_container"] for i in items),
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
    for row in (data.get("items") or []):
        if not (row or {}).get("item_code"):
            continue
        doc.append("items", {
            "item_code": row["item_code"],
            "boxes_per_container": cint(row.get("boxes_per_container")),
        })
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
    names = frappe.get_all(
        "Import Container", filters={"commercial_invoice": ci_name}, pluck="name"
    )
    return names[0] if len(names) == 1 else None


def _ci_import_advances(company: str, ci) -> list[dict]:
    """Submitted advance Payment Entries for a CI, across its containers.

    Only submitted PEs (docstatus=1) with an unallocated balance and matching
    the CI's supplier can be allocated to the invoice. Deduped by PE name.
    """
    seen: dict[str, dict] = {}
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
            seen[adv["name"]] = {
                "name": adv["name"],
                "unallocated_amount": flt(adv.get("unallocated_amount")),
                "party": adv.get("party"),
            }
    return [seen[k] for k in sorted(seen)]


def _restrict_advances_to_import(doc, import_pe_names: set) -> float:
    """Populate the PInv's advances via ERPNext, then keep only this CI's import
    advances. Returns the total allocated. Degrades safely: if set_advances
    can't run, the draft simply carries no advances (Accounts adds them)."""
    try:
        doc.set_advances()
    except Exception:
        doc.set("advances", [])
        return 0.0
    kept = []
    total = 0.0
    for row in doc.get("advances") or []:
        if row.reference_type == "Payment Entry" and row.reference_name in import_pe_names:
            kept.append(row)
            total += flt(row.allocated_amount)
    doc.set("advances", kept)
    return round(total, 2)


@frappe.whitelist()
def convert_ci_to_purchase_invoice(
    commercial_invoice: str, company: str, dry_run: int = 1
) -> dict:
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
            frappe.db.get_value(
                "Commercial Invoice", commercial_invoice, "name", for_update=True
            )
        existing = frappe.db.get_value(
            "Purchase Invoice",
            {"custom_commercial_invoice": commercial_invoice, "docstatus": ["<", 2]},
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
    if ci.currency:
        doc.currency = ci.currency
    doc.set_posting_time = 1
    doc.posting_date = getdate(today())
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

    allocated = _restrict_advances_to_import(doc, {a["name"] for a in advances})
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
        "summary": _fx_reval.reval_summary(
            [r for r in annotated if not r.get("rate_missing")]
        ),
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
            r.update(
                {"channel": "unsplit", "bank_due": outstanding, "cash_due": 0.0, "unsplit": True}
            )

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
        "gated": departure_math.gates_this_transition("PENDING", "DEPARTED_IRAN")
        and doc.status == "PENDING",
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
        "Commercial Invoice", commercial_invoice,
        ["status", "vessel", "voyage", "eta", "eta_transit_port"], as_dict=True,
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
            skipped.append({
                "container": c.name,
                "container_number": c.container_number,
                "status": c.status,
                "state": sea_lifecycle.drift(ci_status, c.status)["state"],
            })
            continue
        steps = sea_lifecycle.path(c.status, ci_status)
        planned.append({
            "container": c.name,
            "container_number": c.container_number,
            "from": c.status,
            "to": ci_status,
            "steps": steps,
        })
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

        frappe.db.set_value("Commercial Invoice", doc.name, {
            "total_boxes": total_boxes,
            "total_kg": total_kg,
            "agreed_total": agreed_total,
            "docs_total": docs_total,
            "cash_difference": cash_diff
        }, update_modified=False)
        updated_count += 1

    frappe.db.commit()
    return {"updated": updated_count}
