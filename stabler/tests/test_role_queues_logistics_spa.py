"""SPA contract tests for Logistics Role Queue (LogistBoard.vue) — Task C4.

Guards rules specified in PROMPT_rol_kuyruklari.md:
  * No Frappe Desk redirects (/app/)
  * Read-only projection: no drag-and-drop directives (R3)
  * Consumes derived lanes from server (R1)
  * Empty state explains reason (R5)
  * Action buttons open SPA views (Doc Center / PO)
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
LOGIST_VUE = _ROOT / "public" / "js" / "pages" / "tender" / "LogistBoard.vue"


def _read(path: Path) -> str:
	return path.read_text(encoding="utf-8")


class TestLogistBoardVueContract(unittest.TestCase):
	def setUp(self):
		self.src = _read(LOGIST_VUE)

	def test_no_escape_to_frappe_desk(self):
		"""Hard rule: Stabler Vue SPA must never link out to Frappe Desk."""
		self.assertNotIn("/app/", self.src)

	def test_no_drag_and_drop_directives_or_handlers(self):
		"""R3: Cards are read-only projections. Cards are not draggable."""
		self.assertNotIn("v-drag", self.src)
		self.assertNotIn("draggable", self.src.lower())
		self.assertNotIn("@drag", self.src)

	def test_logist_board_consumes_derived_lanes(self):
		"""R1 & R4: Renders derived swimlanes structure."""
		self.assertIn("filteredLanes", self.src)
		self.assertIn("LANE_CONFIGS", self.src)

	def test_empty_state_explains_reason(self):
		"""R5: Empty state explains why queue is empty."""
		self.assertIn("No active shipments or won lots in the pipeline.", self.src)
		self.assertIn("EmptyState", self.src)

	def test_actions_open_doc_center_and_po(self):
		"""Actions open Document Center and PO views within the SPA."""
		self.assertIn("openDocCenter", self.src)
		self.assertIn("openPo", self.src)
		self.assertIn("tender-documents", self.src)
		self.assertIn("purchasing-order", self.src)


if __name__ == "__main__":
	unittest.main()
