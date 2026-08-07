"""Static guard (WP-I4): the import-exposure block must stay tenant-isolated.

The base Vendor Center payload (``supplier_detail``) must be BYTE-for-byte the
same for tenants without the imports module — the exposure lives in a SEPARATE,
enable_imports-gated endpoint (``supplier_import_exposure``). This test fails if
someone folds exposure logic into ``supplier_detail`` (which would run for every
tenant) or drops the module gate from the exposure endpoint.
"""

from __future__ import annotations

import ast
import os
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PURCHASING = os.path.join(_APP_ROOT, "api", "purchasing.py")
_SUPPLIERS_VUE = os.path.join(_APP_ROOT, "public", "js", "pages", "purchasing", "Suppliers.vue")


def _suppliers_vue_src() -> str:
	with open(_SUPPLIERS_VUE, encoding="utf-8") as fh:
		return fh.read()


def _func_src(name: str) -> str:
	with open(_PURCHASING, encoding="utf-8") as fh:
		text = fh.read()
	tree = ast.parse(text)
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(text, node) or ""
	return ""


class TestVendorExposureIsolation(unittest.TestCase):
	def test_supplier_detail_has_no_exposure_logic(self):
		seg = _func_src("supplier_detail")
		self.assertTrue(seg, "supplier_detail not found")
		for forbidden in ("_import_exposure", "exposure", "module_map_for", "Commercial Invoice"):
			self.assertNotIn(
				forbidden,
				seg,
				f"supplier_detail must not reference '{forbidden}' — import exposure "
				"belongs in the separate gated supplier_import_exposure endpoint.",
			)

	def test_exposure_endpoint_is_module_gated(self):
		seg = _func_src("supplier_import_exposure")
		self.assertTrue(seg, "supplier_import_exposure not found")
		self.assertIn(
			'module_map_for(company).get("imports")', seg, "exposure endpoint must gate on enable_imports"
		)
		self.assertIn('"enabled": False', seg, "exposure endpoint must return an inert payload when disabled")


class TestSupplierExposureRaceGuard(unittest.TestCase):
	"""Wiring guard (bead stabler-waz): loadExposure must not let a slow response
	for a previously-selected supplier overwrite the currently-selected one, and
	the tenant gate (C1) must survive that fix untouched."""

	def setUp(self):
		src = _suppliers_vue_src()
		start = src.index("async function loadExposure(supplierName) {")
		# The function body is one tab deeper than its own declaration; its close
		# is the next line that is exactly a single closing brace.
		end = src.index("\n}\n", start)
		self.load_exposure_src = src[start:end]
		self.on_select_src = src[
			src.index("function onSelect(row) {") : src.index("function onDetail(detail) {")
		]

	def test_load_exposure_takes_a_ticket_before_the_await(self):
		body = self.load_exposure_src
		self.assertIn("exposureReq.take()", body, "loadExposure must take a ticket before its await")
		ticket_pos = body.index("exposureReq.take()")
		await_pos = body.index("await call(")
		self.assertLess(ticket_pos, await_pos, "the ticket must be taken BEFORE the await, not after")

	def test_load_exposure_checks_the_ticket_after_the_await_in_both_branches(self):
		body = self.load_exposure_src
		await_pos = body.index("await call(")
		try_check_pos = body.index("if (!isCurrent()) return;", await_pos)
		self.assertGreater(try_check_pos, await_pos, "the try branch must check the ticket after the await")
		catch_pos = body.index("catch")
		self.assertIn(
			"if (!isCurrent()) return;",
			body[catch_pos:],
			"a stale request that fails must not null out the current supplier's figures",
		)

	def test_on_select_deselect_invalidates_in_flight_requests(self):
		self.assertIn(
			"exposureReq.invalidate()",
			self.on_select_src,
			"onSelect's deselect branch must invalidate in-flight exposure requests",
		)

	def test_tenant_gate_survives_the_race_fix(self):
		self.assertIn(
			"if (exp && exp.enabled) selectedExposure.value = exp;",
			self.load_exposure_src,
			"the client-side tenant gate (C1) must stay exactly as it was",
		)


if __name__ == "__main__":
	unittest.main()
