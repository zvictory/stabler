"""Whether a submitted Work Order should raise a Material Request. No frappe.

Measured on anjan 2026-08-28: the hook that calls this had never run. Its gate
was `planned_start_date >= tomorrow`, and 0 of 3 789 submitted orders are ever
planned for tomorrow — 3 619 are same-day, 170 backdated. So the function
returned before writing, once per order, for five and a half months, and
`Material Request.work_order` was set on 0 of 488 requests.
"""

from __future__ import annotations

from datetime import date, datetime


def _as_date(value) -> date | None:
	if value is None:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = str(value).strip()
	if not text:
		return None
	try:
		# The column is a datetime and every anjan row carries a time; the date
		# half is the whole question, so the rest is cut rather than parsed.
		return datetime.strptime(text[:10], "%Y-%m-%d").date()
	except ValueError:
		return None


def should_request_materials(planned_start_date, today) -> bool:
	"""True when the order runs today or later.

	Today is included because an order starting today with material missing from
	the line is the urgent case — the one the old gate skipped. Backdated orders
	are still excluded: they are catch-up entries typed after the work happened,
	and a transfer request for work already done is noise. A queue of noise is
	one nobody reads, which is worse than no queue.

	An unknown or unparseable date is not a reason to write.
	"""
	planned = _as_date(planned_start_date)
	if planned is None:
		return False
	reference = _as_date(today)
	if reference is None:
		return False
	return planned >= reference
