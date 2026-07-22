import ast
import inspect
import textwrap

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api import imports
from stabler.stabler.imports_module import packing_service


class CIPackingGrnIntegrationTest(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		self.item = frappe.db.get_value("Item", {"disabled": 0}, "name")
		if not all((self.company, self.supplier, self.item)):
			self.skipTest("Company, Supplier and Item fixtures are required")
		settings = frappe.get_single("Stabler Settings")
		module = next(
			(row for row in settings.company_modules or [] if row.company == self.company),
			None,
		)
		module = module or settings.append("company_modules", {"company": self.company})
		module.enable_imports = 1
		settings.save(ignore_permissions=True)
		source_company = frappe.get_doc("Company", self.company)
		company_suffix = frappe.generate_hash(length=6)
		self.other_company = frappe.new_doc("Company")
		self.other_company.update(
			{
				"company_name": f"Packing Test {company_suffix}",
				"abbr": company_suffix[:5].upper(),
				"default_currency": source_company.default_currency,
				"country": source_company.country,
				"create_chart_of_accounts_based_on": "Standard Template",
			}
		)
		self.other_company.insert(ignore_permissions=True)
		self.ci = frappe.new_doc("Commercial Invoice")
		self.ci.update(
			{
				"company": self.company,
				"supplier": self.supplier,
				"ci_number": frappe.generate_hash(length=10),
				"ci_date": frappe.utils.today(),
			}
		)
		self.ci.append(
			"items",
			{"item": self.item, "qty": 300, "boxes": 15, "box_weight_kg": 20},
		)
		self.ci.insert(ignore_permissions=True)
		self.containers = []
		for suffix, boxes, kg in (("A", 10, 200), ("B", 5, 100)):
			container = frappe.new_doc("Import Container")
			container.update(
				{
					"company": self.company,
					"commercial_invoice": self.ci.name,
					"container_number": f"TEST-{suffix}-{frappe.generate_hash(length=6)}",
				}
			)
			container.append(
				"items",
				{
					"item_code": self.item,
					"box_qty": boxes,
					"box_kg": 20,
					"total_kg": kg,
				},
			)
			container.insert(ignore_permissions=True)
			self.containers.append(container)
		self.container_1, self.container_2 = self.containers

	def tearDown(self):
		frappe.db.rollback()

	def test_ci_payload_aggregates_only_same_company_linked_containers(self):
		other_ci = frappe.copy_doc(self.ci)
		other_ci.ci_number = frappe.generate_hash(length=10)
		other_ci.insert(ignore_permissions=True)
		other = frappe.new_doc("Import Container")
		other.update(
			{
				"company": self.company,
				"commercial_invoice": other_ci.name,
				"container_number": f"OTHER-{frappe.generate_hash(length=6)}",
			}
		)
		other.append(
			"items",
			{
				"item_code": self.item,
				"box_qty": 50,
				"box_kg": 20,
				"total_kg": 1000,
			},
		)
		other.insert(ignore_permissions=True)
		foreign = frappe.new_doc("Import Container")
		foreign.update(
			{
				"company": self.other_company.name,
				"commercial_invoice": self.ci.name,
				"container_number": f"FOREIGN-{frappe.generate_hash(length=6)}",
			}
		)
		foreign.append(
			"items",
			{
				"item_code": self.item,
				"box_qty": 50,
				"box_kg": 20,
				"total_kg": 1000,
			},
		)
		foreign.insert(ignore_permissions=True)

		payload = imports.get_commercial_invoice(self.ci.name)

		self.assertEqual(payload["packing_summary"]["status"], "Ready")
		self.assertEqual(
			payload["packing_summary"]["expected_items"][0]["expected_total_kg"],
			300.0,
		)
		self.assertIsNone(payload["grn"])

	def test_secondary_parent_reads_use_permission_aware_queries(self):
		service_source = inspect.getsource(packing_service.summary_for_ci)
		service_calls = _frappe_calls(packing_service.summary_for_ci)
		endpoint_calls = _frappe_calls(imports.get_commercial_invoice)

		self.assertIn(("get_list", "Import Container"), service_calls)
		self.assertNotIn(("get_all", "Import Container"), service_calls)
		self.assertIn("limit_page_length=0", service_source)
		self.assertNotIn("limit=1000", service_source)
		self.assertIn(("get_list", "GRN Checklist"), endpoint_calls)
		self.assertNotIn(("db.get_value", "GRN Checklist"), endpoint_calls)


def _frappe_calls(function) -> set[tuple[str, str]]:
	tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
	calls = set()
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call) or not node.args:
			continue
		doctype = node.args[0]
		if not isinstance(doctype, ast.Constant) or not isinstance(doctype.value, str):
			continue
		if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
			if node.func.value.id == "frappe":
				calls.add((node.func.attr, doctype.value))
		elif (
			isinstance(node.func, ast.Attribute)
			and isinstance(node.func.value, ast.Attribute)
			and isinstance(node.func.value.value, ast.Name)
			and node.func.value.value.id == "frappe"
		):
			calls.add((f"{node.func.value.attr}.{node.func.attr}", doctype.value))
	return calls
