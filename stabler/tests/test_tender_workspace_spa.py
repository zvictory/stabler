"""Static SPA contract checks for the self-contained tender workspace."""

from __future__ import annotations

import unittest
from pathlib import Path


class TestTenderWorkspaceSpa(unittest.TestCase):
	def setUp(self):
		self.workspace = (
			Path(__file__).parents[1].joinpath("public/js/pages/tender/TenderWorkspaceTabs.vue").read_text()
		)

	def test_workspace_has_query_backed_tabs(self):
		for tab in ("overview", "vendor-po", "delivery", "finance"):
			self.assertIn(tab, self.workspace)
		self.assertIn("route.query.tab", self.workspace)
		self.assertIn("router.replace", self.workspace)
		self.assertNotIn("/app/", self.workspace)

	def test_finance_tab_distinguishes_base_currency_and_planned_margin(self):
		board = Path(__file__).parents[1].joinpath("public/js/pages/tender/PoControlBoard.vue").read_text()
		self.assertIn("financeCurrency", board)
		self.assertIn("finance.planned_margin", board)
		self.assertIn('t("Planned")', board)


if __name__ == "__main__":
	unittest.main()
