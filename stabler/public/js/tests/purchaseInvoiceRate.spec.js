import { describe, expect, it } from "vitest";

import { planRateRefresh } from "../composables/purchaseInvoiceRate.js";

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
