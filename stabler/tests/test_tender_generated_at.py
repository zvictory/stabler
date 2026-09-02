"""Every tender screen's payload carries the server's generation time.

Five screens (director board, funnel, process flow, my tenders, contract board)
each showed numbers with no statement of when they were read. Two of them
auto-refresh; a third has no refresh at all. The reader could not tell a figure
computed four seconds ago from one computed at the last navigation.

`operations_desk` already returned `generated_at` (tender_desk.py) and nothing in
the SPA read it — measured 2026-09-02, it was the only such key in the codebase
and it was unread everywhere. The client half is pinned in
public/js/tests/tenderFreshness.spec.js; this is the server half.

Source-level on purpose: the assertion is that the KEY is in the payload, which
needs no database. The same idiom as test_fx_reval.py's endpoint check — see
.github/frappe-free-tests.txt for why a frappe-free test has to stay frappe-free.
"""

import os
import re
import unittest

API = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "tender.py")

# Function -> the screen that goes dark without it.
PAYLOADS = {
	"_tender_director_payload": "director board (prompt 14, P15)",
	"tender_funnel": "funnel (prompt 15, F18)",
	"tender_flow": "process flow (prompt 16, W18)",
	"sourcing_my_tenders": "my tenders (prompt 17, M15)",
	"so_board": "contract board (prompt 18, C20)",
}


def _body(src: str, name: str) -> str:
	"""Source of one top-level function, from its `def` to the next top-level one."""
	m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
	assert m, f"{name} not found in api/tender.py"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestEveryTenderPayloadStampsItself(unittest.TestCase):
	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()

	def test_now_is_imported(self):
		# WHAT WOULD MAKE THIS FAIL: reaching for datetime.now() instead. The stamp
		# must be the SITE's clock — frappe.utils.now() resolves the site timezone,
		# and a naive datetime on a UTC host would put a Tashkent screen five hours
		# in the past, which is worse than no stamp because it looks like one.
		# assertTrue over assertRegex for the same reason as below: assertRegex would
		# print all of tender.py on failure. re.M because the import is not line 1.
		self.assertTrue(
			re.search(r"^from frappe\.utils import .*\bnow\b", self.src, re.M),
			"api/tender.py must import now from frappe.utils",
		)

	def test_each_payload_carries_generated_at(self):
		for fn, screen in PAYLOADS.items():
			with self.subTest(function=fn, screen=screen):
				body = _body(self.src, fn)
				# WHAT WOULD MAKE THIS FAIL: dropping the key from one payload while
				# the other four keep it. The client renders the stamp only when the
				# key is present, so a silent removal does not break the screen — it
				# just stops saying how old it is, which is the exact regression the
				# five screens were in before this change.
				#
				# assertTrue, not assertIn/assertRegex: those print the whole function
				# body on failure. tender.py's payload builders run to hundreds of
				# lines, and a 140 KB traceback is a failure nobody reads.
				self.assertTrue(
					re.search(r'"generated_at"\]?\s*[:=]\s*now\(\)', body),
					f"{fn} must stamp generated_at with frappe.utils.now() — {screen} "
					f"cannot state its freshness without it, and a literal or a "
					f"request-supplied value would not be the server's clock",
				)


if __name__ == "__main__":
	unittest.main()
