"""Tender / contract execution board (F8) — gated behind the `tender` module.

The board is a Sales-Order kanban: manager-defined stages (Stabler SO Stage),
each SO parked on a stage via `custom_board_stage`. Default stages are seeded
LAZILY (not via a pre-sync patch — patches.txt has no [post_model_sync] marker,
so a seed patch would run before the doctype table exists and silently skip).

All endpoints are gated by `_can_access_module(user, "tender")`, so other
tenants (enable_tender = 0) never reach them.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from stabler.api._common import _require_company
from stabler.api.organization import _can_access_module

_STAGE = "Stabler SO Stage"

# (stage_name, position, color, is_won, is_closed)
_DEFAULT_STAGES = [
	("New", 1, "#6c757d", 0, 0),
	("Procurement", 2, "#f59f00", 0, 0),
	("Delivery", 3, "#4263eb", 0, 0),
	("Acceptance", 4, "#ae3ec9", 0, 0),
	("Invoicing", 5, "#1098ad", 0, 0),
	("Paid", 6, "#2f9e44", 1, 0),
	("Closed", 7, "#adb5bd", 0, 1),
]


def _require_tender(company: str | None = None) -> None:
	"""Gate by role (module map) AND, when a company is given, by that company's
	enable_tender flag — so other tenants can't reach the board even by API."""
	if not _can_access_module(frappe.session.user, "tender"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if company:
		from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

		if not module_map_for(company).get("tender"):
			frappe.throw(_("Tender module is not enabled for {0}.").format(company), frappe.PermissionError)


def _ensure_default_stages() -> None:
	"""Seed the default stages once, if the board has none yet (idempotent)."""
	if frappe.db.count(_STAGE):
		return
	for name, pos, color, is_won, is_closed in _DEFAULT_STAGES:
		if frappe.db.exists(_STAGE, name):
			continue
		frappe.get_doc(
			{
				"doctype": _STAGE,
				"stage_name": name,
				"position": pos,
				"color": color,
				"is_won": is_won,
				"is_closed": is_closed,
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()


def _stages() -> list[dict]:
	return frappe.get_all(
		_STAGE,
		fields=["name", "stage_name", "position", "color", "is_won", "is_closed"],
		order_by="position asc, stage_name asc",
		limit_page_length=0,
	)


@frappe.whitelist()
def so_board(company: str) -> dict:
	"""Stages + the submitted Sales Orders parked on each (kanban feed)."""
	_require_tender(company)
	_require_company(company)
	_ensure_default_stages()

	stages = _stages()
	first_open = next((s["name"] for s in stages if not s["is_closed"]), stages[0]["name"] if stages else None)

	sos = frappe.get_all(
		"Sales Order",
		filters={"company": company, "docstatus": 1},
		fields=[
			"name", "customer", "customer_name", "transaction_date", "delivery_date",
			"currency", "rounded_total", "grand_total", "per_delivered", "per_billed",
			"status", "custom_board_stage", "custom_crm_deal",
		],
		order_by="transaction_date desc",
		limit_page_length=2000,
	)
	cards = []
	for so in sos:
		if so.status in ("Closed", "Cancelled"):
			continue
		stage = so.custom_board_stage or first_open  # lazy placement (virtual until moved)
		cards.append(
			{
				"name": so.name,
				"customer_name": so.customer_name or so.customer,
				"transaction_date": str(so.transaction_date or ""),
				"delivery_date": str(so.delivery_date or ""),
				"currency": so.currency,
				"contract_value": flt(so.rounded_total or so.grand_total),
				"per_delivered": flt(so.per_delivered),
				"per_billed": flt(so.per_billed),
				"status": so.status,
				"stage": stage,
				"deal": so.custom_crm_deal,
			}
		)
	return {"stages": stages, "cards": cards}


@frappe.whitelist()
def move_so_stage(name: str, stage: str) -> dict:
	"""Park a Sales Order on a stage (drag-drop)."""
	company = frappe.db.get_value("Sales Order", name, "company")
	if not company:
		frappe.throw(_("Unknown Sales Order: {0}").format(name))
	_require_tender(company)  # role + company-level tender flag
	if not frappe.db.exists(_STAGE, stage):
		frappe.throw(_("Unknown stage: {0}").format(stage))
	if not frappe.has_permission("Sales Order", "write", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.db.set_value("Sales Order", name, "custom_board_stage", stage)
	frappe.db.commit()
	return {"name": name, "stage": stage}


@frappe.whitelist()
def so_stage_save(company: str, stage_name: str, position: int = 0, color: str = "", is_won: int = 0, is_closed: int = 0, old_name: str = "") -> dict:
	"""Create or rename/update a board stage (manager-defined)."""
	_require_tender(company)
	_require_company(company)
	stage_name = (stage_name or "").strip()
	if not stage_name:
		frappe.throw(_("Stage name is required."))
	if old_name and old_name != stage_name and frappe.db.exists(_STAGE, old_name):
		frappe.rename_doc(_STAGE, old_name, stage_name, force=False)
	doc = frappe.get_doc(_STAGE, stage_name) if frappe.db.exists(_STAGE, stage_name) else frappe.new_doc(_STAGE)
	doc.stage_name = stage_name
	doc.position = int(position or 0)
	doc.color = color or doc.color
	doc.is_won = int(is_won or 0)
	doc.is_closed = int(is_closed or 0)
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"name": doc.name}


@frappe.whitelist()
def so_stage_delete(company: str, stage_name: str) -> dict:
	"""Delete a stage. The doctype's on_trash guard blocks if SOs still sit in it."""
	_require_tender(company)
	_require_company(company)
	frappe.delete_doc(_STAGE, stage_name)  # raises if Sales Orders are parked here
	frappe.db.commit()
	return {"deleted": stage_name}


@frappe.whitelist()
def so_stage_reorder(company: str, names: str | list) -> dict:
	"""Persist column order from a list of stage names (left → right)."""
	_require_tender(company)
	_require_company(company)
	names = frappe.parse_json(names) if isinstance(names, str) else names
	for idx, name in enumerate(names or [], start=1):
		if frappe.db.exists(_STAGE, name):
			frappe.db.set_value(_STAGE, name, "position", idx, update_modified=False)
	frappe.db.commit()
	return {"ordered": len(names or [])}
