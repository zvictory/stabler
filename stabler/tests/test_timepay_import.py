"""Unit tests for the pure TimePay-name import planner (no frappe, no DB)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from stabler.api._timepay_import import normalize_name, plan_timepay_import


class TestNormalizeName(unittest.TestCase):
	def test_lower_collapse_strip(self):
		self.assertEqual(normalize_name("  John   Doe "), "john doe")

	def test_punctuation_and_accents(self):
		# Punctuation (incl. apostrophes, common in Uzbek names) collapses to spaces;
		# applied identically to both sides so matching stays consistent.
		self.assertEqual(normalize_name("O'Brien, Aziz."), "o brien aziz")

	def test_none(self):
		self.assertEqual(normalize_name(None), "")


class TestPlan(unittest.TestCase):
	def test_id_match_sets_name(self):
		stabler = [{"name": "HR-EMP-001", "employee_name": "Aziz K", "custom_timepay_id": "555", "custom_timepay_name": ""}]
		anjan = [{"timepay_id": "555", "fio": "AZIZ KARIMOV"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(len(plan["id_updates"]), 1)
		self.assertEqual(plan["id_updates"][0]["new_name"], "AZIZ KARIMOV")
		self.assertEqual(plan["name_suggestions"], [])
		self.assertEqual(plan["unmatched"], [])

	def test_id_match_no_change_when_same(self):
		stabler = [{"name": "E1", "employee_name": "Aziz", "custom_timepay_id": "5", "custom_timepay_name": "AZIZ"}]
		anjan = [{"timepay_id": "5", "fio": "AZIZ"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(plan["id_updates"], [])

	def test_name_fallback_suggestion(self):
		# id 999 not present on any stabler emp → fall back to a unique name match.
		stabler = [{"name": "E2", "employee_name": "Bobur Aliyev", "custom_timepay_id": "", "custom_timepay_name": ""}]
		anjan = [{"timepay_id": "999", "fio": "bobur  aliyev"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(plan["id_updates"], [])
		self.assertEqual(len(plan["name_suggestions"]), 1)
		self.assertEqual(plan["name_suggestions"][0]["timepay_id"], "999")
		self.assertEqual(plan["name_suggestions"][0]["employee"], "E2")

	def test_ambiguous_name_not_suggested(self):
		# Two employees share a name → not auto-suggested (reported unmatched).
		stabler = [
			{"name": "E3", "employee_name": "Ali", "custom_timepay_id": "", "custom_timepay_name": ""},
			{"name": "E4", "employee_name": "ALI", "custom_timepay_id": "", "custom_timepay_name": ""},
		]
		anjan = [{"timepay_id": "7", "fio": "Ali"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(plan["name_suggestions"], [])
		self.assertEqual(len(plan["unmatched"]), 1)
		self.assertEqual(plan["unmatched"][0]["candidates"], 2)

	def test_name_match_skips_emps_that_already_have_id(self):
		stabler = [{"name": "E5", "employee_name": "Sardor", "custom_timepay_id": "111", "custom_timepay_name": "Sardor"}]
		anjan = [{"timepay_id": "222", "fio": "Sardor"}]
		plan = plan_timepay_import(stabler, anjan)
		# id 222 doesn't match; the only same-name emp already has an id → unmatched.
		self.assertEqual(plan["name_suggestions"], [])
		self.assertEqual(len(plan["unmatched"]), 1)

	def test_reversed_name_fallback(self):
		# anjan-hr stores "Familiya Ism"; Stabler stores "Ism Familiya".
		# The reversed-token fallback should bridge this format difference.
		stabler = [{"name": "E6", "employee_name": "Alisher Maqsudov", "custom_timepay_id": "", "custom_timepay_name": ""}]
		anjan = [{"timepay_id": "777", "fio": "Maqsudov Alisher"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(plan["unmatched"], [])
		self.assertEqual(len(plan["name_suggestions"]), 1)
		self.assertEqual(plan["name_suggestions"][0]["employee"], "E6")
		self.assertEqual(plan["name_suggestions"][0]["timepay_id"], "777")

	def test_reversed_ambiguous_not_suggested(self):
		# Two Stabler employees share the same reversed form → ambiguous, not suggested.
		# Both E7 and E9 normalize to "alisher maqsudov", so reversed "maqsudov alisher"
		# yields two candidates → unmatched.
		stabler = [
			{"name": "E7", "employee_name": "Alisher Maqsudov", "custom_timepay_id": "", "custom_timepay_name": ""},
			{"name": "E9", "employee_name": "Alisher Maqsudov", "custom_timepay_id": "", "custom_timepay_name": ""},
		]
		anjan = [{"timepay_id": "888", "fio": "Maqsudov Alisher"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(plan["name_suggestions"], [])
		self.assertEqual(len(plan["unmatched"]), 1)

	def test_direct_match_wins_over_reversed(self):
		# When Stabler has both "Alisher Maqsudov" (E7) and "Maqsudov Alisher" (E8),
		# anjan-hr "Maqsudov Alisher" direct-matches E8 exactly — suggest E8, not ambiguous.
		stabler = [
			{"name": "E7", "employee_name": "Alisher Maqsudov", "custom_timepay_id": "", "custom_timepay_name": ""},
			{"name": "E8", "employee_name": "Maqsudov Alisher", "custom_timepay_id": "", "custom_timepay_name": ""},
		]
		anjan = [{"timepay_id": "888", "fio": "Maqsudov Alisher"}]
		plan = plan_timepay_import(stabler, anjan)
		self.assertEqual(plan["unmatched"], [])
		self.assertEqual(len(plan["name_suggestions"]), 1)
		self.assertEqual(plan["name_suggestions"][0]["employee"], "E8")

	def test_blank_fio_ignored(self):
		plan = plan_timepay_import([], [{"timepay_id": "1", "fio": ""}])
		self.assertEqual(plan["id_updates"], [])
		self.assertEqual(plan["unmatched"], [])


if __name__ == "__main__":
	unittest.main()
