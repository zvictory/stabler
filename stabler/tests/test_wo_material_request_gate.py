"""When a submitted Work Order should raise a Material Request for its shortages.

The hook has been wired on `Work Order.on_submit` since it was written and has
never once run. Measured on anjan 2026-08-28, read-only:

    submitted Work Orders                              3 789
    …with `planned_start_date` in the future               0
    …same day                                          3 619
    …backdated                                           170
    …with no `wip_warehouse` (the other early return)       0
    Material Requests carrying a `work_order`         0 / 488

`Material Request.work_order` is a real field on this site, so that last number
is not a write that failed — it is a function that returned before writing,
3 789 times. The gate was `planned_start_date >= tomorrow`, and this factory
never plans a day ahead: every order is opened for the day it runs.

The gate was not wrong about wanting one. A backdated order is a catch-up entry
typed after the fact, and asking the store to transfer material for work that
already happened is noise a shift lead learns to ignore — which is how a request
queue dies. What the gate got wrong is the direction it excluded: an order
starting *today* with material missing from the line is the urgent case, not the
one to skip.

So the rule is `planned_start_date >= today`, and it lives in a pure function
because the interesting cases are all about dates and none of them need a
database. `test_wo_role_scoping_integration` proves the hook itself writes.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_material_request_gate -v
"""

from __future__ import annotations

import unittest

from stabler.api._wo_material_request import should_request_materials

_TODAY = "2026-08-28"


class TestTheDayTheOrderRunsIsIncluded(unittest.TestCase):
	"""The whole defect in one class. 3 619 of 3 789 orders are same-day, so a
	rule that excludes today excludes the factory."""

	def test_an_order_starting_today_asks_for_its_shortages(self):
		self.assertTrue(should_request_materials("2026-08-28", today=_TODAY))

	def test_a_datetime_is_read_as_its_date(self):
		"""`planned_start_date` is a datetime column — every anjan row carries a
		time. Comparing the raw value against a date string is how "today" turns
		into "not today" for every order opened after midnight."""
		self.assertTrue(should_request_materials("2026-08-28 15:18:38.887170", today=_TODAY))

	def test_a_future_order_still_asks(self):
		"""The only case the old gate allowed. It has never occurred on anjan,
		but the rule widens rather than moves — nothing that used to produce a
		request may stop producing one."""
		self.assertTrue(should_request_materials("2026-09-01", today=_TODAY))


class TestABackdatedOrderIsStillExcluded(unittest.TestCase):
	"""170 orders are backdated. Keeping them out is deliberate: a request to
	transfer material for work already done is noise, and a queue full of noise
	is one nobody reads — which is worse than the queue not existing."""

	def test_yesterday_does_not_ask(self):
		self.assertFalse(should_request_materials("2026-08-27", today=_TODAY))

	def test_a_backdated_datetime_does_not_ask(self):
		self.assertFalse(should_request_materials("2026-08-27 23:59:59", today=_TODAY))


class TestAMissingDateIsNotTreatedAsToday(unittest.TestCase):
	"""An order with no planned start is not scheduled at all. Reading a blank
	as "now" would make the hook fire on exactly the orders nobody has planned."""

	def test_none_does_not_ask(self):
		self.assertFalse(should_request_materials(None, today=_TODAY))

	def test_blank_does_not_ask(self):
		self.assertFalse(should_request_materials("", today=_TODAY))

	def test_garbage_does_not_ask(self):
		"""Unparseable is unknown, and unknown is not a reason to write."""
		self.assertFalse(should_request_materials("not-a-date", today=_TODAY))


class TestTheRuleIsWrittenDownOnce(unittest.TestCase):
	"""It was written twice. `create_material_request_for_tomorrow_wo` gated on
	`>= tomorrow` and `update_work_order_materials` re-derived the same bound in
	its own words — so fixing one would have left the other excluding every
	order on the floor, and the two would then disagree about whether a request
	for an order exists at all.

	Pinned as a source assertion for the same reason `test_wo_operator_roles`
	pins the assignee rule: a third call site is one edit away, and the failure
	it produces is silence."""

	def test_no_call_site_re_derives_the_bound(self):
		import pathlib

		src = (pathlib.Path(__file__).resolve().parents[1] / "api/manufacturing.py").read_text(
			encoding="utf-8"
		)
		self.assertNotIn(
			"add_days(today(), 1)",
			src,
			"kapı yeniden türetilmiş — should_request_materials tek kaynak olmalı",
		)
		self.assertIn("from stabler.api._wo_material_request import should_request_materials", src)
		self.assertEqual(
			src.count("should_request_materials("),
			2,
			"iki çağrı yeri bekleniyor; sayı değiştiyse kapı ya kopyalandı ya kayboldu",
		)


if __name__ == "__main__":
	unittest.main()
