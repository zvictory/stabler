"""Thorough unit tests for stabler.api._payroll_components.

Run with:
    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_payroll_components -v
"""

from __future__ import annotations

import unittest

from stabler.api._payroll_components import (
	QUANTITY_KEYS,
	components_total,
	mapping_complete,
	slip_variance,
	summary_to_components,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_summary(**overrides) -> dict:
	"""A PAS dict with all six quantities non-zero."""
	base = {
		"present_days": 20,
		"absent_days": 2,
		"late_count": 3,
		"late_minutes": 75,
		"late_deduction_amount": 45000.0,  # Deduction
		"overtime_minutes": 240,
		"overtime_amount": 120000.0,  # Earning
		"night_minutes": 960,
		"night_premium_amount": 18000.0,  # Earning
		"duty_supplement": 50000.0,  # Earning
		"kpi_adjustment": 30000.0,  # Earning (positive)
		"region_rate": 25000.0,  # Earning
		"unpaid_leave_days": 0,
		"paid_leave_days": 1,
	}
	base.update(overrides)
	return base


def _full_map() -> dict:
	"""A complete component_map covering all six quantity keys."""
	return {
		"late_deduction": {"salary_component": "Late Deduction", "component_type": "Deduction"},
		"overtime": {"salary_component": "Overtime Pay", "component_type": "Earning"},
		"night_premium": {"salary_component": "Night Shift Premium", "component_type": "Earning"},
		"duty_supplement": {"salary_component": "Duty Supplement", "component_type": "Earning"},
		"kpi": {"salary_component": "KPI Bonus", "component_type": "Earning"},
		"region_rate": {"salary_component": "Region Allowance", "component_type": "Earning"},
	}


def _lines_by_key(lines: list[dict]) -> dict:
	"""Index lines by quantity key for easier assertion."""
	return {ln["quantity"]: ln for ln in lines}


# ---------------------------------------------------------------------------
# QUANTITY_KEYS contract
# ---------------------------------------------------------------------------


class TestQuantityKeys(unittest.TestCase):
	def test_expected_keys_present(self):
		expected = {"late_deduction", "overtime", "night_premium", "duty_supplement", "kpi", "region_rate"}
		self.assertEqual(set(QUANTITY_KEYS), expected)

	def test_is_list(self):
		self.assertIsInstance(QUANTITY_KEYS, list)

	def test_no_duplicates(self):
		self.assertEqual(len(QUANTITY_KEYS), len(set(QUANTITY_KEYS)))


# ---------------------------------------------------------------------------
# summary_to_components — full summary, all six mapped
# ---------------------------------------------------------------------------


class TestSummaryToComponentsFull(unittest.TestCase):
	"""All six quantities non-zero, fully mapped — canonical happy-path."""

	@classmethod
	def setUpClass(cls):
		cls.lines = summary_to_components(_full_summary(), _full_map())
		cls.by_key = _lines_by_key(cls.lines)

	def test_returns_six_lines(self):
		self.assertEqual(len(self.lines), 6)

	def test_order_matches_quantity_keys(self):
		keys = [ln["quantity"] for ln in self.lines]
		self.assertEqual(keys, QUANTITY_KEYS)

	# --- late_deduction ---
	def test_late_deduction_is_deduction(self):
		self.assertEqual(self.by_key["late_deduction"]["component_type"], "Deduction")

	def test_late_deduction_salary_component(self):
		self.assertEqual(self.by_key["late_deduction"]["salary_component"], "Late Deduction")

	def test_late_deduction_abs_amount(self):
		self.assertEqual(self.by_key["late_deduction"]["abs_amount"], 45000.0)

	def test_late_deduction_no_warning(self):
		self.assertIsNone(self.by_key["late_deduction"]["warning"])

	# --- overtime ---
	def test_overtime_is_earning(self):
		self.assertEqual(self.by_key["overtime"]["component_type"], "Earning")

	def test_overtime_abs_amount(self):
		self.assertEqual(self.by_key["overtime"]["abs_amount"], 120000.0)

	# --- night_premium ---
	def test_night_premium_is_earning(self):
		self.assertEqual(self.by_key["night_premium"]["component_type"], "Earning")

	def test_night_premium_abs_amount(self):
		self.assertEqual(self.by_key["night_premium"]["abs_amount"], 18000.0)

	# --- duty_supplement ---
	def test_duty_supplement_is_earning(self):
		self.assertEqual(self.by_key["duty_supplement"]["component_type"], "Earning")

	def test_duty_supplement_abs_amount(self):
		self.assertEqual(self.by_key["duty_supplement"]["abs_amount"], 50000.0)

	# --- kpi (positive) ---
	def test_kpi_positive_is_earning(self):
		self.assertEqual(self.by_key["kpi"]["component_type"], "Earning")

	def test_kpi_positive_abs_amount(self):
		self.assertEqual(self.by_key["kpi"]["abs_amount"], 30000.0)

	# --- region_rate ---
	def test_region_rate_is_earning(self):
		self.assertEqual(self.by_key["region_rate"]["component_type"], "Earning")

	def test_region_rate_abs_amount(self):
		self.assertEqual(self.by_key["region_rate"]["abs_amount"], 25000.0)


# ---------------------------------------------------------------------------
# Negative KPI → Deduction
# ---------------------------------------------------------------------------


class TestKPISign(unittest.TestCase):
	def test_negative_kpi_becomes_deduction(self):
		summary = _full_summary(kpi_adjustment=-15000.0)
		lines = summary_to_components(summary, _full_map())
		kpi = _lines_by_key(lines)["kpi"]
		self.assertEqual(kpi["component_type"], "Deduction")

	def test_negative_kpi_abs_amount_is_positive(self):
		summary = _full_summary(kpi_adjustment=-15000.0)
		lines = summary_to_components(summary, _full_map())
		kpi = _lines_by_key(lines)["kpi"]
		self.assertEqual(kpi["abs_amount"], 15000.0)
		self.assertGreater(kpi["abs_amount"], 0)

	def test_negative_kpi_raw_amount_is_negative(self):
		summary = _full_summary(kpi_adjustment=-15000.0)
		lines = summary_to_components(summary, _full_map())
		kpi = _lines_by_key(lines)["kpi"]
		self.assertLess(kpi["amount"], 0)

	def test_positive_kpi_is_earning(self):
		summary = _full_summary(kpi_adjustment=5000.0)
		lines = summary_to_components(summary, _full_map())
		kpi = _lines_by_key(lines)["kpi"]
		self.assertEqual(kpi["component_type"], "Earning")

	def test_kpi_sign_rule_overrides_map_type(self):
		"""Even if the map says 'Deduction', positive KPI must be Earning."""
		cmap = _full_map()
		cmap["kpi"]["component_type"] = "Deduction"  # caller mistake
		summary = _full_summary(kpi_adjustment=10000.0)
		lines = summary_to_components(summary, cmap)
		# KPI sign rule always wins
		kpi = _lines_by_key(lines)["kpi"]
		self.assertEqual(kpi["component_type"], "Earning")


# ---------------------------------------------------------------------------
# Zero / None amounts are skipped
# ---------------------------------------------------------------------------


class TestZeroAmountsSkipped(unittest.TestCase):
	def test_zero_overtime_not_in_output(self):
		summary = _full_summary(overtime_amount=0.0)
		lines = summary_to_components(summary, _full_map())
		keys = [ln["quantity"] for ln in lines]
		self.assertNotIn("overtime", keys)

	def test_none_night_premium_not_in_output(self):
		summary = _full_summary(night_premium_amount=None)
		lines = summary_to_components(summary, _full_map())
		keys = [ln["quantity"] for ln in lines]
		self.assertNotIn("night_premium", keys)

	def test_zero_kpi_not_in_output(self):
		summary = _full_summary(kpi_adjustment=0.0)
		lines = summary_to_components(summary, _full_map())
		keys = [ln["quantity"] for ln in lines]
		self.assertNotIn("kpi", keys)

	def test_all_zeros_returns_empty_list(self):
		summary = _full_summary(
			late_deduction_amount=0.0,
			overtime_amount=0.0,
			night_premium_amount=0.0,
			duty_supplement=0.0,
			kpi_adjustment=0.0,
			region_rate=0.0,
		)
		lines = summary_to_components(summary, _full_map())
		self.assertEqual(lines, [])


# ---------------------------------------------------------------------------
# Unmapped non-zero quantity → warning line; also in mapping_complete
# ---------------------------------------------------------------------------


class TestUnmappedQuantity(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.partial_map = {k: v for k, v in _full_map().items() if k != "overtime"}
		cls.summary = _full_summary()
		cls.lines = summary_to_components(cls.summary, cls.partial_map)
		cls.by_key = _lines_by_key(cls.lines)

	def test_unmapped_key_still_in_output(self):
		self.assertIn("overtime", self.by_key)

	def test_unmapped_salary_component_is_none(self):
		self.assertIsNone(self.by_key["overtime"]["salary_component"])

	def test_unmapped_component_type_is_none(self):
		self.assertIsNone(self.by_key["overtime"]["component_type"])

	def test_unmapped_warning_is_string(self):
		warning = self.by_key["overtime"]["warning"]
		self.assertIsInstance(warning, str)
		self.assertGreater(len(warning), 0)

	def test_unmapped_warning_mentions_key(self):
		self.assertIn("overtime", self.by_key["overtime"]["warning"])

	def test_mapped_keys_have_no_warning(self):
		for key in self.by_key:
			if key != "overtime":
				self.assertIsNone(self.by_key[key]["warning"], msg=f"{key} should have no warning")

	def test_mapping_complete_returns_unmapped_key(self):
		missing = mapping_complete(self.summary, self.partial_map)
		self.assertIn("overtime", missing)

	def test_mapping_complete_does_not_include_mapped_keys(self):
		missing = mapping_complete(self.summary, self.partial_map)
		for key in missing:
			self.assertEqual(key, "overtime")

	def test_mapping_complete_empty_map_returns_all_nonzero(self):
		missing = mapping_complete(self.summary, {})
		self.assertEqual(set(missing), set(QUANTITY_KEYS))

	def test_mapping_complete_full_map_returns_empty(self):
		missing = mapping_complete(self.summary, _full_map())
		self.assertEqual(missing, [])


# ---------------------------------------------------------------------------
# mapping_complete — zero amounts not flagged as missing
# ---------------------------------------------------------------------------


class TestMappingCompleteZeros(unittest.TestCase):
	def test_zero_amount_not_in_missing(self):
		summary = _full_summary(overtime_amount=0.0)
		missing = mapping_complete(summary, {})  # empty map
		# overtime is zero → should NOT be in missing
		self.assertNotIn("overtime", missing)

	def test_none_amount_not_in_missing(self):
		summary = _full_summary(kpi_adjustment=None)
		missing = mapping_complete(summary, {})
		self.assertNotIn("kpi", missing)

	def test_empty_summary_all_missing_is_empty(self):
		missing = mapping_complete({}, {})
		self.assertEqual(missing, [])


# ---------------------------------------------------------------------------
# components_total net math
# ---------------------------------------------------------------------------


class TestComponentsTotal(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.lines = summary_to_components(_full_summary(), _full_map())
		cls.totals = components_total(cls.lines)

	def test_earnings_sum(self):
		# overtime=120000 + night=18000 + duty=50000 + kpi=30000 + region=25000 = 243000
		self.assertEqual(self.totals["earnings"], 243000.0)

	def test_deductions_sum(self):
		# late_deduction=45000
		self.assertEqual(self.totals["deductions"], 45000.0)

	def test_net_equals_earnings_minus_deductions(self):
		expected_net = self.totals["earnings"] - self.totals["deductions"]
		self.assertEqual(self.totals["net"], expected_net)

	def test_net_value(self):
		# 243000 - 45000 = 198000
		self.assertEqual(self.totals["net"], 198000.0)

	def test_keys_present(self):
		self.assertIn("earnings", self.totals)
		self.assertIn("deductions", self.totals)
		self.assertIn("net", self.totals)

	def test_empty_lines_all_zero(self):
		totals = components_total([])
		self.assertEqual(totals["earnings"], 0.0)
		self.assertEqual(totals["deductions"], 0.0)
		self.assertEqual(totals["net"], 0.0)

	def test_negative_kpi_increases_deductions(self):
		summary = _full_summary(kpi_adjustment=-20000.0)
		lines = summary_to_components(summary, _full_map())
		totals = components_total(lines)
		# earnings: overtime=120000 + night=18000 + duty=50000 + region=25000 = 213000
		# deductions: late=45000 + kpi=20000 = 65000
		self.assertEqual(totals["earnings"], 213000.0)
		self.assertEqual(totals["deductions"], 65000.0)
		self.assertEqual(totals["net"], 148000.0)

	def test_warning_lines_counted_in_totals(self):
		"""Unmapped (warning) lines have component_type=None → not counted."""
		partial = {k: v for k, v in _full_map().items() if k != "overtime"}
		lines = summary_to_components(_full_summary(), partial)
		totals = components_total(lines)
		# overtime unmapped → component_type=None → not in earnings
		# earnings: night=18000 + duty=50000 + kpi=30000 + region=25000 = 123000
		self.assertEqual(totals["earnings"], 123000.0)


# ---------------------------------------------------------------------------
# slip_variance boundaries (D12: ±1000 UZS tolerance)
# ---------------------------------------------------------------------------


class TestSlipVariance(unittest.TestCase):
	def test_zero_variance_within_tolerance(self):
		r = slip_variance(198000.0, 198000.0)
		self.assertEqual(r["variance"], 0.0)
		self.assertTrue(r["within_tolerance"])

	def test_999_within_tolerance(self):
		r = slip_variance(198000.0, 198999.0)
		self.assertAlmostEqual(r["variance"], 999.0)
		self.assertTrue(r["within_tolerance"])

	def test_1000_within_tolerance(self):
		"""Exactly 1000 UZS is within tolerance (boundary inclusive)."""
		r = slip_variance(198000.0, 199000.0)
		self.assertAlmostEqual(r["variance"], 1000.0)
		self.assertTrue(r["within_tolerance"])

	def test_1001_outside_tolerance(self):
		r = slip_variance(198000.0, 199001.0)
		self.assertAlmostEqual(r["variance"], 1001.0)
		self.assertFalse(r["within_tolerance"])

	def test_negative_variance_999_within(self):
		r = slip_variance(198000.0, 197001.0)
		self.assertAlmostEqual(r["variance"], -999.0)
		self.assertTrue(r["within_tolerance"])

	def test_negative_variance_1000_within(self):
		r = slip_variance(198000.0, 197000.0)
		self.assertAlmostEqual(r["variance"], -1000.0)
		self.assertTrue(r["within_tolerance"])

	def test_negative_variance_1001_outside(self):
		r = slip_variance(198000.0, 196999.0)
		self.assertAlmostEqual(r["variance"], -1001.0)
		self.assertFalse(r["within_tolerance"])

	def test_variance_is_slip_minus_summary(self):
		"""variance = slip_net − summary_net, not the other way around."""
		r = slip_variance(100000.0, 101500.0)
		self.assertAlmostEqual(r["variance"], 1500.0)

	def test_keys_present(self):
		r = slip_variance(0.0, 0.0)
		self.assertIn("variance", r)
		self.assertIn("within_tolerance", r)


# ---------------------------------------------------------------------------
# Rounding: whole UZS, round-half-up
# ---------------------------------------------------------------------------


class TestRoundingWholeUZS(unittest.TestCase):
	def test_fractional_amount_rounded_whole(self):
		"""A non-integer raw amount on the PAS must be rounded to whole UZS."""
		summary = _full_summary(overtime_amount=12345.6)
		lines = summary_to_components(summary, _full_map())
		ot = _lines_by_key(lines)["overtime"]
		self.assertEqual(ot["abs_amount"], 12346.0)  # round-half-up
		self.assertEqual(ot["abs_amount"], int(ot["abs_amount"]))

	def test_half_uzs_rounds_up(self):
		summary = _full_summary(night_premium_amount=999.5)
		lines = summary_to_components(summary, _full_map())
		np_ = _lines_by_key(lines)["night_premium"]
		self.assertEqual(np_["abs_amount"], 1000.0)

	def test_just_below_half_rounds_down(self):
		summary = _full_summary(duty_supplement=999.4)
		lines = summary_to_components(summary, _full_map())
		ds = _lines_by_key(lines)["duty_supplement"]
		self.assertEqual(ds["abs_amount"], 999.0)

	def test_abs_amount_always_integer_valued(self):
		summary = _full_summary(region_rate=7777.77)
		lines = summary_to_components(summary, _full_map())
		rr = _lines_by_key(lines)["region_rate"]
		self.assertEqual(rr["abs_amount"], int(rr["abs_amount"]))

	def test_components_total_returns_whole_uzs(self):
		summary = _full_summary(overtime_amount=12345.6, night_premium_amount=999.5)
		lines = summary_to_components(summary, _full_map())
		totals = components_total(lines)
		for key in ("earnings", "deductions", "net"):
			self.assertEqual(totals[key], int(totals[key]), msg=f"{key} must be a whole UZS amount")


# ---------------------------------------------------------------------------
# Edge cases: bad inputs, missing summary fields
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
	def test_none_summary_returns_empty(self):
		lines = summary_to_components(None, _full_map())
		self.assertEqual(lines, [])

	def test_none_component_map_returns_warning_lines(self):
		lines = summary_to_components(_full_summary(), None)
		# All non-zero → all returned as warning lines
		self.assertEqual(len(lines), 6)
		for ln in lines:
			self.assertIsNone(ln["salary_component"])
			self.assertIsNotNone(ln["warning"])

	def test_missing_amount_field_skipped(self):
		"""A PAS that doesn't carry an amount field at all is treated as zero."""
		summary = {}  # no fields
		lines = summary_to_components(summary, _full_map())
		self.assertEqual(lines, [])

	def test_mapping_complete_none_inputs(self):
		missing = mapping_complete(None, None)
		self.assertEqual(missing, [])

	def test_slip_variance_integer_inputs(self):
		r = slip_variance(100000, 100500)
		self.assertTrue(r["within_tolerance"])


if __name__ == "__main__":
	unittest.main()
