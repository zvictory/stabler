"""Regression guards for the sidebar profile menu.

The menu must escape the sidebar's scroll container, open above its trigger,
and remain keyboard-accessible. These source-level guards run without a browser
or Frappe site and protect the layout contract that caused the production bug.
"""

from __future__ import annotations

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDEBAR = os.path.normpath(os.path.join(_HERE, "..", "public", "js", "components", "Sidebar.vue"))


class TestSidebarProfileMenu(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(_SIDEBAR, encoding="utf-8") as source:
			cls.sidebar = source.read()

	def test_menu_escapes_sidebar_scroll_and_opens_above_trigger(self):
		self.assertIn('<Teleport to="body">', self.sidebar)
		self.assertIn('position: "fixed"', self.sidebar)
		self.assertIn("bottom: `${window.innerHeight - rect.top + 4}px`", self.sidebar)
		self.assertIn("Math.max(0, rect.top - gap - viewportPadding)", self.sidebar)
		self.assertIn("maxHeight:", self.sidebar)
		self.assertNotIn("Math.max(96", self.sidebar)
		self.assertNotIn('data-bs-toggle="dropdown"', self.sidebar)

	def test_menu_closes_accessibly_and_restores_trigger_focus(self):
		for contract in (
			'aria-haspopup="menu"',
			':aria-expanded="userMenuOpen"',
			'event.key === "Escape"',
			"userMenuTrigger.value?.focus()",
			"document.addEventListener",
			"document.removeEventListener",
		):
			self.assertIn(contract, self.sidebar)


if __name__ == "__main__":
	unittest.main()
