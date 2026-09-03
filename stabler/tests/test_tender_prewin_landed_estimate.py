"""ADR-605 — where the pre-win `landed_goods` figure comes from (Frappe-free).

Before a Purchase Order exists there is no post-win landed cost, so `_bid_inputs`
pre-filled `landed_goods` from `_deal_landed` and got 0: the officer priced the bid
against a blank box, at exactly the moment Zafar's pre-win rule says the number must
be quick (`00-SETUP.md`, "The pre-win costing rule"). The lot's sourcing decision has
already NAMED a quotation by then, and that quotation carries the only pre-win landed
number anyone has typed.

Two things must not happen, and each has its own test below:

  * the cheapest bid must never stand in. `Tender Sourcing Decision.cheapest_quotation`
    sits right beside `selected_quotation`; the cheapest is a fact about the
    comparison, not a choice, and a lot's winner is often dearer for a reason the
    comparison cannot see. Pricing a tender off it puts a figure in front of the
    officer that nobody selected.
  * a figure the officer typed must never be overwritten. The pre-fill is a default
    for an empty field, exactly like the post-win PO default beside it.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_prewin_landed_estimate -v
"""

from __future__ import annotations

import importlib
import json
import types
import unittest
from datetime import date

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Row(dict):
	def __getattr__(self, key):
		return self[key]


# The lot's two bids. CHEAP is the cheaper delivered total; DEAR is the one the
# officer chose — a real tender is won on more than price.
_QUOTATIONS = {
	"SQ-CHEAP": {
		"base_grand_total": 800_000_000.0,
		"grand_total": 800_000_000.0,
		"custom_landed_charges": json.dumps([{"charge_type": "Freight", "amount": 10_000_000.0}]),
	},
	"SQ-DEAR": {
		"base_grand_total": 900_000_000.0,
		"grand_total": 900_000_000.0,
		"custom_landed_charges": json.dumps([{"charge_type": "Freight", "amount": 25_000_000.0}]),
	},
	# Same sticker price as SQ-DEAR, but its one charge line names a currency no
	# rate can value — so the landed estimate is 900m and KNOWN to be short.
	"SQ-BROKEN": {
		"base_grand_total": 900_000_000.0,
		"grand_total": 900_000_000.0,
		"custom_landed_charges": json.dumps(
			[{"charge_type": "Freight", "amount_original": 1200.0, "currency": "USD", "fx_rate": 0}]
		),
	},
}


class _FakeDB:
	def __init__(self, *, stored_pricing=None):
		self.stored_pricing = stored_pricing

	def has_column(self, doctype, field):
		return (doctype, field) in {
			("CRM Deal", "custom_bid_pricing"),
			("Purchase Order", "custom_crm_deal"),
			("Purchase Order", "custom_landed_charges"),
			("Sales Order", "custom_crm_deal"),
			("Supplier Quotation", "custom_landed_charges"),
		}

	def get_value(self, doctype, name, field, **_kwargs):
		if doctype == "CRM Deal" and field == "custom_bid_pricing":
			return self.stored_pricing
		if doctype == "Supplier Quotation":
			row = _QUOTATIONS.get(name)
			if not row:
				return None
			return _Row({k: row.get(k) for k in field}) if isinstance(field, list) else row.get(field)
		return None


def _load_tender(db: _FakeDB, decisions: list[dict], *, readable: bool = True):
	"""Import tender.py against only the Frappe surface `_bid_inputs` reaches."""
	_SANDBOX.evict(
		"stabler.api.tender",
		"stabler.api.purchasing",
		"frappe",
		"frappe.utils",
		"stabler.api.approvals",
		"stabler.api._common",
		"stabler.api._bid_package",
		"stabler.api.organization",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
	)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.DoesNotExistError = LookupError
	frappe.session = types.SimpleNamespace(user="source@example.com")
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]
	frappe.get_roles = lambda _user=None: ["Sales Manager"]
	frappe.has_permission = lambda *_args, **_kwargs: readable
	frappe.throw = lambda message, exception=Exception: (_ for _ in ()).throw(exception(message))

	def get_list(doctype, filters=None, order_by=None, limit_page_length=None, **_kwargs):
		"""Deliberately returns the rows UNSORTED and unlimited.

		The ADR-605 review caught the earlier stub honouring neither `order_by` nor
		`limit_page_length`, so the precedence test passed on the order the loop
		happened to ask in rather than on any rule. `_pick_sourcing_decision` now
		chooses in Python, and this stub hands it the rows in the worst order it
		could get them so the choosing is what is actually under test.
		"""
		if doctype != "Tender Sourcing Decision":
			return []
		return [_Row(d) for d in decisions]

	frappe.get_list = get_list
	frappe.get_all = lambda *_args, **_kwargs: []
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.getdate = lambda value: date.fromisoformat(str(value)[:10])
	utils.add_months = lambda value, months: value
	utils.cint = lambda value=0: int(float(value or 0))
	utils.today = lambda: "2026-09-03"
	utils.now = lambda: "2026-09-03 09:00:00"
	frappe.utils = utils
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda _company: None
	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda _company: None
	bid_package = types.ModuleType("stabler.api._bid_package")
	bid_package.assemble_bid_package = lambda *_args, **_kwargs: {}
	bid_package.build_bid_docx = lambda *_args, **_kwargs: b""
	organization = types.ModuleType("stabler.api.organization")
	organization._can_access_module = lambda *_args, **_kwargs: True
	purchasing = types.ModuleType("stabler.api.purchasing")
	purchasing.tender_quotations = lambda _deal: {"rows": []}
	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings.module_map_for = lambda _company: {"tender": True}
	_SANDBOX.install(
		{
			"stabler.api.approvals": approvals,
			"stabler.api._common": common,
			"stabler.api._bid_package": bid_package,
			"stabler.api.organization": organization,
			"stabler.api.purchasing": purchasing,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": settings,
		}
	)
	return importlib.import_module("stabler.api.tender")


# `cheapest_quotation` is populated on purpose and always disagrees with
# `selected_quotation`: it is the trap this module exists to keep shut.
_DRAFT_ON_DEAR = {
	"name": "TSD-1",
	"status": "Draft",
	"selected_quotation": "SQ-DEAR",
	"cheapest_quotation": "SQ-CHEAP",
	"approved_at": None,
	"modified": "2026-09-03 12:00:00",
}
_APPROVED_ON_CHEAP = {
	"name": "TSD-2",
	"status": "Approved",
	"selected_quotation": "SQ-CHEAP",
	"cheapest_quotation": "SQ-DEAR",
	"approved_at": "2026-09-01 09:00:00",
	"modified": "2026-09-01 09:00:00",
}
# An open draft on the OTHER bid, touched more recently than either approval.
# It exists so the ordering tests can DISTINGUISH the rules: "newest `modified`
# wins" and "a draft wins" both answer SQ-CHEAP here, and only "the standing
# approval wins" answers SQ-DEAR.
_LATER_DRAFT_ON_CHEAP = {
	"name": "TSD-4",
	"status": "Draft",
	"selected_quotation": "SQ-CHEAP",
	"cheapest_quotation": "SQ-DEAR",
	"approved_at": None,
	"modified": "2026-09-04 08:00:00",
}


# A re-award: the first winner fell through and the lot was awarded again, later.
_REAPPROVED_ON_DEAR = {
	"name": "TSD-3",
	"status": "Approved",
	"selected_quotation": "SQ-DEAR",
	"cheapest_quotation": "SQ-CHEAP",
	"approved_at": "2026-09-02 15:30:00",
	"modified": "2026-09-02 15:30:00",
}


def _inputs(decisions, *, stored_pricing=None, readable=True):
	tender = _load_tender(_FakeDB(stored_pricing=stored_pricing), decisions, readable=readable)
	return tender._bid_inputs("DEAL-1", "Test Company")


class TestNoDecisionMeansNoEstimate(unittest.TestCase):
	def test_two_bids_and_no_decision_pre_fill_nothing(self):
		"""The screen must say "choose one", never choose one itself.

		Both quotations exist and either could be summed. Guessing here is the
		failure mode ADR-605 refuses: a number arrives in the bid price and no
		human ever picked the vendor it came from.
		"""
		inp, refs = _inputs([])
		self.assertEqual(refs["quotation_landed_estimate"], 0.0)
		self.assertEqual(refs["quotation_landed_source"], "")
		self.assertEqual(inp["landed_goods"], 0.0)


class TestTheDecisionNamesTheQuotation(unittest.TestCase):
	def test_a_draft_decision_is_enough(self):
		"""Pre-win there is at most a DRAFT.

		An approval is what opens the PO route (`purchasing._assert_awarded`), so
		requiring one would leave the field blank for the entire stage this feature
		exists to serve.
		"""
		inp, refs = _inputs([_DRAFT_ON_DEAR])
		self.assertEqual(refs["quotation_landed_estimate"], 925_000_000.0)
		self.assertEqual(refs["quotation_landed_source"], "SQ-DEAR")
		self.assertEqual(inp["landed_goods"], 925_000_000.0)

	def test_the_dearer_chosen_bid_wins_over_the_cheaper_one(self):
		# The decision names SQ-DEAR while SQ-CHEAP is 115 000 000 cheaper
		# delivered. Reading `cheapest_quotation` — the field sitting right beside
		# `selected_quotation` — would price the tender off a vendor nobody chose.
		_inp, refs = _inputs([_DRAFT_ON_DEAR])
		self.assertEqual(refs["quotation_landed_source"], "SQ-DEAR")
		self.assertNotEqual(refs["quotation_landed_estimate"], 810_000_000.0)

	def test_an_approval_in_force_outranks_a_draft(self):
		# Same precedence as `sourcing._standing_award`: a lot can be awarded more
		# than once and only the standing approval is real. Inventing a second
		# ordering here would let this screen name a winner the PO gate refuses.
		_inp, refs = _inputs([_DRAFT_ON_DEAR, _APPROVED_ON_CHEAP])
		self.assertEqual(refs["quotation_landed_source"], "SQ-CHEAP")
		self.assertEqual(refs["quotation_landed_estimate"], 810_000_000.0)

	def test_the_landed_charges_are_included_not_just_the_sticker_price(self):
		# 900 000 000 + 25 000 000. A bid priced off the sticker price alone omits
		# every freight and duty line the officer typed.
		_inp, refs = _inputs([_DRAFT_ON_DEAR])
		self.assertEqual(refs["quotation_landed_estimate"] - 900_000_000.0, 25_000_000.0)


class TestOnlyTheStandingApprovalCounts(unittest.TestCase):
	"""ADR-605 review, item 7. The rule, not the order the rows arrived in.

	`_pick_sourcing_decision` is handed every decision the lot has, unsorted, and
	must reach the same answer `sourcing._standing_award` would: a lot can be
	awarded more than once and only the LATEST approval is in force. Naming a
	superseded winner here would price the bid against a vendor the PO gate refuses.
	"""

	def test_the_later_approval_wins_over_the_earlier_one(self):
		# SQ-CHEAP was approved on the 1st, SQ-DEAR on the 2nd, and a draft on
		# SQ-CHEAP was touched on the 4th. Only "the standing approval, latest
		# first" answers SQ-DEAR; sorting by `modified` or preferring the draft
		# both answer SQ-CHEAP — a winner the PO gate would refuse.
		_inp, refs = _inputs([_APPROVED_ON_CHEAP, _REAPPROVED_ON_DEAR, _LATER_DRAFT_ON_CHEAP])
		self.assertEqual(refs["quotation_landed_source"], "SQ-DEAR")

	def test_the_answer_does_not_depend_on_the_order_the_rows_arrive_in(self):
		# The earlier stub honoured no `order_by`, so the old precedence test was
		# really asserting the order of a tuple in the implementation's own loop.
		rows = [_APPROVED_ON_CHEAP, _REAPPROVED_ON_DEAR, _LATER_DRAFT_ON_CHEAP]
		first = _inputs(rows)[1]
		second = _inputs(list(reversed(rows)))[1]
		self.assertEqual(first["quotation_landed_source"], second["quotation_landed_source"])
		self.assertEqual(first["quotation_landed_source"], "SQ-DEAR")

	def test_a_decision_naming_no_quotation_is_skipped_not_chosen(self):
		# An approved decision with an empty `selected_quotation` must not shadow
		# the draft that does name one — it would blank the field for no reason.
		empty_approval = dict(
			_APPROVED_ON_CHEAP,
			name="TSD-9",
			selected_quotation="",
			approved_at="2026-09-09 00:00:00",
			modified="2026-09-09 00:00:00",
		)
		_inp, refs = _inputs([empty_approval, _REAPPROVED_ON_DEAR])
		self.assertEqual(refs["quotation_landed_source"], "SQ-DEAR")


class TestAnEstimateThatIsItselfIncomplete(unittest.TestCase):
	def test_the_unvalued_line_count_travels_with_the_figure(self):
		"""ADR-605 review, item 4.

		The chosen quotation's own charge line cannot be valued, so `amount` is
		already short. A caller that shows the figure without this count presents a
		confident pre-win price built on an estimate nobody flagged.
		"""
		_inp, refs = _inputs([{**_DRAFT_ON_DEAR, "selected_quotation": "SQ-BROKEN"}])
		self.assertEqual(refs["quotation_landed_unvalued"], 1)
		self.assertEqual(refs["quotation_landed_estimate"], 900_000_000.0)

	def test_a_sound_estimate_reports_nothing_to_flag(self):
		_inp, refs = _inputs([_DRAFT_ON_DEAR])
		self.assertEqual(refs["quotation_landed_unvalued"], 0)


class TestAQuotationTheUserMayNotRead(unittest.TestCase):
	def test_a_denied_read_is_not_the_same_as_no_decision(self):
		"""ADR-605 review, item 5.

		Collapsing the two told a sourcing officer to "select a quotation for this
		lot" when one had already been selected — an instruction they cannot carry
		out, and which hides the real obstacle, a permission.
		"""
		_inp, refs = _inputs([_DRAFT_ON_DEAR], readable=False)
		self.assertTrue(refs["quotation_landed_denied"])
		self.assertEqual(refs["quotation_landed_source"], "SQ-DEAR")
		self.assertEqual(refs["quotation_landed_estimate"], 0.0)

	def test_no_decision_at_all_is_not_reported_as_denied(self):
		_inp, refs = _inputs([])
		self.assertFalse(refs["quotation_landed_denied"])


class TestATypedFigureIsNeverOverwritten(unittest.TestCase):
	def test_a_stored_landed_goods_survives_the_pre_fill(self):
		"""The pre-fill is a default for an empty field, not a correction.

		The officer's own number is the one the bid was quoted on; replacing it on
		the next page load would silently re-price a submitted tender.
		"""
		inp, refs = _inputs([_DRAFT_ON_DEAR], stored_pricing=json.dumps({"landed_goods": 777_000_000.0}))
		self.assertEqual(inp["landed_goods"], 777_000_000.0)
		# Still reported, so the screen can offer it as a link rather than force it.
		self.assertEqual(refs["quotation_landed_estimate"], 925_000_000.0)


if __name__ == "__main__":
	unittest.main()
