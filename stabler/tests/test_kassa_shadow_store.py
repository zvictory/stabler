"""Unit tests for stabler.integrations.kassa.shadow_store (WP-S4a, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_shadow_store -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from stabler.integrations.kassa import shadow_store as ss

CO = "mikas"
D = "2026-07-19"


class TestShadowStore(unittest.TestCase):
	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix=".sqlite")
		os.close(fd)

	def tearDown(self):
		try:
			os.remove(self.path)
		except OSError:
			pass

	def test_opening_and_empty_balance(self):
		ss.set_opening(self.path, CO, D, "nakit", 402_250_000)
		ss.set_opening(self.path, CO, D, "pk", 3_000_000)
		ss.set_opening(self.path, CO, D, "usd", 400)
		self.assertEqual(
			ss.balances(self.path, CO, D), {"nakit": 402_250_000.0, "pk": 3_000_000.0, "usd": 400.0}
		)

	def test_opening_upsert(self):
		ss.set_opening(self.path, CO, D, "nakit", 100)
		ss.set_opening(self.path, CO, D, "nakit", 250)  # overwrite
		self.assertEqual(ss.get_openings(self.path, CO, D)["nakit"], 250.0)

	def test_multi_leg_kirim_updates_balances(self):
		ss.set_opening(self.path, CO, D, "nakit", 402_250_000)
		ss.set_opening(self.path, CO, D, "pk", 3_000_000)
		ss.set_opening(self.path, CO, D, "usd", 400)
		# "Mijozdan 2 mln naqd, 3 mln karta va 500 dollar oldim"
		ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="kirim",
			counterparty="Mijoz",
			raw_text="Mijozdan 2 mln naqd...",
			date=D,
			deltas=[
				{"kassa": "nakit", "delta": 2_000_000},
				{"kassa": "pk", "delta": 3_000_000},
				{"kassa": "usd", "delta": 500},
			],
		)
		self.assertEqual(
			ss.balances(self.path, CO, D), {"nakit": 404_250_000.0, "pk": 6_000_000.0, "usd": 900.0}
		)

	def test_chiqim_negative_delta(self):
		ss.set_opening(self.path, CO, D, "nakit", 1_000_000)
		ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="chiqim",
			date=D,
			purpose="ijara",
			deltas=[{"kassa": "nakit", "delta": -100_000}],
		)
		self.assertEqual(ss.balances(self.path, CO, D)["nakit"], 900_000.0)

	def test_konversiya_two_legs(self):
		ss.set_opening(self.path, CO, D, "nakit", 13_000_000)
		ss.set_opening(self.path, CO, D, "usd", 0)
		# buy 1000$ @ 12900 from Nakit: nakit -12,900,000 ; usd +1000
		ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="konversiya",
			rate=12900,
			date=D,
			deltas=[{"kassa": "nakit", "delta": -12_900_000}, {"kassa": "usd", "delta": 1000}],
		)
		b = ss.balances(self.path, CO, D)
		self.assertEqual(b["nakit"], 100_000.0)
		self.assertEqual(b["usd"], 1000.0)

	def test_list_and_delete(self):
		eid = ss.add_entry(
			self.path,
			company=CO,
			kassir="7001",
			op="kirim",
			counterparty="Ali",
			raw_text="Alidan 600 ming oldim",
			parsed={"op": "kirim"},
			deltas=[{"kassa": "nakit", "delta": 600_000}],
		)
		lst = ss.list_entries(self.path, CO, D if False else ss._today())
		# entry lands under today's date (add_entry defaults date=today)
		today = ss._today()
		lst = ss.list_entries(self.path, CO, today)
		self.assertEqual(len(lst), 1)
		self.assertEqual(lst[0]["counterparty"], "Ali")
		self.assertEqual(lst[0]["legs"], [{"kassa": "nakit", "delta": 600_000.0}])
		ss.delete_entry(self.path, eid, CO)
		self.assertEqual(ss.list_entries(self.path, CO, today), [])
		self.assertEqual(ss.balances(self.path, CO, today).get("nakit", 0), 0.0)

	def test_company_isolation(self):
		ss.add_entry(
			self.path,
			company="mikas",
			kassir="1",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 500}],
			date=D,
		)
		ss.add_entry(
			self.path,
			company="other",
			kassir="2",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 999}],
			date=D,
		)
		self.assertEqual(ss.balances(self.path, "mikas", D)["nakit"], 500.0)
		self.assertEqual(ss.balances(self.path, "other", D)["nakit"], 999.0)


class TestListEntriesOverARange(unittest.TestCase):
	"""The mini app asks for a week, so the store has to be able to answer for one.

	`list_entries` took a single date and the page therefore showed a single day,
	behind arrows that step one day at a time. Reported 2026-08-21: "the bot only
	shows today, I wanted a week to stay — can you bring those back". Nothing was
	lost; a week of work was one day per press away, and the cashier never found
	the presses. A day at a time is also the wrong unit for the question a till
	statement answers, which is "what moved this week".

	`since` defaults to `date`, so every existing caller keeps the old answer.
	"""

	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix=".sqlite")
		os.close(fd)
		for day, amount in (("2026-07-17", 10), ("2026-07-19", 20), ("2026-07-21", 30)):
			ss.add_entry(
				self.path,
				company=CO,
				kassir="1",
				op="kirim",
				deltas=[{"kassa": "nakit", "delta": amount}],
				date=day,
			)

	def tearDown(self):
		os.unlink(self.path)

	def _days(self, **kw):
		return sorted(e["legs"][0]["delta"] for e in ss.list_entries(self.path, CO, **kw))

	def test_without_a_start_it_still_answers_for_one_day(self):
		self.assertEqual(self._days(date="2026-07-19"), [20])

	def test_the_range_includes_both_ends(self):
		"""Off by one at either end silently drops a day of the cashier's work."""
		self.assertEqual(self._days(date="2026-07-21", since="2026-07-17"), [10, 20, 30])
		self.assertEqual(self._days(date="2026-07-19", since="2026-07-17"), [10, 20])
		self.assertEqual(self._days(date="2026-07-21", since="2026-07-19"), [20, 30])

	def test_a_start_after_the_end_returns_nothing_rather_than_everything(self):
		self.assertEqual(self._days(date="2026-07-17", since="2026-07-21"), [])

	def test_the_range_stays_inside_the_company(self):
		ss.add_entry(
			self.path,
			company="other",
			kassir="9",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 999}],
			date="2026-07-19",
		)
		self.assertEqual(self._days(date="2026-07-21", since="2026-07-17"), [10, 20, 30])


class TestOneTillPerCompany(unittest.TestCase):
	"""The drawer belongs to the company, not to whoever is standing at it.

	`balances()` groups by (company, kassa) and never by kassir, so every kassir
	of a company reads and writes one pooled figure. That is deliberate for a
	shared physical till — a cashier taking over a shift must see the cash that
	is actually in the drawer, not their own running total since they logged in.

	It is also the sharpest reading of the complaint raised on 2026-08-21. On
	mikas three kassirs have written here; one of them started on 19 August and
	opened the bot to 581 million so'm accumulated by a colleague in July. "Why
	is it showing a balance that isn't ours" is exactly what pooling looks like
	from the other side of a handover.

	No test pinned this either way, so the behaviour was neither a decision nor
	a guarantee — just what the SQL happened to do. It is pinned here so that
	changing it to per-kassir has to be a choice someone makes on purpose, with
	this test in front of them. `docs/plans/2026-07-19-kassabot-shadow-mode.md`
	promises the opposite ("başka kassir'in verisini ko'rmaydi"); until that is
	resolved the code, not the plan, is what runs.
	"""

	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix=".sqlite")
		os.close(fd)

	def tearDown(self):
		os.unlink(self.path)

	def test_a_second_kassir_reads_the_first_ones_money(self):
		ss.add_entry(
			self.path,
			company=CO,
			kassir="morning-shift",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 5_000_000}],
			date=D,
		)
		ss.add_entry(
			self.path,
			company=CO,
			kassir="evening-shift",
			op="chiqim",
			deltas=[{"kassa": "nakit", "delta": -1_000_000}],
			date=D,
		)
		# One till: 5m in, 1m out, whoever moved it.
		self.assertEqual(ss.balances(self.path, CO, D)["nakit"], 4_000_000)

	def test_an_opening_declared_by_one_kassir_resets_it_for_all_of_them(self):
		"""Counting the drawer is a statement about the drawer, so whoever counts
		it restates the total for everyone. `set_opening` does not even take a
		kassir — there is nobody to attribute the count to, and no check on who
		is allowed to make it (bot.py: "No access restriction for now")."""
		ss.add_entry(
			self.path,
			company=CO,
			kassir="morning-shift",
			op="kirim",
			deltas=[{"kassa": "nakit", "delta": 5_000_000}],
			date=D,
		)
		later = "2026-07-20"
		# A different kassir counts the till the next morning and finds 90 000.
		ss.set_opening(self.path, CO, later, "nakit", 90_000)
		self.assertEqual(ss.balances(self.path, CO, later)["nakit"], 90_000)
		# Yesterday is untouched: a count restates today, it does not rewrite history.
		self.assertEqual(ss.balances(self.path, CO, D)["nakit"], 5_000_000)


class TestCarryForward(unittest.TestCase):
	"""The drawer does not empty itself overnight.

	Until 2026-08-19 `balances()` summed only the requested day's deltas on top of
	that same day's opening row. Openings are entered by hand from a Telegram
	button, and on mikas exactly one day in seven had one — so every other morning
	the mini app opened at zero while the money was still in the drawer. The
	cashiers read that as the bot deleting the day before. Nothing was ever
	deleted; the reading was one day wide.

	What makes an opening special is that it is a RESTATEMENT: the cashier counted
	the cash and declared it. So it supersedes everything before it and the days
	after it accumulate on top. Absent one, the ledger carries from its beginning.
	"""

	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix=".sqlite")
		os.close(fd)

	def tearDown(self):
		try:
			os.remove(self.path)
		except OSError:
			pass

	def _kirim(self, date, amount, kassa="nakit"):
		# Explicit, increasing `ts`: the store derives the entry id from the clock
		# and two inserts inside the same millisecond collide on the primary key
		# (shadow_store.py:80 — the three "extra" digits repeat the milliseconds
		# already in `ts`, so they add no entropy). A test that races the wall clock
		# fails at random for a reason that has nothing to do with what it asserts.
		self._ts = getattr(self, "_ts", 1_700_000_000_000) + 1
		ss.add_entry(
			self.path,
			company=CO,
			kassir="1",
			op="kirim",
			date=date,
			ts=self._ts,
			deltas=[{"kassa": kassa, "delta": amount}],
		)

	def test_yesterdays_money_is_still_there_today(self):
		# The reported symptom, at its smallest: money in on Monday, nothing on
		# Tuesday. Tuesday must not read zero.
		self._kirim("2026-07-19", 500_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-07-20")["nakit"], 500_000.0)

	def test_a_quiet_day_holds_the_balance_not_a_gap(self):
		# Days with no traffic at all are the common case on mikas — seven active
		# days across a month. A gap must not reset anything.
		self._kirim("2026-07-19", 500_000)
		self._kirim("2026-08-10", 100_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-08-19")["nakit"], 600_000.0)

	def test_a_declared_opening_supersedes_everything_before_it(self):
		# The cashier counted the drawer and declared it. Whatever the ledger
		# thought it held before that moment is now wrong, by definition — the
		# count wins, or the button would be pointless.
		self._kirim("2026-07-19", 500_000)
		ss.set_opening(self.path, CO, "2026-07-22", "nakit", 9_000_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-07-22")["nakit"], 9_000_000.0)

	def test_days_after_a_declared_opening_accumulate_on_top_of_it(self):
		self._kirim("2026-07-19", 500_000)
		ss.set_opening(self.path, CO, "2026-07-22", "nakit", 9_000_000)
		self._kirim("2026-07-27", 1_000_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-07-30")["nakit"], 10_000_000.0)

	def test_the_opening_applies_only_to_the_kassa_it_was_declared_for(self):
		# Openings are per (company, date, kassa): a cashier may count the cash
		# drawer and never touch the card terminal. Resetting `pk` off `nakit`'s
		# declaration would silently discard the card balance.
		self._kirim("2026-07-19", 500_000, kassa="nakit")
		self._kirim("2026-07-19", 700_000, kassa="pk")
		ss.set_opening(self.path, CO, "2026-07-22", "nakit", 9_000_000)
		b = ss.balances(self.path, CO, "2026-07-22")
		self.assertEqual(b["nakit"], 9_000_000.0)
		self.assertEqual(b["pk"], 700_000.0)

	def test_an_opening_cuts_off_the_kassa_it_names_and_no_other(self):
		# The companion to the test above, and the one that catches a cut-off
		# recorded under a hardcoded key: declare the opening for `pk`, and `pk`
		# must be the side that loses its history while `nakit` keeps its own.
		# Assert with a NON-default kassa or the wrong-key bug reads as correct.
		self._kirim("2026-07-19", 500_000, kassa="nakit")
		self._kirim("2026-07-19", 700_000, kassa="pk")
		ss.set_opening(self.path, CO, "2026-07-22", "pk", 9_000_000)
		b = ss.balances(self.path, CO, "2026-07-22")
		self.assertEqual(b["pk"], 9_000_000.0)
		self.assertEqual(b["nakit"], 500_000.0)

	def test_the_future_does_not_leak_into_the_past(self):
		# Reading an earlier day must still show that day, or the mini app's date
		# picker would report today's total for every date in the archive.
		self._kirim("2026-07-19", 500_000)
		self._kirim("2026-08-10", 100_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-07-19")["nakit"], 500_000.0)

	def test_an_opening_declared_later_does_not_rewrite_an_earlier_day(self):
		self._kirim("2026-07-19", 500_000)
		ss.set_opening(self.path, CO, "2026-07-22", "nakit", 9_000_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-07-20")["nakit"], 500_000.0)

	def test_a_day_before_the_ledger_begins_is_zero(self):
		self._kirim("2026-07-19", 500_000)
		self.assertEqual(ss.balances(self.path, CO, "2026-07-18")["nakit"], 0.0)

	def test_company_isolation_survives_the_carry(self):
		# Widening the window from one day to all-days-so-far widens what a missing
		# company filter would leak, so the isolation assertion is repeated here.
		self._kirim("2026-07-19", 500_000)
		ss.add_entry(
			self.path,
			company="other",
			kassir="2",
			op="kirim",
			date="2026-07-19",
			ts=self._ts + 1,
			deltas=[{"kassa": "nakit", "delta": 999}],
		)
		self.assertEqual(ss.balances(self.path, CO, "2026-08-19")["nakit"], 500_000.0)
		self.assertEqual(ss.balances(self.path, "other", "2026-08-19")["nakit"], 999.0)


class TestOpeningBalances(unittest.TestCase):
	"""What the ledger table starts its running column from.

	The mini app draws an 'Ochilish balansi' row and adds each entry to it. It used
	to read the day's declared opening, which is absent on almost every day — so the
	column started at zero. Once the cards carry forward, a zero start makes the
	screen contradict itself: the card would show the drawer and the last ledger row
	would show the day's net movement. These have to be the same number.
	"""

	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix=".sqlite")
		os.close(fd)

	def tearDown(self):
		try:
			os.remove(self.path)
		except OSError:
			pass

	def _kirim(self, date, amount, kassa="nakit"):
		# Explicit, increasing `ts`: the store derives the entry id from the clock
		# and two inserts inside the same millisecond collide on the primary key
		# (shadow_store.py:80 — the three "extra" digits repeat the milliseconds
		# already in `ts`, so they add no entropy). A test that races the wall clock
		# fails at random for a reason that has nothing to do with what it asserts.
		self._ts = getattr(self, "_ts", 1_700_000_000_000) + 1
		ss.add_entry(
			self.path,
			company=CO,
			kassir="1",
			op="kirim",
			date=date,
			ts=self._ts,
			deltas=[{"kassa": kassa, "delta": amount}],
		)

	def test_the_day_starts_where_the_day_before_closed(self):
		self._kirim("2026-07-19", 500_000)
		self.assertEqual(ss.opening_balances(self.path, CO, "2026-07-20")["nakit"], 500_000.0)

	def test_a_declared_opening_is_what_the_day_starts_from(self):
		self._kirim("2026-07-19", 500_000)
		ss.set_opening(self.path, CO, "2026-07-20", "nakit", 9_000_000)
		self.assertEqual(ss.opening_balances(self.path, CO, "2026-07-20")["nakit"], 9_000_000.0)

	def test_a_declared_zero_is_a_declaration_not_a_missing_value(self):
		# Counting the drawer and finding it empty is a real answer. Treating 0 as
		# "nothing was declared" would carry yesterday's cash into an emptied till.
		self._kirim("2026-07-19", 500_000)
		ss.set_opening(self.path, CO, "2026-07-20", "nakit", 0)
		self.assertEqual(ss.opening_balances(self.path, CO, "2026-07-20")["nakit"], 0.0)

	def test_the_screen_cannot_contradict_itself(self):
		# The invariant the mini app renders: start + the day's own movements = the
		# card. If these ever diverge the cashier sees two different balances at
		# once and has no way to tell which is the drawer.
		self._kirim("2026-07-19", 500_000)
		self._kirim("2026-07-20", 300_000, kassa="pk")
		ss.set_opening(self.path, CO, "2026-07-22", "nakit", 9_000_000)
		self._kirim("2026-07-22", 250_000)
		self._kirim("2026-07-27", -100_000)
		for day in ("2026-07-19", "2026-07-20", "2026-07-22", "2026-07-27", "2026-07-30"):
			start = ss.opening_balances(self.path, CO, day)
			closing = ss.balances(self.path, CO, day)
			moved = {k: 0.0 for k in ss.KASSAS}
			for e in ss.list_entries(self.path, CO, day):
				for leg in e["legs"]:
					moved[leg["kassa"]] = moved.get(leg["kassa"], 0.0) + leg["delta"]
			for k in ss.KASSAS:
				self.assertAlmostEqual(
					start[k] + moved[k],
					closing[k],
					places=2,
					msg=f"{day}/{k}: baslangic {start[k]} + hareket {moved[k]} != kart {closing[k]}",
				)


if __name__ == "__main__":
	unittest.main()
