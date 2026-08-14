"""Guards for turning a CI-tagged cash/bank expense into an Import Expense (C1).

`/money/expenses` books an expense straight to GL as a Bank Entry Journal Entry.
When the operator tags that voucher with a Commercial Invoice the spend is an
import cost, so it has to become an ``Import Expense`` — otherwise it never shows
up in the CI cost overview and can never be capitalized onto the containers.

Three things about that mirroring are easy to break and expensive when broken:

* **it must fire on every path that submits the voucher.** Maker-checker routing
  submits later, from ``approvals.approve``, outside ``submit_expense_entry`` —
  so the spawn lives in a Journal Entry ``on_submit`` doc_event, the one point
  both the direct and the deferred path pass through. A version that calls the
  spawn from ``money.py`` instead silently creates nothing whenever approvals are
  on, and nothing fails loudly;
* **it must not fire twice, or in reverse.** ``imports._post_expense_kasa_entry``
  posts a Journal Entry *for* an Import Expense that already exists, and that
  voucher carries the same ``custom_commercial_invoice``. Without an explicit
  ``custom_import_expense`` back-link the hook would mirror a duplicate of its own
  parent. The back-link is written before insert, so it survives the approval
  path's document re-fetch — a ``journal_entry`` existence probe alone cannot,
  because ``_post_expense_kasa_entry`` only stamps that field *after* the voucher
  submits;
* **it must not raise a payable for money already paid.** The spawned expense is
  settled cash. Giving it a ``supplier`` would make ``wants_expense_pi`` spawn a
  DRAFT service Purchase Invoice, and giving it a ``truck`` would feed tier 1 of
  the cross-border transport lookup. Both bill the company a second time. The
  attribution stays on the voucher's own ``custom_import_truck`` instead.

Cancel is the mirror image: ``money.amend_expense_entry`` *cancels* the source
voucher rather than deleting it, so an unhandled cancel leaves the mirror behind
and the CI counts the cost twice.

Mostly frappe-free: the two decision functions are exercised as real unit tests,
the wiring is asserted against the source, so a refactor that quietly drops a
gate fails CI rather than production.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_je_import_expense_spawn -v
"""

from __future__ import annotations

import json
import os
import re
import unittest

from stabler.stabler.imports_module import payment_math as pm

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
APP_HOOKS = os.path.join(_ROOT, "hooks.py")
IMPORTS_HOOKS = os.path.join(_ROOT, "stabler", "imports_module", "hooks.py")
MONEY = os.path.join(_ROOT, "api", "money.py")
IMPORTS = os.path.join(_ROOT, "api", "imports.py")
PATCHES_TXT = os.path.join(_ROOT, "patches.txt")
PATCH = os.path.join(_ROOT, "patches", "v82_je_import_expense_link.py")
EXPENSES_VUE = os.path.join(_ROOT, "public", "js", "pages", "money", "Expenses.vue")
EXPENSE_JSON = os.path.join(
	_ROOT,
	"stabler",
	"doctype",
	"import_expense",
	"import_expense.json",
)


def read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def load(path: str) -> dict:
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


def options(doctype_json: dict, fieldname: str) -> list[str]:
	for f in doctype_json["fields"]:
		if f.get("fieldname") == fieldname:
			raw = f.get("options") or ""
			return [opt.strip() for opt in raw.split("\n") if opt.strip()]
	raise AssertionError(f"field {fieldname} not found")


def body(src: str, name: str) -> str:
	"""Extract a top-level function body (up to the next top-level def/decorator)."""
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"function {name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |#: |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


def code(src: str, name: str) -> str:
	"""Function body with its docstring removed — for 'must NOT appear' assertions."""
	text = body(src, name)
	m = re.search(r'"""', text)
	if not m:
		return text
	end = text.index('"""', m.end())
	return text[end + 3 :]


def doc_events_block(src: str, doctype: str) -> str:
	"""The ``doc_events`` entry for one doctype, so hooks can't be read off a sibling."""
	start = src.index(f'\t"{doctype}": {{')
	end = src.index("\n\t},", start)
	return src[start:end]


#: Every value the Import Expense ``category`` Select can hold, read off the
#: doctype rather than retyped — a category added there without updating the
#: patch or the SPA must fail here, not in production.
EXPENSE_CATEGORIES = options(load(EXPENSE_JSON), "category")


class WantsJeImportExpenseTest(unittest.TestCase):
	"""When a submitted expense voucher should mirror itself as an Import Expense."""

	def test_ci_tagged_positive_spend_spawns(self):
		self.assertTrue(
			pm.wants_je_import_expense(
				commercial_invoice="CI-2026-04387", owning_import_expense=None, amount=1200
			)
		)

	def test_untagged_voucher_is_left_completely_alone(self):
		# The whole point of the optional CI field: with it empty, /money/expenses
		# must behave byte-identically to how it did before this feature. Every
		# non-imports tenant posts exclusively through this branch.
		for ci in (None, "", "   "):
			with self.subTest(commercial_invoice=repr(ci)):
				self.assertFalse(
					pm.wants_je_import_expense(
						commercial_invoice=ci, owning_import_expense=None, amount=1200
					)
				)

	def test_a_voucher_that_already_has_a_parent_never_spawns(self):
		# The reverse flow: imports._post_expense_kasa_entry posts this JE *for* an
		# Import Expense, and tags it with the same CI. Mirroring here would create
		# a duplicate of the very document that asked for the payment.
		self.assertFalse(
			pm.wants_je_import_expense(
				commercial_invoice="CI-2026-04387",
				owning_import_expense="IMPEXP-00042",
				amount=1200,
			)
		)

	def test_zero_and_negative_amounts_do_not_spawn(self):
		# An Import Expense with no money in it adds a row to the CI cost overview
		# that changes no valuation — noise that reads as a real cost.
		for amount in (0, None, "0.00", -50):
			with self.subTest(amount=amount):
				self.assertFalse(
					pm.wants_je_import_expense(
						commercial_invoice="CI-2026-04387", owning_import_expense=None, amount=amount
					)
				)

	def test_sub_cent_amounts_round_away(self):
		# Money is compared at 2dp everywhere else in this module; 0.004 is not a
		# cost, it is rounding dust from an FX leg.
		self.assertFalse(
			pm.wants_je_import_expense(
				commercial_invoice="CI-2026-04387", owning_import_expense=None, amount=0.004
			)
		)
		self.assertTrue(
			pm.wants_je_import_expense(
				commercial_invoice="CI-2026-04387", owning_import_expense=None, amount=0.006
			)
		)


class JeCancelExpenseActionTest(unittest.TestCase):
	"""What happens to the mirrored expense when its voucher is cancelled."""

	def test_a_plain_mirror_is_deleted(self):
		# amend_expense_entry cancels rather than deletes the source, then posts a
		# replacement that spawns its own mirror. Leaving this one behind doubles
		# the CI's cost.
		self.assertEqual(
			pm.je_cancel_expense_action(owning_import_expense=None, include_in_landed_cost=0),
			"delete",
		)

	def test_a_capitalized_mirror_blocks_the_cancel(self):
		# Its cost already sits in a container's valuation as Container Cost Line
		# rows. Deleting the expense orphans those rows: the money stays in the
		# stock value with nothing left to trace it to, and the replacement voucher
		# adds it again.
		self.assertEqual(
			pm.je_cancel_expense_action(owning_import_expense=None, include_in_landed_cost=1),
			"block",
		)

	def test_an_imports_owned_expense_is_never_touched(self):
		# Here the Import Expense is the parent and the voucher is its payment.
		# Cancelling the payment must not delete the document that requested it —
		# and it must not be blocked either, capitalized or not.
		for capitalized in (0, 1):
			with self.subTest(include_in_landed_cost=capitalized):
				self.assertEqual(
					pm.je_cancel_expense_action(
						owning_import_expense="IMPEXP-00042", include_in_landed_cost=capitalized
					),
					"keep",
				)


class HookRegistrationTest(unittest.TestCase):
	"""The spawn has to hang off the document lifecycle, not off one API function."""

	def setUp(self):
		self.block = doc_events_block(read(APP_HOOKS), "Journal Entry")

	def test_spawn_runs_on_submit(self):
		# on_submit is the only point both the direct submit and the maker-checker
		# path (approvals.approve -> target.submit()) pass through. Called from
		# money.submit_expense_entry instead, the mirror would silently never be
		# created on any company with approvals switched on.
		self.assertIn(
			'"on_submit": [\n\t\t\t"stabler.stabler.imports_module.hooks.on_journal_entry_submit",',
			self.block,
		)

	def test_cleanup_runs_on_cancel(self):
		self.assertIn(
			'"on_cancel": [\n\t\t\t"stabler.stabler.imports_module.hooks.on_journal_entry_cancel",',
			self.block,
		)


class SpawnHookSourceTest(unittest.TestCase):
	"""The parts of the spawn whose absence is silent rather than loud."""

	def setUp(self):
		self.src = read(IMPORTS_HOOKS)
		self.spawn = code(self.src, "on_journal_entry_submit")
		self.cancel = code(self.src, "on_journal_entry_cancel")

	def test_spawn_is_gated_on_the_imports_module(self):
		# Journal Entry doc_events fire on all seven tenants. Without _should_run
		# the imports feature would start writing Import Expense rows on companies
		# that have the module switched off.
		self.assertIn("_should_run(doc)", self.spawn)

	def test_spawn_delegates_the_decision_to_payment_math(self):
		self.assertIn("pm.wants_je_import_expense(", self.spawn)
		self.assertIn("owning_import_expense=doc.get(\"custom_import_expense\")", self.spawn)

	def test_spawn_is_idempotent_per_voucher(self):
		# A cancelled-and-resubmitted voucher runs on_submit again; without the
		# probe it stacks a second mirror on the same CI.
		self.assertIn('frappe.db.exists("Import Expense", {"journal_entry": doc.name})', self.spawn)

	def test_spawn_sets_no_supplier(self):
		# A supplier makes wants_expense_pi spawn a DRAFT service Purchase Invoice
		# — a payable for cash that has already left the account.
		self.assertNotIn('"supplier":', self.spawn)

	def test_spawn_sets_no_truck(self):
		# A truck makes this expense eligible for tier 1 of the cross-border
		# transport lookup, which bills it to the trucking company on top of the
		# cash already paid. The truck stays on the voucher's custom_import_truck.
		self.assertNotIn('"truck":', self.spawn)

	def test_spawn_does_not_capitalize_by_itself(self):
		# Capitalizing is an explicit operator decision made on the imports side
		# (set_expense_landed_cost, which checks the account type). Money reaching
		# stock valuation as a side effect of paying a bill is exactly the silent
		# double count this whole chain is built to avoid.
		self.assertIn('"include_in_landed_cost": 0', self.spawn)

	def test_spawn_carries_the_voucher_back_reference(self):
		# Also the idempotency key that stops _post_expense_kasa_entry from posting
		# a second voucher for this expense.
		self.assertIn('"journal_entry": doc.name', self.spawn)

	def test_permlevel_fields_are_written_with_db_set(self):
		# bank_payment / cash_payment are permlevel 1 on a doctype that carries no
		# permlevel-1 permission row, so save() drops them silently and the expense
		# stays "Pending" forever despite being paid.
		self.assertIn("expense.db_set(", self.spawn)
		self.assertIn("pm.expense_status(", self.spawn)

	def test_cancel_blocks_instead_of_deleting_capitalized_costs(self):
		self.assertIn("frappe.throw(", self.cancel)
		self.assertIn("pm.je_cancel_expense_action(", self.cancel)


class MoneyApiWiringTest(unittest.TestCase):
	"""The two new arguments on submit_expense_entry, and where they are written."""

	def setUp(self):
		self.fn = body(read(MONEY), "submit_expense_entry")

	def test_category_is_written_only_when_the_field_exists(self):
		# Sites migrate at different times; a bare attribute write would break
		# /money/expenses on every site that has not run v82 yet.
		# Matched loosely across newlines: ruff format decides where this call wraps,
		# and the guard is what matters, not the line breaks.
		self.assertRegex(
			self.fn,
			r'if import_category and frappe\.get_meta\("Journal Entry"\)\.has_field\(\s*"custom_import_expense_category"\s*\)',
		)

	def test_back_link_is_written_outside_the_commercial_invoice_branch(self):
		# One tab = function body, two tabs = inside `if commercial_invoice:`.
		# The back-link is what suppresses the spawn, so it has to be honoured even
		# when the caller passes the expense without repeating its CI — nesting it
		# would make the suppression depend on an unrelated argument.
		self.assertIn('\n\tif import_expense and frappe.get_meta("Journal Entry").has_field(', self.fn)
		self.assertNotIn('\n\t\tif import_expense and', self.fn)


class KasaEntryWiringTest(unittest.TestCase):
	"""The reverse flow must announce itself, or it gets mirrored."""

	def test_kasa_entry_passes_its_own_name_as_the_owner(self):
		fn = body(read(IMPORTS), "_post_expense_kasa_entry")
		self.assertIn("import_expense=doc.name,", fn)

	def test_kasa_entry_forwards_the_category(self):
		fn = body(read(IMPORTS), "_post_expense_kasa_entry")
		self.assertIn('import_category=doc.get("category"),', fn)


class PatchTest(unittest.TestCase):
	"""The two custom fields the whole mechanism reads from."""

	def setUp(self):
		self.src = read(PATCH)

	def test_patch_is_registered(self):
		self.assertIn("stabler.patches.v82_je_import_expense_link", read(PATCHES_TXT))

	def test_patch_is_idempotent(self):
		# patches.txt has no [post_model_sync] marker and migrate re-runs are
		# routine; a second create_custom_fields call on an existing field throws.
		self.assertEqual(self.src.count('frappe.db.exists(\n\t\t"Custom Field"'), 1)
		self.assertIn('"Custom Field", {"dt": "Journal Entry", "fieldname": "custom_import_expense"}', self.src)

	def test_back_link_is_read_only(self):
		# It is set by the server for the kasa flow. A hand-editable back-link is a
		# hand-editable "do not mirror this" switch.
		self.assertIn('"fieldname": "custom_import_expense",', self.src)
		self.assertIn('"read_only": 1,', self.src)

	def test_category_options_match_the_doctype_exactly(self):
		# The value is copied verbatim onto Import Expense.category; anything the
		# doctype's Select does not accept fails validation at insert time, inside
		# an on_submit hook, i.e. it rolls back the user's expense entry.
		m = re.search(r'_CATEGORY_OPTIONS = "([^"]+)"', self.src)
		self.assertIsNotNone(m, "_CATEGORY_OPTIONS not found")
		listed = [opt for opt in m.group(1).split("\\n") if opt]
		self.assertEqual(listed, EXPENSE_CATEGORIES)

	def test_category_allows_being_empty(self):
		# The field sits on every Journal Entry in the system; the overwhelming
		# majority are not import expenses and must not be forced into a category.
		m = re.search(r'_CATEGORY_OPTIONS = "([^"]+)"', self.src)
		self.assertTrue(m.group(1).startswith("\\n"))


class ExpensesVueTest(unittest.TestCase):
	"""The SPA half: what the operator picks, and what it must not be able to pick."""

	def setUp(self):
		self.src = read(EXPENSES_VUE)

	def test_category_list_matches_the_doctype_exactly(self):
		m = re.search(r"const IMPORT_CATEGORIES = \[(.*?)\];", self.src, re.S)
		self.assertIsNotNone(m, "IMPORT_CATEGORIES not found")
		listed = re.findall(r'"([^"]+)"', m.group(1))
		self.assertEqual(listed, EXPENSE_CATEGORIES)

	def test_category_select_is_hidden_without_a_commercial_invoice(self):
		# Nothing is created without a CI, so the control would be a promise the
		# backend does not keep.
		self.assertIn('v-if="importsOn && form.commercial_invoice"', self.src)

	def test_valuation_account_is_matched_on_the_exact_erpnext_string(self):
		# ERPNext ships a near-miss sibling — "Expenses Included In Asset Valuation"
		# — which capitalizes into a fixed asset instead of stock. A prefix or
		# substring match would preselect it.
		self.assertIn('a.account_type === "Expenses Included In Valuation"', self.src)

	def test_prefill_never_overwrites_a_chosen_account(self):
		self.assertIn("if (!line.account) line.account = valuationAccount.value;", self.src)

	def test_category_is_sent_to_the_backend(self):
		self.assertIn("payload.import_category = form.value.import_category", self.src)
