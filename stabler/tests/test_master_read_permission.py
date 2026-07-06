"""Static guard (WP-001 + follow-up): raw-SQL master-data readers must enforce
doctype read permission.

`@frappe.whitelist()` + `_assert_company_scope` scope a call to the caller's
company, but a raw `frappe.db.sql` SELECT against a master table (`tabCustomer`,
`tabSupplier`, `tabEmployee`, `tabCRM Lead`, `tabCRM Deal`) still bypasses
Frappe's `permission_query_conditions`. A user with no read permission on the
doctype could otherwise pull master PII (name / phone / e-mail / salary hints)
via these endpoints. Every such reader must additionally call
`frappe.has_permission("<Doctype>", "read")`.

See audit_critique.md §1.1. Parsed with `ast` — no Frappe runtime needed.
"""

from __future__ import annotations

import ast
import os
import unittest

# module file -> {function name: [required has_permission needles]}
_REQUIRED: dict[str, dict[str, list[str]]] = {
	"sales.py": {
		"list_customers": ['has_permission("Customer", "read")'],
		"get_customer_defaults": ['has_permission("Customer", "read")'],
		"list_customers_with_balances": ['has_permission("Customer", "read")'],
	},
	"purchasing.py": {
		"list_suppliers": ['has_permission("Supplier", "read")'],
		"list_suppliers_with_balances": ['has_permission("Supplier", "read")'],
	},
	"hr.py": {
		"list_employees": ['has_permission("Employee", "read")'],
	},
	"crm.py": {
		"list_leads": ['has_permission("CRM Lead", "read")'],
		"list_deals": ['has_permission("CRM Deal", "read")'],
	},
	"search.py": {
		# palette_search returns Customer + Supplier master rows; both must gate.
		"palette_search": [
			'has_permission("Customer", "read")',
			'has_permission("Supplier", "read")',
		],
	},
}

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler


def _func_source(module_file: str, func_name: str) -> str:
	path = os.path.join(_APP_ROOT, "api", module_file)
	with open(path, encoding="utf-8") as fh:
		src = fh.read()
	tree = ast.parse(src)
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef) and node.name == func_name:
			return ast.get_source_segment(src, node) or ""
	return ""


class TestMasterReadPermission(unittest.TestCase):
	def test_master_readers_check_read_permission(self):
		for module_file, funcs in _REQUIRED.items():
			for func, needles in funcs.items():
				seg = _func_source(module_file, func)
				self.assertTrue(seg, f"{module_file}::{func} not found")
				for needle in needles:
					self.assertIn(
						needle,
						seg,
						f"{module_file}::{func} reads master data but never calls "
						f"frappe.{needle} — restricted users could read master PII.",
					)


if __name__ == "__main__":
	unittest.main()
