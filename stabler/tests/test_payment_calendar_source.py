"""payment_calendar's overdue flag must not crash on its own type contract.

stabler.api.imports.payment_calendar (WP-I16) builds `today_d = today()` and
later flags each bill with `getdate(r["due_date"]) < today_d`. frappe.utils
today() returns a str ("yyyy-mm-dd"); getdate() returns a real datetime.date.
Comparing them with `<` raised in production (msa.erpstable.com, 4x, latest
2026-08-20 20:03:57):

    '<' not supported between instances of 'datetime.date' and 'str'

`imports.py` pulls in erpnext transitively (via _accounts.py) and is not
importable without a live bench, so this is Frappe-free the way
test_imports_api_invariants.py is: it reads the real source text and pins a
property of it. It goes one step further and actually executes the extracted
expression -- with the real frappe.utils.getdate -- so the pin is behavioral
(does it raise / does it answer correctly), not just textual. today() itself
needs a site (System Settings -> frappe.client_cache), so `today_d` is built
here as a plain ISO string -- the exact type+format today() is documented to
return -- rather than calling the real clock.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_payment_calendar_source -v
"""

from __future__ import annotations

import datetime
import os
import re
import unittest

from frappe.utils import getdate

_HERE = os.path.dirname(os.path.abspath(__file__))
_API = os.path.normpath(os.path.join(_HERE, "..", "api"))


def _read(name: str) -> str:
	with open(os.path.join(_API, name), encoding="utf-8") as f:
		return f.read()


def _overdue_expr(src: str) -> str:
	"""Pull the literal RHS of `r["overdue"] = ...` out of payment_calendar."""
	m = re.search(r'r\["overdue"\]\s*=\s*(bool\([^\n]*\))\s*\n', src)
	assert m, "payment_calendar's overdue assignment was not found -- did the line move?"
	return m.group(1)


class TestPaymentCalendarOverdueTypeContract(unittest.TestCase):
	"""imports.py:payment_calendar -- the today()/getdate() type contract.

	An overdue supplier bill must be reported overdue, not take the whole
	calendar response down with a TypeError every other row in the same
	response also depended on.
	"""

	def setUp(self):
		self.expr = _overdue_expr(_read("imports.py"))

	def _overdue(self, due_date, today_d):
		"""Evaluate the real extracted expression, exactly as imports.py wrote it.

		eval() here runs a snippet regex-extracted from this repo's own
		stabler/api/imports.py (never external/user input), in a test process,
		with an explicit two-name namespace -- it is the whole point of the
		test (proving the actual source line is or isn't type-safe), not a
		shortcut around writing real code.
		"""
		return eval(self.expr, {"getdate": getdate}, {"r": {"due_date": due_date}, "today_d": today_d})

	def test_an_overdue_bill_is_flagged_overdue(self):
		# The actual business rule: a bill whose due date has passed must be
		# reported overdue so Accounts pays it. Far enough in the past that no
		# `days` window edge case coincidentally hides it.
		today_d = "2026-08-21"
		self.assertTrue(self._overdue("2020-01-01", today_d))

	def test_a_not_yet_due_bill_is_not_overdue(self):
		today_d = "2026-08-21"
		self.assertFalse(self._overdue("2099-01-01", today_d))

	def test_a_bill_with_no_due_date_is_not_overdue(self):
		today_d = "2026-08-21"
		self.assertFalse(self._overdue(None, today_d))

	def test_today_is_a_plain_string_and_the_comparison_still_works(self):
		# Pins the TYPE, not just the outcome. frappe.utils.today() is
		# documented to return a str ("yyyy-mm-dd" -- frappe/utils/data.py);
		# building today_d any other way here would let a fix that only
		# happens to work on an already-date-typed value slip through.
		today_d = datetime.date.today().isoformat()
		self.assertIsInstance(today_d, str)
		self.assertIsInstance(getdate("2020-01-01"), datetime.date)
		try:
			overdue = self._overdue("2020-01-01", today_d)
		except TypeError as exc:
			self.fail(
				f"overdue comparison raised {exc!r} -- a datetime.date is being "
				"compared against a raw str again (imports.py:payment_calendar)"
			)
		else:
			self.assertTrue(overdue)


if __name__ == "__main__":
	unittest.main()
