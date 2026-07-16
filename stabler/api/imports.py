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

from stabler.api import _imports_rules as rules
from stabler.api import _proforma
from stabler.api._common import _assert_can_read, _require_company
from stabler.api.organization import _ADMIN_ROLES, _MODULE_ROLES
from stabler.api.permissions import cost_visible_for
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


@frappe.whitelist()
def list_commercial_invoices(
    company: str,
    search: str | None = None,
    status: str | None = None,
    supplier: str | None = None,
    limit_start: int = 0,
    limit_page_length: int = 50,
):
    """Commercial Invoice list rows (docs/cash masked for non-cost users)."""
    _assert_imports_access(company)
    clauses, params = rules.ci_filter_clauses(search, status, supplier)
    params["company"] = company
    params["limit_start"] = max(0, cint(limit_start))
    params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
    where = " AND ".join(["ci.company = %(company)s", *clauses])
    rows = frappe.db.sql(
        f"""
        SELECT
          ci.name, ci.ci_number, ci.supplier, s.supplier_name, ci.ci_date,
          ci.status, ci.incoterm, ci.eta_transit_port, ci.total_kg, ci.total_boxes,
          ci.agreed_total, ci.docs_total, ci.cash_difference, ci.currency,
          (SELECT COUNT(*) FROM `tabImport Container` c
             WHERE c.commercial_invoice = ci.name) AS container_count,
          EXISTS(SELECT 1 FROM `tabGRN Checklist` g
             WHERE g.commercial_invoice = ci.name) AS has_grn
        FROM `tabCommercial Invoice` ci
        LEFT JOIN `tabSupplier` s ON s.name = ci.supplier
        WHERE {where}
        ORDER BY ci.ci_date DESC, ci.name DESC
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

    payload = {
        "name": doc.name,
        "modified": str(doc.modified),
        "company": doc.company,
        "import_pi_group": doc.import_pi_group,
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
                "item": it.item,
                "description": it.description,
                "hs_code": it.hs_code,
                "qty": flt(it.qty),
                "uom": it.uom,
                "rate": flt(it.rate),
                "amount": flt(it.amount),
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
        "customs_fee_breakdown": _safe_customs_breakdown(name),
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


_CI_HEADER_FIELDS = (
    "import_pi_group",
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
        cleaned.append(
            {
                "item": item,
                "description": row.get("description") or None,
                "hs_code": row.get("hs_code") or None,
                "qty": qty,
                "uom": row.get("uom") or None,
                "rate": rate,
                "amount": qty * rate,
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
        line.item = row["item"]
        line.description = row["description"]
        line.hs_code = row["hs_code"]
        line.qty = row["qty"]
        line.uom = row["uom"]
        line.rate = row["rate"]
        line.amount = row["amount"]
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
    limit_start: int = 0,
    limit_page_length: int = 50,
):
    """Import Container list rows (cost total masked for non-cost users)."""
    _assert_imports_access(company)
    clauses, params = rules.container_filter_clauses(search, status, commercial_invoice)
    params["company"] = company
    params["limit_start"] = max(0, cint(limit_start))
    params["limit_page_length"] = rules.clamp_page_length(limit_page_length)
    where = " AND ".join(["c.company = %(company)s", *clauses])
    rows = frappe.db.sql(
        f"""
        SELECT
          c.name, c.container_number, c.container_type, c.container_size,
          c.commercial_invoice, c.supplier, c.status, c.total_kg, c.total_boxes,
          c.total_amount, c.currency, c.advance_70_payment_entry,
          (SELECT COALESCE(SUM(cl.amount), 0) FROM `tabContainer Cost Line` cl
             WHERE cl.parent = c.name) AS cost_lines_total
        FROM `tabImport Container` c
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
    total = _count(rules.count_query("`tabImport Container` c", where), params)
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

    The "CI STUFFED → GRN" action, surfaced manually in v1: copies the CI items
    as expected quantities and carries the supplier/company across. If a GRN
    already exists for the CI (the field is unique) the existing name is
    returned — so this can double as "open the GRN for this CI".

    NOTE: an automatic CI-status hook (create the GRN when the CI reaches
    STUFFED) is a later increment; for now the warehouse triggers it by hand.
    """
    if not commercial_invoice or not frappe.db.exists("Commercial Invoice", commercial_invoice):
        frappe.throw(_("Unknown Commercial Invoice: {0}").format(commercial_invoice))
    company = _company_of("Commercial Invoice", commercial_invoice)
    _assert_imports_access(company)

    existing = frappe.db.get_value("GRN Checklist", {"commercial_invoice": commercial_invoice})
    if existing:
        return {"name": existing, "created": False}

    ci = frappe.get_doc("Commercial Invoice", commercial_invoice)
    grn = frappe.new_doc("GRN Checklist")
    grn.company = company
    grn.commercial_invoice = commercial_invoice
    grn.supplier = ci.supplier
    grn.expected_arrival_date = ci.get("eta_transit_port")
    for it in ci.items or []:
        box_kg = 20.0
        qty = flt(it.qty)
        line = grn.append("grn_items", {})
        line.item_code = it.item
        line.item_name = frappe.db.get_value("Item", it.item, "item_name") or it.item
        line.expected_box_kg = box_kg
        line.expected_boxes = round(qty / box_kg) if box_kg else 0
        line.expected_total_kg = qty
    if not grn.grn_items:
        frappe.throw(_("The commercial invoice has no items to receive."))
    grn.insert(ignore_permissions=False)
    return {"name": grn.name, "created": True}


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
def list_pi_groups(company: str):
    """PI Groups for a company + the count of import orders in each."""
    _assert_imports_access(company)
    groups = frappe.get_all(
        "Import PI Group",
        filters={"company": company},
        fields=["name", "title", "status", "remarks"],
        order_by="creation desc",
    )
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
        for g in groups:
            g["order_count"] = by_grp.get(g["name"], 0)
    else:
        for g in groups:
            g["order_count"] = 0
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
