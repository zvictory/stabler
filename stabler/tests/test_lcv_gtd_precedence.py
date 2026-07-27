"""Unit tests for the customs-declaration (GTD) precedence in the LCV build.

A cleared GTD's duty + excise REPLACE any cost-line "Uzbekistan Customs Duty"
(no double count); VAT is never added; Iran-side duty is untouched; a warning is
raised only when both a cost-line Uzbek duty and a cleared GTD are present.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_lcv_gtd_precedence -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import lcv_math


class TestIsUzbekistanCustomsDuty(unittest.TestCase):
	def test_matches_uzbek_duty(self):
		self.assertTrue(lcv_math.is_uzbekistan_customs_duty("Uzbekistan Customs Duty"))
		self.assertTrue(lcv_math.is_uzbekistan_customs_duty("uzbek customs duty"))

	def test_does_not_match_iran_duty(self):
		self.assertFalse(lcv_math.is_uzbekistan_customs_duty("Iran Customs Duty"))

	def test_does_not_match_other(self):
		self.assertFalse(lcv_math.is_uzbekistan_customs_duty("Freight"))


class TestApplyGtdPrecedence(unittest.TestCase):
	def test_no_gtd_is_passthrough(self):
		components = {"Freight": 100.0, "Uzbekistan Customs Duty": 2_000_000.0}
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			components, gtd_duty=0, gtd_excise=0, gtd_present=False
		)
		self.assertEqual(out, components)
		self.assertEqual(warnings, [])
		# The passthrough must be a copy, not the same object.
		self.assertIsNot(out, components)

	def test_gtd_replaces_cost_line_uzbek_duty(self):
		components = {"Freight": 100.0, "Uzbekistan Customs Duty": 2_000_000.0}
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			components, gtd_duty=2_500_000, gtd_excise=0, gtd_present=True
		)
		self.assertEqual(out["Uzbekistan Customs Duty"], 2_500_000.0)  # GTD value, not 2,000,000
		self.assertEqual(out["Freight"], 100.0)
		self.assertEqual(len(warnings), 1)  # both sources present

	def test_gtd_adds_excise_component(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0}, gtd_duty=1_000_000, gtd_excise=300_000, gtd_present=True
		)
		self.assertEqual(out["Uzbekistan Customs Duty"], 1_000_000.0)
		self.assertEqual(out["Uzbekistan Excise"], 300_000.0)
		self.assertEqual(warnings, [])  # no cost-line duty was present

	def test_no_warning_when_only_gtd(self):
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0, "Iran Customs Duty": 50.0},
			gtd_duty=1_000_000,
			gtd_excise=0,
			gtd_present=True,
		)
		self.assertEqual(warnings, [])
		self.assertEqual(out["Iran Customs Duty"], 50.0)  # Iran duty untouched
		self.assertEqual(out["Uzbekistan Customs Duty"], 1_000_000.0)

	def test_zero_gtd_duty_drops_uzbek_line_without_adding(self):
		# A cleared GTD with 0 duty still supersedes the cost-line Uzbek duty.
		out, warnings = lcv_math.apply_gtd_customs_precedence(
			{"Uzbekistan Customs Duty": 2_000_000.0}, gtd_duty=0, gtd_excise=0, gtd_present=True
		)
		self.assertNotIn("Uzbekistan Customs Duty", out)
		self.assertEqual(len(warnings), 1)

	def test_vat_never_added_from_gtd(self):
		# The function only ever emits duty/excise keys — never a VAT key.
		out, _ = lcv_math.apply_gtd_customs_precedence(
			{"Freight": 100.0}, gtd_duty=1_000_000, gtd_excise=200_000, gtd_present=True
		)
		self.assertFalse(any(lcv_math.is_vat_component(k) for k in out))


if __name__ == "__main__":
	unittest.main()
