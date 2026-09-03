"""ADR-605's pre-win landed estimate against a live database.

`test_tender_prewin_landed_estimate` proves the selection rule and the pre-fill
without a bench, against a stubbed `frappe`. What it cannot see is everything that
only exists once the doctypes are real:

  * that a `Tender Sourcing Decision` re-award actually orders the way
    `_pick_sourcing_decision` assumes -- the frappe-free test hands it rows it
    wrote itself, so it proves the RULE and not that the rows carry the fields the
    rule reads (`approved_at` is only set by `approve_sourcing_decision`, and it is
    a Datetime the database returns as a `datetime`, not the string the stub used);
  * that `Supplier Quotation.custom_landed_charges` exists as a column at all --
    it is a Custom Field, so every quotation estimate in this feature is dead on a
    site where the fixture did not land, and `has_column` is the only honest way
    to find out;
  * that a foreign-currency charge line survives the round trip through
    `update_quotation_landed` -> stored JSON -> `get_quotation_landed` with its
    rate and its converted figure intact -- and that a HALF-SWITCHED line survives
    it too, which is the second review's P0: the save used to persist the reader's
    valued output, so the company-currency figure it could not value was written
    back as 0 and the warning vanished on the next read;
  * that `deal_bid_pricing`, the endpoint BidPricing actually calls, pre-fills from
    the quotation when the lot has no Purchase Order and stops doing so the moment
    it has one.

The permission case is the reason this file is not optional. `_quotation_landed_estimate`
calls `frappe.has_permission("Supplier Quotation", "read", doc=quotation)`, and a
permission check is exactly the kind of thing that passes in a test which stubbed it
to True. Whether a real non-privileged session is refused can only be measured here.

    cd /path/to/frappe-bench && bench --site <site> run-tests \\
        --module stabler.tests.test_tender_prewin_landed_bench

NOT in `.github/frappe-free-tests.txt` on purpose: it needs a live bench, so it runs
under `make test-bench`, never under `make check`.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import today

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # newer frappe
	from frappe.tests import IntegrationTestCase as FrappeTestCase

from stabler.api._procurement_policy import MIN_COUNTRIES, MIN_QUOTATIONS
from stabler.api.sourcing import get_quotation_landed, update_quotation_landed
from stabler.api.tender import (
	_bid_inputs,
	_quotation_landed_estimate,
	deal_bid_pricing,
)

_DECISION = "Tender Sourcing Decision"

#: Read on Tender Sourcing Decision, and NOT on Supplier Quotation. Verified from
#: the two doctype JSONs: the decision grants read to Sales User / Sales Manager /
#: System Manager, and Supplier Quotation grants it to the Purchase, Stock and
#: Manufacturing roles. A user with NO role at all cannot be used: the first thing
#: `_quotation_landed_estimate` does is `frappe.get_list(Tender Sourcing Decision)`,
#: which throws PermissionError under frappe v16 before the quotation is reached --
#: so the test would pass on the wrong exception and prove nothing about the
#: quotation read it exists to measure.
_READS_DECISIONS_NOT_QUOTATIONS = "Sales User"


def _tender_company() -> str | None:
	"""A company with the tender module on. Every endpoint below is gated on it."""
	for row in frappe.get_all("Stabler Company Modules", fields=["name", "company"], limit=50):
		if frappe.db.get_value("Stabler Company Modules", row["name"], "enable_tender"):
			return row["company"]
	return None


def _a_supplier() -> str | None:
	rows = frappe.get_all("Supplier", pluck="name", limit=1)
	return rows[0] if rows else None


def _an_item(company: str) -> str | None:
	rows = frappe.get_all("Item", filters={"is_stock_item": 1, "disabled": 0}, pluck="name", limit=1)
	return rows[0] if rows else None


class _TenderFixture(FrappeTestCase):
	"""A deal, two quotations and the decisions that name one of them.

	Every record is registered with `addClassCleanup` at the moment it is created,
	so a failure part-way through still takes its own rows out. Nothing here is
	submitted: a draft Supplier Quotation is enough for the landed estimate, and a
	draft leaves no ledger behind.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = _tender_company()
		cls.supplier = _a_supplier()
		cls.item = _an_item(cls.company) if cls.company else None
		# `CRM Deal.company` is a Stabler CUSTOM field (patch v56) — frappe-crm ships
		# no company on the deal at all. Without it every tender endpoint here is
		# scoped to nothing, so say that rather than failing on a NULL.
		#
		# `table_exists` FIRST: `has_column` raises TableMissingError rather than
		# returning False when the doctype's table is absent, and `crm` is installed
		# on 4 of the 7 stabler sites. On the other three this must read as "not
		# applicable", not as an error in setUpClass.
		cls.deal_scoped = frappe.db.table_exists("CRM Deal") and frappe.db.has_column("CRM Deal", "company")
		cls.ready = bool(cls.company and cls.supplier and cls.item and cls.deal_scoped)
		if not cls.ready:
			return
		cls.has_landed_field = frappe.db.has_column("Supplier Quotation", "custom_landed_charges")
		cls.deal = cls._make_deal()
		cls.cheap = cls._make_quotation(800_000_000.0)
		cls.dear = cls._make_quotation(900_000_000.0)

	@classmethod
	def _track(cls, doctype: str, name: str) -> str:
		cls.addClassCleanup(frappe.delete_doc, doctype, name, force=True, ignore_permissions=True)
		return name

	@classmethod
	def _make_deal(cls) -> str:
		# `organization` is a LINK to CRM Organization, not a label — a free-text
		# value is a LinkValidationError, which is what took every class down in
		# setUpClass. It is not reqd, and nothing under test reads it, so the lot
		# simply has none. `status` IS reqd but `CRM Deal.validate_status` fills it
		# on a new doc, so it is left out too rather than hard-coding a status name
		# that varies per site.
		doc = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"company": cls.company,
			}
		).insert(ignore_permissions=True)
		return cls._track("CRM Deal", doc.name)

	@classmethod
	def _make_quotation(cls, amount: float) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Supplier Quotation",
				"company": cls.company,
				"supplier": cls.supplier,
				"transaction_date": today(),
				"custom_crm_deal": cls.deal
				if frappe.db.has_column("Supplier Quotation", "custom_crm_deal")
				else None,
				"items": [{"item_code": cls.item, "qty": 1, "rate": amount}],
			}
		).insert(ignore_permissions=True)
		return cls._track("Supplier Quotation", doc.name)

	def _make_decision(self, quotation: str, *, status: str, approved_at: str | None = None) -> str:
		"""One decision, cleaned up when THIS test ends.

		Instance-level on purpose. As a classmethod on `addClassCleanup` every row a
		test created outlived it, so `test_a_draft_alone_is_enough`'s draft was still
		standing when `test_no_decision_names_nothing` ran and that test measured the
		previous one's fixture. frappe v16's `IntegrationTestCase` does not roll a
		test method back on its own.

		Three reqd/validated fields the first draft of this file omitted, each read
		from `tender_sourcing_decision.json` / `.py`:
		  * `selection_reason` is reqd -> MandatoryError;
		  * `_require_exception_when_the_quote_set_is_short` refuses an award below
		    MIN_QUOTATIONS/MIN_COUNTRIES without a written policy exception, and a
		    fresh doc has both counts at 0;
		  * `_enforce_one_way_status` refuses a document BORN approved, so an approval
		    is always an insert-then-promote, never an insert.
		"""
		doc = frappe.get_doc(
			{
				"doctype": _DECISION,
				"company": self.company,
				"deal": self.deal,
				"status": "Draft",
				"selected_quotation": quotation,
				"selection_reason": "ADR-605 bench fixture",
				# At the policy minimum, so the award needs no exception. Read from
				# `_procurement_policy` rather than written as 5/2: the constants move
				# and a copy here would silently stop matching the gate.
				"quotation_count": MIN_QUOTATIONS,
				"country_count": MIN_COUNTRIES,
			}
		).insert(ignore_permissions=True)
		name = doc.name
		self.addCleanup(frappe.delete_doc, _DECISION, name, force=True, ignore_permissions=True)
		if status == "Approved":
			# Written straight to the row rather than through
			# `approve_sourcing_decision`: that endpoint requires the director view and
			# stamps `now_datetime()` on every approval, which would make the two
			# timestamps this test orders by identical. `db.set_value` also skips
			# `_reject_client_written_approval`, which exists to stop a CLIENT writing
			# the stamp — not a fixture standing in for the server.
			frappe.db.set_value(
				_DECISION,
				name,
				{"status": "Approved", "approved_by": "Administrator", "approved_at": approved_at},
				update_modified=False,
			)
		return name

	def setUp(self):
		if not self.ready:
			self.skipTest(
				"site has no tender-enabled Company, Supplier, Item, or no CRM Deal.company "
				"custom field (run migrate)"
			)
		frappe.set_user("Administrator")


class TestOnlyTheStandingApprovalNamesTheQuotation(_TenderFixture):
	"""A lot can be awarded more than once; only the latest approval is in force.

	`purchasing._assert_awarded` orders by `approved_at desc` precisely to support
	the re-award that follows a winner falling through. If the pre-win estimate
	disagreed, the bid would be priced against a vendor the PO gate then refuses.
	"""

	def test_the_later_of_two_approvals_wins(self):
		self._make_decision(self.cheap, status="Approved", approved_at="2026-09-01 09:00:00")
		self._make_decision(self.dear, status="Approved", approved_at="2026-09-02 15:30:00")
		# An open draft on the OTHER bid, touched most recently of all: if the rule
		# were "newest row wins" this is the one it would pick.
		self._make_decision(self.cheap, status="Draft")
		est = _quotation_landed_estimate(self.deal, self.company)
		self.assertEqual(est["quotation"], self.dear)

	def test_a_draft_alone_is_enough(self):
		"""Pre-win there is at most a draft — an approval opens the PO route."""
		self._make_decision(self.dear, status="Draft")
		est = _quotation_landed_estimate(self.deal, self.company)
		self.assertEqual(est["quotation"], self.dear)

	def test_no_decision_names_nothing(self):
		est = _quotation_landed_estimate(self.deal, self.company)
		self.assertEqual(est["quotation"], "")
		self.assertFalse(est["denied"])


class TestAQuotationTheSessionMayNotRead(_TenderFixture):
	"""The check a stub cannot prove. `has_permission` is stubbed True in the
	frappe-free test, so whether a real unprivileged session is refused — and
	whether the refusal is reported as DENIED rather than as "nothing chosen" —
	can only be measured against a live permission stack."""

	def test_a_denied_read_is_reported_as_denied_not_as_no_decision(self):
		self._make_decision(self.dear, status="Draft")
		user = self._make_quotation_blind_user()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(user)
		# The precondition, measured rather than assumed: a site with a Custom DocPerm
		# granting this role read on Supplier Quotation would make the test pass while
		# exercising the permitted path. Say so instead of reporting a green.
		if frappe.has_permission("Supplier Quotation", "read", doc=self.dear):
			self.skipTest(
				f"this site grants {_READS_DECISIONS_NOT_QUOTATIONS} read on Supplier Quotation "
				"— the denied path is unreachable with this role"
			)
		est = _quotation_landed_estimate(self.deal, self.company)
		self.assertTrue(est["denied"], "an unreadable quotation must not read as 'none chosen'")
		self.assertEqual(est["quotation"], self.dear, "the officer needs to know WHICH record")
		self.assertEqual(est["amount"], 0.0)

	def _make_quotation_blind_user(self) -> str:
		"""A session that CAN read sourcing decisions and CANNOT read quotations.

		Not a role-less user: `_quotation_landed_estimate` reads the decision list
		first, and frappe v16 refuses that outright for a user with no read on the
		doctype (`db_query.py`), so the test would die before touching the quotation
		and prove nothing. The row is deleted when the test ends -- the first draft of
		this file left a permanent User behind on every run.
		"""
		email = "adr605-noaccess@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "ADR605",
				"send_welcome_email": 0,
				"roles": [{"role": _READS_DECISIONS_NOT_QUOTATIONS}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "User", email, force=True, ignore_permissions=True)
		return email


class TestAForeignChargeLineSurvivesTheRoundTrip(_TenderFixture):
	"""Store, re-read, and the figure must still be the one the officer typed.

	`custom_landed_charges` is a Custom Field, so this whole feature is dead on a
	site where the fixture did not land. Skipped with a reason rather than failing:
	that is a migrate problem, not a code problem — but it must be SAID, because a
	silent pass would report the round trip as proven on a site that cannot store
	a charge line at all.
	"""

	def setUp(self):
		super().setUp()
		if not self.has_landed_field:
			self.skipTest("Supplier Quotation.custom_landed_charges is not on this site — run migrate")

	def test_the_rate_and_the_converted_figure_are_both_stored(self):
		res = update_quotation_landed(
			self.dear,
			[
				{
					"charge_type": "Freight",
					"amount_original": 1200.0,
					"currency": "USD",
					"fx_rate": 12950.0,
					"rate_date": "2026-09-03",
				}
			],
			company=self.company,
		)
		self.addCleanup(frappe.db.set_value, "Supplier Quotation", self.dear, "custom_landed_charges", None)
		self.assertEqual(res["landed_charges_total"], 15_540_000.0)
		self.assertFalse(res["has_unvalued_charges"])

		stored = json.loads(frappe.db.get_value("Supplier Quotation", self.dear, "custom_landed_charges"))
		self.assertEqual(stored[0]["currency"], "USD")
		self.assertEqual(stored[0]["fx_rate"], 12950.0)
		self.assertEqual(stored[0]["amount_original"], 1200.0)

		read_back = get_quotation_landed(self.dear, company=self.company)
		self.assertEqual(read_back["landed_charges_total"], 15_540_000.0)
		self.assertEqual(read_back["charges"][0]["rate_date"], "2026-09-03")

	def test_the_half_switched_line_keeps_its_figure_on_disk(self):
		"""ADR-605 second review, P0, measured against the real column.

		Pick USD on a line already holding 3 200 000 so'm and save. The save path
		must store what it was given -- the frappe-free fixed-point test pins that
		against a fake `db.set_value`, and this pins it against the column, because
		the failure was a WRITE and a stub cannot prove a write landed.

		Reading the stored row again has to reach the same verdict: the flag is
		derived every time and never trusted from storage, so a refresh cannot make
		an incomplete estimate look sound.
		"""
		res = update_quotation_landed(
			self.dear,
			[
				{
					"charge_type": "Freight",
					"description": "sea freight",
					"amount": 3_200_000.0,
					"amount_original": 0,
					"currency": "USD",
					"fx_rate": 0,
				}
			],
			company=self.company,
		)
		self.addCleanup(frappe.db.set_value, "Supplier Quotation", self.dear, "custom_landed_charges", None)
		self.assertTrue(res["has_unvalued_charges"])

		stored = json.loads(frappe.db.get_value("Supplier Quotation", self.dear, "custom_landed_charges"))
		self.assertEqual(stored[0]["amount"], 3_200_000.0, "the save destroyed the officer's figure")
		for derived in ("company_amount", "capitalized_amount", "unvalued"):
			self.assertNotIn(derived, stored[0], f"a derived {derived} reached the column")

		read_back = get_quotation_landed(self.dear, company=self.company)
		self.assertTrue(read_back["has_unvalued_charges"], "the flag did not survive the reload")
		self.assertEqual(read_back["charges"][0]["amount"], 3_200_000.0)
		self.assertEqual(read_back["charges"][0]["company_amount"], 0.0)

	def test_a_line_with_no_usable_rate_is_stored_excluded_and_flagged(self):
		"""The contract the editor now relies on: store, exclude, flag.

		The editor stopped blocking Save on such a line precisely because the
		server does this. If the server ever refused instead, every flag downstream
		would become unreachable through the product.
		"""
		res = update_quotation_landed(
			self.dear,
			[
				{"charge_type": "Freight", "amount_original": 1200.0, "currency": "USD", "fx_rate": 0},
				{"charge_type": "Handling & Terminal", "amount": 250_000.0},
			],
			company=self.company,
		)
		self.addCleanup(frappe.db.set_value, "Supplier Quotation", self.dear, "custom_landed_charges", None)
		self.assertEqual(res["landed_charges_total"], 250_000.0)
		self.assertTrue(res["has_landed_estimate"], "an estimate WAS typed")
		self.assertTrue(res["has_unvalued_charges"], "and it is short — nothing else says so")


class TestTheEndpointBidPricingActuallyCalls(_TenderFixture):
	"""`deal_bid_pricing`, end to end, on a lot with and without a Purchase Order."""

	def setUp(self):
		super().setUp()
		if not self.has_landed_field:
			self.skipTest("Supplier Quotation.custom_landed_charges is not on this site — run migrate")

	def test_with_no_purchase_order_the_quotation_estimate_is_offered_and_pre_filled(self):
		self._make_decision(self.dear, status="Draft")
		update_quotation_landed(
			self.dear,
			[{"charge_type": "Freight", "amount": 25_000_000.0}],
			company=self.company,
		)
		self.addCleanup(frappe.db.set_value, "Supplier Quotation", self.dear, "custom_landed_charges", None)
		out = deal_bid_pricing(self.deal)
		self.assertEqual(out["quotation_landed_source"], self.dear)
		self.assertGreater(out["quotation_landed_estimate"], 0.0)
		# The pre-fill fills an EMPTY field; nothing has been saved on this deal.
		self.assertEqual(out["inputs"]["landed_goods"], out["quotation_landed_estimate"])
		self.assertEqual(out["po_count"], 0)

	def test_the_currency_is_the_company_default(self):
		"""BidPricing renders every figure with the workspace's `overview.currency`.

		`deal_intake` sets that from `Company.default_currency`, and the estimate
		sums `base_grand_total` — company currency too. Asserted here because the
		whole pre-fill rests on the two agreeing, and it is one prop away from being
		wrong.
		"""
		out = deal_bid_pricing(self.deal)
		self.assertEqual(out["currency"], frappe.db.get_value("Company", self.company, "default_currency"))

	def test_one_purchase_order_makes_the_operational_record_win(self):
		"""Post-win the PO sum outranks any estimate, and the estimate is not even
		queried — `_bid_inputs` skips the decision read entirely once a PO exists."""
		self._make_decision(self.dear, status="Draft")
		po = self._make_po()
		if not po:
			self.skipTest("Purchase Order.custom_crm_deal is not on this site — run migrate")
		_inp, refs = _bid_inputs(self.deal, self.company)
		self.assertEqual(refs["po_count"], 1)
		self.assertEqual(refs["quotation_landed_source"], "", "the estimate must not be queried")
		self.assertEqual(refs["quotation_landed_estimate"], 0.0)

	def _make_po(self) -> str | None:
		if not frappe.db.has_column("Purchase Order", "custom_crm_deal"):
			return None
		doc = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": self.company,
				"supplier": self.supplier,
				"transaction_date": today(),
				"schedule_date": today(),
				"custom_crm_deal": self.deal,
				"items": [
					{"item_code": self.item, "qty": 1, "rate": 500_000_000.0, "schedule_date": today()}
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Purchase Order", doc.name, force=True, ignore_permissions=True)
		return doc.name
