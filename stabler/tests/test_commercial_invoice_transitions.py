"""Unit tests for the Commercial Invoice status pipeline (Frappe-free).

`_ALLOWED_TRANSITIONS` in stabler/stabler/doctype/commercial_invoice/commercial_invoice.py
lives in a controller module that imports frappe at the top, so it cannot be
imported directly without a site. This test instead parses the source with
`ast` and evaluates the dict literal in isolation, matching the no-bench
pattern used by test_company_scope_guard.py.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_commercial_invoice_transitions -v
"""

from __future__ import annotations

import ast
import os
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler
_SOURCE_PATH = os.path.join(
	_APP_ROOT, "stabler", "doctype", "commercial_invoice", "commercial_invoice.py"
)

_ALL_STATUSES = {
	"BOOKED",
	"STUFFED",
	"GATE_IN",
	"ON_BOARD",
	"IN_TRANSIT",
	"DISCHARGED",
	"AVAILABLE",
	"ARRIVED_AT_IRAN",
	"DELIVERED_TO_UZBEKISTAN",
	"Cancelled",
}

_TERMINAL_STATUSES = {"DELIVERED_TO_UZBEKISTAN", "Cancelled"}


def _load_allowed_transitions() -> dict[str, set[str]]:
	with open(_SOURCE_PATH, encoding="utf-8") as fh:
		tree = ast.parse(fh.read(), filename=_SOURCE_PATH)
	for node in ast.walk(tree):
		if isinstance(node, ast.Assign) and any(
			isinstance(t, ast.Name) and t.id == "_ALLOWED_TRANSITIONS" for t in node.targets
		):
			return ast.literal_eval(node.value)
	raise AssertionError("_ALLOWED_TRANSITIONS not found in commercial_invoice.py")


class TestAllowedTransitionsShape(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.transitions = _load_allowed_transitions()

	def test_every_status_has_an_entry(self):
		self.assertEqual(set(self.transitions.keys()), _ALL_STATUSES)

	def test_terminal_statuses_accept_nothing(self):
		for status in _TERMINAL_STATUSES:
			self.assertEqual(self.transitions[status], set(), f"{status} should be terminal")

	def test_non_terminal_statuses_can_reach_cancelled(self):
		# ARRIVED_AT_IRAN is the deliberate exception — see
		# test_arrived_at_iran_only_reaches_delivered below.
		for status, targets in self.transitions.items():
			if status in _TERMINAL_STATUSES or status == "ARRIVED_AT_IRAN":
				continue
			self.assertIn("Cancelled", targets, f"{status} should be cancellable")

	def test_targets_are_known_statuses(self):
		for status, targets in self.transitions.items():
			self.assertTrue(targets <= _ALL_STATUSES, f"{status} has unknown target(s): {targets}")

	def test_pipeline_is_one_way(self):
		# Every forward step should only ever move to a status later in the
		# nominal pipeline order, or to Cancelled. This guards against a typo
		# reopening a path back to an earlier stage.
		order = [
			"BOOKED",
			"STUFFED",
			"GATE_IN",
			"ON_BOARD",
			"IN_TRANSIT",
			"DISCHARGED",
			"AVAILABLE",
			"ARRIVED_AT_IRAN",
			"DELIVERED_TO_UZBEKISTAN",
		]
		index = {status: i for i, status in enumerate(order)}
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

	def test_arrived_at_iran_only_reaches_delivered(self):
		# ARRIVED_AT_IRAN is the sole status without a Cancelled exit — once
		# goods have physically arrived the deal cannot be walked back.
		self.assertEqual(self.transitions["ARRIVED_AT_IRAN"], {"DELIVERED_TO_UZBEKISTAN"})


if __name__ == "__main__":
	unittest.main()
