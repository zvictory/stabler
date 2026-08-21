"""The transfer form's exchange-rate wiring — read out of the source.

What is protected: `Transfers.vue` must decide what a change does to the rate
through `planRateRefresh()` in `composables/exchangeRatePolicy.js`, must not
clear the typed-rate mark inside its posting-date watcher, and must tell the
user when it kept or replaced a rate they typed.

Why that matters, measured. The form held two answers to one question. Its
account watcher cleared `rateManuallyEdited` — correct, and the same rule the
journal applies on an account change. Its posting-date watcher cleared it too:

    // Date changes: always re-fetch and show THAT date's CBU rate (the rate is
    // a function of the posting date, so a date change re-anchors it).
    watch(() => form.value.posting_date, async () => {
        rateManuallyEdited.value = false;      # <- the whole defect
        await fetchExchangeRate();

so correcting a mistyped posting date discarded the rate the user had entered
from the bank statement. Twelve lines above, the flag's own comment claimed the
opposite behaviour ("so date changes don't clobber it").

The comment was right and the watcher was wrong, for three reasons that are all
visible in this file. A transfer's two legs are observed bank movements at the
bank's rate, so the rate is the residual of two facts rather than an estimate
the Central Bank can correct. `openEditFromDetail` already treats stored amounts
as authoritative, deriving the rate from them under a `hydrating` guard so the
live rate cannot overwrite them. And submit sends `to_amount` as authoritative
with `to_amount / from_amount` as the rate, while `derive()` re-computes
`to_amount` whenever the rate is replaced — so a silent substitution here
changes how much money lands in the destination account, not merely how a
valuation reads.

That is the defect class behind the 675 submitted purchase invoices on
msa.erpstable.com carrying a rate that is not the Central Bank rate for their
own posting date (363 at rate 0, 312 at a hardcoded 12 800 — hundreds of
billions of so'm), pointed at the second leg of a real bank transfer.

`exchangeRatePolicy.spec.js` covers the decision itself; this file covers the
wiring that must keep reaching it. A Vue component cannot be mounted
(@vue/test-utils is not a dependency here), so the test reads the source. That
is weak verification, but what it guards is a small set of structural facts, and
the edit that breaks any of them changes exactly this text.
"""

import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "public" / "js" / "pages" / "money" / "Transfers.vue"
COMPOSABLE = Path(__file__).parents[1] / "public" / "js" / "composables" / "exchangeRatePolicy.js"


class TestTransferRateWiring(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.body = SOURCE.read_text(encoding="utf-8")
		cls.composable = COMPOSABLE.read_text(encoding="utf-8")

	def _watcher_block(self, marker):
		"""The body of the watch() call whose source starts at `marker`."""
		start = self.body.index(marker)
		end = self.body.index("\n);", start)
		return self.body[start:end]

	def test_the_test_reads_the_form(self):
		"""Anchor: if the path drifts, every assertion below verifies empty text."""
		self.assertIn("get_exchange_rate_for_currencies", self.body)
		self.assertIn("export function rateChangeNotice", self.composable)

	def test_the_watchers_ask_the_shared_planner_instead_of_deciding_for_themselves(self):
		"""Both watchers route through one policy. Two watchers deciding
		separately is how this form ended up contradicting itself, and how it
		ended up contradicting the purchase invoice and the journal."""
		self.assertIn('from "../../composables/exchangeRatePolicy.js"', self.body)
		self.assertIn("planRateRefresh(", self.body)
		self.assertIn("rateManuallyEdited.value = plan.seen.rateTouched;", self.body)

	def test_the_posting_date_watcher_no_longer_discards_a_typed_rate(self):
		"""The defect, in the one place it lived. A date change re-anchors an
		AUTO rate and must not touch one the user typed; clearing the mark here
		is what made the typed rate disappear."""
		block = self._watcher_block("() => form.value.posting_date,")
		self.assertNotIn("rateManuallyEdited.value = false", block)
		self.assertIn("reanchorRate()", block)

	def test_the_account_watcher_still_discards_a_typed_rate(self):
		"""The other half, and it is not optional: a different account pair is a
		different rate question, so the mark must not survive it. Protecting the
		typed rate everywhere would strand a USD→UZS rate on a EUR→UZS
		transfer."""
		block = self._watcher_block("() => [form.value.from_account, form.value.to_account],")
		self.assertIn("reanchorRate()", block)
		self.assertIn("currency: `${fromCurrency.value}→${toCurrency.value}`", self.body)

	def test_the_form_says_what_it_did_to_the_rate(self):
		"""Silently keeping a rate is the same defect as silently replacing one.
		A user who moves the posting date has every reason to assume the rate
		followed it, because until 2026-08-21 it did."""
		self.assertIn("rateChangeNotice(", self.body)
		self.assertIn('notice.kind === "kept"', self.body)
		self.assertIn('notice.kind === "reset"', self.body)

	def test_the_planner_is_told_which_document_is_on_screen(self):
		"""How an install is told apart from an edit. Without `docName`, opening
		a saved transfer for amend looks exactly like the user moving the date,
		and the previous document's typed mark would be reported against it."""
		self.assertIn("docName: editingName.value || null,", self.body)
		self.assertIn("seedRateSeen();", self.body)


if __name__ == "__main__":
	unittest.main()
