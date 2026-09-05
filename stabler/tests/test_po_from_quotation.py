"""Unit and contract tests for create_po_from_quotation (Phase B3).

Verifies that create_po_from_quotation:
- enforces company scope and reject foreign company
- validates that Supplier Quotation exists and is tagged to a CRM Deal lot
- refuses any quotation the lot's approved Tender Sourcing Decision did not select
- returns existing draft PO when one already exists for the lot + supplier (idempotency)
- creates a new draft Purchase Order copying supplier, currency, items, and crm_deal link
- rejects cancelled quotations or quotations with no items
"""

from __future__ import annotations

import importlib
import types
import unittest
from pathlib import Path

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


class _Doc(dict):
	def __getattr__(self, field):
		if field == "flags":
			return self.setdefault("_flags", types.SimpleNamespace())
		return self.get(field)

	def __setattr__(self, field, value):
		self[field] = value

	def as_dict(self):
		return dict(self)

	def append(self, field, row):
		self.setdefault(field, []).append(dict(row))
		return row

	def insert(self, **_kwargs):
		self["inserted"] = True
		self["name"] = self.get("name") or f"PO-{id(self)}"
		if hasattr(self, "_fake") and self._fake:
			self._fake.docs[("Purchase Order", self["name"])] = self
		return self

	def set_missing_values(self):
		pass

	def calculate_taxes_and_totals(self):
		pass


class _FakeDB:
	def __init__(self):
		self.docs = {
			("Company", "ACME"): _Doc(name="ACME", default_currency="USD"),
			("Company", "Other"): _Doc(name="Other", default_currency="EUR"),
			("Warehouse", "Stores - ACME"): _Doc(name="Stores - ACME", company="ACME", is_group=0),
			("Supplier Quotation", "SQ-VALID"): _Doc(
				name="SQ-VALID",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal="LOT-1",
				valid_till="2026-09-01",
				docstatus=0,
				items=[
					_Doc(
						item_code="RAIL-01",
						item_name="Steel Rail",
						qty=5.0,
						uom="Nos",
						rate=100.0,
						amount=500.0,
					)
				],
			),
			# Its own lot, and the award names it — otherwise "no lines" would be
			# reported by the award gate and this fixture would stop testing the
			# empty-quotation guard at all.
			("Supplier Quotation", "SQ-NO-ITEMS"): _Doc(
				name="SQ-NO-ITEMS",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal="LOT-NO-ITEMS",
				docstatus=0,
				items=[],
			),
			("Supplier Quotation", "SQ-NO-DEAL"): _Doc(
				name="SQ-NO-DEAL",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal=None,
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			("Supplier Quotation", "SQ-CANCELLED"): _Doc(
				name="SQ-CANCELLED",
				company="ACME",
				supplier="SUP-ALFA",
				currency="USD",
				custom_crm_deal="LOT-1",
				docstatus=2,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			("Supplier Quotation", "SQ-OTHER-CO"): _Doc(
				name="SQ-OTHER-CO",
				company="Other",
				supplier="SUP-OTHER",
				currency="EUR",
				custom_crm_deal="LOT-OTHER",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			("Purchase Order", "PO-EXISTING"): _Doc(
				name="PO-EXISTING",
				company="ACME",
				supplier="SUP-BETA",
				custom_crm_deal="LOT-EXISTING",
				docstatus=0,
			),
			("Supplier Quotation", "SQ-EXISTING-LOT"): _Doc(
				name="SQ-EXISTING-LOT",
				company="ACME",
				supplier="SUP-BETA",
				currency="USD",
				custom_crm_deal="LOT-EXISTING",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=50.0)],
			),
			# Same lot and same supplier as SQ-EXISTING-LOT, but the losing bid:
			# it must not ride the idempotent early return into somebody else's PO.
			("Supplier Quotation", "SQ-EXISTING-LOT-LOSER"): _Doc(
				name="SQ-EXISTING-LOT-LOSER",
				company="ACME",
				supplier="SUP-BETA",
				currency="USD",
				custom_crm_deal="LOT-EXISTING",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=1.0, rate=90.0)],
			),
			# The losing bid on LOT-1 — the award named SQ-VALID, not this one.
			("Supplier Quotation", "SQ-LOSER"): _Doc(
				name="SQ-LOSER",
				company="ACME",
				supplier="SUP-BETA",
				currency="USD",
				custom_crm_deal="LOT-1",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=5.0, rate=140.0)],
			),
			# A lot whose award is still a draft: written, not yet approved.
			("Supplier Quotation", "SQ-DRAFT-AWARD"): _Doc(
				name="SQ-DRAFT-AWARD",
				company="ACME",
				supplier="SUP-GAMMA",
				currency="USD",
				custom_crm_deal="LOT-DRAFT",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=2.0, rate=60.0)],
			),
			# A lot nobody has decided on at all.
			("Supplier Quotation", "SQ-NO-DECISION"): _Doc(
				name="SQ-NO-DECISION",
				company="ACME",
				supplier="SUP-GAMMA",
				currency="USD",
				custom_crm_deal="LOT-UNDECIDED",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=2.0, rate=60.0)],
			),
			# A lot awarded twice: the first winner fell through, the lot was
			# re-awarded to somebody else.
			("Supplier Quotation", "SQ-OLD-WINNER"): _Doc(
				name="SQ-OLD-WINNER",
				company="ACME",
				supplier="SUP-DELTA",
				currency="USD",
				custom_crm_deal="LOT-REAWARD",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=3.0, rate=70.0)],
			),
			("Supplier Quotation", "SQ-NEW-WINNER"): _Doc(
				name="SQ-NEW-WINNER",
				company="ACME",
				supplier="SUP-EPSILON",
				currency="USD",
				custom_crm_deal="LOT-REAWARD",
				docstatus=0,
				items=[_Doc(item_code="RAIL-01", qty=3.0, rate=75.0)],
			),
			("Tender Sourcing Decision", "TSD-LOT-1"): _Doc(
				name="TSD-LOT-1",
				company="ACME",
				deal="LOT-1",
				status="Approved",
				selected_quotation="SQ-VALID",
				approved_by="director@acme.example",
				approved_at="2026-08-10 09:00:00",
			),
			("Tender Sourcing Decision", "TSD-LOT-EXISTING"): _Doc(
				name="TSD-LOT-EXISTING",
				company="ACME",
				deal="LOT-EXISTING",
				status="Approved",
				selected_quotation="SQ-EXISTING-LOT",
				approved_by="director@acme.example",
				approved_at="2026-08-10 09:00:00",
			),
			("Tender Sourcing Decision", "TSD-LOT-NO-ITEMS"): _Doc(
				name="TSD-LOT-NO-ITEMS",
				company="ACME",
				deal="LOT-NO-ITEMS",
				status="Approved",
				selected_quotation="SQ-NO-ITEMS",
				approved_by="director@acme.example",
				approved_at="2026-08-10 09:00:00",
			),
			("Tender Sourcing Decision", "TSD-LOT-DRAFT"): _Doc(
				name="TSD-LOT-DRAFT",
				company="ACME",
				deal="LOT-DRAFT",
				status="Draft",
				selected_quotation="SQ-DRAFT-AWARD",
			),
			("Tender Sourcing Decision", "TSD-REAWARD-OLD"): _Doc(
				name="TSD-REAWARD-OLD",
				company="ACME",
				deal="LOT-REAWARD",
				status="Approved",
				selected_quotation="SQ-OLD-WINNER",
				approved_by="director@acme.example",
				approved_at="2026-08-10 09:00:00",
			),
			("Tender Sourcing Decision", "TSD-REAWARD-NEW"): _Doc(
				name="TSD-REAWARD-NEW",
				company="ACME",
				deal="LOT-REAWARD",
				status="Approved",
				selected_quotation="SQ-NEW-WINNER",
				approved_by="director@acme.example",
				approved_at="2026-08-12 15:30:00",
			),
		}
		# A site that has not migrated yet has no decision table at all. Modelled
		# because `has_column` RAISES on a missing table instead of answering
		# False, so the guard has to probe the table first.
		self.tables_present = {doctype for (doctype, _name) in self.docs}
		self.created: list[_Doc] = []

	def exists(self, doctype, name):
		if doctype == "Company":
			return name in {"ACME", "Other"}
		return (doctype, name) in self.docs

	def get_value(self, doctype, name, fieldname):
		doc = self.docs.get((doctype, name))
		if not doc:
			return None
		return doc.get(fieldname)

	def table_exists(self, doctype):
		return doctype in self.tables_present

	def has_column(self, doctype, column):
		# The real one raises TableMissingError rather than answering False when
		# the doctype has no table — see .claude/rules/20-backend-migrations.md.
		if doctype not in self.tables_present:
			raise RuntimeError(f"TableMissingError: tab{doctype}")
		return True


def _load_purchasing(db: _FakeDB):
	_SANDBOX.evict(
		"stabler.api.purchasing",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.approvals",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.PermissionError = PermissionError
	frappe.DoesNotExistError = KeyError
	frappe.ValidationError = ValueError
	frappe.session = types.SimpleNamespace(user="buyer@acme.example")
	frappe.flags = types.SimpleNamespace()
	frappe.db = db
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if not args else args[0]
	frappe.get_roles = lambda _user=None: ["Purchase User"]
	frappe.has_permission = lambda doctype, ptype="read", doc=None: True
	frappe.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
	frappe.get_doc = lambda doctype, name: db.docs[(doctype, name)]
	frappe.new_doc = lambda doctype: _new_doc(db, doctype)
	frappe.get_list = lambda doctype, **kwargs: _get_list(db, doctype, **kwargs)
	frappe.get_all = lambda doctype, **kwargs: _get_list(db, doctype, **kwargs)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value: float(value or 0)
	utils.cint = lambda value: int(value or 0)
	utils.getdate = lambda value: str(value)[:10]
	utils.today = lambda: "2026-08-14"
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_args, **_kwargs: None
	common._assert_can_write = lambda *_args, **_kwargs: None
	common._require_company = lambda company: company or "ACME"
	common._company_default_warehouse = lambda company: "Stores - ACME"
	common.check_concurrency = lambda *_args, **_kwargs: None

	approvals = types.ModuleType("stabler.api.approvals")
	# The real helper (`stabler/api/approvals.py`) only ASSERTS and returns None.
	# Until 2026-09-05 this stub returned the company, which hid an endpoint that
	# read the selected company from it: in production every quotation compared
	# against None and was refused as "from another company".
	approvals._assert_company_scope = lambda company: None

	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings.module_map_for = lambda c: {"tender": True, "purchasing": True}
	settings.imports_supplier_groups_for = lambda c: []

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": settings,
		}
	)
	return importlib.import_module("stabler.api.purchasing")


def _new_doc(db: _FakeDB, doctype: str):
	doc = _Doc(doctype=doctype, _fake=db, docstatus=0)
	db.created.append(doc)
	return doc


def _get_list(db: _FakeDB, doctype: str, **kwargs):
	# Querying a doctype whose table was never created is an error in the real
	# framework, not an empty result — so a guard that skips the table probe
	# blows up here instead of quietly reporting "no award".
	if doctype not in db.tables_present:
		raise RuntimeError(f"TableMissingError: tab{doctype}")
	filters = kwargs.get("filters", {})
	res = []
	for (dt, _name), doc in db.docs.items():
		if dt != doctype:
			continue
		match = True
		for k, v in filters.items():
			if k == "docstatus" and isinstance(v, list) and v[0] == "<":
				if doc.get("docstatus", 0) >= v[1]:
					match = False
					break
			elif doc.get(k) != v:
				match = False
				break
		if match:
			res.append(doc)
	# Only enough of `order_by` to model "newest award first"; a fake that ignored
	# it would let a re-awarded lot pass on whichever row the dict happened to
	# yield first, which is the bug the re-award test exists to catch.
	order_by = kwargs.get("order_by") or ""
	if order_by:
		field, _, direction = order_by.split(",")[0].strip().partition(" ")
		res.sort(key=lambda d: str(d.get(field) or ""), reverse=direction.strip().lower() == "desc")
	limit = kwargs.get("limit_page_length")
	if limit:
		res = res[: int(limit)]
	return res


class TestCreatePoFromQuotation(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.purchasing = _load_purchasing(self.db)

	def test_creates_draft_po_with_copied_lines_and_deal_link(self):
		res = self.purchasing.create_po_from_quotation("SQ-VALID", company="ACME")
		self.assertFalse(res["existing"])
		self.assertTrue(res["name"])

		po = self.db.docs[("Purchase Order", res["name"])]
		self.assertEqual(po["company"], "ACME")
		self.assertEqual(po["supplier"], "SUP-ALFA")
		self.assertEqual(po["currency"], "USD")
		self.assertEqual(po["custom_crm_deal"], "LOT-1")
		self.assertEqual(po["docstatus"], 0)
		self.assertEqual(len(po.get("items", [])), 1)
		self.assertEqual(po["items"][0]["item_code"], "RAIL-01")
		self.assertEqual(po["items"][0]["qty"], 5.0)
		self.assertEqual(po["items"][0]["rate"], 100.0)

	def test_returns_existing_po_if_one_already_exists_for_lot_and_supplier(self):
		res = self.purchasing.create_po_from_quotation("SQ-EXISTING-LOT", company="ACME")
		self.assertTrue(res["existing"])
		self.assertEqual(res["name"], "PO-EXISTING")

	def test_rejects_foreign_company(self):
		with self.assertRaises(PermissionError):
			self.purchasing.create_po_from_quotation("SQ-OTHER-CO", company="ACME")

	def test_company_comes_from_require_company_not_from_the_scope_assertion(self):
		"""`_assert_company_scope` is an assertion: by contract it returns None
		(`stabler/api/approvals.py`). The endpoint once read the selected company
		from its return value, so `sq.company != None` held for every quotation
		and the awarded bid was refused with "Quotation does not belong to the
		selected company." — measured 2026-09-05 on the Mikas walk, hidden here
		by a stub that returned the company. The assertion must still run, and
		it must see the resolved company, not the raw argument."""
		seen: list = []
		self.purchasing._assert_company_scope = lambda company: seen.append(company)
		res = self.purchasing.create_po_from_quotation("SQ-VALID", company="ACME")
		self.assertEqual(seen, ["ACME"])
		self.assertEqual(self.db.docs[("Purchase Order", res["name"])]["company"], "ACME")

	def test_rejects_cancelled_quotation(self):
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-CANCELLED", company="ACME")

	def test_rejects_quotation_without_crm_deal(self):
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-NO-DEAL", company="ACME")

	def test_rejects_quotation_with_no_lines(self):
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-NO-ITEMS", company="ACME")


class TestOnlyTheAwardedQuotationBecomesAPurchaseOrder(unittest.TestCase):
	"""Who won the lot is decided by an APPROVED Tender Sourcing Decision, and
	only a director can approve one (`sourcing.approve_sourcing_decision`).

	Until this gate existed the endpoint asked only "is this quotation tagged to
	some lot?", and the award discipline lived exclusively in the SPA, which
	renders the button inside the approved branch. A whitelisted endpoint is not
	a button: anybody who may create a Purchase Order could POST a losing
	quotation and get a real, spendable PO — the tender file would then say one
	supplier won while the money went to another. That is the whole reason the
	decision record exists, so the endpoint has to read it.
	"""

	def setUp(self):
		self.db = _FakeDB()
		self.purchasing = _load_purchasing(self.db)

	def _po_names(self):
		return {name for (dt, name) in self.db.docs if dt == "Purchase Order"}

	def test_awarded_quotation_still_creates_the_purchase_order(self):
		"""The gate must not cost the honest path: the winner still goes through."""
		res = self.purchasing.create_po_from_quotation("SQ-VALID", company="ACME")
		self.assertFalse(res["existing"])
		self.assertEqual(self.db.docs[("Purchase Order", res["name"])]["custom_crm_deal"], "LOT-1")

	def test_losing_quotation_is_refused_and_no_po_is_written(self):
		"""The defect itself: SQ-LOSER sits on the same lot as the winner and was
		never selected, so it must not turn into money."""
		before = self._po_names()
		with self.assertRaises(ValueError) as caught:
			self.purchasing.create_po_from_quotation("SQ-LOSER", company="ACME")
		self.assertIn("sourcing decision", str(caught.exception).lower())
		self.assertEqual(self._po_names(), before)

	def test_draft_decision_is_not_an_award(self):
		"""A draft is sourcing's proposal; the approval is the director's act.
		Honouring a draft would hand the buyer the director's signature."""
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-DRAFT-AWARD", company="ACME")

	def test_lot_without_any_decision_is_refused(self):
		"""No record of an award means no award — not "award not recorded yet"."""
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-NO-DECISION", company="ACME")

	def test_superseded_award_no_longer_opens_the_po_route(self):
		"""A re-awarded lot has two approved decisions. The current one is the
		later approval; the supplier that lost the re-award must not still be
		able to bill the company on the strength of the old one."""
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-OLD-WINNER", company="ACME")
		res = self.purchasing.create_po_from_quotation("SQ-NEW-WINNER", company="ACME")
		self.assertFalse(res["existing"])

	def test_award_is_checked_before_the_idempotent_early_return(self):
		"""The idempotent branch answers "a draft PO for this lot+supplier already
		exists" — by lot and supplier, never by quotation. Asked before the award,
		it hands a losing bid the winner's PO name and a success response, which
		reads downstream as "this quotation produced that PO"."""
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-EXISTING-LOT-LOSER", company="ACME")

	def test_site_without_the_decision_table_fails_closed(self):
		"""On a site that has not migrated, the award cannot be read — and an
		unreadable award is not a granted one. `has_column` would raise here
		rather than answer False, so the guard probes the table first and the
		endpoint refuses instead of exploding with a TableMissingError."""
		self.db.tables_present.discard("Tender Sourcing Decision")
		with self.assertRaises(ValueError):
			self.purchasing.create_po_from_quotation("SQ-VALID", company="ACME")

	def test_award_lookup_ignores_the_callers_read_rights_on_the_decision(self):
		"""Tender Sourcing Decision is readable by Sales roles only, while the PO
		is created by purchasing. A permission-filtered read would return nothing
		for a legitimate buyer and break the honest path — so the gate reads the
		record with `get_all`, and answers a yes/no without exposing it."""
		calls: list[str] = []
		self.purchasing.frappe.get_list = lambda doctype, **kwargs: (
			calls.append(doctype) or _get_list(self.db, doctype, **kwargs)
		)
		self.purchasing.create_po_from_quotation("SQ-VALID", company="ACME")
		self.assertNotIn("Tender Sourcing Decision", calls)


if __name__ == "__main__":
	unittest.main()
