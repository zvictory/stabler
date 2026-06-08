"""CRM module API for Stabler — thin whitelisted wrappers over Frappe CRM doctypes."""

from __future__ import annotations

import json

import frappe
from frappe import _

from stabler.api.organization import _can_access_module


def _require_crm():
    if not _can_access_module(frappe.session.user, "crm"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


_CRM_MANAGER_ROLES = {"Sales Manager", "System Manager", "Stabler Admin"}


def _require_crm_manager():
    """Pipeline config (create/edit/delete/reorder deal statuses) is manager-only."""
    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & _CRM_MANAGER_ROLES):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_leads(search="", status="", lead_owner="", page_length=50, start=0):
    _require_crm()
    where_parts = []
    values: dict = {"limit": int(page_length), "start": int(start)}

    if search:
        where_parts.append(
            "(lead_name LIKE %(search)s OR email LIKE %(search)s OR organization LIKE %(search)s)"
        )
        values["search"] = f"%{search}%"
    if status:
        where_parts.append("status = %(status)s")
        values["status"] = status
    if lead_owner:
        where_parts.append("lead_owner = %(lead_owner)s")
        values["lead_owner"] = lead_owner

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    count_vals = {k: v for k, v in values.items() if k not in ("limit", "start")}

    rows = frappe.db.sql(
        f"""SELECT name, lead_name, first_name, last_name, email, mobile_no,
                   organization, status, lead_owner, source, modified
            FROM `tabCRM Lead`
            {where}
            ORDER BY modified DESC
            LIMIT %(limit)s OFFSET %(start)s""",
        values,
        as_dict=True,
    )
    total = (frappe.db.sql(f"SELECT COUNT(*) FROM `tabCRM Lead` {where}", count_vals) or [[0]])[0][0]
    return {"leads": rows, "total": total}


@frappe.whitelist()
def get_lead(name: str):
    _require_crm()
    if not frappe.has_permission("CRM Lead", "read", name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    return frappe.get_doc("CRM Lead", name).as_dict()


@frappe.whitelist()
def save_lead(data: str | dict):
    _require_crm()
    data = frappe.parse_json(data)
    if data.get("name"):
        if not frappe.has_permission("CRM Lead", "write", data["name"]):
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        doc = frappe.get_doc("CRM Lead", data["name"])
        doc.update(data)
    else:
        doc = frappe.new_doc("CRM Lead")
        doc.update(data)
    doc.save()
    return doc.as_dict()


@frappe.whitelist()
def delete_lead(name: str):
    _require_crm()
    if not frappe.has_permission("CRM Lead", "delete", name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    frappe.delete_doc("CRM Lead", name)
    return "ok"


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_deals(search="", status="", deal_owner="", page_length=50, start=0):
    _require_crm()
    where_parts = []
    values: dict = {"limit": int(page_length), "start": int(start)}

    if search:
        where_parts.append(
            "(organization LIKE %(search)s OR email LIKE %(search)s OR lead_name LIKE %(search)s)"
        )
        values["search"] = f"%{search}%"
    if status:
        where_parts.append("status = %(status)s")
        values["status"] = status
    if deal_owner:
        where_parts.append("deal_owner = %(deal_owner)s")
        values["deal_owner"] = deal_owner

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    count_vals = {k: v for k, v in values.items() if k not in ("limit", "start")}

    rows = frappe.db.sql(
        f"""SELECT name, organization, lead_name, email, mobile_no, status,
                   deal_owner, deal_value, currency, probability,
                   expected_closure_date, modified
            FROM `tabCRM Deal`
            {where}
            ORDER BY modified DESC
            LIMIT %(limit)s OFFSET %(start)s""",
        values,
        as_dict=True,
    )
    total = (frappe.db.sql(f"SELECT COUNT(*) FROM `tabCRM Deal` {where}", count_vals) or [[0]])[0][0]
    return {"deals": rows, "total": total}


@frappe.whitelist()
def get_deal(name: str):
    _require_crm()
    if not frappe.has_permission("CRM Deal", "read", name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    return frappe.get_doc("CRM Deal", name).as_dict()


@frappe.whitelist()
def save_deal(data: str | dict):
    _require_crm()
    data = frappe.parse_json(data)
    if data.get("name"):
        if not frappe.has_permission("CRM Deal", "write", data["name"]):
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        doc = frappe.get_doc("CRM Deal", data["name"])
        doc.update(data)
    else:
        doc = frappe.new_doc("CRM Deal")
        doc.update(data)
    doc.save()
    return doc.as_dict()


@frappe.whitelist()
def delete_deal(name: str):
    _require_crm()
    if not frappe.has_permission("CRM Deal", "delete", name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    frappe.delete_doc("CRM Deal", name)
    return "ok"


# ---------------------------------------------------------------------------
# Metadata (dropdown options for forms)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def crm_meta():
    _require_crm()
    return {
        "lead_statuses": frappe.get_all(
            "CRM Lead Status",
            fields=["name", "color", "position", "type"],
            order_by="position asc",
        ),
        "deal_statuses": frappe.get_all(
            "CRM Deal Status",
            fields=["name", "color", "position", "type"],
            order_by="position asc",
        ),
        "sources": frappe.get_all("CRM Lead Source", pluck="name", order_by="name"),
        "industries": frappe.get_all("CRM Industry", pluck="name", order_by="name"),
    }


# ---------------------------------------------------------------------------
# Deal status (Kanban column) management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def save_deal_status(data):
    """Upsert a CRM Deal Status. data = JSON {name, color, position, type}."""
    _require_crm_manager()
    d = json.loads(data) if isinstance(data, str) else data
    name = (d.get("name") or "").strip()
    if not name:
        frappe.throw(_("Status name is required"))

    if frappe.db.exists("CRM Deal Status", name):
        doc = frappe.get_doc("CRM Deal Status", name)
        for k in ("color", "position", "type"):
            if k in d:
                doc.set(k, d[k])
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.new_doc("CRM Deal Status")
        doc.update(d)
        doc.insert(ignore_permissions=True)

    frappe.db.commit()
    return {"name": doc.name, "color": doc.get("color"), "position": doc.get("position"), "type": doc.get("type")}


@frappe.whitelist()
def delete_deal_status(name):
    """Delete a CRM Deal Status. Blocked if any deal is in that status."""
    _require_crm_manager()
    count = frappe.db.count("CRM Deal", {"status": name})
    if count:
        frappe.throw(_("Cannot delete: {0} deal(s) are still in this status.").format(count))
    frappe.delete_doc("CRM Deal Status", name, ignore_permissions=True)
    frappe.db.commit()
    return "ok"


@frappe.whitelist()
def reorder_deal_statuses(names):
    """Bulk-update column positions. names = JSON array in desired display order."""
    _require_crm_manager()
    order = json.loads(names) if isinstance(names, str) else names
    for i, name in enumerate(order):
        frappe.db.set_value("CRM Deal Status", name, "position", i + 1, update_modified=False)
    frappe.db.commit()
    return "ok"
