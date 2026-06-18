"""Unit tests for the pure sales-margin math (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.api._sales_margin import attach_margins, margin_fields


class TestMarginFields(unittest.TestCase):
	def test_basic_positive_margin(self):
		self.assertEqual(margin_fields(1000, 600), {"margin": 400.0, "margin_pct": 40.0})

	def test_negative_margin_below_cost(self):
		# Sold under cost — margin and % go negative.
		self.assertEqual(margin_fields(100, 150), {"margin": -50.0, "margin_pct": -50.0})

	def test_zero_revenue_no_divide_by_zero(self):
		self.assertEqual(margin_fields(0, 0), {"margin": 0.0, "margin_pct": 0.0})
		# Revenue 0 but cost incurred (e.g. free sample): margin negative, pct 0 (no base).
		self.assertEqual(margin_fields(0, 25), {"margin": -25.0, "margin_pct": 0.0})

	def test_none_inputs_treated_as_zero(self):
		self.assertEqual(margin_fields(None, None), {"margin": 0.0, "margin_pct": 0.0})
		self.assertEqual(margin_fields(500, None), {"margin": 500.0, "margin_pct": 100.0})

	def test_rounding(self):
		# margin rounds to 2dp, pct to 1dp.
		out = margin_fields(333.333, 111.111)
		self.assertEqual(out["margin"], 222.22)
		self.assertEqual(out["margin_pct"], 66.7)

	def test_full_margin_when_no_cost(self):
		self.assertEqual(margin_fields(800, 0), {"margin": 800.0, "margin_pct": 100.0})


class TestAttachMargins(unittest.TestCase):
	def test_attaches_to_each_row_default_keys(self):
		rows = [
			{"item_code": "A", "base_net_revenue": 1000, "cogs": 600},
			{"item_code": "B", "base_net_revenue": 200, "cogs": 250},
		]
		attach_margins(rows)
		self.assertEqual(rows[0]["margin"], 400.0)
		self.assertEqual(rows[0]["margin_pct"], 40.0)
		self.assertEqual(rows[1]["margin"], -50.0)
		self.assertEqual(rows[1]["margin_pct"], -25.0)

	def test_missing_keys_default_zero(self):
		rows = [{"customer": "X"}]
		attach_margins(rows)
		self.assertEqual(rows[0]["margin"], 0.0)
		self.assertEqual(rows[0]["margin_pct"], 0.0)

	def test_custom_keys(self):
		rows = [{"rev": 1000, "cost": 750}]
		attach_margins(rows, revenue_key="rev", cogs_key="cost")
		self.assertEqual(rows[0]["margin"], 250.0)
		self.assertEqual(rows[0]["margin_pct"], 25.0)


if __name__ == "__main__":
	unittest.main()
