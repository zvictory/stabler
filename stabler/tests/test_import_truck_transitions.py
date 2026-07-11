"""Unit tests for the Import Truck status pipeline (Frappe-free).

Parses `_ALLOWED_TRANSITIONS` out of the controller source with `ast` (the
module imports frappe at top), matching the no-bench pattern used by the other
transition tests.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_import_truck_transitions -v
"""

from __future__ import annotations

import ast
import os
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler
_SOURCE_PATH = os.path.join(_APP_ROOT, "stabler", "doctype", "import_truck", "import_truck.py")

_ORDER = [
	"PENDING",
	"DEPARTED_IRAN",
	"AT_BORDER",
	"CROSSED_BORDER",
	"IN_TRANSIT",
	"ARRIVED",
	"UNLOADING",
	"GRN_CREATED",
	"COMPLETED",
]

_ALL_STATUSES = set(_ORDER) | {"Cancelled"}
_TERMINAL_STATUSES = {"COMPLETED", "Cancelled"}


def _load_allowed_transitions() -> dict[str, set[str]]:
	with open(_SOURCE_PATH, encoding="utf-8") as fh:
		tree = ast.parse(fh.read(), filename=_SOURCE_PATH)
	for node in ast.walk(tree):
		if isinstance(node, ast.Assign) and any(
			isinstance(t, ast.Name) and t.id == "_ALLOWED_TRANSITIONS" for t in node.targets
		):
			return ast.literal_eval(node.value)
	raise AssertionError("_ALLOWED_TRANSITIONS not found in import_truck.py")


class TestImportTruckTransitions(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.transitions = _load_allowed_transitions()

	def test_every_status_has_an_entry(self):
		self.assertEqual(set(self.transitions.keys()), _ALL_STATUSES)

	def test_terminal_statuses_accept_nothing(self):
		for status in _TERMINAL_STATUSES:
			self.assertEqual(self.transitions[status], set(), f"{status} should be terminal")

	def test_non_terminal_statuses_can_reach_cancelled(self):
		for status, targets in self.transitions.items():
			if status in _TERMINAL_STATUSES:
				continue
			self.assertIn("Cancelled", targets, f"{status} should be cancellable")

	def test_targets_are_known_statuses(self):
		for status, targets in self.transitions.items():
			self.assertTrue(targets <= _ALL_STATUSES, f"{status} has unknown target(s): {targets}")

	def test_pipeline_is_one_way(self):
		index = {status: i for i, status in enumerate(_ORDER)}
		for status, targets in self.transitions.items():
			if status == "Cancelled":
				continue
			for target in targets:
				if target == "Cancelled":
					continue
				self.assertGreater(
					index[target],
					index[status],
					f"{status} -> {target} moves backwards in the pipeline",
				)

	def test_crossed_border_advances_to_in_transit(self):
		# The CROSSED_BORDER hook fires the transport PI; the nominal next step is
		# IN_TRANSIT (Cancelled is the only other allowed target).
		self.assertEqual(self.transitions["CROSSED_BORDER"], {"IN_TRANSIT", "Cancelled"})


if __name__ == "__main__":
	unittest.main()
