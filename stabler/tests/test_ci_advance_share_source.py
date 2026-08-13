"""Structural guards for the "Advance for this CI" card (stabler-64f).

This card replaces a section that was deliberately deleted from the very same
page hours earlier (commit `a7a4d55`): "Vendor Settlement" turned the Commercial
Invoice into a payment/accounting action centre — *Create Draft Purchase
Invoice*, *Pay Remaining*, a `PartyPaymentModal` drawer and the source PI's
**whole multi-CI** ledger embedded. What was rejected was the framing, not the
arithmetic, so the replacement is deliberately narrow: one read-only row per
source Proforma Invoice, this CI's share only, no action of any kind.

Two regressions are worth a test each:

  1. **Growth.** The easiest way to lose this boundary is one "small" button at a
     time. The guard below fails on any `<button>`, `PartyPaymentModal`,
     `convert_ci_to_purchase_invoice` or `PiAdvanceLedger` re-entering the card.
  2. **Lying about state.** The backend returns `planned` / `reserved` / `posted`
     as three separate amounts precisely so a *planned* proportional figure can
     never be rendered under an *applied* label. A single polymorphic `amount`
     field plus a label would compile, look right, and report money as booked
     that no ledger has ever seen.

Source-text, like its neighbours: a .vue SFC has no unit harness in this repo.

Run:
    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_advance_share_source
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
VUE = os.path.join(_ROOT, "public", "js", "pages", "imports", "CommercialInvoiceForm.vue")
API = os.path.join(_ROOT, "api", "imports.py")
STATUS = os.path.join(_ROOT, "public", "js", "composables", "status.js")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def py_func(src, name):
	"""Slice a module-level def up to the next module-level statement."""
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	nxt = re.search(r"^(?:def |@|class )", src[m.end() :], re.M)
	return src[m.start() : m.end() + nxt.start()] if nxt else src[m.start() :]


def js_block(src, name):
	"""Slice a `const x = computed(...)` / `function x(...)` up to its own close."""
	m = re.search(rf"^(?:const {name} = |function {name}\()", src, re.M)
	assert m, f"{name} not found"
	end = src.index("\n}", m.start())
	return src[m.start() : end + 2]


def card(src):
	"""Isolate the card. This page is ~2400 lines of unrelated cost/GRN/LCV
	markup — a whole-file search for "button" would pass forever regardless of
	what this card actually contains."""
	start = src.index('t("Advance for this CI")')
	return src[start : src.index("<!-- 4 Linked Containers -->", start)]


class PayloadContractTest(unittest.TestCase):
	"""The card renders whatever `getCommercialInvoice` hands it — so the payload
	key and the three amount fields are the contract, not an implementation
	detail."""

	def setUp(self):
		self.api = read(API)
		self.fn = py_func(self.api, "_ci_advance_share")

	def test_the_payload_carries_the_card_under_its_own_key(self):
		self.assertIn('"ci_advance_share": _ci_advance_share(doc) if _cost_visible() else None,', self.api)

	def test_cost_visibility_still_gates_it(self):
		# K3: advance figures are cost data. Dropping the gate would leak supplier
		# pricing to every user who can open a CI.
		self.assertIn("if _cost_visible() else None", self.api)

	def test_the_three_states_are_three_separate_amounts(self):
		for key in ("advance_planned", "advance_reserved", "advance_posted"):
			with self.subTest(key=key):
				self.assertIn(f'"{key}":', self.fn)

	def test_each_source_row_reports_all_three_never_one_polymorphic_amount(self):
		for key in ("planned", "reserved", "posted"):
			with self.subTest(key=key):
				self.assertIn(f'"{key}":', self.fn)
		self.assertNotIn('"amount":', self.fn)

	def test_the_state_string_matches_the_badge_map_keys(self):
		self.assertIn('"posted" if is_posted else ("reserved" if invoice else "planned")', self.fn)
		status = read(STATUS)
		self.assertIn('"CI Advance Share": {', status)
		for label in ("Planned:", "Reserved:", "Posted:"):
			with self.subTest(label=label):
				self.assertIn(label, status)


class PostedFiguresComeFromTheLedgerTest(unittest.TestCase):
	"""Once Accounts submits the Purchase Invoice the Payment Entry has no
	unallocated balance left, so deriving `posted` from `_ci_import_advances`
	would make a real allocation vanish from the card the moment it becomes
	most trustworthy. It is read from the child table instead, grouped by PI."""

	def setUp(self):
		self.fn = py_func(read(API), "_ci_advance_share")

	def test_booked_amounts_are_read_from_purchase_invoice_advance(self):
		self.assertIn("`tabPurchase Invoice Advance` pia", self.fn)
		self.assertIn("pia.reference_type = 'Payment Entry'", self.fn)

	def test_grouped_by_proforma_so_one_row_per_pi(self):
		self.assertIn("GROUP BY pe.custom_proforma_invoice", self.fn)

	def test_a_cancelled_purchase_invoice_is_not_treated_as_the_invoice(self):
		# docstatus < 2: a cancelled PInv must fall back to `planned`, not keep
		# showing its dead allocation as reserved.
		self.assertIn('"docstatus": ["<", 2],', self.fn)

	def test_planned_is_computed_only_when_there_is_no_invoice(self):
		self.assertIn("if not invoice:", self.fn)
		self.assertIn('allocation_by_proforma(plan["allocations"], advances)', self.fn)


class RejectedFramingStaysRejectedTest(unittest.TestCase):
	"""The deleted Vendor Settlement payload. Every one of these keys existed and
	was dropped on purpose — `remaining_to_pay` most of all, since "how much is
	left to pay" is exactly the payment-centre framing the user removed."""

	def setUp(self):
		self.api = read(API)
		self.fn = py_func(self.api, "_ci_advance_share")

	def test_the_old_function_name_is_gone(self):
		self.assertNotIn("_ci_vendor_settlement", self.api)

	def test_no_action_or_payment_keys_return(self):
		for forbidden in (
			"remaining_to_pay",
			"can_create_purchase_invoice",
			"can_pay_remaining",
			"advance_available_to_apply",
			"pi_ledgers",
		):
			with self.subTest(forbidden=forbidden):
				self.assertNotIn(forbidden, self.fn)


class TheCardOffersNoActionsTest(unittest.TestCase):
	"""The guard this file exists for. Anything that writes, pays, converts or
	embeds the PI's other CIs belongs on the Suppliers page or the PI page —
	never here."""

	def setUp(self):
		self.block = card(read(VUE))

	def test_no_buttons_at_all(self):
		self.assertNotIn("<button", self.block)

	def test_no_payment_drawer(self):
		self.assertNotIn("PartyPaymentModal", self.block)

	def test_no_purchase_invoice_conversion(self):
		for forbidden in ("convert_ci_to_purchase_invoice", "convertCiToPurchaseInvoice"):
			with self.subTest(forbidden=forbidden):
				self.assertNotIn(forbidden, self.block)

	def test_the_multi_ci_ledger_does_not_come_back(self):
		# PiAdvanceLedger shows every CI drawing on the PI. That whole-PI story is
		# one router-link away, on the PI page, and stays there.
		self.assertNotIn("PiAdvanceLedger", self.block)
		self.assertNotIn("PiAdvanceLedger", read(VUE))


class NoPlannedFigureUnderAPostedLabelTest(unittest.TestCase):
	"""Each display helper must branch on `state` and read the matching field.
	Reading `row.posted` in the planned branch (or vice versa) is the one
	failure mode that turns an estimate into a claim about the GL."""

	def setUp(self):
		self.vue = read(VUE)

	def test_the_row_amount_reads_the_field_that_matches_the_state(self):
		fn = js_block(self.vue, "advanceShareRowAmount")
		self.assertIn('if (s.state === "posted") return row.posted;', fn)
		self.assertIn('if (s.state === "reserved") return row.reserved;', fn)
		self.assertIn("return row.planned;", fn)

	def test_the_total_reads_the_field_that_matches_the_state(self):
		fn = js_block(self.vue, "advanceShareTotal")
		self.assertIn('if (s.state === "posted") return s.advance_posted;', fn)
		self.assertIn('if (s.state === "reserved") return s.advance_reserved;', fn)
		self.assertIn("return s.advance_planned;", fn)

	def test_applied_is_said_only_in_the_posted_branch(self):
		fn = js_block(self.vue, "advanceShareNote")
		posted_line = 'if (s.state === "posted") return t("Advance applied to this CI");'
		self.assertIn(posted_line, fn)
		self.assertEqual(fn.count("Advance applied"), 1)
		self.assertIn('return t("Advance planned for this CI");', fn)

	def test_the_planned_footer_says_it_has_not_been_booked(self):
		block = card(self.vue)
		self.assertIn("advanceShare.state === 'planned'", block)
		self.assertIn("Proportional share only", block)


class DisplayHygieneTest(unittest.TestCase):
	def setUp(self):
		self.vue = read(VUE)
		self.block = card(self.vue)

	def test_money_goes_through_the_shared_formatter_with_the_ci_currency(self):
		self.assertIn("fm(row.ci_amount, advanceShare.currency)", self.block)
		self.assertIn("fm(advanceShareRowAmount(row), advanceShare.currency)", self.block)

	def test_the_badge_goes_through_the_centralized_map(self):
		self.assertIn("getStatusBadgeClass('CI Advance Share', advanceShareState)", self.block)

	def test_the_pi_link_stays_inside_the_spa(self):
		self.assertIn("`/imports/proformas/${row.proforma_invoice}`", self.block)
		self.assertNotIn("/app/", self.block)

	def test_the_purchase_invoice_is_plain_text_not_a_desk_link(self):
		# The SPA has no Purchase Invoice route, and /app/ links are banned
		# outright — so the name is rendered, not linked.
		self.assertIn('<span class="font-monospace">{{ advanceShare.purchase_invoice }}</span>', self.block)

	def test_no_manual_stripe_class(self):
		self.assertNotIn("table-striped", self.block)

	def test_the_card_hides_itself_when_there_is_nothing_to_show(self):
		fn = js_block(self.vue, "advanceShare")
		self.assertIn("if (!costVisible.value) return null;", fn)
		self.assertIn("return s && (s.sources || []).length ? s : null;", fn)
		self.assertIn('<div v-if="advanceShare" class="card mb-3">', self.vue)

	def test_the_field_is_initialised_so_a_blank_form_renders_nothing(self):
		self.assertIn("ci_advance_share: null,", self.vue)


if __name__ == "__main__":
	unittest.main()
