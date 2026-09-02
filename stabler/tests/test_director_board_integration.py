"""Against a real bench: an unpriced deal's row says "not priced" (P9) — but
until 2026-09-02 the header above it still counted a number nobody entered.

Coordinator re-review (P1-1) on `feat/prompt-14-director-board`, 2026-09-02:
`_bid_inputs`/`compute_bid_pnl` run for every tender deal regardless of
`has_pricing`, and for one with no stored `custom_bid_pricing` they back-solve
a bid price from `_BID_DEFAULTS` — a number nobody entered, built from
whatever `landed_goods` its Purchase Orders happen to sum to.  `total_value`,
`total_ost` and `margins.append` read that back-solved figure unconditionally;
the fix (`stabler/api/tender.py:2118-2122`) wraps all three in `if
has_pricing:`.

`directorBoardPricedState.spec.js` proves the SOURCE now reads `if
has_pricing:` around the right three statements. What it cannot see is
whether `_bid_inputs`/`compute_bid_pnl` genuinely produce a nonzero number for
an unpriced deal with real Purchase Orders on a real site, and whether that
number genuinely stays out of a real payload's totals once computed — a
`has_pricing` that is always `False` (say, because the `custom_bid_pricing`
column patch never ran here) would make the gate look correct while proving
nothing, the same way an empty Sales Order set let `so_board`/`tender_funnel`
"agree" for the wrong reason in `test_tender_board_funnel_integration.py`:
two empty sets are equal no matter what either filter says. `if has_pricing:`
is the line that decides whether a number nobody entered lands in a
director's KPI, and it has never once run against a real payload.

This module seeds a priced deal and an unpriced one carrying a real Purchase
Order and asserts the live payload: the header moves by exactly the priced
deal's own contribution, and by nothing at all for the unpriced one — even
though the unpriced deal's row still privately carries the back-solved
number, because P9 taught the CLIENT to hide it, not the server to stop
computing it. It also seeds the one milestone none of prompt 14's other
acceptance rows ever exercise — `guarantee` — and confirms `at_risk` actually
counts a deal that is overdue on nothing else.

Deliberately kept OUT of `.github/frappe-free-tests.txt` — collected by
`make test-bench` only, the same split and the same reason as
`test_tender_board_funnel_integration.py`.

WHAT IS NOT CLAIMED HERE
  - Per-document read permission on `visible_count`. `_tender_director_payload`
    calls `frappe.has_permission("CRM Deal", "read", doc=deal)` per row, so a
    user who cannot read one deal should see a smaller `visible_count` than
    Administrator does. Proving that needs a restricted-user fixture, and
    `_require_tender_view("director", ...)` may refuse such a user before the
    per-row filtering is even reachable — `test_tender_board_funnel_integration.py`
    declined the same shape of claim for the same reason ("belongs in its own
    module, not smuggled in here"), and that reasoning applies here unchanged.
  - The two further residuals the coordinator's review flagged as separate
    from this defect and not required to close alongside it: DRAFT Sales
    Orders still sit inside Portfolio value (`docstatus < 2`), and
    `value = so_revenue or bid_price` resolves per-deal rather than per-SO as
    the rule line's `sum(...)` phrasing reads. Neither is exercised by this
    module's fixtures.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from stabler.api import tender
from stabler.api._bid_pnl import _BID_DEFAULTS, compute_bid_pnl
from stabler.tests.fixtures import TEST_ITEM, TEST_SUPPLIER
from stabler.tests.test_tender_intake_master_fields_integration import _IntakeBenchFixture


class TestDirectorBoardHeaderExcludesUnpricedDeals(_IntakeBenchFixture, FrappeTestCase):
	"""Two deals on the same company: `deal_priced` (the base fixture's own
	deal, given a pricing plan in setUp) and `deal_unpriced` (a second deal,
	left without one). The main test adds a real Purchase Order to the
	unpriced deal and reads the live payload before and after."""

	def setUp(self):
		super().setUp()  # tender module on, self.company, self.deal
		self.deal_priced = self.deal
		self.deal_unpriced = self._make_deal()
		self.purchase_orders = []
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		# Explicit landed_goods, not derived from a PO: this deal's own
		# contribution to the header must not depend on anything the other
		# deal's fixture does.
		tender.save_deal_bid_pricing(
			deal=self.deal_priced.name,
			pricing={"mode": "margin", "margin_pct": 20.0, "landed_goods": 2_000_000.0},
		)

	def tearDown(self):
		for name in self.purchase_orders:
			if frappe.db.exists("Purchase Order", name):
				frappe.delete_doc("Purchase Order", name, force=True, ignore_permissions=True)
		if frappe.db.exists("CRM Deal", self.deal_unpriced.name):
			frappe.delete_doc("CRM Deal", self.deal_unpriced.name, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()  # deletes deal_priced (== self.deal), restores the module flag

	# ---- fixture helpers ---------------------------------------------------

	def _make_po(self, deal: str, landed_goods: float) -> str:
		"""A draft Purchase Order linking `deal` to a real `landed_goods` total.

		Left as a draft, not submitted — matching `seed_tender_demo.py`'s own
		`_orders()`: every reader here filters `docstatus < 2`, so a draft
		already counts, and submitting would add GL/stock side effects this
		claim has nothing to do with.
		"""
		po = frappe.new_doc("Purchase Order")
		po.company = self.company
		po.custom_crm_deal = deal
		po.supplier = TEST_SUPPLIER
		po.transaction_date = nowdate()
		po.schedule_date = add_days(nowdate(), 30)
		po.append(
			"items",
			{
				"item_code": TEST_ITEM,
				"qty": 1,
				"rate": landed_goods,
				"schedule_date": add_days(nowdate(), 30),
				"warehouse": self.warehouse,
			},
		)
		po.insert(ignore_permissions=True)
		self.purchase_orders.append(po.name)
		return po.name

	def _row(self, payload: dict, deal: str) -> dict:
		return next(r for r in payload["rows"] if r["deal"] == deal)

	# ---- the claims ---------------------------------------------------------

	def test_the_fixture_actually_produces_two_different_priced_states(self):
		# WHAT WOULD MAKE THIS FAIL: a seeding change that leaves both deals
		# equally (un)priced. Every assertion below reads `priced`/the totals
		# off the live payload; if the fixture never actually diverged, those
		# assertions would pass on a payload that never distinguished
		# anything — the same vacuous pass this whole module exists to rule
		# out ("two empty sets are equal no matter what either filter says").
		self.assertTrue(frappe.db.get_value("CRM Deal", self.deal_priced.name, "custom_bid_pricing"))
		self.assertFalse(frappe.db.get_value("CRM Deal", self.deal_unpriced.name, "custom_bid_pricing"))

	def test_an_unpriced_deal_with_a_real_purchase_order_does_not_move_the_header(self):
		# WHAT WOULD MAKE THIS FAIL: total_value/total_ost/margins.append
		# reverted to unconditional — the exact pre-2026-09-02 shape. The
		# unpriced deal's back-solved bid_price would then move all three
		# KPIs by a number nobody entered, which is the defect this test
		# exists to close.
		landed_goods = 1_000_000.0
		expected = compute_bid_pnl({**_BID_DEFAULTS, "landed_goods": landed_goods})

		priced_only = tender.tender_director_board(company=self.company)["kpi"]
		# Non-vacuous: the priced deal alone must already move the header, or
		# an unmoved total below would prove nothing about the unpriced deal
		# either — everything-empty would pass the same way.
		self.assertGreater(priced_only["total_value"], 0)
		self.assertGreater(priced_only["avg_margin"], 0)

		self._make_po(self.deal_unpriced.name, landed_goods)
		payload = tender.tender_director_board(company=self.company)
		both = payload["kpi"]

		# The header does not move AT ALL when the unpriced deal is added —
		# a claim about the CHANGE, not about an absolute total, so it holds
		# regardless of whatever else this site's company already carries.
		self.assertEqual(both["total_value"], priced_only["total_value"])
		self.assertEqual(both["total_ostatok"], priced_only["total_ostatok"])
		self.assertEqual(both["avg_margin"], priced_only["avg_margin"])

		row = self._row(payload, self.deal_unpriced.name)
		self.assertFalse(row["priced"])
		# The row still privately carries the back-solved number — P9 taught
		# the CLIENT to hide it (`priced: false` -> render "—"), not the
		# server to stop computing it. Asserting the exact figure here proves
		# the header's exclusion is doing real work against a real nonzero
		# number, not vacuously agreeing with a row that was already zero.
		self.assertEqual(row["value"], expected["bid_price"])
		self.assertGreater(row["value"], 0)


class TestDirectorBoardAtRiskCountsTheGuaranteeMilestone(_IntakeBenchFixture, FrappeTestCase):
	"""P1-3's corrected rule line, "any milestone · not done · days < 0",
	names `guarantee` as one of five. It is the one milestone none of prompt
	14's other acceptance rows ever exercises — no seeded demo deal sets
	`guarantee_return` at all (prompt 14 §7's own 2026-09-02 correction notes
	this) — so a deal overdue on nothing BUT its guarantee return has to
	actually be counted `at_risk`, not merely have a rule string that claims
	it would be."""

	def test_a_deal_overdue_only_on_guarantee_return_counts_as_at_risk(self):
		# WHAT WOULD MAKE THIS FAIL: `_deal_deadlines` reverting to four
		# milestones (dropping the conditional `guarantee` append), or the
		# risk rollup stopping at the first NOT-risk milestone instead of
		# walking the whole list — either would leave this deal's own overdue
		# date invisible to `at_risk` even though `_milestone` itself computes
		# "risk" for it correctly in isolation.
		before = tender.tender_director_board(company=self.company)["kpi"]["at_risk"]

		tender.save_deal_intake(deal=self.deal.name, intake={"guarantee_return": add_days(nowdate(), -5)})

		payload = tender.tender_director_board(company=self.company)
		# A delta, not an absolute count: robust to however many other
		# at-risk deals this site's company already carries.
		self.assertEqual(payload["kpi"]["at_risk"], before + 1)

		row = next(r for r in payload["rows"] if r["deal"] == self.deal.name)
		self.assertEqual(row["risk"], "risk")
