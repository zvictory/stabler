import unittest

from stabler.stabler.imports_module import packing_math


class TestPackingMath(unittest.TestCase):
	def test_aggregate_combines_same_item_across_containers(self):
		rows = [
			{"container": "C1", "item_code": "BEEF", "item_name": "Beef", "box_qty": 10, "box_kg": 20, "total_kg": 200},
			{"container": "C2", "item_code": "BEEF", "item_name": "Beef", "box_qty": 5, "box_kg": 20, "total_kg": 100},
		]
		self.assertEqual(packing_math.aggregate_container_items(rows), [{
			"item_code": "BEEF", "item_name": "Beef", "expected_boxes": 15,
			"expected_box_kg": 20.0, "expected_total_kg": 300.0,
		}])

	def test_readiness_requires_every_linked_container_and_matching_ci_kg(self):
		packed = packing_math.aggregate_container_items([
			{"container": "C1", "item_code": "BEEF", "box_qty": 10, "box_kg": 20, "total_kg": 200},
		])
		reconciliation = packing_math.reconcile_ci_items([{"item_code": "BEEF", "qty": 200}], packed)
		self.assertEqual(packing_math.packing_readiness(["C1", "C2"], ["C1"], reconciliation), "Incomplete")
		self.assertEqual(packing_math.packing_readiness(["C1"], ["C1"], reconciliation), "Ready")
