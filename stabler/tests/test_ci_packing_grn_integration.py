import ast
import inspect
import threading
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

	def _new_truck(self, *, company=None, commercial_invoice=None):
		truck = frappe.new_doc("Import Truck")
		truck.update(
			{
				"company": company or self.company,
				"commercial_invoice": commercial_invoice or self.ci.name,
			}
		)
		truck.insert(ignore_permissions=True)
		return truck

	def _new_receipt(self, grn_name, truck, *, company=None):
		receipt = frappe.new_doc("Truck Receipt")
		receipt.update(
			{
				"company": company or self.company,
				"grn_checklist": grn_name,
				"truck": truck.name,
				"arrival_date": frappe.utils.today(),
			}
		)
		return receipt

	def _new_ci(self, *, company=None):
		ci = frappe.copy_doc(self.ci)
		ci.company = company or self.company
		ci.ci_number = frappe.generate_hash(length=10)
		ci.insert(ignore_permissions=True)
		return ci

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
				"company": self.company,
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
		frappe.db.set_value(
			"Import Container", foreign.name, "company", self.other_company.name
		)

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
			source.index('if result["created"]:'),
			source.index('_assert_can_read("GRN Checklist", result["name"])'),
		)
		self.assertLess(
			source.index('_assert_can_read("GRN Checklist", result["name"])'),
			source.index("packing_service.summary_for_ci"),
		)

	def test_new_grn_returns_creation_summary_without_post_insert_reads(self):
		with (
			patch.object(
				packing_service,
				"summary_for_ci",
				wraps=packing_service.summary_for_ci,
			) as summary_for_ci,
			patch.object(frappe.db, "get_value", wraps=frappe.db.get_value) as get_value,
		):
			result = imports.create_grn_for_ci(self.ci.name)

		self.assertTrue(result["created"])
		self.assertEqual(result["packing_status"], "Ready")
		self.assertFalse(result["expected_snapshot_locked"])
		self.assertEqual(summary_for_ci.call_count, 1)
		self.assertFalse(
			any(
				call.args[:3]
				== ("GRN Checklist", result["name"], "expected_snapshot_locked")
				for call in get_value.call_args_list
			)
		)

	def test_existing_grn_is_enriched_only_after_read_check(self):
		created = imports.create_grn_for_ci(self.ci.name)

		with (
			patch.object(
				packing_service,
				"summary_for_ci",
				wraps=packing_service.summary_for_ci,
			) as summary_for_ci,
			patch.object(frappe.db, "get_value", wraps=frappe.db.get_value) as get_value,
		):
			result = imports.create_grn_for_ci(self.ci.name)

		self.assertFalse(result["created"])
		self.assertEqual(summary_for_ci.call_count, 1)
		self.assertTrue(
			any(
				call.args[:3]
				== ("GRN Checklist", created["name"], "expected_snapshot_locked")
				for call in get_value.call_args_list
			)
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

	def test_snapshot_lock_is_persisted(self):
		from stabler.stabler.imports_module import hooks

		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		hooks._lock_grn_expected_snapshot(grn_name)
		grn = frappe.get_doc("GRN Checklist", grn_name)

		self.assertEqual(grn.expected_snapshot_locked, 1)
		self.assertIsNotNone(grn.expected_snapshot_locked_at)

	def test_snapshot_lock_rejects_incomplete_packing(self):
		from stabler.stabler.imports_module import hooks

		self.container_2.set("items", [])
		self.container_2.save(ignore_permissions=True)
		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"packing lists must be complete and reconciled",
		):
			hooks._lock_grn_expected_snapshot(grn_name)

	def test_locked_snapshot_blocks_item_change_but_allows_seal_change(self):
		from stabler.stabler.imports_module import hooks

		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		hooks._lock_grn_expected_snapshot(grn_name)

		self.container_1.seal_number = "NEW-SEAL"
		self.container_1.save(ignore_permissions=True)
		self.container_1.items[0].total_kg = 999

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"Packing-list quantities are locked",
		):
			self.container_1.save(ignore_permissions=True)

	def test_submit_hook_locks_before_creating_purchase_receipt(self):
		from stabler.stabler.imports_module import hooks

		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		truck = frappe.new_doc("Import Truck")
		truck.update({"company": self.company, "commercial_invoice": self.ci.name})
		truck.insert(ignore_permissions=True)
		receipt = frappe.new_doc("Truck Receipt")
		receipt.update(
			{
				"company": self.company,
				"grn_checklist": grn_name,
				"truck": truck.name,
				"arrival_date": frappe.utils.today(),
			}
		)
		receipt.insert(ignore_permissions=True)

		def assert_snapshot_is_locked(_receipt):
			self.assertEqual(
				frappe.db.get_value(
					"GRN Checklist", grn_name, "expected_snapshot_locked"
				),
				1,
			)

		with patch.object(
			hooks,
			"_create_pr_for_truck_receipt",
			side_effect=assert_snapshot_is_locked,
		) as create_pr:
			receipt.submit()

		create_pr.assert_called_once_with(receipt)

	def test_receipt_company_must_match_grn_before_insert(self):
		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		receipt = self._new_receipt(
			grn_name,
			self._new_truck(),
			company=self.other_company.name,
		)

		with self.assertRaisesRegex(frappe.ValidationError, "company must match"):
			receipt.insert(ignore_permissions=True)

		self.assertFalse(
			frappe.db.get_value("GRN Checklist", grn_name, "expected_snapshot_locked")
		)

	def test_receipt_truck_must_match_grn_company_and_ci(self):
		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		other_ci = self._new_ci()

		for truck in (
			self._new_truck(company=self.other_company.name),
			self._new_truck(commercial_invoice=other_ci.name),
		):
			with self.subTest(truck=truck.name):
				with self.assertRaisesRegex(frappe.ValidationError, "must match GRN"):
					self._new_receipt(grn_name, truck).insert(ignore_permissions=True)

	def test_locked_ci_rejects_new_container_even_when_empty(self):
		from stabler.stabler.imports_module import hooks

		hooks._lock_grn_expected_snapshot(imports.create_grn_for_ci(self.ci.name)["name"])
		container = frappe.new_doc("Import Container")
		container.update(
			{
				"company": self.company,
				"commercial_invoice": self.ci.name,
				"container_number": f"LOCKED-{frappe.generate_hash(length=6)}",
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "Packing source is locked"):
			container.insert(ignore_permissions=True)

	def test_container_company_must_match_ci_on_insert(self):
		container = frappe.new_doc("Import Container")
		container.update(
			{
				"company": self.other_company.name,
				"commercial_invoice": self.ci.name,
				"container_number": f"MISMATCH-{frappe.generate_hash(length=6)}",
			}
		)

		with self.assertRaisesRegex(frappe.ValidationError, "company must match"):
			container.insert(ignore_permissions=True)

	def test_container_company_must_match_ci_on_update(self):
		self.container_1.company = self.other_company.name

		with self.assertRaisesRegex(frappe.ValidationError, "company must match"):
			self.container_1.save(ignore_permissions=True)

	def test_locked_container_rejects_company_or_full_source_relink(self):
		from stabler.stabler.imports_module import hooks

		hooks._lock_grn_expected_snapshot(imports.create_grn_for_ci(self.ci.name)["name"])
		self.container_1.company = self.other_company.name
		with self.assertRaisesRegex(frappe.ValidationError, "company must match"):
			self.container_1.save(ignore_permissions=True)

		container = frappe.get_doc("Import Container", self.container_1.name)
		container.company = self.other_company.name
		container.commercial_invoice = self._new_ci(company=self.other_company.name).name
		with self.assertRaisesRegex(frappe.ValidationError, "Packing source is locked"):
			container.save(ignore_permissions=True)

	def test_container_cannot_relink_into_or_out_of_locked_ci(self):
		from stabler.stabler.imports_module import hooks

		other_ci = self._new_ci()
		unlocked = frappe.copy_doc(self.container_1)
		unlocked.container_number = f"UNLOCKED-{frappe.generate_hash(length=6)}"
		unlocked.commercial_invoice = other_ci.name
		unlocked.insert(ignore_permissions=True)
		hooks._lock_grn_expected_snapshot(imports.create_grn_for_ci(self.ci.name)["name"])

		for container, target_ci in (
			(self.container_1, other_ci.name),
			(unlocked, self.ci.name),
		):
			with self.subTest(container=container.name):
				container.commercial_invoice = target_ci
				with self.assertRaisesRegex(frappe.ValidationError, "Packing source is locked"):
					container.save(ignore_permissions=True)

	def test_locked_ci_rejects_container_deletion(self):
		from stabler.stabler.imports_module import hooks

		hooks._lock_grn_expected_snapshot(imports.create_grn_for_ci(self.ci.name)["name"])

		with self.assertRaisesRegex(frappe.ValidationError, "Packing source is locked"):
			self.container_1.delete(ignore_permissions=True)

	def test_locked_packing_signature_is_order_independent_and_complete(self):
		from stabler.stabler.imports_module import hooks
		other_item = frappe.db.get_value(
			"Item", {"name": ["!=", self.item], "disabled": 0}, "name"
		)
		self.assertIsNotNone(other_item)

		first = self.container_1.items[0]
		first.box_qty = 5
		first.total_kg = 100
		self.container_1.append(
			"items",
			{
				"item_code": self.item,
				"category": "Frozen",
				"box_qty": 5,
				"box_kg": 20,
				"total_kg": 100,
			},
		)
		self.container_1.save(ignore_permissions=True)
		hooks._lock_grn_expected_snapshot(imports.create_grn_for_ci(self.ci.name)["name"])

		self.container_1.set("items", list(reversed(self.container_1.items)))
		self.container_1.save(ignore_permissions=True)

		mutations = {
			"category": lambda doc: setattr(doc.items[1], "category", "Chilled"),
			"boxes": lambda doc: setattr(doc.items[1], "box_qty", 6),
			"box kg": lambda doc: setattr(doc.items[1], "box_kg", 21),
			"item": lambda doc: setattr(doc.items[1], "item_code", other_item),
			"remove": lambda doc: doc.remove(doc.items[1]),
			"duplicate": lambda doc: doc.append("items", doc.items[1].as_dict()),
		}
		for label, mutate in mutations.items():
			with self.subTest(change=label):
				doc = frappe.get_doc("Import Container", self.container_1.name)
				mutate(doc)
				with self.assertRaisesRegex(
					frappe.ValidationError, "Packing-list quantities are locked"
				):
					doc.save(ignore_permissions=True)

	def test_purchase_receipt_failure_rolls_back_submit_and_snapshot_lock(self):
		from stabler.stabler.imports_module import hooks

		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		grn = frappe.get_doc("GRN Checklist", grn_name)
		grn.grn_items[0].expected_total_kg = 1
		grn.save(ignore_permissions=True)
		receipt = self._new_receipt(grn_name, self._new_truck())
		receipt.insert(ignore_permissions=True)
		frappe.db.savepoint("before_failed_receipt")

		try:
			with (
				patch.object(
					hooks,
					"_create_pr_for_truck_receipt",
					side_effect=frappe.ValidationError("forced PR failure"),
				),
				self.assertRaisesRegex(frappe.ValidationError, "forced PR failure"),
			):
				receipt.submit()
		finally:
			frappe.db.rollback(save_point="before_failed_receipt")

		grn.reload()
		self.assertEqual(frappe.db.get_value("Truck Receipt", receipt.name, "docstatus"), 0)
		self.assertFalse(grn.expected_snapshot_locked)
		self.assertIsNone(grn.expected_snapshot_locked_at)
		self.assertEqual(grn.grn_items[0].expected_total_kg, 1)

	def test_second_receipt_does_not_resynchronize_locked_snapshot(self):
		from stabler.stabler.imports_module import hooks

		grn_name = imports.create_grn_for_ci(self.ci.name)["name"]
		hooks._lock_grn_expected_snapshot(grn_name)
		locked_expected = frappe.db.get_value(
			"GRN Checklist Item", {"parent": grn_name}, "expected_total_kg"
		)
		frappe.db.set_value(
			"Import Container Item",
			self.container_1.items[0].name,
			"total_kg",
			999,
		)
		receipt = self._new_receipt(grn_name, self._new_truck())
		receipt.insert(ignore_permissions=True)

		with patch.object(hooks, "_create_pr_for_truck_receipt"):
			receipt.submit()

		self.assertEqual(
			frappe.db.get_value(
				"GRN Checklist Item", {"parent": grn_name}, "expected_total_kg"
			),
			locked_expected,
		)


class CIPackingGrnConcurrencyTest(FrappeTestCase):
	def test_freeze_serializes_in_flight_container_mutation(self):
		from stabler.stabler.imports_module import hooks

		company = frappe.db.get_value("Company", {}, "name")
		supplier = frappe.db.get_value("Supplier", {}, "name")
		item = frappe.db.get_value("Item", {"disabled": 0}, "name")
		if not all((company, supplier, item)):
			self.skipTest("Company, Supplier and Item fixtures are required")

		ci = frappe.new_doc("Commercial Invoice")
		ci.update(
			{
				"company": company,
				"supplier": supplier,
				"ci_number": frappe.generate_hash(length=10),
				"ci_date": frappe.utils.today(),
			}
		)
		ci.append("items", {"item": item, "qty": 300, "boxes": 15, "box_weight_kg": 20})
		ci.insert(ignore_permissions=True)
		container = frappe.new_doc("Import Container")
		container.update(
			{
				"company": company,
				"commercial_invoice": ci.name,
				"container_number": f"RACE-{frappe.generate_hash(length=6)}",
			}
		)
		container.append(
			"items",
			{"item_code": item, "box_qty": 15, "box_kg": 20, "total_kg": 300},
		)
		container.insert(ignore_permissions=True)
		grn_name = packing_service.create_or_get_grn(ci, ignore_permissions=True)["name"]
		frappe.db.commit()

		site = frappe.local.site
		snapshot_derived = threading.Event()
		allow_freeze = threading.Event()
		mutation_finished = threading.Event()
		freeze_errors: list[BaseException] = []
		mutation_errors: list[BaseException] = []
		replace_calls = 0
		original_replace = packing_service.replace_grn_expected_rows

		def replace_after_barrier(grn, expected_items):
			nonlocal replace_calls
			replace_calls += 1
			snapshot_derived.set()
			if not allow_freeze.wait(timeout=10):
				raise AssertionError("Timed out waiting to release snapshot freeze")
			return original_replace(grn, expected_items)

		def freeze_snapshot():
			frappe.init(site)
			frappe.connect()
			try:
				hooks._lock_grn_expected_snapshot(grn_name)
				frappe.db.commit()
			except BaseException as exc:
				freeze_errors.append(exc)
				frappe.db.rollback()
			finally:
				frappe.destroy()

		def mutate_container():
			frappe.init(site)
			frappe.connect()
			try:
				doc = frappe.get_doc("Import Container", container.name)
				doc.items[0].box_qty = 14
				doc.items[0].total_kg = 280
				doc.save(ignore_permissions=True)
				frappe.db.commit()
			except BaseException as exc:
				mutation_errors.append(exc)
				frappe.db.rollback()
			finally:
				mutation_finished.set()
				frappe.destroy()

		freeze_thread = threading.Thread(target=freeze_snapshot)
		second_freeze_thread = threading.Thread(target=freeze_snapshot)
		mutation_thread = threading.Thread(target=mutate_container)
		try:
			with patch.object(
				packing_service,
				"replace_grn_expected_rows",
				side_effect=replace_after_barrier,
			):
				freeze_thread.start()
				self.assertTrue(snapshot_derived.wait(timeout=10))
				second_freeze_thread.start()
				mutation_thread.start()
				self.assertFalse(mutation_finished.wait(timeout=1))
				allow_freeze.set()
				freeze_thread.join(timeout=10)
				second_freeze_thread.join(timeout=10)
				mutation_thread.join(timeout=10)

			self.assertFalse(freeze_thread.is_alive())
			self.assertFalse(second_freeze_thread.is_alive())
			self.assertFalse(mutation_thread.is_alive())
			self.assertEqual(freeze_errors, [])
			self.assertEqual(replace_calls, 1)
			self.assertEqual(len(mutation_errors), 1)
			self.assertIsInstance(mutation_errors[0], frappe.ValidationError)
			self.assertEqual(
				frappe.db.get_value(
					"Import Container Item", container.items[0].name, "total_kg"
				),
				300,
			)
		finally:
			allow_freeze.set()
			for thread in (freeze_thread, second_freeze_thread, mutation_thread):
				if thread.ident is not None:
					thread.join(timeout=10)
			frappe.db.rollback()
			frappe.delete_doc("GRN Checklist", grn_name, force=True, ignore_permissions=True)
			frappe.delete_doc("Import Container", container.name, force=True, ignore_permissions=True)
			frappe.delete_doc("Commercial Invoice", ci.name, force=True, ignore_permissions=True)
			frappe.db.commit()


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
