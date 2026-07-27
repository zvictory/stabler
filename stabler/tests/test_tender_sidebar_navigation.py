"""Regression guards for role-aware Tender navigation in the SPA sidebar."""

from __future__ import annotations

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDEBAR = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "components", "Sidebar.vue"))


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


if __name__ == "__main__":
	unittest.main()
