"""What the Expense form's source must keep true — read out of `Expenses.vue`.

Two facts, both of them things the screen got wrong while every gate stayed
green, because neither is arithmetic a unit test can reach: a Vue component
cannot be mounted here (`@vue/test-utils` is not a dependency), so this reads
the source, in the same way and for the same reason as
`test_money_input_source.py`. The arithmetic itself lives in
`public/js/tests/fx.spec.js` and `public/js/tests/saveMode.spec.js`; what is
guarded here is that the component actually *calls* it.

1. **The rate field must mean what its label says.** The form built the readable
   quote correctly — label "1 USD =", hint "CBU: 12 953" — and then put the raw
   API answer (0.0000772 USD per сўм) in the input beside it, denominated in USD
   and therefore rendered "0.00". The automatic path posted correctly because it
   sent `1/rate`; the manual correction the screen invited did not. An operator
   who typed the 12 953 the label and the hint both asked for posted a $100
   expense as `100 × 1/12953 = 0.0077` сўм — and the one cross-check on screen,
   the base column in the table footer, printed that as "0". Both directions now
   come from `composables/fx.js`, which is also where the Journal Entry drawer
   and both Sales Order forms read theirs.

2. **A button that says "Save" must save.** The split save button's third item,
   "Save & clear", wrote its own name into `localStorage` and then reset the form
   without calling the API at all. Because the choice persists, the big primary
   button afterwards read "Save & clear" and discarded — no dialog, no toast, no
   undo, on the click an operator makes after typing six expense lines.
"""

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "pages" / "money" / "Expenses.vue"


class TestTheRateShownIsTheRatePosted(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_form(self):
		"""Anchor: if the path drifts, every assertion below reads empty text."""
		self.assertIn("async function fetchExchangeRate()", self.body)
		self.assertIn("payload.exchange_rate", self.body)

	def test_the_direction_helpers_come_from_the_shared_file(self):
		self.assertRegex(self.body, r'import \{[^}]*\} from "\.\./\.\./composables/fx\.js"')

	def test_the_posted_rate_is_converted_by_the_shared_helper(self):
		"""The payload used to hand-roll the reciprocal: `rate > 0 ? 1 / rate : 0`.

		That is correct for a rate the form fetched and wrong for a rate the
		operator typed, and the form could not tell the two apart because it
		never recorded which direction the label had asked for.
		"""
		block = re.search(r"payload\.exchange_rate = (.*?);", self.body, re.S)
		self.assertIsNotNone(block, "could not read the payload rate line — regex has drifted")
		self.assertIn("toLineRate(", block.group(1))
		self.assertNotIn("1 /", block.group(1))

	def test_the_input_holds_the_readable_quote_not_the_raw_api_answer(self):
		"""`form.exchange_rate` is what the operator sees and edits, so it has to
		be the number the label states — not the API's base→payment quote."""
		assignments = re.findall(r"form\.value\.exchange_rate = (.+?);", self.body)
		self.assertTrue(assignments, "no assignment to form.exchange_rate — regex has drifted")
		self.assertNotIn("raw", assignments)
		self.assertIn("rateQuote.value.value", assignments)

	def test_the_base_preview_is_not_a_second_opinion(self):
		"""The footer's base-currency column is the only figure on screen that can
		contradict a wrong rate, so it must be derived the same way the payload
		is. It used to divide by the rate while the payload multiplied by its
		reciprocal — two answers, both wrong, agreeing with each other."""
		block = re.search(r"const baseEquivalent = computed\(\(\) => \{(.*?)\n\}\);", self.body, re.S)
		self.assertIsNotNone(block, "could not read the baseEquivalent computed — regex has drifted")
		self.assertIn("quotedLeg(", block.group(1))
		self.assertNotIn("/ rate", block.group(1))

	def test_the_quote_direction_follows_the_currency_pair_on_screen(self):
		"""A rate lookup that throws must not leave the previous account's
		direction on the label. While these were plain refs, only the success
		branch ever wrote them: switch the payment account to a currency the
		Central Bank has no row for and the label kept naming the old one, over
		an input the operator was being invited to fill in by hand."""
		self.assertIn("const fxBaseCur = computed(", self.body)
		self.assertIn("const fxCounterCur = computed(", self.body)
		self.assertNotIn("fxBaseCur.value =", self.body)
		self.assertNotIn("fxCounterCur.value =", self.body)

	def test_the_rate_input_is_denominated_in_the_other_side_of_the_quote(self):
		"""Under a label reading "1 USD =", the field holds сўм. It was tagged
		`:currency="payCurrency"` — USD, two decimals — which is what rendered a
		12 953 сўм quote as "0.00"."""
		block = re.search(r'<MoneyInput\s+v-model="form\.exchange_rate"(.*?)/>', self.body, re.S)
		self.assertIsNotNone(block, "could not read the rate input — markup has drifted")
		self.assertIn(':currency="fxCounterCur"', block.group(1))
		self.assertNotIn(':currency="payCurrency"', block.group(1))


class TestTheSaveButtonSaves(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_form(self):
		"""Anchor: if the path drifts, every assertion below reads empty text."""
		self.assertIn("const SAVE_MODE_KEY", self.body)
		self.assertIn("async function submitCreate(", self.body)

	def test_the_remembered_mode_is_resolved_never_trusted(self):
		"""Whatever is in the store becomes the primary button's action, and
		"clear" is still in the store of everyone who ever picked it."""
		self.assertIn("resolveSaveMode(localStorage.getItem(SAVE_MODE_KEY))", self.body)

	def test_no_save_mode_skips_the_api(self):
		"""`submitCreate` returned before the call for one of its three modes."""
		block = re.search(r"async function submitCreate\(afterAction\) \{(.*?)\n\}", self.body, re.S)
		self.assertIsNotNone(block, "could not read submitCreate — regex has drifted")
		self.assertNotIn('afterAction === "clear"', block.group(1))

	def test_discarding_the_form_says_so_and_asks_first(self):
		"""Same gate as `cancelEntry` and `deleteEntry` on this screen: a
		destructive action confirms, and the label names the destruction."""
		block = re.search(r"async function clearForm\(\) \{(.*?)\n\}", self.body, re.S)
		self.assertIsNotNone(block, "could not read clearForm — regex has drifted")
		self.assertIn("danger: true", block.group(1))
		self.assertIn('t("Clear form")', self.body)
		self.assertNotIn('t("Save & clear")', self.body)
