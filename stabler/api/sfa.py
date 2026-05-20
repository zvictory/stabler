"""Field Sales (SFA) API for Stabler.

Phase 1 stubs covering Outlet / Route / Visit CRUD plus the visit lifecycle
hooks (check_in / check_out / update_step). Geo-fence distance is computed
server-side with the haversine formula — clients pass raw GPS only.

Role gating:
- Read endpoints allow any logged-in user with access to the company.
- Write endpoints require "Sales User" or "System Manager".
- Field-user-scoped views: non-admins are restricted to their own visits/routes
  via the field_user filter (admins see all).
"""

from __future__ import annotations

import math
from typing import Any

import frappe
from frappe import _

from stabler.api.organization import _user_allowed_companies


_EARTH_RADIUS_M = 6_371_000.0
_WRITE_ROLES = {"System Manager", "Sales User"}


def _require_write() -> None:
	roles = set(frappe.get_roles())
	if not roles & _WRITE_ROLES:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _is_admin() -> bool:
	return "System Manager" in frappe.get_roles()


def _company_filter(company: str | None) -> dict:
	"""Build a Frappe filter dict for the company field, honouring allowed companies."""
	allowed = _user_allowed_companies(frappe.session.user)
	if company:
		if allowed and company not in allowed and not _is_admin():
			frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
		return {"company": company}
	if allowed:
		return {"company": ["in", allowed]}
	return {}


def _update_doc(doctype: str, name: str, payload: dict | str) -> dict:
	"""Shared edit helper for SFA / Marketing list pages.

	Loads the doc, enforces tenant isolation against both the existing and
	(if changed) target company, applies `payload` via `doc.update()` (which
	cascades to child tables — replace-all semantics; the frontend MUST send
	the full child array), then saves. Returns the serialized doc.
	"""
	_require_write()
	if not name:
		frappe.throw(_("{0} name is required.").format(doctype))
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	if not isinstance(payload, dict):
		frappe.throw(_("Payload must be an object."))
	doc = frappe.get_doc(doctype, name)
	_company_filter(doc.company)
	# defense in depth: payload could try to move the row across companies
	target_company = payload.get("company", doc.company)
	if target_company != doc.company:
		_company_filter(target_company)
	doc.update(payload)
	doc.save()
	return doc.as_dict()


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
	"""Great-circle distance in metres."""
	phi1 = math.radians(lat1)
	phi2 = math.radians(lat2)
	d_phi = math.radians(lat2 - lat1)
	d_lambda = math.radians(lng2 - lng1)
	a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
	return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _to_float(value: Any, label: str) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a number").format(label))


# ---------------------------------------------------------------------------
# Outlets
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_outlets(
	company: str | None = None,
	channel: str | None = None,
	outlet_class: str | None = None,
	assigned_field_user: str | None = None,
	is_active: int | None = 1,
	search: str | None = None,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if channel:
		filters["channel"] = channel
	if outlet_class:
		filters["outlet_class"] = outlet_class
	if assigned_field_user:
		filters["assigned_field_user"] = assigned_field_user
	if is_active is not None and is_active != "":
		filters["is_active"] = 1 if str(is_active) in ("1", "true", "True") else 0

	or_filters = None
	if search:
		needle = f"%{search}%"
		or_filters = [
			["outlet_code", "like", needle],
			["outlet_name", "like", needle],
		]

	return frappe.get_all(
		"Outlet",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"outlet_code",
			"outlet_name",
			"company",
			"customer",
			"channel",
			"outlet_class",
			"assigned_field_user",
			"credit_limit",
			"is_active",
			"address",
			"gps_lat",
			"gps_lng",
		],
		order_by="outlet_name asc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_outlet(name: str) -> dict:
	if not name:
		frappe.throw(_("Outlet name is required."))
	doc = frappe.get_doc("Outlet", name)
	_company_filter(doc.company)  # raises if not permitted
	return doc.as_dict()


@frappe.whitelist()
def create_outlet(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("outlet_code", "outlet_name", "company"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Outlet", **payload})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_outlet(name: str, payload: dict | str) -> dict:
	return _update_doc("Outlet", name, payload)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_routes(
	company: str | None = None,
	field_user: str | None = None,
	day_of_week: str | None = None,
	is_active: int | None = 1,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if not _is_admin() and not field_user:
		field_user = frappe.session.user
	if field_user:
		filters["field_user"] = field_user
	if day_of_week:
		filters["day_of_week"] = day_of_week
	if is_active is not None and is_active != "":
		filters["is_active"] = 1 if str(is_active) in ("1", "true", "True") else 0

	return frappe.get_all(
		"Route",
		filters=filters,
		fields=[
			"name",
			"route_code",
			"route_name",
			"company",
			"field_user",
			"day_of_week",
			"is_active",
		],
		order_by="route_name asc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_route(name: str) -> dict:
	if not name:
		frappe.throw(_("Route name is required."))
	doc = frappe.get_doc("Route", name)
	_company_filter(doc.company)
	if not _is_admin() and doc.field_user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc.as_dict()


@frappe.whitelist()
def create_route(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("route_code", "route_name", "company", "field_user"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Route", **payload})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_route(name: str, payload: dict | str) -> dict:
	return _update_doc("Route", name, payload)


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------

_VISIT_FIELDS = [
	"name",
	"outlet",
	"route",
	"field_user",
	"company",
	"planned_date",
	"status",
	"check_in_at",
	"check_out_at",
	"distance_from_outlet_m",
]


@frappe.whitelist()
def list_visits(
	company: str | None = None,
	field_user: str | None = None,
	planned_date: str | None = None,
	status: str | None = None,
	outlet: str | None = None,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if not _is_admin() and not field_user:
		field_user = frappe.session.user
	if field_user:
		filters["field_user"] = field_user
	if planned_date:
		filters["planned_date"] = planned_date
	if status:
		filters["status"] = status
	if outlet:
		filters["outlet"] = outlet

	return frappe.get_all(
		"Visit",
		filters=filters,
		fields=_VISIT_FIELDS,
		order_by="planned_date desc, creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_visit(name: str) -> dict:
	if not name:
		frappe.throw(_("Visit name is required."))
	doc = frappe.get_doc("Visit", name)
	_company_filter(doc.company)
	if not _is_admin() and doc.field_user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc.as_dict()


@frappe.whitelist()
def create_visit(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("outlet", "field_user", "company"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Visit", **payload})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def check_in(visit: str, lat: float, lng: float) -> dict:
	_require_write()
	if not visit:
		frappe.throw(_("Visit is required."))
	doc = frappe.get_doc("Visit", visit)
	_company_filter(doc.company)
	if not _is_admin() and doc.field_user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if doc.check_in_at:
		frappe.throw(_("Visit already checked in at {0}.").format(doc.check_in_at))

	lat_f = _to_float(lat, _("Latitude"))
	lng_f = _to_float(lng, _("Longitude"))

	outlet = frappe.get_doc("Outlet", doc.outlet)
	distance = None
	if outlet.gps_lat and outlet.gps_lng:
		distance = _haversine_m(lat_f, lng_f, float(outlet.gps_lat), float(outlet.gps_lng))

	doc.check_in_at = frappe.utils.now_datetime()
	doc.check_in_lat = lat_f
	doc.check_in_lng = lng_f
	if distance is not None:
		doc.distance_from_outlet_m = distance
	if doc.status == "Planned":
		doc.status = "InProgress"
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def check_out(visit: str, lat: float, lng: float) -> dict:
	_require_write()
	if not visit:
		frappe.throw(_("Visit is required."))
	doc = frappe.get_doc("Visit", visit)
	_company_filter(doc.company)
	if not _is_admin() and doc.field_user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not doc.check_in_at:
		frappe.throw(_("Cannot check out before checking in."))
	if doc.check_out_at:
		frappe.throw(_("Visit already checked out at {0}.").format(doc.check_out_at))

	doc.check_out_at = frappe.utils.now_datetime()
	doc.check_out_lat = _to_float(lat, _("Latitude"))
	doc.check_out_lng = _to_float(lng, _("Longitude"))
	doc.status = "Completed"
	doc.save()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Field Users
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_field_users(
	company: str | None = None,
	is_active: int | None = 1,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if is_active is not None and is_active != "":
		filters["is_active"] = 1 if str(is_active) in ("1", "true", "True") else 0

	return frappe.get_all(
		"Field User",
		filters=filters,
		fields=[
			"name",
			"user",
			"company",
			"default_warehouse",
			"default_route",
			"mobile_phone",
			"is_active",
		],
		order_by="user asc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_field_user(name: str) -> dict:
	if not name:
		frappe.throw(_("Field User name is required."))
	doc = frappe.get_doc("Field User", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_field_user(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("user", "company"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Field User", **payload})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_field_user(name: str, payload: dict | str) -> dict:
	return _update_doc("Field User", name, payload)


# ---------------------------------------------------------------------------
# Van stock
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_van_stock(
	company: str | None = None,
	field_user: str | None = None,
	posting_date: str | None = None,
	status: str | None = None,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if field_user:
		filters["field_user"] = field_user
	if posting_date:
		filters["posting_date"] = posting_date
	if status:
		filters["status"] = status

	return frappe.get_all(
		"Van Stock",
		filters=filters,
		fields=[
			"name",
			"field_user",
			"company",
			"posting_date",
			"status",
			"warehouse",
		],
		order_by="posting_date desc, creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_van_stock(name: str) -> dict:
	if not name:
		frappe.throw(_("Van Stock name is required."))
	doc = frappe.get_doc("Van Stock", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_van_stock(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("field_user", "company", "posting_date"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Van Stock", **payload})
	doc.insert()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Promo schemes
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_promo_schemes(
	company: str | None = None,
	scheme_type: str | None = None,
	is_active: int | None = 1,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if scheme_type:
		filters["scheme_type"] = scheme_type
	if is_active is not None and is_active != "":
		filters["is_active"] = 1 if str(is_active) in ("1", "true", "True") else 0

	return frappe.get_all(
		"Promo Scheme",
		filters=filters,
		fields=[
			"name",
			"scheme_code",
			"scheme_name",
			"company",
			"scheme_type",
			"discount_pct",
			"threshold_qty",
			"free_qty",
			"valid_from",
			"valid_to",
			"is_active",
		],
		order_by="scheme_name asc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_promo_scheme(name: str) -> dict:
	if not name:
		frappe.throw(_("Promo Scheme name is required."))
	doc = frappe.get_doc("Promo Scheme", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_promo_scheme(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("scheme_code", "scheme_name", "company", "scheme_type"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Promo Scheme", **payload})
	doc.insert()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Photo reports
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_photo_reports(
	company: str | None = None,
	outlet: str | None = None,
	visit: str | None = None,
	field_user: str | None = None,
	category: str | None = None,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if outlet:
		filters["outlet"] = outlet
	if visit:
		filters["visit"] = visit
	if not _is_admin() and not field_user:
		field_user = frappe.session.user
	if field_user:
		filters["field_user"] = field_user
	if category:
		filters["category"] = category

	return frappe.get_all(
		"Photo Report",
		filters=filters,
		fields=[
			"name",
			"visit",
			"outlet",
			"field_user",
			"company",
			"category",
			"captured_at",
			"photo_url",
			"photo_lat",
			"photo_lng",
		],
		order_by="captured_at desc, creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_photo_report(name: str) -> dict:
	if not name:
		frappe.throw(_("Photo Report name is required."))
	doc = frappe.get_doc("Photo Report", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_photo_report(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("outlet", "company", "category", "photo_url"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])
	payload.setdefault("field_user", frappe.session.user)
	payload.setdefault("captured_at", frappe.utils.now_datetime())

	doc = frappe.get_doc({"doctype": "Photo Report", **payload})
	doc.insert()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Planograms
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_planograms(
	company: str | None = None,
	outlet: str | None = None,
	category: str | None = None,
	is_active: int | None = 1,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if outlet:
		filters["outlet"] = outlet
	if category:
		filters["category"] = category
	if is_active is not None and is_active != "":
		filters["is_active"] = 1 if str(is_active) in ("1", "true", "True") else 0

	return frappe.get_all(
		"Planogram",
		filters=filters,
		fields=[
			"name",
			"outlet",
			"company",
			"category",
			"valid_from",
			"is_active",
		],
		order_by="creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_planogram(name: str) -> dict:
	if not name:
		frappe.throw(_("Planogram name is required."))
	doc = frappe.get_doc("Planogram", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_planogram(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("outlet", "company"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Planogram", **payload})
	doc.insert()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# OSA audits
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_osa_audits(
	company: str | None = None,
	outlet: str | None = None,
	visit: str | None = None,
	limit: int = 200,
) -> list[dict]:
	filters: dict = _company_filter(company)
	if outlet:
		filters["outlet"] = outlet
	if visit:
		filters["visit"] = visit

	return frappe.get_all(
		"OSA Audit",
		filters=filters,
		fields=[
			"name",
			"visit",
			"outlet",
			"company",
			"audited_at",
			"total_skus",
			"present_skus",
			"osa_pct",
		],
		order_by="audited_at desc, creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


@frappe.whitelist()
def get_osa_audit(name: str) -> dict:
	if not name:
		frappe.throw(_("OSA Audit name is required."))
	doc = frappe.get_doc("OSA Audit", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_osa_audit(payload: dict | str) -> dict:
	_require_write()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("outlet", "company"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])
	payload.setdefault("audited_at", frappe.utils.now_datetime())

	doc = frappe.get_doc({"doctype": "OSA Audit", **payload})
	doc.insert()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Receivables (read-only view over Sales Invoice)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_receivables(
	company: str | None = None,
	outlet: str | None = None,
	limit: int = 200,
) -> list[dict]:
	"""Outstanding Sales Invoices grouped by outlet.

	No new doctype: outlet.customer is the join key. Empty list when the outlet
	has no customer link or no outstanding invoices.
	"""
	filters: dict = {"outstanding_amount": [">", 0], "docstatus": 1}
	allowed = _user_allowed_companies(frappe.session.user)
	if company:
		if allowed and company not in allowed and not _is_admin():
			frappe.throw(_("Not permitted for company {0}").format(company), frappe.PermissionError)
		filters["company"] = company
	elif allowed:
		filters["company"] = ["in", allowed]

	if outlet:
		outlet_doc = frappe.get_doc("Outlet", outlet)
		_company_filter(outlet_doc.company)
		if not outlet_doc.customer:
			return []
		filters["customer"] = outlet_doc.customer

	return frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=[
			"name",
			"customer",
			"company",
			"posting_date",
			"due_date",
			"grand_total",
			"outstanding_amount",
			"currency",
		],
		order_by="due_date asc, posting_date asc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


# ---------------------------------------------------------------------------
# Visit steps
# ---------------------------------------------------------------------------

@frappe.whitelist()
def update_step(
	visit: str,
	step_idx: int,
	status: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	notes: str | None = None,
) -> dict:
	_require_write()
	if not visit:
		frappe.throw(_("Visit is required."))
	doc = frappe.get_doc("Visit", visit)
	_company_filter(doc.company)
	if not _is_admin() and doc.field_user != frappe.session.user:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	try:
		idx_i = int(step_idx)
	except (TypeError, ValueError):
		frappe.throw(_("step_idx must be an integer."))

	steps = list(doc.steps or [])
	matching = [s for s in steps if s.idx == idx_i]
	if not matching:
		frappe.throw(_("Step #{0} not found on this visit.").format(idx_i))
	step = matching[0]

	if status:
		if status not in ("Pending", "Done", "Skipped"):
			frappe.throw(_("Invalid step status: {0}").format(status))
		step.status = status
		now = frappe.utils.now_datetime()
		if status == "Done":
			step.completed_at = now
			if not step.started_at:
				step.started_at = now
		elif status == "Pending" and not step.started_at:
			step.started_at = now
	if reference_doctype is not None:
		step.reference_doctype = reference_doctype
	if reference_name is not None:
		step.reference_name = reference_name
	if notes is not None:
		step.notes = notes

	doc.save()
	return doc.as_dict()
