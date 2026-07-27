"""Unit tests for the imports SPA pure rules (Frappe-free).

Covers cost masking, the eta_transit_port KPI window, status-bucket folding and
the list filter-clause builders.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_imports_rules -v
"""

from __future__ import annotations

import datetime
import unittest

from stabler.api import _imports_rules as rules

_D = datetime.date


class TestMaskNamed(unittest.TestCase):
	def test_visible_is_noop(self):
		row = {"docs_total": 100, "cash_difference": 5}
		out = rules.mask_named(row, rules.CI_MASK_FIELDS, visible=True)
		self.assertEqual(out["docs_total"], 100)
		self.assertEqual(out["cash_difference"], 5)

	def test_masks_named_fields_in_dict(self):
		row = {"docs_total": 100, "cash_difference": 5, "agreed_total": 200}
		rules.mask_named(row, rules.CI_MASK_FIELDS, visible=False)
		self.assertIsNone(row["docs_total"])
		self.assertIsNone(row["cash_difference"])
		# non-masked field survives
		self.assertEqual(row["agreed_total"], 200)

	def test_masks_over_a_list(self):
		rows = [{"total_amount": 1, "cost_lines_total": 2}, {"total_amount": 3}]
		rules.mask_named(rows, rules.CONTAINER_LIST_MASK_FIELDS, visible=False)
		self.assertIsNone(rows[0]["total_amount"])
		self.assertIsNone(rows[0]["cost_lines_total"])
		self.assertIsNone(rows[1]["total_amount"])

	def test_missing_keys_ignored(self):
		row = {"agreed_total": 9}
		rules.mask_named(row, rules.CI_MASK_FIELDS, visible=False)
		self.assertEqual(row, {"agreed_total": 9})

	def test_non_dict_list_items_survive(self):
		rows = [None, {"transport_cost": 7}, "x"]
		rules.mask_named(rows, rules.TRUCK_MASK_FIELDS, visible=False)
		self.assertIsNone(rows[1]["transport_cost"])
		self.assertEqual(rows[0], None)
		self.assertEqual(rows[2], "x")


class TestStatusCounts(unittest.TestCase):
	def test_fills_all_buckets(self):
		counts = rules.status_counts([{"status": "BOOKED", "count": 3}, {"status": "AVAILABLE", "count": 1}])
		self.assertEqual(counts["BOOKED"], 3)
		self.assertEqual(counts["AVAILABLE"], 1)
		self.assertEqual(counts["IN_TRANSIT"], 0)
		self.assertEqual(set(rules.CI_STATUSES), set(counts))

	def test_keeps_extra_status_like_cancelled(self):
		counts = rules.status_counts([{"status": "Cancelled", "count": 2}])
		self.assertEqual(counts["Cancelled"], 2)

	def test_empty_input(self):
		counts = rules.status_counts([])
		self.assertEqual(sum(counts.values()), 0)


class TestEtaWindow(unittest.TestCase):
	def test_days_left_future(self):
		self.assertEqual(rules.days_left(_D(2026, 7, 18), _D(2026, 7, 11)), 7)

	def test_days_left_overdue_is_negative(self):
		self.assertEqual(rules.days_left(_D(2026, 7, 9), _D(2026, 7, 11)), -2)

	def test_days_left_accepts_iso_strings(self):
		self.assertEqual(rules.days_left("2026-07-18", "2026-07-11"), 7)

	def test_days_left_none(self):
		self.assertIsNone(rules.days_left(None, _D(2026, 7, 11)))

	def test_eta_upper_bound(self):
		self.assertEqual(rules.eta_upper_bound(_D(2026, 7, 11), 7), _D(2026, 7, 18))

	def test_is_due_soon_boundary(self):
		today = _D(2026, 7, 11)
		self.assertTrue(rules.is_due_soon(_D(2026, 7, 18), today, 7))  # exactly 7
		self.assertFalse(rules.is_due_soon(_D(2026, 7, 19), today, 7))  # 8 days out
		self.assertTrue(rules.is_due_soon(_D(2026, 7, 5), today, 7))  # overdue counts
		self.assertFalse(rules.is_due_soon(None, today, 7))


class TestFilterClauses(unittest.TestCase):
	def test_ci_no_filters(self):
		clauses, params = rules.ci_filter_clauses()
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_ci_all_filters(self):
		clauses, params = rules.ci_filter_clauses(
			search="ABC", status="BOOKED", supplier="SUP-1", group="IPG-2026-00016"
		)
		self.assertEqual(len(clauses), 4)
		self.assertEqual(params["search"], "%ABC%")
		self.assertEqual(params["status"], "BOOKED")
		self.assertEqual(params["supplier"], "SUP-1")
		self.assertEqual(params["group"], "IPG-2026-00016")
		# parametrised — no raw user value interpolated into the SQL fragment
		joined = " ".join(clauses)
		self.assertIn("%(search)s", joined)
		self.assertNotIn("ABC", joined)
		self.assertNotIn("IPG-2026-00016", joined)

	def test_ci_group_filters_on_the_invoice_own_link(self):
		# A CI may sit in a different PI Group than the proforma it was raised
		# from (20 of msa's 360 do). Filtering through `pi.import_pi_group` would
		# return a different set than the badge the list renders, so the clause
		# must read the CI's own column.
		clauses, params = rules.ci_filter_clauses(group="IPG-2026-00016")
		self.assertEqual(clauses, ["ci.import_pi_group = %(group)s"])
		self.assertEqual(params, {"group": "IPG-2026-00016"})

	def test_container_filters(self):
		clauses, params = rules.container_filter_clauses(
			search="CN", status="ON_BOARD", commercial_invoice="CI-1"
		)
		self.assertEqual(len(clauses), 3)
		self.assertEqual(params["commercial_invoice"], "CI-1")
		self.assertTrue(all("c." in c for c in clauses))

	def test_truck_filters(self):
		clauses, params = rules.truck_filter_clauses(status="AT_BORDER")
		self.assertEqual(clauses, ["tr.status = %(status)s"])
		self.assertEqual(params, {"status": "AT_BORDER"})


class TestGrnFilterClauses(unittest.TestCase):
	def test_no_filters(self):
		clauses, params = rules.grn_filter_clauses()
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_all_filters(self):
		clauses, params = rules.grn_filter_clauses(
			search="GRN-1", status="Receiving", variance_category="MAJOR"
		)
		self.assertEqual(len(clauses), 3)
		self.assertEqual(params["search"], "%GRN-1%")
		self.assertEqual(params["status"], "Receiving")
		self.assertEqual(params["variance_category"], "MAJOR")
		joined = " ".join(clauses)
		self.assertTrue(all("g." in c for c in clauses))
		# status filters the header receipt_status, not docstatus
		self.assertIn("g.receipt_status = %(status)s", joined)
		self.assertNotIn("GRN-1", joined)


class TestTruckReceiptFilterClauses(unittest.TestCase):
	def test_no_filters(self):
		clauses, params = rules.truck_receipt_filter_clauses()
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_grn_and_search(self):
		clauses, params = rules.truck_receipt_filter_clauses(search="TRK", grn="GRN-1")
		self.assertEqual(params["search"], "%TRK%")
		self.assertEqual(params["grn"], "GRN-1")
		self.assertTrue(all("r." in c for c in clauses))

	def test_docstatus_numeric(self):
		clauses, params = rules.truck_receipt_filter_clauses(docstatus="1")
		self.assertEqual(clauses, ["r.docstatus = %(docstatus)s"])
		self.assertEqual(params, {"docstatus": 1})

	def test_docstatus_junk_ignored(self):
		clauses, params = rules.truck_receipt_filter_clauses(docstatus="draft")
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_docstatus_blank_ignored(self):
		clauses, params = rules.truck_receipt_filter_clauses(docstatus="")
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})


class TestTrucksPendingFilterClauses(unittest.TestCase):
	def test_default_statuses(self):
		clauses, params = rules.trucks_pending_filter_clauses("CI-1")
		self.assertEqual(params["commercial_invoice"], "CI-1")
		# one CI clause + one IN clause
		self.assertEqual(len(clauses), 2)
		self.assertIn("t.commercial_invoice = %(commercial_invoice)s", clauses)
		# both receivable statuses are bound as named params, never interpolated
		self.assertEqual(params["pending_status_0"], "ARRIVED")
		self.assertEqual(params["pending_status_1"], "UNLOADING")
		in_clause = clauses[1]
		self.assertIn("%(pending_status_0)s", in_clause)
		self.assertIn("%(pending_status_1)s", in_clause)
		self.assertNotIn("ARRIVED", in_clause)

	def test_custom_statuses(self):
		clauses, params = rules.trucks_pending_filter_clauses("CI-2", statuses=("ARRIVED",))
		self.assertEqual(len(clauses), 2)
		self.assertEqual(params["pending_status_0"], "ARRIVED")
		self.assertNotIn("pending_status_1", params)

	def test_empty_statuses_only_ci_clause(self):
		clauses, params = rules.trucks_pending_filter_clauses("CI-3", statuses=())
		self.assertEqual(clauses, ["t.commercial_invoice = %(commercial_invoice)s"])
		self.assertEqual(params, {"commercial_invoice": "CI-3"})


class TestWp6bFilterClauses(unittest.TestCase):
	def test_customs_no_filters(self):
		clauses, params = rules.customs_declaration_filter_clauses()
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_customs_all_filters(self):
		clauses, params = rules.customs_declaration_filter_clauses(
			search="26010", status="Approved", commercial_invoice="CI-1"
		)
		self.assertEqual(len(clauses), 3)
		self.assertEqual(params["search"], "%26010%")
		self.assertEqual(params["status"], "Approved")
		self.assertEqual(params["commercial_invoice"], "CI-1")
		joined = " ".join(clauses)
		self.assertTrue(all("cd." in c for c in clauses))
		self.assertIn("%(search)s", joined)
		self.assertNotIn("26010", joined)

	def test_freight_filters(self):
		clauses, params = rules.freight_booking_filter_clauses(
			search="BK", status="Booked", commercial_invoice="CI-2"
		)
		self.assertEqual(len(clauses), 3)
		self.assertTrue(all("fb." in c for c in clauses))
		self.assertEqual(params["status"], "Booked")
		self.assertEqual(params["commercial_invoice"], "CI-2")
		self.assertNotIn("BK", " ".join(clauses))

	def test_expense_filters(self):
		clauses, params = rules.import_expense_filter_clauses(
			search="INV", category="Transport", status="Paid", commercial_invoice="CI-3"
		)
		self.assertEqual(len(clauses), 4)
		self.assertTrue(all("ie." in c for c in clauses))
		self.assertEqual(params["category"], "Transport")
		self.assertEqual(params["status"], "Paid")
		self.assertEqual(params["commercial_invoice"], "CI-3")
		self.assertNotIn("INV", " ".join(clauses))

	def test_expense_partial_filters(self):
		clauses, params = rules.import_expense_filter_clauses(category="Storage")
		self.assertEqual(clauses, ["ie.category = %(category)s"])
		self.assertEqual(params, {"category": "Storage"})


class TestCountQuery(unittest.TestCase):
	def test_assembles_count(self):
		sql = rules.count_query(
			"`tabImport Container` c", "c.company = %(company)s AND c.status = %(status)s"
		)
		self.assertEqual(
			sql,
			"SELECT COUNT(*) AS total FROM `tabImport Container` c "
			"WHERE c.company = %(company)s AND c.status = %(status)s",
		)
		self.assertNotIn("LIMIT", sql)


class TestIsExpiringSoon(unittest.TestCase):
	def test_within_window(self):
		today = _D(2026, 7, 11)
		self.assertTrue(rules.is_expiring_soon(_D(2026, 7, 25), today, 14))  # exactly 14
		self.assertFalse(rules.is_expiring_soon(_D(2026, 7, 26), today, 14))  # 15 out
		self.assertTrue(rules.is_expiring_soon(_D(2026, 7, 1), today, 14))  # already expired
		self.assertFalse(rules.is_expiring_soon(None, today, 14))


class TestClampPageLength(unittest.TestCase):
	def test_default_on_junk(self):
		self.assertEqual(rules.clamp_page_length("nope"), 50)
		self.assertEqual(rules.clamp_page_length(0), 50)
		self.assertEqual(rules.clamp_page_length(-5), 50)

	def test_caps_at_maximum(self):
		self.assertEqual(rules.clamp_page_length(9999), 200)

	def test_passthrough(self):
		self.assertEqual(rules.clamp_page_length(25), 25)


class TestPerKg(unittest.TestCase):
	def test_normal(self):
		self.assertEqual(rules.per_kg(1000, 500), 2.0)

	def test_zero_kg_guarded(self):
		# Division-by-zero must not raise — a container with no kg costs 0/kg.
		self.assertEqual(rules.per_kg(1000, 0), 0.0)
		self.assertEqual(rules.per_kg(1000, None), 0.0)
		self.assertEqual(rules.per_kg(1000, -5), 0.0)

	def test_zero_total(self):
		self.assertEqual(rules.per_kg(0, 500), 0.0)

	def test_rounds_to_four_places(self):
		self.assertEqual(rules.per_kg(100, 3), round(100 / 3, 4))


class TestDeriveBillCategory(unittest.TestCase):
	def test_transport_from_truck_ref(self):
		self.assertEqual(rules.derive_bill_category(truck_ref="IMP-TRK-1"), "transport")

	def test_transport_from_item(self):
		self.assertEqual(rules.derive_bill_category(item_codes=["Cross-Border Transport"]), "transport")

	def test_transport_from_bill_marker(self):
		self.assertEqual(rules.derive_bill_category(bill_no="XBORDER-IMP-TRK-1"), "transport")

	def test_expense_from_ref(self):
		self.assertEqual(rules.derive_bill_category(expense_ref="IMP-EXP-1"), "expense")

	def test_expense_from_item_and_marker(self):
		self.assertEqual(rules.derive_bill_category(item_codes=["Import Service"]), "expense")
		self.assertEqual(rules.derive_bill_category(bill_no="IMPEXP-IMP-EXP-1"), "expense")

	def test_transport_wins_over_expense(self):
		# A tier-1/2 transport bill carries both a truck ref and a consumed expense
		# ref — it must bucket as transport, not expense.
		self.assertEqual(
			rules.derive_bill_category(truck_ref="IMP-TRK-1", expense_ref="IMP-EXP-1"),
			"transport",
		)

	def test_freight_marker(self):
		self.assertEqual(rules.derive_bill_category(bill_no="FREIGHT-1"), "freight")

	def test_product_default(self):
		self.assertEqual(rules.derive_bill_category(bill_no="ACME-2026-001"), "product")
		self.assertEqual(rules.derive_bill_category(), "product")


class TestLandedCostBillClauses(unittest.TestCase):
	def test_no_ref_columns_yields_empty(self):
		# No v46 columns present → no "is an import bill" clause can be built.
		clauses, params = rules.landed_cost_bill_clauses([])
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_ref_columns_build_or_clause(self):
		clauses, _params = rules.landed_cost_bill_clauses(
			["custom_import_container", "custom_commercial_invoice"]
		)
		self.assertEqual(len(clauses), 1)
		joined = clauses[0]
		self.assertIn("pi.custom_import_container", joined)
		self.assertIn("pi.custom_commercial_invoice", joined)
		self.assertIn(" OR ", joined)

	def test_filters_are_parametrised(self):
		clauses, params = rules.landed_cost_bill_clauses(
			list(rules.PI_REF_COLUMNS),
			supplier="SUP-1",
			status="Unpaid",
			commercial_invoice="CI-1",
		)
		self.assertEqual(params["supplier"], "SUP-1")
		self.assertEqual(params["status"], "Unpaid")
		self.assertEqual(params["commercial_invoice"], "CI-1")
		joined = " ".join(clauses)
		self.assertIn("%(supplier)s", joined)
		self.assertNotIn("SUP-1", joined)


class TestContainerCostSummary(unittest.TestCase):
	def _summary(self):
		return rules.container_cost_summary(
			product_cost=10000,
			cost_lines=[
				{"amount": 500, "include_in_landed_cost": 1},
				{"amount": 300, "include_in_landed_cost": 1},
				{"amount": 200, "include_in_landed_cost": 0},
			],
			bills=[
				{"grand_total": 1200, "outstanding_amount": 400},
				{"grand_total": 800, "outstanding_amount": 0},
			],
			advances=[{"paid_amount": 7000}],
		)

	def test_landed_excludes_unflagged_line(self):
		s = self._summary()
		# 10000 + 500 + 300 (the 200 line is not flagged into landed cost)
		self.assertEqual(s["landed_total"], 10800.0)

	def test_grand_includes_all_lines(self):
		s = self._summary()
		self.assertEqual(s["grand_total"], 11000.0)

	def test_paid_billed_outstanding(self):
		s = self._summary()
		self.assertEqual(s["paid"], 7000.0)
		self.assertEqual(s["billed_total"], 2000.0)
		self.assertEqual(s["outstanding"], 400.0)

	def test_empty(self):
		s = rules.container_cost_summary(product_cost=0, cost_lines=[], bills=[], advances=[])
		self.assertEqual(s["grand_total"], 0.0)
		self.assertEqual(s["outstanding"], 0.0)


class TestIsOverdue(unittest.TestCase):
	def test_overdue_with_balance(self):
		self.assertTrue(rules.is_overdue(_D(2026, 7, 1), _D(2026, 7, 11), 400))

	def test_not_overdue_when_paid(self):
		self.assertFalse(rules.is_overdue(_D(2026, 7, 1), _D(2026, 7, 11), 0))

	def test_future_due_not_overdue(self):
		self.assertFalse(rules.is_overdue(_D(2026, 7, 20), _D(2026, 7, 11), 400))

	def test_no_due_date(self):
		self.assertFalse(rules.is_overdue(None, _D(2026, 7, 11), 400))


class TestDerivePoLifecycle(unittest.TestCase):
	def test_cancelled_wins(self):
		# docstatus 2 is CANCELLED regardless of everything else.
		self.assertEqual(
			rules.derive_po_lifecycle(
				docstatus=2, advance_paid=999, per_received=100, ci_statuses=["IN_TRANSIT"]
			),
			"CANCELLED",
		)

	def test_draft(self):
		self.assertEqual(rules.derive_po_lifecycle(docstatus=0), "DRAFT")
		# A draft with advance/receipt noise is still DRAFT.
		self.assertEqual(rules.derive_po_lifecycle(docstatus=0, advance_paid=500, per_received=50), "DRAFT")

	def test_confirmed(self):
		self.assertEqual(rules.derive_po_lifecycle(docstatus=1), "CONFIRMED")

	def test_advance_paid(self):
		self.assertEqual(rules.derive_po_lifecycle(docstatus=1, advance_paid=1200), "ADVANCE_PAID")

	def test_advance_zero_stays_confirmed(self):
		self.assertEqual(rules.derive_po_lifecycle(docstatus=1, advance_paid=0), "CONFIRMED")

	def test_shipping_from_ci_status(self):
		self.assertEqual(
			rules.derive_po_lifecycle(docstatus=1, advance_paid=1200, ci_statuses=["IN_TRANSIT"]),
			"SHIPPING",
		)

	def test_shipping_beats_advance(self):
		# Any transit-ish CI supersedes a mere advance-paid badge.
		self.assertEqual(
			rules.derive_po_lifecycle(docstatus=1, advance_paid=1, ci_statuses=["ON_BOARD"]),
			"SHIPPING",
		)

	def test_partial_delivery_is_shipping(self):
		self.assertEqual(
			rules.derive_po_lifecycle(docstatus=1, ci_statuses=["DELIVERED_TO_UZBEKISTAN", "IN_TRANSIT"]),
			"SHIPPING",
		)

	def test_completed_by_per_received(self):
		self.assertEqual(
			rules.derive_po_lifecycle(docstatus=1, per_received=100, ci_statuses=["IN_TRANSIT"]),
			"COMPLETED",
		)

	def test_completed_by_all_delivered(self):
		self.assertEqual(
			rules.derive_po_lifecycle(
				docstatus=1,
				ci_statuses=["DELIVERED_TO_UZBEKISTAN", "DELIVERED_TO_UZBEKISTAN", "Cancelled"],
			),
			"COMPLETED",
		)

	def test_no_cis_not_completed(self):
		# An empty CI set must not count as "all delivered".
		self.assertEqual(rules.derive_po_lifecycle(docstatus=1, ci_statuses=[]), "CONFIRMED")

	def test_all_statuses_reachable(self):
		seen = {
			rules.derive_po_lifecycle(docstatus=0),
			rules.derive_po_lifecycle(docstatus=2),
			rules.derive_po_lifecycle(docstatus=1),
			rules.derive_po_lifecycle(docstatus=1, advance_paid=1),
			rules.derive_po_lifecycle(docstatus=1, ci_statuses=["IN_TRANSIT"]),
			rules.derive_po_lifecycle(docstatus=1, per_received=100),
		}
		self.assertEqual(seen, set(rules.PO_LIFECYCLE_STATUSES))


class TestAdvanceBase(unittest.TestCase):
	def test_docs_total_base(self):
		self.assertEqual(rules.advance_base("Docs Total", 1000, 800, 200), 800.0)

	def test_agreed_total_base_default(self):
		self.assertEqual(rules.advance_base("Agreed Total", 1000, 800, 200), 1000.0)
		self.assertEqual(rules.advance_base(None, 1000, 800, 200), 1000.0)
		self.assertEqual(rules.advance_base("", 1000, 800, 200), 1000.0)


class TestPoPaymentBadge(unittest.TestCase):
	def test_paid(self):
		self.assertEqual(rules.po_payment_badge(700, 700), "PAID")

	def test_paid_within_tolerance(self):
		self.assertEqual(rules.po_payment_badge(700, 699.995), "PAID")

	def test_partial(self):
		self.assertEqual(rules.po_payment_badge(700, 300), "PARTIAL")

	def test_not_paid(self):
		self.assertEqual(rules.po_payment_badge(700, 0), "NOT_PAID")

	def test_no_advance_expected(self):
		self.assertEqual(rules.po_payment_badge(0, 0), "NOT_PAID")
		# An unexpected payment when nothing is due reads PARTIAL, never PAID.
		self.assertEqual(rules.po_payment_badge(0, 50), "PARTIAL")


class TestAdvanceSummary(unittest.TestCase):
	def test_agreed_total_expected_split(self):
		s = rules.advance_summary(
			prepayment_type="Agreed Total",
			advance_percentage=30,
			agreed_total=1000,
			docs_total=800,
			cash_difference=200,
			advance_paid=0,
		)
		self.assertEqual(s["base"], 1000.0)
		self.assertEqual(s["expected"], 300.0)
		self.assertEqual(s["expected_bank"], 240.0)  # 800 * 30%
		self.assertEqual(s["expected_cash"], 60.0)  # 200 * 30%
		self.assertEqual(s["badge"], "NOT_PAID")

	def test_docs_total_expected_no_cash(self):
		s = rules.advance_summary(
			prepayment_type="Docs Total",
			advance_percentage=70,
			agreed_total=1000,
			docs_total=800,
			cash_difference=200,
			advance_paid=0,
		)
		self.assertEqual(s["base"], 800.0)
		self.assertEqual(s["expected"], 560.0)  # 800 * 70%
		self.assertEqual(s["expected_cash"], 0.0)

	def test_paid_split_wins_over_scalar(self):
		s = rules.advance_summary(
			prepayment_type="Agreed Total",
			advance_percentage=30,
			agreed_total=1000,
			docs_total=800,
			cash_difference=200,
			advance_paid=999,  # ignored when an explicit split is given
			paid_bank=240,
			paid_cash=60,
		)
		self.assertEqual(s["paid"], 300.0)
		self.assertEqual(s["paid_bank"], 240.0)
		self.assertEqual(s["paid_cash"], 60.0)
		self.assertEqual(s["remaining"], 0.0)
		self.assertEqual(s["pct_paid"], 100.0)
		self.assertEqual(s["badge"], "PAID")

	def test_partial_from_scalar(self):
		s = rules.advance_summary(
			prepayment_type="Agreed Total",
			advance_percentage=30,
			agreed_total=1000,
			docs_total=800,
			cash_difference=200,
			advance_paid=150,
		)
		self.assertEqual(s["paid"], 150.0)
		self.assertEqual(s["remaining"], 150.0)
		self.assertEqual(s["pct_paid"], 50.0)
		self.assertEqual(s["badge"], "PARTIAL")

	def test_zero_percent_no_expected(self):
		s = rules.advance_summary(
			prepayment_type="Agreed Total",
			advance_percentage=0,
			agreed_total=1000,
			docs_total=800,
			cash_difference=200,
		)
		self.assertEqual(s["expected"], 0.0)
		self.assertEqual(s["pct_paid"], 0.0)
		self.assertEqual(s["badge"], "NOT_PAID")


class TestInvoicedPct(unittest.TestCase):
	def test_normal(self):
		self.assertEqual(rules.invoiced_pct(250, 1000), 25.0)

	def test_zero_total_guarded(self):
		self.assertEqual(rules.invoiced_pct(250, 0), 0.0)
		self.assertEqual(rules.invoiced_pct(250, None), 0.0)
		self.assertEqual(rules.invoiced_pct(250, -5), 0.0)

	def test_none_allocated(self):
		self.assertEqual(rules.invoiced_pct(None, 1000), 0.0)

	def test_capped_at_100(self):
		self.assertEqual(rules.invoiced_pct(1500, 1000), 100.0)

	def test_rounds_one_place(self):
		self.assertEqual(rules.invoiced_pct(1, 3), round(1 / 3 * 100.0, 1))


class TestImportOrderFilterClauses(unittest.TestCase):
	def test_no_filters(self):
		clauses, params = rules.import_order_filter_clauses()
		self.assertEqual(clauses, [])
		self.assertEqual(params, {})

	def test_all_filters(self):
		clauses, params = rules.import_order_filter_clauses(
			search="PI-9", vendor="SUP-1", pi_group="IPG-2026-00001"
		)
		self.assertEqual(len(clauses), 3)
		self.assertEqual(params["search"], "%PI-9%")
		self.assertEqual(params["vendor"], "SUP-1")
		self.assertEqual(params["pi_group"], "IPG-2026-00001")
		joined = " ".join(clauses)
		self.assertTrue(all("po." in c for c in clauses))
		self.assertIn("%(search)s", joined)
		self.assertNotIn("PI-9", joined)

	def test_search_omits_pi_group_when_absent(self):
		clauses, _ = rules.import_order_filter_clauses(search="X", has_pi_group_col=False)
		self.assertNotIn("custom_import_pi_group", clauses[0])

	def test_pi_group_ignored_when_column_absent(self):
		clauses, params = rules.import_order_filter_clauses(pi_group="IPG-1", has_pi_group_col=False)
		self.assertEqual(clauses, [])
		self.assertNotIn("pi_group", params)


class TestImportOrderKpis(unittest.TestCase):
	def _rows(self):
		return [
			{
				"agreed_total": 1000,
				"docs_total": 800,
				"cash_difference": 200,
				"total_boxes": 100,
				"total_kg": 2000,
			},
			{
				"agreed_total": 500,
				"docs_total": 400,
				"cash_difference": 100,
				"total_boxes": 50,
				"total_kg": 1000,
			},
		]

	def test_aggregates(self):
		k = rules.import_order_kpis(self._rows(), invoices_total=3, invoices_pending=1, invoices_done=2)
		self.assertEqual(k["order_count"], 2)
		self.assertEqual(k["agreed_total"], 1500.0)
		self.assertEqual(k["docs_total"], 1200.0)
		self.assertEqual(k["diff"], 300.0)
		self.assertEqual(k["total_boxes"], 150)
		self.assertEqual(k["total_kg"], 3000.0)
		self.assertIsNone(k["fcl"])
		self.assertEqual(k["invoices_total"], 3)
		self.assertEqual(k["invoices_pending"], 1)
		self.assertEqual(k["invoices_done"], 2)

	def test_empty(self):
		k = rules.import_order_kpis([])
		self.assertEqual(k["order_count"], 0)
		self.assertEqual(k["agreed_total"], 0.0)
		self.assertEqual(k["total_boxes"], 0)


if __name__ == "__main__":
	unittest.main()
