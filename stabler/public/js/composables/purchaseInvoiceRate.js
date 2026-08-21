// When a purchase invoice's exchange rate should follow its posting date.
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
