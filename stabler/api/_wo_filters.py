"""Where-clause for the Work Order shift log. No frappe import on purpose.

`list_work_orders` used to build its conditions inline. That was fine while
there were two of them; the shift log needs five, and the risk changes shape
with the count. A filter that matches nothing is a visible bug — the screen goes
empty and somebody says so. A filter that accidentally *widens* the query is
not: the tenant guard or an operator's own-rows guard goes missing, the list
gets longer, and a longer list on a busy screen reads as a good day.

So the clause is assembled here, where it can be asserted on without a database,
and `test_wo_shift_log_filters` pins both directions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

WO_STATUSES = (
	"Draft",
	"Not Started",
	"In Process",
	"Completed",
	"Stopped",
	"Closed",
	"Cancelled",
)

# Both roles work the same order (see `_WO_OPERATOR_FIELDS` in manufacturing.py).
# Kept as a literal here rather than imported: this module must stay frappe-free,
# and `test_wo_operator_roles` already fails if the two lists drift apart.
_OPERATOR_COLUMNS = ("operator", "packaging_operator")


def _clean(value) -> str:
	return str(value).strip() if value is not None else ""


def _day_after(value: str) -> str:
	"""The exclusive upper bound for an inclusive end date.

	`planned_start_date` is a datetime. `<= '2026-08-28'` compares against
	midnight, so an order planned for 09:00 that morning falls outside a range
	whose end the user typed as that very day — the shift lead asks for today
	and is told there is nothing on. Comparing to the next midnight, exclusive,
	is the fix that does not depend on how the column is stored.
	"""
	parsed = datetime.strptime(value[:10], "%Y-%m-%d").date()
	return str(parsed + timedelta(days=1))


def build_work_order_filters(
	company: str,
	status: str | None = None,
	search: str | None = "",
	line: str | None = None,
	operator: str | None = None,
	from_date: str | date | None = None,
	to_date: str | date | None = None,
	assignee_user: str | None = None,
	assignee_columns: tuple[str, ...] | None = None,
) -> tuple[list[str], dict]:
	"""Return (conditions, params) for a `tabWork Order` query.

	`assignee_user` is the own-rows guard, not a filter: pass it for a caller
	who is not a manufacturing manager, and it is ANDed with everything else so
	no filter can be used to reach past it.
	"""
	conds = ["company = %(company)s"]
	params: dict = {"company": company}

	status = _clean(status)
	if status in WO_STATUSES:
		conds.append("status = %(status)s")
		params["status"] = status

	search = _clean(search)
	if search:
		conds.append("(name LIKE %(s)s OR production_item LIKE %(s)s OR item_name LIKE %(s)s)")
		params["s"] = f"%{search}%"

	# The line. `wip_warehouse`, because there are no Workstation records to key
	# on — measured 0 on anjan, 2026-08-28, across 3 795 orders.
	line = _clean(line)
	if line:
		conds.append("wip_warehouse = %(line)s")
		params["line"] = line

	operator = _clean(operator)
	if operator:
		conds.append("(" + " OR ".join(f"`{col}` = %(operator)s" for col in _OPERATOR_COLUMNS) + ")")
		params["operator"] = operator

	from_date = _clean(from_date)
	if from_date:
		conds.append("planned_start_date >= %(from_date)s")
		params["from_date"] = from_date

	to_date = _clean(to_date)
	if to_date:
		conds.append("planned_start_date < %(to_date_end)s")
		params["to_date_end"] = _day_after(to_date)

	if assignee_user:
		columns = assignee_columns or _OPERATOR_COLUMNS
		conds.append("(" + " OR ".join(f"`{col}` = %(assignee)s" for col in columns) + ")")
		params["assignee"] = assignee_user

	return conds, params
