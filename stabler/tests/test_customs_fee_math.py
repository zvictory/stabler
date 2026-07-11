"""Unit tests for the BRV customs-clearance fee math (Frappe-free).

Covers BRV effective-date selection, tier-multiplier edges, the off-hours
surcharge, Decimal exactness, and the missing-config error paths.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_customs_fee_math -v
"""

from __future__ import annotations

import datetime
import unittest
from decimal import Decimal

from stabler.stabler.imports_module import customs_fee_math as cfm

_D = datetime.date

_BRV_ROWS = [
	{"effective_date": _D(2024, 1, 1), "value_uzs": Decimal("330000")},
	{"effective_date": _D(2025, 4, 1), "value_uzs": Decimal("375000")},
	{"effective_date": _D(2026, 4, 1), "value_uzs": Decimal("412000")},
]

# Contiguous tiers with an open-ended top tier.
_TIERS = [
	{"min_value_usd": Decimal("0"), "max_value_usd": Decimal("50000"), "multiplier": Decimal("1")},
	{"min_value_usd": Decimal("50000"), "max_value_usd": Decimal("100000"), "multiplier": Decimal("2")},
	{"min_value_usd": Decimal("100000"), "max_value_usd": None, "multiplier": Decimal("3")},
]


class TestEffectiveBrv(unittest.TestCase):
	def test_picks_latest_on_or_before_date(self):
		self.assertEqual(cfm.effective_brv(_BRV_ROWS, _D(2025, 6, 1)), Decimal("375000"))

	def test_exact_effective_date_matches(self):
		self.assertEqual(cfm.effective_brv(_BRV_ROWS, _D(2026, 4, 1)), Decimal("412000"))

	def test_latest_row_used_for_future_date(self):
		self.assertEqual(cfm.effective_brv(_BRV_ROWS, _D(2030, 1, 1)), Decimal("412000"))

	def test_raises_before_any_row(self):
		with self.assertRaises(ValueError):
			cfm.effective_brv(_BRV_ROWS, _D(2023, 1, 1))

	def test_raises_on_empty_rows(self):
		with self.assertRaises(ValueError):
			cfm.effective_brv([], _D(2025, 6, 1))

	def test_iso_string_dates_sort_correctly(self):
		rows = [
			{"effective_date": "2024-01-01", "value_uzs": 330000},
			{"effective_date": "2025-04-01", "value_uzs": 375000},
		]
		self.assertEqual(cfm.effective_brv(rows, "2025-05-01"), Decimal("375000"))


class TestTierMultiplier(unittest.TestCase):
	def test_bottom_tier(self):
		self.assertEqual(cfm.tier_multiplier(_TIERS, Decimal("10000")), Decimal("1"))

	def test_min_boundary_inclusive(self):
		# 50000 is the max of tier 1 and the min of tier 2 — the first matching
		# row (tier 1, ordered by min asc) wins.
		self.assertEqual(cfm.tier_multiplier(_TIERS, Decimal("50000")), Decimal("1"))

	def test_just_above_boundary(self):
		self.assertEqual(cfm.tier_multiplier(_TIERS, Decimal("50000.01")), Decimal("2"))

	def test_open_ended_top_tier(self):
		self.assertEqual(cfm.tier_multiplier(_TIERS, Decimal("5000000")), Decimal("3"))

	def test_top_tier_min_boundary(self):
		self.assertEqual(cfm.tier_multiplier(_TIERS, Decimal("100000")), Decimal("2"))

	def test_raises_when_no_tier_covers(self):
		gapped = [
			{"min_value_usd": Decimal("1000"), "max_value_usd": Decimal("2000"), "multiplier": Decimal("1")}
		]
		with self.assertRaises(ValueError):
			cfm.tier_multiplier(gapped, Decimal("5000"))
		with self.assertRaises(ValueError):
			cfm.tier_multiplier(gapped, Decimal("500"))

	def test_accepts_float_and_int_inputs(self):
		self.assertEqual(cfm.tier_multiplier(_TIERS, 75000), Decimal("2"))


class TestCustomsFee(unittest.TestCase):
	def test_base_fee_no_surcharge(self):
		res = cfm.customs_fee(Decimal("75000"), _TIERS, Decimal("375000"))
		self.assertEqual(res["multiplier"], Decimal("2"))
		self.assertEqual(res["base_fee"], Decimal("750000"))
		self.assertEqual(res["off_hours_surcharge"], Decimal("0"))
		self.assertEqual(res["fee_uzs"], Decimal("750000"))

	def test_off_hours_adds_quarter_brv(self):
		res = cfm.customs_fee(Decimal("75000"), _TIERS, Decimal("375000"), off_hours=True)
		# base 2x375000 = 750000, surcharge 0.25x375000 = 93750
		self.assertEqual(res["off_hours_surcharge"], Decimal("93750.00"))
		self.assertEqual(res["fee_uzs"], Decimal("843750.00"))

	def test_returns_decimals(self):
		res = cfm.customs_fee(10000, _TIERS, 375000, off_hours=True)
		for key in ("fee_uzs", "multiplier", "brv_value", "base_fee", "off_hours_surcharge"):
			self.assertIsInstance(res[key], Decimal, key)

	def test_top_tier_fee(self):
		res = cfm.customs_fee(Decimal("250000"), _TIERS, Decimal("412000"))
		self.assertEqual(res["fee_uzs"], Decimal("1236000"))


if __name__ == "__main__":
	unittest.main()
