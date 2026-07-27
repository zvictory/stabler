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


if __name__ == "__main__":
	unittest.main()
