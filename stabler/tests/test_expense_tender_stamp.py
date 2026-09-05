"""G.18 (Expense side) — the tender/deal an expense was booked to was invisible.

`Expenses.vue`'s read-only detail drawer (`stabler/public/js/pages/money/Expenses.vue`)
loads from `stabler.api.money.journal_entry_detail`, which never returned the
tender at all — confirmed against the local site before writing this test:

    bench --site stabler execute stabler.api.money.journal_entry_detail \\
        --args '["ACC-JV-2026-07011"]'
    -> no "tender" / "tender_label" key in the response

...although the document plainly carries one:

    SELECT parent, account, tender FROM `tabJournal Entry Account`
    WHERE parent = 'ACC-JV-2026-07011';
    -> both rows: tender = CRM-DEAL-2026-00015

    SELECT custom_crm_deal FROM `tabJournal Entry` WHERE name = 'ACC-JV-2026-07011';
    -> CRM-DEAL-2026-00015

Why `custom_crm_deal`, not the ADR-609 accounting-dimension field `tender`:
Journal Entry's PARENT never received that field — only its `Journal Entry
Account` child rows did (`accounting_dimension_doctypes` in erpnext/hooks.py
names "Journal Entry Account", not "Journal Entry"; confirmed on the local site:
`frappe.db.has_column("Journal Entry", "tender")` is False,
`frappe.db.has_column("Journal Entry Account", "tender")` is True). The legacy
`custom_crm_deal` field, however, DOES sit on the Journal Entry parent, and
`list_bank_entries` (money.py, a few lines above the code this test covers)
already reads it for the Expenses list's tender tag — `openEditFromDetail` in
Expenses.vue even has a standing comment noting the detail endpoint carries no
tender tag and works around it by reaching into the already-loaded list row.
This is the same field, read the same way, for the VIEW-mode drawer.

`_je_tender_stamp`/`_deal_display_label` are tested directly rather than through
`journal_entry_detail` itself: that function calls `frappe.get_doc(...)`, whose
real implementation is far too much machinery to fake credibly in a frappe-free
test, and the two helpers below are the entirety of the new logic — the wiring
that adds their result to `journal_entry_detail`'s returned dict is two lines,
read alongside this test in code review.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_expense_tender_stamp -v
"""

from __future__ import annotations

import importlib
import types
import unittest
from pathlib import Path

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

# Source-level read for WiringNotDroppedTest below — same idiom as
# test_related_documents_contract.py's SALES/`_endpoint_region`.
_ROOT = Path(__file__).resolve().parents[1]
MONEY_SOURCE = (_ROOT / "api" / "money.py").read_text(encoding="utf-8")


def tearDownModule():
	_SANDBOX.restore()


def _journal_entry_detail_region() -> str:
	"""`journal_entry_detail`'s body, up to the next whitelisted function.

	No fixed character window: a window would shift the moment a helper is
	added above or below this one, same lesson as
	test_related_documents_contract.py's `_endpoint_region`.
	"""
	start = MONEY_SOURCE.index("def journal_entry_detail")
	end = MONEY_SOURCE.find("@frappe.whitelist()", start)
	assert end > start, "no whitelist boundary found after journal_entry_detail"
	return MONEY_SOURCE[start:end]


def _load_money():
	"""Import `stabler.api.money` against a minimal hand-built `frappe`."""
	_SANDBOX.evict(
		"stabler.api.money",
		"stabler.api._common",
		"stabler.api._money",
		"stabler.api.approvals",
		"stabler.api.supplier_payment_guard",
		"stabler.api.tender_dimension",
		"frappe",
		"frappe.utils",
		"frappe.rate_limiter",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
	frappe.throw = lambda message, exc=Exception, *a, **k: (_ for _ in ()).throw(exc(str(message)))
	frappe.session = types.SimpleNamespace(user="tester@example.com")
	frappe.get_roles = lambda _user=None: []
	frappe.get_all = lambda *a, **k: []
	frappe.db = types.SimpleNamespace(
		has_column=lambda *a, **k: (_ for _ in ()).throw(AssertionError("has_column not stubbed")),
		get_value=lambda *a, **k: (_ for _ in ()).throw(AssertionError("get_value not stubbed")),
		exists=lambda *a, **k: True,
		sql=lambda *a, **k: [],
	)

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value=0: int(float(value or 0))
	utils.flt = lambda value=0, precision=None: float(value or 0)
	utils.getdate = lambda value=None: value
	utils.formatdate = lambda value, fmt=None: str(value)
	utils.today = lambda: "2026-09-05"
	frappe.utils = utils

	rate_limiter = types.ModuleType("frappe.rate_limiter")
	rate_limiter.rate_limit = lambda *a, **k: lambda fn: fn
	frappe.rate_limiter = rate_limiter

	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils, "frappe.rate_limiter": rate_limiter})

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *a, **k: None
	common._assert_can_write = lambda *a, **k: None
	common._require_company = lambda company: company
	common.check_concurrency = lambda *a, **k: None

	money_mod = types.ModuleType("stabler.api._money")
	money_mod.money_epsilon = lambda *a, **k: 0.005

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda _company: None

	guard = types.ModuleType("stabler.api.supplier_payment_guard")
	guard.assert_supplier_payment_currency = lambda *a, **k: None

	tender_dimension = types.ModuleType("stabler.api.tender_dimension")
	tender_dimension.assert_selectable_tender = lambda *a, **k: None

	_SANDBOX.install(
		{
			"stabler.api._common": common,
			"stabler.api._money": money_mod,
			"stabler.api.approvals": approvals,
			"stabler.api.supplier_payment_guard": guard,
			"stabler.api.tender_dimension": tender_dimension,
		}
	)
	return importlib.import_module("stabler.api.money")


class _FakeDoc(dict):
	"""Just enough of a Frappe Document for `_je_tender_stamp`: `.get(key)`."""


class JournalEntryTenderStampTest(unittest.TestCase):
	def test_reads_custom_crm_deal_off_the_parent_when_the_column_exists(self):
		# Real shape, read-only probed 2026-09-05: ACC-JV-2026-07011.
		money = _load_money()
		money.frappe.db.has_column = lambda doctype, column: (
			(doctype, column)
			== (
				"Journal Entry",
				"custom_crm_deal",
			)
		)
		money.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {
			"organization": "O'zbekiston temir yo'llari AJ [DEMO]",
			"lead_name": None,
		}
		doc = _FakeDoc(custom_crm_deal="CRM-DEAL-2026-00015")

		tender, label = money._je_tender_stamp(doc)

		self.assertEqual(tender, "CRM-DEAL-2026-00015")
		self.assertEqual(label, "O'zbekiston temir yo'llari AJ [DEMO] · CRM-DEAL-2026-00015")

	def test_a_site_without_the_legacy_column_reads_nothing(self):
		# has_column raises TableMissingError-shaped concerns on a missing TABLE,
		# not a missing COLUMN on an existing table (see 20-backend-migrations.md);
		# this is the ordinary "site never had this Custom Field" case, where
		# has_column simply returns False. Reading `doc.get(...)` anyway would be
		# safe (Frappe Documents answer None for an unknown attribute), but the
		# explicit guard matches `tender.py`'s own
		# `has_column("Sales Invoice", "custom_crm_deal")` precedent, so a reader
		# does not have to know that fact about `Document.get` to trust this code.
		money = _load_money()
		money.frappe.db.has_column = lambda *a, **k: False
		money.frappe.db.get_value = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("must not look up a CRM Deal when the column does not exist")
		)
		doc = _FakeDoc(custom_crm_deal="CRM-DEAL-2026-00015")

		tender, label = money._je_tender_stamp(doc)

		self.assertEqual((tender, label), ("", ""))

	def test_column_present_but_this_entry_carries_no_deal(self):
		money = _load_money()
		money.frappe.db.has_column = lambda *a, **k: True
		money.frappe.db.get_value = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("must not look up a CRM Deal for an untagged entry")
		)
		doc = _FakeDoc(custom_crm_deal="")

		tender, label = money._je_tender_stamp(doc)

		self.assertEqual((tender, label), ("", ""))


class DealDisplayLabelTest(unittest.TestCase):
	"""Same fallback chain as `stabler.api.sales._deal_display_label`, duplicated
	per this file's existing style of small per-module helpers rather than a new
	shared module for a two-line lookup (see `_account_title`/`_party_title`)."""

	def test_organization_wins_even_when_lead_name_is_also_present(self):
		# A CRM Deal can carry both; organization must be tried FIRST.
		money = _load_money()
		money.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {
			"organization": "O'zbekiston temir yo'llari AJ [DEMO]",
			"lead_name": "Someone Else",
		}

		label = money._deal_display_label("CRM-DEAL-2026-00015")

		self.assertEqual(label, "O'zbekiston temir yo'llari AJ [DEMO] · CRM-DEAL-2026-00015")

	def test_falls_back_to_lead_name_when_organization_is_blank(self):
		money = _load_money()
		money.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {
			"organization": None,
			"lead_name": "Aziz Karimov",
		}

		self.assertEqual(
			money._deal_display_label("CRM-DEAL-2026-00099"), "Aziz Karimov · CRM-DEAL-2026-00099"
		)

	def test_falls_back_to_the_deal_id_when_neither_name_is_set(self):
		# Review follow-up (P3): the naive `f"{name_part} · {deal}"` prints the
		# id twice once the fallback chain bottoms out at the deal id itself —
		# "CRM-DEAL-2026-00100 · CRM-DEAL-2026-00100". The bare id is what
		# `dealOptionLabel` in PurchaseOrderForm.vue already renders for this
		# exact case.
		money = _load_money()
		money.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {}

		self.assertEqual(money._deal_display_label("CRM-DEAL-2026-00100"), "CRM-DEAL-2026-00100")

	def test_no_deal_is_the_empty_string(self):
		money = _load_money()
		money.frappe.db.get_value = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("an empty deal must short-circuit before any lookup")
		)

		self.assertEqual(money._deal_display_label(""), "")


class JournalEntryDetailWiringNotDroppedTest(unittest.TestCase):
	"""Review follow-up (P2): the module docstring above says the wiring that
	adds `_je_tender_stamp`'s result to `journal_entry_detail`'s returned dict
	is "two lines, read alongside this test in code review" — which is exactly
	the gap. The two helpers are tested directly above; the two-line CALL SITE
	that actually puts their result on the response was never itself under
	test, and could silently drop back out (a merge, a copy-paste of the dict
	literal) with nothing here to notice. Source-level on purpose, same shape
	as test_related_documents_contract.py's `_endpoint_region`.
	"""

	def test_the_response_carries_the_tender_and_its_label(self):
		body = _journal_entry_detail_region()
		self.assertIn(
			'"tender": _tender',
			body,
			"journal_entry_detail's response dropped the tender field",
		)
		self.assertIn(
			'"tender_label": _tender_label',
			body,
			"journal_entry_detail's response dropped the tender_label field",
		)


class RegistrationTest(unittest.TestCase):
	def test_the_module_is_in_the_frappe_free_list(self):
		import pathlib

		root = pathlib.Path(__file__).resolve().parents[2]
		listed = (root / ".github" / "frappe-free-tests.txt").read_text().split()

		self.assertTrue(
			"stabler.tests.test_expense_tender_stamp" in listed,
			"module missing from .github/frappe-free-tests.txt — `make check` would not run it",
		)


if __name__ == "__main__":
	unittest.main()
