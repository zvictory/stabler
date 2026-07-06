"""BPM (Business Process Management) API for Stabler — process diagrams."""
from __future__ import annotations

import frappe
from frappe import _

from stabler.api.organization import _can_access_module


def _require_bpm():
    if not _can_access_module(frappe.session.user, "bpm"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def list_processes(search="", status="", company="", page_length=50, start=0):
    """List Stabler Process records visible to the current company."""
    _require_bpm()
    page_length = min(int(page_length or 50), 500)
    start = int(start or 0)

    # Multi-tenant scoping: validate a passed company against the caller's
    # allowed set; when omitted, restrict a scoped non-admin to their allowed
    # companies rather than returning every tenant's processes. Admins /
    # unrestricted users (empty allowed list) are unaffected.
    from stabler.api.organization import _ADMIN_ROLES, _user_allowed_companies

    is_admin = any(r in frappe.get_roles() for r in _ADMIN_ROLES)
    allowed = [] if is_admin else _user_allowed_companies(frappe.session.user)

    filters = {}
    if company:
        if allowed and company not in allowed:
            frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
        filters["company"] = company
    elif allowed:
        filters["company"] = ["in", allowed]
    if status:
        filters["status"] = status

    if search:
        filters["process_name"] = ["like", f"%{search}%"]

    processes = frappe.get_all(
        "Stabler Process",
        filters=filters,
        fields=["name", "process_name", "company", "status", "modified"],
        order_by="modified desc",
        limit=page_length,
        start=start,
    )
    total = frappe.db.count("Stabler Process", filters)
    return {"processes": processes, "total": total}


@frappe.whitelist()
def get_process(name):
    """Return a single Stabler Process document."""
    _require_bpm()
    if not frappe.db.exists("Stabler Process", name):
        frappe.throw(_("Process not found: {0}").format(name), frappe.DoesNotExistError)
    if not frappe.has_permission("Stabler Process", "read", name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    doc = frappe.get_doc("Stabler Process", name)
    return doc.as_dict()


@frappe.whitelist()
def save_process(data):
    """Create or update a Stabler Process.

    `data` is a JSON-stringified dict. The `diagram` field is stored as-is
    (a JSON string of {lanes, nodes, edges}).
    """
    _require_bpm()
    if isinstance(data, str):
        data = frappe.parse_json(data)

    name = data.get("name")
    if name and frappe.db.exists("Stabler Process", name):
        if not frappe.has_permission("Stabler Process", "write", name):
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        doc = frappe.get_doc("Stabler Process", name)
        for field in ("process_name", "company", "status", "diagram"):
            if field in data:
                setattr(doc, field, data[field])
        doc.save(ignore_permissions=True)
    else:
        if not frappe.has_permission("Stabler Process", "create"):
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        doc = frappe.new_doc("Stabler Process")
        doc.process_name = data.get("process_name", _("Untitled Process"))
        doc.company = data.get("company", "")
        doc.status = data.get("status", "Draft")
        doc.diagram = data.get("diagram", "")
        doc.insert(ignore_permissions=True)

    return {"name": doc.name, "process_name": doc.process_name, "status": doc.status}


@frappe.whitelist()
def delete_process(name):
    """Delete a Stabler Process."""
    _require_bpm()
    if not frappe.db.exists("Stabler Process", name):
        frappe.throw(_("Process not found: {0}").format(name), frappe.DoesNotExistError)
    if not frappe.has_permission("Stabler Process", "delete", name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    frappe.delete_doc("Stabler Process", name, ignore_permissions=True)
    return {"ok": True}
