"""Remittance Settings is the record that decides which drawer the cash lands in.

Two things must hold, and neither is enforced by the database:

1. A desk may hold exactly one account per currency. Frappe's `unique` flag is a
   single-column index and does nothing on a child table, so if the parent's
   validate() ever stops checking the pair, a desk silently gets two USD accounts
   and its book balance stops matching the physical count in the drawer.
2. A missing mapping must BLOCK, never fall back. Registering against some other
   account is worse than refusing: the money moves, the books look fine, and the
   mismatch surfaces only when somebody reconciles by hand.

Bench-free on purpose — the bench set is not part of `make check`, so a test that
needs one would not gate a push.
"""

from __future__ import annotations

import importlib
import json
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONTROLLER = "stabler.stabler.doctype.remittance_settings.remittance_settings"

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _load_doctype(name: str) -> dict:
	path = os.path.join(_PKG, "stabler", "doctype", name, f"{name}.json")
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


class _Row(dict):
	def __getattr__(self, field):
		return self.get(field)


def _load_controller(existing_settings=None):
	"""Import the controller against a fake frappe.

	`existing_settings` is the doc `get_settings` should find, or None to model a
	company that was never configured.
	"""
	_SANDBOX.evict(_CONTROLLER, "frappe", "frappe.model", "frappe.model.document")

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.db = types.SimpleNamespace(exists=lambda _dt, name: existing_settings is not None)
	frappe.get_doc = lambda _dt, _name: existing_settings

	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")

	class Document:
		pass

	document.Document = Document
	model.document = document
	frappe.model = model

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.model": model,
			"frappe.model.document": document,
		}
	)
	return importlib.import_module(_CONTROLLER)


class SettingsShape(unittest.TestCase):
	"""The JSON is the schema — assert the parts other code will depend on."""

	def setUp(self):
		self.dt = _load_doctype("remittance_settings")
		self.fields = {f["fieldname"]: f for f in self.dt["fields"]}

	def test_field_order_and_fields_agree(self):
		self.assertEqual(set(self.dt["field_order"]), set(self.fields))

	def test_one_row_per_company_without_a_validate_check(self):
		# Named after the company AND unique: a second row collides on the primary
		# key, so the constraint lives in the database, not in Python.
		self.assertEqual(self.dt["autoname"], "field:company")
		self.assertEqual(self.fields["company"]["unique"], 1)
		self.assertEqual(self.fields["company"]["reqd"], 1)

	def test_three_company_accounts_all_required(self):
		# ADR-009 cut five accounts to three by removing the FX margin pair. A
		# missing one must stop configuration, not surface at posting time.
		for fieldname in (
			"receiver_obligation_account",
			"deferred_commission_account",
			"commission_income_account",
		):
			field = self.fields[fieldname]
			self.assertEqual(field["fieldtype"], "Link", fieldname)
			self.assertEqual(field["options"], "Account", fieldname)
			self.assertEqual(field.get("reqd"), 1, fieldname)

	def test_no_fx_margin_account_survived(self):
		self.assertFalse([f for f in self.fields if "margin" in f or "fx" in f])

	def test_policy_defaults(self):
		self.assertEqual(self.fields["default_quote_expiry_hours"]["default"], "72")
		self.assertEqual(self.fields["max_code_attempts"]["default"], "5")
		self.assertEqual(self.fields["require_refund_approval"]["default"], "1")

	def test_cash_desk_table_points_at_the_child(self):
		field = self.fields["cash_desk_accounts"]
		self.assertEqual(field["fieldtype"], "Table")
		self.assertEqual(field["options"], "Remittance Cash Desk Account")


class CashDeskAccountShape(unittest.TestCase):
	def setUp(self):
		self.dt = _load_doctype("remittance_cash_desk_account")
		self.fields = {f["fieldname"]: f for f in self.dt["fields"]}

	def test_is_a_child_table(self):
		self.assertEqual(self.dt["istable"], 1)
		self.assertEqual(self.dt["permissions"], [])

	def test_a_row_identifies_a_drawer(self):
		# desk + currency + account is the whole point; any of the three missing
		# makes the row unusable for resolving where cash goes.
		self.assertEqual(self.fields["branch"]["options"], "Branch")
		self.assertEqual(self.fields["currency"]["options"], "Currency")
		self.assertEqual(self.fields["account"]["options"], "Account")
		for fieldname in ("branch", "currency", "account", "evidence_type"):
			self.assertEqual(self.fields[fieldname].get("reqd"), 1, fieldname)

	def test_usdt_is_an_ordinary_desk_currency(self):
		# Zafar's decision: USDT is not an integration, it is a drawer. The only
		# difference is what "counting" it means, so that is a per-row label and
		# not a branch anywhere in the code.
		self.assertEqual(
			self.fields["evidence_type"]["options"].split("\n"),
			["Counted", "Wallet balance"],
		)


class DeskCurrencyUniqueness(unittest.TestCase):
	def test_a_desk_may_not_hold_two_accounts_for_one_currency(self):
		api = _load_controller()
		settings = api.RemittanceSettings()
		settings.cash_desk_accounts = [
			_Row(branch="TAS-C", currency="USD", account="Cash USD TAS - S"),
			_Row(branch="TAS-C", currency="USD", account="Cash USD Other - S"),
		]
		with self.assertRaises(_Thrown):
			settings.validate()

	def test_the_same_desk_may_hold_one_account_per_currency(self):
		api = _load_controller()
		settings = api.RemittanceSettings()
		settings.cash_desk_accounts = [
			_Row(branch="TAS-C", currency="USD", account="Cash USD TAS - S"),
			_Row(branch="TAS-C", currency="UZS", account="Cash UZS TAS - S"),
			_Row(branch="BUX-1", currency="USD", account="Cash USD BUX - S"),
		]
		settings.validate()  # must not throw


class DeskAccountResolution(unittest.TestCase):
	"""A missing mapping blocks. It never falls back to another account."""

	def _configured(self):
		doc = types.SimpleNamespace()
		doc.cash_desk_accounts = [
			_Row(branch="TAS-C", currency="USD", account="Cash USD TAS - S"),
			_Row(branch="TAS-C", currency="UZS", account="Cash UZS TAS - S"),
		]
		return doc

	def test_it_returns_the_account_for_that_desk_and_currency(self):
		api = _load_controller(self._configured())
		self.assertEqual(api.get_desk_account("Mikas", "TAS-C", "UZS"), "Cash UZS TAS - S")

	def test_a_currency_the_desk_does_not_hold_blocks(self):
		api = _load_controller(self._configured())
		with self.assertRaises(_Thrown) as caught:
			api.get_desk_account("Mikas", "TAS-C", "EUR")
		# The message has to name what is missing and where to fix it, or the
		# cashier is left guessing at the counter.
		message = str(caught.exception)
		self.assertIn("TAS-C", message)
		self.assertIn("EUR", message)
		self.assertIn("Remittance Settings", message)

	def test_an_unconfigured_company_blocks(self):
		api = _load_controller(None)
		with self.assertRaises(_Thrown):
			api.get_desk_account("Mikas", "TAS-C", "USD")

	def test_it_never_returns_some_other_desks_account(self):
		api = _load_controller(self._configured())
		with self.assertRaises(_Thrown):
			api.get_desk_account("Mikas", "BUX-1", "USD")


if __name__ == "__main__":
	unittest.main()
