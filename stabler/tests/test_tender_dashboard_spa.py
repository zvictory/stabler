"""Static contract checks for the tender operations dashboard SPA.

The project does not ship a Vue test runner. These checks keep the public
dashboard contract executable without adding a browser-only dependency.

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_dashboard_spa -v
"""

from __future__ import annotations

import os
import unittest


_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_DASHBOARD = os.path.join(_ROOT, "public", "js", "pages", "Dashboard.vue")
_TENDER_PAGES = (
	"DirectorBoard.vue",
	"MyTenders.vue",
	"DeclarantQueue.vue",
	"LogistBoard.vue",
)


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as source:
		return source.read()


class TestTenderDashboardSpaContract(unittest.TestCase):
	def test_dashboard_uses_capability_gate_and_aggregate_endpoint(self):
		source = _read(_DASHBOARD)
		self.assertIn('session.canAccessModule("tender")', source)
		self.assertIn('stabler.api.tender.tender_dashboard', source)
		self.assertIn('v-if="tenderEnabled"', source)
		self.assertIn('v-else', source)

	def test_dashboard_has_accessible_spa_drilldowns_without_desk_links(self):
		source = _read(_DASHBOARD)
		self.assertIn('router.push({ name, query })', source)
		self.assertIn('type="button" class="tender-metric-card"', source)
		self.assertIn('.tender-metric-card:focus-visible', source)
		self.assertIn('.tender-metric-card:active', source)
		self.assertNotIn('"/app/', source)
		self.assertNotIn("'/app/", source)

	def test_dashboard_presents_explicit_lifecycle_and_execution_counts(self):
		source = _read(_DASHBOARD)
		for text in (
			"Tayyor / Go",
			"Yuborilgan",
			"Yetkazilgan SO",
			"Qabul qilingan PO",
			"Tekshirilmagan tarix",
			"Missing required checks",
		):
			self.assertIn(text, source)

	def test_tender_boards_read_documented_route_filters(self):
		for page in _TENDER_PAGES:
			source = _read(os.path.join(_ROOT, "public", "js", "pages", "tender", page))
			self.assertIn('useRoute', source, page)
			self.assertIn('route.query', source, page)
			self.assertIn('filteredRows', source, page)
			for parameter in ("stage", "period", "risk", "due", "status"):
				self.assertIn(parameter, source, f"{page} must support {parameter}")
			self.assertNotIn('"/app/', source, page)


if __name__ == "__main__":
	unittest.main()
