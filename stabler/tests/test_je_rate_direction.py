"""A journal entry must never post at a rate nobody quoted.

Measured on a USD-base tenant, 29.08.2026. The Exchange rates header read

    1 UZS = [ 11,850.00 ] USD

and the operator typed the number they say out loud — 1 USD = 11 850 сўм. The
label said the opposite, so `toLineRate` stored 11 850 as base-per-1-UZS instead
of 1/11 850, and a 29 625 000 сўм cash line previewed as $351 056 250 000. The
error is the square of the rate: 11 850² ~ 140 million.

Two independent defects had to line up, and both are pinned here:

  1. `readableRate` guessed a direction it could not know. With no rate it
     answered "the account currency is the strong one" — right for a USD account
     in a UZS-base book, backwards for a UZS account in a USD-base book, and
     unknowable either way, because the only thing that settles it is the rate
     that is missing. Now an unknown rate says so and names no direction, and
     the header must not offer an input under a direction it does not have.

  2. `1` passed for a rate. It is what `emptyRow()` gives a new line, no two
     different currencies in this book are pegged 1:1, and `canSubmit` only ever
     asked for `> 0` — so an entry whose rate had never been fetched could be
     saved, booking сўм into a USD ledger one-for-one. That is the quiet version
     of the same bug: it balances, so nothing stops it.

Five tenants book in USD — anjan, dts, laminor, smartbox, zuma — and every one
of them reaches this header through any UZS account.

Scope note: the ledger was NOT corrupted. A wrong rate on one line breaks the
balance and the drawer refuses to save, so the damage was a JE that could not be
entered at all. Across the five USD-base sites exactly one historical document
carries an implausible UZS rate (anjan ACC-JV-2026-00023, 40.32 USD, 2026-03-29,
rate 0.00156705) and it predates this header.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FX = (ROOT / "public/js/composables/fx.js").read_text(encoding="utf-8")
DRAWER = (ROOT / "public/js/components/JournalEntryDrawer.vue").read_text(encoding="utf-8")
MONEY_API = (ROOT / "api/money.py").read_text(encoding="utf-8")


def _squash(text: str) -> str:
	return re.sub(r"\s+", " ", text)


def _fn(src: str, signature: str) -> str:
	"""One function's source, up to the next top-level declaration."""
	start = src.index(signature)
	rest = src[start:]
	end = re.search(r"\n(?:export |function |const |async function |@frappe|def )", rest[1:])
	return rest[: end.start() + 1] if end else rest


class TestAnUnknownRateNamesNoDirection(unittest.TestCase):
	def test_readable_rate_reports_the_unknown_instead_of_guessing(self):
		body = _squash(_fn(FX, "export function readableRate("))
		self.assertIn("unknown: true", body, "readableRate still invents a direction it cannot know")

	def test_the_untouched_default_of_one_counts_as_unknown(self):
		"""`emptyRow()` births a line at 1. If 1 reads as a real quote, the header
		labels the pair backwards and `canSubmit` lets the entry through."""
		self.assertRegex(_squash(_fn(FX, "export function readableRate(")), r"r <= 0 \|\| r === 1")
		self.assertIn("exchange_rate: 1", DRAWER, "emptyRow no longer starts at 1 — revisit this rule")


class TestTheHeaderRefusesToAskForANumberItCannotRead(unittest.TestCase):
	def test_the_rate_input_is_hidden_while_the_direction_is_unknown(self):
		"""The whole defect is an input under a guessed label. No label, no input."""
		self.assertRegex(
			_squash(DRAWER),
			r"<template v-if=\"r\.quote\?\.unknown\">.*?</template> <template v-else>.*?"
			r"<MoneyInput :model-value=\"r\.quote\?\.value",
			"the header still offers a rate input when it does not know the direction",
		)

	def test_the_operator_is_told_why_the_input_is_gone(self):
		"""An input that silently disappears is its own bug report. Say it, and
		leave the refresh button reachable."""
		self.assertIn("No rate for this date", DRAWER)

	def test_setting_a_rate_is_refused_without_a_direction(self):
		"""Belt to the template's braces: `setEntryRate` reads the number against
		`quote.strong`, which an unknown quote does not have."""
		self.assertRegex(
			_squash(_fn(DRAWER, "function setEntryRate(")),
			r"if \(!entry\?\.quote \|\| entry\.quote\.unknown\) return;",
		)


class TestAnUnfetchedRateCannotBeSaved(unittest.TestCase):
	def test_submit_requires_a_real_rate_on_every_foreign_line(self):
		"""`rateOf` returns the raw 1, and `> 0` accepts it. An entry saved that
		way books сўм into a USD ledger one-for-one and balances while doing it,
		so nothing downstream ever questions it."""
		self.assertIn("hasRealRate", DRAWER, "canSubmit still accepts the untouched default rate")
		self.assertRegex(
			_squash(DRAWER),
			r"const hasRealRate = \(r\) => \{ const v = Number\(r\.exchange_rate\) \|\| 0; return v > 0 && v !== 1; \}",
		)

	def test_the_guard_is_wired_into_can_submit(self):
		self.assertRegex(_squash(DRAWER), r"!isForeign\(r\) \|\| hasRealRate\(r\)")


class TestTheRateLookupTriesBothDirections(unittest.TestCase):
	"""ERPNext's `get_exchange_rate` matches `from_currency`/`to_currency`
	exactly and never looks at the mirror row, so a book that stores only
	USD->UZS answers nothing for UZS->USD and falls through to an external API
	call that returns 0 offline. That empty answer is what leaves the row at its
	default of 1 and puts the operator in front of the guessed label."""

	def test_the_endpoint_falls_back_to_the_mirror_rate(self):
		body = _fn(MONEY_API, "def get_exchange_rate_for_currencies(")
		self.assertIn("get_exchange_rate(to_currency, from_currency", body)
		self.assertRegex(_squash(body), r"return flt\(1\.0 / flt\(mirror\)\)|1\.0 / flt\(mirror\)")

	def test_the_mirror_is_only_used_when_the_direct_rate_is_missing(self):
		"""A stored direct rate wins. The mirror is a fallback, not a second
		opinion — inverting a rounded rate loses precision."""
		body = _squash(_fn(MONEY_API, "def get_exchange_rate_for_currencies("))
		self.assertLess(
			body.index("get_exchange_rate(from_currency, to_currency"),
			body.index("get_exchange_rate(to_currency, from_currency"),
		)


if __name__ == "__main__":
	unittest.main()
