"""Static guard (WP-001): raw-SQL master-data readers must enforce doctype read
permission.

`@frappe.whitelist()` + `_assert_company_scope` scope a call to the caller's
company, but a raw `frappe.db.sql` SELECT against a master table (`tabCustomer`,
`tabSupplier`) still bypasses Frappe's `permission_query_conditions`. A user with
no read permission on the doctype could otherwise pull the master PII
(phone / e-mail) for their own company. Every such reader must additionally call
`frappe.has_permission("<Doctype>", "read")`.

See audit_critique.md §1.1. Parsed with `ast` — no Frappe runtime needed.
"""

from __future__ import annotations

import ast
import os
import unittest

# function -> (raw master table it selects, doctype it must permission-check)
_REQUIRED: dict[str, tuple[str, str]] = {
	"list_customers":        ("tabCustomer", "Customer"),
	"get_customer_defaults": (None, "Customer"),
	"list_suppliers":        ("tabSupplier", "Supplier"),
}

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler


def _source_of(func_name: str) -> str:
	for mod in ("sales.py", "purchasing.py"):
		path = os.path.join(_APP_ROOT, "api", mod)
		with open(path, encoding="utf-8") as fh:
			src = fh.read()
		tree = ast.parse(src)
		for node in ast.walk(tree):
			if isinstance(node, ast.FunctionDef) and node.name == func_name:
				return ast.get_source_segment(src, node) or ""
	return ""


class TestMasterReadPermission(unittest.TestCase):
	def test_master_readers_check_read_permission(self):
		for func, (_table, doctype) in _REQUIRED.items():
			seg = _source_of(func)
			self.assertTrue(seg, f"{func} not found in api/sales.py or api/purchasing.py")
			needle = f'has_permission("{doctype}", "read")'
			self.assertIn(
				needle,
				seg,
				f"{func} reads {doctype} master data but never calls "
				f'frappe.{needle} — restricted users could read master PII.',
			)


if __name__ == "__main__":
	unittest.main()
