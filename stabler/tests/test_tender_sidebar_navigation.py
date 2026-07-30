"""Regression guards for role-aware Tender navigation in the SPA sidebar."""

from __future__ import annotations

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDEBAR = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "components", "Sidebar.vue"))
_ROUTER = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "router.js"))
_TENDER_NAV = os.path.normpath(
	os.path.join(_HERE, "..", "public", "js", "pages", "tender", "TenderNav.vue")
)


class TestTenderSidebarNavigation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(_SIDEBAR, encoding="utf-8") as source:
			cls.sidebar = source.read()

	def test_tender_is_in_operations_group(self):
		self.assertIn(
			'names: ["purchasing", "imports", "tender", "inventory"',
			self.sidebar,
		)

	def test_sidebar_uses_role_filtered_tender_children(self):
		for route in (
			"/tender/director",
			"/tender/my-tenders",
			"/tender/po-control",
			"/tender/customs",
			"/tender/logistics",
		):
			self.assertIn(route, self.sidebar)
		self.assertIn("ensureTenderViews", self.sidebar)
		self.assertNotIn("/app/", self.sidebar)

	def test_tender_children_are_deduped_by_path_after_the_role_filter(self):
		"""`/tender/crm` is listed once per view, so a director+sourcing user would
		otherwise see it twice. Dedupe must run AFTER the role filter — deduping the
		raw list first would drop the row for a sourcing-only user."""
		self.assertIn("seen.has(item.path)", self.sidebar)
		self.assertIn("const seen = new Set()", self.sidebar)
		self.assertLess(
			self.sidebar.index("session.tenderViews.includes(item.view)"),
			self.sidebar.index("seen.has(item.path)"),
			"path dedupe must come after the role filter",
		)

	def test_tender_director_bookmark_redirects_to_dashboard(self):
		with open(_ROUTER, encoding="utf-8") as source:
			router = source.read()
		self.assertIn(
			'{ path: "/tender/director", redirect: "/dashboard"',
			router,
		)
		self.assertNotIn(
			'{ path: "/tender/director", name: "tender-director", component: DirectorBoard',
			router,
		)

	def test_tender_subnav_keeps_overview_first_and_restores_director_portfolio(self):
		with open(_TENDER_NAV, encoding="utf-8") as source:
			nav = source.read()
		self.assertIn('to="/dashboard"', nav)
		self.assertIn('t("Overview")', nav)
		self.assertIn('t("Director board")', nav)
		self.assertIn('to="/tender/portfolio"', nav)
		self.assertNotIn('to="/tender/director"', nav)


if __name__ == "__main__":
	unittest.main()
