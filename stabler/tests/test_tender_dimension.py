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
import json
import os
import re
import types
import typing
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

	#: Not document fields: the identity Frappe assigns and the methods this stub binds.
	_INTERNALS = ("doctype", "name", "flags", "insert", "append", "save")

	def __setattr__(self, key, value):
		# `doc.some_field = x` sets a FIELD in Frappe, not a python attribute -- a
		# stub that stored it as an attribute would report an empty payload and let
		# a hook that never filled the field pass.
		if key in _Doc._INTERNALS:
			object.__setattr__(self, key, value)
		else:
			self[key] = value


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
		self.filter_reads = []  # every frappe.db.get_value(doctype, {filters}, ...) call
		self.order_bys = []  # the order_by each of those asked for
		self.module_reads = []  # every module_map_for(company) call
		self.inserted = []
		self.dimension = "tender"
		self.columns = set()  # (doctype, column) pairs that exist
		self.tables = set()  # doctypes whose table exists
		self.sql = []  # every statement, in order
		self.rows_matching = 0  # what a SELECT COUNT(*) reports
		self.saved = []  # every doc.save()


class _Row(dict):
	"""A child row, which Frappe hands back with attribute access."""

	def __getattr__(self, key):
		return self.get(key)

	def __setattr__(self, key, value):
		self[key] = value


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
			# Keyed on the requested FIELD too: the same filter is used to read the
			# dimension's `fieldname` and its `name`, and a stub that conflated the
			# two would hide a caller asking for the wrong one.
			where = tuple(sorted(name_or_filters.items()))
			field_key = fields if isinstance(fields, str) else tuple(fields or ())
			site.filter_reads.append((doctype, where, field_key))
			site.order_bys.append((doctype, _kwargs.get("order_by")))
			if (doctype, where, field_key) in site.singles:
				return site.singles[(doctype, where, field_key)]
			return site.singles.get((doctype, where))
		site.reads.append((doctype, name_or_filters, tuple(fields or ())))
		row = site.values.get((doctype, name_or_filters))
		if row is None:
			return None
		if isinstance(fields, str):
			return row.get(fields)
		picked = {f: row.get(f) for f in (fields or [])}
		return picked if as_dict else [picked[f] for f in (fields or [])]

	def _has_column(dt, col):
		if site.tables and dt not in site.tables:
			# Mirrors the real thing: `has_column` raises TableMissingError rather
			# than returning False when the doctype's table does not exist.
			raise LookupError(f"table missing: {dt}")
		return (dt, col) in site.columns

	def _exists(dt, name):
		if isinstance(name, dict):
			return site.singles.get((dt, tuple(sorted(name.items()))))
		return bool(site.values.get((dt, name)))

	def _sql(statement, params=None, **_kwargs):
		site.sql.append((" ".join(str(statement).split()), params))
		return [[site.rows_matching]] if "COUNT(*)" in statement else []

	frappe.db = types.SimpleNamespace(
		get_value=_get_value,
		has_column=_has_column,
		table_exists=lambda dt: (dt in site.tables) if site.tables else True,
		exists=_exists,
		count=lambda dt, filters=None: len(site.lists.get(dt, [])),
		set_value=lambda *_a, **_k: None,
		commit=lambda: None,
		sql=_sql,
	)
	frappe.clear_cache = lambda **_k: None
	frappe.get_meta = lambda doctype, cached=True: site.metas.get(doctype, _Meta([]))
	frappe.get_cached_value = lambda dt, name, field: site.accounts.get(name) if dt == "Account" else None
	frappe.get_all = lambda doctype, **kwargs: _get_all(site, doctype, **kwargs)
	frappe.get_list = frappe.get_all

	def _new_doc(doctype, **fields):
		doc = _Doc(doctype, **fields)
		doc.name = f"{doctype}-NEW"

		def _insert(**kw):
			# CRM Organization autonames `field:organization_name`, which is the only
			# reason the deal's link value reads as the organization's own name.
			if doctype == "CRM Organization" and doc.get("organization_name"):
				doc.name = doc["organization_name"]
			site.inserted.append(({"doctype": doc.doctype, **doc}, kw))

		doc.insert = _insert
		return doc

	def _get_doc(payload, name=None):
		if isinstance(payload, str):
			stored = site.values.get((payload, name))
			doc = _Doc(payload, **(stored or {}))
			doc.name = name
		else:
			doc = _new_doc(payload.get("doctype"), **{k: v for k, v in payload.items() if k != "doctype"})
		doc.flags = types.SimpleNamespace()
		doc.append = lambda table, row: doc.setdefault(table, []).append(_Row(row))
		doc.save = lambda **kw: site.saved.append((doc.doctype, doc.name, dict(doc)))
		return doc

	def _bare_new_doc(doctype):
		doc = _new_doc(doctype)
		doc.flags = types.SimpleNamespace()
		return doc

	frappe.get_doc = _get_doc
	frappe.new_doc = _bare_new_doc
	frappe.logger = lambda *_a, **_k: types.SimpleNamespace(info=lambda *_x, **_y: None)
	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value=0: int(float(value or 0))
	frappe.utils = utils
	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})

	settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")

	def _module_map_for(company):
		site.module_reads.append(company)
		return site.modules.get(company, {})

	settings.module_map_for = _module_map_for
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
	# `start` then `limit_page_length`, the order SQL applies OFFSET and LIMIT.
	# Modelled because `list_active_tenders` pages a set it also filters in
	# Python: a double that ignored the LIMIT would report a green suite for a
	# picker whose page 2 skips rows the filter had already removed.
	start = int(kwargs.get("start") or 0)
	if start:
		rows = rows[start:]
	limit = kwargs.get("limit_page_length")
	if limit:
		rows = rows[: int(limit)]
	pluck = kwargs.get("pluck")
	if pluck:
		return [r.get(pluck) for r in rows]
	return rows


#: How the dimension is looked up: enabled, over CRM Deal.
_ENABLED_DIMENSION = (("disabled", 0), ("document_type", "CRM Deal"))
#: How the patch looks it up: any CRM Deal dimension, enabled or not.
_ANY_DIMENSION = (("document_type", "CRM Deal"),)
#: The company's row on the dimension — the mandatory flag erpnext enforces.
_DETAIL_ROW = (("company", "_Test Company"), ("parent", "Tender"))


def _drop_dimension(site: _Site) -> None:
	for key in (
		("Accounting Dimension", _ENABLED_DIMENSION, "fieldname"),
		("Accounting Dimension", _ENABLED_DIMENSION, "name"),
	):
		site.singles.pop(key, None)


def _tender_site() -> _Site:
	"""`_Test Company` with the tender module on and the dimension installed."""
	site = _Site()
	site.modules["_Test Company"] = {"tender": True}
	site.modules["Plain Co"] = {"tender": False}
	site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "fieldname")] = "tender"
	site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "name")] = "Tender"
	site.singles[("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead")))] = "OVERHEAD-1"
	# What erpnext's `validate_dimensions_for_pl_and_bs` actually reads, and
	# therefore what the GL hook has to gate on.
	site.singles[("Accounting Dimension Detail", _DETAIL_ROW, "mandatory_for_pl")] = 1
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
		_drop_dimension(site)
		mod = _load(site)
		self.assertIsNone(mod.dimension_fieldname())

	def test_honours_a_fieldname_created_by_hand(self):
		site = _tender_site()
		site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "fieldname")] = "ihale"
		mod = _load(site)
		self.assertEqual(mod.dimension_fieldname(), "ihale")

	def test_both_hooks_write_a_hand_made_fieldname(self):
		# The behavioural half of "never hardcode the fieldname": on a site whose
		# dimension was created by hand as `ihale`, the document hook and the GL
		# hook must write `ihale`. A literal anywhere in the chain fails here.
		site = _tender_site()
		site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "fieldname")] = "ihale"
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

	def test_a_gl_row_of_a_company_with_no_dimension_row_is_never_defaulted(self):
		"""The tenant boundary, stated the way erpnext states it.

		A company nobody set up has no Accounting Dimension Detail row, so erpnext
		demands nothing of its P&L rows and this hook must add nothing to them —
		whatever its module flag says. That is the same company as "no tender
		module" today, because only `ensure_company_setup` writes the row and it is
		gated on the flag.
		"""
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
		# Decision 2: the cash leg of an untagged expense is not a tender cost, so
		# the fallback never ADDS a value to one. It does not follow that the
		# ledger's balance-sheet rows are clean — erpnext tags both legs of a
		# voucher that carries the dimension at document level (measured in the
		# bench suite) — which is why P5b sums P&L accounts only.
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

	def test_leaves_a_period_closing_row_alone(self):
		"""R5. The year-end close reverses every P&L account into retained earnings.

		Period Closing Voucher is not one of the 52 dimension doctypes and has no
		`items` table, so nothing about it can name a tender — and defaulting it to
		GENEL GIDER would book the reversal of EVERY tender's profit and loss onto
		overhead, which is a wrong closing entry rather than a missing tag. erpnext
		exempts the same voucher from dimension validation itself (`gl_entry.py`
		lines 98 and 200), so nothing demands a value here either.
		"""
		self.site.metas["Period Closing Voucher"] = _Meta(["company"])
		row = self._row(voucher_type="Period Closing Voucher", voucher_no="PCV-1")
		self.mod.default_gl_tender(row)
		self.assertIsNone(row.get("tender"))

	def test_survives_a_voucher_type_with_no_item_table(self):
		# Reading rows off a voucher with no `items` table is an exception raised
		# inside a GL transaction — the POSTING, not the tag, is what would fail.
		self.site.metas["Landed Cost Voucher"] = _Meta(["company"])
		row = self._row(voucher_type="Landed Cost Voucher", voucher_no="LCV-1")
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

	def test_still_defaults_a_company_whose_module_flag_was_turned_off(self):
		"""Turning `enable_tender` off must not brick the company's ledger.

		`ensure_company_setup` never removes the detail row — historical GL rows
		would be left carrying a dimension nothing declares. So erpnext's
		`validate_dimensions_for_pl_and_bs` goes on REFUSING every P&L row without
		a tender, because it reads that row and not our flag. Measured live: flag
		off, untagged expense -> "Accounting Dimension Tender is required for
		'Profit and Loss' account Tax Expense - _TC". A hook gated on the flag
		stops filling exactly the rows erpnext still demands.
		"""
		self.site.modules["_Test Company"] = {"tender": False}
		row = self._row()
		self.mod.default_gl_tender(row)
		self.assertEqual(row.get("tender"), "OVERHEAD-1")

	def test_a_company_whose_row_is_not_mandatory_is_left_alone(self):
		# The mirror image: nothing demands a value, so nothing is invented.
		self.site.singles[("Accounting Dimension Detail", _DETAIL_ROW, "mandatory_for_pl")] = 0
		row = self._row()
		self.mod.default_gl_tender(row)
		self.assertIsNone(row.get("tender"))

	def test_asks_the_database_once_for_a_voucher_of_many_rows(self):
		"""GL rows are inserted ONE DOCUMENT AT A TIME, so this hook runs per row.

		`general_ledger.make_entry` builds a `frappe.new_doc("GL Entry")` and
		submits it for every line, which is why the hook fires at all — and why an
		uncached lookup is paid once per line. A reviewer instrumented it at 7.0
		queries per row over a 20-row entry.
		"""
		for _index in range(20):
			self.mod.default_gl_tender(self._row(account="Freight - _TC", voucher_no="JE-1"))
		detail = [r for r in self.site.filter_reads if r[0] == "Accounting Dimension Detail"]
		overhead = [r for r in self.site.filter_reads if r[0] == "CRM Deal"]
		dimension = [r for r in self.site.filter_reads if r[0] == "Accounting Dimension"]
		self.assertEqual(len(detail), 1, f"the mandatory row was read {len(detail)} times for one entry")
		self.assertEqual(len(overhead), 1, f"the overhead deal was read {len(overhead)} times for one entry")
		self.assertLessEqual(len(dimension), 2, "the dimension was re-read per row")

	def test_reads_the_module_flag_once_per_company(self):
		# `tender_enabled` costs a Company read, the Singles read and four child
		# tables of Stabler Settings; `stamp_tender` and every writer ask for it.
		for _ in range(5):
			self.mod.tender_enabled("_Test Company")
		self.assertEqual(self.site.module_reads, ["_Test Company"])

	def test_forgetting_the_caches_forgets_all_of_them(self):
		self.mod.tender_enabled("_Test Company")
		self.mod.default_gl_tender(self._row())
		self.mod.clear_dimension_cache()
		self.site.module_reads.clear()
		self.site.filter_reads.clear()
		self.mod.tender_enabled("_Test Company")
		self.mod.default_gl_tender(self._row())
		self.assertEqual(self.site.module_reads, ["_Test Company"], "the module flag survived the reset")
		self.assertTrue(
			[r for r in self.site.filter_reads if r[0] == "Accounting Dimension Detail"],
			"the mandatory row survived the reset",
		)


class TestEnsureCompanySetup(unittest.TestCase):
	"""B1 — the per-company half: one overhead deal, one detail row."""

	def setUp(self):
		self.site = _tender_site()
		self.site.values[("Accounting Dimension", "Tender")] = {
			"document_type": "CRM Deal",
			"fieldname": "tender",
			"dimension_defaults": [],
		}
		self.site.lists["CRM Deal Status"] = [{"name": "Qualification"}]
		self.mod = _load(self.site)

	def test_a_company_without_the_flag_gets_nothing(self):
		# The tenant boundary, stated as data: no detail row means no mandatory
		# check, and no overhead deal means no CRM row on a tenant that never
		# asked for one.
		created = self.mod.ensure_company_setup("Plain Co")
		self.assertEqual(created, {"overhead_deal": False, "detail_row": False, "default_dimension": False})
		self.assertEqual(self.site.inserted, [])
		self.assertEqual(self.site.saved, [])

	def test_creates_the_overhead_deal_and_the_detail_row(self):
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		created = self.mod.ensure_company_setup("_Test Company")
		self.assertTrue(created["overhead_deal"])
		self.assertTrue(created["detail_row"])
		deal = next((p, kw) for p, kw in self.site.inserted if p.get("doctype") == "CRM Deal")
		payload, kwargs = deal
		self.assertEqual(payload["organization"], "GENEL GİDER")
		self.assertEqual(payload["deal_type"], "Overhead")
		self.assertEqual(payload["company"], "_Test Company")
		# `ignore_mandatory` because a CRM Deal normally demands tender fields this
		# ledger bucket must not have.
		self.assertTrue(kwargs.get("ignore_mandatory"))
		row = self.site.saved[0][2]["dimension_defaults"][0]
		self.assertEqual(row["company"], "_Test Company")
		self.assertEqual(row["mandatory_for_pl"], 1)
		self.assertEqual(row["mandatory_for_bs"], 0)
		self.assertEqual(row["reference_document"], "CRM Deal")

	def test_the_overhead_deal_is_read_in_a_defined_order(self):
		"""R8. Two buckets must not make attribution depend on the engine's mood.

		`deal_type` is client-writable through `save_deal`, so a company CAN end up
		with a second Overhead deal. An unordered `get_value` would then answer with
		either one, and the same untagged expense could be attributed differently
		between two requests — two buckets that never reconcile. Ordering by
		creation makes the answer the FIRST bucket, always.
		"""
		self.site.order_bys.clear()
		self.mod.clear_dimension_cache()
		self.mod.overhead_deal("_Test Company")
		asked = [order for doctype, order in self.site.order_bys if doctype == "CRM Deal"]
		self.assertEqual(asked, ["creation asc"])

	def test_a_created_overhead_deal_is_visible_to_the_next_reader(self):
		"""The read is cached per request; the CREATE happens in that same request.

		`ensure_company_setup` asks for the deal, is told None, creates it, and the
		GL hook two lines later asks again. A cache that kept the None would make
		the hook throw "GENEL GİDER deal is missing" for a company it had just set
		up.
		"""
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		self.assertIsNone(self.mod.overhead_deal("_Test Company"))
		self.site.singles[("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead")))] = (
			"OVERHEAD-2"
		)
		self.mod.overhead_deal("_Test Company", create=True)
		self.assertEqual(self.mod.overhead_deal("_Test Company"), "OVERHEAD-2")

	def test_creates_the_organization_the_deal_links_to(self):
		"""`CRM Deal.organization` is a LINK to CRM Organization, not free text.

		Measured on genesis-test.local 2026-09-03, running v103 for the first time:
		inserting the deal with `organization: "GENEL GİDER"` and nothing else died
		with `LinkValidationError: Could not find Organization: GENEL GİDER`, and
		the patch aborted before any company was set up. `ignore_mandatory` does not
		help — link validation is a separate pass. The organization has to exist
		first, exactly as `crm._resolve_crm_organization` does it for every deal the
		SPA saves.
		"""
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		self.mod.overhead_deal("_Test Company", create=True)
		doctypes = [payload.get("doctype") for payload, _kw in self.site.inserted]
		self.assertEqual(doctypes, ["CRM Organization", "CRM Deal"], "the deal was inserted first")
		self.assertEqual(self.site.inserted[0][0]["organization_name"], "GENEL GİDER")

	def test_reuses_an_organization_that_already_exists(self):
		self.site.singles[("CRM Organization", (("organization_name", "GENEL GİDER"),))] = "GENEL GİDER"
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		self.mod.overhead_deal("_Test Company", create=True)
		doctypes = [payload.get("doctype") for payload, _kw in self.site.inserted]
		self.assertEqual(doctypes, ["CRM Deal"], "a second organization was created")

	def test_is_idempotent_when_the_row_already_names_a_default(self):
		self.site.values[("Accounting Dimension", "Tender")]["dimension_defaults"] = [
			_Row({"company": "_Test Company", "default_dimension": "OVERHEAD-1", "mandatory_for_pl": 1})
		]
		created = self.mod.ensure_company_setup("_Test Company")
		self.assertEqual(created, {"overhead_deal": False, "detail_row": False, "default_dimension": False})
		self.assertEqual(self.site.saved, [], "a second run rewrote the dimension")

	def test_never_turns_the_mandatory_check_off(self):
		# Someone unticking `mandatory_for_pl` by hand is a decision this patch may
		# not silently make, but re-running must never make it either.
		self.site.values[("Accounting Dimension", "Tender")]["dimension_defaults"] = [
			_Row({"company": "_Test Company", "default_dimension": "", "mandatory_for_pl": 0})
		]
		self.mod.ensure_company_setup("_Test Company")
		saved_row = self.site.saved[0][2]["dimension_defaults"][0]
		self.assertEqual(saved_row["default_dimension"], "OVERHEAD-1")
		self.assertEqual(saved_row["mandatory_for_pl"], 0, "the patch flipped a flag a human had cleared")


class TestBackfill(unittest.TestCase):
	"""B6 — the historical half. Raw SQL, no doc events, `modified` untouched."""

	def setUp(self):
		self.site = _tender_site()
		self.site.tables = {
			"Sales Order",
			"Sales Order Item",
			"Purchase Order",
			"Purchase Order Item",
			"Supplier Quotation",
			"Supplier Quotation Item",
			"Journal Entry",
			"Journal Entry Account",
			"Sales Invoice",
			"Sales Invoice Item",
			"Delivery Note",
			"Delivery Note Item",
			"Purchase Invoice",
			"Purchase Invoice Item",
			"GL Entry",
		}
		for table in self.site.tables:
			self.site.columns.add((table, "tender"))
			self.site.columns.add((table, "custom_crm_deal"))
		for child, link in (
			("Sales Invoice Item", "sales_order"),
			("Delivery Note Item", "against_sales_order"),
			("Purchase Invoice Item", "purchase_order"),
		):
			self.site.columns.add((child, link))
		self.site.rows_matching = 3
		self.mod = _load(self.site)

	def _run(self):
		return self.mod.backfill(["_Test Company"], "tender")

	def test_the_backfill_skips_the_doctype_that_has_no_dimension_column(self):
		"""R10. `Request for Quotation` is not an accounting dimension doctype.

		It carries `custom_crm_deal` (v34) but ERPNext never adds the dimension
		field to it, so the copy has nowhere to land. `_column_exists` made the
		attempt silent rather than harmless-looking, which is worse: the parent
		read as covered.
		"""
		self.assertNotIn(
			"Request for Quotation",
			[parent for parent, _child in self.mod._LEGACY_PARENTS],
		)

	def test_reports_what_it_changed_per_table(self):
		counts = self._run()
		self.assertTrue(counts, "the backfill reported nothing at all")
		self.assertEqual(set(counts.values()), {3})

	def test_a_second_run_reports_zeros_and_writes_nothing(self):
		# Idempotence is the property the deploy depends on: this patch runs on
		# eight sites and again on every migrate.
		self.site.rows_matching = 0
		counts = self._run()
		self.assertEqual(set(counts.values()), {0})
		self.assertEqual(
			[s for s, _p in self.site.sql if s.startswith("UPDATE")],
			[],
			"a no-op run still issued UPDATEs",
		)

	def test_every_update_is_counted_by_the_same_where(self):
		# The number the patch prints has to be the number of rows that changed —
		# a COUNT over a different WHERE is a report nobody can check.
		self._run()
		counts = [s for s, _p in self.site.sql if s.startswith("SELECT COUNT(*)")]
		updates = [s for s, _p in self.site.sql if s.startswith("UPDATE")]
		self.assertEqual(len(counts), len(updates))
		for select, update in zip(counts, updates, strict=True):
			# rsplit: the derived statements carry a WHERE inside their subquery too.
			self.assertEqual(select.rsplit(" WHERE ", 1)[1], update.rsplit(" WHERE ", 1)[1])

	def test_never_touches_modified(self):
		# A backfill that bumps `modified` breaks every optimistic-concurrency
		# check the SPA holds and rewrites the audit trail of documents nobody
		# edited.
		self._run()
		for statement, _params in self.site.sql:
			self.assertNotIn("modified", statement)

	def test_scopes_every_statement_to_the_named_companies_by_parameter(self):
		# Tenant isolation: a company list spliced into the SQL text is both a
		# leak waiting to happen and an injection surface.
		self._run()
		for statement, params in self.site.sql:
			self.assertIn("IN %(companies)s", statement)
			self.assertEqual(params, {"companies": ("_Test Company",)})
			self.assertNotIn("_Test Company", statement)

	def test_derives_an_invoice_only_from_orders_that_agree(self):
		# Two source orders naming two tenders leave the invoice alone: picking one
		# would attribute the whole invoice to half of its own lines.
		self._run()
		derived = [s for s, _p in self.site.sql if "COUNT(DISTINCT" in s and s.startswith("UPDATE")]
		self.assertEqual(len(derived), 3, "Sales Invoice, Delivery Note and Purchase Invoice")
		for statement in derived:
			self.assertIn("d.n = 1", statement)

	def test_reads_the_delivery_note_link_erpnext_actually_stores(self):
		# Delivery Note Item carries `against_sales_order`, not `sales_order`.
		# Getting this wrong silently backfills nothing and looks like success.
		self._run()
		joined = " ".join(s for s, _p in self.site.sql if "Delivery Note" in s)
		self.assertIn("against_sales_order", joined)

	def test_never_writes_the_overhead_deal_onto_history(self):
		# Pre-P5 rows stay empty so P5b can report them as "unassigned before P5".
		# Stamping GENEL GİDER would invent a decision nobody made.
		self._run()
		for statement, _params in self.site.sql:
			self.assertNotIn("GENEL", statement)
			self.assertNotIn("Overhead", statement)

	def test_skips_a_table_whose_legacy_column_never_landed(self):
		self.site.columns = {c for c in self.site.columns if c != ("Supplier Quotation", "custom_crm_deal")}
		self.mod.clear_dimension_cache()
		counts = self._run()
		self.assertNotIn("Supplier Quotation", counts)

	def test_refuses_a_fieldname_that_is_not_a_plain_column(self):
		# The fieldname is interpolated into SQL (it cannot be bound). It comes
		# from a doctype ERPNext validates, but this module is what would carry the
		# injection if that ever changed.
		with self.assertRaises(_Thrown):
			self.mod.backfill(["_Test Company"], "tender`; DROP TABLE `tabGL Entry")
		self.assertEqual(self.site.sql, [])


class TestPatchV103(unittest.TestCase):
	"""B2 — the patch, run twice, against a stand-in site."""

	def setUp(self):
		self.site = _tender_site()
		self.site.tables = {"CRM Deal", "Company", "Stabler Company Modules", "GL Entry"}
		self.site.columns.add(("CRM Deal", "deal_type"))
		self.site.lists["Company"] = [{"name": "_Test Company"}, {"name": "Plain Co"}]
		self.site.lists["CRM Deal Status"] = [{"name": "Qualification"}]
		self.site.values[("Accounting Dimension", "Tender")] = {
			"document_type": "CRM Deal",
			"fieldname": "tender",
			"dimension_defaults": [_Row({"company": "_Test Company", "default_dimension": "OVERHEAD-1"})],
		}
		self.site.singles[("Custom Field", (("dt", "CRM Deal"), ("fieldname", "deal_type")))] = {
			"name": "CRM Deal-deal_type",
			"options": "Standard\nTender",
		}
		self.site.rows_matching = 0
		self.landed = []

	def _load_patch(self, all_fields_present=True):
		mod = _load(self.site)
		frappe = importlib.import_module("frappe")
		present = ["tender"] if all_fields_present else []
		for doctype in (
			"GL Entry",
			"Journal Entry Account",
			"Sales Invoice",
			"Purchase Invoice",
			"Sales Order",
			"Purchase Order",
		):
			self.site.metas[doctype] = _Meta(present)
		erp = types.ModuleType("erpnext.accounts.doctype.accounting_dimension.accounting_dimension")
		erp.make_dimension_in_accounting_doctypes = lambda doc=None: self.landed.append(doc)
		_SANDBOX.evict("stabler.patches.v103_tender_accounting_dimension")
		_SANDBOX.install({"erpnext.accounts.doctype.accounting_dimension.accounting_dimension": erp})
		self.assertIs(frappe, importlib.import_module("frappe"))
		return importlib.import_module("stabler.patches.v103_tender_accounting_dimension"), mod

	def test_creates_the_dimension_and_installs_its_fields_itself(self):
		# Outside tests `Accounting Dimension.on_update` only ENQUEUES the field
		# creation. A patch that trusts that finishes, prints OK, and leaves the
		# site with a dimension and no columns until a worker happens to run.
		_drop_dimension(self.site)
		self.site.singles[("Accounting Dimension", _ANY_DIMENSION)] = None
		patch, _mod = self._load_patch()
		patch.execute()
		self.assertEqual(len(self.landed), 1, "make_dimension_in_accounting_doctypes was not called directly")
		payload = [p for p, _kw in self.site.inserted if p.get("doctype") == "Accounting Dimension"]
		self.assertEqual(payload[0]["label"], "Tender")
		self.assertEqual(payload[0]["fieldname"], "tender")
		self.assertEqual(payload[0]["document_type"], "CRM Deal")

	def test_fails_loudly_when_a_field_did_not_land(self):
		# A half-installed dimension is worse than none: `mandatory_for_pl` is on
		# and the column the check reads does not exist.
		self.site.singles[("Accounting Dimension", _ANY_DIMENSION)] = "Tender"
		patch, _mod = self._load_patch(all_fields_present=False)
		with self.assertRaises(_Thrown) as caught:
			patch.execute()
		self.assertIn("GL Entry", str(caught.exception))

	def test_stops_before_the_dimension_on_a_site_with_no_tender_company(self):
		# The 52 Link fields must not appear on a tenant that does not run tenders.
		self.site.modules = {"_Test Company": {"tender": False}, "Plain Co": {"tender": False}}
		self.site.singles[("Accounting Dimension", _ANY_DIMENSION)] = None
		patch, _mod = self._load_patch()
		patch.execute()
		self.assertEqual(self.landed, [], "a non-tender site got the dimension")
		self.assertEqual([p for p, _kw in self.site.inserted], [])

	def test_widens_deal_type_before_it_needs_the_option(self):
		# `overhead_deal(create=True)` writes deal_type "Overhead"; a Select that
		# does not offer it stores the value and shows an empty box.
		self.site.singles[("Accounting Dimension", _ANY_DIMENSION)] = "Tender"
		patch, _mod = self._load_patch()
		patch.execute()
		self.assertIn("Overhead", patch.DEAL_TYPE_OPTIONS)

	def test_a_second_run_changes_nothing(self):
		self.site.singles[("Accounting Dimension", _ANY_DIMENSION)] = "Tender"
		self.site.singles[("Custom Field", (("dt", "CRM Deal"), ("fieldname", "deal_type")))] = {
			"name": "CRM Deal-deal_type",
			"options": "Standard\nTender\nOverhead",
		}
		patch, _mod = self._load_patch()
		patch.execute()
		self.site.sql.clear()
		self.site.inserted.clear()
		self.site.saved.clear()
		counts = patch.execute()
		self.assertEqual(self.site.inserted, [], "a second run inserted a document")
		self.assertEqual(self.site.saved, [], "a second run saved a document")
		self.assertEqual(
			[s for s, _p in self.site.sql if s.startswith("UPDATE")], [], "a second run issued an UPDATE"
		)
		self.assertTrue(all(v == 0 for v in counts.values()), f"a second run reported {counts}")

	def test_is_registered_in_patches_txt(self):
		self.assertIn("stabler.patches.v103_tender_accounting_dimension", _read("patches.txt"))

	def _hand_made_dimension(self, fieldname: str, disabled: int = 0) -> None:
		"""A site whose CRM Deal dimension already exists under another name."""
		self.site.singles[("Accounting Dimension", _ANY_DIMENSION)] = "Ihale"
		self.site.values[("Accounting Dimension", "Ihale")] = {
			"document_type": "CRM Deal",
			"fieldname": fieldname,
			"disabled": disabled,
			"dimension_defaults": [],
		}
		_drop_dimension(self.site)
		if not disabled:
			self.site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "fieldname")] = fieldname
			self.site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "name")] = "Ihale"

	def test_checks_and_backfills_the_fieldname_the_site_actually_uses(self):
		"""R3. `make_dimension_in_accounting_doctypes` installs the fields under the
		DIMENSION's fieldname, not under ours. A patch that then asserts a hardcoded
		name throws inside `bench migrate`, which writes no Patch Log row — so every
		later migrate on that site aborts in the same place, forever.
		"""
		self._hand_made_dimension("ihale")
		patch, _mod = self._load_patch()
		for doctype in patch._REQUIRED_ON:
			self.site.metas[doctype] = _Meta(["ihale"])
		self.site.rows_matching = 1
		self.site.tables.update({"Sales Order", "Sales Order Item"})
		self.site.columns.update(
			{
				("Sales Order", "ihale"),
				("Sales Order", "custom_crm_deal"),
				("Sales Order Item", "ihale"),
			}
		)
		patch.execute()
		statements = " ".join(statement for statement, _params in self.site.sql)
		self.assertIn("ihale", statements, "the backfill wrote a column this site does not have")
		self.assertNotIn("`tender`", statements, "the backfill spelled the fieldname it expected to find")

	def test_refuses_a_disabled_dimension_by_name(self):
		"""R3. `dimension_fieldname()` filters `disabled: 0`, so every hook reads
		None and does nothing — while the patch installs 52 custom fields, prints
		zeros and reports success. erpnext refuses a second dimension on the same
		`document_type`, so there is nothing to create instead: name the action.
		"""
		self._hand_made_dimension("ihale", disabled=1)
		patch, _mod = self._load_patch()
		with self.assertRaises(_Thrown) as caught:
			patch.execute()
		self.assertIn("disabled", str(caught.exception).lower())


class TestListActiveTenders(unittest.TestCase):
	"""B3 — what a picker may offer. The rule lives here, the fields stay in crm.py."""

	FIELDS: typing.ClassVar = ["name", "organization", "lead_name", "status", "deal_type", "modified"]

	def setUp(self):
		self.site = _tender_site()
		self.site.values[("CRM Deal", "OVERHEAD-1")] = {
			"name": "OVERHEAD-1",
			"organization": "GENEL GİDER",
			"deal_type": "Overhead",
			"company": "_Test Company",
		}
		self.site.lists["CRM Deal"] = [
			{
				"name": "T-OPEN",
				"organization": "Road works",
				"deal_type": "Tender",
				"company": "_Test Company",
			},
			{"name": "T-LOST", "organization": "Bridge", "deal_type": "Tender", "company": "_Test Company"},
		]
		for name, stage in (("T-OPEN", "priced"), ("T-LOST", "lost")):
			self.site.values[("CRM Deal", name)] = {
				"company": "_Test Company",
				"deal_type": "Tender",
				"custom_tender_stage": stage,
			}
		self.site.columns.add(("CRM Deal", "deal_type"))
		self.mod = _load(self.site)

	def test_the_overhead_deal_comes_first_and_is_labelled(self):
		# It is first because it is the answer for most expenses, and it is marked
		# so the screen can say GENEL GİDER instead of a CRM autoname.
		rows, _total = self.mod.list_active_tenders("_Test Company", self.FIELDS)
		self.assertEqual(rows[0]["name"], "OVERHEAD-1")
		self.assertEqual(rows[0]["organization"], "GENEL GİDER")
		self.assertEqual(rows[0]["is_overhead"], 1)

	def test_excludes_a_lost_tender(self):
		rows, _total = self.mod.list_active_tenders("_Test Company", self.FIELDS)
		names = [r["name"] for r in rows]
		self.assertIn("T-OPEN", names)
		self.assertNotIn("T-LOST", names)

	def test_excludes_standard_deals_entirely(self):
		# 551 of the 552 deals on the test site are Standard. A picker that offered
		# them would make the ledger dimension a free-text field in practice.
		self.site.lists["CRM Deal"].append(
			{"name": "STD-1", "organization": "Shop", "deal_type": "Standard", "company": "_Test Company"}
		)
		rows, _total = self.mod.list_active_tenders("_Test Company", self.FIELDS)
		names = [r["name"] for r in rows]
		self.assertNotIn("STD-1", names)

	def test_asks_the_database_for_tenders_rather_than_filtering_552_deals(self):
		# `is_active_tender` would reject a Standard deal anyway — this pins the
		# other half, which the outcome test cannot see: the query itself must
		# narrow to tenders. Without it every one of the 551 Standard deals on the
		# test site is fetched and then thrown away, one `is_active_tender` read
		# each, on every keystroke in the picker.
		asked = {}
		original = self.mod.frappe.get_list

		def _spy(doctype, **kwargs):
			asked.update(kwargs.get("filters") or {})
			return original(doctype, **kwargs)

		self.mod.frappe.get_list = _spy
		try:
			self.mod.list_active_tenders("_Test Company", self.FIELDS)
		finally:
			self.mod.frappe.get_list = original
		self.assertEqual(asked.get("deal_type"), "Tender")
		self.assertEqual(asked.get("company"), "_Test Company")

	def test_offers_the_overhead_deal_even_when_no_tender_is_active(self):
		# The empty state still has to be usable: every expense needs SOME value,
		# and GENEL GİDER is the honest one when no tender is running.
		self.site.lists["CRM Deal"] = []
		rows, _total = self.mod.list_active_tenders("_Test Company", self.FIELDS)
		self.assertEqual([r["name"] for r in rows], ["OVERHEAD-1"])

	def test_the_page_is_cut_after_the_filter_and_not_by_the_query(self):
		"""R11. `is_active_tender` is a rule SQL cannot express, so SQL must not page.

		With the LIMIT on the query the engine hands back the first `page_length`
		RAW deals and the filter then removes some of them. Two things break at
		once: page 2 skips raw rows rather than shown ones, so a live tender the
		filter dropped on page 1 takes a real tender's place off the end of the
		list; and the overhead bucket is prepended to EVERY page. A picker that
		cannot show a running tender sends that cost to GENEL GİDER instead, and
		the expense lands under the wrong dimension for good.
		"""
		self.site.lists["CRM Deal"] = []
		for index in range(4):
			name = f"T-{index}"
			self.site.lists["CRM Deal"].append(
				{
					"name": name,
					"organization": f"Lot {index}",
					"deal_type": "Tender",
					"company": "_Test Company",
				}
			)
			self.site.values[("CRM Deal", name)] = {
				"company": "_Test Company",
				"deal_type": "Tender",
				# T-1 is lost: the row SQL returns and the filter has to remove.
				"custom_tender_stage": "lost" if index == 1 else "priced",
			}

		first, total = self.mod.list_active_tenders("_Test Company", self.FIELDS, page_length=2)
		second, second_total = self.mod.list_active_tenders(
			"_Test Company", self.FIELDS, page_length=2, start=2
		)

		self.assertEqual([r["name"] for r in first], ["OVERHEAD-1", "T-0"])
		self.assertEqual([r["name"] for r in second], ["T-2", "T-3"])
		# Not 2 (a page) and not 5 (what the query counted before the filter):
		# the picker's footer has to name what the user may actually pick.
		self.assertEqual(total, 4)
		self.assertEqual(second_total, 4)

	def test_returns_nothing_extra_for_a_company_with_no_overhead_deal(self):
		self.site.singles.pop(("CRM Deal", (("company", "_Test Company"), ("deal_type", "Overhead"))))
		rows, _total = self.mod.list_active_tenders("_Test Company", self.FIELDS)
		self.assertEqual([r["name"] for r in rows], ["T-OPEN"])


class TestWriterWiring(unittest.TestCase):
	"""B7 — the endpoints that accept a tender must all check it the same way."""

	def setUp(self):
		self.money = _code_only(_read("api", "money.py"))
		self.purchasing = _code_only(_read("api", "purchasing.py"))
		self.crm = _code_only(_read("api", "crm.py"))

	def test_the_expense_endpoint_checks_selectability_not_existence(self):
		# `frappe.db.exists` accepted a lost tender, another company's tender and a
		# Standard deal — all three post to the ledger under a dimension that has
		# to mean one thing.
		self.assertIn("assert_selectable_tender(deal, company)", self.money)

	def test_the_expense_endpoint_still_names_an_unknown_deal(self):
		self.assertIn('frappe.throw("Unknown deal.")', self.money)

	def test_the_purchase_invoice_endpoints_take_and_check_a_tender(self):
		for contract in (
			"assert_selectable_tender(",
			"def _apply_invoice_payload(",
			'"tender_locked"',
			'"tender_label"',
		):
			self.assertIn(contract, self.purchasing, f"purchasing.py is missing {contract}")

	def test_the_deal_list_excludes_the_overhead_bucket(self):
		# GENEL GİDER is a ledger bucket, not a deal. On the CRM board it would sit
		# in Qualification forever and be counted in every pipeline figure. R9: the
		# filter itself lives in `exclude_overhead_deals`, shared with the manager
		# cockpit, so the two readers cannot drift apart on what counts as a deal.
		self.assertIn("exclude_overhead_deals(filters)", self.crm)
		self.assertIn('["!=", OVERHEAD_DEAL_TYPE]', _code_only(_read("api", "tender_dimension.py")))

	def test_the_deal_list_offers_the_active_tender_mode(self):
		self.assertIn("active_tenders", self.crm)
		self.assertIn("list_active_tenders(", self.crm)

	def test_the_board_enumerations_still_select_tenders_only(self):
		# The three places that enumerate a company's tenders must keep filtering on
		# `deal_type = "Tender"`: `Overhead` is a third value now, and a board that
		# stopped filtering would show GENEL GİDER as a lot.
		tender = _code_only(_read("api", "tender.py"))
		master = _code_only(_read("api", "tender_master.py"))
		self.assertIn('"deal_type": "Tender"', tender)
		self.assertIn('"deal_type": "Tender"', master)
		self.assertNotIn('"deal_type": "Overhead"', tender)
		self.assertNotIn('"deal_type": "Overhead"', master)


class TestTranslatedStrings(unittest.TestCase):
	"""R6 — every string this module shows a user exists in all five catalogues.

	Asserted over the SOURCE rather than as a list of keys: a list has to be
	remembered, and the two strings this caught were added by the same branch that
	wrote the catalogue entries for the other six.
	"""

	#: The four offered languages plus `uzc`, which is still shipped and still
	#: translated — it left the pickers on 2026-08-28, it was not deleted.
	LANGUAGES: typing.ClassVar = ["en", "ru", "uz", "uzc", "tr"]

	def test_every_translated_string_is_in_every_catalogue(self):
		source = _read("api", "tender_dimension.py")
		keys = re.findall(r'_\(\s*"((?:[^"\\]|\\.)*)"', source)
		self.assertTrue(keys, "no translated strings found — did the call shape change?")
		catalogues = {lang: _read("translations", f"{lang}.csv") for lang in self.LANGUAGES}
		missing = [
			f"{lang}: {key}" for key in keys for lang, catalogue in catalogues.items() if key not in catalogue
		]
		self.assertEqual(missing, [], f"untranslated strings: {missing}")


class TestHooksRegistration(unittest.TestCase):
	"""A handler nobody calls is a handler that does not exist."""

	def setUp(self):
		self.hooks = _code_only(_read("hooks.py"))

	def test_the_document_hook_runs_on_every_writer_stabler_owns(self):
		for doctype in (
			"Sales Order",
			"Purchase Order",
			"Supplier Quotation",
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

	def test_no_stamp_is_wired_to_a_doctype_erpnext_gives_no_dimension_field(self):
		"""R10. Request for Quotation is not an accounting dimension doctype.

		ERPNext creates a dimension's custom field only on the doctypes named by
		its `accounting_dimension_doctypes` hook, and RFQ is not one of them —
		`Supplier Quotation` is, RFQ never was. A `stamp_tender` there sets a
		value on a field that does not exist and Frappe drops it on save: a
		handler on every RFQ write, reading as coverage the ledger never had.
		"""
		self.assertNotIn('"Request for Quotation": {', self.hooks)

	def test_the_gl_safety_net_is_registered(self):
		self.assertIn("stabler.api.tender_dimension.default_gl_tender", self.hooks)
		gl = self.hooks.split('"GL Entry": {', 1)
		self.assertEqual(len(gl), 2, "GL Entry has no doc_events block")
		self.assertIn("before_validate", gl[1].split("\n\t},", 1)[0])

	def test_turning_the_module_on_sets_the_company_up(self):
		"""Registered on the SINGLE, not on its rows.

		The first draft hooked `Stabler Company Modules`. That doctype is a child
		table (`"istable": 1`), and frappe persists child rows with `db_update()` in
		`Document.update_child_table` — their document methods are never run. A
		reviewer replaced the handler with a probe, flipped `enable_tender` on and
		saved: it fired zero times. So the flag could be turned on from the
		organization screen and the company would get no GENEL GIDER deal and no
		detail row, while `default_gl_tender` told the user to save the very screen
		that does nothing.
		"""
		self.assertIn("stabler.api.tender_dimension.on_settings_update", self.hooks)
		block = self.hooks.split('"Stabler Settings": {', 1)
		self.assertEqual(len(block), 2, "Stabler Settings has no doc_events block")
		self.assertIn("stabler.api.tender_dimension.on_settings_update", block[1].split("\n\t},", 1)[0])
		self.assertNotIn(
			"on_company_modules_update", self.hooks, "the dead child-table hook is still registered"
		)

	def test_no_doc_event_is_registered_on_a_child_table(self):
		"""The general form of the bug above, over every stabler doctype in hooks.

		A child table's handlers never run, so registering one is not a subtle
		mistake — it is a handler that silently does not exist. Only doctypes this
		repository owns can be checked; those are exactly the ones a stabler change
		can get wrong.
		"""
		offenders = []
		for doctype in re.findall(r'^\t"([A-Z][^"]*)": \{', self.hooks, re.MULTILINE):
			slug = doctype.lower().replace(" ", "_")
			schema = os.path.join(_ROOT, "stabler", "doctype", slug, f"{slug}.json")
			if not os.path.exists(schema):
				continue
			with open(schema, encoding="utf-8") as handle:
				if json.load(handle).get("istable"):
					offenders.append(doctype)
		self.assertEqual(offenders, [], f"doc_events registered on child tables: {offenders}")


class TestSettingsHook(unittest.TestCase):
	"""`on_settings_update` — what the parent save is allowed to do."""

	def setUp(self):
		self.site = _tender_site()
		self.mod = _load(self.site)
		self.calls = []
		self.mod.ensure_company_setup = lambda company: self.calls.append(company)

	def _settings(self, *rows):
		doc = _Doc("Stabler Settings")
		doc["company_modules"] = [_Row(row) for row in rows]
		return doc

	def test_sets_up_only_the_companies_whose_flag_is_on(self):
		self.mod.on_settings_update(
			self._settings(
				{"company": "_Test Company", "enable_tender": 1},
				{"company": "Plain Co", "enable_tender": 0},
			)
		)
		self.assertEqual(self.calls, ["_Test Company"])

	def test_does_nothing_on_a_site_without_the_dimension(self):
		_drop_dimension(self.site)
		self.mod.clear_dimension_cache()
		self.mod.on_settings_update(self._settings({"company": "_Test Company", "enable_tender": 1}))
		self.assertEqual(self.calls, [], "a site that never ran v103 was set up by a settings save")

	def test_re_reads_rather_than_trusting_what_it_cached_before_the_save(self):
		"""The caches answer from BEFORE the save this hook is reacting to.

		Primed here the way a real request primes them: something asked earlier in
		the same request, when the site had no dimension yet. If the hook trusts
		that answer it returns immediately and the company it was called to set up
		is never set up.
		"""
		_drop_dimension(self.site)
		self.assertIsNone(self.mod.dimension_fieldname())
		self.site.singles[("Accounting Dimension", _ENABLED_DIMENSION, "fieldname")] = "tender"
		self.mod.on_settings_update(self._settings({"company": "_Test Company", "enable_tender": 1}))
		self.assertEqual(
			self.calls,
			["_Test Company"],
			"the settings hook answered from the cache it was called to invalidate",
		)

	def test_a_nested_save_does_not_run_the_setup_twice(self):
		"""`ensure_company_setup` can save Stabler Settings itself.

		`tender_enabled` -> `module_map_for` -> `get_company_module_row` appends a
		default row and saves when a company has none, which re-enters this hook.
		Without the guard the setup runs once per nesting level, and a company whose
		row is being created is set up while its row is half-written.
		"""
		settings = self._settings({"company": "_Test Company", "enable_tender": 1})

		def _reenter(company):
			self.calls.append(company)
			self.mod.on_settings_update(settings)

		self.mod.ensure_company_setup = _reenter
		self.mod.on_settings_update(settings)
		self.assertEqual(self.calls, ["_Test Company"], "the nested save ran the setup again")


if __name__ == "__main__":
	unittest.main()
