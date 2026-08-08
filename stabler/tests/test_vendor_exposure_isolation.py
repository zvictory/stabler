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
		write_pos = body.index("if (exp && exp.enabled) selectedExposure.value = exp;")
		# Bound the search to the window between the await and the write. Searching
		# from await_pos to the end of the body was vacuous: it also matched the
		# catch branch's guard, so deleting the try-branch one -- or moving it below
		# the write, which is the race itself -- kept this test green.
		self.assertIn(
			"if (!isCurrent()) return;",
			body[await_pos:write_pos],
			"the try branch must check the ticket between the await and the write to selectedExposure",
		)
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


class TestSupplierQuotationsRaceGuard(unittest.TestCase):
	"""Wiring guard (bead stabler-5cp): loadSuppQuotations carries the same
	unguarded-await race as loadExposure -- click supplier A then B and A's slow
	response paints A's quotations under B's name. Its finally clause needs the
	guard too: a stale request clearing suppQuotationsLoading would drop the
	skeleton while the current request is still in flight, so the table reads as
	loaded while showing the previous supplier's rows."""

	def setUp(self):
		src = _suppliers_vue_src()
		start = src.index("async function loadSuppQuotations(supplierName) {")
		end = src.index("\n}\n", start)
		self.body = src[start:end]
		self.on_select_src = src[
			src.index("function onSelect(row) {") : src.index("function onDetail(detail) {")
		]

	def test_takes_a_ticket_before_the_await(self):
		self.assertIn("quotationsReq.take()", self.body)
		self.assertLess(
			self.body.index("quotationsReq.take()"),
			self.body.index("await call("),
			"the ticket must be taken BEFORE the await, not after",
		)

	def test_checks_the_ticket_between_the_await_and_the_write(self):
		# Bounded window, deliberately: searching to the end of the body would also
		# match the catch and finally guards, so dropping this one would stay green.
		await_pos = self.body.index("await call(")
		write_pos = self.body.index("suppQuotations.value = res?.rows || [];")
		self.assertIn(
			"if (!isCurrent()) return;",
			self.body[await_pos:write_pos],
			"the try branch must check the ticket before writing suppQuotations",
		)

	def test_the_catch_branch_checks_it_too(self):
		# A stale request that FAILS must not blank the current supplier's rows.
		catch_pos = self.body.index("catch")
		finally_pos = self.body.index("finally")
		self.assertIn("if (!isCurrent()) return;", self.body[catch_pos:finally_pos])

	def test_a_stale_request_does_not_clear_the_loading_flag(self):
		# finally runs even after the early return above, so the flag write is the
		# one place a retired request can still reach shared state.
		finally_pos = self.body.index("finally")
		self.assertIn("if (isCurrent()) suppQuotationsLoading.value = false;", self.body[finally_pos:])

	def test_on_select_deselect_invalidates_and_clears_the_flag(self):
		self.assertIn("quotationsReq.invalidate()", self.on_select_src)
		# The retired request's finally no longer owns the flag, so the deselect
		# branch has to clear it or the skeleton spins forever.
		self.assertIn("suppQuotationsLoading.value = false;", self.on_select_src)


if __name__ == "__main__":
	unittest.main()
