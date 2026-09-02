"""A deal card states the currency the deal was entered in, and who owns it.

Two defects, both reported from a live screen on 2026-09-02 and both the same
shape: `crm_board` builds the card payload by hand, and two fields the intake
already stores never made it into it.

1. CURRENCY. The drawer offers a currency picker (TenderMasterDrawer.vue,
   `form.currency`, default USD) and `_clean_intake` stores it — "currency" is in
   `_INTAKE_KEYS_STR`. `crm_board` ignored it and wrote `"currency": base_ccy`,
   the company default, onto every card unconditionally. A deal entered as
   USD 15,000 rendered "15 000,00 сўм" on the card, in the drawer, in the lane
   total and in the pipeline KPI. Worse than a wrong label: opening Edit read
   that base currency back into `form.currency`, so the next save cemented it.

2. ASSIGNED TO. `assign_tender` writes `assigned_to`/`assigned_to_name` into the
   intake and four other screens read them back. The card payload carried
   `owner`* but not `assigned_to`, so the drawer's picker showed the assignment
   until the next load and "— Unassigned —" after it. The write was never lost;
   the read was never wired.

   * `owner` is the Frappe document owner — who CREATED the deal. It is not the
     assignment and cannot stand in for it.

Source-level on purpose: the claim is that the payload carries the keys, which
needs no database. Same idiom as test_tender_generated_at.py — see
.github/frappe-free-tests.txt for why a frappe-free test has to stay frappe-free.
That the values round-trip through a real save is `make test-bench` territory and
is NOT claimed here.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api", "tender.py")


def _body(src: str, name: str) -> str:
	"""Source of one top-level function, from its `def` to the next top-level one."""
	m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
	assert m, f"{name} not found in api/tender.py"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@|def )", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class TestDealCardCarriesWhatTheIntakeStores(unittest.TestCase):
	def setUp(self):
		with open(API, encoding="utf-8") as fh:
			self.src = fh.read()
		self.board = _body(self.src, "crm_board")

	def test_the_intake_still_stores_a_currency(self):
		# WHAT WOULD MAKE THIS FAIL: dropping "currency" from the intake contract.
		# The card can only report what is stored, so this is the precondition for
		# every other assertion here — and it is the half that was already correct,
		# which is why the defect was a read and not a write.
		m = re.search(r"^_INTAKE_KEYS_STR = \(([\s\S]*?)^\)", self.src, re.M)
		self.assertIsNotNone(m, "_INTAKE_KEYS_STR has moved")
		self.assertIn('"currency"', m.group(1))

	def test_the_card_does_not_stamp_the_company_currency_over_it(self):
		# WHAT WOULD MAKE THIS FAIL: `"currency": base_ccy` coming back. That single
		# line is the whole defect — it took a figure the user entered in one
		# currency and labelled it with another, everywhere the deal appears. A
		# fallback for a deal that names no currency is fine and is asserted below;
		# an unconditional assignment is not.
		#
		# Boolean form, not assertNotIn: a failing assertNotIn prints the haystack,
		# and crm_board's body is ~250 lines. A traceback nobody reads is a test
		# that does not report.
		self.assertFalse(
			'"currency": base_ccy,' in self.board,
			"crm_board must not label every card with the company currency",
		)

	def test_the_card_reports_the_currency_the_deal_was_entered_in(self):
		# WHAT WOULD MAKE THIS FAIL: reading the value from the intake and the
		# currency from anywhere else. The amount and its unit come from the same
		# place or they do not belong together: `estimated_total` and `currency` are
		# two fields of one thing the user typed on one form.
		#
		# Both halves, because computing `ccy` and then not using it is exactly what
		# a half-revert looks like: the mutation pass restored `"currency": base_ccy`
		# and this test stayed green on the surviving read above it.
		self.assertTrue(
			re.search(r'ccy = str\(intake\.get\("currency"\)', self.board),
			"crm_board must read the deal's currency out of the intake",
		)
		self.assertTrue(
			re.search(r'"currency": ccy or base_ccy,', self.board),
			"the card payload must REPORT that currency, falling back to the company's "
			"only when the deal names none",
		)

	def test_the_card_carries_the_assignment(self):
		# WHAT WOULD MAKE THIS FAIL: dropping either key. The drawer binds its picker
		# to selectedDeal.assigned_to; without the key in the payload the control
		# reads empty on every load, so an assignment that WAS saved looks lost and
		# the user re-assigns — over and over, because re-assigning cannot fix a
		# missing read.
		for key in ("assigned_to", "assigned_to_name"):
			with self.subTest(key=key):
				self.assertTrue(
					re.search(rf'"{key}": intake\.get\("{key}"\)', self.board),
					f"crm_board's card payload must carry {key} from the intake",
				)

	def test_the_board_states_the_base_currency_and_its_rates(self):
		# WHAT WOULD MAKE THIS FAIL: dropping either key from the response. The
		# client cannot convert without both, and it deliberately renders NO
		# converted figure rather than a guessed one — so a missing key silently
		# removes the whole base-currency companion line instead of breaking.
		self.assertTrue(
			re.search(r'"base_currency": base_ccy', self.board),
			"crm_board must name the currency its rates convert TO",
		)
		self.assertTrue(
			re.search(r'"rates": rates', self.board),
			"crm_board must return the rate table the companion line needs",
		)

	def test_the_rate_is_the_cbu_rate_the_ledger_already_uses(self):
		# WHAT WOULD MAKE THIS FAIL: a hardcoded rate, or a second rate source.
		# .claude/rules/10-frontend.md requires a live rate and never a literal, and
		# _cbu_rate_on_or_before is what validate_exchange_rate measures every real
		# document against — a screen hint disagreeing with the ledger's own
		# validator would be a second answer to one question.
		self.assertIn("cbu_rate_on_or_before", self.board)
		# ...and it is the SAME function, not a second copy that could drift: the
		# body moved to _fx_rates on 2026-09-02 (because _accounts imports erpnext at
		# module level and crm_board has to be reachable from the frappe-free suite),
		# and _accounts re-exports it under the name its six callers already use.
		with open(os.path.join(HERE, "..", "api", "_accounts.py"), encoding="utf-8") as fh:
			accounts = fh.read()
		self.assertIn(
			"from stabler.api._fx_rates import cbu_rate_on_or_before as _cbu_rate_on_or_before",
			accounts,
			"_accounts must re-export the moved reader, or validate_exchange_rate and this "
			"screen are measuring against two different rates",
		)
		self.assertNotIn(
			"def _cbu_rate_on_or_before(",
			accounts,
			"a second copy of the rate reader is back in _accounts",
		)
		self.assertFalse(
			re.search(r"\b1[0-9]{4}(\.[0-9]+)?\b", self.board),
			"a five-digit literal in crm_board reads like a hardcoded UZS rate",
		)

	def test_a_currency_with_no_rate_is_simply_absent(self):
		# WHAT WOULD MAKE THIS FAIL: writing a 0 or a 1.0 placeholder into the table.
		# The client renders nothing when the key is missing; a 0 would render
		# "≈ 0,00 сўм" and a 1.0 would render the foreign figure with the base
		# symbol — the exact defect this whole change exists to remove.
		m = re.search(r"rates: dict\[str, dict\] = \{\}([\s\S]*?)\n\treturn \{", self.board)
		self.assertIsNotNone(m, "the rate-table block has moved")
		block = m.group(1)
		self.assertTrue(
			re.search(r"if rate and flt\(rate\) > 0:", block),
			f"the rate table must only carry a positive rate: {block[-200:]}",
		)
		self.assertNotIn("or 1.0", block)
		self.assertNotIn('"rate": 0', block)

	def test_the_base_currency_needs_no_rate(self):
		# WHAT WOULD MAKE THIS FAIL: looking up base -> base. It is 1 by definition,
		# CBU stores no such row, so the lookup returns nothing and every card in the
		# company's own currency would lose its total.
		self.assertTrue(
			re.search(r"!=\s*base_ccy", self.board),
			"crm_board must skip the company's own currency when building rates",
		)

	def test_owner_is_still_reported_separately(self):
		# WHAT WOULD MAKE THIS FAIL: "fixing" the assignment by renaming owner. They
		# are different facts — owner is who created the deal, assigned_to is who is
		# working it — and the card's avatar initials are built from the owner. One
		# replacing the other would silently relabel every card on the board.
		self.assertIn('"owner": owner,', self.board)
		self.assertIn('"owner_name": owner_name,', self.board)


if __name__ == "__main__":
	unittest.main()
