"""Static guard (WP-311): no hand-rolled absolute-positioned suggestion dropdowns.

A `position-absolute` options list rendered inline gets CLIPPED by any ancestor
with overflow (e.g. `.table-responsive` inside a modal) — the Stock Entry item
picker bug. The sanctioned picker is the shared Typeahead component, which
Teleports its menu to <body> with fixed positioning and therefore can never be
clipped. This test fails if a page/component reintroduces the inline pattern.

Typeahead.vue itself is excluded (it owns the one legitimate implementation).
"""

from __future__ import annotations

import os
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../stabler
_JS_ROOT = os.path.join(_APP_ROOT, "public", "js")

# The clipped-dropdown fingerprint: an inline absolutely-positioned list-group.
_FORBIDDEN = "list-group position-absolute"
_ALLOWED_FILES = {"Typeahead.vue"}


def _vue_files():
	for base in ("pages", "components"):
		root = os.path.join(_JS_ROOT, base)
		for dirpath, _dirs, files in os.walk(root):
			for fn in files:
				if fn.endswith(".vue") and fn not in _ALLOWED_FILES:
					yield os.path.join(dirpath, fn)


class TestNoInlineDropdowns(unittest.TestCase):
	def test_no_inline_absolute_suggestion_dropdowns(self):
		offenders = []
		for path in _vue_files():
			with open(path, encoding="utf-8") as fh:
				if _FORBIDDEN in fh.read():
					offenders.append(os.path.relpath(path, _JS_ROOT))
		self.assertEqual(
			offenders,
			[],
			"Hand-rolled absolute dropdowns get clipped by overflow containers. "
			"Use the shared Typeahead (teleported to <body>) instead: " + ", ".join(offenders),
		)


if __name__ == "__main__":
	unittest.main()
