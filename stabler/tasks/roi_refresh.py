"""Daily Campaign ROI snapshot refresh.

For each Active PromoPlan whose date window covers today, compute the day's
ROI snapshot. Upsert one row per (promo_plan, today) into
`Campaign ROI Snapshot` — re-running on the same day is idempotent.

Definitions (kept intentionally simple — Phase 3.3):
- units_sold = sum of submitted Sales Invoice Item.qty for the plan's
  trigger_item between plan.start_date..today.
- baseline_weekly = median of weekly trigger_item qty totals across the
  8 weeks prior to start_date.
- weeks_elapsed = max(1, days_since_start / 7) — fractional, capped at total.
- incremental_units = units_sold - (weeks_elapsed * baseline_weekly).
- uplift_value = incremental_units * Item.standard_rate.
- cost_to_serve = plan.budget * (weeks_elapsed / total_weeks).
- gross_roi_pct = uplift_value / cost_to_serve * 100 (0 if no cost).
- net_roi_pct = (uplift_value - cost_to_serve) / cost_to_serve * 100.

Run on-demand:
    bench --site stabler execute stabler.tasks.roi_refresh.daily

Registered in hooks.py under scheduler_events.daily.
"""

from __future__ import annotations

import datetime
import statistics
from typing import Any

import frappe
from frappe.utils import flt, getdate


def _sum_qty(item_code: str, start: datetime.date, end: datetime.date) -> float:
	"""Total submitted Sales Invoice Item qty for `item_code` in [start, end]."""
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(sii.qty), 0) AS qty
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1
		  AND sii.item_code = %(item)s
		  AND si.posting_date BETWEEN %(start)s AND %(end)s
		""",
		{"item": item_code, "start": start, "end": end},
		as_dict=True,
	)
	return float(rows[0]["qty"] or 0) if rows else 0.0


def _median_weekly_baseline(item_code: str, start_date: datetime.date) -> float:
	"""Median weekly qty across the 8 weeks before `start_date`."""
	weekly: list[float] = []
	for i in range(8):
		week_end = start_date - datetime.timedelta(days=1 + i * 7)
		week_start = week_end - datetime.timedelta(days=6)
		qty = _sum_qty(item_code, week_start, week_end)
		weekly.append(qty)
	if not weekly:
		return 0.0
	return float(statistics.median(weekly))


def _item_rate(item_code: str) -> float:
	rate = frappe.db.get_value("Item", item_code, "standard_rate")
	try:
		return float(rate or 0)
	except TypeError, ValueError:
		return 0.0


def _compute_snapshot(plan: dict, today: datetime.date) -> dict[str, Any]:
	start = getdate(plan["start_date"])
	end = getdate(plan["end_date"])
	trigger_item = plan.get("trigger_item")
	budget = flt(plan.get("budget") or 0)

	total_days = max(1, (end - start).days + 1)
	total_weeks = total_days / 7.0
	elapsed_days = max(0, (today - start).days + 1)
	elapsed_days = min(elapsed_days, total_days)
	weeks_elapsed = elapsed_days / 7.0

	units_sold = 0.0
	baseline_weekly = 0.0
	if trigger_item:
		units_sold = _sum_qty(trigger_item, start, today)
		baseline_weekly = _median_weekly_baseline(trigger_item, start)

	expected_baseline_units = weeks_elapsed * baseline_weekly
	incremental_units = units_sold - expected_baseline_units

	rate = _item_rate(trigger_item) if trigger_item else 0.0
	uplift_value = incremental_units * rate

	cost_to_serve = budget * (weeks_elapsed / total_weeks) if total_weeks else 0.0

	if cost_to_serve:
		gross_roi_pct = (uplift_value / cost_to_serve) * 100.0
		net_roi_pct = ((uplift_value - cost_to_serve) / cost_to_serve) * 100.0
	else:
		gross_roi_pct = 0.0
		net_roi_pct = 0.0

	return {
		"units_sold": round(units_sold),
		"incremental_units": round(incremental_units),
		"uplift_value": uplift_value,
		"cost_to_serve": cost_to_serve,
		"gross_roi_pct": gross_roi_pct,
		"net_roi_pct": net_roi_pct,
	}


def _upsert_snapshot(plan_name: str, snapshot_date: datetime.date, metrics: dict[str, Any]) -> str:
	existing = frappe.db.get_value(
		"Campaign ROI Snapshot",
		{"promo_plan": plan_name, "snapshot_date": snapshot_date},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Campaign ROI Snapshot", existing)
		for key, value in metrics.items():
			doc.set(key, value)
		doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.get_doc(
		{
			"doctype": "Campaign ROI Snapshot",
			"promo_plan": plan_name,
			"snapshot_date": snapshot_date,
			**metrics,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def daily() -> dict[str, Any]:
	"""Entry point. Returns a summary dict for logs."""
	if not frappe.db.exists("DocType", "Promo Plan"):
		return {"status": "skipped", "reason": "Promo Plan doctype missing"}
	if not frappe.db.exists("DocType", "Campaign ROI Snapshot"):
		return {"status": "skipped", "reason": "Campaign ROI Snapshot doctype missing"}

	today = datetime.date.today()
	plans = frappe.get_all(
		"Promo Plan",
		filters={
			"status": "Active",
			"start_date": ["<=", today],
			"end_date": [">=", today],
		},
		fields=["name", "start_date", "end_date", "budget", "trigger_item"],
	)

	updated: list[str] = []
	errors: list[dict[str, str]] = []
	for plan in plans:
		try:
			metrics = _compute_snapshot(plan, today)
			snap_name = _upsert_snapshot(plan["name"], today, metrics)
			updated.append(snap_name)
		except Exception as exc:
			frappe.log_error(frappe.get_traceback(), f"roi_refresh:{plan['name']}")
			errors.append({"plan": plan["name"], "error": str(exc)})

	frappe.db.commit()
	summary = {
		"status": "ok",
		"date": today.isoformat(),
		"plans_processed": len(plans),
		"snapshots_upserted": updated,
		"errors": errors,
	}
	print(f"[stabler.tasks.roi_refresh] {summary}")
	return summary
