"""Unit tests for the pure three-way-match logic (no Frappe, no I/O)."""
from __future__ import annotations

import unittest

from stabler.api._three_way_match import (
	BLOCK,
	WARN,
	evaluate_invoice,
	evaluate_line,
)

TOL = {"qty_tol_pct": 5, "rate_tol_pct": 2}


class RateVarianceTest(unittest.TestCase):
	def test_within_tolerance_ok(self):
		line = {"idx": 1, "item_code": "X", "bill_qty": 10, "bill_rate": 101, "po_qty": 10, "po_rate": 100, "received_qty": 10}
		self.assertEqual(evaluate_line(line, **TOL), [])  # 1% < 2%

	def test_over_tolerance_blocks(self):
		line = {"idx": 1, "item_code": "X", "bill_qty": 10, "bill_rate": 110, "po_qty": 10, "po_rate": 100, "received_qty": 10}
		exc = evaluate_line(line, **TOL)
		self.assertTrue(any(e["type"] == "rate_variance" and e["severity"] == BLOCK for e in exc))

	def test_no_po_rate_skips(self):
		line = {"idx": 1, "bill_qty": 5, "bill_rate": 999}  # no po_rate
		self.assertEqual(evaluate_line(line, **TOL), [])


class OverReceivedTest(unittest.TestCase):
	def test_billing_more_than_received_blocks(self):
		line = {"idx": 1, "item_code": "X", "bill_qty": 12, "bill_rate": 100, "po_qty": 20, "po_rate": 100, "received_qty": 10}
		exc = evaluate_line(line, **TOL)
		self.assertTrue(any(e["type"] == "over_received" and e["severity"] == BLOCK for e in exc))

	def test_billing_within_received_ok(self):
		line = {"idx": 1, "bill_qty": 10, "bill_rate": 100, "po_qty": 20, "po_rate": 100, "received_qty": 10}
		exc = [e for e in evaluate_line(line, **TOL) if e["type"] == "over_received"]
		self.assertEqual(exc, [])

	def test_no_receipt_skips_over_received(self):
		line = {"idx": 1, "bill_qty": 99, "bill_rate": 100, "po_qty": 100, "po_rate": 100}  # no received_qty
		exc = [e for e in evaluate_line(line, **TOL) if e["type"] == "over_received"]
		self.assertEqual(exc, [])


class OverOrderedTest(unittest.TestCase):
	def test_over_ordered_is_warn_not_block(self):
		line = {"idx": 1, "bill_qty": 30, "bill_rate": 100, "po_qty": 20, "po_rate": 100}
		exc = [e for e in evaluate_line(line, **TOL) if e["type"] == "over_ordered"]
		self.assertEqual(len(exc), 1)
		self.assertEqual(exc[0]["severity"], WARN)


class InvoiceTest(unittest.TestCase):
	def test_clean_invoice_no_block(self):
		lines = [
			{"idx": 1, "bill_qty": 10, "bill_rate": 100, "po_qty": 10, "po_rate": 100, "received_qty": 10},
			{"idx": 2, "bill_qty": 5, "bill_rate": 50, "po_qty": 5, "po_rate": 50, "received_qty": 5},
		]
		res = evaluate_invoice(lines, **TOL)
		self.assertFalse(res["has_block"])
		self.assertEqual(res["blocking"], [])

	def test_mixed_invoice_flags_blocking(self):
		lines = [
			{"idx": 1, "bill_qty": 10, "bill_rate": 100, "po_qty": 10, "po_rate": 100, "received_qty": 10},
			{"idx": 2, "bill_qty": 12, "bill_rate": 100, "po_qty": 20, "po_rate": 100, "received_qty": 10},  # over-received
		]
		res = evaluate_invoice(lines, **TOL)
		self.assertTrue(res["has_block"])
		self.assertEqual(len(res["blocking"]), 1)
		self.assertEqual(res["blocking"][0]["idx"], 2)

	def test_empty_invoice(self):
		self.assertFalse(evaluate_invoice([], **TOL)["has_block"])


if __name__ == "__main__":
	unittest.main()
