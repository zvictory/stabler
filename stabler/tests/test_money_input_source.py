"""`MoneyInput`'s fraction-digit contract — read out of the source.

What is protected: the component must take a currency's precision from
`moneyFractionDigits()` in `composables/money.js` and must not carry a second
copy of the policy in its own branches.

Why that matters, measured: the component used to decide precision itself with
an `isUZS` branch, and that branch said 0 — so a Mikas user typing an opening
balance of 1 500 000,50 so'm watched `onBlur` round it to 1 500 001 and post
that. ERPNext stores UZS at precision 2 on every tenant (`currency_precision`
unset, `use_number_format_from_currency` 0, global format "#,###.##"), so the
ledger had room for the kopecks all along. One policy in two places is how the
form and the ledger came to disagree; this file exists to keep it in one.

The zero-digit branch is kept and still wins over the unit-price override,
because a currency with no sub-unit (JPY, KRW) genuinely cannot show one and an
override of 4 must not invent it.

A JS component cannot be mounted (@vue/test-utils is not a dependency here), so
the test reads the source. That is weak verification, but what it guards is a small set of
structural facts, and the edit that breaks any of them changes exactly this
text. `money.spec.js` covers the arithmetic itself.
"""

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "components" / "MoneyInput.vue"
MONEY = Path(__file__).parents[1] / "public" / "js" / "composables" / "money.js"


class TestMoneyInputFractionContract(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")

	def test_the_test_reads_the_component(self):
		"""Anchor: if the path drifts, every assertion below verifies empty text."""
		self.assertIn("const maxFractionDigits = computed(", self.body)

	def test_precision_comes_from_the_shared_helper(self):
		self.assertIn("moneyFractionDigits", self.body)

	def test_the_component_keeps_no_second_copy_of_the_currency_policy(self):
		"""`isUZS` may still pick the сўм badge; it may not decide precision.

		This is the actual regression. While the component branched on the
		currency itself, `money.js` and `MoneyInput.vue` could disagree about
		what UZS is — and for two years they did, silently, in the direction that
		destroyed data.
		"""
		for name in ("minFractionDigits", "maxFractionDigits"):
			block = re.search(
				rf"const {name} = computed\(\(\) => \{{(.*?)\n\}}\);", self.body, re.S
			) or re.search(rf"const {name} = computed\(\(\) => (.*?);\n", self.body, re.S)
			self.assertIsNotNone(block, f"could not read the {name} computed — regex has drifted")
			self.assertNotIn(
				"isUZS",
				block.group(1),
				f"{name} branches on the currency itself instead of asking moneyFractionDigits",
			)

	def test_a_sub_unit_less_currency_wins_over_the_unit_price_override(self):
		"""JPY has no sub-unit, so `maxFractionDigits=4` must not create one."""
		block = re.search(r"const maxFractionDigits = computed\(\(\) => \{(.*?)\n\}\);", self.body, re.S)
		self.assertIsNotNone(block, "could not read the maxFractionDigits computed — regex has drifted")
		body = block.group(1)
		zero_guard = body.index("=== 0")
		override = body.index("props.maxFractionDigits")
		self.assertLess(
			zero_guard,
			override,
			"the override is consulted before the zero-digit guard — a whole-unit currency would show sub-units",
		)

	def test_the_grouped_display_follows_the_same_maximum(self):
		"""Live grouping is where typing gets cut. A hardcoded 2 would clip a unit
		price under the key: 4,4150 typed, 4,41 kept.

		The cut moved into `groupMoneyWhileTyping` on 2026-08-21 so a test could
		run it against `parseMoneyInput`, which has to read its output back. The
		contract is therefore in two halves and both are pinned: the component
		must hand its own maximum down, and the helper must cut by the number it
		was handed rather than one of its own.
		"""
		self.assertIn(
			"groupMoneyWhileTyping(text, props.language, maxFractionDigits.value)",
			self.body,
			"MoneyInput no longer passes its own maximum down to the live grouper",
		)
		money = MONEY.read_text(encoding="utf-8")
		block = re.search(r"export function groupMoneyWhileTyping\((.*?)\n\}", money, re.S)
		self.assertIsNotNone(block, "could not read groupMoneyWhileTyping — has it moved again?")
		self.assertIn(
			'parts.slice(1).join("").slice(0, maxFractionDigits)',
			block.group(1),
			"the live grouper cuts by something other than the maximum it was given",
		)


if __name__ == "__main__":
	unittest.main()
