"""Work-queue policy contracts (Phase 4, stabler-l0m.4).

Bench-free: `work_policy` imports nothing from frappe by construction, so these
tests run under plain unittest with no site, no DB and no fixtures.

What is being defended here is not "the functions return values" but the two
rules that keep the queue honest:

* one definition of overdue, shared with Phase 2's `_open_total`;
* one work item per policy firing, keyed on the event's own date — so a
  scheduler that runs twice today, or every night for six months, still owes the
  customer exactly one collection task per late installment.
"""

from __future__ import annotations

import unittest
from datetime import date

from stabler.api.vehicle_finance import work_policy as policy


class TestOverdueDefinition(unittest.TestCase):
	"""`row_outstanding` must mirror the per-row half of v1.py's `_open_total`
	exactly. If these drift, the work queue and the agreement detail screen start
	telling a customer two different stories about the same installment."""

	def test_outstanding_is_amount_minus_paid(self):
		self.assertEqual(policy.row_outstanding(1000, 250), 750.0)

	def test_over_allocated_row_never_goes_negative(self):
		# _open_total clamps at zero per row: a row overpaid by 50 must not lend
		# that 50 to the next row and hide a genuine shortfall.
		self.assertEqual(policy.row_outstanding(1000, 1050), 0.0)

	def test_open_total_agrees_row_by_row(self):
		rows = [(1000, 250), (1000, 1050), (500, 500), (300, 0)]
		open_total = sum(max(0.0, float(a) - float(p)) for a, p in rows)
		self.assertEqual(sum(policy.row_outstanding(a, p) for a, p in rows), open_total)

	def test_fully_paid_row_is_not_open(self):
		self.assertFalse(policy.is_open(500, 500))
		self.assertTrue(policy.is_open(500, 499.99))


class TestRowEvent(unittest.TestCase):
	TODAY = date(2026, 3, 15)

	def test_past_due_date_is_overdue(self):
		self.assertEqual(policy.row_event(date(2026, 3, 1), self.TODAY), policy.EVENT_OVERDUE)

	def test_today_is_due_today_not_overdue(self):
		self.assertEqual(policy.row_event(self.TODAY, self.TODAY), policy.EVENT_DUE_TODAY)

	def test_within_seven_days_is_upcoming(self):
		self.assertEqual(policy.row_event(date(2026, 3, 22), self.TODAY), policy.EVENT_UPCOMING_7D)

	def test_beyond_the_window_fires_nothing(self):
		self.assertIsNone(policy.row_event(date(2026, 3, 23), self.TODAY))

	def test_string_dates_are_accepted(self):
		# Frappe hands dates back as strings from raw SQL and as JSON from a
		# whitelisted call; the policy must not care which.
		self.assertEqual(policy.row_event("2026-03-01", "2026-03-15"), policy.EVENT_OVERDUE)


class TestIdentityAndIdempotency(unittest.TestCase):
	"""The scheduler's whole idempotency story."""

	def test_policy_date_is_the_due_date_not_the_run_date(self):
		due = date(2026, 3, 1)
		first_run = policy.policy_date_for(policy.EVENT_OVERDUE, due_date=due)
		self.assertEqual(first_run, due)

	def test_same_row_yields_one_identity_no_matter_when_the_job_runs(self):
		due = date(2026, 3, 1)
		run_dates = [date(2026, 3, 2), date(2026, 3, 2), date(2026, 3, 30), date(2026, 5, 30)]
		tuples = set()
		for run_date in run_dates:
			event = policy.row_event(due, run_date)
			self.assertEqual(event, policy.EVENT_OVERDUE)
			tuples.add(
				policy.identity(
					"Acme",
					"VFA-0001",
					"row-7",
					event,
					policy.policy_date_for(event, due_date=due),
				)
			)
		self.assertEqual(len(tuples), 1, "a late row must never file more than one overdue item")

	def test_promise_events_key_on_the_promise_date(self):
		promised = date(2026, 4, 10)
		self.assertEqual(
			policy.policy_date_for(policy.EVENT_PROMISE_BROKEN, due_date=date(2026, 3, 1), promise_date=promised),
			promised,
		)

	def test_different_event_types_are_different_work(self):
		due = date(2026, 3, 1)
		due_today = policy.identity("Acme", "VFA-0001", "row-7", policy.EVENT_DUE_TODAY, due)
		overdue = policy.identity("Acme", "VFA-0001", "row-7", policy.EVENT_OVERDUE, due)
		self.assertNotEqual(due_today, overdue)

	def test_same_row_name_in_two_companies_is_two_identities(self):
		due = date(2026, 3, 1)
		self.assertNotEqual(
			policy.identity("Acme", "VFA-0001", "row-7", policy.EVENT_OVERDUE, due),
			policy.identity("Beta", "VFA-0001", "row-7", policy.EVENT_OVERDUE, due),
		)

	def test_missing_policy_date_is_refused(self):
		with self.assertRaises(ValueError):
			policy.policy_date_for(policy.EVENT_PROMISE_DUE, due_date=date(2026, 3, 1))


class TestPromiseEvents(unittest.TestCase):
	TODAY = date(2026, 4, 15)

	def test_kept_promise_fires_nothing(self):
		self.assertIsNone(policy.promise_event(date(2026, 4, 10), 500, 500, self.TODAY))

	def test_promise_kept_on_the_day_itself_counts(self):
		# `allocated_on_or_before` is inclusive of the promise date — paying on
		# the promised day is keeping the promise, not breaking it.
		self.assertIsNone(policy.promise_event(self.TODAY, 500, 500, self.TODAY))

	def test_underpaid_promise_past_its_date_is_broken(self):
		self.assertEqual(
			policy.promise_event(date(2026, 4, 10), 500, 499, self.TODAY),
			policy.EVENT_PROMISE_BROKEN,
		)

	def test_promise_due_today_is_not_yet_broken(self):
		self.assertEqual(
			policy.promise_event(self.TODAY, 500, 0, self.TODAY),
			policy.EVENT_PROMISE_DUE,
		)

	def test_future_promise_is_silent(self):
		self.assertIsNone(policy.promise_event(date(2026, 5, 1), 500, 0, self.TODAY))

	def test_rounding_residue_does_not_break_a_kept_promise(self):
		self.assertTrue(policy.promise_is_kept(500, 499.999, precision=2))


class TestRowViews(unittest.TestCase):
	TODAY = date(2026, 3, 15)

	def test_overdue_row_is_in_overdue_but_not_yet_critical(self):
		views = policy.row_views(date(2026, 3, 13), self.TODAY, escalation_threshold_days=7)
		self.assertIn(policy.VIEW_OVERDUE, views)
		self.assertNotIn(policy.VIEW_CRITICAL_OVERDUE, views)

	def test_threshold_comes_from_the_company_setting(self):
		late_three_days = date(2026, 3, 12)
		self.assertNotIn(
			policy.VIEW_CRITICAL_OVERDUE,
			policy.row_views(late_three_days, self.TODAY, escalation_threshold_days=7),
		)
		self.assertIn(
			policy.VIEW_CRITICAL_OVERDUE,
			policy.row_views(late_three_days, self.TODAY, escalation_threshold_days=3),
		)

	def test_broken_promise_is_critical_without_erasing_due_today(self):
		# The regression this test exists for: making the broken-promise rule an
		# `elif` in the date chain silently dropped a row due *today* out of the
		# due_today view the moment its promise broke.
		views = policy.row_views(self.TODAY, self.TODAY, has_broken_promise=True)
		self.assertIn(policy.VIEW_DUE_TODAY, views)
		self.assertIn(policy.VIEW_CRITICAL_OVERDUE, views)

	def test_upcoming_row_lands_in_next_seven_days(self):
		self.assertEqual(
			policy.row_views(date(2026, 3, 20), self.TODAY),
			frozenset({policy.VIEW_NEXT_7_DAYS}),
		)

	def test_far_future_row_with_an_open_promise_is_monitored(self):
		views = policy.row_views(date(2026, 6, 1), self.TODAY, has_open_promise=True)
		self.assertEqual(views, frozenset({policy.VIEW_MONITORING}))

	def test_far_future_row_with_nothing_pending_is_not_work(self):
		self.assertEqual(policy.row_views(date(2026, 6, 1), self.TODAY), frozenset())

	def test_monitoring_never_shadows_a_real_view(self):
		views = policy.row_views(date(2026, 3, 1), self.TODAY, has_open_followup=True)
		self.assertIn(policy.VIEW_OVERDUE, views)
		self.assertNotIn(policy.VIEW_MONITORING, views)


class TestPromiseValidation(unittest.TestCase):
	TODAY = date(2026, 3, 15)

	def test_positive_promise_within_outstanding_is_accepted(self):
		self.assertIsNone(policy.promise_validation_error(500, date(2026, 3, 20), self.TODAY, 1000))

	def test_zero_amount_is_refused(self):
		self.assertEqual(
			policy.promise_validation_error(0, date(2026, 3, 20), self.TODAY, 1000),
			policy.PROMISE_ERR_AMOUNT,
		)

	def test_promise_above_outstanding_is_refused(self):
		self.assertEqual(
			policy.promise_validation_error(1500, date(2026, 3, 20), self.TODAY, 1000),
			policy.PROMISE_ERR_EXCEEDS,
		)

	def test_promise_equal_to_outstanding_is_accepted(self):
		self.assertIsNone(policy.promise_validation_error(1000, date(2026, 3, 20), self.TODAY, 1000))

	def test_past_promise_date_is_refused(self):
		self.assertEqual(
			policy.promise_validation_error(500, date(2026, 3, 14), self.TODAY, 1000),
			policy.PROMISE_ERR_PAST_DATE,
		)

	def test_promise_today_is_accepted(self):
		self.assertIsNone(policy.promise_validation_error(500, self.TODAY, self.TODAY, 1000))

	def test_settled_row_cannot_carry_a_promise(self):
		self.assertEqual(
			policy.promise_validation_error(500, date(2026, 3, 20), self.TODAY, 0),
			policy.PROMISE_ERR_ROW_SETTLED,
		)


class TestCurrencyTotals(unittest.TestCase):
	def test_two_currencies_stay_two_numbers(self):
		totals: dict = {}
		policy.add_currency_total(totals, "USD", 1000)
		policy.add_currency_total(totals, "UZS", 12_000_000)
		policy.add_currency_total(totals, "USD", 500)
		self.assertEqual(totals, {"USD": 1500.0, "UZS": 12_000_000.0})

	def test_a_total_without_a_currency_is_impossible(self):
		with self.assertRaises(ValueError):
			policy.add_currency_total({}, "", 1000)


class TestVocabulary(unittest.TestCase):
	"""The doctype JSON hardcodes these option lists; a rename in one place and
	not the other produces a work item nobody can filter for."""

	def test_event_types_match_the_doctype_options(self):
		self.assertEqual(
			set(policy.EVENT_TYPES),
			{"due_today", "overdue", "promise_due", "promise_broken", "upcoming_7d"},
		)

	def test_work_statuses_match_the_doctype_options(self):
		self.assertEqual(
			list(policy.WORK_STATUSES),
			["Unassigned", "Assigned", "Contacted", "Promise", "Escalated", "Resolved"],
		)

	def test_resolved_is_the_only_closed_status(self):
		self.assertNotIn(policy.WORK_RESOLVED, policy.OPEN_WORK_STATUSES)
		self.assertEqual(len(policy.OPEN_WORK_STATUSES), len(policy.WORK_STATUSES) - 1)


if __name__ == "__main__":
	unittest.main()
