import { describe, expect, it } from "vitest";

import { planRateRefresh, rateChangeNotice } from "../composables/exchangeRatePolicy.js";

// The state the form last showed the planner. `docName` is what tells an
// install apart from an edit; see the composable.
const seen = (over = {}) => ({
	docName: "ACC-PINV-0001",
	currency: "USD",
	postingDate: "2026-08-20",
	rateTouched: false,
	...over,
});
const next = (over = {}) => ({
	docName: "ACC-PINV-0001",
	currency: "USD",
	postingDate: "2026-08-20",
	editable: true,
	isForeign: true,
	...over,
});

describe("planRateRefresh — which rate a purchase invoice is booked at", () => {
	// The measured damage this exists to stop: on msa.erpstable.com 675
	// submitted purchase invoices carry a conversion_rate that is not the
	// Central Bank rate for their own posting date — 363 at rate 0 and 312 at a
	// hardcoded 12 800 — moving the UZS ledger by hundreds of billions of so'm.
	//
	// The form's own contribution to that: it fetched the rate for the new
	// posting date and then threw it away unless the field happened to be
	// empty (`if (!Number(form.value.conversion_rate))`). Backdate an invoice
	// that already has a rate and it keeps the rate of the date it no longer
	// has, silently, and ERPNext books whatever the form sends.
	it("refetches when the posting date moves, so the invoice carries its own date's rate", () => {
		const plan = planRateRefresh(seen(), next({ postingDate: "2026-07-01" }));
		expect(plan.refresh).toBe(true);
		expect(plan.seen.postingDate).toBe("2026-07-01");
	});

	// The other half, and it is not optional: blindly overwriting on every date
	// change wipes a rate the user deliberately typed — the contract rate, the
	// bank's actual rate. That is the same defect pointing the other way, and
	// it would be worse, because the user watched themselves enter the number.
	it("leaves a rate the user typed over alone when the date moves", () => {
		const plan = planRateRefresh(seen({ rateTouched: true }), next({ postingDate: "2026-07-01" }));
		expect(plan.refresh).toBe(false);
		expect(plan.seen.rateTouched).toBe(true);
	});

	// A different currency is a different rate question: the number the user
	// typed was a USD rate, and it says nothing about EUR. Same reset the
	// journal drawer does when the account changes.
	it("refetches on a currency change and drops the typed-over mark with it", () => {
		const plan = planRateRefresh(seen({ rateTouched: true }), next({ currency: "EUR" }));
		expect(plan.refresh).toBe(true);
		expect(plan.seen.rateTouched).toBe(false);
	});

	// Installing a document is not the user moving anything. The watcher fires
	// on load because `load()` assigns currency and posting_date at once; if
	// that counted as a date change, opening a saved draft would rewrite the
	// rate it was saved with before the user had touched the screen.
	it("adopts a freshly loaded document instead of refetching over its stored rate", () => {
		const plan = planRateRefresh(
			{ docName: null, currency: "", postingDate: "", rateTouched: false },
			next({ postingDate: "2026-01-15" })
		);
		expect(plan.refresh).toBe(false);
		expect(plan.seen).toEqual({
			docName: "ACC-PINV-0001",
			currency: "USD",
			postingDate: "2026-01-15",
			rateTouched: false,
		});
	});

	// Navigating from one invoice to another is an install too.
	it("adopts when a different document takes the screen", () => {
		const plan = planRateRefresh(seen(), next({ docName: "ACC-PINV-0002", postingDate: "2026-02-02" }));
		expect(plan.refresh).toBe(false);
	});

	// A submitted invoice is a posted ledger entry. Nothing the form does may
	// rewrite its rate — this is the guard that keeps a refresh legitimate only
	// on a draft the user is editing.
	it("never refetches over a document that is not editable", () => {
		expect(planRateRefresh(seen(), next({ editable: false, postingDate: "2026-07-01" })).refresh).toBe(false);
	});

	// A base-currency invoice has no conversion rate to fetch; conversion_rate
	// is not even sent (`toPayload` omits it unless isForeign).
	it("does not refetch for a base-currency invoice", () => {
		expect(planRateRefresh(seen(), next({ isForeign: false, postingDate: "2026-07-01" })).refresh).toBe(false);
	});

	// The watcher fires on any write to either field, including ones that
	// change nothing. Re-fetching then would undo a typed rate via a no-op.
	it("does nothing when neither the date nor the currency actually moved", () => {
		expect(planRateRefresh(seen(), next()).refresh).toBe(false);
	});

	// Even when it refuses to refresh, the planner must advance what it has
	// seen — otherwise the next real edit is compared against a stale date and
	// the refresh fires a transition late.
	it("advances the seen state even when it refuses to refresh", () => {
		const plan = planRateRefresh(seen({ rateTouched: true }), next({ postingDate: "2026-07-01" }));
		expect(plan.seen.postingDate).toBe("2026-07-01");
	});
});

// --------------------------------------------------------------------------
// The transfer form asked the same question and answered it the other way.
// --------------------------------------------------------------------------
// `Transfers.vue` cleared its own `rateManuallyEdited` flag inside the
// posting-date watcher and then refetched, so moving the date *discarded* a
// rate the user had typed. Its comment argued that was deliberate — "the rate
// is a function of the posting date, so a date change re-anchors it".
//
// That premise is weakest in precisely the form that claimed it. A transfer's
// two legs are observed bank movements: 5 000 USD left one account and
// 63 500 000 UZS arrived in another, at the bank's rate, not the Central
// Bank's. The rate is the residual of two facts, not an estimate the CBU can
// correct. And the form already agreed — `openEditFromDetail()` loads a
// historical transfer by deriving the rate *from* the stored amounts under a
// `hydrating` guard, expressly so the live CBU rate cannot overwrite them.
// Only the date watcher disagreed, with the rest of its own file.
//
// It is also the form where a silent substitution costs the most. The transfer
// posts `to_amount` as authoritative and sends `to_amount / from_amount` as the
// rate, and the reciprocal binding re-derives `to_amount` whenever the rate is
// replaced. So discarding a typed rate there does not merely misstate a
// valuation — it silently changes how much money lands in the destination
// account.
describe("planRateRefresh — the same rule, asked by the transfer form", () => {
	const pair = (over = {}) => ({
		docName: null,
		currency: "USD→UZS",
		postingDate: "2026-08-20",
		rateTouched: false,
		...over,
	});
	const pairNext = (over = {}) => ({
		docName: null,
		currency: "USD→UZS",
		postingDate: "2026-08-20",
		editable: true,
		isForeign: true,
		...over,
	});

	// The protect half. The bank gave 12 700; the CBU says 12 950 for that day.
	// Correcting a mistyped posting date must not overwrite what the statement
	// says actually happened.
	it("keeps a typed transfer rate when only the posting date moves", () => {
		const plan = planRateRefresh(pair({ rateTouched: true }), pairNext({ postingDate: "2026-08-15" }));
		expect(plan.refresh).toBe(false);
		expect(plan.seen.rateTouched).toBe(true);
		expect(plan.reason).toBe("date");
	});

	// The refresh half, and it is not optional: this is the behaviour the old
	// date watcher got right. An untouched rate is showing the CBU rate for a
	// date that is no longer the posting date, and must follow it.
	it("still refetches an untouched transfer rate when the posting date moves", () => {
		const plan = planRateRefresh(pair(), pairNext({ postingDate: "2026-08-15" }));
		expect(plan.refresh).toBe(true);
		expect(plan.reason).toBe("date");
	});

	// A different account pair is a different rate question — the same reason
	// the journal clears its mark on an account change and the invoice on a
	// currency change. A USD→UZS rate says nothing about EUR→UZS.
	it("discards a typed rate when the account pair changes", () => {
		const plan = planRateRefresh(pair({ rateTouched: true }), pairNext({ currency: "EUR→UZS" }));
		expect(plan.refresh).toBe(true);
		expect(plan.seen.rateTouched).toBe(false);
		expect(plan.reason).toBe("currency");
	});

	// `hadTypedRate` is what the notice hangs on, so it must not survive a
	// document swap: the previous document's mark says nothing about the one
	// now on screen, and reporting it would announce a loss that never happened.
	it("does not carry a previous document's typed mark onto a newly installed one", () => {
		const plan = planRateRefresh(pair({ rateTouched: true, docName: "ACC-JV-0001" }), pairNext());
		expect(plan.reason).toBe("installed");
		expect(plan.hadTypedRate).toBe(false);
	});
});

// --------------------------------------------------------------------------
// Whatever the rule does, the user has to be able to see that it happened.
// --------------------------------------------------------------------------
// This is the defect class the whole exercise is about: 675 submitted purchase
// invoices on msa.erpstable.com carry a rate that is not the Central Bank rate
// for their own posting date — 363 at rate 0 and 312 at a hardcoded 12 800 —
// hundreds of billions of so'm in the wrong direction. Every one of them was
// booked by a form that changed a rate, or refused to, without saying so.
//
// Keeping a typed rate silently is the same failure as replacing one silently.
// A user who moves the posting date has every reason to assume the rate
// followed it — that is what the form did until this change — so the half that
// protects their input is exactly the half they cannot see.
describe("rateChangeNotice — the form has to say what it did to the rate", () => {
	const plan = (over = {}) => ({ reason: "date", hadTypedRate: true, ...over });

	it("reports a typed rate that was kept, and what the date's CBU rate was", () => {
		const notice = rateChangeNotice(plan(), { typed: 12700, cbu: 12950 });
		expect(notice.kind).toBe("kept");
		expect(notice.typed).toBe(12700);
		expect(notice.cbu).toBe(12950);
	});

	it("reports a typed rate that was discarded by an account-pair change", () => {
		const notice = rateChangeNotice(plan({ reason: "currency" }), { typed: 12700, cbu: 13600 });
		expect(notice.kind).toBe("reset");
		expect(notice.typed).toBe(12700);
	});

	// An AUTO rate that follows the date is the form working as advertised —
	// the AUTO badge and the live CBU hint already say so. A toast on every
	// date keystroke would train the user to dismiss the one that matters.
	it("says nothing when the rate was never typed", () => {
		expect(rateChangeNotice(plan({ hadTypedRate: false }), { typed: 12950, cbu: 12950 }).kind).toBe(null);
	});

	// Nothing diverged, so there is nothing to warn about: the rate the user
	// typed is the rate the new date would have fetched anyway.
	it("says nothing when the typed rate already equals the new date's CBU rate", () => {
		expect(rateChangeNotice(plan(), { typed: 12950, cbu: 12950 }).kind).toBe(null);
	});

	// No rate came back, so nothing was kept *over* anything and nothing was
	// replaced — announcing a comparison against 0 would be a false report.
	it("says nothing when no CBU rate came back to compare against", () => {
		expect(rateChangeNotice(plan(), { typed: 12700, cbu: 0 }).kind).toBe(null);
	});

	it("says nothing when a document was just installed on screen", () => {
		expect(rateChangeNotice(plan({ reason: "installed", hadTypedRate: false }), { typed: 1, cbu: 2 }).kind).toBe(null);
	});
});
