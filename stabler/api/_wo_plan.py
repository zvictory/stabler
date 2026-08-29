"""The line × day planning board's rules. No frappe import on purpose.

Three things this module deliberately does not do, each because a measurement
on anjan 2026-08-28 said the input for it does not exist:

* no duration — 0 of 3 789 orders carry a `planned_end_date`;
* no capacity or load — 0 submitted BOMs carry any `operating_cost`;
* no demand — 0 orders are linked to a Sales Order.

What is left is what somebody actually typed: which line, which day, how much.
`test_wo_plan_board` pins both the arithmetic and the three refusals.
"""

from __future__ import annotations

from datetime import date, datetime

# Work already finished. Its planned date is the record of when it ran, and the
# shift log's date filter reads that column and nothing else.
_FINISHED = ("Completed", "Closed", "Cancelled")


def _as_datetime(value) -> datetime | None:
	if isinstance(value, datetime):
		return value
	if isinstance(value, date):
		return datetime(value.year, value.month, value.day)
	text = str(value or "").strip()
	if not text:
		return None
	for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			continue
	return None


def _day_of(value) -> str:
	parsed = _as_datetime(value)
	return "" if parsed is None else parsed.strftime("%Y-%m-%d")


def may_reschedule(status: str) -> tuple[bool, str]:
	"""Whether this order's planned day may still be moved, and why not.

	The reason is returned rather than thrown because the board moves one order
	out of a screenful: a throw would abandon the gesture, while a named refusal
	can be shown on the row the planner just dragged.
	"""
	if str(status or "").strip() in _FINISHED:
		return False, "finished"
	return True, ""


def reschedule_target(current, new_date: str) -> str:
	"""The datetime to write when an order is moved to `new_date`.

	The clock is carried over, not reset. Orders on this site are opened between
	05:00 and 23:00 and the hour is the only record of which shift the work
	belongs to — and nothing would report its loss, because every screen that
	shows a planned date compares the date half.
	"""
	parsed = _as_datetime(current)
	time_part = "00:00:00" if parsed is None else parsed.strftime("%H:%M:%S")
	return f"{new_date} {time_part}"


class ScheduleRefused(ValueError):
	"""A typed start/end pair that must not be written.

	A named exception rather than a `(ok, reason)` tuple like `may_reschedule`:
	that one answers a question about an order the planner already dragged, and
	the gesture has to survive the answer. This one is about what they just typed
	into a form, where refusing IS the outcome and the message is the point.
	"""


def schedule_window(start, end):
	"""The `(planned_start_date, planned_end_date)` to write, or a refusal.

	This is design 1c's missing axis. Measured on anjan 2026-08-29: all 3 799
	orders carry a `planned_start_date`, but 3 464 of them (91%) sit within 60
	seconds of `creation` — ERPNext's default, the moment the form was opened,
	not a plan — and 0 carry a `planned_end_date`. Without a real pair there is
	no position and no width, and a grid drawn from the defaults charts data
	entry while looking exactly like a schedule.

	Both fields are `allow_on_submit`, and ERPNext recomputes `planned_end_date`
	only from an order's operations (`work_order.py:1045`). anjan holds 0 Work
	Order Operations, so a planner's hours are not overwritten behind their back.
	Re-measure that if hours ever start disappearing.
	"""
	first = _as_datetime(start)
	# Refused, never coerced to midnight: a bare date carries no hour, and the
	# hour is the entire point of typing this — coerced, it would put a night job
	# on the board that nobody planned.
	#
	# The test is the SHAPE of what was typed, not what it parsed to. The first
	# version of this guard compared the parsed value against the same string
	# truncated to ten characters, which made an explicitly typed `00:00`
	# indistinguishable from a date with no hour at all — and so refused the one
	# input the comment above promises to protect. A datetime handed in from the
	# database is already unambiguous and skips the check.
	typed = start if isinstance(start, (datetime, date)) else str(start or "")
	if first is None or (isinstance(typed, str) and ":" not in typed):
		raise ScheduleRefused("start")

	text = str(end or "").strip()
	if not text:
		# Blank means blank. "Keep whatever was there" would make a mistyped end
		# impossible to correct from the only screen that can set it.
		return first.strftime("%Y-%m-%d %H:%M:%S"), None

	last = _as_datetime(text)
	# Unreadable is NOT "no end": a typed end that vanished silently is a planner
	# watching their entry disappear with no idea why.
	if last is None:
		raise ScheduleRefused("end")
	# Not a shorter job — a typo. Written through it draws a bar of negative
	# width, and every duration computed from it is negative. Equal is refused
	# for a measured reason: `actual_end == actual_start` on 354 of 434 orders
	# finished in the last 30 days, and that zero is exactly what makes those
	# timestamps unusable. The planned pair must not inherit it. An overnight job
	# needs no special case — the end carries its own date.
	if last <= first:
		raise ScheduleRefused("order")

	return first.strftime("%Y-%m-%d %H:%M:%S"), last.strftime("%Y-%m-%d %H:%M:%S")


def build_plan_grid(orders, days, lines) -> dict:
	"""Place `orders` into a line × day grid, and hand back whatever did not fit.

	Every requested square exists even when empty: an absent cell and an empty
	one render identically and mean opposite things, and "this line has nothing
	on Saturday" is the answer the board was opened for.
	"""
	buckets: dict[tuple[str, str], list] = {(line, day): [] for line in lines for day in days}
	unscheduled = []

	for order in orders:
		key = (order.get("wip_warehouse") or "", _day_of(order.get("planned_start_date")))
		if key in buckets:
			buckets[key].append(order)
		else:
			# Not a filter: an order lands here because it has no planned day, or
			# runs on a line this board is not showing, or falls outside the
			# window. All three are work somebody scheduled, so all three come
			# back named instead of being swallowed by the grid.
			unscheduled.append(order)

	cells = [
		{
			"line": line,
			"day": day,
			"orders": buckets[(line, day)],
			"qty": sum(float(o.get("qty") or 0) for o in buckets[(line, day)]),
		}
		for line in lines
		for day in days
	]
	return {"lines": list(lines), "days": list(days), "cells": cells, "unscheduled": unscheduled}
