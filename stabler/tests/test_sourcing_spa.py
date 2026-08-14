"""Source contracts for the in-SPA supplier quotation entry (Faz 2 · Task 2).

The project ships no Vue test runner, so these are structural guards on the
component source. Each one stands for a rule that has already been broken once
somewhere in this tree: a bare date input the OS localizes, a raw number field
for money, a link that escapes to the Frappe Desk, a component nobody mounts.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_sourcing_spa -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
DRAWER = _ROOT / "public" / "js" / "components" / "QuotationEntryDrawer.vue"
SOURCING = _ROOT / "public" / "js" / "pages" / "tender" / "SourcingWorkspace.vue"
RFQ_FORM = _ROOT / "public" / "js" / "pages" / "tender" / "rfq" / "RfqForm.vue"
RFQ_DETAIL = _ROOT / "public" / "js" / "pages" / "tender" / "rfq" / "RfqDetail.vue"
API = _ROOT / "api" / "sourcing.py"


def _read(path: Path) -> str:
	return path.read_text(encoding="utf-8")


def _template(path: Path) -> str:
	src = _read(path)
	start = src.index("<template>")
	return re.sub(r"<!--[\s\S]*?-->", "", src[start:])


class TestQuotationDrawerUsesTheSharedInputs(unittest.TestCase):
	def setUp(self):
		self.src = _read(DRAWER)

	def test_money_goes_through_moneyinput(self):
		"""CLAUDE.md hard rule: no bare `<input type="number">` for an amount.
		A rate typed into a raw number field loses the tenant's decimal
		convention, and the rate is what the whole comparison ranks on."""
		self.assertIn("MoneyInput", self.src)
		self.assertNotIn('type="number"', self.src)

	def test_dates_go_through_dateinput(self):
		"""A bare `<input type="date">` renders in the OS locale, not dd.mm.yyyy.
		`valid_till` decides whether a quotation still counts."""
		self.assertIn("DateInput", self.src)
		self.assertNotIn('type="date"', self.src)

	def test_every_search_field_advertises_the_shortcut(self):
		"""Search placeholders carry `⌘K` everywhere else in the SPA; two lonely
		fields that do not are how a convention stops being one."""
		placeholders = re.findall(r':placeholder="t\(\'([^\']+)\'\)"', self.src)
		self.assertTrue(placeholders, "drawer has no typeahead placeholder at all")
		for text in placeholders:
			with self.subTest(placeholder=text):
				self.assertIn("⌘K", text)

	def test_no_escape_to_the_frappe_desk(self):
		self.assertNotIn("/app/", self.src)

	def test_no_hand_written_stripe_class(self):
		"""Striping is global; writing it by hand applies the rule twice."""
		self.assertNotIn("table-striped", self.src)


class TestSavingAndSubmittingStayTwoActions(unittest.TestCase):
	"""The policy count distinguishes a draft from a submitted quotation.

	If the save handler also submitted, "5 quotations collected from 2 countries"
	would become unfalsifiable — every half-typed draft would read as a firm
	offer, and the badge that gates bid pricing would go green on nothing.
	"""

	def setUp(self):
		self.src = _read(DRAWER)

	def _function_body(self, name: str) -> str:
		start = self.src.index(f"async function {name}(")
		tail = self.src[start:]
		end = tail.index("\n}\n")
		return tail[:end]

	def test_the_save_handler_never_submits(self):
		self.assertNotIn("submit_supplier_quotation", self._function_body("save"))

	def test_submitting_is_its_own_handler_and_endpoint(self):
		body = self._function_body("submitQuotation")
		self.assertIn("stabler.api.sourcing.submit_supplier_quotation", body)
		self.assertNotIn("save_supplier_quotation", body)

	def test_submit_is_disabled_until_a_draft_exists(self):
		"""There is nothing to submit before the first save, and a button that
		looks live but throws server-side reads as a broken screen."""
		self.assertIn(':disabled="!form.name || submitting"', self.src)

	def test_the_drawer_calls_the_company_scoped_endpoints(self):
		"""Every sourcing endpoint requires an explicit company; a call that
		omits it fails the tenant guard server-side, i.e. it never works."""
		for endpoint in ("save_supplier_quotation", "submit_supplier_quotation"):
			with self.subTest(endpoint=endpoint):
				call_site = self.src[self.src.index(f"stabler.api.sourcing.{endpoint}") :][:400]
				self.assertIn("company: activeCompany.value", call_site)


class TestTheDrawerIsActuallyReachable(unittest.TestCase):
	"""A component nobody mounts is dead code. `TenderControlTower.vue` sat in
	this tree for weeks at 319 lines with no route and no importer; this test is
	the cheap version of noticing."""

	def test_the_sourcing_screen_mounts_the_drawer(self):
		page = _read(SOURCING)
		self.assertIn("QuotationEntryDrawer", page)
		self.assertIn("<QuotationEntryDrawer", _template(SOURCING))

	def test_the_screen_reloads_the_comparison_after_a_save(self):
		"""Otherwise the quotation the user just entered is missing from the very
		table they entered it for, and the policy badge still says 4/5."""
		self.assertRegex(_template(SOURCING), r'@saved="[^"]*load')


class TestTheDrawerMirrorsTheServerRules(unittest.TestCase):
	"""Client-side validation is a courtesy, never the gate — but a courtesy that
	disagrees with the server teaches users to distrust the form."""

	def setUp(self):
		self.drawer = _read(DRAWER)
		self.api = _read(API)

	def test_valid_till_date_input_binds_min(self):
		self.assertIn(':min="minValidTill"', self.drawer)

	def test_a_negative_rate_is_refused_on_both_sides(self):
		self.assertIn("Rate cannot be negative", self.drawer)
		self.assertIn("Rate cannot be negative", self.api)

	def test_a_missing_currency_is_refused_on_both_sides(self):
		self.assertIn("Pick the currency the supplier quoted in.", self.drawer)
		self.assertIn("Pick the currency the supplier quoted in.", self.api)

	def test_valid_till_before_transaction_date_refused_on_both_sides(self):
		self.assertIn("cannot be before transaction date", self.drawer)
		self.assertIn("cannot be before transaction date", self.api)

	def test_the_client_never_claims_to_be_the_authorization(self):
		"""If this comment goes, so does the reason the checks are duplicated."""
		self.assertIn("api/sourcing.py", self.drawer)


class TestSourcingWorkspaceContract(unittest.TestCase):
	def setUp(self):
		self.src = _read(SOURCING)

	def test_the_workspace_no_longer_edits_money_or_dates(self):
		"""RFQ creation moved to its own page (RfqForm); the workspace keeps
		the comparison and the award. What remains here may not regress to raw
		inputs either — but the shared-component contract now lives with the
		form that actually edits those values (TestRfqFormContract below)."""
		self.assertNotIn('type="number"', self.src)
		self.assertNotIn('type="date"', self.src)

	def test_every_search_field_advertises_the_shortcut(self):
		placeholders = re.findall(r':placeholder="t\(\'([^\']+)\'\)"', self.src)
		self.assertTrue(placeholders, "workspace has no typeahead placeholder at all")
		for text in placeholders:
			if "Search" in text:
				with self.subTest(placeholder=text):
					self.assertIn("⌘K", text)

	def test_no_escape_to_the_frappe_desk(self):
		self.assertNotIn("/app/", self.src)

	def test_approval_button_does_not_call_save_decision(self):
		"""Approval and save are separate actions and separate endpoints."""
		approve_start = self.src.index("async function approveDecision()")
		approve_body = self.src[approve_start : approve_start + 400]
		self.assertIn("approve_sourcing_decision", approve_body)
		self.assertNotIn("save_sourcing_decision", approve_body)


class TestRfqFormContract(unittest.TestCase):
	"""The RFQ form inherited the workspace's old job — asking suppliers — so
	it inherits the structural contracts that came with it, plus the one this
	slice exists for: the tender's items must pre-fill it."""

	def setUp(self):
		self.src = _read(RFQ_FORM)

	def test_money_goes_through_moneyinput(self):
		self.assertIn("MoneyInput", self.src)
		self.assertNotIn('type="number"', self.src)

	def test_dates_go_through_dateinput(self):
		self.assertIn("DateInput", self.src)
		self.assertNotIn('type="date"', self.src)

	def test_the_prefill_comes_from_the_deal_defaults(self):
		"""The items a tender was specified with arrive from the server, not
		from client-side guessing about the lot."""
		self.assertIn("stabler.api.sourcing.get_deal_rfq_defaults", self.src)

	def test_every_search_field_advertises_the_shortcut(self):
		placeholders = re.findall(r':placeholder="t\(\'([^\']+)\'\)"', self.src)
		self.assertTrue(placeholders, "form has no typeahead placeholder at all")
		for text in placeholders:
			with self.subTest(placeholder=text):
				self.assertIn("⌘K", text)

	def test_no_escape_to_the_frappe_desk(self):
		self.assertNotIn("/app/", self.src)

	def test_the_draft_is_created_through_the_scoped_endpoint(self):
		call_site = self.src[self.src.index("stabler.api.sourcing.create_rfq") :][:400]
		self.assertIn("company: activeCompany.value", call_site)


class TestRfqPagesAreLinked(unittest.TestCase):
	"""A page nobody reaches is dead code — the TenderControlTower lesson, now
	applied on day one instead of weeks later."""

	def test_the_workspace_links_to_the_rfq_pages(self):
		src = _read(SOURCING)
		self.assertIn("tender-rfq-new", src)
		self.assertIn("tender-rfq-detail", src)

	def test_the_detail_page_links_back_to_the_comparison(self):
		src = _read(RFQ_DETAIL)
		self.assertIn("tender-sourcing", src)
		self.assertNotIn("/app/", src)


if __name__ == "__main__":
	unittest.main()
