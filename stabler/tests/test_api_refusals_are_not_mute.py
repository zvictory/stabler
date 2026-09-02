"""A refusal the browser cannot read is not a refusal — it is "Request failed: 417".

`frappe.throw` and `raise frappe.ValidationError` look interchangeable and are
not. `throw` goes through `msgprint`, which appends the text to
`frappe.local.message_log`; the response layer emits `_server_messages` only
when that log is non-empty. A bare `raise` skips all of it, and production
strips `exception`/traceback from the payload as well — so the SPA client
(`public/js/api/client.js`, which reads `_server_messages` first and falls back
to `exception || _error_message || message`) is left with nothing to show but
the literal `Request failed: ${res.status}`.

Measured on anjan prod 2026-09-02, calling `create_direct_sales_return` with a
rate of 0:

    exception            frappe.ValidationError, http 417
    exception args       ('Return rate must be greater than zero for SDX498.',)
    frappe.local.message_log   []          <- the text never leaves the server

The operator saw a red bar reading `Request failed: 417` and nothing else, on a
credit note that was one keystroke from correct. The message existed the whole
time; only the transport was missing.

This is a source guard, not a behaviour test, and that is deliberate: the
behaviour test needs a bench (`_()` wants a site, `message_log` is only bound
after `frappe.init`) and so cannot run in `make check`. The rule this pins is
cheap to state and easy to break by copy-paste, which is exactly how it spread
to three modules in the first place.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
API_SOURCES = sorted(API_DIR.rglob("*.py"))

# The three modules that route their refusals through a `_validation_error`
# helper. Every one of them was mute.
HELPER_MODULES = ("sales.py", "pos.py", "service.py")


def _hits(pattern: str) -> list[str]:
	"""Every `path:line` under stabler/api/ whose line matches *pattern*."""
	found = []
	for path in API_SOURCES:
		lines = path.read_text(encoding="utf-8").splitlines()
		for number, line in enumerate(lines, 1):
			if re.search(pattern, line):
				found.append(f"{path.relative_to(ROOT)}:{number}")
	return found


def _helper_body(module: str) -> str:
	"""The indented body of `def _validation_error(...)` in *module*."""
	src = (API_DIR / module).read_text(encoding="utf-8")
	match = re.search(
		r"def _validation_error\([^)]*\)[^:]*:\n((?:[ \t]+.*\n|\n)*)",
		src,
	)
	assert match, f"{module} has no _validation_error helper"
	return match.group(1)


class ApiRefusalsAreNotMute(unittest.TestCase):
	def test_no_refusal_is_raised_bare(self):
		"""A bare raise produces no _server_messages, so the SPA shows a status code."""
		self.assertEqual(
			_hits(r"raise\s+frappe\.ValidationError\("),
			[],
			"bare raise -> empty message_log -> the user reads 'Request failed: 417'. "
			"Use frappe.throw() so the text reaches the browser.",
		)

	def test_every_validation_error_helper_throws(self):
		for module in HELPER_MODULES:
			with self.subTest(module=module):
				body = _helper_body(module)
				self.assertIn(
					"frappe.throw(message)",
					body,
					f"api/{module}: _validation_error must throw, not raise",
				)
				self.assertNotIn("raise frappe.ValidationError", body)

	def test_no_refusal_is_written_as_an_f_string(self):
		"""An f-string message can never be translated.

		The harvester matches string literals only, so an f-string is invisible
		to it, and at runtime `_()` would be handed an already-interpolated
		sentence that no catalogue can contain. `_("...{0}...").format(x)` keeps
		the key harvestable and the value substituted.
		"""
		self.assertEqual(
			_hits(r"_validation_error\(\s*f[\"']"),
			[],
			'f-string refusal is unharvestable; use _("...{0}...").format(...)',
		)


if __name__ == "__main__":
	unittest.main()
