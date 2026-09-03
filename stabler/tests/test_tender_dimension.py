"""ADR-609 P5a — the tender as an accounting dimension (Frappe-free).

WHY this file exists. Until P5a the tender link was `custom_crm_deal`, a
document-level Custom Field that never reached the General Ledger. A tender's
cost was therefore assembled by walking documents, which misses every posting
that has no tender-bearing document of its own: the COGS row a Delivery Note
writes, a Purchase Invoice booked without a Purchase Order, a hand-written
Journal Entry. P5a makes the tender an Accounting Dimension so that EVERY
profit-and-loss row of a tender-enabled company names exactly one tender or the
"GENEL GİDER" overhead deal.

The rules below are the ones a refactor can silently undo while every number on
every screen still looks right, so each is pinned against a stubbed `frappe`
rather than asserted from the source text:

  * a company WITHOUT `enable_tender` must be untouched — no stamping, no
    default, no throw. Stabler is one app across seven tenants; a dimension that
    leaks onto a non-tender company puts a mandatory field on its ledger.
  * the fieldname is READ, never hardcoded: a site whose dimension was created by
    hand under a different fieldname must keep working.
  * a lost tender, and a won tender whose every submitted Sales Order is closed,
    may not be SELECTED any more — but a document that already carries one must
    stay readable and savable.
  * the GL fallback fills only empty P&L rows, never balance-sheet rows, and
    never creates a CRM Deal inside a GL transaction.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dimension -v
"""

from __future__ import annotations

import importlib
import os
import re
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))


def tearDownModule():
	"""The fakes below are process-wide -- hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


def _read(*parts: str) -> str:
	path = os.path.join(_ROOT, *parts)
	if not os.path.exists(path):
		return ""
	with open(path, encoding="utf-8") as source:
		return source.read()


def _code_only(src: str) -> str:
	"""The source with docstrings and comments removed.

	Every assertion that BANS a spelling has to look past the prose, or it passes
	the moment somebody EXPLAINS the mistake in a comment -- and would have passed
	on the mistake itself once the comment was deleted.
	"""
	src = re.sub(r'"""(?:.|\n)*?"""', "", src)
	return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


class _Doc(dict):
	"""The half of a Frappe document these hooks actually touch."""

	def __init__(self, doctype: str, **fields):
		super().__init__(**fields)
		self.doctype = doctype

	def get(self, key, default=None):
		if key == "doctype":
			return self.doctype
		return dict.get(self, key, default)

	def set(self, key, value):
		self[key] = value

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError as exc:  # pragma: no cover - mirrors frappe's AttributeError
			raise AttributeError(key) from exc


class _Meta:
	def __init__(self, fields: list[str], tables: dict | None = None):
		self._fields = set(fields)
		self._tables = tables or {}

	def has_field(self, fieldname):
		return fieldname in self._fields

	def get_field(self, fieldname):
		options = self._tables.get(fieldname)
		return types.SimpleNamespace(options=options) if options else None


class _Site:
	"""A tiny stand-in database: only the reads these two hooks perform."""

	def __init__(self):
		self.modules = {}  # company -> module map
		self.metas = {}  # doctype -> _Meta
		self.values = {}  # (doctype, name) -> dict of fields
		self.singles = {}  # (doctype, tuple(sorted(filters))) -> name/value
		self.accounts = {}  # account -> report_type
		self.lists = {}  # doctype -> list of rows
		self.reads = []  # every frappe.db.get_value(doctype, name, ...) call
		self.inserted = []
		self.dimension = "tender"
		self.columns = set()  # (doctype, column) pairs that exist


class _Thrown(Exception):
	pass


def _load(site: _Site):
	"""`stabler.api.tender_dimension` against the Frappe names it really touches."""
	_SANDBOX.evict(
		"stabler.api.tender_dimension",
		"frappe",
		"frappe.utils",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
	)
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.local = types.SimpleNamespace()
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]
	frappe.throw = lambda message, exception=_Thrown: (_ for _ in ()).throw(exception(message))

	def _get_value(doctype, name_or_filters, fields=None, as_dict=False, **_kwargs):
		if isinstance(name_or_filters, dict):
			key = (doctype, tuple(sorted(name_or_filters.items())))
			return site.singles.get(key)
		site.reads.append((doctype, name_or_filters, tuple(fields or ())))
		row = site.values.get((doctype, name_or_filters))
		if row is None:
			return None
		if isinstance(fields, str):
			return row.get(fields)
		picked = {f: row.get(f) for f in (fields or [])}
		return picked if as_dict else [picked[f] for f in (fields or [])]

	frappe.db = types.SimpleNamespace(
		get_value=_get_value,
		has_column=lambda dt, col: (dt, col) in site.columns,
		exists=lambda dt, name: bool(site.values.get((dt, name)) if isinstance(name, str) else None),
		sql=lambda *_a, **_k: [],
	)
	frappe.get_meta = lambda doctype, cached=True: site.metas.get(doctype, _Meta([]))
	frappe.get_cached_value = lambda dt, name, field: site.accounts.get(name) if dt == "Account" else None
	frappe.get_all = lambda doctype, **kwargs: _get_all(site, doctype, **kwargs)
	frappe.get_list = frappe.get_all

	def _get_doc(payload):
		doc = _Doc(payload.get("doctype"), **payload)
		doc.flags = types.SimpleNamespace()
		doc.name = f"{payload.get('doctype')}-NEW"
		doc.insert = lambda **kw: site.inserted.append((payload, kw))
		return doc

	frappe.get_doc = _get_doc
	frappe.logger = lambda *_a, **_k: types.SimpleNamespace(info=lambda *_x, **_y: None)
	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value=0: int(float(value or 0))
	frappe.utils = utils
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})

	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	settings.module_map_for = lambda company: site.modules.get(company, {})
	_SANDBOX.install({"stabler.stabler.doctype.stabler_settings.stabler_settings": settings})
	return importlib.import_module("stabler.api.tender_dimension")


def _get_all(site: _Site, doctype: str, **kwargs):
	rows = list(site.lists.get(doctype, []))
	filters = kwargs.get("filters") or {}
	for field, wanted in filters.items():
		if isinstance(wanted, list):
			op, value = wanted
			if op == "in":
				rows = [r for r in rows if r.get(field) in value]
			continue
		rows = [r for r in rows if r.get(field) == wanted]
	pluck = kwargs.get("pluck")
	if pluck:
		return [r.get(pluck) for r in rows]
	return rows


def _tender_site() -> _Site:
	"""`_Test Company` with the tender module on and the dimension installed."""
	site = _Site()
	site.modules["_Test Company"] = {"tender": True}
	site.modules["Plain Co"] = {"tender": False}
	site.singles[("Accounting Dimension", (("disabled", 0), ("document_type", "CRM Deal")))] = "tender"
	site.singles[("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead")))] = "OVERHEAD-1"
	site.metas["GL Entry"] = _Meta(["company", "account", "tender", "is_cancelled"])
	site.columns.add(("CRM Deal", "custom_tender_stage"))
	site.columns.add(("Sales Order", "custom_crm_deal"))
	return site


class TestDimensionFieldname(unittest.TestCase):
	"""The fieldname is read from the site, never spelled into a caller."""

	def test_reads_the_enabled_crm_deal_dimension(self):
		site = _tender_site()
		mod = _load(site)
		self.assertEqual(mod.dimension_fieldname(), "tender")

	def test_is_none_when_the_site_has_no_such_dimension(self):
		# A tenant that never ran v103 must get None and not a guessed "tender":
		# every writer below is a no-op in that state, which is what keeps the
		# feature invisible on the six non-tender sites.
		site = _tender_site()
		site.singles.pop(("Accounting Dimension", (("disabled", 0), ("document_type", "CRM Deal"))))
		mod = _load(site)
		self.assertIsNone(mod.dimension_fieldname())

	def test_honours_a_fieldname_created_by_hand(self):
		site = _tender_site()
		site.singles[("Accounting Dimension", (("disabled", 0), ("document_type", "CRM Deal")))] = "ihale"
		mod = _load(site)
		self.assertEqual(mod.dimension_fieldname(), "ihale")

	def test_both_hooks_write_a_hand_made_fieldname(self):
		# The behavioural half of "never hardcode the fieldname": on a site whose
		# dimension was created by hand as `ihale`, the document hook and the GL
		# hook must write `ihale`. A literal anywhere in the chain fails here.
		site = _tender_site()
		site.singles[("Accounting Dimension", (("disabled", 0), ("document_type", "CRM Deal")))] = "ihale"
		site.metas["GL Entry"] = _Meta(["company", "account", "ihale", "is_cancelled"])
		site.metas["Sales Order"] = _Meta(
			["company", "ihale", "custom_crm_deal"], {"items": "Sales Order Item"}
		)
		site.metas["Sales Order Item"] = _Meta(["ihale"])
		site.metas["Journal Entry"] = _Meta(["company"])
		site.accounts["Freight - _TC"] = "Profit and Loss"
		mod = _load(site)

		doc = _Doc(
			"Sales Order", company="_Test Company", custom_crm_deal="T-1", items=[_Doc("Sales Order Item")]
		)
		mod.stamp_tender(doc)
		self.assertEqual(doc.get("ihale"), "T-1")
		self.assertEqual(doc["items"][0].get("ihale"), "T-1")

		row = _Doc(
			"GL Entry",
			company="_Test Company",
			account="Freight - _TC",
			voucher_type="Journal Entry",
			voucher_no="JE-1",
			is_cancelled=0,
		)
		mod.default_gl_tender(row)
		self.assertEqual(row.get("ihale"), "OVERHEAD-1")


class TestTenderEnabledGate(unittest.TestCase):
	"""A company without the flag sees nothing. This is the tenant boundary."""

	def test_reads_the_company_module_flag(self):
		mod = _load(_tender_site())
		self.assertTrue(mod.tender_enabled("_Test Company"))
		self.assertFalse(mod.tender_enabled("Plain Co"))

	def test_a_company_without_the_flag_is_never_stamped(self):
		site = _tender_site()
		site.metas["Sales Order"] = _Meta(["company", "tender", "custom_crm_deal"])
		mod = _load(site)
		doc = _Doc("Sales Order", company="Plain Co", custom_crm_deal="DEAL-1")
		mod.stamp_tender(doc)
		self.assertIsNone(doc.get("tender"))

	def test_a_gl_row_of_a_company_without_the_flag_is_never_defaulted(self):
		site = _tender_site()
		site.accounts["Freight - PC"] = "Profit and Loss"
		mod = _load(site)
		row = _Doc(
			"GL Entry",
			company="Plain Co",
			account="Freight - PC",
			voucher_type="Journal Entry",
			voucher_no="JE-1",
		)
		mod.default_gl_tender(row)
		self.assertIsNone(row.get("tender"))


class TestActiveTenderRule(unittest.TestCase):
	"""Which deals a writer may still choose."""

	def setUp(self):
		self.site = _tender_site()
		self.site.values[("CRM Deal", "T-OPEN")] = {
			"company": "_Test Company",
			"deal_type": "Tender",
			"custom_tender_stage": "submitted",
		}
		self.site.values[("CRM Deal", "T-LOST")] = {
			"company": "_Test Company",
			"deal_type": "Tender",
			"custom_tender_stage": "lost",
		}
		self.site.values[("CRM Deal", "T-WON")] = {
			"company": "_Test Company",
			"deal_type": "Tender",
			"custom_tender_stage": "won",
		}
		self.site.values[("CRM Deal", "T-OTHER")] = {
			"company": "Plain Co",
			"deal_type": "Tender",
			"custom_tender_stage": "submitted",
		}
		self.site.values[("CRM Deal", "STANDARD-1")] = {
			"company": "_Test Company",
			"deal_type": "Standard",
			"custom_tender_stage": "",
		}
		self.mod = _load(self.site)

	def test_an_open_tender_is_active(self):
		self.assertTrue(self.mod.is_active_tender("T-OPEN", "_Test Company"))

	def test_a_lost_tender_is_not(self):
		self.assertFalse(self.mod.is_active_tender("T-LOST", "_Test Company"))

	def test_a_standard_deal_is_not_a_tender(self):
		self.assertFalse(self.mod.is_active_tender("STANDARD-1", "_Test Company"))

	def test_another_companys_tender_is_not(self):
		# The whole point of company scoping: a deal is a ledger dimension, and a
		# dimension value from another tenant's company would post foreign data.
		self.assertFalse(self.mod.is_active_tender("T-OTHER", "_Test Company"))

	def test_a_won_tender_with_an_open_order_is_still_active(self):
		# Won does not mean finished: the delivery is where the cost lands.
		self.site.lists["Sales Order"] = [
			{"name": "SO-1", "custom_crm_deal": "T-WON", "docstatus": 1, "status": "To Deliver and Bill"},
		]
		self.assertTrue(self.mod.is_active_tender("T-WON", "_Test Company"))

	def test_a_won_tender_whose_every_order_is_closed_is_not(self):
		self.site.lists["Sales Order"] = [
			{"name": "SO-1", "custom_crm_deal": "T-WON", "docstatus": 1, "status": "Closed"},
			{"name": "SO-2", "custom_crm_deal": "T-WON", "docstatus": 1, "status": "Cancelled"},
		]
		self.assertFalse(self.mod.is_active_tender("T-WON", "_Test Company"))

	def test_a_won_tender_with_no_order_at_all_is_still_active(self):
		# "every order is closed" is vacuously true over an empty list, and that
		# reading would refuse a tender that was won this morning.
		self.site.lists["Sales Order"] = []
		self.assertTrue(self.mod.is_active_tender("T-WON", "_Test Company"))

	def test_the_overhead_deal_is_selectable_but_not_an_active_tender(self):
		self.site.values[("CRM Deal", "OVERHEAD-1")] = {
			"company": "_Test Company",
			"deal_type": "Overhead",
			"custom_tender_stage": "",
		}
		self.assertFalse(self.mod.is_active_tender("OVERHEAD-1", "_Test Company"))
		self.mod.assert_selectable_tender("OVERHEAD-1", "_Test Company")  # must not throw

	def test_a_lost_tender_cannot_be_selected(self):
		with self.assertRaises(_Thrown) as caught:
			self.mod.assert_selectable_tender("T-LOST", "_Test Company")
		self.assertIn("GENEL GİDER", str(caught.exception))

	def test_another_companys_tender_cannot_be_selected(self):
		with self.assertRaises(_Thrown):
			self.mod.assert_selectable_tender("T-OTHER", "_Test Company")


class TestStampTender(unittest.TestCase):
	"""B4 — the document hook, which is what puts the value on the voucher."""

	def setUp(self):
		self.site = _tender_site()
		self.site.metas["Sales Order"] = _Meta(
			["company", "tender", "custom_crm_deal"], {"items": "Sales Order Item"}
		)
		self.site.metas["Sales Order Item"] = _Meta(["tender"])
		self.site.metas["Sales Invoice"] = _Meta(["company", "tender"], {"items": "Sales Invoice Item"})
		self.site.metas["Sales Invoice Item"] = _Meta(["tender", "sales_order"])
		self.site.metas["Journal Entry"] = _Meta(
			["company", "custom_crm_deal"], {"accounts": "Journal Entry Account"}
		)
		self.site.metas["Journal Entry Account"] = _Meta(["tender", "account"])
		self.mod = _load(self.site)

	def test_copies_the_documents_own_crm_deal_onto_the_dimension(self):
		doc = _Doc(
			"Sales Order", company="_Test Company", custom_crm_deal="T-1", items=[_Doc("Sales Order Item")]
		)
		self.mod.stamp_tender(doc)
		self.assertEqual(doc.get("tender"), "T-1")
		self.assertEqual(doc["items"][0].get("tender"), "T-1")

	def test_never_overwrites_a_value_the_caller_already_chose(self):
		doc = _Doc("Sales Order", company="_Test Company", custom_crm_deal="T-1", tender="T-2", items=[])
		self.mod.stamp_tender(doc)
		self.assertEqual(doc.get("tender"), "T-2")

	def test_derives_the_invoice_value_from_its_single_source_order(self):
		self.site.values[("Sales Order", "SO-1")] = {"tender": "T-1", "custom_crm_deal": "T-1"}
		self.site.columns.add(("Sales Order", "tender"))
		doc = _Doc(
			"Sales Invoice",
			company="_Test Company",
			items=[_Doc("Sales Invoice Item", sales_order="SO-1")],
		)
		self.mod.stamp_tender(doc)
		self.assertEqual(doc.get("tender"), "T-1")
		self.assertEqual(doc["items"][0].get("tender"), "T-1")

	def test_leaves_the_parent_empty_when_two_orders_disagree_and_stamps_rows(self):
		# One invoice, two tenders. A parent value would attribute BOTH lines to
		# one of them; the rows are where the truth is, so the rows carry it.
		self.site.values[("Sales Order", "SO-1")] = {"tender": "T-1"}
		self.site.values[("Sales Order", "SO-2")] = {"tender": "T-2"}
		doc = _Doc(
			"Sales Invoice",
			company="_Test Company",
			items=[
				_Doc("Sales Invoice Item", sales_order="SO-1"),
				_Doc("Sales Invoice Item", sales_order="SO-2"),
			],
		)
		self.mod.stamp_tender(doc)
		self.assertIsNone(doc.get("tender"))
		self.assertEqual(doc["items"][0].get("tender"), "T-1")
		self.assertEqual(doc["items"][1].get("tender"), "T-2")

	def test_reads_each_source_document_once(self):
		# Ten lines off one order is one read, not ten: this hook runs on every
		# save of every voucher on the company.
		self.site.values[("Sales Order", "SO-1")] = {"tender": "T-1"}
		doc = _Doc(
			"Sales Invoice",
			company="_Test Company",
			items=[_Doc("Sales Invoice Item", sales_order="SO-1") for _ in range(10)],
		)
		self.mod.stamp_tender(doc)
		self.assertEqual([r for r in self.site.reads if r[0] == "Sales Order"].__len__(), 1)

	def test_journal_entry_rows_take_the_parents_deal(self):
		# The Journal Entry PARENT is not one of the 52 dimension doctypes; its
		# account rows are, and they are what get_gl_dict reads.
		doc = _Doc(
			"Journal Entry",
			company="_Test Company",
			custom_crm_deal="T-1",
			accounts=[_Doc("Journal Entry Account"), _Doc("Journal Entry Account", tender="T-9")],
		)
		self.mod.stamp_tender(doc)
		self.assertEqual(doc["accounts"][0].get("tender"), "T-1")
		self.assertEqual(doc["accounts"][1].get("tender"), "T-9")

	def test_never_writes_the_overhead_deal_at_document_level(self):
		# GENEL GİDER is a LEDGER default, applied per GL row by B5. Writing it on
		# the document would make an untagged invoice look deliberately overhead.
		doc = _Doc("Sales Order", company="_Test Company", items=[])
		self.mod.stamp_tender(doc)
		self.assertIsNone(doc.get("tender"))


class TestDefaultGlTender(unittest.TestCase):
	"""B5 — the safety net: no P&L row of a tender company stays unattributed."""

	def setUp(self):
		self.site = _tender_site()
		self.site.accounts["Freight - _TC"] = "Profit and Loss"
		self.site.accounts["Cash - _TC"] = "Balance Sheet"
		self.site.metas["Journal Entry"] = _Meta(["company"])
		self.site.metas["Sales Invoice"] = _Meta(["company", "tender"], {"items": "Sales Invoice Item"})
		self.site.metas["Sales Invoice Item"] = _Meta(["tender"])
		self.mod = _load(self.site)

	def _row(self, **over):
		fields = {
			"company": "_Test Company",
			"account": "Freight - _TC",
			"voucher_type": "Journal Entry",
			"voucher_no": "JE-1",
			"is_cancelled": 0,
		}
		fields.update(over)
		return _Doc("GL Entry", **fields)

	def test_falls_back_to_the_overhead_deal_on_a_pl_row(self):
		row = self._row()
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "OVERHEAD-1")

	def test_leaves_a_balance_sheet_row_alone(self):
		# Decision 2: the cash leg of an expense is not a tender cost. Filling it
		# would double every tender's figure the moment P5b sums the dimension.
		row = self._row(account="Cash - _TC")
		self.mod.default_gl_tender(row)
		self.assertIsNone(row.get("tender"))

	def test_leaves_a_row_that_already_names_a_tender_alone(self):
		row = self._row(tender="T-1")
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "T-1")

	def test_leaves_a_cancelled_row_alone(self):
		# `validate_dimensions_for_pl_and_bs` skips cancelled rows, so stamping
		# one would write a value the mandatory check never asked for.
		row = self._row(is_cancelled=1)
		self.mod.default_gl_tender(row)
		self.assertIsNone(row.get("tender"))

	def test_prefers_the_vouchers_own_value_over_the_overhead_deal(self):
		self.site.values[("Sales Invoice", "SI-1")] = {"tender": "T-1"}
		row = self._row(voucher_type="Sales Invoice", voucher_no="SI-1", account="Freight - _TC")
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "T-1")

	def test_takes_the_single_item_value_when_the_parent_is_empty(self):
		self.site.values[("Sales Invoice", "SI-2")] = {"tender": None}
		self.site.lists["Sales Invoice Item"] = [
			{"parent": "SI-2", "parenttype": "Sales Invoice", "tender": "T-7"},
			{"parent": "SI-2", "parenttype": "Sales Invoice", "tender": "T-7"},
		]
		row = self._row(voucher_type="Sales Invoice", voucher_no="SI-2")
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "T-7")

	def test_falls_back_to_overhead_when_the_items_disagree(self):
		self.site.values[("Sales Invoice", "SI-3")] = {"tender": None}
		self.site.lists["Sales Invoice Item"] = [
			{"parent": "SI-3", "parenttype": "Sales Invoice", "tender": "T-1"},
			{"parent": "SI-3", "parenttype": "Sales Invoice", "tender": "T-2"},
		]
		row = self._row(voucher_type="Sales Invoice", voucher_no="SI-3")
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "OVERHEAD-1")

	def test_survives_a_voucher_type_with_no_item_table(self):
		# Period Closing Voucher has no `items`. Reading rows off it blindly is an
		# exception raised inside a GL transaction — the posting, not the tag,
		# is what would fail.
		self.site.metas["Period Closing Voucher"] = _Meta(["company"])
		row = self._row(voucher_type="Period Closing Voucher", voucher_no="PCV-1")
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "OVERHEAD-1")

	def test_throws_by_name_when_the_overhead_deal_was_deleted(self):
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		row = self._row()
		with self.assertRaises(_Thrown) as caught:
			self.mod.default_gl_tender(row)
		self.assertIn("_Test Company", str(caught.exception))

	def test_never_creates_a_deal_inside_a_gl_transaction(self):
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		row = self._row()
		with self.assertRaises(_Thrown):
			self.mod.default_gl_tender(row)
		self.assertEqual(self.site.inserted, [], "a GL posting created a CRM Deal")


class TestHooksRegistration(unittest.TestCase):
	"""A handler nobody calls is a handler that does not exist."""

	def setUp(self):
		self.hooks = _code_only(_read("hooks.py"))

	def test_the_document_hook_runs_on_every_writer_stabler_owns(self):
		for doctype in (
			"Sales Order",
			"Purchase Order",
			"Supplier Quotation",
			"Request for Quotation",
			"Journal Entry",
			"Sales Invoice",
			"Purchase Invoice",
			"Delivery Note",
			"Purchase Receipt",
		):
			block = self.hooks.split(f'"{doctype}": {{', 1)
			self.assertEqual(len(block), 2, f"{doctype} has no doc_events block")
			body = block[1].split("\n\t},", 1)[0]
			self.assertIn("stabler.api.tender_dimension.stamp_tender", body, f"{doctype} is not stamped")

	def test_the_gl_safety_net_is_registered(self):
		self.assertIn("stabler.api.tender_dimension.default_gl_tender", self.hooks)
		gl = self.hooks.split('"GL Entry": {', 1)
		self.assertEqual(len(gl), 2, "GL Entry has no doc_events block")
		self.assertIn("before_validate", gl[1].split("\n\t},", 1)[0])

	def test_turning_the_module_on_sets_the_company_up(self):
		self.assertIn("stabler.api.tender_dimension.on_company_modules_update", self.hooks)


if __name__ == "__main__":
	unittest.main()
