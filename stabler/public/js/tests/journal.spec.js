import { describe, expect, it } from "vitest";

import { computeBalancePlug, isDraftDirty, isRowOrphaned, postableRows, snapshotDraft } from "../composables/journal.js";

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

	// The worst version of the phantom-row bug: the residual was measured
	// against an amount the server never receives, and the answer was written
	// into a REAL line. Give the orphan an account an hour later and that
	// derived 700 goes to the ledger without anyone ever having agreed to it.
	it("measures the residual only over lines that will be posted", () => {
		const rows = [row({ debit: 500 }), row(), row({ account: "", debit: 200 })];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 1, field: "credit", value: 500 });
	});
});

describe("postableRows / isRowOrphaned — the lines the server will actually see", () => {
	// Both the submit filter and the backend (_clean_je_rows) drop a line whose
	// account is blank. The balance badge did not: it summed every row. A 200
	// typed on a line whose account was still empty made the form say
	// "Balanced" on a payload the server then rejected as 500 against 700 —
	// two figures that appear nowhere on the screen the user was looking at.
	it("leaves out a line whose account is still blank", () => {
		const rows = [row({ debit: 500 }), row({ account: "", debit: 200 })];
		expect(postableRows(rows)).toEqual([rows[0]]);
	});

	it("keeps a line that has an account but no amount yet — it is still part of the entry", () => {
		const rows = [row({ debit: 500 }), row()];
		expect(postableRows(rows)).toHaveLength(2);
	});

	// The badge going honest is only half of it. Without a mark on the row, the
	// user is told the entry does not balance and has no way to see which line
	// stopped counting.
	it("marks a line that carries an amount but no account", () => {
		expect(isRowOrphaned(row({ account: "", debit: 200 }))).toBe(true);
		expect(isRowOrphaned(row({ account: "", credit: 200 }))).toBe(true);
	});

	// A blank line is how every entry starts. Painting it red on open is how
	// people learn to read past the colour.
	it("does not mark a line the user has not started", () => {
		expect(isRowOrphaned(row({ account: "" }))).toBe(false);
		expect(isRowOrphaned(row({ account: "", debit: 0 }))).toBe(false);
	});
});

describe("snapshotDraft / isDraftDirty — the difference between a stray keypress and lost work", () => {
	// Escape used to close the edit pane outright. Half an opening balance —
	// a dozen lines typed by hand — went with it, silently, and there was no
	// undo. Dirtiness is the whole question the confirm prompt asks, so it is
	// the thing that has to be right.
	const draft = (over = {}) => ({
		posting_date: "2026-08-19", voucher_type: "Journal Entry", user_remark: "", cheque_no: "", cheque_date: "",
		accounts: [row({ account: "" }), row({ account: "" })],
		...over,
	});

	it("a form nobody has touched since it opened is not dirty", () => {
		const form = draft();
		expect(isDraftDirty(form, snapshotDraft(form))).toBe(false);
	});

	it("an amount the user typed makes it dirty — this is the work worth a prompt", () => {
		const form = draft();
		const pristine = snapshotDraft(form);
		form.accounts[0].debit = 5000000;
		expect(isDraftDirty(form, pristine)).toBe(true);
	});

	it("picking an account makes it dirty even before any amount is typed", () => {
		const form = draft();
		const pristine = snapshotDraft(form);
		form.accounts[0].account = "1110 - Kassa - MIK";
		expect(isDraftDirty(form, pristine)).toBe(true);
	});

	it("a changed header field is dirty too — the date is data, not chrome", () => {
		const form = draft();
		const pristine = snapshotDraft(form);
		form.posting_date = "2026-07-01";
		expect(isDraftDirty(form, pristine)).toBe(true);
	});

	// MoneyInput hands back null for an emptied field and the server hands back
	// 0. Treating those as different would put a "discard?" prompt in front of
	// a user who typed nothing at all, and a prompt that cries wolf gets
	// dismissed reflexively — which is how the real one gets dismissed too.
	it("null and 0 are the same emptiness", () => {
		const form = draft();
		const pristine = snapshotDraft(form);
		form.accounts[0].debit = 0;
		form.accounts[1].credit = null;
		expect(isDraftDirty(form, pristine)).toBe(false);
	});

	// party_name is a label the server sent for display; account_currency is
	// derived from the account. Neither is something the user typed, so
	// neither may raise a prompt on its own.
	it("labels the form filled in for itself are not the user's work", () => {
		const form = draft();
		const pristine = snapshotDraft(form);
		form.accounts[0].party_name = "Mikas Trading LLC";
		form.accounts[0].account_currency = "UZS";
		form.accounts[0]._auto = true;
		expect(isDraftDirty(form, pristine)).toBe(false);
	});

	it("an added row is dirty even while it is still empty — the user asked for it", () => {
		const form = draft();
		const pristine = snapshotDraft(form);
		form.accounts.push(row({ account: "" }));
		expect(isDraftDirty(form, pristine)).toBe(true);
	});

	// No snapshot means no edit pane was ever opened. Escape must stay plain
	// "go back" there; a prompt with nothing behind it is worse than none.
	it("without a snapshot nothing is dirty", () => {
		expect(isDraftDirty(draft(), null)).toBe(false);
		expect(isDraftDirty(draft(), undefined)).toBe(false);
	});
});
