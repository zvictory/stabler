"""v102 against the real Property Setter, the real meta, and a real sub-assembly.

The frappe-free half of this feature (`test_work_order_multi_level_default.py`)
can prove that the patch writes the right key and that the assignment in
`create_work_order` sits before the BOM is read. It cannot prove the only two
things that decide whether anjan's operators stop being handed the wrong
materials:

  * that a Property Setter with this key actually changes what
    `frappe.new_doc("Work Order")` hands back — the whole design rests on
    `frappe.new_doc` reading the same doctype meta ERPNext's BOM dialog reads
    (`bom.py:232-241`), and a row written against `DocType` instead of
    `DocField` is a valid row that `meta.py:437-444` applies to the doctype
    rather than to the field, i.e. one nothing reads;
  * that a Work Order created through `create_work_order` requires the
    sub-assembly itself rather than the sub-assembly's raw materials. That is a
    property of `required_items`, not of the stored flag: put the assignment
    after `get_items_and_operations_from_bom()` and the record stores
    `use_multi_level_bom = 0` while carrying the exploded list, because
    `reset_use_multi_level_bom` returns early on a new document
    (`work_order.py:405-406`) and `validate` only refreshes quantities once
    `required_items` is populated (`work_order.py:217-220`).

The mechanism itself: `work_order.py:1558-1560` passes
`fetch_exploded=self.use_multi_level_bom` into `get_bom_items_as_dict`, and
`bom.py:1427` (`if cint(fetch_exploded):`) then reads `BOM Explosion Item`
instead of `BOM Item`.

Measured on anjan, read-only, 2026-09-03: 197 of 4 271 Work Orders carry 1, 167
of them submitted, the most recent 2026-09-02 09:31; 130 of those 167 sit on a
BOM containing a sub-assembly, so the flag really did change what the shop floor
was asked to issue.

Needs a site, so it is deliberately NOT in `.github/frappe-free-tests.txt` —
the Makefile derives the bench set as everything that list does not name:

    bench --site <site> run-tests --module stabler.tests.test_work_order_multi_level_default_bench

Site state: everything this module creates — the Property Setter the patch owns,
three Items and two submitted BOMs — is registered with `addClassCleanup` at the
moment it is created, not in a `tearDownClass`. unittest skips `tearDownClass`
entirely when `setUpClass` raises, and this `setUpClass` deletes a real row
before it does anything that can fail; a teardown that does not run on the
failure path is how a test permanently deletes a site's configuration.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import today

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # newer frappe
	from frappe.tests import IntegrationTestCase as FrappeTestCase

from stabler.api.manufacturing import create_work_order
from stabler.patches.v102_work_order_multi_level_bom_default import execute as v102

_SETTER_KEY = {
	"doc_type": "Work Order",
	"field_name": "use_multi_level_bom",
	"property": "default",
}


def _clear_work_order_meta() -> None:
	"""Evict BOTH caches a changed default has to get past.

	`frappe.clear_cache(doctype=...)` drops the doctype's meta but NOT
	`frappe.local.new_doc_templates` — only the no-arg "everything" branch resets
	that (`cache_manager.py:299`). `frappe.new_doc` returns a deepcopy of that
	per-process template (`create_new.py:18-24`), so a template built earlier in
	this run keeps handing out the old default however many times the meta is
	cleared.

	In production this is not a concern: `frappe.local` is per request, so no
	request ever reuses another's template. It matters only here, because one
	process runs this whole file back to back and unittest orders classes by
	name — `TheApiRequiresTheSubAssemblyItself` runs first and populates the
	template with ERPNext's default of 1, and without this pop the assertion in
	`ThePatchIsSafeToRunTwice` would read that stale template and fail with a
	message telling the next reader to go redesign a fix that works.
	"""
	frappe.clear_cache(doctype="Work Order")
	frappe.local.new_doc_templates.pop("Work Order", None)


# --------------------------------------------------------------------------- #
# Property Setter save/restore — this module must not decide the site's default
# --------------------------------------------------------------------------- #
def _setter_rows() -> list[dict]:
	return frappe.get_all(
		"Property Setter",
		filters=_SETTER_KEY,
		fields=["name", "value", "property_type", "doctype_or_field"],
	)


def _snapshot_setter() -> list[dict]:
	rows = _setter_rows()
	_drop_setter()
	return rows


def _drop_setter() -> None:
	for row in _setter_rows():
		frappe.delete_doc("Property Setter", row["name"], force=True, ignore_permissions=True)
	frappe.db.commit()
	_clear_work_order_meta()


def _restore_setter(rows: list[dict]) -> None:
	_drop_setter()
	for row in rows:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": row["doctype_or_field"],
				"property_type": row["property_type"],
				"value": row["value"],
				**_SETTER_KEY,
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()
	_clear_work_order_meta()


# --------------------------------------------------------------------------- #
# A two-level BOM, built here rather than assumed: no fixture in this repo makes
# one, and the whole point is a BOM whose item list contains something produced
# by its own Work Order.
# --------------------------------------------------------------------------- #
def _a_company() -> str:
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		raise unittest.SkipTest("no Company on this site")
	return company


def _a_warehouse(company: str) -> str:
	warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	if not warehouse:
		raise unittest.SkipTest(f"no leaf Warehouse under {company}")
	return warehouse


def _make_item(code: str, company: str, warehouse: str) -> str:
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": frappe.db.get_value("UOM", {"name": "Nos"}, "name") or "Nos",
			"is_stock_item": 1,
			# A rate the BOM can price itself from; a zero-valued BOM only
			# msgprints, but a priced one keeps the noise out of the log.
			"valuation_rate": 100,
			"item_defaults": [{"company": company, "default_warehouse": warehouse}],
		}
	).insert(ignore_permissions=True)
	return code


def _delete_item(code: str) -> None:
	frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
	frappe.db.commit()


def _make_bom(item: str, company: str, rows: list[dict]) -> str:
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": item,
			"company": company,
			"currency": frappe.db.get_value("Company", company, "default_currency"),
			"quantity": 1,
			"is_active": 1,
			"is_default": 1,
			"items": rows,
		}
	)
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name


def _delete_bom(name: str) -> None:
	"""Cancel then delete. A submitted BOM cannot be deleted, and a BOM left
	behind per run is how a throwaway test site grows without bound."""
	doc = frappe.get_doc("BOM", name)
	if doc.docstatus == 1:
		doc.cancel()
	frappe.delete_doc("BOM", name, force=True, ignore_permissions=True)
	frappe.db.commit()


class ThePatchIsSafeToRunTwice(FrappeTestCase):
	"""One key, one row, whatever a site started from.

	A patch runs a second time more often than Frappe's Patch Log suggests: a
	site restored from backup, or an operator repairing a tenant by hand (16328bf
	— zuma's log claimed 94 patches applied while 206 Custom Fields were missing).
	Two Property Setters on the same key is not a cosmetic duplicate: Frappe reads
	one of them, and which one is not something this code gets to choose.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._saved = _snapshot_setter()
		cls.addClassCleanup(_restore_setter, cls._saved)

	def test_two_runs_leave_exactly_one_setter_holding_zero(self):
		# From empty, whatever a sibling test left behind: `execute()` commits, so
		# these tests are not isolated from each other by the usual rollback, and
		# "the first run creates it" has to be the first run against nothing.
		_drop_setter()

		v102()
		after_first = _setter_rows()
		v102()
		after_second = _setter_rows()

		self.assertEqual(
			len(after_first),
			1,
			f"the first run must create exactly one Property Setter, found {after_first!r}",
		)
		self.assertEqual(
			len(after_second),
			1,
			"the second run duplicated the Property Setter; Frappe would then read "
			f"whichever row it happened to find first: {after_second!r}",
		)
		self.assertEqual(after_second[0]["value"], "0")
		self.assertEqual(
			after_second[0]["property_type"],
			"Text",
			"Customize Form writes `default` as Text (customize_form.py:800); a row "
			"typed otherwise is the shape nobody else in Frappe produces",
		)
		self.assertEqual(
			after_second[0]["doctype_or_field"],
			"DocField",
			"meta.py:437-444 applies a setter to a field only when the row says "
			"DocField; a DocType row sets a property on the doctype instead",
		)

	def test_the_patch_repairs_a_doctype_row_the_meta_would_ignore(self):
		"""The realistic non-empty starting state, and the one that fails silently.

		A row in this same autoname slot carrying `doctype_or_field = "DocType"`
		is found by the patch's lookup, so a repair that compares only value and
		property_type rewrites it to "0", reports success, and changes nothing —
		`meta.py:437-444` never applies a DocType row to a field. Idempotency must
		not mean "a row exists, leave it": the row has to end up holding this
		decision in the shape that is read.
		"""
		_drop_setter()
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocType",
				"property_type": "Int",
				"value": "1",
				**_SETTER_KEY,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		v102()

		rows = _setter_rows()
		self.assertEqual(len(rows), 1, f"expected one row after repair, found {rows!r}")
		self.assertEqual(rows[0]["value"], "0")
		self.assertEqual(rows[0]["property_type"], "Text")
		self.assertEqual(rows[0]["doctype_or_field"], "DocField")

	def test_the_setter_actually_changes_what_a_new_work_order_says(self):
		"""The claim the whole design rests on, and the one a same-process probe
		gets wrong: meta is cached for the life of a worker, so a setter written
		and read back in one breath appears to have done nothing. Reading with
		`cached=False` asks the database the question the next fresh process will
		ask, which is the only reading that predicts what an operator sees.
		"""
		v102()

		field = frappe.get_meta("Work Order", cached=False).get_field("use_multi_level_bom")
		self.assertEqual(
			field.default,
			"0",
			"the Property Setter did not reach the doctype meta, so ERPNext's BOM "
			"dialog still opens with the box ticked",
		)

		# Both caches, not just the meta — see _clear_work_order_meta. Without the
		# template eviction this assertion reads a copy built by an earlier class
		# in this same process and fails for a reason that has nothing to do with
		# the patch.
		_clear_work_order_meta()
		self.assertEqual(
			frappe.new_doc("Work Order").use_multi_level_bom,
			0,
			"frappe.new_doc still hands out ERPNext's default of 1 — the setter "
			"path is wrong and the fix belongs in a before_insert hook instead",
		)


class TheApiRequiresTheSubAssemblyItself(FrappeTestCase):
	"""The materials, not the flag — deliberately with NO Property Setter.

	Dropping the setter for this class is what makes the assertion about
	`create_work_order` and not about site configuration. With the meta default
	back at ERPNext's 1, the only thing standing between the operator and a
	list of flour, sugar and milk is the explicit assignment in the API, placed
	before the BOM is read.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._saved = _snapshot_setter()
		# Registered before anything that can raise. setUpClass deletes a real row
		# first, and unittest runs no tearDownClass when setUpClass throws — a
		# SkipTest from _a_company below would otherwise leave the site's default
		# permanently deleted.
		cls.addClassCleanup(_restore_setter, cls._saved)

		cls.company = _a_company()
		cls.warehouse = _a_warehouse(cls.company)
		suffix = frappe.generate_hash(length=8)

		# Each cleanup is registered as soon as its object exists, so a failure
		# half way through this fixture still unwinds what was already created.
		# addClassCleanup is LIFO, which puts the BOMs before the Items they
		# reference, and the finished-goods BOM before the sub-assembly BOM it
		# links to.
		cls.leaf = _make_item(f"_MLB Leaf {suffix}", cls.company, cls.warehouse)
		cls.addClassCleanup(_delete_item, cls.leaf)
		cls.sub = _make_item(f"_MLB Mix {suffix}", cls.company, cls.warehouse)
		cls.addClassCleanup(_delete_item, cls.sub)
		cls.finished = _make_item(f"_MLB Cone {suffix}", cls.company, cls.warehouse)
		cls.addClassCleanup(_delete_item, cls.finished)

		# The mix is made from the leaf material and has a Work Order of its own.
		cls.sub_bom = _make_bom(cls.sub, cls.company, [{"item_code": cls.leaf, "qty": 2}])
		cls.addClassCleanup(_delete_bom, cls.sub_bom)
		# The cone consumes the mix. `bom_no` on the row is what makes ERPNext
		# able to explode it — i.e. what makes this test able to fail.
		cls.fg_bom = _make_bom(
			cls.finished,
			cls.company,
			[{"item_code": cls.sub, "qty": 1, "bom_no": cls.sub_bom}],
		)
		cls.addClassCleanup(_delete_bom, cls.fg_bom)
		frappe.db.commit()

	def test_the_fixture_really_is_two_levels(self):
		"""Without this, a BOM that failed to link its sub-assembly would make
		the real assertion below pass for the one reason that proves nothing:
		there was never anything to explode."""
		exploded = {row.item_code for row in frappe.get_doc("BOM", self.fg_bom).exploded_items}
		self.assertIn(
			self.leaf,
			exploded,
			"the finished-goods BOM does not explode into the leaf material, so "
			"single-level and multi-level would produce the same list",
		)

	def test_a_created_work_order_asks_for_the_mix_not_its_ingredients(self):
		"""anjan's actual complaint, in one assertion.

		The mix is produced by its own Work Order. An order that consumes it must
		require one line of mix; requiring the mix's flour and sugar instead asks
		the shop floor to issue material that has already been consumed once.
		"""
		# The API builds its document with frappe.new_doc, so the per-process
		# template decides what default it starts from. Evicting it here is what
		# makes this test run against ERPNext's 1 rather than against whatever a
		# sibling test happened to cache.
		_clear_work_order_meta()

		created = create_work_order(
			company=self.company,
			production_item=self.finished,
			qty=1,
			bom_no=self.fg_bom,
			planned_start_date=today(),
			fg_warehouse=self.warehouse,
			wip_warehouse=self.warehouse,
			source_warehouse=self.warehouse,
		)
		self.addCleanup(frappe.delete_doc, "Work Order", created["name"], force=True, ignore_permissions=True)
		doc = frappe.get_doc("Work Order", created["name"])
		required = {row.item_code for row in doc.required_items}

		self.assertIn(
			self.sub,
			required,
			f"the sub-assembly is not on the order at all; required_items = {sorted(required)!r}",
		)
		self.assertNotIn(
			self.leaf,
			required,
			"the sub-assembly was exploded into its raw materials. Either the "
			"assignment in create_work_order is missing, or it runs after "
			"get_items_and_operations_from_bom() — in which case the stored flag "
			"reads 0 and lies, because a new document never re-derives the list "
			f"(work_order.py:405-406). required_items = {sorted(required)!r}",
		)
		self.assertEqual(
			doc.use_multi_level_bom,
			0,
			"the stored flag disagrees with the materials, which means a later "
			"edit of this order would re-explode it",
		)


if __name__ == "__main__":
	unittest.main()
