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

	def test_tender_subnav_is_overview_first_without_director_button(self):
		with open(_TENDER_NAV, encoding="utf-8") as source:
			nav = source.read()
		self.assertIn('to="/dashboard"', nav)
		self.assertIn('t("Overview")', nav)
		self.assertNotIn('t("Director board")', nav)
		self.assertNotIn('to="/tender/director"', nav)


if __name__ == "__main__":
	unittest.main()
