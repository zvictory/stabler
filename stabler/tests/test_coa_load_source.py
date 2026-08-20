"""The chart of accounts fetches its two halves at once, and keeps its balances.

Two facts about `Accounts.vue`'s load path, both of which were false until
2026-08-20 and neither of which any other test could see.

1. The tree and the balances are independent queries — `chart_of_accounts`
   reads the Account table, `chart_balances` runs one GROUP BY over GL Entry —
   and they were awaited one after the other. Measured on the local bench,
   where latency is ~0: the tree ran 563-597ms and the balances started at 606.
   On prod each of those gaps is a real round trip (~0.4s of TTFB measured
   against mikas), so the page spent one waiting for nothing.

2. `load()` cleared `balances` on its way past. That is right for a company
   switch and wrong everywhere else, and the `includeDisabled` watcher calls
   `load()` alone: ticking "include disabled" wiped every balance on screen
   and nothing fetched them back. Measured in a browser: 19 rows showing a
   number before the click, 0 after. `chart_balances` returns the full tree
   including disabled accounts, so that toggle cannot change a balance at all.

Read from the source, because a Vue SFC cannot be mounted without a Frappe
bootstrap. That limit is real and worth stating plainly: this pins the SHAPE
that produces the behaviour, not the behaviour. Both facts above were verified
in a browser against the local bench; what these assertions defend against is
someone re-serialising the calls or putting the clear back, not a subtler way
of breaking the same thing.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "pages" / "money" / "Accounts.vue"


class TestChartOfAccountsLoadPath(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def _block(self, name: str) -> str:
		match = re.search(rf"(?:async )?function {name}\(.*?\) \{{(.*?)\n\}}", self.body, re.S)
		self.assertIsNotNone(match, f"could not read {name} — has it been renamed?")
		return match.group(1)

	def test_the_two_fetches_are_in_flight_together(self):
		block = self._block("loadAll")
		self.assertIn("Promise.all", block, "the tree and the balances are serialised again")
		self.assertIn("load()", block)
		self.assertIn("loadBalances()", block)

	def test_nothing_awaits_the_tree_before_asking_for_the_balances(self):
		"""The old shape, spelled out, so it cannot come back by hand.

		`await load()` immediately followed by `await loadBalances()` is exactly
		the serialisation this change removed, and it reads perfectly natural —
		which is why it needs naming rather than trusting the check above.
		"""
		self.assertNotRegex(
			self.body,
			r"await load\(\);\s*\n\s*await loadBalances\(\);",
			"the two calls are awaited in sequence again",
		)

	def test_loading_the_tree_does_not_throw_the_balances_away(self):
		block = self._block("load")
		self.assertNotIn(
			"balances.value = new Map()",
			block,
			"load() clears the balances again — ticking 'include disabled' will blank them",
		)

	def test_switching_company_still_clears_them(self):
		"""The one case where clearing IS correct, and it must survive the fix.

		Balances are keyed by account name and companies share none, but a stale
		map sitting against the incoming company's tree for the length of a round
		trip is a wrong number on screen, not a blank one.
		"""
		match = re.search(r"watch\(activeCompany, async \(\) => \{(.*?)\n\}\);", self.body, re.S)
		self.assertIsNotNone(match, "could not read the activeCompany watcher")
		self.assertIn("balances.value = new Map()", match.group(1))


if __name__ == "__main__":
	unittest.main()
