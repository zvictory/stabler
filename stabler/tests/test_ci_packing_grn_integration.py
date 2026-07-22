import ast
import inspect
import textwrap
from unittest.mock import patch

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

	def test_create_grn_uses_packing_aggregate_not_ci_lines(self):
		result = imports.create_grn_for_ci(self.ci.name)
		grn = frappe.get_doc("GRN Checklist", result["name"])

		self.assertEqual(result["packing_status"], "Ready")
		self.assertFalse(result["expected_snapshot_locked"])
		self.assertEqual(grn.grn_items[0].expected_total_kg, 300.0)

	def test_manual_create_checks_record_permissions_before_derived_reads(self):
		source = inspect.getsource(imports.create_grn_for_ci)

		self.assertLess(
			source.index('_assert_can_read("Commercial Invoice", commercial_invoice)'),
			source.index('_company_of("Commercial Invoice", commercial_invoice)'),
		)
		self.assertLess(
			source.index('_assert_can_read("Commercial Invoice", commercial_invoice)'),
			source.index('frappe.get_doc("Commercial Invoice", commercial_invoice)'),
		)
		self.assertLess(
			source.index('_assert_can_read("GRN Checklist", result["name"])'),
			source.index("packing_service.summary_for_ci"),
		)

	def test_incomplete_packing_creates_shell_without_invented_rows(self):
		self.container_2.set("items", [])
		self.container_2.save(ignore_permissions=True)

		result = imports.create_grn_for_ci(self.ci.name)
		grn = frappe.get_doc("GRN Checklist", result["name"])

		self.assertEqual(result["packing_status"], "Incomplete")
		self.assertEqual(grn.grn_items[0].expected_total_kg, 200.0)

	def test_no_packing_rows_creates_empty_shell(self):
		for container in self.containers:
			container.set("items", [])
			container.save(ignore_permissions=True)

		result = imports.create_grn_for_ci(self.ci.name)
		grn = frappe.get_doc("GRN Checklist", result["name"])

		self.assertEqual(result["packing_status"], "Incomplete")
		self.assertEqual(grn.grn_items, [])

	def test_stuffed_hook_uses_the_same_packing_aggregate(self):
		self.ci.items[0].qty = 450
		self.ci.status = "STUFFED"
		self.ci.save(ignore_permissions=True)

		grn_name = frappe.db.get_value(
			"GRN Checklist", {"commercial_invoice": self.ci.name}
		)
		grn = frappe.get_doc("GRN Checklist", grn_name)

		self.assertEqual(grn.grn_items[0].expected_total_kg, 300.0)

	def test_refresh_replaces_partial_snapshot_from_current_packing(self):
		self.container_2.set("items", [])
		self.container_2.save(ignore_permissions=True)
		created = imports.create_grn_for_ci(self.ci.name)
		self.container_2.append(
			"items",
			{
				"item_code": self.item,
				"box_qty": 5,
				"box_kg": 20,
				"total_kg": 100,
			},
		)
		self.container_2.save(ignore_permissions=True)

		result = imports.refresh_grn_expected_quantities(created["name"])
		grn = frappe.get_doc("GRN Checklist", created["name"])

		self.assertEqual(result["packing_status"], "Ready")
		self.assertEqual(grn.grn_items[0].expected_total_kg, 300.0)

	def test_refresh_rejects_submitted_truck_receipt_before_replacing_rows(self):
		created = imports.create_grn_for_ci(self.ci.name)
		truck = frappe.new_doc("Import Truck")
		truck.update({"company": self.company, "commercial_invoice": self.ci.name})
		truck.insert(ignore_permissions=True)
		receipt = frappe.new_doc("Truck Receipt")
		receipt.update(
			{
				"company": self.company,
				"grn_checklist": created["name"],
				"truck": truck.name,
				"arrival_date": frappe.utils.today(),
			}
		)
		receipt.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Truck Receipt", receipt.name, "docstatus", 1
		)

		with self.assertRaisesRegex(frappe.ValidationError, "Expected quantities are locked"):
			imports.refresh_grn_expected_quantities(created["name"])

	def test_refresh_rejects_submitted_grn(self):
		created = imports.create_grn_for_ci(self.ci.name)
		frappe.db.set_value("GRN Checklist", created["name"], "docstatus", 1)

		with self.assertRaisesRegex(frappe.ValidationError, "Expected quantities are locked"):
			imports.refresh_grn_expected_quantities(created["name"])

	def test_create_or_get_grn_recovers_concurrent_unique_winner(self):
		summary = packing_service.summary_for_ci(self.ci.name, self.company)
		winner = frappe.new_doc("GRN Checklist")
		winner.update(
			{
				"company": self.company,
				"commercial_invoice": self.ci.name,
				"supplier": self.supplier,
			}
		)
		packing_service.replace_grn_expected_rows(winner, summary["expected_items"])

		def insert_winner(_commercial_invoice, _company):
			winner.insert(ignore_permissions=True)
			return summary

		with patch.object(packing_service, "summary_for_ci", side_effect=insert_winner):
			result = packing_service.create_or_get_grn(self.ci, ignore_permissions=True)

		self.assertEqual(result, {"name": winner.name, "created": False})


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
