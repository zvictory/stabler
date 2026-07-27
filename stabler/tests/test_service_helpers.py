from __future__ import annotations

import unittest

from frappe import ValidationError

from stabler.api.service import (
	_latest_visit_state,
	_normalize_visit_items,
	_service_calendar_state,
	_visit_billing_filter_condition,
	_visit_needs_billing,
)


class ServiceHelperTest(unittest.TestCase):
	def test_normalize_visit_items_rejects_empty_payload(self):
		with self.assertRaises(ValidationError):
			_normalize_visit_items([])

	def test_normalize_visit_items_accepts_rates_and_warehouses(self):
		items = _normalize_visit_items(
			[
				{"item_code": "LABOR", "qty": "1", "rate": "250000"},
				{"item_code": "FILTER", "qty": 2, "basic_rate": "10000", "warehouse": "Van - A"},
			]
		)

		self.assertEqual(
			items,
			[
				{
					"item_code": "LABOR",
					"qty": 1.0,
					"rate": 250000.0,
					"basic_rate": None,
					"warehouse": None,
					"uom": None,
				},
				{
					"item_code": "FILTER",
					"qty": 2.0,
					"rate": None,
					"basic_rate": 10000.0,
					"warehouse": "Van - A",
					"uom": None,
				},
			],
		)

	def test_normalize_visit_items_rejects_missing_item_and_non_positive_qty(self):
		with self.assertRaises(ValidationError):
			_normalize_visit_items([{"qty": 1}])

		with self.assertRaises(ValidationError):
			_normalize_visit_items([{"item_code": "FILTER", "qty": 0}])

	def test_visit_needs_billing_for_billable_issue_types_only(self):
		self.assertTrue(_visit_needs_billing("Refill", False))
		self.assertTrue(_visit_needs_billing("Repair", False))
		self.assertFalse(_visit_needs_billing("Repair", True))
		self.assertFalse(_visit_needs_billing("Inspection", False))

	def test_visit_billing_filter_condition_maps_report_filters(self):
		self.assertEqual(_visit_billing_filter_condition("open"), "mv.docstatus = 0")
		self.assertEqual(
			_visit_billing_filter_condition("unbilled"),
			"mv.docstatus = 1 AND (mv.custom_sales_invoice IS NULL OR mv.custom_sales_invoice = '') AND (mv.custom_stock_entry IS NULL OR mv.custom_stock_entry = '')",
		)
		self.assertEqual(
			_visit_billing_filter_condition("invoiced"),
			"mv.custom_sales_invoice IS NOT NULL AND mv.custom_sales_invoice != ''",
		)
		self.assertEqual(
			_visit_billing_filter_condition("stock_issued"),
			"mv.custom_stock_entry IS NOT NULL AND mv.custom_stock_entry != ''",
		)
		self.assertEqual(_visit_billing_filter_condition("all"), "")
		self.assertEqual(_visit_billing_filter_condition("unexpected"), "")

	def test_service_calendar_state_maps_completion_and_due_date(self):
		self.assertEqual(_service_calendar_state("Fully Completed", "2026-06-01", "2026-06-12"), "paid")
		self.assertEqual(
			_service_calendar_state("Partially Completed", "2026-06-01", "2026-06-12"), "partial"
		)
		self.assertEqual(_service_calendar_state("Pending", "2026-06-01", "2026-06-12"), "overdue")
		self.assertEqual(_service_calendar_state("Pending", "2026-06-20", "2026-06-12"), "upcoming")

	def test_latest_visit_state_no_visits_is_none(self):
		got = _latest_visit_state([], "2026-06-12")
		self.assertEqual(got["state"], "none")
		self.assertIsNone(got["last_date"])
		self.assertEqual(got["visit_count"], 0)

	def test_latest_visit_state_picks_most_recent(self):
		visits = [
			{"date": "2026-06-02", "completion_status": "Pending"},
			{"date": "2026-06-20", "completion_status": "Fully Completed"},
			{"date": "2026-06-10", "completion_status": "Partially Completed"},
		]
		got = _latest_visit_state(visits, "2026-06-12")
		# Latest (2026-06-20, Fully Completed) → paid; counts all three.
		self.assertEqual(got["state"], "paid")
		self.assertEqual(str(got["last_date"]), "2026-06-20")
		self.assertEqual(got["visit_count"], 3)

	def test_latest_visit_state_overdue_when_latest_pending_past_due(self):
		visits = [{"date": "2026-06-01", "completion_status": "Pending"}]
		got = _latest_visit_state(visits, "2026-06-12")
		self.assertEqual(got["state"], "overdue")


if __name__ == "__main__":
	unittest.main()
