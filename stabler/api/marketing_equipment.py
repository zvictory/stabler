"""Marketing — Equipment & Repair Requests API.

Whitelisted endpoints for the Equipment doctype (cooler/freezer/rack/POSM
assets placed at outlets) and EquipmentRepairRequest workflow.

Role gating:
- Reads: any logged-in user with company access (filtered via outlet.company).
- Writes: Marketing User, Warehouse User, or System Manager.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from stabler.api._common import _assert_can_read, _assert_can_write
from stabler.api.sfa import _company_filter, _is_admin

_WRITE_ROLES = {"System Manager", "Marketing User", "Warehouse User"}
_REPAIR_WRITE_ROLES = {"System Manager", "Marketing User", "Warehouse User", "Sales User"}


def _require_write_equipment() -> None:
	roles = set(frappe.get_roles())
	if not roles & _WRITE_ROLES:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_write_repair() -> None:
	roles = set(frappe.get_roles())
	if not roles & _REPAIR_WRITE_ROLES:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _outlets_for_company_filter() -> list[str] | None:
	"""Return outlet names visible to the caller via the company filter.

	Returns None when no company restriction applies (e.g. unrestricted admin).
	"""
	cf = _company_filter(None)
	if not cf:
		return None
	return [row["name"] for row in frappe.get_all("Outlet", filters=cf, fields=["name"], limit=0)]


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

_EQUIPMENT_FIELDS = [
	"name",
	"asset_tag",
	"category",
	"outlet",
	"brand",
	"model",
	"serial_no",
	"install_date",
	"warranty_until",
	"status",
	"utilization_pct",
]


@frappe.whitelist()
def list_equipment(
	filters: dict | str | None = None,
	limit: int = 200,
) -> list[dict]:
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}
	filters = dict(filters or {})

	query_filters: dict[str, Any] = {}
	for key in ("category", "outlet", "status"):
		val = filters.get(key)
		if val:
			query_filters[key] = val

	search = filters.get("search")
	or_filters = None
	if search:
		needle = f"%{search}%"
		or_filters = [
			["asset_tag", "like", needle],
			["serial_no", "like", needle],
			["brand", "like", needle],
			["model", "like", needle],
		]

	# Scope by outlet.company when the caller is restricted.
	allowed_outlets = _outlets_for_company_filter()
	if allowed_outlets is not None:
		# Allow equipment with no outlet only for admins.
		if not allowed_outlets:
			return []
		query_filters["outlet"] = ["in", allowed_outlets]

	return frappe.get_all(
		"Equipment",
		filters=query_filters,
		or_filters=or_filters,
		fields=_EQUIPMENT_FIELDS,
		order_by="asset_tag asc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_equipment(name: str) -> dict:
	_assert_can_read("Equipment", name)
	if not name:
		frappe.throw(_("Equipment name is required."))
	doc = frappe.get_doc("Equipment", name)
	if doc.outlet:
		outlet_company = frappe.db.get_value("Outlet", doc.outlet, "company")
		_company_filter(outlet_company)
	elif not _is_admin():
		# Unassigned equipment is visible to admins only.
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc.as_dict()


@frappe.whitelist()
def create_equipment(payload: dict | str) -> dict:
	_require_write_equipment()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("asset_tag", "category"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))

	outlet = payload.get("outlet")
	if outlet:
		outlet_company = frappe.db.get_value("Outlet", outlet, "company")
		_company_filter(outlet_company)
	elif not _is_admin():
		frappe.throw(_("Outlet is required."), frappe.PermissionError)

	doc = frappe.get_doc({"doctype": "Equipment", **payload})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_equipment_status(name: str, status: str) -> dict:
	_assert_can_write("Equipment", name, "write")
	_require_write_equipment()
	if not name:
		frappe.throw(_("Equipment name is required."))
	if status not in ("InService", "Repair", "Retired"):
		frappe.throw(_("Invalid status: {0}").format(status))

	doc = frappe.get_doc("Equipment", name)
	if doc.outlet:
		outlet_company = frappe.db.get_value("Outlet", doc.outlet, "company")
		_company_filter(outlet_company)
	elif not _is_admin():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc.status = status
	doc.save()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Equipment Repair Request
# ---------------------------------------------------------------------------

_REPAIR_FIELDS = [
	"name",
	"equipment",
	"reported_by",
	"reported_at",
	"issue",
	"photo_url",
	"assigned_technician",
	"status",
	"resolved_at",
]


def _repair_equipment_outlets(equipment_names: list[str]) -> dict[str, str | None]:
	"""Map equipment name -> outlet name (None if unassigned)."""
	if not equipment_names:
		return {}
	rows = frappe.get_all(
		"Equipment",
		filters={"name": ["in", equipment_names]},
		fields=["name", "outlet"],
	)
	return {row["name"]: row.get("outlet") for row in rows}


@frappe.whitelist()
def list_repair_requests(
	filters: dict | str | None = None,
	limit: int = 200,
) -> list[dict]:
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}
	filters = dict(filters or {})

	query_filters: dict[str, Any] = {}
	for key in ("equipment", "status", "assigned_technician", "reported_by"):
		val = filters.get(key)
		if val:
			query_filters[key] = val

	allowed_outlets = _outlets_for_company_filter()
	if allowed_outlets is not None:
		if not allowed_outlets:
			return []
		allowed_equipment = frappe.get_all(
			"Equipment",
			filters={"outlet": ["in", allowed_outlets]},
			fields=["name"],
			limit=0,
		)
		allowed_names = [row["name"] for row in allowed_equipment]
		if not allowed_names:
			return []
		existing = query_filters.get("equipment")
		if existing and existing not in allowed_names:
			return []
		query_filters["equipment"] = existing or ["in", allowed_names]

	return frappe.get_all(
		"Equipment Repair Request",
		filters=query_filters,
		fields=_REPAIR_FIELDS,
		order_by="reported_at desc, creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_repair_request(name: str) -> dict:
	_assert_can_read("Equipment Repair Request", name)
	if not name:
		frappe.throw(_("Repair Request name is required."))
	doc = frappe.get_doc("Equipment Repair Request", name)
	outlet = frappe.db.get_value("Equipment", doc.equipment, "outlet")
	if outlet:
		outlet_company = frappe.db.get_value("Outlet", outlet, "company")
		_company_filter(outlet_company)
	elif not _is_admin():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc.as_dict()


@frappe.whitelist()
def create_repair_request(
	equipment: str,
	issue: str,
	photo_url: str | None = None,
) -> dict:
	_require_write_repair()
	if not equipment:
		frappe.throw(_("Equipment is required."))
	if not issue:
		frappe.throw(_("Issue is required."))

	outlet = frappe.db.get_value("Equipment", equipment, "outlet")
	if outlet:
		outlet_company = frappe.db.get_value("Outlet", outlet, "company")
		_company_filter(outlet_company)
	elif not _is_admin():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc = frappe.get_doc(
		{
			"doctype": "Equipment Repair Request",
			"equipment": equipment,
			"issue": issue,
			"photo_url": photo_url,
		}
	)
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_repair_status(
	name: str,
	status: str,
	assigned_technician: str | None = None,
) -> dict:
	_assert_can_write("Equipment Repair Request", name, "write")
	_require_write_repair()
	if not name:
		frappe.throw(_("Repair Request name is required."))
	if status not in ("Open", "InProgress", "Resolved", "Cancelled"):
		frappe.throw(_("Invalid status: {0}").format(status))

	doc = frappe.get_doc("Equipment Repair Request", name)
	outlet = frappe.db.get_value("Equipment", doc.equipment, "outlet")
	if outlet:
		outlet_company = frappe.db.get_value("Outlet", outlet, "company")
		_company_filter(outlet_company)
	elif not _is_admin():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc.status = status
	if assigned_technician is not None:
		doc.assigned_technician = assigned_technician or None
	# Controller stamps resolved_at when status becomes Resolved.
	doc.save()
	return doc.as_dict()
