import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api import imports


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

		payload = imports.get_commercial_invoice(self.ci.name)

		self.assertEqual(payload["packing_summary"]["status"], "Ready")
		self.assertEqual(
			payload["packing_summary"]["expected_items"][0]["expected_total_kg"],
			300.0,
		)
		self.assertIsNone(payload["grn"])
