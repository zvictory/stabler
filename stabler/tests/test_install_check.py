"""The post-install assertion list, and the repair it deliberately refuses.

A Patch Log row means "this patch was marked run", not "this patch did anything".
`16328bf` measured the difference: zuma's log claimed all 94 patches while 206
Custom Fields were missing. `install_check` exists to ask the site directly, and
these tests pin two things about it.

First, that it asks the right questions and says why. A report reading
"Role Stabler Declarant is missing" is not actionable; the reason it can never
appear on its own — the name is in no doctype JSON, so sync will not create it —
is the whole content.

Second, and more important, that it stays a *reader*. The obvious repair is to
call every patch module's `execute()` after setup, and that is the single most
dangerous instruction in this area: `v80` rewrote live supplier advances, and
`v62`/`v63`/`v64`/`v65` reversed operator decisions, precisely by being run a
second time. A checker that grows a repair mode becomes the thing it was written
to protect against, so the test reads the module's own source and refuses it.
"""

from __future__ import annotations

import ast
import os
import unittest

from stabler import install_check

_MODULE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "install_check.py")
with open(_MODULE, encoding="utf-8") as _fh:
	_SOURCE = _fh.read()


class TheListSaysWhatIsMissingAndWhy(unittest.TestCase):
	def test_a_complete_site_reports_nothing(self):
		present = {k: True for k in _all_keys()}
		self.assertEqual(install_check.missing(install_check._EXPECTATIONS, present), [])

	def test_a_missing_artifact_names_the_patch_that_owed_it(self):
		present = {k: True for k in _all_keys()}
		present[("doc", "Role", "Stabler Declarant")] = False
		gaps = install_check.missing(install_check._EXPECTATIONS, present)
		self.assertEqual([g["label"] for g in gaps], ['Role "Stabler Declarant"'])
		self.assertEqual(gaps[0]["patch"], "v38_tender_view_roles")

	def test_a_tax_template_is_reported_per_company_not_once(self):
		"""v05 names templates `<title> - <abbr>`, so the gap is per tenant.

		Reporting it once would send the operator to look at whichever company
		they happened to think of first.
		"""
		present = {k: True for k in _all_keys()}
		present[("per_company", "Uzbekistan NDS 12%", "Mikas")] = False
		gaps = install_check.missing(install_check._EXPECTATIONS, present)
		self.assertEqual(len(gaps), 1)
		self.assertIn("Mikas", gaps[0]["label"])
		self.assertTrue(gaps[0]["soft"], "v05 legitimately skips a company with no tax account")

	def test_every_expectation_carries_a_patch_and_a_consequence(self):
		"""An entry with no `why` is a line the operator cannot act on."""
		for exp in install_check._EXPECTATIONS:
			with self.subTest(exp=exp.get("name") or exp.get("title")):
				self.assertTrue(exp.get("patch"))
				self.assertGreater(len(exp.get("why", "")), 30)

	def test_the_two_items_the_import_hooks_bill_against_are_both_asserted(self):
		"""These are the two whose absence stops a hook silently, not loudly."""
		items = {
			e["name"] for e in install_check._EXPECTATIONS if e["kind"] == "doc" and e["doctype"] == "Item"
		}
		self.assertEqual(items, {"Cross-Border Transport", "Import Service"})


class ItMustNeverBecomeTheRepair(unittest.TestCase):
	def test_it_never_imports_or_calls_a_patch_module(self):
		"""Bulk-running patches is what this report exists to talk people out of."""
		tree = ast.parse(_SOURCE)
		for node in ast.walk(tree):
			if isinstance(node, ast.Import):
				for alias in node.names:
					self.assertNotIn("patches", alias.name)
			if isinstance(node, ast.ImportFrom):
				self.assertNotIn("patches", node.module or "")

	def test_it_does_not_need_frappe_to_be_imported(self):
		"""The pure half must load on a machine with no bench.

		This gates `make check`, which runs without one — and the fix that made
		that true is the reason: pushing a stub `frappe` into `sys.modules` at
		import time turned six unrelated bench modules red, because discovery
		imports a test module without running it and so nothing ever undid the
		stub. Keeping the import inside the two functions that need it removes
		the need for a sandbox entirely.
		"""
		tree = ast.parse(_SOURCE)
		for node in tree.body:
			if isinstance(node, ast.Import):
				self.assertNotIn("frappe", [a.name for a in node.names])
			if isinstance(node, ast.ImportFrom):
				self.assertNotIn("frappe", (node.module or ""))

	def test_it_writes_nothing(self):
		"""Read-only in the literal sense: no insert, no save, no set_value, no DDL."""
		forbidden = ("set_value", "insert", "save", "delete_doc", "sql_ddl", "new_doc", "get_doc")
		tree = ast.parse(_SOURCE)
		called = {
			node.func.attr
			for node in ast.walk(tree)
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
		}
		self.assertEqual(called & set(forbidden), set())

	def test_the_report_tells_the_operator_not_to_bulk_run(self):
		"""The warning is the deliverable; a report that omits it invites the repair."""
		self.assertIn("Do NOT bulk-run patch modules", _SOURCE)


def _all_keys():
	keys = []
	for exp in install_check._EXPECTATIONS:
		if exp["kind"] == "doc":
			keys.append(("doc", exp["doctype"], exp["name"]))
		elif exp["kind"] == "index":
			keys.append(("index", exp["name"]))
		else:
			for company in ("Mikas", "Anjan"):
				keys.append(("per_company", exp["title"], company))
	return keys


if __name__ == "__main__":
	unittest.main()
