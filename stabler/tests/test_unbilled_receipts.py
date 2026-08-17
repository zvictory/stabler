"""Unit tests for stabler.api._unbilled_receipts (GR/IR aging, Frappe-free).

Every test here defends one rule of the unbilled-goods report. The rules are not
cosmetic: this report is the only thing in the app that tells anyone a shipment
was received and never invoiced, and its number is reconciled against the Stock
Received But Not Billed ledger. A rule that silently reads "unbilled" as
"billed" makes SRBNB look clean and hides a supplier debt the company owes.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_unbilled_receipts -v
"""

from __future__ import annotations

import unittest

from stabler.api._unbilled_receipts import (
	BUCKET_BOUNDS,
	BUCKETS,
	annotate_rows,
	billed_percent,
	bucket_of,
	reconciliation_comparable,
	summarise,
	unbilled_amount,
)

#: One truck of frozen beef, company currency (UZS). Chosen so that halves and
#: thirds stay exact and a wrong answer cannot look like rounding noise.
TRUCK = 120_000_000.0


def _bounds_match(bucket_key, age):
	"""Does BUCKET_BOUNDS admit `age` into `bucket_key`?

	This is the predicate the endpoint's SQL builds from those bounds
	(``DATEDIFF(as_of, posting_date) >= age_min`` / ``<= age_max``), restated in
	Python so the test can compare it against bucket_of() row labelling.
	"""
	low, high = BUCKET_BOUNDS[bucket_key]
	return (low is None or age >= low) and (high is None or age <= high)


class TestUnbilledAmount(unittest.TestCase):
	def test_untouched_receipt_is_exposed_for_its_whole_base_value(self):
		"""per_billed = 0: the goods are in the warehouse and nothing is payable yet,
		so the entire company-currency value of the receipt is the exposure."""
		self.assertEqual(
			unbilled_amount(TRUCK, 0),
			TRUCK,
			"a receipt with no invoice against it must report its full value, "
			"or the report under-states what the company owes",
		)

	def test_half_billed_receipt_exposes_half_its_base_value(self):
		"""per_billed = 50: half the goods were invoiced, half were not. The report
		is proportional, which is what makes it addable against the SRBNB ledger."""
		self.assertEqual(unbilled_amount(TRUCK, 50), 60_000_000.0)
		self.assertEqual(unbilled_amount(TRUCK, 25), 90_000_000.0)

	def test_fully_billed_receipt_has_no_exposure(self):
		"""per_billed = 100: the Purchase Invoice already debited SRBNB, so this
		receipt must contribute nothing. A non-zero here double-counts a debt."""
		self.assertEqual(unbilled_amount(TRUCK, 100), 0.0)

	def test_over_billed_receipt_clamps_to_zero_and_never_goes_negative(self):
		"""ERPNext permits over-billing within tolerance, so per_billed > 100 is a
		real value in production. An over-billed receipt is an AP over-accrual, not
		negative exposure: if it came back negative it would net down the genuine
		exposure of other receipts inside the same total and shrink the report."""
		self.assertEqual(unbilled_amount(TRUCK, 100.5), 0.0)
		self.assertEqual(unbilled_amount(TRUCK, 140), 0.0)
		self.assertGreaterEqual(
			unbilled_amount(TRUCK, 140),
			0.0,
			"over-billing must not produce negative exposure that cancels out other rows",
		)

	def test_blank_per_billed_is_treated_as_fully_unbilled(self):
		"""None and "" mean "nothing was ever billed against this receipt" in
		practice — a receipt ERPNext has not touched since submit. We deliberately
		read them as 0% billed, i.e. maximum exposure: over-stating is visible in
		the SRBNB difference, under-stating is invisible and hides a real debt."""
		self.assertEqual(unbilled_amount(TRUCK, None), TRUCK)
		self.assertEqual(unbilled_amount(TRUCK, ""), TRUCK)

	def test_junk_per_billed_is_treated_as_fully_unbilled(self):
		"""Same direction for an unparseable value: degrade towards reporting the
		exposure, never towards deleting it. And never raise — one bad row must not
		take down the whole report."""
		for junk in ("abc", "50%", object(), [], {}):
			with self.subTest(per_billed=junk):
				self.assertEqual(unbilled_amount(TRUCK, junk), TRUCK)

	def test_negative_per_billed_is_treated_as_fully_unbilled(self):
		"""A negative percentage is corrupt data; it must not inflate the exposure
		above the value of the goods either (that would over-state SRBNB)."""
		self.assertEqual(unbilled_amount(TRUCK, -20), TRUCK)

	def test_unreadable_base_value_degrades_to_zero_instead_of_raising(self):
		"""Nothing in this module may blow up a report. A row with no readable
		company-currency value contributes nothing and the report still renders."""
		self.assertEqual(unbilled_amount(None, 0), 0.0)
		self.assertEqual(unbilled_amount("", 0), 0.0)
		self.assertEqual(unbilled_amount("not money", 0), 0.0)
		self.assertEqual(unbilled_amount(float("nan"), 0), 0.0)
		self.assertEqual(unbilled_amount(float("inf"), 0), 0.0)

	def test_negative_base_value_floors_at_zero(self):
		"""Return receipts are filtered out upstream, so a negative base value here
		is bad data. Reporting it as negative exposure would quietly net down the
		total; the floor keeps the total an honest upper bound."""
		self.assertEqual(unbilled_amount(-TRUCK, 0), 0.0)

	def test_money_is_rounded_to_two_decimals(self):
		"""Float noise must not reach the screen or the SRBNB comparison: the raw
		product below is 6.666666699999999, and an unrounded column of those is what
		makes a reconciliation difference look real when it is not."""
		self.assertEqual(unbilled_amount(10.0, 33.333333), 6.67)
		self.assertEqual(unbilled_amount(100.129, 0), 100.13)


class TestBilledPercent(unittest.TestCase):
	def test_percentage_is_clamped_into_the_legal_range(self):
		"""The clamp is the single place the 0..100 rule lives; unbilled_amount and
		anything else added later must not re-derive it."""
		self.assertEqual(billed_percent(0), 0.0)
		self.assertEqual(billed_percent(37.5), 37.5)
		self.assertEqual(billed_percent(100), 100.0)
		self.assertEqual(billed_percent(101), 100.0)
		self.assertEqual(billed_percent(-5), 0.0)
		self.assertEqual(billed_percent(None), 0.0)


class TestBuckets(unittest.TestCase):
	def test_bucket_boundaries_are_inclusive_and_leave_no_gap(self):
		"""The escalation policy is written on these edges: over 30 days chase the
		supplier, over 60 get written confirmation, over 90 escalate. An off-by-one
		moves a receipt out of the bucket that would have triggered the phone call."""
		self.assertEqual(bucket_of(0), "b_0_30", "a receipt posted today is 0 days old, not unbucketed")
		self.assertEqual(bucket_of(30), "b_0_30", "day 30 is still inside the normal cycle")
		self.assertEqual(bucket_of(31), "b_31_60", "day 31 is the first chase-the-supplier day")
		self.assertEqual(bucket_of(60), "b_31_60")
		self.assertEqual(bucket_of(61), "b_61_90", "day 61 needs written confirmation")
		self.assertEqual(bucket_of(90), "b_61_90")
		self.assertEqual(bucket_of(91), "b_90_plus", "day 91 escalates")
		self.assertEqual(bucket_of(3650), "b_90_plus")

	def test_bucket_bounds_table_agrees_with_bucket_of(self):
		"""The endpoint's SQL bucket filter is built from BUCKET_BOUNDS while the
		rows are bucketed by bucket_of. If the two disagree, filtering to a bucket
		returns rows labelled with a different bucket — so pin them together."""
		for age in range(0, 200):
			hits = [k for k in BUCKETS if _bounds_match(k, age)]
			self.assertEqual(
				hits,
				[bucket_of(age)],
				f"age {age}: the SQL bounds must select exactly the bucket bucket_of() labels it "
				f"with — overlapping bounds return rows tagged as another bucket, a gap returns none",
			)
		self.assertEqual(tuple(BUCKET_BOUNDS), BUCKETS, "every bucket key needs SQL bounds")

	def test_unreadable_or_future_age_lands_in_the_youngest_bucket(self):
		"""A back-dated report date can age a row negatively. It must still land in
		a bucket, because the buckets have to add up to the total."""
		self.assertEqual(bucket_of(-5), "b_0_30")
		self.assertEqual(bucket_of(None), "b_0_30")
		self.assertEqual(bucket_of("junk"), "b_0_30")


class TestAnnotateRows(unittest.TestCase):
	def _raw(self):
		return [
			{"name": "PR-A", "base_grand_total": TRUCK, "per_billed": 0, "age_days": 10},
			{"name": "PR-B", "base_grand_total": TRUCK, "per_billed": 50, "age_days": 45},
			{"name": "PR-C", "base_grand_total": TRUCK, "per_billed": None, "age_days": 200},
		]

	def test_annotation_adds_the_three_report_fields_and_keeps_the_rest(self):
		rows = annotate_rows(self._raw())
		self.assertEqual([r["name"] for r in rows], ["PR-A", "PR-B", "PR-C"], "SQL row order is preserved")
		self.assertEqual(rows[0]["bucket"], "b_0_30")
		self.assertEqual(rows[0]["unbilled_amount"], TRUCK)
		self.assertEqual(rows[1]["bucket"], "b_31_60")
		self.assertEqual(rows[1]["unbilled_amount"], 60_000_000.0)
		self.assertEqual(rows[2]["bucket"], "b_90_plus")
		self.assertEqual(rows[2]["unbilled_amount"], TRUCK, "a NULL per_billed row is fully exposed")

	def test_annotation_does_not_mutate_the_caller_rows(self):
		"""The endpoint passes a live SQL result; silently rewriting it would make
		the second pass over the same rows compute different numbers."""
		raw = self._raw()
		annotate_rows(raw)
		self.assertNotIn("unbilled_amount", raw[0])
		self.assertNotIn("bucket", raw[0])

	def test_negative_age_is_clamped_for_display(self):
		rows = annotate_rows([{"base_grand_total": TRUCK, "per_billed": 0, "age_days": -3}])
		self.assertEqual(rows[0]["age_days"], 0, "a report never shows a negative age")


class TestSummarise(unittest.TestCase):
	def _annotated(self):
		return annotate_rows(
			[
				{"base_grand_total": TRUCK, "per_billed": 0, "age_days": 5},  # 120M, b_0_30
				{"base_grand_total": TRUCK, "per_billed": 50, "age_days": 40},  # 60M, b_31_60
				{"base_grand_total": TRUCK, "per_billed": 75, "age_days": 75},  # 30M, b_61_90
				{"base_grand_total": TRUCK, "per_billed": None, "age_days": 400},  # 120M, b_90_plus
			]
		)

	def test_totals_split_by_bucket_and_count_the_receipts(self):
		"""These five numbers are the report header. The bucket split is what tells
		the owner whether the exposure is this month's paperwork or last quarter's."""
		s = summarise(self._annotated())
		self.assertEqual(s["b_0_30"], 120_000_000.0)
		self.assertEqual(s["b_31_60"], 60_000_000.0)
		self.assertEqual(s["b_61_90"], 30_000_000.0)
		self.assertEqual(s["b_90_plus"], 120_000_000.0)
		self.assertEqual(s["total_unbilled"], 330_000_000.0)
		self.assertEqual(s["receipts"], 4, "receipts is the row count the screen shows")

	def test_total_equals_the_sum_of_the_buckets(self):
		"""The screen prints the total and the split side by side, and the total is
		what gets compared against the SRBNB ledger. Money that reached one and not
		the other would be invisible in both."""
		s = summarise(self._annotated())
		self.assertAlmostEqual(s["total_unbilled"], sum(s[k] for k in BUCKETS), places=2)

	def test_a_row_with_a_junk_bucket_is_rebucketed_not_dropped(self):
		"""Defends the identity above against a row whose bucket key is missing or
		misspelled: its money stays in the split instead of leaking into the total
		alone."""
		rows = [
			{"unbilled_amount": 1000.0, "age_days": 5, "bucket": "b_0_30"},
			{"unbilled_amount": 2000.0, "age_days": 120, "bucket": "not_a_bucket"},
			{"unbilled_amount": 4000.0, "age_days": 95},
		]
		s = summarise(rows)
		self.assertEqual(s["total_unbilled"], 7000.0)
		self.assertEqual(sum(s[k] for k in BUCKETS), 7000.0)
		self.assertEqual(s["b_90_plus"], 6000.0, "both aged rows belong in the escalation bucket")

	def test_zero_exposure_rows_still_count_as_receipts(self):
		"""The count is the list length, so the screen's header cannot disagree with
		the number of lines under it."""
		s = summarise(annotate_rows([{"base_grand_total": TRUCK, "per_billed": 100, "age_days": 5}]))
		self.assertEqual(s["total_unbilled"], 0.0)
		self.assertEqual(s["receipts"], 1)

	def test_empty_and_none_input_are_safe(self):
		"""An empty report is the good case; it must render, not error."""
		for empty in ([], None, ()):
			with self.subTest(rows=empty):
				s = summarise(empty)
				self.assertEqual(s["total_unbilled"], 0.0)
				self.assertEqual(s["receipts"], 0)
				self.assertEqual([s[k] for k in BUCKETS], [0.0, 0.0, 0.0, 0.0])
		self.assertEqual(annotate_rows(None), [])

	def test_unreadable_amount_on_a_row_does_not_poison_the_total(self):
		"""One corrupt row must cost its own value, not the whole report."""
		s = summarise(
			[
				{"unbilled_amount": "junk", "age_days": 5},
				{"unbilled_amount": float("nan"), "age_days": 5},
				{"unbilled_amount": 500.0, "age_days": 5},
			]
		)
		self.assertEqual(s["total_unbilled"], 500.0)
		self.assertEqual(s["receipts"], 3)


class TestReconciliationComparable(unittest.TestCase):
	"""When the SRBNB ledger balance may be subtracted from this report's total.

	The screen renders a non-zero difference as an accusation that someone posted
	outside the receipt/invoice chain. These tests defend the dates on which that
	accusation is allowed to be made at all.
	"""

	def test_a_run_dated_today_is_comparable(self):
		"""The default view must never degrade into "cannot measure" — it is the
		one the report is opened on, and it is the one that catches the real
		break."""
		self.assertTrue(reconciliation_comparable("2026-08-17", "2026-08-17"))

	def test_a_back_dated_run_is_not_comparable_because_billing_state_is_current(self):
		"""The ledger half is summed up to the cut-off; the receipt half is valued
		from per_billed, which ERPNext overwrites in place and which carries no
		date. So their difference on a past date is the invoicing done since then,
		and reporting it as a ledger break accuses an accountant of ordinary work.
		Fails the moment the predicate is loosened to `<=` or dropped."""
		self.assertFalse(reconciliation_comparable("2026-07-31", "2026-08-17"))
		self.assertFalse(reconciliation_comparable("2026-08-16", "2026-08-17"))

	def test_a_forward_dated_run_stays_comparable_because_receipts_cannot_be_future_dated(self):
		"""ERPNext throws on a future posting date for a Purchase Receipt, so no
		receipt can appear between today and a future cut-off and both halves
		still describe the same set. This is why the predicate is `>=` and not
		`==`: tightening it to equality would blank the difference for a reason
		that does not exist."""
		self.assertTrue(reconciliation_comparable("2026-08-18", "2026-08-17"))
		self.assertTrue(reconciliation_comparable("2027-01-01", "2026-08-17"))

	def test_the_boundary_is_the_day_and_not_the_year_or_the_month(self):
		"""ISO strings are compared lexicographically, which only agrees with date
		order while the format is zero-padded YYYY-MM-DD. A caller passing a
		display format (17.08.2026) would silently invert the whole rule, so the
		boundary is pinned across a month and a year edge."""
		self.assertFalse(reconciliation_comparable("2026-07-31", "2026-08-01"))
		self.assertTrue(reconciliation_comparable("2026-08-01", "2026-07-31"))
		self.assertFalse(reconciliation_comparable("2025-12-31", "2026-01-01"))
		self.assertTrue(reconciliation_comparable("2026-01-01", "2025-12-31"))


if __name__ == "__main__":
	unittest.main()
