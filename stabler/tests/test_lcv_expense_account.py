"""The imports LCV expense account must never be resolved on emptiness alone.

`Stabler Settings` is a Single: one global account name for every company on the
site, and nothing revalidates it when a chart of accounts changes. Measured on
msa (2026-08-14) the field named an account that did not exist at all — and the
old check, `if not expense_account`, read that as "configured", handed it to the
voucher payload and killed the entire landed-cost chain (LCV_COUNT = 0) on a
setting no user ever sees.

So these tests encode WHY the resolver looks the way it does: a value that
cannot carry the charge — missing, another company's, a group, not an expense —
must behave exactly like an empty one and fall back. The one thing it must never
do is post a company's landed cost to a different company's account.

Bench-free: `frappe` is stubbed into ``sys.modules`` for the duration of each
load and restored afterwards, so a full bench run is unaffected.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from contextlib import contextmanager

_HOOKS = "stabler.stabler.imports_module.hooks"
_FAKES = ("frappe", "frappe.utils")


class _Dict(dict):
	"""frappe._dict stand-in — the resolver reads rows with attribute access."""

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError as exc:  # pragma: no cover - defensive
			raise AttributeError(key) from exc


class _Db:
	def __init__(self, accounts: dict, singles: dict):
		self.accounts = accounts
		self.singles = singles

	def get_single_value(self, _doctype, field):
		return self.singles.get(field)

	def get_value(self, doctype, filters, fieldname, as_dict=False, **_kwargs):
		assert doctype == "Account", doctype
		if isinstance(filters, dict):
			for name, row in self.accounts.items():
				if all(row.get(key) == value for key, value in filters.items()):
					return _Dict(row, name=name)[fieldname] if not as_dict else _Dict(row, name=name)
			return None
		row = self.accounts.get(filters)
		if row is None:
			return None
		row = _Dict(row, name=filters)
		return row if as_dict else row.get(fieldname)


@contextmanager
def _hooks(accounts: dict, singles: dict):
	"""Import hooks.py against a fake bench, then put ``sys.modules`` back."""
	saved = {name: sys.modules.get(name) for name in (*_FAKES, _HOOKS)}
	warnings: list[str] = []
	try:
		frappe = types.ModuleType("frappe")
		frappe._ = lambda value: value
		frappe.flags = types.SimpleNamespace()
		frappe.db = _Db(accounts, singles)
		frappe.throw = lambda message, *a, **k: (_ for _ in ()).throw(Exception(message))
		frappe.whitelist = lambda *a, **k: (lambda fn: fn)
		frappe.logger = lambda _name=None: types.SimpleNamespace(
			warning=warnings.append, info=lambda *a, **k: None, error=lambda *a, **k: None
		)
		utils = types.ModuleType("frappe.utils")
		utils.cint = lambda value=0: int(value or 0)
		utils.flt = lambda value=0, precision=None: float(value or 0)
		utils.getdate = lambda value=None: value
		utils.now_datetime = lambda: None
		utils.today = lambda: "2026-08-14"
		frappe.utils = utils

		sys.modules.update({"frappe": frappe, "frappe.utils": utils})
		sys.modules.pop(_HOOKS, None)
		yield importlib.import_module(_HOOKS), warnings
	finally:
		for name, module in saved.items():
			if module is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = module


VALID = {"company": "MSA", "is_group": 0, "root_type": "Expense", "account_type": "Tax"}
EIIV = {
	"company": "MSA",
	"is_group": 0,
	"root_type": "Expense",
	"account_type": "Expenses Included In Valuation",
}


class TestResolveLcvExpenseAccount(unittest.TestCase):
	def _resolve(self, accounts, singles, company="MSA"):
		with _hooks(accounts, singles) as (hooks, warnings):
			return hooks.resolve_lcv_expense_account(company), warnings

	def test_configured_and_usable_account_wins(self):
		"""A deliberate setting must beat auto-discovery — that is what it is for."""
		account, warnings = self._resolve(
			{"Chosen - M": VALID, "Auto - M": EIIV},
			{"imports_lcv_expense_account": "Chosen - M"},
		)
		self.assertEqual(account, "Chosen - M")
		self.assertEqual(warnings, [])

	def test_nonexistent_account_falls_back_instead_of_killing_the_chain(self):
		"""The msa outage: a filled-but-missing name must behave like an empty one."""
		account, warnings = self._resolve(
			{"Expenses Included In Valuation - M": EIIV},
			{"imports_lcv_expense_account": "5113 - Expenses Included In Valuation - M"},
		)
		self.assertEqual(account, "Expenses Included In Valuation - M")
		self.assertTrue(any("unusable" in w for w in warnings), warnings)

	def test_account_of_another_company_is_never_posted_to(self):
		"""The setting is site-wide, Account is company-bound — a mismatch is a
		cross-company posting, the one failure worse than no voucher at all."""
		account, _ = self._resolve(
			{
				"Foreign - A": {**VALID, "company": "ANJAN"},
				"Expenses Included In Valuation - M": EIIV,
			},
			{"imports_lcv_expense_account": "Foreign - A"},
		)
		self.assertEqual(account, "Expenses Included In Valuation - M")

	def test_group_account_falls_back(self):
		"""Frappe refuses GL entries against a group account — accept it here, not
		three doctypes later inside the voucher's own validation."""
		account, _ = self._resolve(
			{"Indirect Expenses - M": {**VALID, "is_group": 1}, "Auto - M": EIIV},
			{"imports_lcv_expense_account": "Indirect Expenses - M"},
		)
		self.assertEqual(account, "Auto - M")

	def test_non_expense_account_falls_back(self):
		account, _ = self._resolve(
			{"Debtors - M": {**VALID, "root_type": "Asset"}, "Auto - M": EIIV},
			{"imports_lcv_expense_account": "Debtors - M"},
		)
		self.assertEqual(account, "Auto - M")

	def test_promoted_field_is_the_second_candidate(self):
		"""``api/lcv.py`` already treats the two Stabler Settings fields as
		interchangeable; a site configured only through the promoted field must not
		silently drop to auto-discovery here."""
		account, _ = self._resolve(
			{"Promoted - M": VALID, "Auto - M": EIIV},
			{"imports_lcv_expense_account": "", "landed_cost_expense_account": "Promoted - M"},
		)
		self.assertEqual(account, "Promoted - M")

	def test_discovery_prefers_expenses_included_in_valuation(self):
		"""Landed cost belongs in valuation; a plain expense account is the last
		resort, not an equal one."""
		account, warnings = self._resolve(
			{"Plain Expense - M": VALID, "Valuation - M": EIIV},
			{},
		)
		self.assertEqual(account, "Valuation - M")
		self.assertTrue(any("auto-discovered" in w for w in warnings), warnings)

	def test_discovery_falls_back_to_any_expense_account(self):
		account, _ = self._resolve({"Plain Expense - M": VALID}, {})
		self.assertEqual(account, "Plain Expense - M")

	def test_discovery_is_company_scoped(self):
		"""Auto-discovery must not reach into another company's chart either."""
		account, _ = self._resolve({"Plain Expense - A": {**VALID, "company": "ANJAN"}}, {})
		self.assertIsNone(account)

	def test_nothing_resolvable_returns_none_so_the_caller_can_throw(self):
		"""Fail loud: no account means a visible throw, never a silent LCV skip."""
		account, _ = self._resolve({}, {"imports_lcv_expense_account": "Ghost - M"})
		self.assertIsNone(account)


if __name__ == "__main__":  # pragma: no cover
	unittest.main()
