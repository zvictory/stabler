"""The line × day planning board: what it may place, move, and must not compute.

Measured on anjan 2026-08-28, read-only, before any of this was designed:

    submitted Work Orders                              3 789
    …opened for a day later than the day they were created      0
    …carrying a `planned_end_date`                              0
    submitted BOMs with any `operating_cost`                    0
    submitted Work Orders linked to a Sales Order               0
    `Version` rows that ever touched `planned_start_date`   38 / 8 906
    `wip_warehouse`.allow_on_submit                             0
    `planned_start_date`.allow_on_submit                        1

Read together those numbers decide the whole screen.

**No gantt bar.** An order has no end date and its BOM has no operating time, so
its duration is not merely unknown, it is unrecorded — a bar would have to pick a
width, and a picked width is a drawing of a number nobody entered.

**No capacity or utilisation.** Same reason, one step worse: "this line is 80 %
full" would be read as a measurement and acted on. The cell shows the order count
and the summed quantity, which are both things somebody actually typed.

**Days move, lines do not.** `planned_start_date` is writable after submit;
`wip_warehouse` is not. A board with draggable columns would therefore fail on
the gesture it most invites, and only 6 orders on the whole site are drafts. So
the line is presented as fixed, and the only write is the day.

**The board opens empty, and that is the point.** Nothing on this site is ever
planned forward — 3 789 of 3 789 orders were opened for the day they ran. A
planning screen here is not a view of an existing plan; it is the first surface
on which one can be made. Which is also why `may_reschedule` is careful: the 38
reschedules in the site's whole history mean the floor has no habit here to
protect, and every rule below is a rule about the first time somebody tries.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_plan_board -v
"""

from __future__ import annotations

import unittest

from stabler.api._wo_plan import (
	ScheduleRefused,
	build_plan_grid,
	may_reschedule,
	reschedule_target,
	schedule_window,
)

_LINES = ["Work In Progress - A", "WIP.1-Bo'lim - A"]
_DAYS = ["2026-08-28", "2026-08-29", "2026-08-30"]


def _order(name, line, when, qty=10.0, status="Not Started"):
	return {
		"name": name,
		"wip_warehouse": line,
		"planned_start_date": when,
		"qty": qty,
		"status": status,
	}


class TestMovingAnOrderKeepsTheHourItStartsAt(unittest.TestCase):
	"""`planned_start_date` is a datetime and every anjan row carries a real
	clock time — orders are opened between 05:00 and 23:00. Writing back a bare
	date would reset all of them to midnight, and nothing would complain: the
	shift log filters on the date half, so the loss is invisible on every screen
	that could have shown it."""

	def test_the_clock_survives_the_move(self):
		self.assertEqual(reschedule_target("2026-08-28 09:30:00", "2026-09-01"), "2026-09-01 09:30:00")

	def test_a_microsecond_stamp_is_not_carried_into_the_plan(self):
		"""Rows carry values like `2026-08-28 15:18:38.887170`. Minutes are what
		a shift is planned in; the rest is noise from whenever somebody clicked."""
		self.assertEqual(reschedule_target("2026-08-28 15:18:38.887170", "2026-09-01"), "2026-09-01 15:18:38")

	def test_an_order_with_no_planned_time_lands_at_midnight(self):
		"""There is no shift start recorded anywhere on this site, so inventing
		an 08:00 would be inventing a fact. Midnight is the honest default: it
		says the day is planned and the hour is not."""
		self.assertEqual(reschedule_target(None, "2026-09-01"), "2026-09-01 00:00:00")
		self.assertEqual(reschedule_target("", "2026-09-01"), "2026-09-01 00:00:00")


class TestFinishedWorkIsNotReplanned(unittest.TestCase):
	"""The plan date of work that already happened is how the floor later
	reconstructs what ran when — the shift log's date filter reads that column
	and nothing else. Letting the board rewrite it turns a planning gesture into
	a quiet edit of history, on the one screen built for dragging things around.
	"""

	def test_a_completed_order_refuses_and_says_why(self):
		allowed, reason = may_reschedule("Completed")
		self.assertFalse(allowed)
		self.assertTrue(reason, "reddin gerekçesi boş — ekran sessizce hiçbir şey yapmaz")

	def test_a_closed_order_refuses(self):
		self.assertFalse(may_reschedule("Closed")[0])

	def test_a_cancelled_order_refuses(self):
		self.assertFalse(may_reschedule("Cancelled")[0])

	def test_work_not_yet_finished_may_be_moved(self):
		for status in ("Draft", "Not Started", "In Process"):
			with self.subTest(status=status):
				allowed, reason = may_reschedule(status)
				self.assertTrue(allowed)
				self.assertEqual(reason, "")

	def test_a_stopped_order_may_be_moved(self):
		"""Stopped is paused, not finished — `resume_work_order` exists. Moving
		it to the day it will actually resume is the gesture, and refusing it
		would leave a stopped order pinned to a date nobody means any more."""
		self.assertTrue(may_reschedule("Stopped")[0])


class TestTheCellCountsWhatWasTypedAndNothingElse(unittest.TestCase):
	"""The refusal that gives this screen its value. 0 BOMs carry an operating
	time and 0 orders carry an end date, so any load percentage would be derived
	from nothing — and a percentage is read as a measurement, then staffed
	against. Count and quantity were both entered by a person."""

	def test_a_cell_reports_its_orders_and_their_quantity(self):
		grid = build_plan_grid(
			[
				_order("WO-1", _LINES[0], "2026-08-28 09:00:00", qty=12.5),
				_order("WO-2", _LINES[0], "2026-08-28 14:00:00", qty=7.5),
			],
			_DAYS,
			_LINES,
		)
		cell = _cell(grid, _LINES[0], "2026-08-28")
		self.assertEqual([o["name"] for o in cell["orders"]], ["WO-1", "WO-2"])
		self.assertEqual(cell["qty"], 20.0)

	def test_no_cell_carries_a_load_or_capacity_figure(self):
		grid = build_plan_grid([_order("WO-1", _LINES[0], "2026-08-28 09:00:00")], _DAYS, _LINES)
		for cell in grid["cells"]:
			for invented in ("load", "capacity", "utilisation", "utilization", "hours"):
				self.assertNotIn(invented, cell, f"uydurulmuş alan: {invented}")

	def test_an_empty_cell_still_exists(self):
		"""An absent cell and an empty one look the same in a table and mean
		opposite things: "this line has nothing on Saturday" is the answer a
		planner opened the board for."""
		grid = build_plan_grid([], _DAYS, _LINES)
		self.assertEqual(len(grid["cells"]), len(_LINES) * len(_DAYS))
		self.assertEqual(_cell(grid, _LINES[1], "2026-08-30")["orders"], [])
		self.assertEqual(_cell(grid, _LINES[1], "2026-08-30")["qty"], 0)


class TestNothingIsDroppedWithoutSaying(unittest.TestCase):
	"""The board is a grid, and a grid silently swallows whatever does not fit
	one of its squares. Every such order is work somebody scheduled; it has to
	come back named, not vanish."""

	def test_an_order_with_no_planned_date_is_listed_separately(self):
		grid = build_plan_grid([_order("WO-9", _LINES[0], None)], _DAYS, _LINES)
		self.assertEqual([o["name"] for o in grid["unscheduled"]], ["WO-9"])
		self.assertEqual(sum(len(c["orders"]) for c in grid["cells"]), 0)

	def test_an_order_on_a_line_the_board_does_not_show_is_listed_separately(self):
		"""A line only appears once an order is poured on it, so a line that
		exists in the data but not in the passed list is normal — and its work
		must not disappear because the dropdown was built from a different day."""
		grid = build_plan_grid([_order("WO-8", "WIP.9-Bo'lim - A", "2026-08-28 09:00:00")], _DAYS, _LINES)
		self.assertEqual([o["name"] for o in grid["unscheduled"]], ["WO-8"])

	def test_an_order_outside_the_window_is_listed_separately(self):
		grid = build_plan_grid([_order("WO-7", _LINES[0], "2026-09-15 09:00:00")], _DAYS, _LINES)
		self.assertEqual([o["name"] for o in grid["unscheduled"]], ["WO-7"])

	def test_the_grid_keeps_the_line_and_day_order_it_was_given(self):
		"""The lines come ordered by how much work they carry and the days in
		calendar order. Re-sorting them here would put the busiest line wherever
		the alphabet says."""
		grid = build_plan_grid([], _DAYS, _LINES)
		self.assertEqual(grid["lines"], _LINES)
		self.assertEqual(grid["days"], _DAYS)


class TestTheHoursAPlannerTypes(unittest.TestCase):
	"""Design 1c's grid needs a start AND an end, and the reason this exists is
	that neither is recorded today. Measured on anjan 2026-08-29: every one of
	3 799 orders carries a `planned_start_date`, but 3 464 of them (91%) sit
	within 60 seconds of `creation` — it is the moment somebody opened the form,
	not a plan — and 0 carry a `planned_end_date` at all.

	Both fields are `allow_on_submit` in ERPNext, and `planned_end_date` is
	recomputed only from an order's operations (`work_order.py:1045`). anjan
	holds 0 Work Order Operations, so what a planner types here is not going to
	be quietly overwritten. That is the fact this whole feature rests on, and it
	is the one to re-measure if the grid ever starts losing hours."""

	def test_a_start_alone_is_a_plan(self):
		"""An end is optional: entering when a job starts is useful on its own,
		and demanding both would leave the field empty for another five months."""
		self.assertEqual(
			schedule_window("2026-08-30 08:00:00", None),
			("2026-08-30 08:00:00", None),
		)

	def test_a_start_and_an_end_are_carried_through_whole(self):
		self.assertEqual(
			schedule_window("2026-08-30 08:00", "2026-08-30 14:30"),
			("2026-08-30 08:00:00", "2026-08-30 14:30:00"),
		)

	def test_an_end_can_be_cleared(self):
		"""A planner who mistyped an end must be able to take it back. Blank
		means blank — not "keep whatever was there", which would make the field
		impossible to correct from this screen."""
		self.assertEqual(schedule_window("2026-08-30 08:00", "")[1], None)

	def test_an_end_before_the_start_is_refused(self):
		"""Not a shorter job — a typo. Written through, it draws a bar with
		negative width, and every duration computed from it is negative."""
		with self.assertRaises(ScheduleRefused):
			schedule_window("2026-08-30 14:00", "2026-08-30 08:00")

	def test_an_end_equal_to_the_start_is_refused(self):
		"""Zero minutes is what the ACTUAL timestamps already say on 82% of
		finished orders (354 of 434 over 30 days), and it is exactly the value
		that makes those unusable. The planned pair must not inherit it."""
		with self.assertRaises(ScheduleRefused):
			schedule_window("2026-08-30 08:00", "2026-08-30 08:00")

	def test_midnight_is_an_hour_like_any_other(self):
		"""The first version of the bare-date guard compared the parsed value
		against the same string truncated to its date, which made an explicitly
		typed 00:00 indistinguishable from a date with no hour — and refused the
		one input the guard's own comment promised to protect. The guard reads
		the SHAPE of what was typed, not what it parsed to."""
		self.assertEqual(
			schedule_window("2026-08-30 00:00", "2026-08-30 06:00"),
			("2026-08-30 00:00:00", "2026-08-30 06:00:00"),
		)

	def test_a_start_that_is_not_a_time_is_refused(self):
		"""Rejected rather than coerced to midnight: 00:00 is a legal hour, so a
		silent fallback would put a night job on the board that nobody planned."""
		for bad in ("", None, "tomorrow", "2026-13-01 08:00", "2026-08-30"):
			with self.assertRaises(ScheduleRefused, msg=repr(bad)):
				schedule_window(bad, None)

	def test_an_end_that_is_not_a_time_is_refused(self):
		"""Same rule, and NOT treated as "no end": a typed end that could not be
		read must be reported, or the planner sees their entry silently vanish."""
		with self.assertRaises(ScheduleRefused):
			schedule_window("2026-08-30 08:00", "half past eight")

	def test_an_overnight_job_is_written_when_the_dates_say_so(self):
		"""Crossing midnight is legal and needs no special case — the end simply
		carries its own date. What is refused is an end that is EARLIER, which is
		the same input a planner would produce by typing 06:00 and meaning
		tomorrow. The screen has to ask for the date rather than guess."""
		self.assertEqual(
			schedule_window("2026-08-30 22:00", "2026-08-31 06:00"),
			("2026-08-30 22:00:00", "2026-08-31 06:00:00"),
		)


def _cell(grid, line, day):
	for cell in grid["cells"]:
		if cell["line"] == line and cell["day"] == day:
			return cell
	raise AssertionError(f"hücre yok: {line} / {day}")


if __name__ == "__main__":
	unittest.main()
