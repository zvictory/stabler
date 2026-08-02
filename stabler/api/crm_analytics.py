"""Manager Cockpit Analytics & Pipeline Intelligence API.

Computes weighted forecast, commit/best-case, stage aging,
rep workload, and win/loss conversion rates.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from stabler.api.sourcing import _assert_company_scope


@frappe.whitelist()
def get_manager_cockpit_metrics(company: str, owner: str | None = None) -> dict:
	"""Compute drillable manager cockpit KPIs for a company."""
	_assert_company_scope(company)

	filters = {"company": company}
	if owner:
		filters["owner"] = owner

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
		],
		limit_page_length=500,
	)

	total_value = 0.0
	weighted_forecast = 0.0
	commit_total = 0.0
	best_case_total = 0.0
	stage_aging: dict[str, int] = {}
	rep_workload: dict[str, int] = {}
	won_count = 0
	lost_count = 0

	for d in deals:
		val = flt(d.get("contract_value"))
		prob = flt(d.get("probability", 50.0))
		stage = d.get("stage", "seen")
		rep = d.get("owner") or "Unassigned"

		total_value += val
		weighted_forecast += val * (prob / 100.0)

		if stage in ("won", "awarded"):
			commit_total += val
			won_count += 1
		elif stage in ("lost", "cancelled"):
			lost_count += 1
		else:
			if prob >= 70.0:
				commit_total += val * (prob / 100.0)
			best_case_total += val * (prob / 100.0)

		stage_aging[stage] = stage_aging.get(stage, 0) + 1
		rep_workload[rep] = rep_workload.get(rep, 0) + 1

	total_decided = won_count + lost_count
	win_rate = (won_count / total_decided * 100.0) if total_decided > 0 else 0.0

	return {
		"company": company,
		"deal_count": len(deals),
		"total_value": total_value,
		"weighted_forecast": weighted_forecast,
		"commit_total": commit_total,
		"best_case_total": best_case_total,
		"win_rate_pct": round(win_rate, 1),
		"stage_aging": stage_aging,
		"rep_workload": rep_workload,
	}
