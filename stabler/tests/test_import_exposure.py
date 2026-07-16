"""Unit tests for stabler.api._import_exposure (WP-I4, Frappe-free).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_import_exposure -v
"""

from __future__ import annotations

import unittest

from stabler.api._import_exposure import (
	classify_method,
	exposure_summary,
	open_commitment,
	reconciles_gl,
	split_by_method,
)


class TestClassify(unittest.TestCase):
	def test_cash_bank_other(self):
		self.assertEqual(classify_method("Cash"), "cash")
		self.assertEqual(classify_method("bank"), "bank")
		self.assertEqual(classify_method("Receivable"), "other")
		self.assertEqual(classify_method(None), "other")
		self.assertEqual(classify_method(""), "other")


class TestSplit(unittest.TestCase):
	def test_sums_by_method(self):
		rows = [
			{"amount": 1000, "account_type": "Cash"},
			{"amount": 500, "account_type": "Cash"},
			{"amount": 4000, "account_type": "Bank"},
			{"amount": 50, "account_type": "Receivable"},
		]
		s = split_by_method(rows)
		self.assertEqual(s, {"cash": 1500.0, "bank": 4000.0, "other": 50.0})

	def test_garbage_safe(self):
		self.assertEqual(split_by_method(None), {"cash": 0.0, "bank": 0.0, "other": 0.0})
		self.assertEqual(split_by_method([{"amount": "x", "account_type": "Cash"}])["cash"], 0.0)


class TestReconcile(unittest.TestCase):
	def test_reconciles_to_gl_total(self):
		# The core invariant: cash + bank + other == GL total paid.
		by = {"cash": 1500.0, "bank": 4000.0, "other": 50.0}
		self.assertTrue(reconciles_gl(by, 5550.0))
		self.assertTrue(reconciles_gl(by, 5550.3))  # within epsilon
		self.assertFalse(reconciles_gl(by, 6000.0))  # a leak = fail


class TestOpenCommitment(unittest.TestCase):
	def test_excludes_terminal_statuses(self):
		rows = [
			{"agreed_total": 10000, "status": "IN_TRANSIT"},
			{"agreed_total": 5000, "status": "BOOKED"},
			{"agreed_total": 7000, "status": "DELIVERED_TO_UZBEKISTAN"},  # excluded
			{"agreed_total": 3000, "status": "Cancelled"},  # excluded
		]
		self.assertEqual(open_commitment(rows), 15000.0)

	def test_empty(self):
		self.assertEqual(open_commitment(None), 0.0)


class TestSummary(unittest.TestCase):
	def test_full_shape_and_reconcile(self):
		ci = [{"agreed_total": 10000, "status": "IN_TRANSIT"}]
		pays = [
			{"amount": 3000, "account_type": "Cash"},
			{"amount": 4000, "account_type": "Bank"},
		]
		s = exposure_summary(ci, pays, gl_total_paid=7000)
		self.assertEqual(s["open_commitment"], 10000.0)
		self.assertEqual(s["cash_paid"], 3000.0)
		self.assertEqual(s["bank_paid"], 4000.0)
		self.assertEqual(s["total_paid"], 7000.0)
		self.assertTrue(s["reconciles_gl"])

	def test_reconcile_fails_on_mismatch(self):
		s = exposure_summary([], [{"amount": 100, "account_type": "Cash"}], gl_total_paid=999)
		self.assertFalse(s["reconciles_gl"])


if __name__ == "__main__":
	unittest.main()
