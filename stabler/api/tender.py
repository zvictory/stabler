"""Tender / contract execution board (F8) — gated behind the `tender` module.

The board is a Sales-Order kanban: manager-defined stages (Stabler SO Stage),
each SO parked on a stage via `custom_board_stage`. Default stages are seeded
LAZILY (not via a pre-sync patch — patches.txt has no [post_model_sync] marker,
so a seed patch would run before the doctype table exists and silently skip).

All endpoints are gated by `_can_access_module(user, "tender")`, so other
tenants (enable_tender = 0) never reach them.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate, now, today

from stabler.api._bid_package import assemble_bid_package, build_bid_docx
from stabler.api._common import _require_company
from stabler.api.approvals import _assert_company_scope
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
		_require_tender_enabled(company)


def _require_tender_enabled(company: str) -> None:
	"""Company module gate shared by interactive and trusted-server writers."""
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
def so_board(company: str, tender_only: int = 0) -> dict:
	"""Stages + the submitted Sales Orders parked on each (kanban feed)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_tender(company)
	_require_company(company)
	_ensure_default_stages()

	stages = _stages()
	first_open = next(
		(s["name"] for s in stages if not s["is_closed"]), stages[0]["name"] if stages else None
	)

	so_filters = (
		{"company": company, "docstatus": ["<", 2]}
		if int(tender_only or 0)
		else {"company": company, "docstatus": 1}
	)
	sos = frappe.get_list(
		"Sales Order",
		filters=so_filters,
		fields=[
			"name",
			"customer",
			"customer_name",
			"transaction_date",
			"delivery_date",
			"currency",
			"rounded_total",
			"grand_total",
			"per_delivered",
			"per_billed",
			"status",
			"custom_board_stage",
			"custom_crm_deal",
		],
		order_by="transaction_date desc",
		limit_page_length=2000,
	)
	cards = []
	for so in sos:
		if not frappe.has_permission("Sales Order", "read", doc=so.name):
			continue
		if so.status in ("Closed", "Cancelled"):
			continue
		if int(tender_only or 0) and not so.custom_crm_deal:
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
def so_stage_save(
	company: str,
	stage_name: str,
	position: int = 0,
	color: str = "",
	is_won: int = 0,
	is_closed: int = 0,
	old_name: str = "",
) -> dict:
	"""Create or rename/update a board stage (manager-defined)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_tender(company)
	_require_company(company)
	stage_name = (stage_name or "").strip()
	if not stage_name:
		frappe.throw(_("Stage name is required."))
	if old_name and old_name != stage_name and frappe.db.exists(_STAGE, old_name):
		frappe.rename_doc(_STAGE, old_name, stage_name, force=False)
	doc = (
		frappe.get_doc(_STAGE, stage_name) if frappe.db.exists(_STAGE, stage_name) else frappe.new_doc(_STAGE)
	)
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
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_tender(company)
	_require_company(company)
	frappe.delete_doc(_STAGE, stage_name)  # raises if Sales Orders are parked here
	frappe.db.commit()
	return {"deleted": stage_name}


@frappe.whitelist()
def so_stage_reorder(company: str, names: str | list) -> dict:
	"""Persist column order from a list of stage names (left → right)."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_tender(company)
	_require_company(company)
	names = frappe.parse_json(names) if isinstance(names, str) else names
	for idx, name in enumerate(names or [], start=1):
		if frappe.db.exists(_STAGE, name):
			frappe.db.set_value(_STAGE, name, "position", idx, update_modified=False)
	frappe.db.commit()
	return {"ordered": len(names or [])}


# --------------------------------------------------------------------------- #
# PO control board — every Purchase Order raised for one tender (F9)
# --------------------------------------------------------------------------- #
def _po_lane(docstatus: int, per_received: float) -> str:
	"""Derive the board lane from the PO's own workflow state (read-only)."""
	if docstatus == 0:
		return "draft"
	if per_received >= 100:
		return "completed"
	if per_received > 0:
		return "partial"
	return "to_receive"


# Planned landed-cost charge types (for grouping/iconography in the SPA). The
# `label` is free text so the plan can hold literally any cost item; `type` only
# drives the icon/colour. Stored per-PO as a JSON array in `custom_landed_charges`.
_CHARGE_TYPES = (
	"transport",
	"customs",
	"certification",
	"insurance",
	"storage",
	"declarant",
	"legal",
	"broker",
	"loading",
	"bank",
	"other",
)


def _parse_landed(raw) -> list[dict]:
	"""Parse the JSON stored in Purchase Order.custom_landed_charges into a clean
	list of dicts (amount in company/base currency). Each line may carry a ТН ВЭД
	(HS) code and an attributed provider (declarant / lawyer / logistician …) as a
	Supplier link + denormalized name for display."""
	if not raw:
		return []
	try:
		data = raw if isinstance(raw, list) else json.loads(raw)
	except (ValueError, TypeError):
		return []
	out: list[dict] = []
	for it in data if isinstance(data, list) else []:
		if not isinstance(it, dict):
			continue
		ctype = str(it.get("type") or "other")
		if ctype not in _CHARGE_TYPES:
			ctype = "other"
		out.append(
			{
				"type": ctype,
				"label": str(it.get("label") or "").strip()[:140],
				"amount": flt(it.get("amount")),  # planned
				"actual": flt(it.get("actual")),  # actual (recorded from real invoices)
				"tnved": str(it.get("tnved") or "").strip()[:40],
				"supplier": str(it.get("supplier") or "").strip()[:140],
				"supplier_name": str(it.get("supplier_name") or "").strip()[:140],
				# Customs calculator inputs (ГТД): customs value (CIF) + duty% + excise% + VAT%.
				"cif": flt(it.get("cif")),
				"duty_pct": flt(it.get("duty_pct")),
				"excise_pct": flt(it.get("excise_pct")),
				"vat_pct": flt(it.get("vat_pct")),
				# WP-T1: for a VAT-registered company (Mikas) import VAT is RECOVERABLE
				# input tax — it must NOT be capitalized into landed cost (IAS 2 §11;
				# same stance as the imports LCV engine). Default True so new customs
				# lines exclude VAT from `amount`; set False only for a non-registered
				# scenario where VAT becomes a real cost. Legacy lines with no flag keep
				# their stored amount until re-saved.
				"vat_recoverable": bool(it.get("vat_recoverable", True)),
				# WP-T5: the `actual` may be sourced from a real GL voucher (PInv/PE/JE)
				# instead of hand-typed. When linked, the amount is pulled read-only from
				# the document's base total so plan-vs-actual reflects the ledger.
				"actual_voucher_type": str(it.get("actual_voucher_type") or "").strip()[:40],
				"actual_voucher": str(it.get("actual_voucher") or "").strip()[:140],
			}
		)
	return out


_ACTUAL_VOUCHER_TYPES = ("Purchase Invoice", "Payment Entry", "Journal Entry")


@frappe.whitelist()
def landed_actual_from_voucher(voucher_type: str, voucher: str, company: str) -> dict:
	"""Pull a landed-charge actual from a real GL document (WP-T5).

	Replaces hand-typed actuals with the ledger truth: the base-currency total of
	a Purchase Invoice / Payment Entry / Journal Entry the user links to a landed
	line. Read-only, tender-gated + company-scoped, and the underlying Frappe read
	permission still applies (the real boundary). Returns {found, amount, label,
	docstatus, currency} — found=False leaves the caller on manual entry."""
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)
	vt = (voucher_type or "").strip()
	vn = (voucher or "").strip()
	if vt not in _ACTUAL_VOUCHER_TYPES or not vn or not frappe.db.exists(vt, vn):
		return {"found": False, "amount": 0.0, "label": "", "docstatus": None}
	if frappe.db.get_value(vt, vn, "company") != company:
		frappe.throw(_("Document belongs to another company."), frappe.PermissionError)
	if not frappe.has_permission(vt, "read", doc=vn):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	# Base-currency amount + a human label per doctype.
	if vt == "Purchase Invoice":
		amount = flt(frappe.db.get_value(vt, vn, "base_grand_total"))
		label = frappe.db.get_value(vt, vn, "supplier_name") or vn
	elif vt == "Payment Entry":
		amount = flt(frappe.db.get_value(vt, vn, "base_paid_amount"))
		label = frappe.db.get_value(vt, vn, "party_name") or frappe.db.get_value(vt, vn, "party") or vn
	else:  # Journal Entry
		amount = flt(frappe.db.get_value(vt, vn, "total_debit"))
		label = frappe.db.get_value(vt, vn, "user_remark") or vn
	return {
		"found": True,
		"voucher_type": vt,
		"voucher": vn,
		"amount": round(amount, 2),
		"label": str(label)[:140],
		"docstatus": frappe.db.get_value(vt, vn, "docstatus"),
	}


def _po_scope(po: str, write: bool = False):
	"""Resolve + authorize a Purchase Order for landed-charge access.
	Returns the resolved company. Enforces tender module + company scope + the
	underlying Frappe permission (the real security boundary)."""
	if not po or not frappe.db.exists("Purchase Order", po):
		frappe.throw(_("Unknown purchase order: {0}").format(po), frappe.DoesNotExistError)
	company = frappe.db.get_value("Purchase Order", po, "company")
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)
	if not frappe.has_permission("Purchase Order", "write" if write else "read", doc=po):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return company


@frappe.whitelist()
def hs_rate_lookup(hs_code: str, company: str) -> dict:
	"""Look up the customs duty/excise/VAT rates for a ТН ВЭД (HS) code so the
	PO landed-charge editor can auto-fill them from the real rate engine (WP-T2)
	instead of the user typing percentages by hand. Same HS Duty Rate table the
	imports customs estimate uses; the latest effective_from row wins.

	Returns {found, hs_code, duty_pct, excise_pct, vat_pct, effective_from} —
	found=False (rest zero) when the code is not in the table, so the caller
	falls back to manual entry. Read-only; gated on the tender module + company
	scope like every other board endpoint."""
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)
	code = (hs_code or "").strip()
	if not code or not frappe.db.exists("DocType", "HS Duty Rate"):
		return {"found": False, "hs_code": code, "duty_pct": 0.0, "excise_pct": 0.0, "vat_pct": 0.0}
	rows = frappe.get_all(
		"HS Duty Rate",
		filters={"hs_code": code, "effective_from": ["<=", today()]},
		fields=["duty_pct", "excise_pct", "vat_pct", "effective_from"],
		order_by="effective_from desc",
		limit_page_length=1,
	)
	if not rows:
		return {"found": False, "hs_code": code, "duty_pct": 0.0, "excise_pct": 0.0, "vat_pct": 0.0}
	r = rows[0]
	return {
		"found": True,
		"hs_code": code,
		"duty_pct": flt(r.duty_pct),
		"excise_pct": flt(r.excise_pct),
		"vat_pct": flt(r.vat_pct) or 12.0,
		"effective_from": str(r.effective_from) if r.effective_from else None,
	}


@frappe.whitelist()
def po_landed_charges(po: str) -> dict:
	"""Read the planned landed-cost lines for one Purchase Order, with the base
	amount and the resulting landed total (all in company currency)."""
	company = _po_scope(po, write=False)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	charges = []
	if frappe.db.has_column("Purchase Order", "custom_landed_charges"):
		charges = _parse_landed(frappe.db.get_value("Purchase Order", po, "custom_landed_charges"))
	base_total = flt(frappe.db.get_value("Purchase Order", po, "base_grand_total"))
	charges_total = sum(c["amount"] for c in charges)
	actual_total = sum(c["actual"] for c in charges)
	# WP-T1: recoverable import VAT sitting OUTSIDE landed cost — informational,
	# so the declarant sees the input-tax asset that is deliberately not
	# capitalized. duty/VAT only meaningful on customs lines with a CIF value.
	recoverable_vat = 0.0
	for c in charges:
		if c["type"] == "customs" and c.get("vat_recoverable") and flt(c.get("cif")):
			duty = flt(c["cif"]) * flt(c["duty_pct"]) / 100.0
			excise = flt(c["cif"]) * flt(c.get("excise_pct")) / 100.0
			recoverable_vat += (flt(c["cif"]) + duty + excise) * flt(c["vat_pct"]) / 100.0
	return {
		"po": po,
		"currency": base_ccy,
		"charges": charges,
		"base_total": base_total,
		"charges_total": charges_total,
		"actual_total": actual_total,
		"recoverable_vat": round(recoverable_vat, 2),
		"landed_total": base_total + charges_total,
		"actual_landed": base_total + actual_total,
	}


@frappe.whitelist()
def save_po_landed_charges(po: str, charges) -> dict:
	"""Replace the planned landed-cost lines for one Purchase Order.

	`charges` is a JSON array of {type, label, amount}. Persisted via db_set so
	the plan can also be maintained on an already-submitted PO (the field is a
	read-only, allow_on_submit overlay — it never touches the accounting doc).
	"""
	_po_scope(po, write=True)
	if not frappe.db.has_column("Purchase Order", "custom_landed_charges"):
		frappe.throw(_("Run migrate to enable landed-cost planning."))
	cleaned = _parse_landed(charges)
	frappe.db.set_value(
		"Purchase Order",
		po,
		"custom_landed_charges",
		json.dumps(cleaned, ensure_ascii=False),
		update_modified=False,
	)
	base_total = flt(frappe.db.get_value("Purchase Order", po, "base_grand_total"))
	charges_total = sum(c["amount"] for c in cleaned)
	return {
		"po": po,
		"charges": cleaned,
		"base_total": base_total,
		"charges_total": charges_total,
		"landed_total": base_total + charges_total,
	}


@frappe.whitelist()
def po_control_board(deal: str) -> dict:
	"""Tender PO control board: every Purchase Order raised to vendors for one
	tender (linked via Purchase Order.custom_crm_deal), grouped into status lanes
	with KPIs and a per-vendor comparison against the supplier quotations
	collected for the same tender. Read-only.
	"""
	if not deal or not frappe.db.exists("CRM Deal", deal):
		frappe.throw(_("Unknown deal: {0}").format(deal), frappe.DoesNotExistError)
	company = frappe.db.get_value("CRM Deal", deal, "company") or frappe.defaults.get_user_default("Company")
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)

	lanes_def = [
		("draft", _("Draft")),
		("to_receive", _("To receive")),
		("partial", _("Partially received")),
		("completed", _("Completed")),
	]
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""

	# The custom field is added by patch v34 — until migrate runs, return an empty
	# (but well-shaped) board instead of erroring.
	if not frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		return {
			"deal": deal,
			"currency": base_ccy,
			"lanes": [{"key": k, "label": l, "count": 0, "total": 0.0} for k, l in lanes_def],
			"cards": [],
			"compare": [],
			"kpi": {"po_count": 0, "total": 0.0, "received_pct": 0, "vendors": 0},
		}

	po_fields = [
		"name",
		"supplier",
		"supplier_name",
		"grand_total",
		"base_grand_total",
		"per_received",
		"per_billed",
		"status",
		"currency",
		"docstatus",
		"schedule_date",
		"transaction_date",
	]
	has_landed = frappe.db.has_column("Purchase Order", "custom_landed_charges")
	if has_landed:
		po_fields.append("custom_landed_charges")

	rows = frappe.get_list(
		"Purchase Order",
		filters={"custom_crm_deal": deal, "company": company, "docstatus": ["<", 2]},
		fields=po_fields,
		order_by="transaction_date desc, name desc",
		limit_page_length=1000,
	)
	rows = [row for row in rows if frappe.has_permission("Purchase Order", "read", doc=row.name)]

	today_d = getdate(today())
	# Landed cost (base currency) = base_grand_total + planned charges. The
	# vendor comparison ranks on landed, so "cheapest" means cheapest delivered.
	landed_by_po = {
		r.name: flt(r.base_grand_total)
		+ sum(c["amount"] for c in _parse_landed(r.get("custom_landed_charges") if has_landed else None))
		for r in rows
	}
	min_landed = min((landed_by_po[r.name] for r in rows), default=0.0)
	cards: list[dict] = []
	total = 0.0
	recv_weighted = 0.0
	suppliers: dict[str, dict] = {}

	for r in rows:
		gt = flt(r.grand_total)
		base_gt = flt(r.base_grand_total)
		charges_total = flt(landed_by_po[r.name] - base_gt)
		landed = flt(landed_by_po[r.name])
		pr = flt(r.per_received)
		pb = flt(r.per_billed)
		delayed = bool(
			r.docstatus == 1 and pr < 100 and r.schedule_date and getdate(r.schedule_date) < today_d
		)
		badges: list[str] = []
		if landed and landed == min_landed:
			badges.append("cheapest")
		if r.docstatus == 0:
			badges.append("draft")
		if delayed:
			badges.append("delayed")
		if pr >= 100:
			badges.append("received")
		elif pr > 0:
			badges.append("partial:%d" % round(pr))
		if pb >= 100:
			badges.append("billed")
		cards.append(
			{
				"name": r.name,
				"lane": _po_lane(r.docstatus, pr),
				"supplier": r.supplier,
				"supplier_name": r.supplier_name,
				"amount": gt,
				"currency": r.currency or base_ccy,
				"base_amount": base_gt,
				"charges_total": charges_total,
				"landed": landed,
				"schedule_date": str(r.schedule_date) if r.schedule_date else None,
				"per_received": pr,
				"per_billed": pb,
				"status": r.status,
				"badges": badges,
			}
		)
		total += gt
		recv_weighted += gt * pr
		s = suppliers.setdefault(
			r.supplier,
			{
				"supplier": r.supplier,
				"supplier_name": r.supplier_name,
				"po_total": 0.0,
				"base_po_total": 0.0,
				"charges_total": 0.0,
				"count": 0,
				"min_sched": None,
			},
		)
		s["po_total"] += gt
		s["base_po_total"] += base_gt
		s["charges_total"] += charges_total
		s["count"] += 1
		if r.schedule_date and (s["min_sched"] is None or str(r.schedule_date) < s["min_sched"]):
			s["min_sched"] = str(r.schedule_date)

	# Supplier quotation totals for this tender → PO-vs-quotation delta per vendor.
	q_by_supplier: dict[str, float] = {}
	if frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		for q in frappe.get_all(
			"Supplier Quotation",
			filters={"custom_crm_deal": deal, "docstatus": ["<", 2]},
			fields=["supplier", "grand_total"],
			limit_page_length=1000,
		):
			q_by_supplier[q.supplier] = q_by_supplier.get(q.supplier, 0.0) + flt(q.grand_total)

	compare = []
	for s in suppliers.values():
		qt = q_by_supplier.get(s["supplier"], 0.0)
		delta = ((s["po_total"] - qt) / qt * 100) if qt else None
		landed_total = flt(s["base_po_total"] + s["charges_total"])
		compare.append(
			{
				"supplier": s["supplier"],
				"supplier_name": s["supplier_name"],
				"po_total": s["po_total"],
				"base_po_total": s["base_po_total"],
				"charges_total": s["charges_total"],
				"landed_total": landed_total,
				"quotation_total": qt,
				"delta_pct": round(delta, 1) if delta is not None else None,
				"schedule_date": s["min_sched"],
				"count": s["count"],
			}
		)
	# Cheapest = lowest landed (delivered) cost; rank cheapest-first and flag it,
	# plus each vendor's landed premium over the cheapest.
	cheapest_landed = min((c["landed_total"] for c in compare if c["landed_total"]), default=0.0)
	for c in compare:
		c["cheapest"] = bool(c["landed_total"] and c["landed_total"] == cheapest_landed)
		c["landed_delta_pct"] = (
			round((c["landed_total"] - cheapest_landed) / cheapest_landed * 100, 1)
			if cheapest_landed
			else None
		)
	compare.sort(key=lambda x: x["landed_total"])

	lanes = []
	for key, label in lanes_def:
		lc = [c for c in cards if c["lane"] == key]
		lanes.append({"key": key, "label": label, "count": len(lc), "total": sum(c["amount"] for c in lc)})

	return {
		"deal": deal,
		"currency": (rows[0].currency if rows else base_ccy) or base_ccy,
		"lanes": lanes,
		"cards": cards,
		"compare": compare,
		"kpi": {
			"po_count": len(cards),
			"total": total,
			"received_pct": round(recv_weighted / total, 1) if total else 0,
			"vendors": len(suppliers),
		},
	}


# --------------------------------------------------------------------------- #
# Tender execution workspace — the tender's purchase and sales document chains.
# --------------------------------------------------------------------------- #
def _deal_link_field(doctype: str) -> str | None:
	"""Return the installed tender link field without reading unscoped documents."""
	for field in ("custom_crm_deal", "custom_tender_deal"):
		if frappe.db.has_column(doctype, field):
			return field
	return None


def _document_row(row, date_field: str, link_field: str, linked_name: str) -> dict:
	"""Normalize ERPNext document rows for the SPA's chain component."""
	return {
		"name": row.get("name"),
		"docstatus": row.get("docstatus"),
		"posting_date": str(row.get(date_field) or ""),
		"status": row.get("status") or "",
		"grand_total": flt(row.get("grand_total")),
		"outstanding_amount": flt(row.get("outstanding_amount")),
		"base_grand_total": flt(row.get("base_grand_total")),
		"base_outstanding_amount": flt(row.get("base_outstanding_amount")),
		"currency": row.get("currency") or "",
		link_field: linked_name,
	}


def _linked_document_rows(
	parent_doctype: str,
	item_doctype: str,
	order_names: list[str],
	company: str,
	link_field: str,
	date_field: str,
	include_outstanding: bool = False,
) -> list[dict]:
	"""Return permitted parent rows linked through one document-item query.

	The parent query establishes company and document-state scope.  The item query
	then supplies the PO/SO links in one batch, avoiding a query per order.
	"""
	if not order_names:
		return []
	fields = ["name", date_field, "docstatus", "status", "grand_total", "base_grand_total", "currency"]
	if include_outstanding:
		fields.extend(["outstanding_amount", "base_outstanding_amount"])
	parents = frappe.get_list(
		parent_doctype,
		filters={"company": company, "docstatus": ["<", 2]},
		fields=fields,
		order_by=f"{date_field} asc, name asc",
		limit_page_length=1000,
	)
	parents = [row for row in parents if frappe.has_permission(parent_doctype, "read", doc=row.name)]
	parent_names = [row.name for row in parents]
	if not parent_names:
		return []
	links = frappe.get_list(
		item_doctype,
		filters={"parent": ["in", parent_names], link_field: ["in", order_names]},
		fields=["parent", link_field],
		limit_page_length=10000,
		# Child rows are link evidence only. Parent documents were already
		# company-scoped and permission-checked above; applying the child
		# DocType permission query here can reject valid dashboard reads.
		ignore_permissions=True,
	)
	linked_by_parent: dict[str, list[str]] = {}
	for link in links:
		linked_name = link.get(link_field)
		if linked_name:
			linked_by_parent.setdefault(link.parent, []).append(linked_name)
	rows: list[dict] = []
	for parent in parents:
		for linked_name in dict.fromkeys(linked_by_parent.get(parent.name, [])):
			rows.append(_document_row(parent, date_field, link_field, linked_name))
	return rows


def _purchase_document_chain(deal: str, company: str) -> dict:
	"""Return company-scoped PO, Purchase Receipt, and Purchase Invoice rows."""
	deal_field = _deal_link_field("Purchase Order")
	if not deal_field:
		return {"orders": [], "receipts": [], "invoices": []}
	orders = frappe.get_list(
		"Purchase Order",
		filters={deal_field: deal, "company": company, "docstatus": ["<", 2]},
		fields=["name", "transaction_date", "status", "grand_total", "base_grand_total", "currency"],
		order_by="transaction_date asc, name asc",
		limit_page_length=1000,
	)
	orders = [row for row in orders if frappe.has_permission("Purchase Order", "read", doc=row.name)]
	order_rows = [_document_row(row, "transaction_date", "purchase_order", row.name) for row in orders]
	order_names = [row.name for row in orders]
	return {
		"orders": order_rows,
		"receipts": _linked_document_rows(
			"Purchase Receipt",
			"Purchase Receipt Item",
			order_names,
			company,
			"purchase_order",
			"posting_date",
		),
		"invoices": _linked_document_rows(
			"Purchase Invoice",
			"Purchase Invoice Item",
			order_names,
			company,
			"purchase_order",
			"posting_date",
			include_outstanding=True,
		),
	}


def _sales_document_chain(deal: str, company: str) -> dict:
	"""Return company-scoped SO, Delivery Note, and Sales Invoice rows."""
	deal_field = _deal_link_field("Sales Order")
	if not deal_field:
		return {"orders": [], "deliveries": [], "invoices": []}
	orders = frappe.get_list(
		"Sales Order",
		filters={deal_field: deal, "company": company, "docstatus": ["<", 2]},
		fields=["name", "transaction_date", "status", "grand_total", "base_grand_total", "currency"],
		order_by="transaction_date asc, name asc",
		limit_page_length=1000,
	)
	orders = [row for row in orders if frappe.has_permission("Sales Order", "read", doc=row.name)]
	order_rows = [_document_row(row, "transaction_date", "sales_order", row.name) for row in orders]
	order_names = [row.name for row in orders]
	return {
		"orders": order_rows,
		"deliveries": _linked_document_rows(
			"Delivery Note",
			"Delivery Note Item",
			order_names,
			company,
			"sales_order",
			"posting_date",
		),
		"invoices": _linked_document_rows(
			"Sales Invoice",
			"Sales Invoice Item",
			order_names,
			company,
			"sales_order",
			"posting_date",
			include_outstanding=True,
		),
	}


def _unique_invoice_rows(rows: list[dict]) -> list[dict]:
	"""Keep one invoice total when its item links span multiple deal orders."""
	seen: set[str] = set()
	unique: list[dict] = []
	for row in rows:
		name = str(row.get("name") or "")
		if name and name in seen:
			continue
		if name:
			seen.add(name)
		unique.append(row)
	return unique


def _invoice_status_counts(
	order_names: list[str],
	*,
	parent_doctype: str,
	item_doctype: str,
	order_link_field: str,
	company: str,
	start,
	end,
) -> dict[str, int]:
	"""Count selected-period invoices linked to readable tender orders.

	The buckets are intentionally exclusive: a submitted invoice that still has
	an outstanding balance is counted as ``unpaid`` rather than twice.
	"""
	counts = {"draft": 0, "submitted": 0, "unpaid": 0}
	rows = _unique_invoice_rows(
		_linked_document_rows(
			parent_doctype,
			item_doctype,
			order_names,
			company,
			order_link_field,
			"posting_date",
			include_outstanding=True,
		)
	)
	for invoice in rows:
		if not _in_dashboard_period(invoice.get("posting_date"), start, end):
			continue
		if invoice.get("docstatus") == 0:
			counts["draft"] += 1
		elif invoice.get("status") in ("Unpaid", "Partly Paid", "Overdue"):
			counts["unpaid"] += 1
		else:
			counts["submitted"] += 1
	return counts


def _linked_document_count(
	order_names: list[str],
	*,
	parent_doctype: str,
	item_doctype: str,
	order_link_field: str,
	company: str,
	start,
	end,
) -> int:
	"""Count unique readable tender documents posted in the dashboard period."""
	rows = _unique_invoice_rows(
		_linked_document_rows(
			parent_doctype,
			item_doctype,
			order_names,
			company,
			order_link_field,
			"posting_date",
		)
	)
	return sum(
		1 for row in rows if _in_dashboard_period(row.get("posting_date"), start, end)
	)


def _tender_finance_chain(
	purchase: dict,
	sales: dict,
	*,
	currency: str,
	planned_margin: float = 0.0,
) -> dict:
	"""Derive base-currency AP, AR, paid, outstanding, and tender margins."""
	purchase_invoices = _unique_invoice_rows(purchase["invoices"])
	sales_invoices = _unique_invoice_rows(sales["invoices"])
	ap_total = sum(flt(row.get("base_grand_total")) for row in purchase_invoices)
	ap_outstanding = sum(flt(row.get("base_outstanding_amount")) for row in purchase_invoices)
	ar_total = sum(flt(row.get("base_grand_total")) for row in sales_invoices)
	ar_outstanding = sum(flt(row.get("base_outstanding_amount")) for row in sales_invoices)
	return {
		"currency": currency,
		"ap_total": ap_total,
		"ap_outstanding": ap_outstanding,
		"ap_paid": ap_total - ap_outstanding,
		"ar_total": ar_total,
		"ar_outstanding": ar_outstanding,
		"ar_paid": ar_total - ar_outstanding,
		"actual_margin": ar_total - ap_total,
		"planned_margin": flt(planned_margin),
	}


@frappe.whitelist()
def tender_workspace(deal: str) -> dict:
	"""Return the permission-scoped data backing the four-tab tender workspace."""
	from stabler.api.purchasing import tender_quotations

	company = _deal_scope(deal, write=False)
	out = {
		"deal": deal,
		"company": company,
		"overview": deal_intake(deal),
		"sourcing": tender_quotations(deal),
		"purchase_execution": _purchase_document_chain(deal, company),
		"sales_execution": _sales_document_chain(deal, company),
	}
	if _can_view_tender_finance():
		bid_inputs, _ = _bid_inputs(deal, company)
		planned_margin = _compute_bid_pnl(bid_inputs).get("profit")
		out["finance"] = _tender_finance_chain(
			out["purchase_execution"],
			out["sales_execution"],
			currency=out["overview"].get("currency") or "",
			planned_margin=planned_margin,
		)
	return out


# --------------------------------------------------------------------------- #
# Tender bid pricing — landed cost + our margin → the price WE bid (Договор).
# The sell side is a Sales Order (revenue); the cost side is the deal's POs
# (landed). This mirrors the customer's contract P&L sheet.
# --------------------------------------------------------------------------- #
_BID_DEFAULTS = {
	"mode": "margin",  # "margin" (target margin → bid) | "price" (bid → margin)
	"margin_pct": 20.0,  # Прибыль ÷ net revenue, %
	"vat_pct": 12.0,  # НДС
	"exchange_pct": 0.15,  # биржа комиссия (on gross bid)
	"profit_tax_pct": 15.0,  # налог на прибыль
	"dividend_tax_pct": 5.0,  # налог на дивиденды
}


def _deal_scope(deal: str, write: bool = False) -> str:
	if not deal or not frappe.db.exists("CRM Deal", deal):
		frappe.throw(_("Unknown deal: {0}").format(deal), frappe.DoesNotExistError)
	company = frappe.db.get_value("CRM Deal", deal, "company") or frappe.defaults.get_user_default("Company")
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)
	if not frappe.has_permission("CRM Deal", "write" if write else "read", doc=deal):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return company


def _deal_landed_split(deal: str, company: str) -> tuple[float, float, int]:
	"""(planned_landed, actual_landed, po_count) in base currency across the deal's
	POs. Planned = base + planned charges; actual = base + recorded actual charges."""
	if not frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		return 0.0, 0.0, 0
	has_landed = frappe.db.has_column("Purchase Order", "custom_landed_charges")
	po_fields = ["name", "base_grand_total"]
	if has_landed:
		po_fields.append("custom_landed_charges")
	pos = frappe.get_list(
		"Purchase Order",
		filters={"custom_crm_deal": deal, "company": company, "docstatus": ["<", 2]},
		fields=po_fields,
		limit_page_length=1000,
	)
	pos = [row for row in pos if frappe.has_permission("Purchase Order", "read", doc=row.name)]
	planned = 0.0
	actual = 0.0
	for p in pos:
		base = flt(p.base_grand_total)
		lines = _parse_landed(p.get("custom_landed_charges") if has_landed else None)
		planned += base + sum(c["amount"] for c in lines)
		actual += base + sum(c["actual"] for c in lines)
	return planned, actual, len(pos)


def _deal_landed(deal: str, company: str) -> tuple[float, int]:
	"""Sum planned landed cost (base currency) across the deal's Purchase Orders."""
	planned, _actual, count = _deal_landed_split(deal, company)
	return planned, count


def _deal_revenue_actual(deal: str, company: str) -> float:
	"""Actual invoiced revenue (base currency) = Σ SO.base_grand_total × per_billed%."""
	if not frappe.db.has_column("Sales Order", "custom_crm_deal"):
		return 0.0
	sos = frappe.get_all(
		"Sales Order",
		filters={"custom_crm_deal": deal, "company": company, "docstatus": 1},
		fields=["base_grand_total", "per_billed"],
		limit_page_length=1000,
	)
	return sum(flt(s.base_grand_total) * flt(s.per_billed) / 100.0 for s in sos)


def _deal_revenue(deal: str, company: str) -> tuple[float, int]:
	"""Sum revenue (base currency) across the deal's Sales Orders (the bid we won)."""
	if not frappe.db.has_column("Sales Order", "custom_crm_deal"):
		return 0.0, 0
	sos = frappe.get_all(
		"Sales Order",
		filters={"custom_crm_deal": deal, "company": company, "docstatus": ["<", 2]},
		fields=["name", "base_grand_total"],
		limit_page_length=1000,
	)
	return sum(flt(s.base_grand_total) for s in sos), len(sos)


def _deal_kassa_actual(deal: str, company: str) -> tuple[list[dict], float]:
	"""Real cash expenses booked against this tender (WP-K4).

	Sums SUBMITTED Journal Entries tagged ``custom_crm_deal = deal`` (the kassa
	bot / Expenses page write these), grouping the base-currency debit to each
	Expense account. Returns ([{label: account_name, amount}], total) sorted by
	amount desc. These are above-the-line, tax-deductible operating costs of
	winning/executing the tender (per the cost-sheet: subtracted before profit
	tax), so the caller folds them into ``above_other`` on the actual side.

	Guarded on the v52 field so mixed-version benches return ([], 0.0)."""
	if not frappe.db.has_column("Journal Entry", "custom_crm_deal"):
		return [], 0.0
	rows = frappe.db.sql(
		"""
		SELECT a.account_name AS label, SUM(jea.debit) AS amount
		FROM `tabJournal Entry` je
		JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		JOIN `tabAccount` a ON a.name = jea.account
		WHERE je.custom_crm_deal = %(deal)s
		  AND je.company = %(company)s
		  AND je.docstatus = 1
		  AND a.root_type = 'Expense'
		  AND jea.debit > 0
		GROUP BY a.account_name
		ORDER BY amount DESC
		""",
		{"deal": deal, "company": company},
		as_dict=True,
	)
	lines = [{"label": r.label or "", "amount": flt(r.amount)} for r in rows]
	return lines, sum(x["amount"] for x in lines)


def _num(v, d=0.0) -> float:
	try:
		return float(v)
	except (TypeError, ValueError):
		return d


def _compute_bid_pnl(p: dict) -> dict:
	"""Full contract P&L waterfall (mirrors the customer's cost sheet).

	Two directions:
	  mode="margin" → back-solve the gross bid price from a target margin.
	  mode="price"  → forward-compute the resulting margin from a given bid.
	Costs split into above-the-line (before Прибыль, taxable) and below-the-line
	(after dividends — reduce Остаток only, e.g. office, extra certification).
	"""
	landed_goods = _num(p.get("landed_goods"))
	above_other = [
		{"label": str(x.get("label") or ""), "amount": _num(x.get("amount"))}
		for x in (p.get("above_other") or [])
		if isinstance(x, dict)
	]
	below_other = [
		{"label": str(x.get("label") or ""), "amount": _num(x.get("amount"))}
		for x in (p.get("below_other") or [])
		if isinstance(x, dict)
	]
	vat_f = _num(p.get("vat_pct", _BID_DEFAULTS["vat_pct"])) / 100.0
	exch_f = _num(p.get("exchange_pct", _BID_DEFAULTS["exchange_pct"])) / 100.0
	ptax_f = _num(p.get("profit_tax_pct", _BID_DEFAULTS["profit_tax_pct"])) / 100.0
	dtax_f = _num(p.get("dividend_tax_pct", _BID_DEFAULTS["dividend_tax_pct"])) / 100.0

	above_excl = landed_goods + sum(x["amount"] for x in above_other)  # excludes exchange commission
	mode = p.get("mode") or "margin"

	if mode == "margin":
		m = _num(p.get("margin_pct", _BID_DEFAULTS["margin_pct"])) / 100.0
		denom = (1.0 - m) - (1.0 + vat_f) * exch_f
		net_rev = above_excl / denom if denom > 0 else 0.0
		gross = net_rev * (1.0 + vat_f)
	else:
		gross = _num(p.get("bid_price"))
		net_rev = gross / (1.0 + vat_f) if (1.0 + vat_f) else 0.0

	vat = gross - net_rev
	exchange = gross * exch_f
	above_total = above_excl + exchange
	profit = net_rev - above_total
	profit_tax = max(profit, 0.0) * ptax_f
	net_profit = profit - profit_tax
	dividend_tax = max(net_profit, 0.0) * dtax_f
	dividends = net_profit - dividend_tax
	below_total = sum(x["amount"] for x in below_other)
	ostatok = dividends - below_total

	return {
		"mode": mode,
		"bid_price": round(gross, 2),  # Договор (gross, VAT-inclusive)
		"vat": round(vat, 2),
		"net_revenue": round(net_rev, 2),  # Чистая выручка
		"exchange_fee": round(exchange, 2),
		"landed_goods": round(landed_goods, 2),
		"above_other": above_other,
		"above_total": round(above_total, 2),
		"profit": round(profit, 2),  # Прибыль
		"profit_tax": round(profit_tax, 2),
		"net_profit": round(net_profit, 2),  # Чистая прибыль
		"dividend_tax": round(dividend_tax, 2),
		"dividends": round(dividends, 2),  # Дивиденды
		"below_other": below_other,
		"below_total": round(below_total, 2),
		"ostatok": round(ostatok, 2),  # Остаток
		"margin_on_revenue_pct": round(profit / net_rev * 100, 2) if net_rev else 0.0,
		"markup_on_cost_pct": round(profit / above_total * 100, 2) if above_total else 0.0,
	}


def _bid_inputs(deal: str, company: str) -> tuple[dict, dict]:
	"""Merge stored pricing plan with defaults + live SO revenue / PO landed."""
	stored = {}
	if frappe.db.has_column("CRM Deal", "custom_bid_pricing"):
		raw = frappe.db.get_value("CRM Deal", deal, "custom_bid_pricing")
		if raw:
			try:
				stored = json.loads(raw) if not isinstance(raw, dict) else raw
			except (ValueError, TypeError):
				stored = {}
	po_landed, po_count = _deal_landed(deal, company)
	so_revenue, so_count = _deal_revenue(deal, company)
	inp = dict(_BID_DEFAULTS)
	inp.update({k: v for k, v in stored.items() if v is not None})
	# Defaults: landed basis from the deal's POs; bid (price mode) from its SOs.
	if inp.get("landed_goods") in (None, "", 0, 0.0):
		inp["landed_goods"] = po_landed
	if inp.get("mode") == "price" and inp.get("bid_price") in (None, "", 0, 0.0):
		inp["bid_price"] = so_revenue
	inp["above_other"] = stored.get("above_other") or []
	inp["below_other"] = stored.get("below_other") or []
	return inp, {"po_landed": po_landed, "po_count": po_count, "so_revenue": so_revenue, "so_count": so_count}


def _actual_block(deal: str, company: str, inp: dict, planned_pnl: dict) -> dict:
	"""Realized side: actual landed (recorded) + actual invoiced revenue → actual
	P&L, reusing the same tax rates and fixed other-costs as the plan."""
	planned_landed, actual_landed, _ = _deal_landed_split(deal, company)
	actual_revenue = _deal_revenue_actual(deal, company)
	kassa_lines, kassa_total = _deal_kassa_actual(deal, company)
	a_inp = dict(inp)
	a_inp["mode"] = "price"
	a_inp["bid_price"] = actual_revenue or planned_pnl.get("bid_price")
	a_inp["landed_goods"] = actual_landed or inp.get("landed_goods")
	# Real kassa spend is layered on top of the plan's structural above-line
	# costs (exchange etc.), each category a distinct line so the actual P&L
	# shows GL truth rather than a hand-typed estimate.
	a_inp["above_other"] = list(inp.get("above_other") or []) + kassa_lines
	a_pnl = _compute_bid_pnl(a_inp)
	return {
		"invoiced": bool(actual_revenue),
		"planned_landed": planned_landed,
		"actual_landed": actual_landed,
		"actual_revenue": actual_revenue,
		"kassa_actual": kassa_lines,
		"kassa_actual_total": round(kassa_total, 2),
		"pnl": a_pnl,
		"ostatok_delta": flt(a_pnl["ostatok"]) - flt(planned_pnl.get("ostatok")),
	}


@frappe.whitelist()
def deal_bid_pricing(deal: str) -> dict:
	"""Read the tender bid-pricing plan + computed P&L (plan and actual) for a deal."""
	company = _deal_scope(deal, write=False)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	inp, refs = _bid_inputs(deal, company)
	pnl = _compute_bid_pnl(inp)
	return {
		"deal": deal,
		"currency": base_ccy,
		"inputs": inp,
		"pnl": pnl,
		"actual": _actual_block(deal, company, inp, pnl),
		**refs,
	}


@frappe.whitelist()
def bid_package(deal: str) -> dict:
	"""Assemble the tender bid submission dataset and generate a .docx package.

	Read-only on the deal (gated by _deal_scope: company + tender module +
	CRM Deal read permission). When every required field is present it renders a
	bid letter + price table and attaches it to the deal as a private File; when
	something is missing it returns ``missing[]`` so the human sees the gap before
	anything is produced. No portal submission — the human signs (E-IMZO) and
	uploads. See docs/plans/uzex-eimzo-feasibility.md.
	"""
	company = _deal_scope(deal, write=False)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""

	intake = _read_intake(deal)
	inp, _refs = _bid_inputs(deal, company)
	pnl = _compute_bid_pnl(inp)

	uzex_fields: dict = {}
	if frappe.db.has_column("CRM Deal", "custom_uzex_lot_no"):
		uzex_fields = (
			frappe.db.get_value(
				"CRM Deal",
				deal,
				[
					"custom_uzex_lot_no",
					"custom_uzex_customer_org",
					"custom_uzex_deadline",
					"custom_uzex_start_price",
					"custom_uzex_portal",
				],
				as_dict=True,
			)
			or {}
		)

	comp = frappe.db.get_value("Company", company, ["company_name", "tax_id"], as_dict=True) or {}
	company_info = {"name": comp.get("company_name"), "tax_id": comp.get("tax_id"), "address": None}

	package = assemble_bid_package(deal, intake, pnl, uzex_fields, company_info, base_ccy)

	files: list[dict] = []
	warnings: list[str] = []
	if package["ready"]:
		import os
		import tempfile

		from frappe.utils.file_manager import save_file

		lot_no = (package["lot"]["lot_no"] or deal).replace("/", "-")
		tmp = tempfile.mktemp(suffix=".docx")
		try:
			build_bid_docx(package, tmp)
			with open(tmp, "rb") as fh:
				content = fh.read()
			f = save_file(f"bid_{lot_no}.docx", content, "CRM Deal", deal, is_private=1)
			files.append({"file_name": f.file_name, "file_url": f.file_url})
		except ImportError:
			# python-docx not installed on this bench — data still returned.
			warnings.append("python-docx is not installed on the server; document not generated.")
		finally:
			if os.path.exists(tmp):
				os.remove(tmp)

	return {
		"deal": deal,
		"package": package,
		"missing": package["missing"],
		"ready": package["ready"],
		"files": files,
		"warnings": warnings,
	}


@frappe.whitelist()
def save_deal_bid_pricing(deal: str, pricing) -> dict:
	"""Persist the bid-pricing plan (JSON) on the CRM Deal and return the P&L."""
	company = _deal_scope(deal, write=True)
	if not frappe.db.has_column("CRM Deal", "custom_bid_pricing"):
		frappe.throw(_("Run migrate to enable bid pricing."))
	try:
		data = pricing if isinstance(pricing, dict) else json.loads(pricing)
	except (ValueError, TypeError):
		frappe.throw(_("Invalid pricing payload."))
	# Keep only known keys; coerce cost lines.
	clean = {
		"mode": "price" if data.get("mode") == "price" else "margin",
		"margin_pct": _num(data.get("margin_pct"), _BID_DEFAULTS["margin_pct"]),
		"bid_price": _num(data.get("bid_price")),
		"landed_goods": _num(data.get("landed_goods")),
		"vat_pct": _num(data.get("vat_pct"), _BID_DEFAULTS["vat_pct"]),
		"exchange_pct": _num(data.get("exchange_pct"), _BID_DEFAULTS["exchange_pct"]),
		"profit_tax_pct": _num(data.get("profit_tax_pct"), _BID_DEFAULTS["profit_tax_pct"]),
		"dividend_tax_pct": _num(data.get("dividend_tax_pct"), _BID_DEFAULTS["dividend_tax_pct"]),
		"above_other": [
			{"label": str(x.get("label") or "").strip()[:140], "amount": _num(x.get("amount"))}
			for x in (data.get("above_other") or [])
			if isinstance(x, dict) and _num(x.get("amount"))
		],
		"below_other": [
			{"label": str(x.get("label") or "").strip()[:140], "amount": _num(x.get("amount"))}
			for x in (data.get("below_other") or [])
			if isinstance(x, dict) and _num(x.get("amount"))
		],
	}
	frappe.db.set_value(
		"CRM Deal", deal, "custom_bid_pricing", json.dumps(clean, ensure_ascii=False), update_modified=False
	)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	inp, refs = _bid_inputs(deal, company)
	return {"deal": deal, "currency": base_ccy, "inputs": inp, "pnl": _compute_bid_pnl(inp), **refs}


# --------------------------------------------------------------------------- #
# Tender intake + deadline control ("muddat nazorati").
# Pre-bid intake fields on the deal, plus a milestone timeline (bid / contract /
# PO ETA / delivery) with days-left + a good/warn/risk status per milestone.
# --------------------------------------------------------------------------- #
_INTAKE_KEYS_STR = (
	"lot_no",
	"buyer",
	"unit",
	"bid_deadline",
	"delivery_deadline",
	"guarantee_return",
	"go_no_go",
	"result",
	"purchase_method",
	"fx_currency",
	"notes",
)
_INTAKE_KEYS_NUM = (
	"volume",
	"guarantee_amount",
	"penalty_pct_per_day",
	"won_price",
	"fx_amount",
	"fx_bid_rate",
	"fx_pay_rate",
)
# Purchase method (способ закупки) drives the BPM branch: selection/tender require
# tender documents; auction/shop pass without.
_PURCHASE_METHODS = ("auction", "shop", "selection", "tender")


def _clean_intake(data: dict, prior: dict | None = None, audit_actor: str | None = None) -> dict:
	"""Normalize client-editable intake fields and preserve server audit facts.

	The browser may submit a stale or forged audit payload, so audit keys are
	never read from ``data``.  Existing facts survive an unchanged decision;
	changing a decision records a fresh server timestamp and actor instead.
	"""
	prior = prior or {}
	out = {k: str(data.get(k) or "").strip()[:200] for k in _INTAKE_KEYS_STR}
	for k in _INTAKE_KEYS_NUM:
		out[k] = _num(data.get(k))
	out["cert_required"] = 1 if data.get("cert_required") else 0
	# normalize decision / result / purchase-method vocab
	out["go_no_go"] = out["go_no_go"] if out["go_no_go"] in ("go", "no_go") else ""
	out["result"] = out["result"] if out["result"] in ("won", "lost", "pending") else ""
	out["purchase_method"] = out["purchase_method"] if out["purchase_method"] in _PURCHASE_METHODS else ""
	actor = audit_actor or frappe.session.user
	for field, at_key, by_key in (
		("go_no_go", "go_no_go_at", "go_no_go_by"),
		("result", "result_at", "result_by"),
	):
		if out[field] and out[field] == prior.get(field):
			out[at_key] = str(prior.get(at_key) or "")[:40]
			out[by_key] = str(prior.get(by_key) or "")[:140]
		elif out[field]:
			out[at_key] = now()
			out[by_key] = actor
		else:
			out[at_key] = ""
			out[by_key] = ""
	# Submission can only be created by mark_tender_submitted(). Preserve the
	# recorded fact across ordinary intake edits; never trust client-provided data.
	for key, limit in (("submitted_at", 40), ("submitted_by", 140), ("submission_reference", 200)):
		out[key] = str(prior.get(key) or "")[:limit]
	# Assignment defines the sourcing visibility boundary. It is changed only by
	# assign_tender(); ordinary intake payloads may neither spoof nor clear it.
	for key, limit in (
		("assigned_to", 140),
		("assigned_to_name", 200),
		("assigned_at", 40),
		("assigned_by", 140),
	):
		out[key] = str(prior.get(key) or "")[:limit]
	# document checklist (ГТД, certificate, acceptance act, contract, invoice …)
	out["documents"] = [
		{
			"label": str(d.get("label") or "").strip()[:140],
			"required": 1 if d.get("required") else 0,
			"done": 1 if d.get("done") else 0,
			"date": str(d.get("date") or "").strip()[:20],
		}
		for d in (data.get("documents") or [])
		if isinstance(d, dict) and str(d.get("label") or "").strip()
	][:40]
	prior_ready = prior.get("go_no_go") == "go" and not any(
		d.get("required") and not d.get("done") for d in (prior.get("documents") or [])
	)
	current_ready = out["go_no_go"] == "go" and not any(
		d.get("required") and not d.get("done") for d in out["documents"]
	)
	if current_ready and prior_ready:
		out["ready_at"] = str(prior.get("ready_at") or "")[:40]
		out["ready_by"] = str(prior.get("ready_by") or "")[:140]
	elif current_ready:
		out["ready_at"] = now()
		out["ready_by"] = actor
	else:
		out["ready_at"] = ""
		out["ready_by"] = ""
	return out


def _fx_summary(intake: dict) -> dict:
	"""FX exposure & risk: goods bought in a foreign currency, sold in UZS. Planned
	base = amount × bid-rate; realized = amount × pay-rate; a higher pay-rate means
	the delivered cost rose in UZS (unfavorable → warn/risk)."""
	cur = str(intake.get("fx_currency") or "").strip().upper()[:8]
	amt = _num(intake.get("fx_amount"))
	br = _num(intake.get("fx_bid_rate"))
	pr = _num(intake.get("fx_pay_rate"))
	planned = amt * br
	realized = amt * pr if pr else 0.0
	delta = (realized - planned) if pr else 0.0
	delta_pct = (delta / planned * 100) if (pr and planned) else 0.0
	if not (cur and amt and br):
		status = "none"
	elif not pr:
		status = "open"  # exposure set but rate not yet realized
	elif delta_pct > 3:
		status = "risk"
	elif delta_pct > 0:
		status = "warn"
	else:
		status = "good"
	return {
		"currency": cur,
		"amount": amt,
		"bid_rate": br,
		"pay_rate": pr,
		"planned_base": planned,
		"realized_base": realized,
		"delta": delta,
		"delta_pct": round(delta_pct, 2),
		"status": status,
	}


def _docs_summary(intake: dict) -> dict:
	docs = intake.get("documents") or []
	req = [d for d in docs if d.get("required")]
	return {
		"total": len(docs),
		"required": len(req),
		"done_required": sum(1 for d in req if d.get("done")),
		"missing": [d.get("label") for d in req if not d.get("done")],
	}


def _read_intake(deal: str) -> dict:
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		return {}
	return _parse_intake(frappe.db.get_value("CRM Deal", deal, "custom_tender_intake"))


def _parse_intake(raw) -> dict:
	if not raw:
		return {}
	try:
		return raw if isinstance(raw, dict) else json.loads(raw)
	except (ValueError, TypeError):
		return {}


def _read_intake_for_update(deal: str) -> dict:
	"""Lock the Deal row and return the latest committed intake JSON."""
	rows = frappe.db.sql(
		"""SELECT custom_tender_intake
		FROM `tabCRM Deal`
		WHERE name = %s
		FOR UPDATE""",
		(deal,),
		as_dict=True,
	)
	return _parse_intake(rows[0].get("custom_tender_intake") if rows else None)


def _milestone(key: str, label: str, date_val, done: bool, today_d) -> dict | None:
	"""Build one deadline milestone with days-left + risk status."""
	if not date_val:
		return {
			"key": key,
			"label": label,
			"date": None,
			"days_left": None,
			"status": "none",
			"done": bool(done),
		}
	d = getdate(date_val)
	days = (d - today_d).days
	if done:
		status = "good"
	elif days < 0:
		status = "risk"
	elif days <= 7:
		status = "warn"
	else:
		status = "good"
	return {
		"key": key,
		"label": label,
		"date": str(d),
		"days_left": days,
		"status": status,
		"done": bool(done),
	}


def _deal_deadlines(deal: str, company: str, intake: dict) -> dict:
	"""Milestone timeline across the tender chain, from intake + SO + PO dates."""
	today_d = getdate(today())

	# Sales Orders (revenue / contract / delivery side)
	so_rows = []
	if frappe.db.has_column("Sales Order", "custom_crm_deal"):
		so_rows = frappe.get_list(
			"Sales Order",
			filters={"custom_crm_deal": deal, "company": company, "docstatus": ["<", 2]},
			fields=["name", "transaction_date", "delivery_date", "per_delivered"],
			limit_page_length=1000,
		)
		so_rows = [row for row in so_rows if frappe.has_permission("Sales Order", "read", doc=row.name)]
	so_exists = bool(so_rows)
	so_delivered = bool(so_rows) and all(flt(s.per_delivered) >= 100 for s in so_rows)
	so_first_txn = min((s.transaction_date for s in so_rows if s.transaction_date), default=None)
	so_delivery = min((s.delivery_date for s in so_rows if s.delivery_date), default=None)

	# Purchase Orders (procurement / ETA side)
	po_rows = []
	if frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		po_rows = frappe.get_list(
			"Purchase Order",
			filters={"custom_crm_deal": deal, "company": company, "docstatus": ["<", 2]},
			fields=["name", "schedule_date", "per_received"],
			limit_page_length=1000,
		)
		po_rows = [row for row in po_rows if frappe.has_permission("Purchase Order", "read", doc=row.name)]
	po_received = bool(po_rows) and all(flt(p.per_received) >= 100 for p in po_rows)
	po_eta = min((p.schedule_date for p in po_rows if p.schedule_date), default=None)

	bid_done = bool(intake.get("result")) or bool(intake.get("go_no_go") == "no_go")
	delivery_date = intake.get("delivery_deadline") or so_delivery

	milestones = [
		_milestone("bid", _("Bid deadline"), intake.get("bid_deadline"), bid_done, today_d),
		_milestone("contract", _("Contract"), so_first_txn, so_exists, today_d),
		_milestone("po_eta", _("PO ETA"), po_eta, po_received, today_d),
		_milestone("delivery", _("Delivery deadline"), delivery_date, so_delivered, today_d),
	]
	# Guarantee return (garov qaytishi) — only when a return date is set. Considered
	# done once the contract is closed (delivered) or the bid was lost.
	if intake.get("guarantee_return"):
		g_done = bool(so_delivered or intake.get("result") == "lost")
		milestones.append(
			_milestone("guarantee", _("Guarantee return"), intake.get("guarantee_return"), g_done, today_d)
		)
	milestones = [m for m in milestones if m]
	worst = "good"
	for m in milestones:
		if m["status"] == "risk":
			worst = "risk"
			break
		if m["status"] == "warn":
			worst = "warn"
	return {"milestones": milestones, "risk": worst, "today": str(today_d)}


@frappe.whitelist()
def deal_intake(deal: str) -> dict:
	"""Read the tender intake + the deadline/risk timeline for a deal."""
	company = _deal_scope(deal, write=False)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	intake = _read_intake(deal)
	return {
		"deal": deal,
		"currency": base_ccy,
		"intake": intake,
		"deadlines": _deal_deadlines(deal, company, intake),
		"docs": _docs_summary(intake),
		"fx": _fx_summary(intake),
	}


@frappe.whitelist()
def save_deal_intake(deal: str, intake) -> dict:
	"""Persist the tender intake (JSON) on the CRM Deal and return it + deadlines."""
	company = _deal_scope(deal, write=True)
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		frappe.throw(_("Run migrate to enable tender intake."))
	try:
		data = intake if isinstance(intake, dict) else json.loads(intake)
	except (ValueError, TypeError):
		frappe.throw(_("Invalid intake payload."))
	clean = _clean_intake(data, _read_intake_for_update(deal))
	frappe.db.set_value(
		"CRM Deal", deal, "custom_tender_intake", json.dumps(clean, ensure_ascii=False), update_modified=False
	)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	return {
		"deal": deal,
		"currency": base_ccy,
		"intake": clean,
		"deadlines": _deal_deadlines(deal, company, clean),
		"docs": _docs_summary(clean),
		"fx": _fx_summary(clean),
	}


@frappe.whitelist()
def mark_tender_submitted(deal: str, submission_reference: str = "") -> dict:
	"""Record a tender submission with an immutable server-side audit trail."""
	company = _deal_scope(deal, write=True)
	if not set(_tender_views()).intersection(("director", "sourcing")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		frappe.throw(_("Run migrate to enable tender intake."))
	# The locking read serializes concurrent submissions. A request waiting here
	# re-reads the winner's committed JSON before deciding whether it may write.
	intake = _read_intake_for_update(deal)
	if _has_submission_evidence(intake):
		return {
			"deal": deal,
			"company": company,
			"submitted_at": intake["submitted_at"],
			"submitted_by": intake["submitted_by"],
			"submission_reference": intake.get("submission_reference") or "",
		}
	intake["submitted_at"] = now()
	intake["submitted_by"] = frappe.session.user
	intake["submission_reference"] = str(submission_reference or "").strip()[:200]
	clean = _clean_intake(intake, intake)
	# _clean_intake intentionally ignores client audit keys; submission facts are
	# introduced here, after access checks, and therefore always server-owned.
	clean["submitted_at"] = intake["submitted_at"]
	clean["submitted_by"] = intake["submitted_by"]
	clean["submission_reference"] = intake["submission_reference"]
	frappe.db.set_value(
		"CRM Deal", deal, "custom_tender_intake", json.dumps(clean, ensure_ascii=False), update_modified=False
	)
	return {
		"deal": deal,
		"company": company,
		"submitted_at": clean["submitted_at"],
		"submitted_by": clean["submitted_by"],
		"submission_reference": clean["submission_reference"],
	}


def set_tender_go_no_go_from_trusted_source(deal: str, decision: str, *, actor: str) -> dict:
	"""Persist a portal decision with the trusted integration actor in its audit.

	This helper is intentionally not whitelisted. Callers are responsible for
	authenticating their transport (the UZEX webhook verifies Telegram's secret),
	while this layer still validates the Deal's company and tender enablement.
	"""
	if decision not in ("go", "no_go"):
		frappe.throw(_("Invalid Go/No-Go decision."))
	if not actor:
		frappe.throw(_("Trusted actor is required."), frappe.PermissionError)
	if not deal or not frappe.db.exists("CRM Deal", deal):
		frappe.throw(_("Unknown deal: {0}").format(deal), frappe.DoesNotExistError)
	company = frappe.db.get_value("CRM Deal", deal, "company")
	_require_company(company)
	_require_tender_enabled(company)
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		frappe.throw(_("Run migrate to enable tender intake."))
	prior = _read_intake_for_update(deal)
	clean = _clean_intake({**prior, "go_no_go": decision}, prior, audit_actor=actor)
	frappe.db.set_value(
		"CRM Deal", deal, "custom_tender_intake", json.dumps(clean, ensure_ascii=False), update_modified=False
	)
	return {
		"deal": deal,
		"company": company,
		"go_no_go": clean["go_no_go"],
		"go_no_go_at": clean["go_no_go_at"],
		"go_no_go_by": clean["go_no_go_by"],
	}


# --------------------------------------------------------------------------- #
# Tender role windows ("rol oynalari") — director / sourcing / declarant / logist.
# UX access layer over the existing tender module gate; real security stays in
# Frappe has_permission on every underlying doctype read.
# --------------------------------------------------------------------------- #
_TENDER_VIEW_ROLES = {
	"director": ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Tender Director"),
	"sourcing": ("System Manager", "Stabler Admin", "Sales Manager", "Sales User"),
	"declarant": ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Declarant"),
	"logist": ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Logist"),
}


def _tender_views(user: str | None = None) -> list[str]:
	roles = set(frappe.get_roles(user or frappe.session.user))
	return [v for v, allow in _TENDER_VIEW_ROLES.items() if roles.intersection(allow)]


def _require_tender_view(view: str, company: str) -> None:
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)
	if view not in _tender_views():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def tender_views() -> dict:
	"""Which role windows the current user may open (drives SPA nav)."""
	return {"views": _tender_views()}


_OVERSIGHT_ROLES = ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Tender Director")


def _is_tender_oversight(user: str | None = None) -> bool:
	"""Oversight = sees every tender (director / dep-head / admin). Plain sourcing
	users only see tenders assigned to them."""
	return bool(set(frappe.get_roles(user or frappe.session.user)).intersection(_OVERSIGHT_ROLES))


@frappe.whitelist()
def tender_managers(company: str) -> dict:
	"""Users a tender can be assigned to (sourcing roles), for the distribution UI."""
	_require_tender_view("director", company)
	names: set[str] = set()
	for r in frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["Sales User", "Sales Manager"]], "parenttype": "User"},
		fields=["parent"],
		distinct=True,
		limit_page_length=1000,
	):
		names.add(r.parent)
	out = []
	for u in names:
		if u in ("Administrator", "Guest"):
			continue
		row = frappe.db.get_value("User", u, ["enabled", "full_name"], as_dict=True)
		if row and row.enabled:
			out.append({"name": u, "full_name": row.full_name or u})
	out.sort(key=lambda x: x["full_name"].lower())
	return {"managers": out}


@frappe.whitelist()
def assign_tender(deal: str, user: str = "") -> dict:
	"""Assign a tender to a manager (director / dep-head only). Empty = unassign."""
	_deal_scope(deal, write=True)
	if not _is_tender_oversight():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not frappe.db.has_column("CRM Deal", "custom_tender_intake"):
		frappe.throw(_("Run migrate to enable tender intake."))
	name = ""
	if user:
		if not frappe.db.exists("User", user):
			frappe.throw(_("Unknown user: {0}").format(user))
		name = frappe.db.get_value("User", user, "full_name") or user
	intake = _read_intake_for_update(deal)
	clean = _clean_intake(intake, intake)
	clean["assigned_to"] = user or ""
	clean["assigned_to_name"] = name
	if user:
		if user != intake.get("assigned_to") or not (intake.get("assigned_at") and intake.get("assigned_by")):
			clean["assigned_at"] = now()
			clean["assigned_by"] = frappe.session.user
	else:
		clean["assigned_at"] = ""
		clean["assigned_by"] = ""
	frappe.db.set_value(
		"CRM Deal", deal, "custom_tender_intake", json.dumps(clean, ensure_ascii=False), update_modified=False
	)
	return {
		"deal": deal,
		"assigned_to": user or "",
		"assigned_to_name": name,
		"assigned_at": clean["assigned_at"],
		"assigned_by": clean["assigned_by"],
	}


def _tender_deal_names(company: str) -> set[str]:
	"""All CRM Deals that are tenders for this company: any tagged SO/PO/quotation,
	plus deals carrying an intake or pricing plan."""
	names: set[str] = set()
	if not frappe.db.exists("DocType", "CRM Deal"):
		return names
	for dt in ("Sales Order", "Purchase Order", "Supplier Quotation"):
		if frappe.db.has_column(dt, "custom_crm_deal"):
			for r in frappe.get_list(
				dt,
				filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": ["<", 2]},
				fields=["custom_crm_deal"],
				distinct=True,
				limit_page_length=5000,
			):
				if r.custom_crm_deal:
					names.add(r.custom_crm_deal)
	for fld in ("custom_tender_intake", "custom_bid_pricing"):
		if frappe.db.has_column("CRM Deal", fld):
			for r in frappe.get_list(
				"CRM Deal",
				filters={"company": company, fld: ["is", "set"]},
				fields=["name"],
				limit_page_length=5000,
			):
				names.add(r.name)
	return names


def _deal_label(deal: str) -> str:
	return (
		frappe.db.get_value("CRM Deal", deal, "organization")
		or frappe.db.get_value("CRM Deal", deal, "lead_name")
		or deal
	)


_RISK_ORDER = {"risk": 0, "warn": 1, "good": 2, "none": 3}


def _tender_filter_evidence(intake: dict, creation, risk: str) -> dict:
	"""Evidence-bearing lifecycle fields for client-side tender-board filters."""
	decision = intake.get("go_no_go")
	verified = _has_submission_evidence(intake)
	result = intake.get("result") if verified else ""
	event_dates = _tender_event_dates(intake, creation)
	return {
		"event_date": event_dates["identified"],
		"event_dates": event_dates,
		"lifecycle": {
			"identified": True,
			"decided": decision in ("go", "no_go"),
			"go": decision == "go",
			"ready": _has_ready_evidence(intake),
			"submitted": verified,
			"assigned": (intake.get("assigned_to") or "") == frappe.session.user,
			"unverified_history": bool(intake.get("result") and not verified),
		},
		"status": result or ("unverified_history" if intake.get("result") else ""),
		"due": "late" if risk == "risk" else ("soon" if risk == "warn" else "on_time"),
	}


def _tender_director_payload(company: str, *, include_rows: bool) -> dict:
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	rows = []
	visible_count = 0
	total_value = 0.0
	total_ost = 0.0
	at_risk = 0
	margins = []
	won = lost = pending = 0
	unverified_history = 0
	for deal in _tender_deal_names(company):
		if not frappe.has_permission("CRM Deal", "read", doc=deal):
			continue
		visible_count += 1
		intake = _read_intake(deal)
		verified = _has_submission_evidence(intake)
		_res = intake.get("result") if verified else ""
		if _res == "won":
			won += 1
		elif _res == "lost":
			lost += 1
		elif _res == "pending":
			pending += 1
		elif intake.get("result"):
			unverified_history += 1
		dl = _deal_deadlines(deal, company, intake)
		evidence = _tender_filter_evidence(
			intake,
			frappe.db.get_value("CRM Deal", deal, "creation"),
			dl["risk"],
		)
		inp, refs = _bid_inputs(deal, company)
		pnl = _compute_bid_pnl(inp)
		value = flt(refs["so_revenue"]) or flt(pnl["bid_price"])
		total_value += value
		total_ost += flt(pnl["ostatok"])
		if pnl["margin_on_revenue_pct"]:
			margins.append(pnl["margin_on_revenue_pct"])
		if dl["risk"] == "risk":
			at_risk += 1
		delivery = next((m["date"] for m in dl["milestones"] if m["key"] == "delivery"), None)
		if include_rows:
			rows.append(
				{
					"deal": deal,
					"label": _deal_label(deal),
					"value": value,
					"landed": refs["po_landed"],
					"ostatok": pnl["ostatok"],
					"margin_pct": pnl["margin_on_revenue_pct"],
					"po_count": refs["po_count"],
					"so_count": refs["so_count"],
					"risk": dl["risk"],
					"delivery": delivery,
					"result": _res,
					"event_date": evidence["event_date"],
					"event_dates": evidence["event_dates"],
					"lifecycle": evidence["lifecycle"],
					"status": evidence["status"],
					"due": evidence["due"],
					"assigned_to": intake.get("assigned_to") or "",
					"assigned_to_name": intake.get("assigned_to_name") or "",
				}
			)
	kpi = {
		"count": visible_count,
		"total_value": total_value,
		"avg_margin": round(sum(margins) / len(margins), 1) if margins else 0,
		"at_risk": at_risk,
		"total_ostatok": total_ost,
		"won": won,
		"lost": lost,
		"pending": pending,
		"unverified_history": unverified_history,
		"win_rate": round(won / (won + lost) * 100, 1) if (won + lost) else 0,
	}
	payload = {"currency": base_ccy, "kpi": kpi}
	if include_rows:
		rows.sort(
			key=lambda r: (
				_RISK_ORDER.get(r["risk"], 3),
				r["delivery"] or "9999-99-99",
				r["deal"],
			)
		)
		payload["rows"] = rows
	return payload


def _dashboard_executive_payload(company: str, views: set[str]) -> dict:
	if "director" not in views:
		return {"executive_kpi": None, "executive_currency": ""}
	executive = _tender_director_payload(company, include_rows=False)
	return {
		"executive_kpi": executive["kpi"],
		"executive_currency": executive["currency"],
	}


@frappe.whitelist()
def tender_director_board(company: str) -> dict:
	"""Director portfolio: every tender with value, margin, Остаток, deadline risk.

	Rows retain the "event_date", "lifecycle", "status", and "due" filter evidence.
	"""
	_require_tender_view("director", company)
	return _tender_director_payload(company, include_rows=True)


def _po_rows_for_views(company: str) -> tuple[list, bool]:
	"""Shared PO fetch for declarant/logist windows (all tenders)."""
	if not frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		return [], False
	has_landed = frappe.db.has_column("Purchase Order", "custom_landed_charges")
	fields = [
		"name",
		"supplier",
		"supplier_name",
		"transaction_date",
		"schedule_date",
		"per_received",
		"custom_crm_deal",
		"status",
	]
	if has_landed:
		fields.append("custom_landed_charges")
	rows = frappe.get_list(
		"Purchase Order",
		filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": ["<", 2]},
		fields=fields,
		order_by="schedule_date asc",
		limit_page_length=2000,
	)
	return [row for row in rows if frappe.has_permission("Purchase Order", "read", doc=row.name)], has_landed


@frappe.whitelist()
def declarant_queue(company: str) -> dict:
	"""Declarant window: POs awaiting customs, with ТН ВЭД + customs charge + ETA."""
	_require_tender_view("declarant", company)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	pos, has_landed = _po_rows_for_views(company)
	today_d = getdate(today())
	out = []
	for p in pos:
		charges = _parse_landed(p.get("custom_landed_charges")) if has_landed else []
		customs_total = sum(c["amount"] for c in charges if c["type"] == "customs")
		tnved = next((c["tnved"] for c in charges if c.get("tnved")), "")
		cleared = flt(p.per_received) >= 100
		eta = getdate(p.schedule_date) if p.schedule_date else None
		days = (eta - today_d).days if eta else None
		status = "cleared" if cleared else ("in_progress" if customs_total else "pending")
		risk = (
			"risk"
			if days is not None and days < 0
			else ("warn" if days is not None and days <= 7 else "good")
		)
		deal = p.custom_crm_deal
		can_read_deal = bool(deal and frappe.has_permission("CRM Deal", "read", doc=deal))
		out.append(
			{
				"po": p.name,
				"supplier_name": p.supplier_name,
				"deal": deal,
				"deal_label": _deal_label(deal) if can_read_deal else "",
				"tnved": tnved,
				"customs_total": customs_total,
				"event_date": str(p.transaction_date or ""),
				"eta": str(eta) if eta else None,
				"days_left": days,
				"stage": status,
				"status": status,
				"risk": risk,
				"due": "late" if risk == "risk" else ("soon" if risk == "warn" else "on_time"),
			}
		)
	return {"currency": base_ccy, "rows": out}


@frappe.whitelist()
def logist_board(company: str) -> dict:
	"""Logistician window: shipments (POs) with ETA, delivery deadline and delay risk."""
	_require_tender_view("logist", company)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	pos, has_landed = _po_rows_for_views(company)
	deliv_cache: dict[str, object] = {}
	out = []
	for p in pos:
		charges = _parse_landed(p.get("custom_landed_charges")) if has_landed else []
		transport = sum(c["amount"] for c in charges if c["type"] in ("transport", "loading"))
		received = flt(p.per_received) >= 100
		eta = getdate(p.schedule_date) if p.schedule_date else None
		deal = p.custom_crm_deal
		if deal not in deliv_cache:
			can_read_deal = bool(deal and frappe.has_permission("CRM Deal", "read", doc=deal))
			dv = None
			if can_read_deal:
				intake = _read_intake(deal)
				dv = intake.get("delivery_deadline")
				if not dv and frappe.db.has_column("Sales Order", "custom_crm_deal"):
					dv = min(
						(
							s.delivery_date
							for s in frappe.get_list(
								"Sales Order",
								filters={"custom_crm_deal": deal, "company": company, "docstatus": ["<", 2]},
								fields=["name", "delivery_date"],
								limit_page_length=500,
							)
							if frappe.has_permission("Sales Order", "read", doc=s.name) and s.delivery_date
						),
						default=None,
					)
			deliv_cache[deal] = getdate(dv) if dv else None
		delivery = deliv_cache[deal]
		late = bool(not received and eta and delivery and eta > delivery)
		status = "delivered" if received else ("late" if late else "in_transit")
		out.append(
			{
				"po": p.name,
				"supplier_name": p.supplier_name,
				"deal": deal,
				"deal_label": _deal_label(deal)
				if deal and frappe.has_permission("CRM Deal", "read", doc=deal)
				else "",
				"transport": transport,
				"event_date": str(p.transaction_date or ""),
				"eta": str(eta) if eta else None,
				"delivery": str(delivery) if delivery else None,
				"received": received,
				"stage": status,
				"status": status,
				"risk": "risk" if status == "late" else "good",
				"due": "late" if status == "late" else "on_time",
			}
		)
	return {"currency": base_ccy, "rows": out}


@frappe.whitelist()
def sourcing_my_tenders(company: str) -> dict:
	"""Sourcing window: the tender pipeline with landed cost, PO/vendor counts and risk."""
	_require_tender_view("sourcing", company)
	base_ccy = frappe.db.get_value("Company", company, "default_currency") or ""
	# Oversight roles see the whole pipeline; a plain sourcing user sees only the
	# tenders assigned to them (the department head distributes via assign_tender).
	oversight = _is_tender_oversight()
	me = frappe.session.user
	rows = []
	for deal in _tender_deal_names(company):
		if not frappe.has_permission("CRM Deal", "read", doc=deal):
			continue
		intake = _read_intake(deal)
		if not oversight and (intake.get("assigned_to") or "") != me:
			continue
		dl = _deal_deadlines(deal, company, intake)
		evidence = _tender_filter_evidence(
			intake,
			frappe.db.get_value("CRM Deal", deal, "creation"),
			dl["risk"],
		)
		po_landed, po_count = _deal_landed(deal, company)
		delivery = next((m["date"] for m in dl["milestones"] if m["key"] == "delivery"), None)
		rows.append(
			{
				"deal": deal,
				"label": _deal_label(deal),
				"landed": po_landed,
				"po_count": po_count,
				"risk": dl["risk"],
				"delivery": delivery,
				"result": intake.get("result") or "",
				"event_date": evidence["event_date"],
				"event_dates": evidence["event_dates"],
				"lifecycle": evidence["lifecycle"],
				"status": evidence["status"],
				"due": evidence["due"],
				"assigned_to": intake.get("assigned_to") or "",
				"assigned_to_name": intake.get("assigned_to_name") or "",
			}
		)
	rows.sort(key=lambda r: (_RISK_ORDER.get(r["risk"], 3), r["delivery"] or "9999-99-99"))
	return {"currency": base_ccy, "rows": rows, "oversight": oversight}


@frappe.whitelist()
def tender_funnel(company: str, days: int = 90):
	"""Pipeline funnel: every tender counted in exactly ONE stage, plus the
	conversion funnel and execution buckets. Stage boxes show the current state
	of open tenders; won/lost and the funnel respect the reporting window so the
	win-rate is a period statement.

	Classification lives in _funnel.py (pure) — precedence result > submitted >
	priced > sourcing > go > seen keeps a deal from appearing in two boxes.
	"""
	from datetime import timedelta

	from stabler.api import _funnel

	_require_tender(company)
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	days = max(7, min(cint(days) or 90, 366))
	cutoff = getdate(today()) - timedelta(days=days)

	# One grouped pass for quotation counts — not one query per deal.
	sq_counts: dict[str, int] = {}
	if frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		for r in frappe.get_all(
			"Supplier Quotation",
			filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": ["<", 2]},
			fields=["custom_crm_deal"],
			limit_page_length=0,
		):
			sq_counts[r.custom_crm_deal] = sq_counts.get(r.custom_crm_deal, 0) + 1

	has_pricing_col = frappe.db.has_column("CRM Deal", "custom_bid_pricing")
	rows = []
	stage_rows: dict[str, list] = {}
	policy_gap = submitted_urgent = 0
	for deal in _tender_deal_names(company):
		if not frappe.has_permission("CRM Deal", "read", doc=deal):
			continue
		intake = _read_intake(deal)
		has_pricing = bool(
			has_pricing_col and frappe.db.get_value("CRM Deal", deal, "custom_bid_pricing")
		)
		stage = _funnel.classify(
			{
				"go_no_go": intake.get("go_no_go"),
				"result": intake.get("result"),
				"submitted": _has_submission_evidence(intake),
				"has_pricing": has_pricing,
				"sq_count": sq_counts.get(deal, 0),
			}
		)
		# Window: terminal stages date from the result stamp; open ones from creation.
		if stage in ("won", "lost"):
			ref_date = intake.get("result_at") or frappe.db.get_value("CRM Deal", deal, "creation")
		else:
			ref_date = frappe.db.get_value("CRM Deal", deal, "creation")
		try:
			in_window = getdate(ref_date) >= cutoff
		except (TypeError, ValueError):
			in_window = True
		# Deadline urgency only matters (and only costs a computation) while open.
		urgent = False
		if stage in ("go", "sourcing", "priced", "submitted"):
			urgent = _deal_deadlines(deal, company, intake)["risk"] == "risk"
		if stage == "sourcing" and sq_counts.get(deal, 0) < 5:
			policy_gap += 1
		if stage == "submitted" and urgent:
			submitted_urgent += 1
		rows.append({"stage": stage, "urgent": urgent, "in_window": in_window})
		# The drill list is built in the SAME pass as the count, so a stage's
		# number and its list can never disagree. Terminal stages only list
		# in-window deals — exactly what the box counted.
		if stage not in ("won", "lost") or in_window:
			stage_rows.setdefault(stage, []).append({
				"deal": deal,
				"label": _deal_label(deal),
				"lot_no": intake.get("lot_no") or "",
				"buyer": intake.get("buyer") or "",
				"bid_deadline": intake.get("bid_deadline") or "",
				"delivery_deadline": intake.get("delivery_deadline") or "",
				"sq_count": sq_counts.get(deal, 0),
				"urgent": urgent,
				"won_price": flt(intake.get("won_price")) or 0,
				"result_at": str(intake.get("result_at") or "")[:10],
			})

	for lst in stage_rows.values():
		lst.sort(key=lambda r: (not r["urgent"], r["bid_deadline"] or "9999-99-99"))
	out = _funnel.summarise(rows)
	out["meta"] = {"sourcing_policy_gap": policy_gap, "submitted_urgent": submitted_urgent}
	out["rows"] = stage_rows

	# Execution buckets from the contract board (submitted SOs tagged to a deal).
	so_stages = []
	so_rows: dict[str, list] = {}
	if frappe.db.has_column("Sales Order", "custom_crm_deal"):
		for r in frappe.get_all(
			"Sales Order",
			filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": 1},
			fields=["name", "custom_crm_deal", "custom_board_stage", "customer",
				"rounded_total", "grand_total", "delivery_date", "currency"],
			limit_page_length=0,
		):
			so_stages.append(r.custom_board_stage)
			so_rows.setdefault(_funnel.bucket_so(r.custom_board_stage), []).append({
				"so": r.name,
				"deal": r.custom_crm_deal,
				"stage": r.custom_board_stage or "New",
				"customer": r.customer,
				"total": flt(r.rounded_total or r.grand_total),
				"currency": r.currency or "",
				"delivery_date": str(r.delivery_date) if r.delivery_date else "",
			})
	out["so"] = _funnel.summarise_so(so_stages)
	out["so_rows"] = so_rows
	out["days"] = days
	out["currency"] = frappe.db.get_value("Company", company, "default_currency") or ""
	return out


# --------------------------------------------------------------------------- #
# Tender operations centre — compact, role-adaptive aggregate feed for the SPA
# dashboard. Detail pages remain the source of record; this endpoint only
# returns counts and a small attention queue, always after the same company,
# module, role-window and document-permission checks as those pages.
# --------------------------------------------------------------------------- #
def _dashboard_period(from_date=None, to_date=None) -> tuple[object, object]:
	end = getdate(to_date) if to_date else getdate(today())
	start = getdate(from_date) if from_date else getdate(f"{end.year}-{end.month:02d}-01")
	if start > end:
		frappe.throw(_("From date cannot be after to date."))
	return start, end


def _in_dashboard_period(value, start, end) -> bool:
	if not value:
		return False
	try:
		day = getdate(value)
	except (TypeError, ValueError):
		return False
	return start <= day <= end


def _tender_event_dates(intake: dict, creation) -> dict[str, str]:
	"""Return the server evidence date for each lifecycle transition."""
	decision_at = str(intake.get("go_no_go_at") or "")
	submitted_at = str(intake.get("submitted_at") or "")
	result_at = str(intake.get("result_at") or "")
	decision = intake.get("go_no_go")
	result = intake.get("result")
	ready_at = str(intake.get("ready_at") or "") if _has_ready_evidence(intake) else ""
	event_dates = {
		"identified": str(creation or ""),
		"decided": decision_at if decision in ("go", "no_go") else "",
		"go": decision_at if decision == "go" else "",
		"no_go": decision_at if decision == "no_go" else "",
		"ready": ready_at,
		"submitted": submitted_at if _has_submission_evidence(intake) else "",
		"result": result_at if result else "",
		"won": result_at if result == "won" and _has_submission_evidence(intake) else "",
		"lost": result_at if result == "lost" and _has_submission_evidence(intake) else "",
		"pending": result_at if result == "pending" and _has_submission_evidence(intake) else "",
		"unverified_history": result_at if result and not _has_submission_evidence(intake) else "",
	}
	event_dates["assigned"] = str(intake.get("assigned_at") or "") if intake.get("assigned_to") else ""
	return event_dates


def _has_submission_evidence(intake: dict) -> bool:
	"""A result is not proof of participation; both server audit fields are."""
	return bool(intake.get("submitted_at") and intake.get("submitted_by"))


def _has_ready_evidence(intake: dict) -> bool:
	"""Readiness is current completeness backed by a server transition audit."""
	return bool(
		intake.get("go_no_go") == "go"
		and not _docs_summary(intake)["missing"]
		and intake.get("ready_at")
		and intake.get("ready_by")
	)


def _can_view_tender_finance(user: str | None = None) -> bool:
	roles = set(frappe.get_roles(user or frappe.session.user))
	return _is_tender_oversight(user) or bool(roles.intersection(("Accounts User", "Accounts Manager")))


def _intake_attention(deal: str, intake: dict, today_d) -> list[dict]:
	items = []
	deadline = intake.get("bid_deadline")
	if deadline:
		try:
			days_left = (getdate(deadline) - today_d).days
			if days_left <= 7:
				items.append(
					{
						"deal": deal,
						"kind": "bid_deadline",
						"date": str(getdate(deadline)),
						"days_left": days_left,
						"severity": "risk" if days_left < 0 else "warn",
					}
				)
		except (TypeError, ValueError):
			pass
	missing = _docs_summary(intake)["missing"]
	if intake.get("go_no_go") == "go" and missing:
		items.append({"deal": deal, "kind": "documents", "missing": missing, "severity": "warn"})
	if intake.get("result") and not _has_submission_evidence(intake):
		items.append({"deal": deal, "kind": "unverified_history", "severity": "warn"})
	return items


def _weighted_progress(rows, field: str) -> float:
	total = sum(flt(row.get("base_grand_total")) for row in rows)
	if not total:
		return 0.0
	done = sum(flt(row.get("base_grand_total")) * flt(row.get(field)) / 100 for row in rows)
	return round(done / total * 100, 1)


def _monthly_trend(events: list[dict], start, end) -> list[dict]:
	months = {}
	cursor = getdate(start).replace(day=1)
	while cursor <= end:
		key = cursor.strftime("%Y-%m")
		months[key] = {"month": key, "submitted": 0, "won": 0, "won_value": 0.0}
		cursor = add_months(cursor, 1)
	for event in events:
		submitted = str(event.get("submitted_at") or "")[:7]
		won = str(event.get("result_at") or "")[:7]
		if submitted in months:
			months[submitted]["submitted"] += 1
		if event.get("result") == "won" and won in months:
			months[won]["won"] += 1
			months[won]["won_value"] += flt(event.get("value"))
	return list(months.values())


def _portfolio_deadlines(intake: dict, pos, sos, today_d) -> dict:
	"""Calculate portfolio risk from the already fetched, readable PO/SO rows."""
	po_received = bool(pos) and all(flt(row.per_received) >= 100 for row in pos)
	so_delivered = bool(sos) and all(flt(row.per_delivered) >= 100 for row in sos)
	so_delivery = min((row.get("delivery_date") for row in sos if row.get("delivery_date")), default=None)
	milestones = [
		_milestone(
			"bid",
			_("Bid deadline"),
			intake.get("bid_deadline"),
			bool(intake.get("result") or intake.get("go_no_go") == "no_go"),
			today_d,
		),
		_milestone(
			"po_eta",
			_("PO ETA"),
			min((row.get("schedule_date") for row in pos if row.get("schedule_date")), default=None),
			po_received,
			today_d,
		),
		_milestone(
			"delivery",
			_("Delivery deadline"),
			intake.get("delivery_deadline") or so_delivery,
			so_delivered,
			today_d,
		),
	]
	if any(milestone["status"] == "risk" for milestone in milestones):
		return {"risk": "risk"}
	if any(milestone["status"] == "warn" for milestone in milestones):
		return {"risk": "warn"}
	return {"risk": "good"}


@frappe.whitelist()
def tender_dashboard(
	company: str, from_date=None, to_date=None, trend_from_date=None, trend_to_date=None
) -> dict:
	"""Tender lifecycle and execution KPIs for the active company and role.

	Only records the caller can read are considered.  In particular, an old deal
	with a result but no server submission audit remains ``unverified_history``;
	it never silently raises submitted, won, or lost participation counts.
	"""
	_require_company(company)
	_require_tender(company)
	_assert_company_scope(company)
	views = _tender_views()
	if not views:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	start, end = _dashboard_period(from_date, to_date)
	trend_start, trend_end = _dashboard_period(trend_from_date or start, trend_to_date or end)
	user = frappe.session.user
	oversight = _is_tender_oversight(user)
	can_view_finance = _can_view_tender_finance(user)
	is_sourcing = "sourcing" in views
	is_operations = bool(set(views).intersection(("declarant", "logist")))
	acquisition_scope = "portfolio" if oversight else ("assigned" if is_sourcing else "none")
	execution_scope = "portfolio" if oversight or is_operations else "assigned"
	today_d = getdate(today())
	acquisition = {
		"identified": 0,
		"go": 0,
		"no_go": 0,
		"ready": 0,
		"submitted": 0,
		"won": 0,
		"lost": 0,
		"pending": 0,
		"unverified_history": 0,
	}
	attention: list[dict] = []
	my_assigned = 0
	execution_deals: set[str] = set()
	deal_names = _tender_deal_names(company)
	trend_events: list[dict] = []
	portfolio_intakes: dict[str, dict] = {}
	for deal in deal_names:
		if not frappe.has_permission("CRM Deal", "read", doc=deal):
			continue
		intake = _read_intake(deal)
		if acquisition_scope == "assigned" and (intake.get("assigned_to") or "") != user:
			continue
		portfolio_intakes[deal] = intake
		if execution_scope == "assigned":
			execution_deals.add(deal)
		creation = frappe.db.get_value("CRM Deal", deal, "creation")
		event_dates = _tender_event_dates(intake, creation)
		verified = _has_submission_evidence(intake)
		if verified:
			trend_events.append(
				{
					"submitted_at": event_dates["submitted"],
					"result": intake.get("result"),
					"result_at": event_dates["won"],
					"value": intake.get("won_price"),
				}
			)
		if acquisition_scope == "none":
			continue
		identified_in_period = _in_dashboard_period(event_dates["identified"], start, end)
		if identified_in_period:
			acquisition["identified"] += 1
		decision = intake.get("go_no_go")
		if decision in ("go", "no_go") and _in_dashboard_period(event_dates[decision], start, end):
			acquisition[decision] += 1
		if _in_dashboard_period(event_dates["ready"], start, end):
			acquisition["ready"] += 1
		result = intake.get("result")
		if verified and _in_dashboard_period(event_dates["submitted"], start, end):
			acquisition["submitted"] += 1
		if (
			verified
			and result in ("won", "lost", "pending")
			and _in_dashboard_period(event_dates[result], start, end)
		):
			acquisition[result] += 1
		elif result and not verified and _in_dashboard_period(event_dates["unverified_history"], start, end):
			acquisition["unverified_history"] += 1
		if (intake.get("assigned_to") or "") == user and _in_dashboard_period(
			event_dates["assigned"], start, end
		):
			my_assigned += 1
		if any(_in_dashboard_period(value, start, end) for value in event_dates.values()):
			for item in _intake_attention(deal, intake, today_d):
				item["label"] = _deal_label(deal)
				attention.append(item)

	po_fields = [
		"name",
		"custom_crm_deal",
		"transaction_date",
		"schedule_date",
		"per_received",
		"per_billed",
		"status",
		"base_grand_total",
	]
	has_landed = frappe.db.has_column("Purchase Order", "custom_landed_charges")
	if has_landed:
		po_fields.append("custom_landed_charges")
	po_rows = []
	if frappe.db.has_column("Purchase Order", "custom_crm_deal"):
		po_rows = frappe.get_list(
			"Purchase Order",
			filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": ["<", 2]},
			fields=po_fields,
			limit_page_length=5000,
		)
	so_rows = []
	if frappe.db.has_column("Sales Order", "custom_crm_deal"):
		so_rows = frappe.get_list(
			"Sales Order",
			filters={"company": company, "custom_crm_deal": ["is", "set"], "docstatus": ["<", 2]},
			fields=[
				"name",
				"custom_crm_deal",
				"transaction_date",
				"delivery_date",
				"per_delivered",
				"per_billed",
				"status",
				"base_grand_total",
			],
			limit_page_length=5000,
		)
	execution = {
		"purchase_orders": 0,
		"purchase_receipts": 0,
		"purchase_invoices": 0,
		"received": 0,
		"receiving": 0,
		"customs_workload_open": 0,
		"sales_orders": 0,
		"sales_invoices": 0,
		"delivery_notes": 0,
		"delivered": 0,
		"delivery_pending": 0,
		# No native PO-level customs clearance field exists in this install. This
		# is workload evidence from planned landed customs charges, not clearance.
		"customs_proxy": {
			"basis": "planned_landed_customs_charge_not_clearance",
			"po_received_with_customs_charge": 0,
			"po_open_with_customs_charge": 0,
			"po_without_customs_charge": 0,
		},
		"logistics_status": {},
		"invoice_status": {
			"purchase_invoices": {"draft": 0, "submitted": 0, "unpaid": 0},
			"sales_invoices": {"draft": 0, "submitted": 0, "unpaid": 0},
		},
	}
	procurement_total = 0.0
	contract_total = 0.0
	for po in po_rows:
		if (
			execution_scope == "assigned" and po.custom_crm_deal not in execution_deals
		) or not _in_dashboard_period(po.transaction_date, start, end):
			continue
		if not frappe.has_permission("Purchase Order", "read", doc=po.name):
			continue
		execution["purchase_orders"] += 1
		procurement_total += flt(po.base_grand_total)
		logistics_status = str(po.status or "unknown")
		execution["logistics_status"][logistics_status] = (
			execution["logistics_status"].get(logistics_status, 0) + 1
		)
		charges = _parse_landed(po.get("custom_landed_charges") if has_landed else None)
		has_customs = any(charge["type"] == "customs" for charge in charges)
		received = flt(po.per_received) >= 100
		if received:
			execution["received"] += 1
			execution["customs_proxy"][
				"po_received_with_customs_charge" if has_customs else "po_without_customs_charge"
			] += 1
		else:
			execution["receiving"] += 1
			if has_customs:
				execution["customs_workload_open"] += 1
				execution["customs_proxy"]["po_open_with_customs_charge"] += 1
			else:
				execution["customs_proxy"]["po_without_customs_charge"] += 1
	for so in so_rows:
		if (
			execution_scope == "assigned" and so.custom_crm_deal not in execution_deals
		) or not _in_dashboard_period(so.transaction_date, start, end):
			continue
		if so.status in ("Closed", "Cancelled"):
			continue
		if not frappe.has_permission("Sales Order", "read", doc=so.name):
			continue
		execution["sales_orders"] += 1
		contract_total += flt(so.base_grand_total)
		if flt(so.per_delivered) >= 100:
			execution["delivered"] += 1
		else:
			execution["delivery_pending"] += 1

	po_by_deal: dict[str, list] = {}
	for po in po_rows:
		if po.custom_crm_deal not in portfolio_intakes:
			continue
		if frappe.has_permission("Purchase Order", "read", doc=po.name):
			po_by_deal.setdefault(po.custom_crm_deal, []).append(po)
	so_by_deal: dict[str, list] = {}
	for so in so_rows:
		if so.custom_crm_deal not in portfolio_intakes:
			continue
		if frappe.has_permission("Sales Order", "read", doc=so.name):
			so_by_deal.setdefault(so.custom_crm_deal, []).append(so)
	portfolio_preview = []
	for deal, intake in portfolio_intakes.items():
		deal_pos = po_by_deal.get(deal, [])
		deal_sos = so_by_deal.get(deal, [])
		portfolio_procurement_total = sum(flt(row.base_grand_total) for row in deal_pos)
		portfolio_contract_total = sum(flt(row.base_grand_total) for row in deal_sos)
		deadlines = _portfolio_deadlines(intake, deal_pos, deal_sos, today_d)
		portfolio_preview.append(
			{
				"deal": deal,
				"label": _deal_label(deal),
				"lot_no": intake.get("lot_no") or "",
				"status": intake.get("result") if _has_submission_evidence(intake) else "",
				"risk": deadlines["risk"],
				"po_received_pct": _weighted_progress(deal_pos, "per_received"),
				"po_billed_pct": _weighted_progress(deal_pos, "per_billed"),
				"so_delivered_pct": _weighted_progress(deal_sos, "per_delivered"),
				"so_billed_pct": _weighted_progress(deal_sos, "per_billed"),
				"procurement_total": portfolio_procurement_total,
				"contract_total": portfolio_contract_total,
				"spread": portfolio_contract_total - portfolio_procurement_total,
			}
		)

	invoice_deals = execution_deals if execution_scope == "assigned" else set(portfolio_intakes)
	purchase_order_names = [
		po.name
		for po in po_rows
		if po.custom_crm_deal in invoice_deals
		and frappe.has_permission("Purchase Order", "read", doc=po.name)
	]
	sales_order_names = [
		so.name
		for so in so_rows
		if so.custom_crm_deal in invoice_deals and frappe.has_permission("Sales Order", "read", doc=so.name)
	]
	execution["invoice_status"]["purchase_invoices"] = _invoice_status_counts(
		purchase_order_names,
		parent_doctype="Purchase Invoice",
		item_doctype="Purchase Invoice Item",
		order_link_field="purchase_order",
		company=company,
		start=start,
		end=end,
	)
	execution["invoice_status"]["sales_invoices"] = _invoice_status_counts(
		sales_order_names,
		parent_doctype="Sales Invoice",
		item_doctype="Sales Invoice Item",
		order_link_field="sales_order",
		company=company,
		start=start,
		end=end,
	)
	execution["purchase_receipts"] = _linked_document_count(
		purchase_order_names,
		parent_doctype="Purchase Receipt",
		item_doctype="Purchase Receipt Item",
		order_link_field="purchase_order",
		company=company,
		start=start,
		end=end,
	)
	execution["delivery_notes"] = _linked_document_count(
		sales_order_names,
		parent_doctype="Delivery Note",
		item_doctype="Delivery Note Item",
		order_link_field="against_sales_order",
		company=company,
		start=start,
		end=end,
	)
	execution["purchase_invoices"] = sum(
		execution["invoice_status"]["purchase_invoices"].values()
	)
	execution["sales_invoices"] = sum(
		execution["invoice_status"]["sales_invoices"].values()
	)

	attention.sort(key=lambda item: (0 if item["severity"] == "risk" else 1, item.get("days_left", 9999)))
	out = {
		"period": {"from_date": str(start), "to_date": str(end)},
		"trend_period": {"from_date": str(trend_start), "to_date": str(trend_end)},
		"role_scope": {
			"views": views,
			"oversight": oversight,
			"acquisition_scope": acquisition_scope,
			"execution_scope": execution_scope,
			"can_view_finance": can_view_finance,
		},
		"acquisition": acquisition,
		"execution": execution,
		"trend": _monthly_trend(trend_events, trend_start, trend_end),
		"portfolio_preview": portfolio_preview,
		"attention": {"count": len(attention), "items": attention[:100]},
		"my_work": {
			"assigned": my_assigned,
			"customs_workload_open": execution["customs_workload_open"] if "declarant" in views else 0,
			"delivery_pending": execution["delivery_pending"] if "logist" in views else 0,
		},
	}
	out.update(_dashboard_executive_payload(company, set(views)))
	if out["executive_kpi"] is not None:
		period_decisions = acquisition["won"] + acquisition["lost"]
		out["executive_kpi"]["win_rate"] = (
			round(acquisition["won"] / period_decisions * 100, 1) if period_decisions else 0
		)
	if can_view_finance:
		out["finance"] = {
			"currency": frappe.db.get_value("Company", company, "default_currency") or "",
			"procurement_total": procurement_total,
			"contract_total": contract_total,
			"execution_spread": contract_total - procurement_total,
		}
	return out
