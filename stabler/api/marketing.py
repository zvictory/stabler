"""Marketing API for Stabler.

Phase 3 endpoints: Promo Plan, Campaign ROI Snapshot, Marketing Claim.

Role gating:
- Write endpoints require "Marketing User" or "System Manager".
- Read endpoints filter by `_company_filter` from sfa.py.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from stabler.api.sfa import _company_filter, _is_admin


_WRITE_ROLES = {"System Manager", "Marketing User"}
_CLAIM_DECISIONS = {"UnderReview", "Approved", "Rejected"}


def _require_write_marketing() -> None:
	roles = set(frappe.get_roles())
	if not roles & _WRITE_ROLES:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Promo Plans
# ---------------------------------------------------------------------------

_PROMO_PLAN_FIELDS = [
	"name",
	"campaign_name",
	"company",
	"plan_type",
	"channel",
	"status",
	"budget",
	"start_date",
	"end_date",
	"linked_promo_scheme",
	"trigger_item",
	"notes",
]


@frappe.whitelist()
def list_promo_plans(
	filters: dict | str | None = None,
	limit: int = 100,
) -> list[dict]:
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}
	filters = dict(filters or {})

	company = filters.pop("company", None)
	search = filters.pop("search", None)
	resolved: dict = _company_filter(company)
	for key in ("plan_type", "channel", "status"):
		val = filters.pop(key, None)
		if val:
			resolved[key] = val

	or_filters = None
	if search:
		needle = f"%{search}%"
		or_filters = [
			["campaign_name", "like", needle],
			["name", "like", needle],
		]

	return frappe.get_all(
		"Promo Plan",
		filters=resolved,
		or_filters=or_filters,
		fields=_PROMO_PLAN_FIELDS,
		order_by="start_date desc, creation desc",
		limit=max(1, min(int(limit or 100), 1000)),
	)


@frappe.whitelist()
def get_promo_plan(name: str) -> dict:
	if not name:
		frappe.throw(_("Promo Plan name is required."))
	if not frappe.db.exists("Promo Plan", name):
		frappe.throw(_("Promo Plan {0} not found.").format(name))
	doc = frappe.get_doc("Promo Plan", name)
	_company_filter(doc.company)
	return doc.as_dict()


@frappe.whitelist()
def create_promo_plan(payload: dict | str) -> dict:
	_require_write_marketing()
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	for key in ("campaign_name", "company", "plan_type", "start_date", "end_date"):
		if not payload.get(key):
			frappe.throw(_("{0} is required.").format(key))
	_company_filter(payload["company"])

	doc = frappe.get_doc({"doctype": "Promo Plan", **payload})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def update_promo_plan_status(name: str, status: str) -> dict:
	_require_write_marketing()
	if not name:
		frappe.throw(_("Promo Plan name is required."))
	if status not in ("Draft", "Active", "Closed"):
		frappe.throw(_("Invalid status: {0}").format(status))
	if not frappe.db.exists("Promo Plan", name):
		frappe.throw(_("Promo Plan {0} not found.").format(name))
	doc = frappe.get_doc("Promo Plan", name)
	_company_filter(doc.company)
	doc.status = status
	doc.save()
	return doc.as_dict()


# ---------------------------------------------------------------------------
# Campaign ROI Snapshots
# ---------------------------------------------------------------------------

_ROI_FIELDS = [
	"name",
	"promo_plan",
	"snapshot_date",
	"units_sold",
	"incremental_units",
	"uplift_value",
	"cost_to_serve",
	"gross_roi_pct",
	"net_roi_pct",
]


@frappe.whitelist()
def list_roi_snapshots(
	promo_plan: str | None = None,
	limit: int = 200,
) -> list[dict]:
	filters: dict = {}
	if promo_plan:
		filters["promo_plan"] = promo_plan

	# Constrain to plans the user can see (company scope).
	allowed = _company_filter(None)
	if allowed:
		visible_plans = frappe.get_all(
			"Promo Plan",
			filters=allowed,
			pluck="name",
			limit=10_000,
		)
		if promo_plan and promo_plan not in visible_plans and not _is_admin():
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		if not promo_plan:
			if not visible_plans:
				return []
			filters["promo_plan"] = ["in", visible_plans]

	return frappe.get_all(
		"Campaign ROI Snapshot",
		filters=filters,
		fields=_ROI_FIELDS,
		order_by="snapshot_date desc, creation desc",
		limit=max(1, min(int(limit or 200), 1000)),
	)


# ---------------------------------------------------------------------------
# Marketing Claims
# ---------------------------------------------------------------------------

_CLAIM_FIELDS = [
	"name",
	"promo_plan",
	"distributor",
	"claim_amount",
	"status",
	"documents",
	"reviewer_notes",
	"settled_payment_entry",
	"creation",
]


@frappe.whitelist()
def list_claims(filters: dict | str | None = None) -> list[dict]:
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}
	filters = dict(filters or {})

	resolved: dict = {}
	for key in ("promo_plan", "distributor", "status"):
		val = filters.pop(key, None)
		if val:
			resolved[key] = val

	return frappe.get_all(
		"Marketing Claim",
		filters=resolved,
		fields=_CLAIM_FIELDS,
		order_by="creation desc",
		limit=500,
	)


@frappe.whitelist()
def get_claim(name: str) -> dict:
	if not name:
		frappe.throw(_("Claim name is required."))
	if not frappe.db.exists("Marketing Claim", name):
		frappe.throw(_("Claim {0} not found.").format(name))
	return frappe.get_doc("Marketing Claim", name).as_dict()


@frappe.whitelist()
def submit_claim(
	promo_plan: str,
	distributor: str,
	claim_amount: float | str,
	documents: str | None = None,
) -> dict:
	_require_write_marketing()
	if not promo_plan or not frappe.db.exists("Promo Plan", promo_plan):
		frappe.throw(_("Valid Promo Plan is required."))
	if not distributor or not frappe.db.exists("Customer", distributor):
		frappe.throw(_("Valid Distributor (Customer) is required."))
	amount = flt(claim_amount)
	if amount <= 0:
		frappe.throw(_("Claim amount must be greater than zero."))

	doc = frappe.get_doc(
		{
			"doctype": "Marketing Claim",
			"promo_plan": promo_plan,
			"distributor": distributor,
			"claim_amount": amount,
			"documents": documents,
			"status": "Submitted",
		}
	)
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def review_claim(name: str, decision: str, reviewer_notes: str | None = None) -> dict:
	_require_write_marketing()
	if not name or not frappe.db.exists("Marketing Claim", name):
		frappe.throw(_("Claim {0} not found.").format(name))
	if decision not in _CLAIM_DECISIONS:
		frappe.throw(_("Invalid decision: {0}").format(decision))

	doc = frappe.get_doc("Marketing Claim", name)
	if doc.status in ("Paid", "Rejected") and decision != doc.status:
		frappe.throw(_("Claim is already {0} and cannot be re-reviewed.").format(doc.status))

	doc.status = decision
	if reviewer_notes is not None:
		doc.reviewer_notes = reviewer_notes
	doc.save()
	return doc.as_dict()


def _resolve_party_account(company: str, customer: str) -> str:
	"""Pick a receivable Account for the party. Throw clearly if missing."""
	from erpnext.accounts.party import get_party_account  # type: ignore[import-not-found]

	try:
		account = get_party_account("Customer", customer, company)
	except Exception as exc:  # noqa: BLE001
		frappe.throw(
			_("No receivable account configured for distributor {0} in company {1}: {2}").format(
				customer, company, exc
			)
		)
	if not account:
		frappe.throw(
			_("No receivable account configured for distributor {0} in company {1}.").format(
				customer, company
			)
		)
	return account


def _default_payment_account(company: str) -> str:
	"""Pick the company's default bank/cash account for outgoing payment."""
	account = frappe.db.get_value("Company", company, "default_bank_account")
	if not account:
		account = frappe.db.get_value("Company", company, "default_cash_account")
	if not account:
		# Fall back to any Bank account for the company.
		account = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Bank", "is_group": 0},
			"name",
		)
	if not account:
		frappe.throw(
			_("No default Bank or Cash account configured for company {0}.").format(company)
		)
	return account


@frappe.whitelist()
def settle_claim(name: str) -> dict:
	_require_write_marketing()
	if not name or not frappe.db.exists("Marketing Claim", name):
		frappe.throw(_("Claim {0} not found.").format(name))

	doc = frappe.get_doc("Marketing Claim", name)
	if doc.status != "Approved":
		frappe.throw(_("Only Approved claims can be settled. Current status: {0}").format(doc.status))
	if doc.settled_payment_entry:
		frappe.throw(_("Claim is already settled by {0}.").format(doc.settled_payment_entry))

	plan_company = frappe.db.get_value("Promo Plan", doc.promo_plan, "company")
	if not plan_company:
		frappe.throw(_("Promo Plan {0} has no company.").format(doc.promo_plan))

	party_account = _resolve_party_account(plan_company, doc.distributor)
	paid_from = _default_payment_account(plan_company)
	company_currency = frappe.db.get_value("Company", plan_company, "default_currency")

	pe = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Pay",
			"party_type": "Customer",
			"party": doc.distributor,
			"company": plan_company,
			"posting_date": nowdate(),
			"paid_amount": flt(doc.claim_amount),
			"received_amount": flt(doc.claim_amount),
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
			"paid_from": paid_from,
			"paid_from_account_currency": company_currency,
			"paid_to": party_account,
			"paid_to_account_currency": company_currency,
			"reference_no": doc.name,
			"reference_date": nowdate(),
			"remarks": _("Marketing claim settlement for {0}").format(doc.name),
		}
	)
	pe.insert(ignore_permissions=True)
	pe.submit()

	doc.settled_payment_entry = pe.name
	doc.status = "Paid"
	doc.save(ignore_permissions=True)
	return doc.as_dict()
