"""Queue item 14: the one doctype change the idempotency board voted to spend.

`/money/expenses` and `/money/transfers` hand an operator a filled form and a
failed request at the same time (`Expenses.vue:710-713` keeps the form on
screen). Clicking Submit again posts a second Journal Entry with the same
lines, the same `cheque_no = f"Exp-{posting_date}"` — which every expense that
day already shares, so it is not a key — and nothing but a serial number tells
the two vouchers apart. The board rejected a payload fingerprint
(`company, posting_date, payment_from, base_total, payee`): two identical cash
expenses on one day are legitimate, and a guard that refuses them teaches
operators to work around it. What is left is an identity carrier the caller
supplies once and repeats on retry, and a unique index that turns the second
insert into a no-op.

This test locks the shape of that field. No bench, no DB — the unique index
itself is only provable against a live site, and the commit says so.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "patches" / "v96_money_idempotency_key.py"
PATCHES_TXT = ROOT / "patches.txt"
FIELDNAME = "custom_idempotency_key"


def _assignments() -> dict[str, ast.expr]:
	"""Module-level `NAME = <expr>` nodes in the patch, by name."""
	tree = ast.parse(PATCH_PATH.read_text(encoding="utf-8"))
	return {
		node.targets[0].id: node.value
		for node in tree.body
		if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
	}


def _as_dict(node: ast.Dict, base: dict) -> dict:
	"""One field spec, resolving the single `**_FIELD` spread the patch uses.

	Read statically on purpose: the patch imports frappe at module level, and
	`make check` runs on a machine that has no bench to import it from.
	"""
	out: dict = {}
	for key, value in zip(node.keys, node.values, strict=True):
		if key is None:  # `**_FIELD`
			out.update(base)
			continue
		out[key.value] = value.value if isinstance(value, ast.Constant) else value
	return out


def _field_specs() -> dict[str, list[dict]]:
	"""{doctype: [field spec, ...]} as the patch declares them."""
	assigns = _assignments()
	base = _as_dict(assigns["_FIELD"], {})
	fields = assigns["_FIELDS"]
	return {
		dt.value: [_as_dict(spec, base) for spec in lst.elts]
		for dt, lst in zip(fields.keys, fields.values, strict=True)
	}


class TheFieldExistsOnBothMoneyDoctypes(unittest.TestCase):
	"""One field, two doctypes. A Journal Entry and a Payment Entry are two
	different ways for the same double-click to hit the ledger, and the queue
	item bought both at once precisely so a second migration would not be
	needed for the half that got left out."""

	def test_journal_entry_and_payment_entry_both_carry_it(self):
		specs = _field_specs()
		self.assertEqual(set(specs), {"Journal Entry", "Payment Entry"})
		for doctype, rows in specs.items():
			names = [r.get("fieldname") for r in rows]
			self.assertIn(FIELDNAME, names, f"{doctype} has no idempotency key")


class TheIndexIsWhatActuallyGuards(unittest.TestCase):
	"""`unique: 1` is not a nicety here — it IS the guard.

	The server-side check reads the field before inserting, but two requests
	from one double-click can both read "not there" and both proceed. Only the
	index decides which of them wins; the loser gets an IntegrityError the API
	turns back into the winner's document. Drop `unique` and the guard degrades
	to a race that is lost exactly when it matters — under the slow response
	that made the operator click twice in the first place.
	"""

	def test_the_field_is_declared_unique_on_both(self):
		for doctype, rows in _field_specs().items():
			spec = next(r for r in rows if r.get("fieldname") == FIELDNAME)
			self.assertEqual(spec.get("unique"), 1, f"{doctype}: idempotency key is not unique")

	def test_it_is_a_data_field(self):
		for doctype, rows in _field_specs().items():
			spec = next(r for r in rows if r.get("fieldname") == FIELDNAME)
			self.assertEqual(spec.get("fieldtype"), "Data", doctype)


class ADefaultWouldDestroyTheIndexAndTheMigration(unittest.TestCase):
	"""The field must declare NO default, and the damage is at migrate time.

	A `default` reaches the DDL as `ADD COLUMN ... DEFAULT ''`
	(`frappe/database/schema.py:255-256`), which stamps every existing row with
	the empty string before the `ADD UNIQUE INDEX` runs. Measured against this
	engine: a unique key accepts any number of NULLs and exactly one empty
	string, so the index build dies with a 1062 on the second Journal Entry —
	the migrate fails on every populated tenant, which is all seven.

	It is specifically NOT an insert-time hazard: frappe converts a blank value
	on a unique field to None before writing
	(`frappe/model/base_document.py:555-558`), so a writer passing "" is safe.
	That protection does not reach backwards over rows the ALTER filled in.

	`test_patch_custom_field_defaults` will not catch this — it refuses only
	non-string defaults, for the unrelated `format_value` reason, and "" is a
	string.
	"""

	def test_no_default_is_declared(self):
		for doctype, rows in _field_specs().items():
			spec = next(r for r in rows if r.get("fieldname") == FIELDNAME)
			self.assertNotIn(
				"default",
				spec,
				f"{doctype}: a default on a unique Data field collides on the second unset row",
			)


class ThePatchRunsAfterTheDoctypeSync(unittest.TestCase):
	"""Registered under [post_model_sync], like every other Custom Field patch.

	Journal Entry and Payment Entry are ERPNext doctypes; their tables exist
	before this patch runs either way. What post-sync buys is the ordering the
	rest of the file already assumes, and it is the section five sibling
	docstrings were corrected to stop misdescribing.
	"""

	def test_it_is_registered_after_the_post_model_sync_marker(self):
		lines = [ln.strip() for ln in PATCHES_TXT.read_text(encoding="utf-8").splitlines()]
		entry = "stabler.patches.v96_money_idempotency_key"
		self.assertIn(entry, lines, "the patch is not registered at all")
		self.assertGreater(lines.index(entry), lines.index("[post_model_sync]"))


class InstallCheckAssertsTheFieldItself(unittest.TestCase):
	"""A Patch Log row is not evidence the field exists — zuma proved that.

	206 Custom Fields were missing on a site whose Patch Log claimed all 94
	patches applied. This field fails silently in exactly that state: every
	writer guards with `has_field`, so a site without the column simply stops
	deduping and says nothing. `install_check` is where that question gets
	asked out loud.
	"""

	def test_both_fields_are_named_in_the_expectations(self):
		from stabler.install_check import _EXPECTATIONS

		asserted = {
			(e.get("doctype"), e.get("fieldname")) for e in _EXPECTATIONS if e["kind"] == "custom_field"
		}
		self.assertEqual(asserted, {("Journal Entry", FIELDNAME), ("Payment Entry", FIELDNAME)})

	def test_the_expectations_name_the_patch_that_creates_them(self):
		from stabler.install_check import _EXPECTATIONS

		for exp in _EXPECTATIONS:
			if exp["kind"] == "custom_field":
				self.assertEqual(exp["patch"], "v96_money_idempotency_key")


if __name__ == "__main__":
	unittest.main()
