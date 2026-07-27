"""Unit tests for the pure period-close decision logic.

These import only ``stabler.api._period_close`` (zero Frappe), so they run
under plain ``python -m unittest`` as well as ``bench run-tests``.

Coverage checklist
------------------
* Blank / None close_date  →  always open (never blocks).
* Boundary is inclusive: posting_date == close_date  →  closed.
* One day after close_date  →  open.
* One day before close_date  →  closed.
* ``has_override=True``  →  always allowed, regardless of dates.
* String ISO dates are coerced correctly.
* datetime.datetime objects are accepted.
* Garbage inputs do not crash and resolve to "open".
* ValueError message mentions both dates.
"""

from __future__ import annotations

import datetime
import unittest

from stabler.api._period_close import (
	_to_date,
	assert_posting_allowed,
	is_closed,
)

# ---------------------------------------------------------------------------
# _to_date coercion
# ---------------------------------------------------------------------------

class ToDateTest(unittest.TestCase):
	def test_none_returns_none(self):
		self.assertIsNone(_to_date(None))

	def test_empty_string_returns_none(self):
		self.assertIsNone(_to_date(""))
		self.assertIsNone(_to_date("   "))

	def test_date_object_passthrough(self):
		d = datetime.date(2025, 3, 31)
		self.assertEqual(_to_date(d), d)

	def test_datetime_object_returns_date(self):
		dt = datetime.datetime(2025, 3, 31, 23, 59, 59)
		self.assertEqual(_to_date(dt), datetime.date(2025, 3, 31))

	def test_iso_string_parsed(self):
		self.assertEqual(_to_date("2025-03-31"), datetime.date(2025, 3, 31))

	def test_iso_string_with_whitespace(self):
		self.assertEqual(_to_date("  2025-03-31  "), datetime.date(2025, 3, 31))

	def test_garbage_string_returns_none(self):
		self.assertIsNone(_to_date("not-a-date"))
		self.assertIsNone(_to_date("31/03/2025"))
		self.assertIsNone(_to_date("2025-13-01"))	# month 13 invalid

	def test_integer_returns_none(self):
		self.assertIsNone(_to_date(20250331))

	def test_float_returns_none(self):
		self.assertIsNone(_to_date(3.14))


# ---------------------------------------------------------------------------
# is_closed
# ---------------------------------------------------------------------------

class IsClosedTest(unittest.TestCase):

	# --- close_date absent → always open ---

	def test_none_close_date_always_open(self):
		self.assertFalse(is_closed("2020-01-01", None))

	def test_empty_string_close_date_always_open(self):
		self.assertFalse(is_closed("2020-01-01", ""))

	def test_blank_whitespace_close_date_always_open(self):
		self.assertFalse(is_closed("2020-01-01", "   "))

	# --- boundary: inclusive ---

	def test_posting_equals_close_is_closed(self):
		self.assertTrue(is_closed("2025-03-31", "2025-03-31"))

	def test_posting_before_close_is_closed(self):
		self.assertTrue(is_closed("2025-03-30", "2025-03-31"))

	def test_posting_day_after_close_is_open(self):
		self.assertFalse(is_closed("2025-04-01", "2025-03-31"))

	def test_posting_far_after_close_is_open(self):
		self.assertFalse(is_closed("2026-01-01", "2025-03-31"))

	# --- string coercion ---

	def test_string_dates_coerced(self):
		self.assertTrue(is_closed("2025-01-15", "2025-03-31"))
		self.assertFalse(is_closed("2025-04-01", "2025-03-31"))

	def test_date_objects_accepted(self):
		self.assertTrue(
			is_closed(
				datetime.date(2025, 3, 31),
				datetime.date(2025, 3, 31),
			)
		)

	def test_datetime_objects_accepted(self):
		self.assertTrue(
			is_closed(
				datetime.datetime(2025, 3, 31, 23, 59),
				datetime.datetime(2025, 3, 31, 0, 0),
			)
		)

	# --- garbage dates are safe (never crash, resolve to open) ---

	def test_garbage_posting_date_is_open(self):
		self.assertFalse(is_closed("not-a-date", "2025-03-31"))

	def test_garbage_close_date_is_open(self):
		self.assertFalse(is_closed("2025-03-01", "rubbish"))

	def test_both_garbage_is_open(self):
		self.assertFalse(is_closed(None, None))
		self.assertFalse(is_closed("", ""))
		self.assertFalse(is_closed("bad", "bad"))

	def test_integer_dates_are_open(self):
		self.assertFalse(is_closed(20250101, 20251231))

	# --- end-of-year boundary ---

	def test_year_boundary_open(self):
		# New year posting against a Dec-31 close date  →  open
		self.assertFalse(is_closed("2026-01-01", "2025-12-31"))

	def test_year_boundary_closed(self):
		# Dec 31 posting against a Dec-31 close date  →  closed
		self.assertTrue(is_closed("2025-12-31", "2025-12-31"))


# ---------------------------------------------------------------------------
# assert_posting_allowed
# ---------------------------------------------------------------------------

class AssertPostingAllowedTest(unittest.TestCase):

	# --- allowed cases (no exception raised) ---

	def test_no_close_date_always_allowed(self):
		assert_posting_allowed("2025-01-01", None)
		assert_posting_allowed("2025-01-01", "")

	def test_future_posting_allowed(self):
		assert_posting_allowed("2025-04-01", "2025-03-31")

	def test_same_day_as_close_raises(self):
		with self.assertRaises(ValueError):
			assert_posting_allowed("2025-03-31", "2025-03-31")

	# --- override bypasses guard ---

	def test_override_allows_closed_period(self):
		# Must NOT raise even though period is closed
		assert_posting_allowed("2025-01-01", "2025-03-31", has_override=True)

	def test_override_allows_on_boundary(self):
		assert_posting_allowed("2025-03-31", "2025-03-31", has_override=True)

	def test_override_false_is_same_as_default(self):
		with self.assertRaises(ValueError):
			assert_posting_allowed("2025-03-31", "2025-03-31", has_override=False)

	# --- ValueError message quality ---

	def test_error_message_contains_both_dates(self):
		try:
			assert_posting_allowed("2025-01-15", "2025-03-31")
			self.fail("Expected ValueError")
		except ValueError as exc:
			msg = str(exc)
			self.assertIn("2025-01-15", msg)
			self.assertIn("2025-03-31", msg)

	def test_error_message_mentions_administrator(self):
		try:
			assert_posting_allowed("2025-01-15", "2025-03-31")
		except ValueError as exc:
			self.assertIn("administrator", str(exc).lower())

	# --- garbage never raises ---

	def test_garbage_posting_date_does_not_raise(self):
		# Unparseable dates → open; function must not crash
		assert_posting_allowed("not-a-date", "2025-03-31")

	def test_garbage_close_date_does_not_raise(self):
		assert_posting_allowed("2025-01-01", "garbage")

	def test_none_both_does_not_raise(self):
		assert_posting_allowed(None, None)

	# --- string/object coercion round-trips ---

	def test_string_coercion_raises_correctly(self):
		with self.assertRaises(ValueError):
			assert_posting_allowed("2025-02-28", "2025-03-31")

	def test_date_object_coercion_raises_correctly(self):
		with self.assertRaises(ValueError):
			assert_posting_allowed(
				datetime.date(2025, 2, 28),
				datetime.date(2025, 3, 31),
			)

	def test_datetime_object_coercion_raises_correctly(self):
		with self.assertRaises(ValueError):
			assert_posting_allowed(
				datetime.datetime(2025, 2, 28, 10, 0),
				datetime.datetime(2025, 3, 31, 0, 0),
			)


if __name__ == "__main__":
	unittest.main()
