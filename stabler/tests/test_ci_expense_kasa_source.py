"""Source guards for the Commercial Invoice form's container / truck / expense blocks.

The 2026-08-11 regression shipped a version of this screen that compiled, passed
every test and still showed invented numbers: containers, trucks and expenses were
built with `Math.random()` into local arrays and never reached the database. A
compile check cannot see that, and neither can a "the form opened populated" smoke
check — so the guard lives here, in the source itself.

Frappe-free on purpose (listed in `.github/frappe-free-tests.txt`): it reads files.

	PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_expense_kasa_source -v
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_FORM_PATH = ROOT / "stabler/public/js/pages/imports/CommercialInvoiceForm.vue"
IMPORTS_API_PATH = ROOT / "stabler/api/imports.py"
IE_DOCTYPE_PATH = ROOT / "stabler/stabler/doctype/import_expense/import_expense.json"

CI_FORM = CI_FORM_PATH.read_text()
IMPORTS_API = IMPORTS_API_PATH.read_text()
IE_DOCTYPE = json.loads(IE_DOCTYPE_PATH.read_text())
IE_FIELDS = {f["fieldname"]: f for f in IE_DOCTYPE["fields"]}


class TestCiFormHasNoFabricatedRecords(unittest.TestCase):
	def test_no_client_side_record_invention(self):
		"""No screen may mint a record identity or an amount out of thin air."""
		for banned in ("Math.random()", "localTrucks"):
			with self.subTest(banned=banned):
				self.assertNotIn(banned, CI_FORM)

	def test_dead_demo_scaffolding_is_gone(self):
		# `invoicingMode` toggled two buttons and was read nowhere; the PINV name
		# was a constant baked into a translated string.
		for banned in ("invoicingMode", "ACC-PINV"):
			with self.subTest(banned=banned):
				self.assertNotIn(banned, CI_FORM)


class TestCiFormWritesThroughRealEndpoints(unittest.TestCase):
	def test_containers_are_linked_or_created_server_side(self):
		self.assertIn("importsApi.listImportContainers", CI_FORM)
		self.assertIn("importsApi.createImportContainer", CI_FORM)
		self.assertIn("importsApi.updateImportContainer", CI_FORM)
		# list_* endpoints return {rows, total_count}; forgetting `.rows` is the
		# defect class that emptied the tender master drawer.
		self.assertRegex(CI_FORM, r"(?s)async function searchContainers\(q\).*?res\?\.rows \|\| \[\]")
		# Linking = writing `commercial_invoice` on the real record, then reloading
		# from the server rather than trusting a local push.
		self.assertRegex(
			CI_FORM,
			r"(?s)async function linkContainer\(row\).*?commercial_invoice: docName\.value.*?await loadDoc\(\)",
		)

	def test_trucks_are_linked_or_created_server_side(self):
		self.assertIn("importsApi.listImportTrucks", CI_FORM)
		self.assertIn("importsApi.createImportTruck", CI_FORM)
		self.assertIn("importsApi.updateImportTruck", CI_FORM)
		self.assertRegex(CI_FORM, r"(?s)async function searchTrucks\(q\).*?res\?\.rows \|\| \[\]")
		self.assertRegex(
			CI_FORM,
			r"(?s)async function linkTruck\(row\).*?commercial_invoice: docName\.value.*?await loadDoc\(\)",
		)

	def test_expense_is_saved_through_the_import_expense_endpoint(self):
		self.assertRegex(
			CI_FORM,
			r"(?s)async function saveImportExpense\(\).*?importsApi\.createImportExpense\(",
		)
		# The cash-desk pair is what turns the expense into a real Journal Entry.
		for field in ("paid_from_account", "expense_account"):
			with self.subTest(field=field):
				self.assertIn(f"{field}: expenseForm.value.{field}", CI_FORM)
		# A voucher that went to the approval queue has NOT moved money yet; the
		# two outcomes must not share one green toast.
		self.assertIn("res?.pending_approval", CI_FORM)
		self.assertIn("res?.journal_entry", CI_FORM)

	def test_landed_cost_comes_from_the_server_not_from_local_arithmetic(self):
		self.assertIn("importsApi.calculateCiLandedCostUzs", CI_FORM)
		self.assertRegex(CI_FORM, r"landedCostUzs\.value\?\.items \|\| \[\]")

	def test_amount_uses_moneyinput_and_the_cash_desk_currency(self):
		self.assertIn("MoneyInput", CI_FORM)
		self.assertNotIn('<input type="number"', CI_FORM)
		self.assertNotIn('<input type="date"', CI_FORM)
		# Currency is read off the paying account — money.submit_expense_entry
		# rejects a line whose currencies differ, so it is never a free choice.
		self.assertIn("expensePayAccount.value?.account_currency", CI_FORM)
		self.assertIn("expenseCurrencyMismatch", CI_FORM)

	def test_new_invoice_hides_the_record_backed_cards(self):
		# On an unsaved CI there is no docName to link against; the cards must not
		# render at all rather than render empty demo state.
		self.assertGreaterEqual(CI_FORM.count('v-if="!isCreate"'), 8)


class TestImportExpenseCarriesTheKasaContract(unittest.TestCase):
	def test_doctype_has_the_three_cash_desk_fields(self):
		for fieldname, options in (
			("expense_account", "Account"),
			("paid_from_account", "Account"),
			("journal_entry", "Journal Entry"),
		):
			with self.subTest(fieldname=fieldname):
				self.assertIn(fieldname, IE_FIELDS)
				self.assertEqual(IE_FIELDS[fieldname]["fieldtype"], "Link")
				self.assertEqual(IE_FIELDS[fieldname]["options"], options)
				self.assertIn(fieldname, IE_DOCTYPE["field_order"])

	def test_journal_entry_is_not_user_writable(self):
		"""It is the posting's receipt and the idempotency key — never typed in."""
		self.assertEqual(IE_FIELDS["journal_entry"].get("read_only"), 1)

	def test_cash_desk_fields_stay_at_permlevel_zero(self):
		"""`Import Expense` carries no permlevel-1 DocPerm row.

		`bank_payment`/`cash_payment` are permlevel 1 and are therefore written with
		`db_set` after the save. If the new pair were also permlevel 1,
		`validate_higher_perm_levels` would silently drop them on insert and the
		expense would save with no cash desk at all.
		"""
		self.assertFalse(any(p.get("permlevel") for p in IE_DOCTYPE["permissions"]))
		for fieldname in ("expense_account", "paid_from_account"):
			with self.subTest(fieldname=fieldname):
				self.assertNotIn("permlevel", IE_FIELDS[fieldname])

	def test_api_posts_the_bank_entry_and_refuses_the_double_count(self):
		self.assertIn("def _post_expense_kasa_entry(doc)", IMPORTS_API)
		self.assertIn("from stabler.api.money import submit_expense_entry", IMPORTS_API)
		self.assertIn("def _assert_ie_payment_route(doc)", IMPORTS_API)
		# Both write endpoints, not just create.
		self.assertEqual(IMPORTS_API.count("_assert_ie_payment_route(doc)"), 3)
		self.assertEqual(IMPORTS_API.count("_post_expense_kasa_entry(doc)"), 3)

	def test_posting_is_idempotent_on_the_journal_entry_link(self):
		self.assertRegex(
			IMPORTS_API,
			r'(?s)def _post_expense_kasa_entry\(doc\).*?if doc\.get\("journal_entry"\)'
			r' or not doc\.get\("paid_from_account"\):\s*\n\s*return \{\}',
		)


if __name__ == "__main__":
	unittest.main()
