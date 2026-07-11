"""Unit tests for the PR-per-TruckReceipt math (Frappe-free).

Covers PO-rate resolution, batch naming, the Good-only qty rule, the cold-chain
temperature check, and the Purchase Receipt payload shape.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_receipt_math -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import receipt_math as rm


class TestGoodQty(unittest.TestCase):
	def test_only_good_condition_enters_pr(self):
		self.assertEqual(rm.good_qty(1000.0, "Good"), 1000.0)
		self.assertEqual(rm.good_qty(1000.0, "Damaged"), 0.0)
		self.assertEqual(rm.good_qty(1000.0, "Rejected"), 0.0)

	def test_case_insensitive(self):
		self.assertEqual(rm.good_qty(50.0, "good"), 50.0)


class TestTemperatureOk(unittest.TestCase):
	def test_within_range(self):
		self.assertTrue(rm.temperature_ok(-20, -22, -18))

	def test_out_of_range(self):
		self.assertFalse(rm.temperature_ok(-5, -22, -18))
		self.assertFalse(rm.temperature_ok(0, -22, -18))

	def test_no_reading_or_no_range_passes(self):
		self.assertTrue(rm.temperature_ok(None, -22, -18))
		self.assertTrue(rm.temperature_ok("", -22, -18))
		self.assertTrue(rm.temperature_ok(-5, None, None))


class TestBatchName(unittest.TestCase):
	def test_container_prefix(self):
		self.assertEqual(
			rm.batch_name("MSKU1234567", "CI-2026-00001", "BEEF-CUBE", "2026-07-10"),
			"MSKU1234567-BEEF-CUBE-2026-07-10",
		)

	def test_falls_back_to_ci(self):
		self.assertEqual(
			rm.batch_name(None, "CI-2026-00001", "BEEF-CUBE", "2026-07-10"),
			"CI-2026-00001-BEEF-CUBE-2026-07-10",
		)


class TestResolvePoRate(unittest.TestCase):
	def _rows(self):
		return [
			{"purchase_order": "PO-1", "purchase_order_item": "row-a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-1", "purchase_order_item": "row-b", "item_code": "LAMB", "rate": 6.0},
		]

	def test_single_match_resolves_rate_and_linkage(self):
		res = rm.resolve_po_rate("BEEF", self._rows())
		self.assertEqual(res["rate"], 4.5)
		self.assertEqual(res["purchase_order"], "PO-1")
		self.assertEqual(res["purchase_order_item"], "row-a")
		self.assertIsNone(res["warning"])

	def test_missing_item_zero_rate_with_warning(self):
		res = rm.resolve_po_rate("CHICKEN", self._rows())
		self.assertEqual(res["rate"], 0.0)
		self.assertIsNone(res["purchase_order"])
		self.assertIn("No linked Purchase Order line", res["warning"])

	def test_ambiguous_same_rate_uses_rate_no_linkage(self):
		rows = [
			{"purchase_order": "PO-1", "purchase_order_item": "a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-2", "purchase_order_item": "b", "item_code": "BEEF", "rate": 4.5},
		]
		res = rm.resolve_po_rate("BEEF", rows)
		self.assertEqual(res["rate"], 4.5)
		self.assertIsNone(res["purchase_order_item"])
		self.assertIn("same rate", res["warning"])

	def test_ambiguous_diff_rate_zero(self):
		rows = [
			{"purchase_order": "PO-1", "purchase_order_item": "a", "item_code": "BEEF", "rate": 4.5},
			{"purchase_order": "PO-2", "purchase_order_item": "b", "item_code": "BEEF", "rate": 5.0},
		]
		res = rm.resolve_po_rate("BEEF", rows)
		self.assertEqual(res["rate"], 0.0)
		self.assertIn("differing rates", res["warning"])


class TestBuildPrPayload(unittest.TestCase):
	def _line(self, item, qty, batch=None, po=None, poi=None):
		return rm.build_pr_line(
			item_code=item,
			qty=qty,
			rate=4.5,
			warehouse="WH - MSA",
			purchase_order=po,
			purchase_order_item=poi,
			batch_no=batch,
		)

	def test_zero_qty_lines_dropped(self):
		lines = [self._line("BEEF", 1000.0), self._line("LAMB", 0.0)]
		payload = rm.build_pr_payload(
			company="MSA",
			supplier="IRAN MEAT CO",
			posting_date="2026-07-10",
			currency="USD",
			warehouse="WH - MSA",
			lines=lines,
			truck_receipt_name="TRK-RCV-2026-00001",
		)
		self.assertEqual(len(payload["items"]), 1)
		self.assertEqual(payload["items"][0]["item_code"], "BEEF")
		self.assertEqual(payload["items"][0]["uom"], "Kg")
		self.assertEqual(payload["currency"], "USD")
		self.assertEqual(payload["set_posting_time"], 1)
		self.assertNotIn("docstatus", payload)

	def test_none_when_nothing_receivable(self):
		payload = rm.build_pr_payload(
			company="MSA",
			supplier="IRAN MEAT CO",
			posting_date="2026-07-10",
			currency="USD",
			warehouse="WH - MSA",
			lines=[self._line("BEEF", 0.0)],
			truck_receipt_name="TRK-RCV-2026-00001",
		)
		self.assertIsNone(payload)

	def test_batch_and_po_linkage_carried(self):
		line = self._line("BEEF", 1000.0, batch="B1", po="PO-1", poi="row-a")
		self.assertEqual(line["batch_no"], "B1")
		self.assertEqual(line["purchase_order"], "PO-1")
		self.assertEqual(line["purchase_order_item"], "row-a")
		# No batch -> no batch_no key at all.
		self.assertNotIn("batch_no", self._line("BEEF", 1000.0))


if __name__ == "__main__":
	unittest.main()
