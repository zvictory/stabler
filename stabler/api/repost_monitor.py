"""Repost Item Valuation monitor (admin).

ERPNext reposts stock valuation in the background after a stock/valuation doc is
cancelled or amended. The reposts run sequentially — a single one stuck
"In Progress" (dead worker) blocks every later one, silently freezing valuation
corrections. This surfaces the queue health in the SPA and lets an admin
re-queue stuck reposts or kick the processor, instead of needing bench access.
"""

from __future__ import annotations

import frappe
from frappe.utils import time_diff_in_seconds

from stabler.api.organization import _require_admin

_RIV = "Repost Item Valuation"


@frappe.whitelist()
def repost_status() -> dict:
	"""Queue health: counts by status, oldest queued, stuck + errored reposts."""
	_require_admin()
	counts = {
		row[0]: row[1]
		for row in frappe.db.sql("select status, count(*) from `tab%s` group by status" % _RIV)
	}
	oldest_queued = frappe.db.get_value(
		_RIV, {"status": "Queued"}, "creation", order_by="creation asc"
	)
	in_progress = frappe.get_all(
		_RIV,
		filters={"status": "In Progress"},
		fields=["name", "voucher_type", "voucher_no", "modified", "creation"],
		order_by="creation asc",
	)
	now = frappe.utils.now_datetime()
	for r in in_progress:
		r["stuck_minutes"] = round(time_diff_in_seconds(now, r["modified"]) / 60)
	has_err = frappe.db.has_column(_RIV, "error_log")
	err_fields = ["name", "voucher_type", "voucher_no", "modified"] + (["error_log"] if has_err else [])
	errors = frappe.get_all(
		_RIV,
		filters={"status": ["in", ["Failed", "Error"]]},
		fields=err_fields,
		order_by="modified desc",
		limit_page_length=20,
	)
	return {
		"counts": counts,
		"queued": int(counts.get("Queued", 0)),
		"in_progress": in_progress,
		"errors": errors,
		"oldest_queued": str(oldest_queued or ""),
	}


@frappe.whitelist()
def repost_run_now() -> dict:
	"""Kick the repost processor in the background (non-blocking)."""
	_require_admin()
	frappe.enqueue(
		"erpnext.stock.doctype.repost_item_valuation.repost_item_valuation.repost_entries",
		queue="long",
		job_name="stabler_manual_repost",
		enqueue_after_commit=True,
	)
	return {"queued": True}


@frappe.whitelist()
def repost_reset_stuck(minutes: int = 30) -> dict:
	"""Re-queue reposts stuck 'In Progress' longer than `minutes` (dead worker)."""
	_require_admin()
	minutes = max(int(minutes or 30), 5)
	now = frappe.utils.now_datetime()
	reset = []
	for r in frappe.get_all(_RIV, filters={"status": "In Progress"}, fields=["name", "modified"]):
		if time_diff_in_seconds(now, r["modified"]) / 60 >= minutes:
			frappe.db.set_value(_RIV, r["name"], {"status": "Queued", "current_index": 0}, update_modified=False)
			reset.append(r["name"])
	return {"reset": reset, "count": len(reset)}
