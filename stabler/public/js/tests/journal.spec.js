import { describe, expect, it } from "vitest";

import {
	balanceCacheKey,
	balanceTolerance,
	computeBalancePlug,
	describePlugResidual,
	isDraftDirty,
	isPostingFrozen,
	journalFreezeDate,
	isRowOrphaned,
	postableRows,
	ratesToRefresh,
	snapshotDraft,
} from "../composables/journal.js";

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

	// The residual is measured in base currency, so only a base-currency line
	// can hold it exactly. Put 1 234 567 so'm on a USD line at 12 335 and the
	// closest USD can come is 100.09 — the entry is then out by ~43 so'm and
	// Save is off permanently, because one US cent moves 123 so'm and no
	// amount of typing lands on the figure. Given an open so'm line, the plug
	// belongs there and the residual is zero.
	it("prefers an open base-currency line — a foreign one cannot hold the residual exactly", () => {
		const rows = [
			row({ debit: 1234567 }),
			row({ account: "1210 - Bank USD - MIK", account_currency: "USD", exchange_rate: 12335 }),
			row({ account: "1110 - Kassa - MIK" }),
		];
		expect(computeBalancePlug(rows, { editedIdx: 0, rateOf })).toEqual({ index: 2, field: "credit", value: 1234567 });
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

	// `editedIdx: -1` means "no line is off-limits" — the change was not an
	// amount somebody typed. Deleting a line and correcting an exchange rate
	// both come through that way, and both used to skip this function
	// entirely, leaving the plug frozen at a figure nothing derived any more.
	it("re-derives the standing plug when the change was not a typed amount", () => {
		const rows = [row({ debit: 6000000 }), row({ credit: 8000000, _auto: true })];
		expect(computeBalancePlug(rows, { editedIdx: -1, rateOf })).toEqual({ index: 1, field: "credit", value: 6000000 });
	});

	// The line the plug was balancing is gone, so the plug is a derivation of
	// nothing. Left standing it stops being a derivation and becomes a figure
	// the user never typed and cannot account for — which is precisely how a
	// deleted line used to leave 5 000 000 sitting on the screen.
	it("clears the plug it wrote once the lines it balanced are gone", () => {
		const rows = [row({ credit: 5000000, _auto: true }), row()];
		expect(computeBalancePlug(rows, { editedIdx: -1, rateOf })).toEqual({ index: 0, field: "credit", value: null });
	});

	it("never clears an amount the user typed, however the entry now adds up", () => {
		const rows = [row({ credit: 5000000, _auto: false }), row()];
		expect(computeBalancePlug(rows, { editedIdx: 1, rateOf })).toBeNull();
	});

	// Idempotence again: the caller runs this on every keystroke, so an empty
	// plug seat must report nothing to do or the loop never visibly settles.
	it("has nothing to clear on an empty plug line", () => {
		const rows = [row({ _auto: true }), row()];
		expect(computeBalancePlug(rows, { editedIdx: -1, rateOf })).toBeNull();
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

describe("balanceTolerance — one threshold, not three", () => {
	// Three gates decided "balanced" and none of them agreed. The form said
	// `Math.abs(diff) < 1` base unit; api/money.py said 1.0 for a
	// multi-currency entry and 0.01 otherwise; the gate that actually decides
	// whether the document saves is fx_balance's residual_tolerance(). On a
	// 2-decimal base currency the form was the LOOSEST of the three, so
	// anything between 0.04 and 0.99 went green here and then fell over inside
	// ERPNext with an untranslated "Total Debit must be equal to Total Credit".
	// This function is the JS mirror of stabler/api/_fx_residual.py.
	it("allows one smallest unit per line, plus a cushion", () => {
		expect(balanceTolerance(2, 2)).toBe(0.04);
		expect(balanceTolerance(5, 2)).toBe(0.07);
	});

	// The direction that locks people out rather than letting them through: on
	// a UZS-base company the smallest unit is a whole so'm, so a tolerance of
	// 0.01 is a hundred times tighter than the ledger's and rejects entries
	// the ledger would have taken.
	it("scales to a whole-unit base currency instead of assuming cents", () => {
		expect(balanceTolerance(2, 0)).toBe(4);
		expect(balanceTolerance(5, 0)).toBe(7);
	});

	it("survives a line count it cannot use", () => {
		expect(balanceTolerance(0, 2)).toBe(0.02);
		expect(balanceTolerance(-1, 2)).toBe(0.02);
	});
});

describe("describePlugResidual — why a form that filled the line in will not let you save", () => {
	// "The form writes a number for you, then locks you out because of that
	// number." Without this line the screen shows a red Δ and no reason for
	// it, and the entry genuinely cannot be balanced by typing.
	it("names the rounding a foreign plug line cannot avoid", () => {
		const rows = [
			row({ account: "5010 - Ijara - MIK", debit: 1234567 }),
			row({ account: "1210 - Bank USD - MIK", account_currency: "USD", exchange_rate: 12335, credit: 100.09, _auto: true }),
		];
		const note = describePlugResidual(rows, { rateOf, tolerance: 4 });
		expect(note).toMatchObject({ index: 1, amount: 100.09, currency: "USD" });
		expect(Math.round(note.base)).toBe(1234610);
		expect(note.counterBase).toBe(1234567);
	});

	// A base-currency plug is exact by construction, so there is nothing to
	// explain and a standing explanation would be noise.
	it("says nothing when the plug sits on a base-currency line", () => {
		const rows = [row({ debit: 5000000 }), row({ credit: 5000000, _auto: true })];
		expect(describePlugResidual(rows, { rateOf, tolerance: 4 })).toBeNull();
	});

	it("says nothing while the entry is inside the ledger's tolerance", () => {
		const rows = [
			row({ debit: 1234567 }),
			row({ account: "1210 - Bank USD - MIK", account_currency: "USD", exchange_rate: 12335, credit: 100.09, _auto: true }),
		];
		expect(describePlugResidual(rows, { rateOf, tolerance: 100 })).toBeNull();
	});

	// An imbalance the user typed is not a rounding story; saying "rounding"
	// about a plain typo sends them looking in the wrong place.
	it("says nothing about an imbalance the user typed", () => {
		const rows = [
			row({ debit: 1234567 }),
			row({ account: "1210 - Bank USD - MIK", account_currency: "USD", exchange_rate: 12335, credit: 50 }),
		];
		expect(describePlugResidual(rows, { rateOf, tolerance: 4 })).toBeNull();
	});
});

describe("what the posting date owns", () => {
	const isForeign = (r) => !!r.account_currency && r.account_currency !== "UZS";

	// The rate was fetched for form.posting_date but only ever from
	// onAccountChange, and nothing watched the date. "New entry → pick the USD
	// account → set the date to last month" therefore booked last month's
	// entry at today's rate, and ERPNext keeps a rate the form sends
	// (journal_entry.py only fills in its own when the line has none), so the
	// wrong rate went to the ledger silently. A percent or two of FX straight
	// into the trial balance, with nothing on screen to notice.
	it("refetches the rate for a foreign line when the date moves", () => {
		const rows = [row({ account_currency: "UZS" }), row({ account_currency: "USD", exchange_rate: 12335 })];
		expect(ratesToRefresh(rows, isForeign)).toEqual([rows[1]]);
	});

	// …but a rate the user typed is a decision — the bank's rate, the
	// contract's rate — and moving the date must not quietly undo it.
	it("leaves a rate the user corrected by hand alone", () => {
		const rows = [row({ account_currency: "USD", exchange_rate: 12500, _rateTouched: true })];
		expect(ratesToRefresh(rows, isForeign)).toEqual([]);
	});

	// The hint asks the server for the balance `as_of` the posting date, but
	// cached it under the account name alone. Backdate the entry and the first
	// date's figure stayed on screen, labelled as if it were the new one —
	// and "what is in the till" is exactly the decision that hint is for.
	it("keys a balance to its date, not just its account", () => {
		expect(balanceCacheKey("1110 - Kassa - MIK", "2026-07-31")).not.toBe(balanceCacheKey("1110 - Kassa - MIK", "2026-08-19"));
		expect(balanceCacheKey("1110 - Kassa - MIK", "2026-07-31")).toBe(balanceCacheKey("1110 - Kassa - MIK", "2026-07-31"));
	});
});

describe("journalFreezeDate — which freeze actually closes a journal entry", () => {
	// get_backdating_status reports two earliest-open dates, one for stock and
	// one for accounting, and the money-page banner takes the later of the two
	// because it speaks for every document type. A Journal Entry writes no
	// stock ledger, and _assert_posting_date_open on the server checks
	// acc_frozen_upto alone for exactly that reason.
	//
	// While this only painted a banner, taking the later date was merely
	// imprecise. It now disables Save, so a tenant whose stock period is closed
	// further forward than their accounting period would be locked out of dates
	// the ledger accepts without complaint — the form refusing what the server
	// would have taken.
	it("gates on the accounting freeze, not the later of the two", () => {
		const status = { active: true, stock_earliest_date: "2026-09-01", acc_earliest_date: "2026-08-01" };
		expect(journalFreezeDate(status)).toBe("2026-08-01");
	});

	it("is open when only stock is frozen — a journal entry does not touch stock", () => {
		expect(journalFreezeDate({ active: true, stock_earliest_date: "2026-09-01", acc_earliest_date: null })).toBeNull();
	});

	// `active` already folds in the exemption roles the server checks, so the
	// person whose job is correcting a closed period keeps their only tool.
	it("is open for a user the server treats as exempt", () => {
		expect(journalFreezeDate({ active: false, acc_earliest_date: "2026-08-01" })).toBeNull();
	});

	it("is open when the status never arrived", () => {
		expect(journalFreezeDate(null)).toBeNull();
	});
});

describe("isPostingFrozen — the date the ledger will not take", () => {
	// The warning band was computed and then ignored: Save did not consult it,
	// and neither did create/update_journal_entry. So the draft really saved,
	// and the refusal arrived at Submit instead, in ERPNext's untranslated
	// words — leaving a record that is in the list but not in the ledger, which
	// is where "I entered it, why is it not in the trial balance" comes from.
	it("refuses a date inside the frozen period", () => {
		expect(isPostingFrozen("2026-07-15", "2026-08-01")).toBe(true);
	});

	// The band says "frozen BEFORE {date}", so the boundary day itself is open.
	// Getting this off by one closes a period a day early, every period.
	it("allows the freeze date itself, and everything after it", () => {
		expect(isPostingFrozen("2026-08-01", "2026-08-01")).toBe(false);
		expect(isPostingFrozen("2026-08-19", "2026-08-01")).toBe(false);
	});

	it("is not frozen when no window is set, or no date is chosen", () => {
		expect(isPostingFrozen("2026-07-15", null)).toBe(false);
		expect(isPostingFrozen("", "2026-08-01")).toBe(false);
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
