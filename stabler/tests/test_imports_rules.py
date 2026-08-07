"""Unit tests for the imports SPA pure rules (Frappe-free).

Covers cost masking, the eta_transit_port KPI window, status-bucket folding and
the list filter-clause builders.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_imports_rules -v
"""

from __future__ import annotations

import datetime
import os
import unittest

from stabler.api import _imports_rules as rules

_D = datetime.date

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler
_ALLOCATION_GUARD_PATH = os.path.join(_APP_ROOT, "stabler", "imports_module", "allocation_guard.py")
_CI_CONTROLLER_PATH = os.path.join(
	_APP_ROOT, "stabler", "doctype", "commercial_invoice", "commercial_invoice.py"
)


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

	def test_ci_group_filter_matches_the_badge_expression(self):
		# The list badge renders the *effective* group (own link, else derived
		# from the proforma). If the filter read only `ci.import_pi_group` it
		# would hide rows that visibly carry a badge, so both must read the very
		# same expression.
		clauses, params = rules.ci_filter_clauses(group="IPG-2026-00016")
		self.assertEqual(clauses, [f"({rules.ci_effective_group_expr(True)}) = %(group)s"])
		self.assertEqual(params, {"group": "IPG-2026-00016"})

	def test_group_clause_named_group(self):
		# A real group stays parametrised — the value must never be interpolated
		# into the SQL text.
		clause, params = rules.group_clause("pi.import_pi_group", "IPG-2026-00016")
		self.assertEqual(clause, "pi.import_pi_group = %(group)s")
		self.assertEqual(params, {"group": "IPG-2026-00016"})
		self.assertNotIn("IPG-2026-00016", clause)

	def test_group_clause_ungrouped_sentinel(self):
		# The sentinel is a *filter mode*, not a group name. If it ever reached
		# SQL as a bound value the query would read `= '__none__'` and silently
		# return zero rows instead of the ungrouped ones — hence: NULL test, and
		# no params at all.
		clause, params = rules.group_clause("pi.import_pi_group", rules.UNGROUPED)
		self.assertEqual(clause, "NULLIF(pi.import_pi_group, '') IS NULL")
		self.assertEqual(params, {})
		self.assertNotIn(rules.UNGROUPED, clause)

	def test_ci_group_filter_ungrouped_wraps_the_effective_expr(self):
		# "No group" on the CI list means no group by *any* route. Testing only
		# `ci.import_pi_group` would list invoices that visibly carry a purple
		# badge derived from their proforma.
		clauses, params = rules.ci_filter_clauses(group=rules.UNGROUPED)
		self.assertEqual(clauses, [f"NULLIF(({rules.ci_effective_group_expr(True)}), '') IS NULL"])
		self.assertEqual(params, {})

	def test_ci_pi_match_filter_is_opt_in(self):
		# An unrecognised (or absent) value must mean "no filter" — degrading to
		# `linked` would quietly hide every invoice the report exists to surface.
		self.assertIsNone(rules.ci_pi_match_clause(None))
		self.assertIsNone(rules.ci_pi_match_clause(""))
		self.assertIsNone(rules.ci_pi_match_clause("whatever"))
		self.assertEqual(rules.ci_filter_clauses(pi_match=None)[0], [])

	def test_ci_pi_match_linked_is_the_exact_negation_of_unlinked(self):
		# The two modes must partition the list: an invoice that appears under
		# neither (or under both) is a hole in the "every CI is linked" claim.
		unlinked = rules.ci_pi_match_clause("unlinked")
		linked = rules.ci_pi_match_clause("linked")
		self.assertEqual(linked, f"NOT {unlinked}")

	def test_ci_pi_match_counts_a_partly_linked_invoice_as_unlinked(self):
		# A multi-PI invoice where only some rows name a proforma is precisely
		# the defect being hunted, so the clause must test for the *existence* of
		# an empty row — not for the absence of any filled one.
		unlinked = rules.ci_pi_match_clause("unlinked")
		self.assertIn("OR EXISTS", unlinked)
		self.assertIn("COALESCE(cim.custom_proforma_invoice, '') = ''", unlinked)
		# An invoice with no items at all traces to nothing either.
		self.assertIn("NOT EXISTS", unlinked)

	def test_ci_pi_match_without_the_custom_field_says_nothing_is_linked(self):
		# On a site that never carried the imports work the header column does
		# not exist. Emitting the real clause would raise "Unknown column"; and
		# claiming everything is linked would be a lie.
		self.assertEqual(rules.ci_pi_match_clause("unlinked", has_pi_link=False), "1=1")
		self.assertEqual(rules.ci_pi_match_clause("linked", has_pi_link=False), "1=0")

	def test_ci_pi_match_expr_is_self_contained(self):
		# Same trap as the group expression: `count_query` drops the joins, so a
		# join alias here would blow up the count only — after the rows rendered.
		for mode in ("linked", "unlinked"):
			expr = rules.ci_pi_match_clause(mode)
			for alias in ("pi.", "s.", "pig."):
				self.assertNotIn(alias, expr)

	def test_ci_effective_group_expr_is_self_contained(self):
		# `count_query` mirrors the list's FROM *without* its joins, so the
		# expression may only touch `ci` and correlated subqueries. Referencing a
		# join alias would raise "Unknown column" on the count query alone —
		# after the rows had already rendered fine.
		for has_pi_link in (True, False):
			expr = rules.ci_effective_group_expr(has_pi_link)
			for alias in ("pi.", "s.", "pig."):
				self.assertNotIn(alias, expr)
			self.assertIn("ci.import_pi_group", expr)

	def test_ci_effective_group_expr_without_pi_link(self):
		# `custom_proforma_invoice` on the CI header is a Custom Field: on a site
		# that never carried the imports work the column is absent and naming it
		# would break the whole list.
		expr = rules.ci_effective_group_expr(False)
		self.assertNotIn("ci.custom_proforma_invoice", expr)
		# the item-level derivation survives — that column ships in the doctype
		self.assertIn("tabCommercial Invoice Item", expr)

	def test_ci_effective_group_expr_ignores_multi_group_invoices(self):
		# A CI whose items point at proformas in *different* groups must show
		# nothing rather than an arbitrary one of them.
		self.assertIn("HAVING COUNT(DISTINCT pi3.import_pi_group) = 1", rules.ci_effective_group_expr())

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


def _pi_line(pi, category, item, boxes, qty, **kw):
	row = {"pi_name": pi, "category": category, "item": item, "boxes": boxes, "qty": qty}
	row.update(kw)
	return row


def _ci_line(ci, pi, category, item, boxes, qty, **kw):
	row = {
		"ci_name": ci,
		"custom_proforma_invoice": pi,
		"category": category,
		"item": item,
		"boxes": boxes,
		"qty": qty,
	}
	row.update(kw)
	return row


class TestPiCiMatching(unittest.TestCase):
	"""The contract↔shipment math ported from the ~/msa-sandbox prototype.

	Each test pins one fact the sandbox established against the real MSA book;
	the numbers in the assertions are the measured ones, not invented.
	"""

	def test_norm_key_collapses_whitespace_and_case(self):
		# The book writes the same product as "Whole leg" and "WHOLE LEG"; raw-text
		# matching invented 40 phantom "not on any PI" lines.
		self.assertEqual(rules.norm_key("  Whole   leg "), "WHOLE LEG")
		self.assertEqual(rules.norm_key("WHOLE LEG"), "WHOLE LEG")
		self.assertEqual(rules.norm_key(None), "")
		self.assertEqual(
			rules.match_key(" HMA/PI/1 ", "Cube  roll"),
			("HMA/PI/1", "CUBE ROLL"),
		)

	def test_compensated_bundle_matches_on_category_not_item(self):
		# One PI line (a compensated bundle) ships as three sub-cuts. Matching on
		# the category folds them back onto the contract line; matching on the
		# item — what the old code did — finds nothing.
		pi_rows = [_pi_line("PI-1", "BUFFALO COMPENSATED", "CM60/40", 16800, 336000)]
		ci_rows = [
			_ci_line("CI-1", "PI-1", "BUFFALO COMPENSATED", "41 TOPSIDE", 6000, 120000),
			_ci_line("CI-1", "PI-1", "buffalo  compensated", "44 SILVER SIDE", 5800, 116000),
			_ci_line("CI-2", "PI-1", "BUFFALO COMPENSATED", "45 RUMP STEAK", 5000, 100000),
		]
		contract = rules.contract_index(pi_rows)
		shipped = rules.shipped_index(ci_rows)
		key = rules.match_key("PI-1", "BUFFALO COMPENSATED")
		self.assertEqual(len(shipped), 1, "all three sub-cuts must fold onto one key")
		rem = rules.remaining_for(contract[key], shipped[key])
		self.assertEqual(rem["shipped_boxes"], 16800)
		self.assertEqual(rem["remaining_boxes"], 0)
		self.assertFalse(rem["over_shipped"])
		self.assertEqual(rem["ci_count"], 2)
		# The sub-cut is reported as info, never as a failure.
		diffs = rules.diff_ci_line(ci_rows[0], contract[key])
		self.assertEqual([d["code"] for d in diffs], ["sub_cut"])
		self.assertEqual(rules.worst_level(diffs), "info")

	def test_over_shipment_is_not_swallowed(self):
		# HMA/PI/2677/202425 · TRIMING really did ship 38 boxes over contract.
		# max(0, ...) hid 21 keys / 25 959 boxes book-wide.
		contract = {"boxes": 4200, "qty": 84000}
		shipped = {"boxes": 4238, "qty": 84760, "ci_names": {"CI-1"}}
		rem = rules.remaining_for(contract, shipped)
		self.assertEqual(rem["remaining_boxes"], -38)
		self.assertTrue(rem["over_shipped"])
		self.assertEqual(rem["over_boxes"], 38)
		self.assertEqual(rem["pct"], 100.0, "pct caps at 100 even when over-shipped")

	def test_unattributable_line_is_flagged_not_netted(self):
		# A CI line whose key is on no PI must not reduce anyone's remaining
		# balance — it is surfaced instead.
		pi_rows = [_pi_line("PI-1", "BLADE", "12", 4911, 98220)]
		ci_rows = [
			_ci_line("CI-1", "PI-1", "BLADE", "12", 4911, 98220),
			_ci_line("CI-1", "PI-1", "MYSTERY CUT", "99", 500, 10000),
		]
		summary = rules.reconcile(pi_rows, ci_rows)
		self.assertEqual(summary["orphan_lines"], 1)
		self.assertEqual(summary["orphan_boxes"], 500)
		self.assertEqual(summary["matched_lines"], 1)
		self.assertEqual(summary["remaining_boxes"], 0, "the orphan must not go negative")
		diffs = rules.diff_ci_line(ci_rows[1], None)
		self.assertEqual([d["code"] for d in diffs], ["unattributable"])
		self.assertEqual(rules.worst_level(diffs), "error")

	def test_multiple_contract_prices_accept_any(self):
		# BUFFALO COMPENSATED_3 is contracted at 4.05 / 4.15 / 4.10 — four such
		# keys exist. A CI at any of them is compliant.
		pi_rows = [
			_pi_line("PI-1", "BUFFALO COMPENSATED", "CM", 100, 2000, rate=4.05),
			_pi_line("PI-1", "BUFFALO COMPENSATED", "CM", 100, 2000, rate=4.15),
			_pi_line("PI-1", "BUFFALO COMPENSATED", "CM", 100, 2000, rate=4.10),
		]
		contract = rules.contract_index(pi_rows)[rules.match_key("PI-1", "BUFFALO COMPENSATED")]
		self.assertEqual(contract["agreed_prices"], {4.05, 4.15, 4.1})
		compliant = _ci_line("CI-1", "PI-1", "BUFFALO COMPENSATED", "CM", 100, 2000, rate=4.10)
		self.assertEqual(rules.diff_ci_line(compliant, contract), [])
		off = _ci_line("CI-1", "PI-1", "BUFFALO COMPENSATED", "CM", 100, 2000, rate=4.20)
		diffs = rules.diff_ci_line(off, contract)
		self.assertEqual([d["code"] for d in diffs], ["price_agreed"])
		self.assertEqual(diffs[0]["pi_value"], [4.05, 4.1, 4.15])

	def test_price_compare_rounds_to_four_places(self):
		# Raw float equality produced 273 phantom mismatches book-wide.
		pi_rows = [_pi_line("PI-1", "BLADE", "12", 100, 2000, rate=4.1, docs_price=3.85)]
		contract = rules.contract_index(pi_rows)[rules.match_key("PI-1", "BLADE")]
		line = _ci_line("CI-1", "PI-1", "BLADE", "12", 100, 2000, rate=4.0999999999, docs_price=3.8500000001)
		self.assertEqual(rules.diff_ci_line(line, contract), [])

	def test_reconcile_totals_match_sandbox_fixture(self):
		# HMA/PI/2677/202425 end to end: BLADE ships exactly, HEAD MEAT is 38
		# boxes short, TRIMING is 38 boxes over. The shortfall and the overage
		# must NOT cancel each other out in the summary.
		pi = "HMA/PI/2677/202425"
		pi_rows = [
			_pi_line(pi, "BLADE", "12", 4911, 98220, rate=3.85, amount=378147.0),
			_pi_line(pi, "HEAD MEAT", "13", 4200, 84000, rate=3.20, amount=268800.0),
			_pi_line(pi, "TRIMING", "14", 4200, 84000, rate=2.95, amount=247800.0),
		]
		ci_rows = [
			_ci_line("MH/104/202526", pi, "BLADE", "12", 4911, 98220, rate=3.85),
			_ci_line("MH/104/202526", pi, "HEAD MEAT", "13", 4162, 83240, rate=3.20),
			_ci_line("MH/105/202526", pi, "TRIMING", "14", 4238, 84760, rate=2.95),
		]
		contract = rules.contract_index(pi_rows)
		shipped = rules.shipped_index(ci_rows)
		per_key = {
			category: rules.remaining_for(
				contract[rules.match_key(pi, category)], shipped.get(rules.match_key(pi, category))
			)
			for category in ("BLADE", "HEAD MEAT", "TRIMING")
		}
		self.assertEqual(per_key["BLADE"]["remaining_boxes"], 0)
		self.assertEqual(per_key["HEAD MEAT"]["remaining_boxes"], 38)
		self.assertEqual(per_key["TRIMING"]["remaining_boxes"], -38)
		self.assertTrue(per_key["TRIMING"]["over_shipped"])

		summary = rules.reconcile(pi_rows, ci_rows)
		self.assertEqual(summary["contract_lines"], 3)
		self.assertEqual(summary["contract_keys"], 3)
		self.assertEqual(summary["ci_lines"], 3)
		self.assertEqual(summary["matched_lines"], 3)
		self.assertEqual(summary["ci_count"], 2)
		self.assertEqual(summary["orphan_lines"], 0)
		self.assertEqual(summary["over_keys"], 1)
		self.assertEqual(summary["over_boxes"], 38)
		# 38 remaining, NOT 0: the over-shipped key is excluded from the netting.
		self.assertEqual(summary["remaining_boxes"], 38)
		self.assertEqual(summary["price_docs"], 0)
		self.assertEqual(summary["price_agreed"], 0)

	def test_header_pi_is_used_when_the_row_has_none(self):
		# K1: ~2 127 CI item rows carry no row-level PI; the header link is the
		# only thing tying them to a contract. They must still count as shipped.
		pi_rows = [_pi_line("PI-1", "BLADE", "12", 4911, 98220)]
		ci_rows = [
			{
				"ci_name": "CI-1",
				"custom_proforma_invoice": "",
				"header_proforma_invoice": "PI-1",
				"category": "BLADE",
				"item": "12",
				"boxes": 4911,
				"qty": 98220,
			}
		]
		summary = rules.reconcile(pi_rows, ci_rows)
		self.assertEqual(summary["matched_lines"], 1)
		self.assertEqual(summary["orphan_lines"], 0)
		self.assertEqual(summary["remaining_boxes"], 0)

	def test_qty_arithmetic_tolerance(self):
		pi_rows = [_pi_line("PI-1", "BLADE", "12", 100, 2000)]
		contract = rules.contract_index(pi_rows)[rules.match_key("PI-1", "BLADE")]
		ok = _ci_line("CI-1", "PI-1", "BLADE", "12", 100, 2000.4, box_weight_kg=20)
		self.assertEqual([d["code"] for d in rules.diff_ci_line(ok, contract)], [])
		bad = _ci_line("CI-1", "PI-1", "BLADE", "12", 100, 1900, box_weight_kg=20)
		diffs = rules.diff_ci_line(bad, contract)
		self.assertEqual([d["code"] for d in diffs], ["qty_arithmetic"])
		self.assertEqual(diffs[0]["pi_value"], 2000.0)

	def test_blank_category_never_matches_a_contract_line(self):
		# Post-deploy defect on msa: 29 CI lines carry no category and 27 of them
		# "matched" whichever other category-less line sat on the same PI —
		# inheriting a foreign price and netting out of a foreign balance.
		# (PI, "") is a hole in the data, not a key.
		pi_rows = [
			_pi_line("PI-1", "", "12", 4000, 80000, rate=4.675),
			_pi_line("PI-1", "BLADE", "12", 1000, 20000, rate=4.10),
		]
		ci_rows = [_ci_line("CI-1", "PI-1", "", "12", 500, 10000, rate=4.865)]
		contract = rules.contract_index(pi_rows)
		self.assertNotIn(rules.match_key("PI-1", ""), contract, "blank key must not be indexed")
		self.assertEqual(len(contract), 1)
		self.assertNotIn(rules.match_key("PI-1", ""), rules.shipped_index(ci_rows))

		summary = rules.reconcile(pi_rows, ci_rows)
		self.assertEqual(summary["orphan_lines"], 1)
		self.assertEqual(summary["missing_category"], 1)
		self.assertEqual(summary["price_agreed"], 0, "an unmatched line must not report a price diff")
		# The dropped contract line is reported, not silently written off.
		self.assertEqual(summary["contract_unkeyed_lines"], 1)
		self.assertEqual(summary["contract_unkeyed_boxes"], 4000)
		# The BLADE line keeps its own balance, untouched by the blank rows.
		self.assertEqual(summary["remaining_boxes"], 1000)

	def test_blank_category_reports_its_own_code_not_unattributable(self):
		# "Not on any PI" would send the operator to the proforma; the defect is
		# on the CI line itself.
		line = _ci_line("CI-1", "PI-1", "   ", "12", 500, 10000)
		diffs = rules.diff_ci_line(line, None)
		self.assertEqual([d["code"] for d in diffs], ["missing_category"])
		self.assertEqual(diffs[0]["field"], "category")
		self.assertEqual(rules.worst_level(diffs), "error")

	def test_price_tolerance_absorbs_the_pi_third_decimal(self):
		# A PI books 4.865 and its CI stores 4.86 — the same price at two
		# precisions. Exact 4-decimal equality called 816 of 818 agreed-price
		# comparisons on msa a difference; only 2 were real, and both were the
		# blank-category defect above. Nothing on that book falls between 0.005
		# and 0.05, so a whole-cent error is still caught.
		pi_rows = [_pi_line("PI-1", "BLADE", "12", 100, 2000, rate=4.865, docs_price=4.425)]
		contract = rules.contract_index(pi_rows)[rules.match_key("PI-1", "BLADE")]
		rounded = _ci_line("CI-1", "PI-1", "BLADE", "12", 100, 2000, rate=4.86, docs_price=4.43)
		self.assertEqual(rules.diff_ci_line(rounded, contract), [])
		# A whole cent out is a real pricing error and still warns.
		off = _ci_line("CI-1", "PI-1", "BLADE", "12", 100, 2000, rate=4.85, docs_price=4.425)
		self.assertEqual([d["code"] for d in rules.diff_ci_line(off, contract)], ["price_agreed"])
		# A missing docs price (0) is a difference, not a rounding artefact.
		zero = _ci_line("CI-1", "PI-1", "BLADE", "12", 100, 2000, rate=4.865, docs_price=0)
		self.assertEqual([d["code"] for d in rules.diff_ci_line(zero, contract)], ["price_docs"])

	def test_every_diff_code_has_a_label(self):
		self.assertEqual(
			set(rules.DIFF_LABELS),
			{
				"unattributable",
				"missing_category",
				"price_docs",
				"price_agreed",
				"qty_arithmetic",
				"sub_cut",
			},
		)


#: PI-AUG-26 as booked on msa: thirteen cuts, one category, 8 400 boxes /
#: 168 000 kg. The Smart Fill picker used to show this as a single row because
#: that is exactly what the (PI, category) key says it is.
_PI_AUG_26 = [
	("105/106 FOREQUARTER / FQ ROLL", 1494, 29880),
	("15-17 NECK", 1200, 24000),
	("31 TENDERLOIN", 216, 4320),
	("41 TOPSIDE", 720, 14400),
	("42 THICK FLANK / knuckle", 570, 11400),
	("44 SILVER SIDE", 1020, 20400),
	("45 RUMP STEAK", 480, 9600),
	("46 STRIPLOIN", 330, 6600),
	("60/60A SHIN SHANK", 420, 8400),
	("63 CHUCK", 720, 14400),
	("64 CHUCK TENDER", 150, 3000),
	("65 BLADE", 870, 17400),
	("67 CUBE ROLL", 210, 4200),
]


class TestContractLineBreakdown(unittest.TestCase):
	"""The picker shows the cuts; the guard still counts the bundle.

	``contract_line_breakdown`` exists so Smart Fill can offer a compensated
	bundle's individual PI lines without introducing a second match key. Every
	test here pins that the split is presentation-only: the key does not move,
	the totals do not move, and nothing is clamped on the way through.
	"""

	def _bundle(self):
		rows = [
			_pi_line(
				"PI-AUG-26",
				"BUFFALO COMPENSATED_5",
				item,
				boxes,
				qty,
				name=f"pii-{idx}",
				box_weight_kg=20,
				rate=4.50,
				docs_price=4.20,
			)
			for idx, (item, boxes, qty) in enumerate(_PI_AUG_26)
		]
		return rules.contract_index(rows)[rules.match_key("PI-AUG-26", "BUFFALO COMPENSATED_5")]

	def test_split_sums_back_to_the_pool_the_guard_enforces(self):
		# The invariant the group header and the Apply loop both stand on: if the
		# thirteen rows did not add back up to 8 400 / 168 000, the picker would be
		# offering boxes the server is going to refuse.
		entry = self._bundle()
		children = rules.contract_line_breakdown(entry)
		self.assertEqual(len(children), 13)
		self.assertEqual(sum(c["boxes"] for c in children), 8400)
		self.assertEqual(sum(c["qty"] for c in children), 168000)
		balance = rules.remaining_for(entry, None)
		self.assertEqual(balance["contract_boxes"], 8400)
		self.assertEqual(balance["contract_qty"], 168000)

	def test_the_match_key_does_not_move(self):
		# The whole point: thirteen offerable rows, still ONE key. Item-level
		# keying matched 19.5% of live CI lines; category-level matched 98.3%.
		rows = [
			_pi_line("PI-AUG-26", "BUFFALO COMPENSATED_5", item, boxes, qty, name=f"pii-{idx}")
			for idx, (item, boxes, qty) in enumerate(_PI_AUG_26)
		]
		index = rules.contract_index(rows)
		self.assertEqual(len(index), 1)
		self.assertEqual(len(rules.contract_line_breakdown(next(iter(index.values())))), 13)

	def test_repeated_item_code_stays_two_rows(self):
		# One PI may book the same cut twice at two prices (invariant 4). Merging
		# on `item` would collapse them into one allocation box and silently lose
		# a rate; identity is the child-row docname.
		rows = [
			_pi_line("PI-1", "BLADE", "12", 100, 2000, name="a", rate=4.50),
			_pi_line("PI-1", "BLADE", "12", 40, 800, name="b", rate=4.80),
		]
		entry = rules.contract_index(rows)[rules.match_key("PI-1", "BLADE")]
		children = rules.contract_line_breakdown(entry)
		self.assertEqual([c["row"] for c in children], ["a", "b"])
		self.assertEqual([c["agreed_rate"] for c in children], [4.50, 4.80])

	def test_row_identity_is_present_and_unique(self):
		# The UI keys its allocation store and its DOM ids off `row`. A blank or
		# colliding id means two inputs writing over each other.
		entry = self._bundle()
		ids = [c["row"] for c in rules.contract_line_breakdown(entry)]
		self.assertTrue(all(ids))
		self.assertEqual(len(set(ids)), len(ids))
		# Rows that arrive without a docname still get a unique id rather than "".
		unnamed = rules.contract_index(
			[
				_pi_line("PI-1", "BLADE", "12", 10, 200),
				_pi_line("PI-1", "BLADE", "13", 10, 200),
			]
		)[rules.match_key("PI-1", "BLADE")]
		synthetic = [c["row"] for c in rules.contract_line_breakdown(unnamed)]
		self.assertTrue(all(synthetic))
		self.assertEqual(len(set(synthetic)), 2)

	def test_nothing_is_clamped_and_the_entry_is_not_mutated(self):
		# Invariant 1 reaches down to the child rows: a negative correction line in
		# the source book must stay visible, not silently read as zero.
		rows = [
			_pi_line("PI-1", "BLADE", "12", 100, 2000, name="a"),
			_pi_line("PI-1", "BLADE", "12", -30, -600, name="b"),
		]
		entry = rules.contract_index(rows)[rules.match_key("PI-1", "BLADE")]
		before = dict(entry)
		children = rules.contract_line_breakdown(entry)
		self.assertEqual([c["boxes"] for c in children], [100, -30])
		self.assertEqual([c["qty"] for c in children], [2000, -600])
		self.assertEqual(entry, before)
		self.assertEqual(len(entry["lines"]), 2)

	def test_item_code_travels_verbatim(self):
		# It is written back into the CI as a Link value; upper-casing it the way
		# the match key does would point at a docname that does not exist.
		entry = rules.contract_index([_pi_line("PI-1", "BLADE", "42 Thick Flank", 10, 200, name="a")])[
			rules.match_key("PI-1", "BLADE")
		]
		self.assertEqual(rules.contract_line_breakdown(entry)[0]["item"], "42 Thick Flank")

	def test_empty_bundle_is_an_empty_list(self):
		self.assertEqual(rules.contract_line_breakdown({"key": ("PI-1", "BLADE"), "lines": []}), [])
		self.assertEqual(rules.contract_line_breakdown({"key": ("PI-1", "BLADE")}), [])


class TestCiAllocationCap(unittest.TestCase):
	"""R4 — a Commercial Invoice may not allocate past what the contract has left.

	The SPA caps the picker, but the SPA is not a control: the REST API is open.
	These pin the pure half of the server guarantee (``changed_allocation_keys`` /
	``over_allocations``); the query that feeds them is pinned by
	``TestAllocationGuardQuery`` below.
	"""

	def _fixture(self, contract_boxes=100, contract_qty=2000, shipped=()):
		pi_rows = [_pi_line("PI-1", "BLADE", "12", contract_boxes, contract_qty)]
		return (
			rules.contract_index(pi_rows),
			rules.shipped_index(list(shipped)),
			rules.match_key("PI-1", "BLADE"),
		)

	def test_over_allocation_beyond_remaining_is_reported(self):
		# 100 contracted, 60 already on another CI -> 40 left. 41 is a breach, 40 is not.
		contract, shipped, key = self._fixture(shipped=[_ci_line("CI-1", "PI-1", "BLADE", "12", 60, 1200)])
		self.assertEqual(rules.remaining_for(contract[key], shipped[key])["remaining_boxes"], 40)

		draft = [_ci_line("CI-2", "PI-1", "BLADE", "12", 41, 820)]
		breaches = rules.over_allocations(contract, shipped, draft, {key})
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0]["key"], key)
		self.assertEqual(breaches[0]["allocated_boxes"], 41)
		self.assertEqual(breaches[0]["remaining_boxes"], 40)
		self.assertEqual(breaches[0]["over_boxes"], 1)
		self.assertEqual(breaches[0]["level"], "error", "severity comes from DIFF_LEVELS")

		exact = [_ci_line("CI-2", "PI-1", "BLADE", "12", 40, 800)]
		self.assertEqual(rules.over_allocations(contract, shipped, exact, {key}), [])

	def test_boxes_and_kg_cap_independently(self):
		# box_weight_kg is display only — a line may sit inside the box balance and
		# still blow the kg balance, and either one is a breach.
		contract, shipped, key = self._fixture(shipped=[_ci_line("CI-1", "PI-1", "BLADE", "12", 60, 1200)])
		heavy = [_ci_line("CI-2", "PI-1", "BLADE", "12", 10, 900)]
		breaches = rules.over_allocations(contract, shipped, heavy, {key})
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0]["over_boxes"], 0.0, "boxes are within balance")
		self.assertEqual(breaches[0]["over_qty"], 100)

	def test_editing_a_ci_does_not_count_against_itself(self):
		# CI-1 IS the document being saved, so the guard's shipped index excludes it.
		own = [_ci_line("CI-1", "PI-1", "BLADE", "12", 60, 1200)]
		contract, shipped_without_self, key = self._fixture()
		self.assertEqual(rules.over_allocations(contract, shipped_without_self, own, {key}), [])

		# Counting it against itself is the bug this excludes: 100 - 60 = 40 left,
		# so its own 60 boxes would read as a 20-box overage on every edit.
		shipped_with_self = rules.shipped_index(own)
		self_cannibal = rules.over_allocations(contract, shipped_with_self, own, {key})
		self.assertEqual(len(self_cannibal), 1)
		self.assertEqual(self_cannibal[0]["over_boxes"], 20)

	def test_cancelled_ci_does_not_consume_quantity(self):
		# The guard's query filters `ci.status != 'Cancelled'` before indexing, so a
		# cancelled invoice releases its boxes back to the contract.
		all_rows = [
			dict(_ci_line("CI-1", "PI-1", "BLADE", "12", 60, 1200), ci_status="Cancelled"),
			dict(_ci_line("CI-2", "PI-1", "BLADE", "12", 10, 200), ci_status="IN_TRANSIT"),
		]
		contract, live_shipped, key = self._fixture(
			shipped=[r for r in all_rows if r["ci_status"] != "Cancelled"]
		)
		self.assertEqual(rules.remaining_for(contract[key], live_shipped[key])["remaining_boxes"], 90)
		self.assertEqual(
			rules.over_allocations(
				contract, live_shipped, [_ci_line("CI-3", "PI-1", "BLADE", "12", 90, 1800)], {key}
			),
			[],
			"the cancelled 60 boxes must be available again",
		)
		self.assertEqual(
			len(
				rules.over_allocations(
					contract, live_shipped, [_ci_line("CI-3", "PI-1", "BLADE", "12", 91, 1820)], {key}
				)
			),
			1,
		)
		# Had the cancelled CI still counted, only 30 would be left and 90 would breach.
		with_cancelled = rules.shipped_index(all_rows)
		self.assertEqual(rules.remaining_for(contract[key], with_cancelled[key])["remaining_boxes"], 30)

	def test_compensated_bundle_shows_true_remaining(self):
		# C1 regression guard. One PI line (a compensated bundle) shipped earlier as
		# sub-cuts. Keying on the item would find nothing and call the bundle 100%
		# unshipped, so the cap would let a second CI ship the full 16 800 again.
		pi_rows = [_pi_line("PI-1", "BUFFALO COMPENSATED", "CM60/40", 16800, 336000)]
		prior = [
			_ci_line("CI-1", "PI-1", "BUFFALO COMPENSATED", "41 TOPSIDE", 6000, 120000),
			_ci_line("CI-1", "PI-1", "buffalo  compensated", "44 SILVER SIDE", 5800, 116000),
		]
		contract = rules.contract_index(pi_rows)
		shipped = rules.shipped_index(prior)
		key = rules.match_key("PI-1", "BUFFALO COMPENSATED")
		rem = rules.remaining_for(contract[key], shipped[key])
		self.assertNotEqual(rem["remaining_boxes"], 16800, "item-keying would report the bundle untouched")
		self.assertEqual(rem["remaining_boxes"], 5000)

		# A third sub-cut is capped at the bundle's real remainder, not at zero and
		# not at the full contract.
		over = [_ci_line("CI-2", "PI-1", "BUFFALO COMPENSATED", "45 RUMP STEAK", 5001, 100020)]
		breaches = rules.over_allocations(contract, shipped, over, {key})
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0]["over_boxes"], 1)
		self.assertEqual(breaches[0]["label"], "BUFFALO COMPENSATED")
		exact = [_ci_line("CI-2", "PI-1", "BUFFALO COMPENSATED", "45 RUMP STEAK", 5000, 100000)]
		self.assertEqual(rules.over_allocations(contract, shipped, exact, {key}), [])

	def test_over_shipped_key_returns_negative_remaining(self):
		# HMA/PI/2677/202425 · TRIMING is 38 boxes over contract in the real book.
		# max(0, ...) is forbidden: the breach report must carry the raw negative.
		pi_rows = [_pi_line("PI-1", "TRIMING", "14", 4200, 84000)]
		contract = rules.contract_index(pi_rows)
		shipped = rules.shipped_index([_ci_line("CI-1", "PI-1", "TRIMING", "14", 4238, 84760)])
		key = rules.match_key("PI-1", "TRIMING")
		rem = rules.remaining_for(contract[key], shipped[key])
		self.assertEqual(rem["remaining_boxes"], -38)
		self.assertTrue(rem["over_shipped"])
		self.assertEqual(rem["over_boxes"], 38)

		breaches = rules.over_allocations(
			contract, shipped, [_ci_line("CI-2", "PI-1", "TRIMING", "14", 1, 20)], {key}
		)
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0]["remaining_boxes"], -38, "unclamped in the breach report too")
		self.assertEqual(breaches[0]["over_boxes"], 39, "1 claimed on top of a 38-box overage")

	def test_unchanged_rows_produce_no_keys(self):
		# The guarantee that set_ci_status and compute_customs_fee(apply=1) — which
		# write a header field and never touch an item row — stay unblocked.
		rows = [
			_ci_line("CI-1", "PI-1", "BLADE", "12", 60, 1200),
			_ci_line("CI-1", "PI-1", "HEAD MEAT", "13", 10, 200),
		]
		self.assertEqual(rules.changed_allocation_keys(rows, list(rows)), set())
		self.assertEqual(
			rules.changed_allocation_keys(rows, list(reversed(rows))),
			set(),
			"row order is not an allocation change",
		)

	def test_reducing_boxes_is_never_a_breach(self):
		# A historic over-allocated CI must stay correctable downwards.
		before = [_ci_line("CI-1", "PI-1", "TRIMING", "14", 4238, 84760)]
		after = [_ci_line("CI-1", "PI-1", "TRIMING", "14", 4000, 80000)]
		self.assertEqual(rules.changed_allocation_keys(before, after), set())
		self.assertEqual(rules.changed_allocation_keys(before, []), set(), "deleting a row is not a claim")
		# Moving boxes between keys flags only the key that grew.
		moved = [_ci_line("CI-1", "PI-1", "BLADE", "12", 4238, 84760)]
		self.assertEqual(rules.changed_allocation_keys(before, moved), {rules.match_key("PI-1", "BLADE")})

	def test_historic_over_allocated_ci_saves_untouched(self):
		# Cancelling or re-statusing one of the 21 over-shipped msa keys must still
		# work: the item rows are identical, so no key is checked at all.
		pi_rows = [_pi_line("PI-1", "TRIMING", "14", 4200, 84000)]
		rows = [_ci_line("CI-1", "PI-1", "TRIMING", "14", 4238, 84760)]
		contract = rules.contract_index(pi_rows)
		shipped = rules.shipped_index([])  # CI-1 is the document being saved
		keys = rules.changed_allocation_keys(rows, list(rows))
		self.assertEqual(keys, set())
		self.assertEqual(rules.over_allocations(contract, shipped, rows, keys), [])
		# ...even though the key really is over-allocated when it IS inspected.
		self.assertEqual(
			len(rules.over_allocations(contract, shipped, rows, {rules.match_key("PI-1", "TRIMING")})), 1
		)

	def test_header_pi_fallback_attributes_the_row(self):
		# ~2 127 msa CI rows carry the PI link only on the header. Ignoring the
		# fallback would make them unattributable and the cap unenforceable.
		row = {
			"ci_name": "CI-2",
			"custom_proforma_invoice": "",
			"header_proforma_invoice": "PI-1",
			"category": "BLADE",
			"item": "12",
			"boxes": 41,
			"qty": 820,
		}
		key = rules.match_key("PI-1", "BLADE")
		self.assertEqual(rules.changed_allocation_keys(None, [row]), {key})

		contract, shipped, _ = self._fixture(shipped=[_ci_line("CI-1", "PI-1", "BLADE", "12", 60, 1200)])
		breaches = rules.over_allocations(contract, shipped, [row], {key})
		self.assertEqual(len(breaches), 1)
		self.assertEqual(breaches[0]["over_boxes"], 1)

		# A row with neither link carries no PI and cannot be keyed at all.
		orphan = dict(row, header_proforma_invoice="")
		self.assertEqual(rules.changed_allocation_keys(None, [orphan]), set())

	def test_insert_counts_every_allocating_row(self):
		rows = [
			_ci_line("CI-2", "PI-1", "BLADE", "12", 41, 820),
			_ci_line("CI-2", "PI-1", "HEAD MEAT", "13", 5, 100),
			_ci_line("CI-2", "PI-1", "", "14", 5, 100),  # no category — not a key
		]
		self.assertEqual(
			rules.changed_allocation_keys(None, rows),
			{rules.match_key("PI-1", "BLADE"), rules.match_key("PI-1", "HEAD MEAT")},
		)

	def test_a_key_on_no_pi_is_not_an_over_allocation(self):
		# "Not on any PI" is the `unattributable` defect diff_ci_line reports; there
		# is no contract balance to cap against, so the guard must not throw on it.
		contract, shipped, _ = self._fixture()
		stray = [_ci_line("CI-2", "PI-1", "MYSTERY CUT", "99", 500, 10000)]
		key = rules.match_key("PI-1", "MYSTERY CUT")
		self.assertEqual(rules.over_allocations(contract, shipped, stray, {key}), [])


class TestAllocationGuardQuery(unittest.TestCase):
	"""Source-level pins on the guard's SQL — it imports frappe, so it cannot be
	imported without a site (same ast/source pattern as
	test_commercial_invoice_transitions.py).
	"""

	@classmethod
	def setUpClass(cls):
		with open(_ALLOCATION_GUARD_PATH, encoding="utf-8") as fh:
			cls.source = fh.read()

	def test_query_excludes_cancelled_invoices(self):
		self.assertIn("ci.status != 'Cancelled'", self.source)

	def test_query_excludes_the_document_being_saved(self):
		self.assertIn("ci.name != %(self_name)s", self.source)

	def test_pi_attribution_uses_the_shared_row_then_header_expression(self):
		self.assertIn("_ci_item_effective_pi_expr", self.source)

	def test_gate_matches_the_status_pipeline_gate(self):
		self.assertIn("frappe.flags.in_msaerp_migration", self.source)
		self.assertIn("_imports_active", self.source)

	def test_no_clamp_on_the_remaining_balance(self):
		self.assertNotIn("max(0", self.source)


class TestAllocationGuardIsWiredIntoValidate(unittest.TestCase):
	"""The guard is only a guarantee if ``validate`` reaches it.

	The SPA creates invoices with ``doc.insert()``, so the call MUST sit above the
	controller's ``is_new()`` early return. Move it below and every frappe-free
	test here stays green while newly-created over-allocating invoices silently
	stop being refused — which is the one case the guard exists for. Source-text,
	because importing the controller needs a site.
	"""

	@classmethod
	def setUpClass(cls):
		with open(_CI_CONTROLLER_PATH, encoding="utf-8") as fh:
			cls.source = fh.read()

	def _line_of(self, needle: str) -> int:
		for number, line in enumerate(self.source.splitlines(), start=1):
			if needle in line:
				return number
		self.fail(f"{needle!r} not found in commercial_invoice.py")

	def test_validate_calls_the_guard(self):
		self.assertIn("assert_within_remaining(self)", self.source)

	def test_the_guard_runs_before_the_is_new_early_return(self):
		guard = self._line_of("assert_within_remaining(self)")
		validate = self._line_of("def validate(self)")
		is_new = self._line_of("if self.is_new():")
		self.assertGreater(guard, validate, "the guard must live inside validate()")
		self.assertLess(guard, is_new, "the guard must run before the is_new() early return")


if __name__ == "__main__":
	unittest.main()
