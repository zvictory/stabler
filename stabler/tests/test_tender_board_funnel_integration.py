"""Against a real bench: the funnel's number and the board it navigates to
name the SAME Sales Orders.

Prompt 18's acceptance row C14 says "the board's filter matches the number that
navigated to it". Until 2026-09-02 it could not: `so_board` swapped in
`{"docstatus": ["<", 2]}` whenever `tender_only` was on, so turning the filter
ON *added* rows — the drafts — while `tender_funnel` counted `docstatus == 1`
only. The user clicked a chevron reading 7 and landed on a board showing 9.
`tests/test_tender_board_filter.py` pins the fix at the source level, and
`make test` runs it.

What that module cannot see is the actual row sets. It reads the filter dict out
of the file; it never asks a database what comes back. So the fix was verified
by reading, and by calling both endpoints by hand against genesis-test.local —
where the answer was "0 cards in both modes", because that site had no Sales
Order at all. Equal, and worth nothing: two empty sets are equal no matter what
either filter says.

This module seeds the four orders that make the sets differ and asserts the
agreement on real rows. It is deliberately kept OUT of
`.github/frappe-free-tests.txt` so only `make test-bench` collects it — the same
split, and the same reason, as `test_tender_intake_master_fields_integration.py`.

WHAT IS NOT CLAIMED HERE
  - Per-document read permission. The funnel reads with `frappe.get_all` and
    checks nothing; the board reads with `frappe.get_list` and then calls
    `frappe.has_permission(..., doc=...)` per row. A user who may see the number
    but not the order would see the two disagree. Observing that needs a
    restricted-user fixture, and `_require_any_tender_view` may refuse such a
    user before the divergence is even reachable — so it belongs in its own
    module, not smuggled in here.
  - The 2000-row cap. `so_board` passes `limit_page_length=2000`; the funnel
    passes 0 (unlimited). A tenant with more submitted orders than that would
    diverge silently. Seeding 2001 orders to prove it is not worth the minutes
    it would add to every future run of this suite.
  - Stage agreement. The board reports `custom_board_stage or "New"`; the funnel
    folds the same field through `_funnel.bucket_so`. This module asserts the
    two name the same ORDERS, not that they place them in the same column.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from stabler.api import tender
from stabler.tests.fixtures import TEST_ITEM
from stabler.tests.test_tender_intake_master_fields_integration import _IntakeBenchFixture


class TestBoardAndFunnelNameTheSameOrders(_IntakeBenchFixture, FrappeTestCase):
	"""Four orders, chosen so that every filter this pair applies separates two
	of them: submitted/draft, deal-linked/not, open/closed."""

	def setUp(self):
		super().setUp()  # tender module on, a CRM Deal to link to
		for column in ("custom_crm_deal", "custom_board_stage"):
			if not frappe.db.has_column("Sales Order", column):
				self.skipTest(f"site has not run the Sales Order {column} patch")
		if not frappe.db.exists("Item", TEST_ITEM):
			self.skipTest(f"{TEST_ITEM} fixture is required")
		# _Test Item is a stock item (tests/fixtures.py), and ERPNext refuses to
		# submit a Sales Order line for one without a delivery warehouse. Resolved
		# rather than spelled "Stores - _TC": the abbreviation is a fixture detail
		# and a renamed company would break this module for a reason that has
		# nothing to do with what it asserts.
		self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not self.warehouse:
			self.skipTest(f"{self.company} has no leaf warehouse")
		self.customer = self._customer()
		self.orders = []
		self.so_open = self._make_so(deal=self.deal.name, submit=True)
		self.so_plain = self._make_so(deal=None, submit=True)
		self.so_draft = self._make_so(deal=self.deal.name, submit=False)
		self.so_closed = self._make_so(deal=self.deal.name, submit=True)
		# db.set_value, not `update_status("Closed")`: the two endpoints under
		# test both READ `status` off the table, so writing the column writes
		# exactly the state they see. update_status would drag in credit-limit
		# and delivery checks that have nothing to do with this claim.
		frappe.db.set_value("Sales Order", self.so_closed, "status", "Closed")
		frappe.db.commit()

	def tearDown(self):
		"""Orders first: `custom_crm_deal` is a Link, so the deal cannot be
		deleted while one still points at it.

		A submitted order has to be CANCELLED before it can go — `force=True`
		does not bypass that check, it only bypasses the link check. And a
		Closed one refuses to cancel, so its status goes back first. Leaving
		them behind is not an option: `_closed_orders()` reads the site, so one
		leaked Closed order would poison the next run's divergence assertion."""
		for name in self.orders:
			if not frappe.db.exists("Sales Order", name):
				continue
			if frappe.db.get_value("Sales Order", name, "docstatus") == 1:
				frappe.db.set_value("Sales Order", name, "status", "To Deliver and Bill")
				frappe.get_doc("Sales Order", name).cancel()
			frappe.delete_doc("Sales Order", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Customer", self.customer):
			frappe.delete_doc("Customer", self.customer, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	# ---- fixture helpers -------------------------------------------------

	def _customer(self) -> str:
		name = "_Test Tender Board Customer"
		if frappe.db.exists("Customer", name):
			return name
		doc = frappe.new_doc("Customer")
		doc.customer_name = name
		doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	def _make_so(self, *, deal: str | None, submit: bool) -> str:
		so = frappe.new_doc("Sales Order")
		so.company = self.company
		so.customer = self.customer
		so.transaction_date = nowdate()
		so.delivery_date = add_days(nowdate(), 7)
		so.custom_crm_deal = deal or ""
		so.append(
			"items",
			{
				"item_code": TEST_ITEM,
				"qty": 1,
				"rate": 1000,
				"delivery_date": add_days(nowdate(), 7),
				"warehouse": self.warehouse,
			},
		)
		so.insert(ignore_permissions=True)
		if submit:
			so.submit()
		self.orders.append(so.name)
		return so.name

	# ---- what each side actually returns ---------------------------------

	def _board(self, tender_only: int) -> set[str]:
		res = tender.so_board(company=self.company, tender_only=tender_only)
		return {c["name"] for c in res["cards"]}

	def _funnel(self) -> dict:
		return tender.tender_funnel(company=self.company)

	def _funnel_orders(self) -> set[str]:
		out = self._funnel()
		return {r["so"] for rows in (out.get("so_rows") or {}).values() for r in rows}

	def _closed_orders(self) -> set[str]:
		"""Every submitted, deal-linked order this company hides from the board.

		Measured, not assumed to be the fixture's one: the divergence assertion
		below is a claim about the SITE, and hardcoding `{self.so_closed}` would
		turn it into a claim about this fixture that a stray Closed order
		elsewhere on the site would break for the wrong reason."""
		return set(
			frappe.get_all(
				"Sales Order",
				filters={
					"company": self.company,
					"custom_crm_deal": ["is", "set"],
					"docstatus": 1,
					"status": ["in", ("Closed", "Cancelled")],
				},
				pluck="name",
			)
		)

	# ---- the claims ------------------------------------------------------

	def test_the_fixture_actually_separates_the_two_sides(self):
		# WHAT WOULD MAKE THIS FAIL: a seeding change that lands all four orders
		# in the same bucket. Every assertion below is a set comparison, and set
		# comparisons pass trivially on sets that were never made to differ —
		# which is exactly how the by-hand verification on 2026-09-02 reported
		# "equal" on a site holding no Sales Orders at all. This test exists so
		# that a vacuous run of this module is a RED, not a green.
		self.assertEqual(len(set(self.orders)), 4, "the four fixture orders are not distinct")
		self.assertEqual(frappe.db.get_value("Sales Order", self.so_draft, "docstatus"), 0)
		self.assertEqual(frappe.db.get_value("Sales Order", self.so_open, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Sales Order", self.so_closed, "status"), "Closed")
		self.assertFalse(frappe.db.get_value("Sales Order", self.so_plain, "custom_crm_deal"))
		self.assertIn(
			self.so_open, self._board(tender_only=1), "the fixture's own open order is not on the board"
		)

	def test_the_board_never_shows_an_order_the_funnel_did_not_count(self):
		# WHAT WOULD MAKE THIS FAIL: the board widening its filter — the C14
		# defect exactly. This is the direction the user experiences: they click
		# a chevron reading 7 and the board it opens shows 9, so the number they
		# were given is wrong the moment they act on it. There is no acceptable
		# excess here, which is why this asserts an empty set rather than a
		# tolerance.
		self.assertEqual(self._board(tender_only=1) - self._funnel_orders(), set())

	def test_closed_contracts_are_the_only_thing_the_funnel_counts_and_the_board_hides(self):
		# WHAT WOULD MAKE THIS FAIL: either side changing its mind about Closed
		# — and a NEW divergence appearing, which is the more valuable half. The
		# gap is deliberate (a closed contract is not work in progress, and the
		# board is a work board), and prompt 18's S1 says so; what must not
		# happen is a second, undocumented gap growing beside it unnoticed.
		self.assertEqual(self._funnel_orders() - self._board(tender_only=1), self._closed_orders())

	def test_a_draft_is_on_neither_side(self):
		# WHAT WOULD MAKE THIS FAIL: `{"docstatus": ["<", 2]}` coming back to
		# so_board. A draft is a proposal nobody has committed to: counting it
		# as a contract inflates the board, and it inflated it ONLY when the
		# tender filter was on, so the number and the board disagreed by exactly
		# the drafts. The funnel never counted them, which is why the fix moved
		# the board and not the funnel.
		self.assertNotIn(self.so_draft, self._board(tender_only=1))
		self.assertNotIn(self.so_draft, self._board(tender_only=0))
		self.assertNotIn(self.so_draft, self._funnel_orders())

	def test_turning_the_filter_off_only_ever_adds(self):
		# WHAT WOULD MAKE THIS FAIL: tender_only doing anything besides narrow.
		# It is ONE axis — deal-linked or not — and the whole C14 defect was a
		# second axis riding along with it. A filter that both adds and removes
		# rows cannot be reasoned about by the person using it.
		wide, narrow = self._board(tender_only=0), self._board(tender_only=1)
		self.assertTrue(narrow <= wide, f"tender_only=1 shows rows tender_only=0 does not: {narrow - wide}")
		self.assertIn(self.so_plain, wide)
		self.assertNotIn(self.so_plain, narrow)
		self.assertNotIn(self.so_plain, self._funnel_orders(), "the funnel counts an order no deal points at")

	def test_the_number_on_the_chevron_equals_the_list_it_drills_to(self):
		# WHAT WOULD MAKE THIS FAIL: the count and the rows being built in two
		# passes that can drift. tender_funnel builds them in one loop precisely
		# so they cannot — this asserts that property rather than trusting the
		# comment, and it is the number C14 is about: what the user reads before
		# they click.
		out = self._funnel()
		counted = sum(out["so"][b] for b in ("contract", "procurement", "delivery", "done"))
		self.assertEqual(counted, len(self._funnel_orders()))
		self.assertEqual(counted, len(self._board(tender_only=1)) + len(self._closed_orders()))
