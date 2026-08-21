// When a form's exchange rate should follow its posting date — one answer, for
// every money form that asks.
//
// Named for the invoice until 2026-08-21, because the invoice was the second
// form to ask and the first to put the answer somewhere testable. The transfer
// form was the third, and it had answered the opposite way; renaming the file
// is how the shared rule stops looking like one screen's private business.
//
// The rate is fetched `as of` the posting date, and the form watches the date —
// but it applied what came back only when the field was empty
// (`if (!Number(form.value.conversion_rate))`). Backdate an invoice that
// already carries a rate and the correct rate for the new date was fetched and
// then thrown away: the invoice kept the rate of a date it no longer has, with
// nothing on screen to say so, and ERPNext books whatever rate the form sends.
// On msa.erpstable.com 675 submitted purchase invoices carry a rate that is not
// the Central Bank rate for their own date — 363 at rate 0, 312 at a hardcoded
// 12 800 — worth hundreds of billions of so'm in the wrong direction.
//
// Overwriting on every date change is the same defect pointing the other way:
// it wipes the contract rate or the bank's actual rate that the user typed on
// purpose. `composables/journal.js` already settled that tension for the
// journal entry — `ratesToRefresh()` skips a line whose `_rateTouched` is set,
// and `JournalEntryDrawer.vue` clears the mark when the account changes,
// because a different account is a different rate question. This is the same
// rule for the invoice: a different currency is a different rate question.
//
// `ratesToRefresh()` itself is not reused here. It filters a list of journal
// *lines*, each carrying its own rate, and returns the subset to refetch; an
// invoice has one rate on the header and needs a yes/no. More importantly it
// answers only half the question. The other half — telling "the user moved the
// date" apart from "a document was just installed in the form" — lives inline
// in the drawer as a `formDate` sentinel, seeded in the same synchronous block
// that assigns the form. This form cannot do that: `useDocumentForm.load()`
// owns the assignment, so nothing here can seed a sentinel before the watcher
// observes the new values. `docName` is the discriminator instead — it changes
// exactly when a different document takes the screen, and never when the user
// edits the one in front of them.
//
// Getting that half wrong is worse than the bug being fixed: opening a saved
// draft would rewrite the rate it was saved with before the user touched
// anything.

/**
 * Decide whether the fetched rate for the new posting date should be applied,
 * and advance the state the caller compares against next time.
 *
 * @param {{docName: ?string, currency: string, postingDate: string, rateTouched: boolean}} seen
 *        what the form last showed us
 * @param {{docName: ?string, currency: string, postingDate: string, editable: boolean, isForeign: boolean}} next
 *        what it shows now
 * @returns {{refresh: boolean, seen: object}}
 */
export function planRateRefresh(seen, next) {
	const installed = seen.docName !== next.docName;
	const currencyChanged = !installed && seen.currency !== next.currency;
	const dateChanged = !installed && seen.postingDate !== next.postingDate;

	// A rate typed for one currency says nothing about another, and a document
	// arriving on screen carries its own saved rate — neither is a mark the
	// user made against what is now in front of them.
	const rateTouched = installed || currencyChanged ? false : Boolean(seen.rateTouched);

	return {
		refresh:
			Boolean(next.editable) &&
			Boolean(next.isForeign) &&
			(currencyChanged || dateChanged) &&
			!rateTouched,
		// Which of the three transitions fired. Exposed so the caller can tell
		// the user what happened to their rate without recomputing the diff and
		// drifting out of step with the decision above.
		reason: installed ? "installed" : currencyChanged ? "currency" : dateChanged ? "date" : "none",
		// Whether a rate the user typed was on screen when this transition
		// began. Suppressed on an install: the mark belonged to the document
		// that just left, so reporting it would announce a loss that never
		// happened to anything the user can see.
		hadTypedRate: !installed && Boolean(seen.rateTouched),
		// Advanced even when the refresh is refused, so the next real edit is
		// compared against what is on screen and not a date two edits stale.
		seen: {
			docName: next.docName,
			currency: next.currency,
			postingDate: next.postingDate,
			rateTouched,
		},
	};
}

/**
 * What the form must tell the user about the rate it just kept or replaced.
 *
 * Silence is the defect this whole rule exists to stop, and it has two faces.
 * Replacing a typed rate without saying so is how a contract rate becomes the
 * Central Bank's. Keeping one without saying so is subtler and now more likely:
 * a user who moves the posting date has every reason to assume the rate
 * followed it — that is what these forms did before — so the half that protects
 * their input is exactly the half they cannot see. On msa.erpstable.com 675
 * submitted purchase invoices carry a rate that is not the Central Bank rate for
 * their own posting date — 363 at rate 0 and 312 at a hardcoded 12 800, worth
 * hundreds of billions of so'm — and every one was booked by a form that
 * decided something about a rate and said nothing.
 *
 * Only a rate the user typed is worth a word. An untouched rate following its
 * date is the form working as advertised, and the AUTO badge and the live CBU
 * hint already show it; a toast on every date keystroke would train the user to
 * dismiss the one that matters.
 *
 * @param {{reason: string, hadTypedRate: boolean}} plan a `planRateRefresh()` result
 * @param {{typed: number, cbu: number}} rates the rate on screen before this
 *        transition, and the reference rate that came back for the new date
 * @returns {{kind: ?string, typed: number, cbu: number}} `kind` is `"kept"`,
 *          `"reset"`, or `null` when there is nothing worth interrupting for
 */
export function rateChangeNotice(plan, rates) {
	const typed = Number(rates?.typed) || 0;
	const cbu = Number(rates?.cbu) || 0;

	// No reference rate came back, so nothing was kept *over* anything and
	// nothing was replaced. Reporting a comparison against 0 would be a false
	// report of exactly the kind this function exists to prevent.
	if (!plan?.hadTypedRate || !(typed > 0) || !(cbu > 0)) return { kind: null, typed, cbu };

	// A different currency pair is a different rate question, so the typed rate
	// is genuinely gone. That is a destructive edit the user did not ask for
	// directly, and it is the one case here where they lose work.
	if (plan.reason === "currency") return { kind: "reset", typed, cbu };

	// The rate survived the date change. Worth a word only when it disagrees
	// with the new date's reference rate — if they match, the date would have
	// fetched what the user typed anyway and there is nothing to report.
	if (plan.reason === "date" && typed !== cbu) return { kind: "kept", typed, cbu };

	return { kind: null, typed, cbu };
}
