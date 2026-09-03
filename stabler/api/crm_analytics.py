"""Manager Cockpit Analytics & Pipeline Intelligence API.

Computes weighted forecast, commit/best-case totals, stage aging (average days),
stage counts, rep workload, and win/loss conversion rates.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from stabler.api.crm import _require_crm, _require_crm_company
from stabler.api.organization import _ADMIN_ROLES
from stabler.api.tender_dimension import exclude_overhead_deals

_CRM_MANAGER_ROLES = frozenset((*_ADMIN_ROLES, "Sales Manager", "CRM Specialist"))


def _require_crm_manager(company: str) -> None:
	"""Verify caller has CRM module access, company scoping, and CRM Manager/Admin role."""
	_require_crm()
	_require_crm_company(company)

	user_roles = frappe.get_roles(frappe.session.user)
	if not any(role in user_roles for role in _CRM_MANAGER_ROLES):
		frappe.throw(
			_("Not permitted. CRM Manager role required."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def get_manager_cockpit_metrics(company: str, owner: str | None = None) -> dict:
	"""Compute drillable manager cockpit KPIs for a company."""
	_require_crm_manager(company)

	today = getdate(nowdate())
	filters = {"company": company}
	if owner:
		filters["owner"] = owner
	# ADR-609: the cockpit steers on these numbers, so it must count the same
	# deals the boards show — the GENEL GİDER bucket is not one of them.
	exclude_overhead_deals(filters)

	deals = frappe.get_list(
		"CRM Deal",
		filters=filters,
		fields=[
			"name",
			"organization",
			"stage",
			"contract_value",
			"probability",
			"owner",
			"creation",
			"modified",
			"last_activity_date",
		],
		limit_page_length=500,
	)

	total_value = 0.0
	weighted_forecast = 0.0
	commit_total = 0.0
	best_case_total = 0.0

	stage_counts: dict[str, int] = {}
	stage_age_sum: dict[str, float] = {}
	rep_workload: dict[str, int] = {}

	won_count = 0
	lost_count = 0

	for d in deals:
		val = flt(d.get("contract_value"))
		prob = flt(d.get("probability", 50.0))
		stage = (d.get("stage") or "seen").lower()
		rep = d.get("owner") or "Unassigned"

		# Determine reference date for stage age (modified, last_activity_date, or creation)
		ref_date_str = d.get("modified") or d.get("last_activity_date") or d.get("creation")
		age_days = max(0, date_diff(today, getdate(ref_date_str))) if ref_date_str else 0

		stage_counts[stage] = stage_counts.get(stage, 0) + 1
		stage_age_sum[stage] = stage_age_sum.get(stage, 0.0) + age_days
		rep_workload[rep] = rep_workload.get(rep, 0) + 1

		if stage in ("won", "awarded"):
			won_count += 1
			commit_total += val
			best_case_total += val
			total_value += val
		elif stage in ("lost", "cancelled"):
			lost_count += 1
		else:
			# Active pipeline deal
			total_value += val
			weighted_forecast += val * (prob / 100.0)

			if prob >= 70.0 or stage == "commit":
				commit_total += val
			if prob >= 40.0 or stage in ("commit", "best_case"):
				best_case_total += val

	total_decided = won_count + lost_count
	win_rate = (won_count / total_decided * 100.0) if total_decided > 0 else 0.0

	# Calculate average stage aging in days
	stage_aging = {st: round(stage_age_sum[st] / count, 1) for st, count in stage_counts.items() if count > 0}

	return {
		"company": company,
		"deal_count": len(deals),
		"total_value": total_value,
		"weighted_forecast": weighted_forecast,
		"commit_total": commit_total,
		"best_case_total": best_case_total,
		"win_rate_pct": round(win_rate, 1),
		"stage_counts": stage_counts,
		"stage_aging": stage_aging,
		"rep_workload": rep_workload,
	}
