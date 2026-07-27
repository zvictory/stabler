"""Unit tests for the imports automation math / decisions (Frappe-free).

The frappe-facing orchestration lives in imports_module/hooks.py and cannot be
imported without a bench, but every calculation and run/skip decision it makes
is delegated to imports_module/payment_math.py, which imports no frappe. These
tests exercise that pure layer:

* the M6 guard (migration flag + per-company toggle) no-ops correctly,
* the ARRIVED_AT_IRAN / CROSSED_BORDER edge detection,
* the DRAFT Payment Entry payload (70% of goods value, Pay to Supplier,
  proportional PO references, idempotency marker, never submitted),
* the DRAFT transport Purchase Invoice payload (single service line, skipped
  when transport_cost is 0).

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_container_arrival_hook -v
"""

from __future__ import annotations

import unittest

from stabler.stabler.imports_module import payment_math as pm


class TestRunGuard(unittest.TestCase):
	def test_noop_during_migration(self):
		# ETL sets frappe.flags.in_msaerp_migration — automation must not fire.
		self.assertFalse(pm.should_run_automation(in_migration=True, imports_enabled=True))

	def test_noop_when_imports_disabled(self):
		# M6: inert on tenants that have the imports module switched off.
		self.assertFalse(pm.should_run_automation(in_migration=False, imports_enabled=False))

	def test_runs_when_enabled_outside_migration(self):
		self.assertTrue(pm.should_run_automation(in_migration=False, imports_enabled=True))


class TestEdgeDetection(unittest.TestCase):
	def test_advance_fires_only_on_transition_into_arrived(self):
		self.assertTrue(pm.wants_advance_pe("AVAILABLE", "ARRIVED_AT_IRAN"))
		# Re-save that keeps the same status must NOT re-fire.
		self.assertFalse(pm.wants_advance_pe("ARRIVED_AT_IRAN", "ARRIVED_AT_IRAN"))
		self.assertFalse(pm.wants_advance_pe("AVAILABLE", "AVAILABLE"))

	def test_transport_fires_only_on_transition_into_crossed(self):
		self.assertTrue(pm.wants_transport_pi("AT_BORDER", "CROSSED_BORDER"))
		self.assertFalse(pm.wants_transport_pi("CROSSED_BORDER", "CROSSED_BORDER"))


class TestAllocateAmount(unittest.TestCase):
	def test_proportional_split_sums_exactly(self):
		amounts = pm.allocate_amount(100.0, [3, 1])
		self.assertEqual(amounts, [75.0, 25.0])
		self.assertAlmostEqual(sum(amounts), 100.0, places=2)

	def test_rounding_absorbed_by_last_row(self):
		amounts = pm.allocate_amount(100.0, [1, 1, 1])
		self.assertAlmostEqual(sum(amounts), 100.0, places=2)
		self.assertEqual(len(amounts), 3)

	def test_equal_split_when_all_weights_zero(self):
		amounts = pm.allocate_amount(90.0, [0, 0, 0])
		self.assertAlmostEqual(sum(amounts), 90.0, places=2)

	def test_empty_weights(self):
		self.assertEqual(pm.allocate_amount(100.0, []), [])


class TestAdvancePEPayload(unittest.TestCase):
	def _payload(self, po_rows):
		return pm.build_advance_pe_payload(
			company="MSA",
			supplier="ACME",
			currency="USD",
			total_amount=1000.0,
			po_rows=po_rows,
			container_name="IMP-CNT-2026-00001",
		)

	def test_pay_to_supplier_70pct(self):
		payload = self._payload([{"purchase_order": "PO-1", "grand_total": 1000}])
		self.assertEqual(payload["payment_type"], "Pay")
		self.assertEqual(payload["party_type"], "Supplier")
		self.assertEqual(payload["party"], "ACME")
		self.assertEqual(payload["paid_amount"], 700.0)
		self.assertEqual(payload["received_amount"], 700.0)

	def test_is_draft(self):
		# Never set docstatus — the PE must be inserted as a draft for review.
		payload = self._payload([{"purchase_order": "PO-1", "grand_total": 1000}])
		self.assertNotIn("docstatus", payload)

	def test_idempotency_marker(self):
		payload = self._payload([])
		self.assertEqual(payload["reference_no"], "70PCT-IMP-CNT-2026-00001")

	def test_container_ref_stamped(self):
		# WP7 vendor traceability: the advance PE back-links its container.
		payload = self._payload([])
		self.assertEqual(payload["custom_import_container"], "IMP-CNT-2026-00001")

	def test_references_allocated_proportionally(self):
		payload = self._payload(
			[
				{"purchase_order": "PO-1", "grand_total": 600},
				{"purchase_order": "PO-2", "grand_total": 400},
			]
		)
		refs = payload["references"]
		self.assertEqual([r["reference_name"] for r in refs], ["PO-1", "PO-2"])
		self.assertTrue(all(r["reference_doctype"] == "Purchase Order" for r in refs))
		self.assertEqual(refs[0]["allocated_amount"], 420.0)
		self.assertEqual(refs[1]["allocated_amount"], 280.0)
		self.assertAlmostEqual(sum(r["allocated_amount"] for r in refs), payload["paid_amount"], places=2)

	def test_no_pos_means_no_references(self):
		payload = self._payload([])
		self.assertEqual(payload["references"], [])
		self.assertEqual(payload["paid_amount"], 700.0)


class TestTransportPIPayload(unittest.TestCase):
	def test_single_service_line_draft(self):
		payload = pm.build_transport_pi_payload(
			company="MSA",
			supplier="TRUCKCO",
			currency="USD",
			transport_cost=1500.0,
			truck_name="IMP-TRK-2026-00001",
		)
		self.assertEqual(payload["doctype"], "Purchase Invoice")
		self.assertEqual(payload["supplier"], "TRUCKCO")
		self.assertEqual(payload["bill_no"], "XBORDER-IMP-TRK-2026-00001")
		self.assertEqual(len(payload["items"]), 1)
		line = payload["items"][0]
		self.assertEqual(line["item_code"], pm.XBORDER_ITEM_CODE)
		self.assertEqual(line["qty"], 1)
		self.assertEqual(line["rate"], 1500.0)
		self.assertNotIn("docstatus", payload)

	def test_vendor_traceability_refs(self):
		# WP7: the transport bill back-links its truck, CI and consumed expense.
		payload = pm.build_transport_pi_payload(
			company="MSA",
			supplier="TRUCKCO",
			currency="USD",
			transport_cost=1500.0,
			truck_name="IMP-TRK-2026-00001",
			commercial_invoice="IMP-CI-2026-00001",
			import_expense="IMP-EXP-2026-00001",
		)
		self.assertEqual(payload["custom_import_truck"], "IMP-TRK-2026-00001")
		self.assertEqual(payload["custom_commercial_invoice"], "IMP-CI-2026-00001")
		self.assertEqual(payload["custom_import_expense"], "IMP-EXP-2026-00001")
		self.assertIsNone(payload["custom_import_container"])

	def test_skipped_when_zero_cost(self):
		self.assertIsNone(
			pm.build_transport_pi_payload(
				company="MSA",
				supplier="TRUCKCO",
				currency="USD",
				transport_cost=0,
				truck_name="IMP-TRK-2026-00001",
			)
		)


class TestImportExpensePIPayload(unittest.TestCase):
	def test_vendor_traceability_refs(self):
		# WP7: a non-transport expense bill back-links its CI / container / truck /
		# expense so the container cost ledger can attribute it.
		payload = pm.build_import_expense_pi_payload(
			company="MSA",
			supplier="CUSTOMSCO",
			currency="USD",
			amount=250.0,
			category="Customs",
			description="broker fee",
			expense_name="IMP-EXP-2026-00009",
			commercial_invoice="IMP-CI-2026-00001",
			container="IMP-CNT-2026-00001",
			truck=None,
		)
		self.assertEqual(payload["custom_import_expense"], "IMP-EXP-2026-00009")
		self.assertEqual(payload["custom_commercial_invoice"], "IMP-CI-2026-00001")
		self.assertEqual(payload["custom_import_container"], "IMP-CNT-2026-00001")
		self.assertIsNone(payload["custom_import_truck"])
		self.assertNotIn("docstatus", payload)

	def test_skipped_when_zero_amount(self):
		self.assertIsNone(
			pm.build_import_expense_pi_payload(
				company="MSA",
				supplier="CUSTOMSCO",
				currency="USD",
				amount=0,
				category="Customs",
				description="",
				expense_name="IMP-EXP-2026-00009",
			)
		)


if __name__ == "__main__":
	unittest.main()
