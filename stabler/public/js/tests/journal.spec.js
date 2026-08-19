import { describe, expect, it } from "vitest";

import { computeBalancePlug } from "../composables/journal.js";

// Every line is in the company's base currency unless a test says otherwise.
const rateOf = (r) => Number(r.exchange_rate) || 1;
const row = (over = {}) => ({ account: "1110 - Kassa - MIK", debit: null, credit: null, exchange_rate: 1, _auto: false, ...over });

describe("computeBalancePlug — the counter-line a journal entry can work out for itself", () => {
	// The complaint this answers: entering an opening balance meant typing the
	// same number twice, on both sides, for every account. The debit is the
	// judgement call; the credit that squares it is arithmetic, and arithmetic
	// is not the accountant's job.
	it("fills the empty counter-line so the entry balances", () => {
		const rows = [row({ debit: 5000000 }), row()];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 1, field: "credit", value: 5000000 });
	});

	it("plugs the debit side when the credits are heavier", () => {
		const rows = [row({ credit: 5000000 }), row()];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 1, field: "debit", value: 5000000 });
	});

	// The line that makes this safe to run on every keystroke. A number the user
	// typed is data; overwriting it would make the form fight its own operator.
	it("never overwrites an amount the user typed", () => {
		const rows = [row({ debit: 5000000 }), row({ credit: 3000000 })];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toBeNull();
	});

	// ...but a number this function put there is not data, it is a derivation,
	// so it stays live. Without this the plug would freeze at its first value
	// and silently go stale as the user keeps typing.
	it("keeps recomputing the line it filled itself, in place", () => {
		const rows = [row({ debit: 6000000 }), row({ credit: 4000000, _auto: true })];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 1, field: "credit", value: 6000000 });
	});

	it("leaves the row being edited alone — it is the one the user is holding", () => {
		const rows = [row({ debit: 5000000 }), row()];
		expect(computeBalancePlug(rows, { editedIdx: 1, rateOf })).toBeNull();
	});

	// Idempotence: the caller runs this on every keystroke, so "no change" has
	// to be distinguishable from "write the same thing again" or the loop never
	// visibly settles.
	it("reports nothing to do when the line it filled is already correct", () => {
		const rows = [row({ debit: 5000000 }), row({ credit: 5000000, _auto: true })];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toBeNull();
	});

	it("ignores a row with no account chosen — there is nowhere to post it", () => {
		const rows = [row({ debit: 5000000 }), row({ account: "" })];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toBeNull();
	});

	// Multi-currency: the residual is measured in the base currency, but the
	// field the user sees is in the account's own currency. Writing the base
	// figure into a USD line would silently overstate it by the rate.
	it("converts the base-currency residual through the target line's own rate", () => {
		const rows = [row({ debit: 12_000_000 }), row({ exchange_rate: 12000 })];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 1, field: "credit", value: 1000 });
	});

	it("weighs a foreign source line by its rate before working out the residual", () => {
		const rows = [row({ debit: 1000, exchange_rate: 12000 }), row()];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 1, field: "credit", value: 12_000_000 });
	});

	it("fills the first empty line when several are open", () => {
		const rows = [row({ debit: 5000000 }), row(), row()];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })?.index).toBe(1);
	});

	// UZS has no fractional unit, so a plug of 3333333.3333 is not a rounding
	// nicety — it is a number the ledger cannot hold.
	it("rounds the plug to the TARGET line's precision, not the company's", () => {
		const rows = [row({ debit: 10_000_000 / 3 }), row()];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf, fractionDigitsOf: () => 0 })?.value).toBe(3333333);
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf, fractionDigitsOf: () => 2 })?.value).toBe(3333333.33);
	});

	it("returns null for a single-row entry — there is no counter-line", () => {
		expect(computeBalancePlug([row({ debit: 5000000 })], { editedIdx: 0, rateOf })).toBeNull();
	});
});
