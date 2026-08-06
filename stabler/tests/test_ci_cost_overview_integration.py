"""Integration tests for ``stabler.api.imports.ci_cost_overview``.

Why this file exists: the pure math engine (``_imports_rules.calculate_ci_cost_overview``)
was already well covered by unit tests, yet both blockers of the v46 cycle escaped —
one in ``_related_import_bills`` (a bill raised against a *container* was invisible to
its commercial invoice), one in the customs ``duties_estimated`` flag. Both live in the
endpoint layer: SQL, module gating, cost masking. A pure unit test cannot reach that
layer, so the behaviour is pinned here instead.

Every fixture is created by the test itself on whatever Company / Supplier / Item the
site happens to carry, and rolled back in ``tearDown``: no pre-existing record is
mutated and ``frappe.db.commit()`` is never called. If the fixtures cannot be built the
tests skip with the reason rather than fail, so the suite stays green on a bare site.
"""

from __future__ import annotations

import unittest
from unittest import mock

import frappe

from stabler.api import imports as imports_api

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


def _first_company():
	return frappe.db.get_value("Company", {}, "name")


def _first_supplier():
	return frappe.db.get_value("Supplier", {}, "name")


def _first_item():
	return frappe.db.get_value("Item", {}, "name")


def _gtd_number() -> str:
	"""A unique GTD in the format the doctype enforces: XXXXX/DDMMYY/NNNNNNN."""
	tail = int(frappe.generate_hash(length=8), 16) % 10_000_000
	return f"26010/{frappe.utils.getdate().strftime('%d%m%y')}/{tail:07d}"


class CiCostOverviewIntegrationTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _first_company()
		cls.supplier = _first_supplier()
		cls.item = _first_item()
		cls.currency = (
			frappe.db.get_value("Company", cls.company, "default_currency") if cls.company else None
		)

	def setUp(self):
		if not (self.company and self.supplier and self.item):
			self.skipTest("no Company / Supplier / Item fixtures available")
		for dt in ("Commercial Invoice", "Import Container", "Import Expense", "Stabler Settings"):
			if not frappe.db.exists("DocType", dt):
				self.skipTest(f"{dt} doctype not present")
		self._set_imports_enabled(True)

	def tearDown(self):
		frappe.db.rollback()

	# --- fixtures -----------------------------------------------------------

	def _set_imports_enabled(self, enabled: bool) -> None:
		settings = frappe.get_single("Stabler Settings")
		row = None
		for r in settings.company_modules or []:
			if r.company == self.company:
				row = r
				break
		if row is None:
			row = settings.append("company_modules", {"company": self.company})
		row.enable_imports = 1 if enabled else 0
		settings.save(ignore_permissions=True)

	def _new_ci(self, *, total_kg=0.0, agreed_total=0.0, docs_total=0.0) -> str:
		ci = frappe.get_doc(
			{
				"doctype": "Commercial Invoice",
				"company": self.company,
				"supplier": self.supplier,
				"ci_number": frappe.generate_hash(length=8),
				"ci_date": frappe.utils.today(),
				"currency": self.currency,
				"total_kg": total_kg,
				"agreed_total": agreed_total,
				"docs_total": docs_total,
			}
		).insert(ignore_permissions=True)
		return ci.name

	def _new_container(self, ci: str, *, total_kg: float) -> str:
		cnt = frappe.get_doc(
			{
				"doctype": "Import Container",
				"company": self.company,
				"commercial_invoice": ci,
				"container_number": frappe.generate_hash(length=8),
				"total_kg": total_kg,
				"total_boxes": 100,
				"status": "IN_TRANSIT",
			}
		).insert(ignore_permissions=True)
		return cnt.name

	def _new_bill(
		self,
		*,
		grand_total: float,
		ci: str | None = None,
		container: str | None = None,
		bill_no: str | None = None,
	) -> str:
		"""A draft Purchase Invoice. ``docstatus < 2`` is all the endpoint asks for."""
		payload = {
			"doctype": "Purchase Invoice",
			"company": self.company,
			"supplier": self.supplier,
			"posting_date": frappe.utils.today(),
			"due_date": frappe.utils.today(),
			"currency": self.currency,
			"conversion_rate": 1.0,
			"bill_no": bill_no,
			"items": [{"item_code": self.item, "qty": 1, "rate": grand_total}],
		}
		if ci:
			payload["custom_commercial_invoice"] = ci
		if container:
			payload["custom_import_container"] = container
		try:
			return frappe.get_doc(payload).insert(ignore_permissions=True).name
		except Exception as exc:  # accounting defaults vary per site
			self.skipTest(f"Purchase Invoice fixture could not be built: {exc}")

	def _new_expense(
		self,
		ci: str,
		*,
		amount: float,
		category: str = "Transport",
		bank_payment: float = 0.0,
		cash_payment: float = 0.0,
		container: str | None = None,
		purchase_invoice: str | None = None,
	) -> str:
		exp = frappe.get_doc(
			{
				"doctype": "Import Expense",
				"company": self.company,
				"commercial_invoice": ci,
				"container": container,
				"category": category,
				"expense_date": frappe.utils.today(),
				"supplier": self.supplier,
				"amount": amount,
				"bank_payment": bank_payment,
				"cash_payment": cash_payment,
				"purchase_invoice": purchase_invoice,
			}
		).insert(ignore_permissions=True)
		return exp.name

	def _new_declaration(self, ci: str, *, duty_amount: float, cleared_date=None) -> str:
		"""``total_duties`` is derived by the doctype from duty + VAT + excise."""
		decl = frappe.get_doc(
			{
				"doctype": "Customs Declaration",
				"company": self.company,
				"commercial_invoice": ci,
				"gtd_number": _gtd_number(),
				"declaration_date": frappe.utils.today(),
				"cleared_date": cleared_date,
				"duty_amount": duty_amount,
				"status": "Draft",
			}
		).insert(ignore_permissions=True)
		return decl.name

	def _container_linked_scenario(self):
		"""CI whose only bill is raised against its container, not against the CI."""
		ci = self._new_ci(total_kg=3750.0)
		cnt = self._new_container(ci, total_kg=3750.0)
		bill = self._new_bill(grand_total=850.0, container=cnt)
		self._new_expense(ci, amount=850.0, bank_payment=600.0, container=cnt, purchase_invoice=bill)
		return ci, cnt, bill

	# --- tests --------------------------------------------------------------

	def test_ci_with_expense_and_bill(self):
		"""Full shape plus the reconciliation identity transport == billed + unbilled.

		The identity is the number an importer actually reads: every transport expense
		is either covered by a supplier bill or still unbilled. A drift here means
		money is double counted or lost, so it is asserted exactly (the engine only
		emits ``reconciliation_diff`` when the identity breaks).
		"""
		ci = self._new_ci(total_kg=5000.0, agreed_total=40000.0, docs_total=40000.0)
		self._new_container(ci, total_kg=2500.0)
		self._new_container(ci, total_kg=2500.0)
		goods_bill = self._new_bill(grand_total=40000.0, ci=ci)
		# XBORDER- prefix => derive_bill_category() classifies it as transport, so it
		# does not leak into accounting.billed_goods.
		transport_bill = self._new_bill(
			grand_total=1500.0, ci=ci, bill_no="XBORDER-" + frappe.generate_hash(length=6)
		)
		self._new_expense(ci, amount=1500.0, bank_payment=800.0, purchase_invoice=transport_bill)

		res = imports_api.ci_cost_overview(ci)

		self.assertEqual(
			set(res),
			{
				"expenses",
				"bills",
				"unbilled",
				"by_vendor",
				"by_container",
				"operational",
				"accounting",
				"gap",
				"totals",
				"currency",
			},
		)
		self.assertEqual({b["name"] for b in res["bills"]}, {goods_bill, transport_bill})

		totals = res["totals"]
		self.assertEqual(totals["containers"], 2)
		self.assertEqual(totals["cargo_kg"], 5000.0)
		self.assertEqual(totals["transport"], 1500.0)
		self.assertEqual(totals["billed"], 1500.0)
		self.assertEqual(totals["unbilled"], 0.0)
		self.assertNotIn("reconciliation_diff", totals)
		self.assertEqual(totals["paid"], 800.0)
		self.assertEqual(totals["outstanding"], 700.0)

		# Only the product bill counts as goods; the transport bill must not.
		self.assertEqual(res["accounting"]["billed_goods"], 40000.0)
		self.assertGreater(res["operational"]["per_kg"], 0)
		# No container on the expense => weight allocation spreads it over both.
		self.assertEqual(len(res["by_container"]), 2)
		for row in res["by_container"]:
			self.assertGreater(row["per_kg"], 0)

	def test_ci_with_container_linked_bill(self):
		"""A bill raised against a container belongs to that container's CI.

		Escaped blocker #1: ``_related_import_bills`` used to take a single container,
		so a CI carrying several containers saw none of their bills — the cost picture
		silently under-reported. This is the only reason the parameter is a list.
		"""
		ci, _cnt, bill = self._container_linked_scenario()

		res = imports_api.ci_cost_overview(ci)

		self.assertEqual([b["name"] for b in res["bills"]], [bill])
		self.assertEqual(res["totals"]["billed"], 850.0)
		self.assertEqual(res["totals"]["unbilled"], 0.0)
		self.assertEqual(res["totals"]["transport"], 850.0)
		self.assertNotIn("reconciliation_diff", res["totals"])

	def test_ci_without_expenses(self):
		"""An untouched CI returns empty collections and zeros, never an error."""
		ci = self._new_ci()

		res = imports_api.ci_cost_overview(ci)

		self.assertEqual(res["expenses"], [])
		self.assertEqual(res["bills"], [])
		self.assertEqual(res["unbilled"], [])
		self.assertEqual(res["by_vendor"], [])
		self.assertEqual(res["totals"]["transport"], 0.0)
		self.assertEqual(res["totals"]["containers"], 0)
		self.assertEqual(res["gap"]["amount"], 0.0)

	def test_container_cost_ledger_regression(self):
		"""The list-taking ``containers=`` signature must not break the ledger.

		``container_cost_ledger`` shares ``_related_import_bills`` with the overview;
		when that signature changed, this caller was the one that could have silently
		stopped finding its own bill.
		"""
		_ci, cnt, bill = self._container_linked_scenario()

		led = imports_api.container_cost_ledger(container=cnt)

		self.assertEqual(
			set(led),
			{"advances", "bills", "cost_lines", "cost_visible", "header", "landed_cost_vouchers", "summary"},
		)
		self.assertIn(bill, [b["name"] for b in led["bills"]])

	def test_masked_financials_are_none(self):
		"""Without cost permission every money field is ``None``, never ``0``.

		``0`` would read as "this shipment cost nothing" — a wrong number is worse
		than a withheld one. Structure (container count, cargo weight, flags) stays
		visible so the page still renders.
		"""
		ci, _cnt, _bill = self._container_linked_scenario()

		with mock.patch.object(imports_api, "_cost_visible", return_value=False):
			res = imports_api.ci_cost_overview(ci)

		self.assertIsNone(res["totals"]["transport"])
		self.assertIsNone(res["totals"]["billed"])
		self.assertIsNone(res["operational"]["total"])
		self.assertIsNone(res["accounting"]["total"])
		self.assertIsNone(res["gap"]["amount"])
		self.assertIsNone(res["expenses"][0]["amount"])
		self.assertIsNone(res["expenses"][0]["bank_payment"])
		self.assertIsNone(res["bills"][0]["grand_total"])
		self.assertIsNone(res["bills"][0]["outstanding_amount"])
		# Shape survives masking.
		self.assertEqual(res["totals"]["containers"], 1)
		self.assertEqual(res["totals"]["cargo_kg"], 3750.0)
		self.assertIsInstance(res["operational"]["duties_estimated"], bool)

	def test_duties_estimated_flag(self):
		"""Duties are an estimate until customs actually cleared the declaration.

		Escaped blocker #2: the endpoint used to read a ``released`` field that does
		not exist on Customs Declaration. The real signal is ``cleared_date``, and the
		flag drives whether the UI may present the landed cost as final.
		"""
		ci = self._new_ci(total_kg=1000.0)

		# No declaration at all — nothing has been declared, so nothing is final.
		self.assertTrue(imports_api.ci_cost_overview(ci)["operational"]["duties_estimated"])

		decl = self._new_declaration(ci, duty_amount=1200.0)
		res = imports_api.ci_cost_overview(ci)
		self.assertTrue(res["operational"]["duties_estimated"])
		self.assertEqual(res["operational"]["duties"], 1200.0)

		frappe.db.set_value("Customs Declaration", decl, "cleared_date", frappe.utils.today())
		res = imports_api.ci_cost_overview(ci)
		self.assertFalse(res["operational"]["duties_estimated"])
		self.assertEqual(res["operational"]["duties"], 1200.0)


if __name__ == "__main__":
	unittest.main()
