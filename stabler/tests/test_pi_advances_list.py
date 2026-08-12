"""`list_pi_advances` — the /imports/advances page's only data source.

Two things can break this endpoint silently, so both get a test that can fail:

1. **The rows must be the same ledger the PI detail page shows.** The list builds
   its ledger from a bulk SQL row (a ``frappe._dict`` of parent fields), while
   ``pi_advance_ledger`` builds it from a full ``frappe.get_doc``. That shortcut is
   only safe while ``_build_proforma_advance_ledger`` reads parent fields exclusively
   — and ``frappe._dict`` returns ``None`` for a missing key instead of raising, so
   the day it starts reading a child table the list would quietly report different
   money. ``test_list_row_matches_the_single_pi_ledger`` is the guard on that
   equivalence; it builds a real PI and a real advance Payment Entry rather than
   scanning whatever the site happens to contain, because a scan finds nothing on an
   empty site and then asserts nothing.

2. **``scope="open"`` must not lose open advances behind the limit.**
   ``advance_available`` is derived, not a column, so the filter runs in Python after
   the query. Applying the SQL ``LIMIT`` to the candidates would drop older PIs that
   still hold credit — exactly the rows the page exists to show.
   ``test_limit_counts_filtered_rows_not_candidates`` reproduces that: five
   candidates, the three newest already consumed, ``limit=2``. A candidate-side limit
   returns zero rows; the correct implementation returns both open ones.

Fixtures are rolled back in ``tearDown``; ``frappe.db.commit()`` is never called.
The two access gates are patched in the fixture test — it is asserting ledger
equivalence, not permissions, and both call paths go through the same two module
functions, so patching cannot mask a divergence between them.
"""

from __future__ import annotations

import re
import unittest
from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.utils import today

from stabler.api.imports import _ADVANCE_SCAN_LIMIT, list_pi_advances, pi_advance_ledger

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


PI_TOTAL = 300_000.0
ADVANCE_PCT = 30.0
ADVANCE_AMOUNT = 90_000.0
#: Declared (customs) unit price on the single fixture line — 100 × 1 000 = 100 000,
#: so docs_total and cash_difference are both non-zero and their equality assertions
#: compare real numbers instead of 0.0 == 0.0.
DOCS_PRICE = 1_000.0
DOCS_TOTAL = 100_000.0


def _account(company: str, currency: str, **filters) -> str | None:
	return frappe.db.get_value(
		"Account",
		dict(company=company, is_group=0, disabled=0, account_currency=currency, **filters),
		"name",
	)


class PiAdvancesListFixtureTest(FrappeTestCase):
	"""Real PI + real advance Payment Entry, then compare list against detail."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		cls.currency = (
			frappe.db.get_value("Company", cls.company, "default_currency") if cls.company else None
		)

	def setUp(self):
		if not (self.company and self.currency):
			self.skipTest("no Company fixture available")
		if not frappe.db.exists("DocType", "Proforma Invoice"):
			self.skipTest("Proforma Invoice doctype not present")
		self.bank = _account(self.company, self.currency, account_type="Bank") or _account(
			self.company, self.currency, account_type="Cash"
		)
		self.payable = _account(self.company, self.currency, account_type="Payable")
		if not (self.bank and self.payable):
			self.skipTest("company has no bank / payable account to post an advance against")
		# docs_total is read-only and derived from the item lines, so the fixture needs
		# a real Item to carry a non-zero declared value. Without one, docs_total and
		# cash_difference would both be 0.0 on both sides and their equality assertions
		# could not fail.
		self.item = frappe.db.get_value("Item", {"disabled": 0}, "name")
		if not self.item:
			self.skipTest("no Item available to build a PI line with a declared value")
		if not frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
			# Without that column a referenceless advance cannot be tied to a PI at all,
			# so the endpoint's EXISTS clause has nothing to match and there is no
			# equivalence left to test on this site.
			self.skipTest("Payment Entry.custom_proforma_invoice is missing on this site")

	def tearDown(self):
		frappe.db.rollback()

	# --- fixtures -----------------------------------------------------------

	def _supplier(self) -> str:
		"""A brand-new supplier, so the only advance in play is the one we create."""
		return (
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": "PiAdvList_" + frappe.generate_hash(length=8),
					"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _proforma_invoice(self, supplier: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Proforma Invoice",
					"company": self.company,
					"supplier": supplier,
					"supplier_pi_ref": "PI-LIST-" + frappe.generate_hash(length=8),
					"pi_date": today(),
					"currency": self.currency,
					"agreed_total": PI_TOTAL,
					"advance_pct": ADVANCE_PCT,
					"status": "CONFIRMED",
					"items": [
						{
							"item": self.item,
							"qty": 100.0,
							"rate": PI_TOTAL / 100.0,
							"docs_price": DOCS_PRICE,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _advance_payment(self, supplier: str, pi: str, amount: float) -> str:
		"""A submitted Pay entry with no references — i.e. a pure advance."""
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Pay"
		pe.company = self.company
		pe.posting_date = today()
		pe.party_type = "Supplier"
		pe.party = supplier
		pe.paid_from = self.bank
		pe.paid_to = self.payable
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.source_exchange_rate = 1.0
		pe.target_exchange_rate = 1.0
		pe.reference_no = "ADV-" + frappe.generate_hash(length=6)
		pe.reference_date = today()
		if frappe.db.has_column("Payment Entry", "custom_proforma_invoice"):
			pe.custom_proforma_invoice = pi
		try:
			pe.insert(ignore_permissions=True)
			pe.submit()
		except Exception as exc:  # accounting defaults vary per site
			self.skipTest(f"advance Payment Entry could not be submitted: {exc}")
		return pe.name

	def _list(self, supplier: str, scope: str) -> list[dict]:
		with (
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_cost_visible"),
		):
			return list_pi_advances(self.company, scope=scope, supplier=supplier)

	def _ledger(self, pi: str) -> dict:
		with (
			patch("stabler.api.imports._assert_imports_access"),
			patch("stabler.api.imports._assert_cost_visible"),
		):
			return pi_advance_ledger(pi)

	# --- tests --------------------------------------------------------------

	def test_list_row_matches_the_single_pi_ledger(self):
		"""The list's bulk-SQL shortcut must produce byte-identical money."""
		supplier = self._supplier()
		pi = self._proforma_invoice(supplier)
		self._advance_payment(supplier, pi, ADVANCE_AMOUNT)

		rows = self._list(supplier, "all")
		self.assertEqual(
			[r["proforma_invoice"] for r in rows],
			[pi],
			"the PI carrying the advance must be the only row for its own supplier",
		)

		single = self._ledger(pi)
		# Guard the fixture itself: if the line stopped producing a declared value the
		# two assertions below would degrade to 0.0 == 0.0 and stop proving anything.
		self.assertEqual(single["docs_total"], DOCS_TOTAL)
		self.assertEqual(single["cash_difference"], PI_TOTAL - DOCS_TOTAL)

		self.assertEqual(rows[0]["summary"], single["summary"])
		self.assertEqual(rows[0]["rows"], single["rows"])
		self.assertEqual(rows[0]["currency"], single["currency"])
		self.assertEqual(rows[0]["docs_total"], single["docs_total"])
		self.assertEqual(rows[0]["cash_difference"], single["cash_difference"])
		self.assertEqual(rows[0]["supplier_pi_ref"], single["supplier_pi_ref"])

	def test_list_columns_come_from_the_pi(self):
		"""The four list-only columns are what the table renders; they are not derived."""
		supplier = self._supplier()
		pi = self._proforma_invoice(supplier)
		self._advance_payment(supplier, pi, ADVANCE_AMOUNT)

		row = self._list(supplier, "all")[0]
		self.assertEqual(row["supplier"], supplier)
		self.assertEqual(row["supplier_name"], frappe.db.get_value("Supplier", supplier, "supplier_name"))
		self.assertEqual(row["pi_date"], today())
		self.assertEqual(row["status"], "CONFIRMED")

	def test_an_unpaid_pi_is_not_listed_at_all(self):
		"""No advance Payment Entry, no row — in either scope."""
		supplier = self._supplier()
		self._proforma_invoice(supplier)

		self.assertEqual(self._list(supplier, "all"), [])
		self.assertEqual(self._list(supplier, "open"), [])

	def test_a_paid_advance_is_open(self):
		"""An unconsumed advance keeps its PI on the page — that is the whole feature."""
		supplier = self._supplier()
		pi = self._proforma_invoice(supplier)
		self._advance_payment(supplier, pi, ADVANCE_AMOUNT)

		rows = self._list(supplier, "open")
		self.assertEqual([r["proforma_invoice"] for r in rows], [pi])
		self.assertGreater(rows[0]["summary"]["advance_available"], 0)


class PiAdvancesScopeTest(unittest.TestCase):
	"""The scope/limit contract, driven by stubbed ledgers so the numbers are exact."""

	# name -> (advance_available, advance_pending_approval)
	LEDGERS: ClassVar[dict[str, tuple[float, float]]] = {
		"PI-1": (0, 0),  # consumed  — must drop off
		"PI-2": (0, 100),  # draft payment pending — still open
		"PI-3": (100, 0),  # credit left — open
	}

	def _run(self, scope: str, ledgers: dict, limit: int = 200) -> tuple[list[dict], dict]:
		"""Call the endpoint with every DB touch stubbed; return rows + the SQL filters."""
		rows, captured, _query, _gates = self._run_full(scope, ledgers, limit)
		return rows, captured

	def _run_full(self, scope: str, ledgers: dict, limit: int = 200) -> tuple[list[dict], dict, str, tuple]:
		"""As ``_run``, but also hands back the query text and the patched gates."""
		captured: dict = {}
		seen_query: list[str] = []

		def fake_sql(query, filters=None, as_dict=False):
			captured.update(filters or {})
			seen_query.append(query)
			# Honour the query's own LIMIT the way the database would — otherwise a
			# candidate-side limit (the P1 bug) would still hand every row back and
			# test_limit_counts_filtered_rows_not_candidates could never fail.
			match = re.search(r"LIMIT\s+%\((\w+)\)s", query)
			self.assertIsNotNone(match, "the candidate query must carry a bound LIMIT")
			cut = filters[match.group(1)]
			names = list(ledgers)[:cut]
			return [frappe._dict({"name": name, "supplier": "S1"}) for name in names]

		def fake_build(doc, advances):
			available, pending = ledgers[doc.name]
			return {
				"proforma_invoice": doc.name,
				"summary": {"advance_available": available, "advance_pending_approval": pending},
				"rows": [],
			}

		with (
			patch("stabler.api.imports._assert_imports_access") as imports_gate,
			patch("stabler.api.imports._assert_cost_visible") as cost_gate,
			patch("stabler.api.imports._po_advance_payment_entries", return_value=([], 0, 0)),
			patch("stabler.api.imports._build_proforma_advance_ledger", side_effect=fake_build),
			patch("frappe.db.has_column", return_value=True),
			patch("frappe.db.sql", side_effect=fake_sql),
		):
			rows = list_pi_advances("Test Company", scope=scope, limit=limit)
		return rows, captured, seen_query[0], (imports_gate, cost_gate)

	def test_scope_all_keeps_every_candidate(self):
		rows, _ = self._run("all", self.LEDGERS)
		self.assertEqual([r["proforma_invoice"] for r in rows], ["PI-1", "PI-2", "PI-3"])

	def test_scope_open_drops_the_consumed_pi_only(self):
		rows, _ = self._run("open", self.LEDGERS)
		names = [r["proforma_invoice"] for r in rows]
		self.assertNotIn("PI-1", names, "a fully consumed advance must leave the page")
		self.assertEqual(names, ["PI-2", "PI-3"], "pending approval counts as open credit")

	def test_limit_counts_filtered_rows_not_candidates(self):
		"""The P1 regression: an open advance behind newer consumed ones stays visible."""
		ledgers = {
			"PI-new-1": (0, 0),
			"PI-new-2": (0, 0),
			"PI-new-3": (0, 0),
			"PI-old-1": (500, 0),
			"PI-old-2": (0, 250),
		}
		rows, _ = self._run("open", ledgers, limit=2)
		self.assertEqual(
			[r["proforma_invoice"] for r in rows],
			["PI-old-1", "PI-old-2"],
			"limit must cut the open rows, not the candidates it scanned to find them",
		)

	def test_scan_bound_depends_on_scope(self):
		"""scope='all' needs no post-filter, so its SQL limit is exact; 'open' scans wide."""
		_, all_filters = self._run("all", self.LEDGERS, limit=25)
		self.assertEqual(all_filters["scan"], 25)

		_, open_filters = self._run("open", self.LEDGERS, limit=25)
		self.assertEqual(open_filters["scan"], _ADVANCE_SCAN_LIMIT)
		self.assertGreater(_ADVANCE_SCAN_LIMIT, 25)

	def test_limit_is_never_zero_or_negative(self):
		rows, filters = self._run("all", self.LEDGERS, limit=0)
		self.assertEqual(filters["scan"], 1)
		self.assertEqual(len(rows), 1)

	def test_both_permission_gates_run_before_any_query(self):
		"""Deleting either gate must break a test — this endpoint returns supplier costs.

		``_assert_imports_access`` is the module/company gate and ``_assert_cost_visible``
		the cost-visibility gate; without this, both could be removed and every other
		test here would still pass, because they patch the gates for convenience.
		"""
		_, _, _, (imports_gate, cost_gate) = self._run_full("open", self.LEDGERS)
		imports_gate.assert_called_once_with("Test Company")
		cost_gate.assert_called_once_with()

	def test_query_is_scoped_to_the_requested_company(self):
		"""Tenant isolation is in the SQL, not in the caller — both sides must carry it."""
		_, filters, query, _ = self._run_full("open", self.LEDGERS)
		self.assertEqual(filters["company"], "Test Company")
		self.assertIn("pi.company = %(company)s", query)
		self.assertIn(
			"pe.company = %(company)s",
			query,
			"the candidate EXISTS must match the same company as the ledger fetch",
		)
